"""「Todo」シート・「設定」シートへのアクセスと、旧形式(A〜F列)からの移行。

Google Sheets自体を唯一のデータストアとして扱う。認証はADC(Cloud Run実行SA)で、
スコープはspreadsheetsのみ。アクセスできるのはSAに共有されたシートだけになる。

既存データ保護の方針(移行処理 migrate_todo_sheet):
- 既存のデータ行には一切書き込まない。変更するのは1行目のG〜K列(空欄)へのヘッダー追記のみ。
- 追記の前に同じスプレッドシート内へバックアップタブを複製し、内容が元と完全一致することを
  確認できた場合だけ追記に進む。どこかで失敗・不一致があればその時点で中止し、例外を送出する。
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

import google.auth
import gspread

from . import config

COL_ID = 1  # A
COL_TITLE = 2  # B
COL_CONTENT = 3  # C
COL_DUE_DATE = 4  # D
COL_CREATED_AT = 5  # E
COL_UPDATED_AT = 6  # F
COL_IMPORTANCE = 7  # G
COL_STATUS = 8  # H
COL_COMPLETED_AT = 9  # I
COL_NOTIFIED_DAY_BEFORE = 10  # J: 前日通知済みの期日
COL_NOTIFIED_SAME_DAY = 11  # K: 当日通知済みの期日
ROW_WIDTH = COL_NOTIFIED_SAME_DAY

HEADER_ROW_V1 = ["ID", "タイトル", "内容", "期日", "登録日時", "更新日時"]
HEADER_ROW = HEADER_ROW_V1 + ["重要度", "状態", "完了日時", "前日通知済み期日", "当日通知済み期日"]
V1_WIDTH = len(HEADER_ROW_V1)

SETTINGS_HEADER = ["項目", "値", "説明"]
SETTINGS_DEFAULT_ROWS = [
    ["day_before_enabled", "TRUE", "前日通知(TRUE/FALSE)"],
    ["day_before_hour", "20", "前日通知の時刻(0〜23時)"],
    ["same_day_enabled", "TRUE", "当日通知(TRUE/FALSE)"],
    ["same_day_hour", "8", "当日通知の時刻(0〜23時)"],
]


class SheetsConfigError(Exception):
    """シートの設定・構成が想定と異なる(ID未設定、ヘッダー不一致、移行の中止など)。"""


def col_letter(col: int) -> str:
    return chr(ord("A") + col - 1)


def _trim(row: list) -> list:
    row = [str(c) for c in row]
    while row and not row[-1].strip():
        row.pop()
    return row


def _backup_title(now: datetime.datetime) -> str:
    return f"{config.TODO_SHEET_NAME}_backup_{now.strftime('%Y%m%d_%H%M%S')}"


def migrate_todo_sheet(spreadsheet, ws, now: datetime.datetime) -> str:
    """Todoシートを現行形式にそろえる。戻り値は実施内容("ok" / "initialized" / "migrated")。"""
    values = ws.get_all_values()
    header = _trim(values[0]) if values else []
    data_rows = values[1:]

    if header == HEADER_ROW:
        return "ok"

    if not header:
        if any(any(str(c).strip() for c in r) for r in data_rows):
            raise SheetsConfigError("ヘッダー行が空なのにデータ行があるため中止しました")
        ws.update(values=[HEADER_ROW], range_name=f"A1:{col_letter(ROW_WIDTH)}1", value_input_option="RAW")
        return "initialized"

    if header != HEADER_ROW_V1:
        raise SheetsConfigError("シートのヘッダー行が想定と異なります")

    # --- 旧形式(A〜F列) → 現行形式(A〜K列) ---
    for r in values:
        if any(str(c).strip() for c in r[V1_WIDTH:]):
            raise SheetsConfigError("G列以降に既存の値があるため移行を中止しました")

    backup = spreadsheet.duplicate_sheet(ws.id, new_sheet_name=_backup_title(now))
    if [_trim(r) for r in backup.get_all_values()] != [_trim(r) for r in values]:
        raise SheetsConfigError("バックアップの内容が元データと一致しないため移行を中止しました")

    ws.update(
        values=[HEADER_ROW[V1_WIDTH:]],
        range_name=f"{col_letter(V1_WIDTH + 1)}1:{col_letter(ROW_WIDTH)}1",
        value_input_option="RAW",
    )
    if _trim(ws.row_values(1)) != HEADER_ROW:
        raise SheetsConfigError("ヘッダー追記後の確認に失敗しました")
    return "migrated"


def ensure_settings_sheet(spreadsheet):
    """「設定」シートが無ければ初期値つきで作成する。既存の場合は内容を変更しない。"""
    try:
        return spreadsheet.worksheet(config.SETTINGS_SHEET_NAME)
    except gspread.WorksheetNotFound:
        pass
    ws = spreadsheet.add_worksheet(title=config.SETTINGS_SHEET_NAME, rows=20, cols=3)
    rows = [SETTINGS_HEADER] + SETTINGS_DEFAULT_ROWS
    ws.update(values=rows, range_name=f"A1:C{len(rows)}", value_input_option="RAW")
    return ws


class SheetsClient:
    def __init__(self) -> None:
        self._worksheet = None
        self._settings_worksheet = None
        self.last_migration_result = ""

    def _prepare(self) -> None:
        if not config.TODO_SPREADSHEET_ID:
            raise SheetsConfigError("TODO_SPREADSHEET_ID が設定されていません")
        creds, _ = google.auth.default(scopes=config.SCOPES)
        spreadsheet = gspread.authorize(creds).open_by_key(config.TODO_SPREADSHEET_ID)
        ws = spreadsheet.worksheet(config.TODO_SHEET_NAME)
        now = datetime.datetime.now(ZoneInfo(config.TIMEZONE_NAME))
        self.last_migration_result = migrate_todo_sheet(spreadsheet, ws, now)
        self._settings_worksheet = ensure_settings_sheet(spreadsheet)
        self._worksheet = ws

    @property
    def worksheet(self):
        if self._worksheet is None:
            self._prepare()
        return self._worksheet

    @property
    def settings_worksheet(self):
        if self._settings_worksheet is None:
            self._prepare()
        return self._settings_worksheet
