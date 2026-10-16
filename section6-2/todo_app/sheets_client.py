"""「Todo」シートへのアクセス。

Google Sheets自体を唯一のデータストアとして扱う。認証はADC(Cloud Run実行SA)で、
スコープはspreadsheetsのみ。アクセスできるのはSAに共有されたシートだけになる。
"""

from __future__ import annotations

import google.auth
import gspread

from . import config

COL_ID = 1  # A
COL_TITLE = 2  # B
COL_CONTENT = 3  # C
COL_DUE_DATE = 4  # D
COL_CREATED_AT = 5  # E
COL_UPDATED_AT = 6  # F
ROW_WIDTH = COL_UPDATED_AT

HEADER_ROW = ["ID", "タイトル", "内容", "期日", "登録日時", "更新日時"]


class SheetsConfigError(Exception):
    """シートの設定・構成が想定と異なる(ID未設定、ヘッダー不一致など)。"""


class SheetsClient:
    def __init__(self) -> None:
        self._worksheet: gspread.Worksheet | None = None

    @property
    def worksheet(self) -> gspread.Worksheet:
        if self._worksheet is None:
            if not config.TODO_SPREADSHEET_ID:
                raise SheetsConfigError("TODO_SPREADSHEET_ID が設定されていません")
            creds, _ = google.auth.default(scopes=config.SCOPES)
            client = gspread.authorize(creds)
            ws = client.open_by_key(config.TODO_SPREADSHEET_ID).worksheet(config.TODO_SHEET_NAME)
            ensure_header(ws)
            self._worksheet = ws
        return self._worksheet


def ensure_header(ws) -> None:
    """1行目が空ならヘッダーを書き込む。別の内容があれば既存データ保護のため上書きせずエラーにする。"""
    first_row = ws.row_values(1)
    if not any(cell.strip() for cell in first_row):
        ws.update(values=[HEADER_ROW], range_name="A1:F1", value_input_option="RAW")
        return
    if first_row[:ROW_WIDTH] != HEADER_ROW:
        raise SheetsConfigError("シートのヘッダー行が想定と異なります")
