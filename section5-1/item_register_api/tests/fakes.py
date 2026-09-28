"""実際のGoogle Sheets APIを呼ばずにservice.pyのロジックを検証するための簡易フェイク。"""

from item_register_api import request_log, sheets_client

HEADER = [""] * sheets_client.ROW_WIDTH

# 実シートで確認済みの入力規則(検証ロジックが正しい列を見ているかのテストに使う)。
COLUMN_VALIDATIONS = {
    sheets_client.COL_GENRE: "ONE_OF_LIST",
    sheets_client.COL_STYLE: "ONE_OF_LIST",
    sheets_client.COL_CONDITION: "ONE_OF_LIST",
    sheets_client.COL_SEASON: "ONE_OF_LIST",
    sheets_client.COL_SALES_CHANNEL: "ONE_OF_LIST",
    sheets_client.COL_MERCARI_ACCOUNT: "ONE_OF_LIST",
}


class FakeWorksheet:
    def __init__(self, header: list):
        self.rows = [list(header)]  # rows[0] = header

    def col_values(self, col: int) -> list:
        idx = col - 1
        return [str(r[idx]) if idx < len(r) and r[idx] != "" else "" for r in self.rows]

    def insert_rows(self, values, row, value_input_option=None, inherit_from_before=False):
        for i, v in enumerate(values):
            padded = list(v) + [""] * (sheets_client.ROW_WIDTH - len(v))
            self.rows.insert(row - 1 + i, padded)

    def get(self, range_name: str, value_render_option=None):
        row_number = int("".join(ch for ch in range_name.split(":")[0] if ch.isdigit()))
        return [self.rows[row_number - 1]]

    def append_row(self, values, value_input_option=None):
        self.rows.append(list(values) + [""] * (6 - len(values)))

    def get_all_values(self):
        return [list(r) for r in self.rows]

    def update(self, range_name=None, values=None, value_input_option=None):
        self.rows[0] = values[0]

    def hide(self):
        pass


class FakeSheetsClient:
    def __init__(self):
        self._item_sheet = FakeWorksheet(HEADER)
        self._log_sheet = FakeWorksheet(
            ["request_id", "management_number", "storage_location", "description", "created_at_jst", "status"]
        )

    @property
    def item_sheet(self):
        return self._item_sheet

    def get_request_log_sheet(self):
        return self._log_sheet

    def get_row_data_validations(self, worksheet, row_number: int) -> dict:
        return dict(COLUMN_VALIDATIONS)
