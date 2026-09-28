"""request_idによる二重登録防止のための永続ログ。

商品説明を保存する専用列が「商品管理」シートに無いため、GPT Actionsが再度同じ
request_idで呼び出したときに管理番号と完成descriptionをそのまま返せるよう、
同じスプレッドシート内の専用シート(「登録ログ(自動)」)にrequest_idごとの
処理結果を記録する。別ファイルやDBを増やさず、既存のGoogle Sheets基盤だけで
完結させることで運用・保守をシンプルに保っている。
"""

from dataclasses import dataclass
from typing import Optional

COL_REQUEST_ID = 1
COL_MANAGEMENT_NUMBER = 2
COL_STORAGE_LOCATION = 3
COL_DESCRIPTION = 4
COL_CREATED_AT = 5
COL_STATUS = 6

STATUS_SUCCESS = "success"


@dataclass
class RequestLogEntry:
    request_id: str
    management_number: str
    storage_location: str
    description: str
    created_at_jst: str
    status: str


def find_entry(worksheet, request_id: str) -> Optional[RequestLogEntry]:
    """成功済みのrequest_idがあれば、そのログ行を返す。無ければNone。"""
    values = worksheet.get_all_values()
    for row in values[1:]:  # 1行目はヘッダー
        if len(row) < 6:
            row = row + [""] * (6 - len(row))
        if row[COL_REQUEST_ID - 1] == request_id and row[COL_STATUS - 1] == STATUS_SUCCESS:
            return RequestLogEntry(
                request_id=row[COL_REQUEST_ID - 1],
                management_number=row[COL_MANAGEMENT_NUMBER - 1],
                storage_location=row[COL_STORAGE_LOCATION - 1],
                description=row[COL_DESCRIPTION - 1],
                created_at_jst=row[COL_CREATED_AT - 1],
                status=row[COL_STATUS - 1],
            )
    return None


def append_entry(worksheet, entry: RequestLogEntry) -> None:
    worksheet.append_row(
        [
            entry.request_id,
            entry.management_number,
            entry.storage_location,
            entry.description,
            entry.created_at_jst,
            entry.status,
        ],
        value_input_option="USER_ENTERED",
    )
