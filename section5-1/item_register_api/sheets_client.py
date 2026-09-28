"""「商品管理」シートへの新規行追加ロジック。

既存の運用(カスタムメニュー「新規行を追加」)や section5-1/mercari_to_sheets.py と同じ考え方で、
ヘッダー直下(2行目)に行を挿入し、既存の2行目(挿入後は3行目になる)から書式・入力規則・
チェックボックス設定を引き継ぐ。inheritFromBefore=false で行を挿入すると、新しい行は
「挿入位置の後ろの行」の書式をそのまま引き継ぐため、ヘッダー行ではなく既存データ行の
書式が新規行に適用される。
"""

import json
import re
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from . import config

# 商品管理シートの列 (1始まり)。A=1, B=2, ... Z=26, AA=27, ...
COL_MANAGEMENT_NUMBER = 1  # A: 管理番号
COL_TITLE = 2  # B: 商品名
COL_GENRE = 3  # C: ジャンル
COL_STYLE = 4  # D: 系統
COL_BRAND = 5  # E: ブランド
COL_PRICE = 6  # F: 出品価格
COL_CONDITION = 7  # G: 商品の状態
COL_SEASON = 13  # M: 季節
COL_QUANTITY = 14  # N: 出品点数
COL_LISTED_DATE = 15  # O: 出品日
COL_SALES_CHANNEL = 18  # R: 販売場所
COL_MEMO = 38  # AL: メモ(保管場所)
COL_MERCARI_ACCOUNT = 45  # AS: メルカリアカウント
COL_URL = 46  # AT: メルカリ商品URL/画像
ROW_WIDTH = COL_URL

# 既存2行目に入っている数式をそのまま流用する(行番号だけを挿入先の行番号に差し替える)。
# mercari_to_sheets.py の FORMULA_TEMPLATES と同一(2026-09時点でシートから実測して確認済み)。
FORMULA_TEMPLATES = {
    11: '=IF(I{r}="","",I{r}+IF(J{r}="",0,J{r}))',  # K: 仕入れ合計コスト
    21: '=IF(Q{r}="","",IFS(R{r}="ラクマ","",R{r}="ヤフマ",ROUND(Q{r}*0.05),R{r}="メルカリ",ROUND(Q{r}*0.1),TRUE,ROUND(Q{r}*0.1)))',  # U: 販売手数料
    22: '=IF(Q{r}="","",Q{r}-IF(K{r}="",0,K{r})-IF(U{r}="",0,U{r})-IF(S{r}="",0,S{r})-IF(T{r}="",0,T{r}))',  # V: 利益
    23: '=IF(OR(Q{r}="",Q{r}=0),"",IFERROR(ROUND(V{r}/Q{r}*100,1),""))',  # W: 利益率
    24: '=IF(OR(K{r}="",K{r}=0),"",IFERROR(ROUND(V{r}/K{r}*100,1),""))',  # X: 仕入れ利益率
    25: '=IF(OR(P{r}="",O{r}=""),"",P{r}-O{r})',  # Y: リードタイム
    26: '=IF(OR(O{r}="",P{r}<>""),"",TODAY()-O{r})',  # Z: 在庫日数
    27: '=IF(O{r}="","",IF(P{r}="","在庫中","済"))',  # AA: 売却フラグ
    32: '=IF(OR(AD{r}="",AE{r}="",AE{r}=0),"",IFERROR(ROUND(AD{r}/AE{r}*100,1),""))',  # AF: 閲覧率
    37: '=IF(OR(AJ{r}="",P{r}=""),"",AJ{r}-P{r})',  # AK: 決済リードタイム
}

MANAGEMENT_NUMBER_RE = re.compile(r"^(\d{4})-(\d{3})$")


def _build_credentials() -> Credentials:
    if config.GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON:
        info = json.loads(config.GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON)
        return Credentials.from_service_account_info(info, scopes=config.SCOPES)
    return Credentials.from_service_account_file(config.SERVICE_ACCOUNT_FILE, scopes=config.SCOPES)


class SheetsClient:
    """gspreadクライアントとワークシートの取得をまとめて管理する。"""

    def __init__(self):
        creds = _build_credentials()
        self._client = gspread.authorize(creds)
        self._spreadsheet = self._client.open_by_key(config.SPREADSHEET_ID)
        self._sheets_api = build("sheets", "v4", credentials=creds, cache_discovery=False)

    @property
    def item_sheet(self):
        return self._spreadsheet.worksheet(config.SHEET_NAME)

    def get_row_data_validations(self, worksheet, row_number: int) -> dict:
        """指定行の各列に設定されている入力規則の種類(ONE_OF_LIST/BOOLEAN等)を取得する。
        行挿入によって既存の入力規則が消えていないかを検証するために使う。
        戻り値は {列番号(1始まり): 種類の文字列 または None} の辞書。
        """
        res = (
            self._sheets_api.spreadsheets()
            .get(
                spreadsheetId=config.SPREADSHEET_ID,
                ranges=[f"{config.SHEET_NAME}!A{row_number}:AT{row_number}"],
                includeGridData=True,
                fields="sheets.data.rowData.values.dataValidation.condition.type",
            )
            .execute()
        )
        row_data = res["sheets"][0]["data"][0]["rowData"][0].get("values", [])
        result = {}
        for i, cell in enumerate(row_data, start=1):
            validation = cell.get("dataValidation", {}).get("condition", {}).get("type")
            result[i] = validation
        return result

    def get_request_log_sheet(self):
        """request_idの二重登録防止用ログシートを取得する。無ければ作成する。"""
        try:
            return self._spreadsheet.worksheet(config.REQUEST_LOG_SHEET_NAME)
        except gspread.WorksheetNotFound:
            ws = self._spreadsheet.add_worksheet(title=config.REQUEST_LOG_SHEET_NAME, rows=1000, cols=6)
            ws.update(
                range_name="A1:F1",
                values=[["request_id", "management_number", "storage_location", "description", "created_at_jst", "status"]],
                value_input_option="USER_ENTERED",
            )
            try:
                ws.hide()
            except Exception:
                pass
            return ws


def get_max_management_number(worksheet, yymm: str) -> int:
    """A列(管理番号)から、同じYYMMで始まる管理番号のうち最大の連番(NNN)を返す。無ければ0。"""
    values = worksheet.col_values(COL_MANAGEMENT_NUMBER)
    max_seq = 0
    for v in values[1:]:  # 1行目はヘッダー
        m = MANAGEMENT_NUMBER_RE.match(v.strip())
        if m and m.group(1) == yymm:
            max_seq = max(max_seq, int(m.group(2)))
    return max_seq


def build_management_number(yymm: str, seq: int) -> str:
    return f"{yymm}-{seq:03d}"


def build_item_row(
    *,
    row_number: int,
    management_number: str,
    title: str,
    genre: str,
    style: str,
    brand: Optional[str],
    sale_price: int,
    condition: str,
    season: str,
    listed_date: str,
    storage_location: str,
    mercari_account: Optional[str],
) -> list:
    """新規2行目に書き込む46列(A〜AT)分の配列を作る。
    書き込み対象外の列は空文字にする(既存の書式・入力規則・チェックボックスは
    行挿入時にinheritFromBeforeで引き継がれるため、値を空にしても壊れない)。
    """
    row = [""] * ROW_WIDTH
    row[COL_MANAGEMENT_NUMBER - 1] = management_number
    row[COL_TITLE - 1] = title
    row[COL_GENRE - 1] = genre
    row[COL_STYLE - 1] = style
    row[COL_BRAND - 1] = brand or ""
    row[COL_PRICE - 1] = sale_price
    row[COL_CONDITION - 1] = condition
    row[COL_SEASON - 1] = season
    row[COL_QUANTITY - 1] = 1
    row[COL_LISTED_DATE - 1] = listed_date
    row[COL_SALES_CHANNEL - 1] = "メルカリ"
    row[COL_MEMO - 1] = storage_location
    row[COL_MERCARI_ACCOUNT - 1] = mercari_account or ""
    for col, template in FORMULA_TEMPLATES.items():
        row[col - 1] = template.format(r=row_number)
    return row


def insert_item_row(worksheet, row: list) -> None:
    """ヘッダー直下(2行目)に新規行を挿入する。既存行は1つ下へ押し出される。
    inherit_from_before=False: 新規行は挿入位置の「後ろ」= 既存の2行目(押し出されて3行目になる)から
    書式・入力規則・チェックボックス設定を引き継ぐ(ヘッダー行からは引き継がない)。
    """
    worksheet.insert_rows([row], row=2, value_input_option="USER_ENTERED", inherit_from_before=False)


def read_written_row_unformatted(worksheet, row_number: int) -> list:
    """検証用に、書き込んだ行の値を書式なし(数値は数値のまま)で取得する。"""
    return worksheet.get(
        f"A{row_number}:AT{row_number}",
        value_render_option="UNFORMATTED_VALUE",
    )[0]


def read_written_row_formulas(worksheet, row_number: int) -> list:
    """検証用に、数式そのもの(=から始まる文字列)を取得する。"""
    return worksheet.get(
        f"A{row_number}:AT{row_number}",
        value_render_option="FORMULA",
    )[0]
