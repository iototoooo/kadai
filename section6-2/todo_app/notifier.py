"""LINE期限通知: 対象の選定・メッセージ作成・送信・送信済み記録。

Cloud Scheduler から毎時呼ばれる前提。重複送信の防止は2段構え:
1. シートのJ列(前日)/K列(当日)に「どの期日について通知済みか」を記録し、同じ期日では再送しない。
2. 記録を先に書いてから送信する(記録できなければ送らない)。送信の再試行には対象一覧から決まる
   X-Line-Retry-Keyを付けるため、1回目が実は届いていた場合も再試行はLINE側で409(受付済み)となり、二重に届かない。
"""

from __future__ import annotations

import datetime
import logging
import uuid
from dataclasses import dataclass

from .models import NotificationSettings, Todo
from .todo_service import NotifyKind, TodoService, sort_todos

logger = logging.getLogger("todo_app.notifier")

MAX_ITEMS_PER_MESSAGE = 30
_RETRY_KEY_NAMESPACE = uuid.UUID("6f1d3c2a-6a43-4b5e-9a57-2f0a6e1f7c10")


@dataclass(frozen=True)
class NotificationItem:
    todo: Todo
    kind: NotifyKind


def select_notifications(todos: list[Todo], settings: NotificationSettings, now: datetime.datetime) -> list[NotificationItem]:
    """now(日本時間)時点で送るべき通知を返す。完了済み・期日なしは対象外。"""
    today = now.date()
    tomorrow = today + datetime.timedelta(days=1)
    items: list[NotificationItem] = []
    for todo in sort_todos(todos, "importance"):
        if todo.completed or not todo.due_date:
            continue
        try:
            due = datetime.date.fromisoformat(todo.due_date)
        except ValueError:
            continue
        if (
            settings.same_day_enabled
            and due == today
            and now.hour >= settings.same_day_hour
            and todo.notified_same_day_due != todo.due_date
        ):
            items.append(NotificationItem(todo, "same_day"))
        elif (
            settings.day_before_enabled
            and due == tomorrow
            and now.hour >= settings.day_before_hour
            and todo.notified_day_before_due != todo.due_date
        ):
            items.append(NotificationItem(todo, "day_before"))
    return items[:MAX_ITEMS_PER_MESSAGE]


def build_message(items: list[NotificationItem], app_url: str = "") -> str:
    lines = ["【Todo期限のお知らせ】"]
    for kind, heading in (("same_day", "■ 今日が期日"), ("day_before", "■ 明日が期日")):
        group = [i for i in items if i.kind == kind]
        if group:
            lines.append("")
            lines.append(heading)
            lines.extend(f"・[{i.todo.importance}] {i.todo.title}" for i in group)
    if app_url:
        lines += ["", app_url]
    return "\n".join(lines)


def retry_key_for(items: list[NotificationItem]) -> str:
    key = ";".join(sorted(f"{i.todo.id}:{i.kind}:{i.todo.due_date}" for i in items))
    return str(uuid.uuid5(_RETRY_KEY_NAMESPACE, key))


def _previous_mark(item: NotificationItem) -> str:
    return item.todo.notified_day_before_due if item.kind == "day_before" else item.todo.notified_same_day_due


def run_notifications(service: TodoService, line_client, now: datetime.datetime, app_url: str = "") -> dict:
    """通知を1回分実行する。

    順序は「送信済み記録 → 送信」。記録できなかったものは送らないため、記録漏れによる重複は起きない。
    送信が失敗した場合は同じretry keyで1回だけ再試行し(LINE側で重複配信されない)、
    それでも失敗したら記録を元に戻して例外を送出する(次回の定期実行で再試行される)。
    """
    settings = service.get_settings()
    items = select_notifications(service.all_todos(), settings, now)
    if not items:
        return {"sent": 0}

    for item in items:
        service.mark_notified(item.todo.id, item.kind, item.todo.due_date)

    message = build_message(items, app_url)
    retry_key = retry_key_for(items)
    try:
        try:
            result = line_client.push_text(message, retry_key)
        except Exception:  # noqa: BLE001
            logger.warning("LINE push failed once; retrying with the same retry key")
            result = line_client.push_text(message, retry_key)
    except Exception:
        for item in items:
            try:
                service.mark_notified(item.todo.id, item.kind, _previous_mark(item))
            except Exception:  # noqa: BLE001
                logger.exception("failed to roll back notification mark")
        raise

    logger.info("notification %s: %d item(s)", result, len(items))
    return {"sent": len(items), "result": result}
