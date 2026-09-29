"""登録処理の本体ロジック(解析・重複チェック・採番・Drive保存・Sheets書き込み)。

item_register_api/service.py と同じ設計方針:
- 「登録する」実行時にのみ書き込みが発生する(解析だけでは何も保存しない)。
- request_idによる冪等性(同じrequest_idの再送は新規登録せず既存結果を返す)。
- 読み取り→採番→書き込みの一連をスレッドロックで直列化し、Cloud Runへの
  デプロイ時は --concurrency=1 --max-instances=1 を推奨する(競合を避けるため)。
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import threading
import uuid
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from . import drive_client, gemini_client, sheets_client
from .choices import ACCOUNT_CATEGORIES, BUSINESS_SEGMENTS
from .config import TIMEZONE_NAME
from .models import (
    AnalyzeResponse,
    DuplicateCandidate,
    ExpenseFields,
    ExpenseListItem,
    RegisterBlockedResponse,
    RegisterResult,
)

JST = ZoneInfo(TIMEZONE_NAME)
logger = logging.getLogger("expense_manager")
# ルートロガーの既定レベル(WARNING)だとinfoログがCloud Loggingに出ないため、
# このロガー専用にINFO以上を確実に出力する設定を行う(gemini_client.pyと同様の方針。
# 秘密情報・APIキー・OAuthトークン・画像そのものは一切含めない)。
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False

EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "application/pdf": ".pdf",
}


class DuplicateBlockedError(Exception):
    """重複によりブロックされたことを表す。呼び出し側はRegisterBlockedResponseに変換する。"""

    def __init__(self, response: RegisterBlockedResponse):
        super().__init__(response.message)
        self.response = response


class DriveSaveError(Exception):
    """Google Driveへの証憑画像保存が失敗したことを表す。メッセージはユーザー画面に
    そのまま表示して問題ない、安全な日本語文言のみを保持する。Drive APIの生のエラー・
    内部ID・OAuth情報は一切含めない(それらは呼び出し時点でログにのみ記録する)。
    """

    def __init__(
        self,
        user_message: str = "証憑画像の保存に失敗しました。しばらくしてからもう一度お試しください。",
    ):
        super().__init__(user_message)


class SheetsRegistrationError(Exception):
    """Google Sheetsへの読み書きが失敗したことを表す。メッセージはユーザー画面に
    そのまま表示して問題ない、安全な日本語文言のみを保持する。Sheets APIの生のエラー・
    内部IDは一切含めない(それらは呼び出し時点でログにのみ記録する)。
    """

    def __init__(
        self,
        user_message: str = "経費データの登録に失敗しました。しばらくしてからもう一度お試しください。",
    ):
        super().__init__(user_message)


def _extension_for(content_type: str) -> str:
    ext = EXTENSION_BY_CONTENT_TYPE.get(content_type)
    if ext:
        return ext
    return mimetypes.guess_extension(content_type) or ""


def _yymm_from_transaction_date(transaction_date: Optional[str], now: datetime) -> tuple[str, list[str]]:
    """取引日からYYMMを決める。パースできなければ現在時刻(JST)基準にフォールバックし、注記を返す。"""
    notes: list[str] = []
    if transaction_date:
        try:
            d = datetime.strptime(transaction_date, "%Y-%m-%d")
            return d.strftime("%y%m"), notes
        except ValueError:
            notes.append(f"取引日「{transaction_date}」を解釈できなかったため、登録日時点の年月で管理番号を発行しました")
    else:
        notes.append("取引日が未入力のため、登録日時点の年月で管理番号を発行しました")
    return now.strftime("%y%m"), notes


def _normalize_category(value: Optional[str]) -> str:
    if value in ACCOUNT_CATEGORIES:
        return value
    return "判定不能"


def _normalize_segment(value: Optional[str]) -> str:
    if value in BUSINESS_SEGMENTS:
        return value
    return "未判定"


class ExpenseService:
    def __init__(self, client: Optional[sheets_client.SheetsClient] = None, drive: Optional[drive_client.DriveClient] = None):
        # Sheets/DriveはGemini解析では不要なため、ここでは構築せず遅延初期化する
        # (下記の_client/_driveプロパティ参照)。これにより、Sheets/Driveが利用
        # できない状態でも /api/analyze のGemini解析自体は実行できる。
        self._client_override = client
        self._drive_override = drive
        self._client_lazy: Optional[sheets_client.SheetsClient] = None
        self._drive_lazy: Optional[drive_client.DriveClient] = None
        self._lock = threading.Lock()

    @property
    def _client(self) -> sheets_client.SheetsClient:
        if self._client_override is not None:
            return self._client_override
        if self._client_lazy is None:
            self._client_lazy = sheets_client.SheetsClient()
        return self._client_lazy

    @property
    def _drive(self) -> drive_client.DriveClient:
        if self._drive_override is not None:
            return self._drive_override
        if self._drive_lazy is None:
            self._drive_lazy = drive_client.DriveClient()
        return self._drive_lazy

    # --- 解析(何も保存しない。Sheets/Driveには一切触れない) ---

    def analyze(self, image_bytes: bytes, content_type: str) -> AnalyzeResponse:
        raw = gemini_client.analyze_receipt_image(image_bytes, content_type)

        notes: list[str] = []
        for key in ("transaction_date", "payee", "amount"):
            if raw.get(key) in (None, ""):
                notes.append(f"{key} を画像から読み取れませんでした")

        fields = ExpenseFields(
            transaction_date=raw.get("transaction_date"),
            payee=raw.get("payee"),
            amount=raw.get("amount"),
            tax_amount=raw.get("tax_amount"),
            tax_rate=raw.get("tax_rate"),
            tax_rate_10_base=raw.get("tax_rate_10_base"),
            tax_rate_10_amount=raw.get("tax_rate_10_amount"),
            tax_rate_8_base=raw.get("tax_rate_8_base"),
            tax_rate_8_amount=raw.get("tax_rate_8_amount"),
            invoice_registration_number=raw.get("invoice_registration_number"),
            description=raw.get("description"),
            payment_method=raw.get("payment_method"),
            account_category=_normalize_category(raw.get("account_category")),
            business_segment=_normalize_segment(raw.get("business_segment")),
            memo=raw.get("memo"),
        )
        request_id = f"expense-{uuid.uuid4().hex}"
        return AnalyzeResponse(request_id=request_id, fields=fields, notes=notes)

    # --- 登録(重複チェック→採番→Drive保存→Sheets書き込み) ---

    def register(
        self,
        *,
        request_id: str,
        fields: ExpenseFields,
        image_bytes: bytes,
        content_type: str,
        override_hash_duplicate: bool = False,
        override_possible_duplicate: bool = False,
    ) -> RegisterResult:
        image_hash = hashlib.sha256(image_bytes).hexdigest()

        with self._lock:
            # --- Sheets読み取り(重複チェック・採番) ---
            # gspread/Sheets APIの生のエラーをユーザーへ見せないよう、ここで
            # SheetsRegistrationErrorへ変換する。DuplicateBlockedErrorは
            # エラーではなく正常な業務フロー(要override確認)なのでそのまま伝播させる。
            try:
                sheet = self._client.expense_sheet
                rows = sheets_client.get_all_rows(sheet)

                # 1. request_id一致 -> 冪等に既存結果を返す(新規登録しない)。
                existing = sheets_client.find_by_request_id(rows, request_id)
                if existing is not None:
                    return RegisterResult(
                        already_registered=True,
                        management_number=existing.management_number,
                        drive_file_url=existing.drive_file_url,
                        notes=["同じrequest_idで既に登録済みのため、既存の登録結果を返しました"],
                    )

                # 2. 画像ハッシュ一致 -> 原則ブロック(明示的なoverrideがあれば続行)。
                hash_dup = sheets_client.find_by_image_hash(rows, image_hash)
                if hash_dup is not None and not override_hash_duplicate:
                    raise DuplicateBlockedError(
                        RegisterBlockedResponse(
                            reason="duplicate_hash",
                            message=f"同一画像が既に管理番号{hash_dup.management_number}として登録されています",
                            duplicate_candidates=[
                                DuplicateCandidate(
                                    management_number=hash_dup.management_number,
                                    transaction_date=hash_dup.transaction_date,
                                    payee=hash_dup.payee,
                                    amount=hash_dup.amount or 0,
                                    account_category=hash_dup.account_category,
                                    business_segment=hash_dup.business_segment,
                                )
                            ],
                        )
                    )

                # 3〜5. 取引日+金額を軸にした重複候補チェック(インボイス登録番号一致・
                # 正規化後の支払先一致・取引日+金額のみの「弱い」一致のいずれも対象)。
                # 自動拒否はせず、警告として既存候補を提示し、明示的なoverrideで続行できる。
                if fields.transaction_date and fields.amount is not None:
                    candidates = sheets_client.find_possible_duplicates(
                        rows,
                        fields.transaction_date,
                        fields.amount,
                        payee=fields.payee,
                        invoice_registration_number=fields.invoice_registration_number,
                    )
                    if candidates and not override_possible_duplicate:
                        raise DuplicateBlockedError(
                            RegisterBlockedResponse(
                                reason="possible_duplicate",
                                message="同じ経費の可能性がある登録が見つかりました",
                                duplicate_candidates=[
                                    DuplicateCandidate(
                                        management_number=c.management_number,
                                        transaction_date=c.transaction_date,
                                        payee=c.payee,
                                        amount=c.amount or 0,
                                        account_category=c.account_category,
                                        business_segment=c.business_segment,
                                    )
                                    for c in candidates
                                ],
                            )
                        )

                now = datetime.now(JST)
                yymm, date_notes = _yymm_from_transaction_date(fields.transaction_date, now)

                max_seq = sheets_client.get_max_management_number(sheet, yymm)
                management_number = sheets_client.build_management_number(yymm, max_seq + 1)
                # 書き込み直前に再確認する(item_register_apiと同じ二段階チェック)。
                recheck_max = sheets_client.get_max_management_number(sheet, yymm)
                if recheck_max >= max_seq + 1:
                    management_number = sheets_client.build_management_number(yymm, recheck_max + 1)
            except DuplicateBlockedError:
                raise
            except Exception as e:
                logger.error(
                    "Sheets読み取り処理に失敗しました: exception_type=%s, request_id=%s",
                    type(e).__name__,
                    request_id,
                )
                raise SheetsRegistrationError() from e

            # --- Drive保存 ---
            # Drive APIの生のエラー(HttpError等)をユーザーへ見せないよう、
            # DriveAuthExpiredError(再認可が必要、既に安全なメッセージを持つ)以外は
            # DriveSaveErrorへ変換する。
            year = f"20{yymm[:2]}"
            month = yymm[2:]
            extension = _extension_for(content_type)
            try:
                _file_id, drive_url = self._drive.upload_receipt_image(
                    year=year,
                    month=month,
                    management_number=management_number,
                    file_bytes=image_bytes,
                    content_type=content_type,
                    extension=extension,
                )
            except drive_client.DriveAuthExpiredError:
                raise
            except Exception as e:
                logger.error(
                    "Drive保存に失敗しました: exception_type=%s, management_number=%s",
                    type(e).__name__,
                    management_number,
                )
                raise DriveSaveError() from e

            row = [
                management_number,
                fields.transaction_date or "",
                fields.payee or "",
                fields.amount if fields.amount is not None else "",
                fields.tax_amount if fields.tax_amount is not None else "",
                fields.tax_rate or "",
                fields.invoice_registration_number or "",
                fields.description or "",
                _normalize_category(fields.account_category),
                _normalize_segment(fields.business_segment),
                fields.memo or "",
                fields.payment_method or "",
                drive_url,
                now.isoformat(),
                request_id,
                image_hash,
                fields.tax_rate_10_base if fields.tax_rate_10_base is not None else "",
                fields.tax_rate_10_amount if fields.tax_rate_10_amount is not None else "",
                fields.tax_rate_8_base if fields.tax_rate_8_base is not None else "",
                fields.tax_rate_8_amount if fields.tax_rate_8_amount is not None else "",
            ]
            try:
                sheets_client.append_expense_row(sheet, row)
            except Exception as sheets_error:
                # Drive保存は既に成功しているが、Sheets書き込みに失敗した。
                # 「Drive上にだけ証憑ファイルが残る部分登録」を防ぐため、
                # アップロード済みのDriveファイルを削除してロールバックする。
                try:
                    self._drive.delete_file(_file_id)
                    logger.error(
                        "Sheets書き込み失敗のためDriveファイルをロールバック削除しました: "
                        "file_id=%s, management_number=%s, exception_type=%s",
                        _file_id,
                        management_number,
                        type(sheets_error).__name__,
                    )
                except Exception as rollback_error:
                    # ロールバック自体が失敗した場合は、手動対応が必要な旨をログに残す。
                    # 元のsheets_errorを握りつぶさず、安全なメッセージへ変換した上で伝播させる。
                    logger.error(
                        "Sheets書き込み失敗後、Driveファイルのロールバック削除にも失敗しました。"
                        "手動削除が必要です: file_id=%s, management_number=%s, "
                        "sheets_exception_type=%s, rollback_exception_type=%s",
                        _file_id,
                        management_number,
                        type(sheets_error).__name__,
                        type(rollback_error).__name__,
                    )
                raise SheetsRegistrationError() from sheets_error

            return RegisterResult(
                already_registered=False,
                management_number=management_number,
                drive_file_url=drive_url,
                notes=date_notes,
            )

    # --- 一覧取得・CSV出力(共通のフィルタロジック) ---

    def _filtered_rows(
        self, *, year: Optional[str] = None, month: Optional[str] = None, business_segment: Optional[str] = None
    ) -> list[sheets_client.ExistingRow]:
        sheet = self._client.expense_sheet
        rows = sheets_client.get_all_rows(sheet)
        result = []
        for r in rows:
            if year and not r.transaction_date.startswith(year):
                continue
            if month and r.transaction_date[5:7] != month:
                continue
            if business_segment and r.business_segment != business_segment:
                continue
            result.append(r)
        return result

    def list_expenses(
        self, *, year: Optional[str] = None, month: Optional[str] = None, business_segment: Optional[str] = None
    ) -> list[ExpenseListItem]:
        rows = self._filtered_rows(year=year, month=month, business_segment=business_segment)
        return [
            ExpenseListItem(
                management_number=r.management_number,
                transaction_date=r.transaction_date,
                payee=r.payee,
                amount=r.amount,
                account_category=r.account_category,
                business_segment=r.business_segment,
                drive_file_url=r.drive_file_url,
            )
            for r in rows
        ]

    def list_raw_rows(
        self, *, year: Optional[str] = None, month: Optional[str] = None, business_segment: Optional[str] = None
    ) -> list[dict]:
        """CSV出力用。フィルタ適用後の全列(A〜P)を辞書のリストで返す。"""
        sheet = self._client.expense_sheet
        values = sheet.get_all_values()
        results = []
        for raw in values[1:]:
            padded = list(raw) + [""] * (sheets_client.ROW_WIDTH - len(raw))
            row_dict = dict(zip(sheets_client.HEADER_ROW, padded))
            if year and not row_dict["取引日"].startswith(year):
                continue
            if month and row_dict["取引日"][5:7] != month:
                continue
            if business_segment and row_dict["事業区分"] != business_segment:
                continue
            results.append(row_dict)
        return results
