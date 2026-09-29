"""実際のGoogle Sheets/Drive/Gemini APIを呼ばずにexpense_service.pyのロジックを検証するための簡易フェイク。"""

from expense_manager import sheets_client


class FakeWorksheet:
    def __init__(self, header: list):
        self.rows = [list(header)]  # rows[0] = header
        self.fail_append_with: Exception | None = None  # テストからappend_row失敗を注入する口
        self.fail_get_all_values_with: Exception | None = None  # get_all_values失敗を注入する口

    def col_values(self, col: int) -> list:
        idx = col - 1
        return [str(r[idx]) if idx < len(r) and r[idx] != "" else "" for r in self.rows]

    def get_all_values(self) -> list:
        if self.fail_get_all_values_with is not None:
            raise self.fail_get_all_values_with
        return [list(r) for r in self.rows]

    def append_row(self, values, value_input_option=None):
        if self.fail_append_with is not None:
            raise self.fail_append_with
        padded = list(values) + [""] * (sheets_client.ROW_WIDTH - len(values))
        self.rows.append(padded)

    def row_values(self, row_number: int) -> list:
        idx = row_number - 1
        return list(self.rows[idx]) if idx < len(self.rows) else []

    def update(self, range_name=None, values=None, value_input_option=None):
        self.rows[0] = values[0]


class FakeSheetsClient:
    def __init__(self):
        self._expense_sheet = FakeWorksheet(sheets_client.HEADER_ROW)

    @property
    def expense_sheet(self):
        return self._expense_sheet


class FakeDriveClient:
    def __init__(self):
        self.uploaded = []  # 呼び出し履歴の記録用
        self.deleted_ids = []  # delete_file呼び出し履歴(ロールバック検証用)
        self.fail_upload_with: Exception | None = None  # upload_receipt_image失敗を注入する口
        self._next_id = 1

    def upload_receipt_image(self, *, year, month, management_number, file_bytes, content_type, extension):
        if self.fail_upload_with is not None:
            raise self.fail_upload_with
        file_id = f"fake-file-{self._next_id}"
        self._next_id += 1
        url = f"https://drive.example.invalid/{year}/{month}/{management_number}{extension}"
        self.uploaded.append(
            {
                "year": year,
                "month": month,
                "management_number": management_number,
                "content_type": content_type,
                "extension": extension,
                "bytes_len": len(file_bytes),
                "file_id": file_id,
            }
        )
        return file_id, url

    def delete_file(self, file_id: str) -> None:
        self.deleted_ids.append(file_id)
