"""実際のGoogle Sheets APIを呼ばずにTodoServiceを検証するための簡易フェイク。"""

from todo_app import sheets_client


class FakeWorksheet:
    def __init__(self, header: list | None = None):
        self.rows = [list(header if header is not None else sheets_client.HEADER_ROW)]
        self.calls = []  # (メソッド名, value_input_option) の記録

    def row_values(self, row_number: int) -> list:
        idx = row_number - 1
        return list(self.rows[idx]) if idx < len(self.rows) else []

    def get_all_values(self) -> list:
        return [list(r) for r in self.rows]

    def append_row(self, values, value_input_option=None, insert_data_option=None, table_range=None):
        self.calls.append(("append_row", value_input_option))
        self.rows.append([str(v) for v in values])

    def update(self, values=None, range_name=None, value_input_option=None):
        self.calls.append(("update", value_input_option))
        start = range_name.split(":")[0]
        row_idx = int("".join(ch for ch in start if ch.isdigit())) - 1
        while len(self.rows) <= row_idx:
            self.rows.append([""] * sheets_client.ROW_WIDTH)
        self.rows[row_idx] = [str(v) for v in values[0]]


class FakeSheetsClient:
    def __init__(self, worksheet: FakeWorksheet | None = None):
        self.worksheet = worksheet or FakeWorksheet()


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
