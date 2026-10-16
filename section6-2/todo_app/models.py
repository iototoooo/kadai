"""Todoの入出力モデル。"""

from __future__ import annotations

import datetime
import re

from pydantic import BaseModel, Field, field_validator

TITLE_MAX = 100
CONTENT_MAX = 2000
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TodoInput(BaseModel):
    title: str = Field(max_length=TITLE_MAX)
    content: str = Field(default="", max_length=CONTENT_MAX)
    due_date: str = ""  # YYYY-MM-DD または空文字(期日なし)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("タイトルを入力してください")
        return v

    @field_validator("content")
    @classmethod
    def _strip_content(cls, v: str) -> str:
        return v.strip()

    @field_validator("due_date")
    @classmethod
    def _valid_date(cls, v: str) -> str:
        v = v.strip()
        if not v:
            return ""
        if not DATE_RE.match(v):
            raise ValueError("期日はYYYY-MM-DD形式で入力してください")
        try:
            datetime.date.fromisoformat(v)
        except ValueError as e:
            raise ValueError("存在しない日付です") from e
        return v


class Todo(BaseModel):
    id: str
    title: str
    content: str
    due_date: str
    created_at: str
    updated_at: str
