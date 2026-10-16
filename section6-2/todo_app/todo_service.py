"""Todoの一覧・取得・登録・編集。

書き込みはすべて value_input_option="RAW" で行う。ユーザー入力が "=" 等で始まっても
数式として解釈されず、日付文字列も自動変換されずにそのまま保存される。
"""

from __future__ import annotations

import datetime
import uuid
from zoneinfo import ZoneInfo

from . import config
from .models import Todo, TodoInput
from .sheets_client import ROW_WIDTH, SheetsClient


class TodoNotFoundError(Exception):
    pass


def _now_str() -> str:
    return datetime.datetime.now(ZoneInfo(config.TIMEZONE_NAME)).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_todo(row: list) -> Todo:
    cells = [str(c) for c in row] + [""] * (ROW_WIDTH - len(row))
    return Todo(
        id=cells[0],
        title=cells[1],
        content=cells[2],
        due_date=cells[3],
        created_at=cells[4],
        updated_at=cells[5],
    )


def _sort_todos(todos: list[Todo]) -> list[Todo]:
    # 期日が近い順。期日なしは最後。同じ期日内では新しく登録したものを先に(安定ソートを2段階で適用)。
    newest_first = sorted(todos, key=lambda t: t.created_at, reverse=True)
    return sorted(newest_first, key=lambda t: (t.due_date == "", t.due_date))


class TodoService:
    def __init__(self, sheets: SheetsClient | None = None, now=_now_str, new_id=None) -> None:
        self._sheets = sheets or SheetsClient()
        self._now = now
        self._new_id = new_id or (lambda: uuid.uuid4().hex)

    @property
    def _ws(self):
        return self._sheets.worksheet

    def _data_rows(self) -> list[list]:
        return self._ws.get_all_values()[1:]  # 1行目はヘッダー

    def list_todos(self) -> list[Todo]:
        todos = [_row_to_todo(r) for r in self._data_rows() if r and str(r[0]).strip()]
        return _sort_todos(todos)

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
        )
        self._ws.append_row(
            _todo_to_row(todo), value_input_option="RAW", insert_data_option="INSERT_ROWS", table_range="A1"
        )
        return todo

    def update_todo(self, todo_id: str, data: TodoInput) -> Todo:
        row_number, current = self._find(todo_id)
        todo = current.model_copy(
            update={
                "title": data.title,
                "content": data.content,
                "due_date": data.due_date,
                "updated_at": self._now(),
            }
        )
        self._ws.update(
            values=[_todo_to_row(todo)],
            range_name=f"A{row_number}:F{row_number}",
            value_input_option="RAW",
        )
        return todo


def _todo_to_row(todo: Todo) -> list[str]:
    return [todo.id, todo.title, todo.content, todo.due_date, todo.created_at, todo.updated_at]
