"""Todoの一覧・取得・登録・編集・完了切り替えと、通知設定の読み書き。

書き込みはすべて value_input_option="RAW" で行う。ユーザー入力が "=" 等で始まっても
数式として解釈されず、日付文字列も自動変換されずにそのまま保存される。
既存行の更新は、その操作で変わる列だけを書き込む(他の列の値を巻き込んで上書きしない)。
"""

from __future__ import annotations

import datetime
import uuid
from typing import Literal
from zoneinfo import ZoneInfo

from . import config
from .models import (
    DEFAULT_IMPORTANCE,
    IMPORTANCE_VALUES,
    STATUS_DONE,
    STATUS_OPEN,
    NotificationSettings,
    Todo,
    TodoInput,
)
from .sheets_client import (
    COL_COMPLETED_AT,
    COL_DUE_DATE,
    COL_IMPORTANCE,
    COL_NOTIFIED_DAY_BEFORE,
    COL_NOTIFIED_SAME_DAY,
    COL_STATUS,
    COL_TITLE,
    COL_UPDATED_AT,
    ROW_WIDTH,
    SETTINGS_DEFAULT_ROWS,
    SETTINGS_HEADER,
    SheetsClient,
    col_letter,
)

StatusFilter = Literal["open", "done", "all"]
SortKey = Literal["due", "importance"]
NotifyKind = Literal["day_before", "same_day"]

_IMPORTANCE_RANK = {v: i for i, v in enumerate(IMPORTANCE_VALUES)}  # 高=0, 中=1, 低=2


class TodoNotFoundError(Exception):
    pass


def _now_str() -> str:
    return datetime.datetime.now(ZoneInfo(config.TIMEZONE_NAME)).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_todo(row: list) -> Todo:
    cells = [str(c) for c in row] + [""] * (ROW_WIDTH - len(row))
    importance = cells[COL_IMPORTANCE - 1].strip()
    return Todo(
        id=cells[0],
        title=cells[1],
        content=cells[2],
        due_date=cells[3],
        created_at=cells[4],
        updated_at=cells[5],
        # 旧形式の行(G列以降が空)は 重要度=中・未完了 として扱う。
        importance=importance if importance in IMPORTANCE_VALUES else DEFAULT_IMPORTANCE,
        completed=cells[COL_STATUS - 1].strip() == STATUS_DONE,
        completed_at=cells[COL_COMPLETED_AT - 1],
        notified_day_before_due=cells[COL_NOTIFIED_DAY_BEFORE - 1],
        notified_same_day_due=cells[COL_NOTIFIED_SAME_DAY - 1],
    )


def _todo_to_row(todo: Todo) -> list[str]:
    return [
        todo.id,
        todo.title,
        todo.content,
        todo.due_date,
        todo.created_at,
        todo.updated_at,
        todo.importance,
        STATUS_DONE if todo.completed else STATUS_OPEN,
        todo.completed_at,
        todo.notified_day_before_due,
        todo.notified_same_day_due,
    ]


def _due_key(t: Todo):
    return (t.due_date == "", t.due_date)


def _importance_key(t: Todo):
    return _IMPORTANCE_RANK[t.importance]


def sort_todos(todos: list[Todo], sort: SortKey = "due") -> list[Todo]:
    # 安定ソートを優先度の低い順に重ねる。最後の基準は「新しく登録したものが先」。
    result = sorted(todos, key=lambda t: t.created_at, reverse=True)
    if sort == "importance":
        result = sorted(result, key=_due_key)
        return sorted(result, key=_importance_key)
    result = sorted(result, key=_importance_key)
    return sorted(result, key=_due_key)


def _cell(col: int, row: int) -> str:
    return f"{col_letter(col)}{row}"


class TodoService:
    def __init__(self, sheets: SheetsClient | None = None, now=_now_str, new_id=None) -> None:
        self._sheets = sheets or SheetsClient()
        self._now = now
        self._new_id = new_id or (lambda: uuid.uuid4().hex)

    @property
    def _ws(self):
        return self._sheets.worksheet

    def check_connection(self) -> str:
        """シートを開き、移行(必要な場合)と設定シートの準備まで行う。失敗時は例外を送出する。

        戻り値は移行処理の結果("ok" / "initialized" / "migrated")。
        """
        _ = self._ws
        _ = self._sheets.settings_worksheet
        return getattr(self._sheets, "last_migration_result", "")

    def _data_rows(self) -> list[list]:
        return self._ws.get_all_values()[1:]  # 1行目はヘッダー

    def all_todos(self) -> list[Todo]:
        return [_row_to_todo(r) for r in self._data_rows() if r and str(r[0]).strip()]

    def list_todos(self, status: StatusFilter = "open", sort: SortKey = "due") -> list[Todo]:
        todos = self.all_todos()
        if status == "open":
            todos = [t for t in todos if not t.completed]
        elif status == "done":
            todos = [t for t in todos if t.completed]
        return sort_todos(todos, sort)

    def _find(self, todo_id: str) -> tuple[int, Todo]:
        """(シート上の行番号, Todo) を返す。"""
        for i, row in enumerate(self._data_rows()):
            if row and str(row[0]) == todo_id:
                return i + 2, _row_to_todo(row)
        raise TodoNotFoundError(todo_id)

    def get_todo(self, todo_id: str) -> Todo:
        return self._find(todo_id)[1]

    def create_todo(self, data: TodoInput) -> Todo:
        now = self._now()
        todo = Todo(
            id=self._new_id(),
            title=data.title,
            content=data.content,
            due_date=data.due_date,
            created_at=now,
            updated_at=now,
            importance=data.importance,
        )
        self._ws.append_row(
            _todo_to_row(todo), value_input_option="RAW", insert_data_option="INSERT_ROWS", table_range="A1"
        )
        return todo

    def update_todo(self, todo_id: str, data: TodoInput) -> Todo:
        row, current = self._find(todo_id)
        todo = current.model_copy(
            update={
                "title": data.title,
                "content": data.content,
                "due_date": data.due_date,
                "importance": data.importance,
                "updated_at": self._now(),
            }
        )
        # B〜D(タイトル・内容・期日)と F〜G(更新日時・重要度)だけを書く。
        # ID・登録日時・完了状態・通知記録の列には触れない。
        self._ws.batch_update(
            [
                {
                    "range": f"{_cell(COL_TITLE, row)}:{_cell(COL_DUE_DATE, row)}",
                    "values": [[todo.title, todo.content, todo.due_date]],
                },
                {
                    "range": f"{_cell(COL_UPDATED_AT, row)}:{_cell(COL_IMPORTANCE, row)}",
                    "values": [[todo.updated_at, todo.importance]],
                },
            ],
            value_input_option="RAW",
        )
        return todo

    def set_completion(self, todo_id: str, completed: bool) -> Todo:
        row, current = self._find(todo_id)
        now = self._now()
        todo = current.model_copy(
            update={"completed": completed, "completed_at": now if completed else "", "updated_at": now}
        )
        self._ws.batch_update(
            [
                {"range": _cell(COL_UPDATED_AT, row), "values": [[todo.updated_at]]},
                {
                    "range": f"{_cell(COL_STATUS, row)}:{_cell(COL_COMPLETED_AT, row)}",
                    "values": [[STATUS_DONE if completed else STATUS_OPEN, todo.completed_at]],
                },
            ],
            value_input_option="RAW",
        )
        return todo

    def mark_notified(self, todo_id: str, kind: NotifyKind, due_date: str) -> None:
        """通知済みの記録(J列またはK列)だけを書き込む。"""
        row, _ = self._find(todo_id)
        col = COL_NOTIFIED_DAY_BEFORE if kind == "day_before" else COL_NOTIFIED_SAME_DAY
        self._ws.update(values=[[due_date]], range_name=_cell(col, row), value_input_option="RAW")

    # --- 通知設定(「設定」シート、アプリ全体で共通) ---

    def get_settings(self) -> NotificationSettings:
        rows = self._sheets.settings_worksheet.get_all_values()[1:]
        raw = {str(r[0]).strip(): str(r[1]).strip() for r in rows if len(r) >= 2 and str(r[0]).strip()}
        defaults = NotificationSettings()
        values = {}
        for key, default in defaults.model_dump().items():
            if key not in raw:
                values[key] = default
            elif isinstance(default, bool):
                values[key] = raw[key].upper() == "TRUE"
            else:
                values[key] = int(raw[key]) if raw[key].isdigit() and 0 <= int(raw[key]) <= 23 else default
        return NotificationSettings(**values)

    def save_settings(self, settings: NotificationSettings) -> NotificationSettings:
        descriptions = {r[0]: r[2] for r in SETTINGS_DEFAULT_ROWS}
        rows = [SETTINGS_HEADER] + [
            [key, ("TRUE" if value else "FALSE") if isinstance(value, bool) else str(value), descriptions.get(key, "")]
            for key, value in settings.model_dump().items()
        ]
        self._sheets.settings_worksheet.update(
            values=rows, range_name=f"A1:C{len(rows)}", value_input_option="RAW"
        )
        return settings
