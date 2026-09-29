"""「経費」シートへの読み書きと、管理番号採番・重複チェックのためのスキャン処理。

item_register_api/sheets_client.py と同じ考え方: 別データベースを持たず、
Google Sheets自体を唯一のデータストアとして扱う。
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from . import config

# 「経費」シートの列(1始まり)。
COL_MANAGEMENT_NUMBER = 1  # A
COL_TRANSACTION_DATE = 2  # B
COL_PAYEE = 3  # C
COL_AMOUNT = 4  # D
COL_TAX_AMOUNT = 5  # E
COL_TAX_RATE = 6  # F
COL_INVOICE_NUMBER = 7  # G
COL_DESCRIPTION = 8  # H
COL_ACCOUNT_CATEGORY = 9  # I
COL_BUSINESS_SEGMENT = 10  # J
COL_MEMO = 11  # K
COL_PAYMENT_METHOD = 12  # L
COL_DRIVE_URL = 13  # M
COL_REGISTERED_AT = 14  # N
COL_REQUEST_ID = 15  # O
COL_IMAGE_HASH = 16  # P
# 8%・10%混在税率対応で追加(既存A〜P列は変更せず、末尾に追加する)。
COL_TAX_RATE_10_BASE = 17  # Q: 10%対象額
COL_TAX_RATE_10_AMOUNT = 18  # R: 10%消費税額
COL_TAX_RATE_8_BASE = 19  # S: 8%対象額
COL_TAX_RATE_8_AMOUNT = 20  # T: 8%消費税額
ROW_WIDTH = COL_TAX_RATE_8_AMOUNT

HEADER_ROW = [
    "管理番号",
    "取引日",
    "支払先",
    "金額",
    "消費税額",
    "税率",
    "インボイス登録番号",
    "内容・品目",
    "勘定科目",
    "事業区分",
    "摘要",
    "支払方法",
    "証憑画像URL",
    "登録日時",
    "request_id",
    "画像ハッシュ",
    "10%対象額",
    "10%消費税額",
    "8%対象額",
    "8%消費税額",
]

MANAGEMENT_NUMBER_RE = re.compile(r"^EX(\d{4})(\d{3})$")


def _build_credentials() -> Credentials:
    if config.GOOGLE_SERVICE_ACCOUNT_JSON:
        info = json.loads(config.GOOGLE_SERVICE_ACCOUNT_JSON)
        return Credentials.from_service_account_info(info, scopes=config.SCOPES)
    return Credentials.from_service_account_file(config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=config.SCOPES)


class SheetsClient:
    """gspreadクライアントとワークシート取得をまとめて管理する。"""

    def __init__(self):
        creds = _build_credentials()
        self._client = gspread.authorize(creds)
        self._spreadsheet = self._client.open_by_key(config.EXPENSE_SPREADSHEET_ID)
        self._sheets_api = build("sheets", "v4", credentials=creds, cache_discovery=False)

    @property
    def expense_sheet(self):
        return self._spreadsheet.worksheet(config.EXPENSE_SHEET_NAME)


def build_management_number(yymm: str, seq: int) -> str:
    return f"EX{yymm}{seq:03d}"


def get_max_management_number(worksheet, yymm: str) -> int:
    """A列(管理番号)から、同じYYMMで始まる管理番号のうち最大の連番(NNN)を返す。無ければ0。"""
    values = worksheet.col_values(COL_MANAGEMENT_NUMBER)
    max_seq = 0
    for v in values[1:]:  # 1行目はヘッダー
        m = MANAGEMENT_NUMBER_RE.match(v.strip())
        if m and m.group(1) == yymm:
            max_seq = max(max_seq, int(m.group(2)))
    return max_seq


@dataclass
class ExistingRow:
    row_number: int  # 1始まり(ヘッダーを含む実際のシート行番号)
    management_number: str
    transaction_date: str
    payee: str
    amount: Optional[int]
    account_category: str
    business_segment: str
    drive_file_url: str
    request_id: str
    image_hash: str
    invoice_registration_number: str


def _parse_amount(raw: str) -> Optional[int]:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def get_all_rows(worksheet) -> list[ExistingRow]:
    """ヘッダーを除く全行を取得する。重複チェック・一覧表示の両方から使う共通関数。"""
    values = worksheet.get_all_values()
    rows: list[ExistingRow] = []
    for i, raw in enumerate(values[1:], start=2):  # 実際の行番号は2から
        padded = list(raw) + [""] * (ROW_WIDTH - len(raw))
        rows.append(
            ExistingRow(
                row_number=i,
                management_number=padded[COL_MANAGEMENT_NUMBER - 1],
                transaction_date=padded[COL_TRANSACTION_DATE - 1],
                payee=padded[COL_PAYEE - 1],
                amount=_parse_amount(padded[COL_AMOUNT - 1]),
                account_category=padded[COL_ACCOUNT_CATEGORY - 1],
                business_segment=padded[COL_BUSINESS_SEGMENT - 1],
                drive_file_url=padded[COL_DRIVE_URL - 1],
                request_id=padded[COL_REQUEST_ID - 1],
                image_hash=padded[COL_IMAGE_HASH - 1],
                invoice_registration_number=padded[COL_INVOICE_NUMBER - 1],
            )
        )
    return rows


def find_by_request_id(rows: list[ExistingRow], request_id: str) -> Optional[ExistingRow]:
    for row in rows:
        if row.request_id == request_id:
            return row
    return None


def find_by_image_hash(rows: list[ExistingRow], image_hash: str) -> Optional[ExistingRow]:
    for row in rows:
        if row.image_hash == image_hash:
            return row
    return None


_CORPORATE_ENTITY_PATTERN = re.compile(
    r"株式会社|有限会社|合同会社|合資会社|合名会社|\(株\)|\(有\)|\(同\)|（株）|（有）|（同）"
)


def normalize_payee(payee: Optional[str]) -> str:
    """支払先文字列を、AI解析結果の表記揺れを吸収した形へ正規化する
    (重複候補判定でのみ使用し、保存データ自体は変更しない)。

    行う正規化:
    - 全角/半角の統一(Unicode NFKC。全角スペース→半角スペースも含む)
    - 「株式会社」「(株)」「（株）」等の法人格表記の除去
    - 前後・連続する空白の圧縮
    - 大文字/小文字の統一(casefold)
    - 空白区切りで同じ単語が連続して重複している場合の除去
      (例: "はま寿司 はま寿司 板橋徳丸店" -> "はま寿司 板橋徳丸店")
    - 最終的に空白そのものを除去して比較する(半角・全角スペース除去)
    """
    if not payee:
        return ""
    s = unicodedata.normalize("NFKC", payee)
    s = _CORPORATE_ENTITY_PATTERN.sub("", s)
    s = s.casefold()
    s = re.sub(r"\s+", " ", s).strip()
    tokens = s.split(" ") if s else []
    deduped: list[str] = []
    for token in tokens:
        if not deduped or deduped[-1] != token:
            deduped.append(token)
    return "".join(deduped)


def find_possible_duplicates(
    rows: list[ExistingRow],
    transaction_date: str,
    amount: int,
    payee: Optional[str] = None,
    invoice_registration_number: Optional[str] = None,
) -> list[ExistingRow]:
    """取引日+金額が一致する既存行を「重複候補」として返す(自動拒否はしない、
    呼び出し側でユーザーへの警告・確認に使う)。

    優先順位:
    1. 取引日+金額+インボイス登録番号一致(双方に値がある場合) — 最も強い根拠
    2. 取引日+金額+支払先(正規化後)一致 — AI解析の表記揺れを吸収した根拠
    3. 取引日+金額のみの一致 — 「弱い重複候補」。支払先・インボイス番号が
       一致しなくても検出する(自動拒否はせず、確認を求めるだけ)

    上記1・2はいずれも取引日+金額の一致が前提のため、検出される行の集合は
    「取引日+金額一致」の集合と一致する。1・2の判定は、候補が複数ある場合に
    より確からしい候補を先頭に表示するための並び替えに使う。
    """
    normalized_target_payee = normalize_payee(payee) if payee else ""

    def match_strength(r: ExistingRow) -> int:
        if (
            invoice_registration_number
            and r.invoice_registration_number
            and r.invoice_registration_number == invoice_registration_number
        ):
            return 2  # 取引日+金額+インボイス登録番号一致
        if payee and normalize_payee(r.payee) == normalized_target_payee:
            return 1  # 取引日+金額+支払先(正規化後)一致
        return 0  # 取引日+金額のみ一致(弱い候補)

    candidates = [r for r in rows if r.transaction_date == transaction_date and r.amount == amount]
    candidates.sort(key=match_strength, reverse=True)
    return candidates


def append_expense_row(worksheet, row: list) -> None:
    worksheet.append_row(row, value_input_option="USER_ENTERED")


def ensure_header(worksheet) -> None:
    """1行目がヘッダーになっていなければ書き込む(新規シート作成直後の初期化用)。
    範囲はHEADER_ROWの長さから動的に決定する(列追加時に手動修正しなくて済むように)。
    """
    first_row = worksheet.row_values(1)
    if first_row != HEADER_ROW:
        end_cell = gspread.utils.rowcol_to_a1(1, len(HEADER_ROW))
        worksheet.update(range_name=f"A1:{end_cell}", values=[HEADER_ROW], value_input_option="USER_ENTERED")
