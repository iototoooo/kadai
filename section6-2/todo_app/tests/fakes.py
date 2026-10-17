"""実際のGoogle Sheets API・LINE APIを呼ばずに検証するための簡易フェイク。"""

import re

import gspread

from todo_app import sheets_client

_CELL_RE = re.compile(r"^([A-Z]+)(\d+)$")


def _parse_cell(cell: str) -> tuple[int, int]:
    m = _CELL_RE.match(cell)
    col = 0
    for ch in m.group(1):
        col = col * 26 + (ord(ch) - ord("A") + 1)
    return int(m.group(2)) - 1, col - 1  # 0始まり (row, col)


class FakeWorksheet:
    _next_id = 1

    def __init__(self, header: list | None = None, title: str = "Todo"):
        self.rows = [list(header if header is not None else sheets_client.HEADER_ROW)]
        self.title = title
        self.id = FakeWorksheet._next_id
        FakeWorksheet._next_id += 1
        self.calls = []  # (メソッド名, value_input_option, range) の記録
        self.fail_update_with: Exception | None = None

    # --- 読み取り ---
    def row_values(self, row_number: int) -> list:
        idx = row_number - 1
        return list(self.rows[idx]) if idx < len(self.rows) else []

    def get_all_values(self) -> list:
        width = max((len(r) for r in self.rows), default=0)
        return [list(r) + [""] * (width - len(r)) for r in self.rows]

    # --- 書き込み(セル単位で指定範囲だけを書き換える) ---
    def _write(self, range_name: str, values):
        start = range_name.split(":")[0]
        r0, c0 = _parse_cell(start)
        for dr, row_values in enumerate(values):
            r = r0 + dr
            while len(self.rows) <= r:
                self.rows.append([])
            row = self.rows[r]
            for dc, v in enumerate(row_values):
                c = c0 + dc
                while len(row) <= c:
                    row.append("")
                row[c] = str(v)

    def append_row(self, values, value_input_option=None, insert_data_option=None, table_range=None):
        self.calls.append(("append_row", value_input_option, None))
        self.rows.append([str(v) for v in values])

    def update(self, values=None, range_name=None, value_input_option=None):
        if self.fail_update_with is not None:
            raise self.fail_update_with
        self.calls.append(("update", value_input_option, range_name))
        self._write(range_name, values)

    def batch_update(self, data, value_input_option=None):
        if self.fail_update_with is not None:
            raise self.fail_update_with
        for item in data:
            self.calls.append(("batch_update", value_input_option, item["range"]))
            self._write(item["range"], item["values"])


class FakeSpreadsheet:
    def __init__(self, todo_ws: FakeWorksheet):
        self.sheets = {todo_ws.title: todo_ws}
        self.corrupt_duplicate = False  # バックアップ内容の不一致を注入する口
        self.fail_duplicate_with: Exception | None = None

    def worksheet(self, title):
        if title not in self.sheets:
            raise gspread.WorksheetNotFound(title)
        return self.sheets[title]

    def duplicate_sheet(self, source_sheet_id, new_sheet_name=None, **_):
        if self.fail_duplicate_with is not None:
            raise self.fail_duplicate_with
        src = next(ws for ws in self.sheets.values() if ws.id == source_sheet_id)
        copy = FakeWorksheet(header=[], title=new_sheet_name)
        copy.rows = [list(r) for r in src.rows]
        if self.corrupt_duplicate:
            copy.rows = copy.rows[:-1]
        self.sheets[new_sheet_name] = copy
        return copy

    def add_worksheet(self, title, rows, cols, index=None):
        ws = FakeWorksheet(header=[], title=title)
        ws.rows = []
        self.sheets[title] = ws
        return ws


class FakeSheetsClient:
    def __init__(self, worksheet: FakeWorksheet | None = None, settings_worksheet: FakeWorksheet | None = None):
        self.worksheet = worksheet or FakeWorksheet()
        if settings_worksheet is None:
            settings_worksheet = FakeWorksheet(header=[], title="設定")
            settings_worksheet.rows = [sheets_client.SETTINGS_HEADER] + [list(r) for r in sheets_client.SETTINGS_DEFAULT_ROWS]
        self.settings_worksheet = settings_worksheet
        self.last_migration_result = "ok"


class FakeClock:
    def __init__(self, start: str = "2026-10-16 10:00:00"):
        self.value = start

    def __call__(self) -> str:
        return self.value


class SequentialIds:
    def __init__(self):
        self.n = 0

    def __call__(self) -> str:
        self.n += 1
        return f"{self.n:032x}"


class FakeLineClient:
    def __init__(self):
        self.sent = []  # (text, retry_key)
        self.fail_times = 0  # 先頭からこの回数だけ失敗させる
        self.fail_with: Exception | None = None
        self.result = "sent"
        self.attempts = 0

    def push_text(self, text, retry_key):
        self.attempts += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise self.fail_with or RuntimeError("line down")
        self.sent.append((text, retry_key))
        return self.result
