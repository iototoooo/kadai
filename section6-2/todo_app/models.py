"""Todo・通知設定の入出力モデル。"""

from __future__ import annotations

import datetime
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

TITLE_MAX = 100
CONTENT_MAX = 2000
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

Importance = Literal["高", "中", "低"]
IMPORTANCE_VALUES = ("高", "中", "低")
DEFAULT_IMPORTANCE: Importance = "中"
STATUS_OPEN = "未完了"
STATUS_DONE = "完了"


class TodoInput(BaseModel):
    title: str = Field(max_length=TITLE_MAX)
    content: str = Field(default="", max_length=CONTENT_MAX)
    due_date: str = ""  # YYYY-MM-DD または空文字(期日なし)
    importance: Importance = DEFAULT_IMPORTANCE

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


class CompletionInput(BaseModel):
    completed: bool


class Todo(BaseModel):
    id: str
    title: str
    content: str
    due_date: str
    created_at: str
    updated_at: str
    importance: Importance = DEFAULT_IMPORTANCE
    completed: bool = False
    completed_at: str = ""
    # 「どの期日について通知済みか」。期日が変わればまた通知対象になる。
    notified_day_before_due: str = ""
    notified_same_day_due: str = ""


class NotificationSettings(BaseModel):
    day_before_enabled: bool = True
    day_before_hour: int = Field(default=20, ge=0, le=23)
    same_day_enabled: bool = True
    same_day_hour: int = Field(default=8, ge=0, le=23)
