"""② LINE期限通知: 対象選定・重複防止・失敗時の扱い。"""

import datetime

import pytest

from todo_app import line_client, notifier
from todo_app.models import NotificationSettings, TodoInput
from todo_app.tests.fakes import FakeClock, FakeLineClient, FakeSheetsClient, FakeWorksheet, SequentialIds
from todo_app.todo_service import TodoService

TODAY = datetime.date(2026, 10, 17)
TOMORROW = "2026-10-18"
TODAY_S = "2026-10-17"


def at(hour: int, day: datetime.date = TODAY) -> datetime.datetime:
    return datetime.datetime(day.year, day.month, day.day, hour, 0, 5)


@pytest.fixture
def ws():
    return FakeWorksheet()


@pytest.fixture
def service(ws):
    return TodoService(sheets=FakeSheetsClient(ws), now=FakeClock(), new_id=SequentialIds())


@pytest.fixture
def line():
    return FakeLineClient()


def kinds(items):
    return [(i.todo.title, i.kind) for i in items]


# --- 対象選定 ---


def test_same_day_and_day_before_selected_after_configured_hours(service):
    service.create_todo(TodoInput(title="今日", due_date=TODAY_S))
    service.create_todo(TodoInput(title="明日", due_date=TOMORROW))
    service.create_todo(TodoInput(title="明後日", due_date="2026-10-19"))
    service.create_todo(TodoInput(title="昨日", due_date="2026-10-16"))
    service.create_todo(TodoInput(title="期日なし"))
    s = NotificationSettings()  # 前日20時・当日8時

    assert kinds(notifier.select_notifications(service.all_todos(), s, at(7))) == []
    assert kinds(notifier.select_notifications(service.all_todos(), s, at(8))) == [("今日", "same_day")]
    assert kinds(notifier.select_notifications(service.all_todos(), s, at(20))) == [
        ("今日", "same_day"),
        ("明日", "day_before"),
    ]


def test_completed_todos_are_never_notified(service):
    t = service.create_todo(TodoInput(title="完了済み", due_date=TODAY_S))
    service.create_todo(TodoInput(title="完了済み明日", due_date=TOMORROW))
    service.set_completion(t.id, True)
    service.set_completion(service.all_todos()[1].id, True)
    assert notifier.select_notifications(service.all_todos(), NotificationSettings(), at(23)) == []


def test_disabled_kinds_are_skipped(service):
    service.create_todo(TodoInput(title="今日", due_date=TODAY_S))
    service.create_todo(TodoInput(title="明日", due_date=TOMORROW))
    s = NotificationSettings(day_before_enabled=False, same_day_enabled=False)
    assert notifier.select_notifications(service.all_todos(), s, at(23)) == []


def test_custom_hours(service):
    service.create_todo(TodoInput(title="明日", due_date=TOMORROW))
    s = NotificationSettings(day_before_hour=7)
    assert kinds(notifier.select_notifications(service.all_todos(), s, at(6))) == []
    assert kinds(notifier.select_notifications(service.all_todos(), s, at(7))) == [("明日", "day_before")]


def test_items_ordered_by_importance(service):
    service.create_todo(TodoInput(title="低", due_date=TODAY_S, importance="低"))
    service.create_todo(TodoInput(title="高", due_date=TODAY_S, importance="高"))
    items = notifier.select_notifications(service.all_todos(), NotificationSettings(), at(9))
    assert [i.todo.title for i in items] == ["高", "低"]


def test_message_contents():
    from todo_app.models import Todo

    def todo(title, due, imp):
        return Todo(id="a" * 32, title=title, content="", due_date=due, created_at="", updated_at="", importance=imp)

    items = [
        notifier.NotificationItem(todo("レポート", TODAY_S, "高"), "same_day"),
        notifier.NotificationItem(todo("買い物", TOMORROW, "中"), "day_before"),
    ]
    text = notifier.build_message(items, "https://example.invalid/")
    assert text.splitlines() == [
        "【Todo期限のお知らせ】", "", "■ 今日が期日", "・[高] レポート", "", "■ 明日が期日", "・[中] 買い物",
        "", "https://example.invalid/",
    ]


# --- 送信と重複防止 ---


def test_run_sends_once_and_records(service, ws, line):
    t = service.create_todo(TodoInput(title="今日", due_date=TODAY_S))

    assert notifier.run_notifications(service, line, at(9)) == {"sent": 1, "result": "sent"}
    assert len(line.sent) == 1 and "今日" in line.sent[0][0]
    assert service.get_todo(t.id).notified_same_day_due == TODAY_S

    # 毎時の再実行でも同じ通知は送らない
    for hour in range(10, 24):
        assert notifier.run_notifications(service, line, at(hour)) == {"sent": 0}
    assert len(line.sent) == 1


def test_day_before_and_same_day_are_separate_kinds(service, line):
    service.create_todo(TodoInput(title="明日", due_date=TOMORROW))
    notifier.run_notifications(service, line, at(20))
    notifier.run_notifications(service, line, at(8, TODAY + datetime.timedelta(days=1)))
    notifier.run_notifications(service, line, at(12, TODAY + datetime.timedelta(days=1)))
    assert len(line.sent) == 2
    assert "明日が期日" in line.sent[0][0] and "今日が期日" in line.sent[1][0]


def test_changing_due_date_makes_todo_eligible_again(service, line):
    t = service.create_todo(TodoInput(title="延期", due_date=TODAY_S))
    notifier.run_notifications(service, line, at(9))
    service.update_todo(t.id, TodoInput(title="延期", due_date=TOMORROW))
    notifier.run_notifications(service, line, at(21))
    assert len(line.sent) == 2


def test_completed_after_selection_window_is_not_sent(service, line):
    t = service.create_todo(TodoInput(title="先に完了", due_date=TODAY_S))
    service.set_completion(t.id, True)
    assert notifier.run_notifications(service, line, at(9)) == {"sent": 0}
    assert line.attempts == 0


def test_multiple_items_are_combined_into_one_message(service, line):
    for i in range(3):
        service.create_todo(TodoInput(title=f"今日{i}", due_date=TODAY_S))
    notifier.run_notifications(service, line, at(9))
    assert len(line.sent) == 1


def test_retry_key_is_deterministic_for_same_items(service):
    service.create_todo(TodoInput(title="今日", due_date=TODAY_S))
    items1 = notifier.select_notifications(service.all_todos(), NotificationSettings(), at(9))
    items2 = notifier.select_notifications(service.all_todos(), NotificationSettings(), at(15))
    assert notifier.retry_key_for(items1) == notifier.retry_key_for(items2)


def test_transient_failure_is_retried_with_same_key(service, line):
    service.create_todo(TodoInput(title="今日", due_date=TODAY_S))
    line.fail_times = 1
    notifier.run_notifications(service, line, at(9))
    assert line.attempts == 2 and len(line.sent) == 1


def test_persistent_failure_rolls_back_marks_and_raises(service, line):
    t = service.create_todo(TodoInput(title="今日", due_date=TODAY_S))
    line.fail_times = 2
    line.fail_with = line_client.LineSendError(500)
    with pytest.raises(line_client.LineSendError):
        notifier.run_notifications(service, line, at(9))
    assert service.get_todo(t.id).notified_same_day_due == ""  # 次回に再試行される

    notifier.run_notifications(service, line, at(10))
    assert len(line.sent) == 1


def test_mark_failure_prevents_sending(service, ws, line):
    service.create_todo(TodoInput(title="今日", due_date=TODAY_S))
    ws.fail_update_with = RuntimeError("sheets down")
    with pytest.raises(RuntimeError):
        notifier.run_notifications(service, line, at(9))
    assert line.attempts == 0  # 記録できなければ送らない(重複の芽を作らない)


def test_duplicate_response_counts_as_delivered(service, line):
    t = service.create_todo(TodoInput(title="今日", due_date=TODAY_S))
    line.result = "duplicate"
    assert notifier.run_notifications(service, line, at(9))["result"] == "duplicate"
    assert service.get_todo(t.id).notified_same_day_due == TODAY_S


# --- LINEクライアント(HTTPはフェイク) ---


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


class _Session:
    def __init__(self, status_code):
        self.status_code = status_code
        self.calls = []

    def post(self, url, headers, json, timeout):
        self.calls.append((url, headers, json))
        return _Resp(self.status_code)


CFG = line_client.LineConfig(channel_access_token="tok-SECRET", to="U" + "0" * 32)


@pytest.mark.parametrize("status,expected", [(200, "sent"), (409, "duplicate")])
def test_line_client_success_statuses(status, expected):
    session = _Session(status)
    assert line_client.LineClient(CFG, session).push_text("hello", "key-1") == expected
    url, headers, body = session.calls[0]
    assert url == line_client.PUSH_URL
    assert headers["X-Line-Retry-Key"] == "key-1"
    assert body["messages"] == [{"type": "text", "text": "hello"}]


def test_line_client_error_does_not_leak_secrets(caplog):
    with pytest.raises(line_client.LineSendError) as exc:
        line_client.LineClient(CFG, _Session(401)).push_text("hello", "k")
    assert "tok-SECRET" not in str(exc.value) and CFG.to not in str(exc.value)
    assert "tok-SECRET" not in caplog.text and CFG.to not in caplog.text


def test_line_client_truncates_long_text():
    session = _Session(200)
    line_client.LineClient(CFG, session).push_text("あ" * 6000, "k")
    assert len(session.calls[0][2]["messages"][0]["text"]) == line_client.TEXT_MAX_LENGTH


@pytest.mark.parametrize(
    "raw,ok",
    [
        ('{"channel_access_token": "t", "to": "U1"}', True),
        ('{"channel_access_token": "t"}', False),
        ("not json", False),
        ("", False),
    ],
)
def test_load_line_config(monkeypatch, raw, ok):
    from todo_app import config

    monkeypatch.setattr(config, "TODO_LINE_CONFIG", raw)
    assert line_client.is_configured() is ok


# --- 失敗パターンごとの記録の扱い(重複防止の最終確認) ---


def test_partial_mark_failure_rolls_back_and_sends_nothing(service, line, monkeypatch):
    a = service.create_todo(TodoInput(title="A", due_date=TODAY_S))
    b = service.create_todo(TodoInput(title="B", due_date=TODAY_S))
    original = service.mark_notified
    calls = {"n": 0}

    def flaky(todo_id, kind, due):
        calls["n"] += 1
        if calls["n"] == 2:  # 2件目の記録で失敗
            raise RuntimeError("sheets down")
        return original(todo_id, kind, due)

    monkeypatch.setattr(service, "mark_notified", flaky)
    with pytest.raises(RuntimeError):
        notifier.run_notifications(service, line, at(9))
    assert line.attempts == 0
    monkeypatch.setattr(service, "mark_notified", original)
    # 1件目の記録も元に戻っているので、次回は2件とも送られる(取りこぼしなし)
    assert service.get_todo(a.id).notified_same_day_due == ""
    assert service.get_todo(b.id).notified_same_day_due == ""
    notifier.run_notifications(service, line, at(10))
    assert len(line.sent) == 1 and "A" in line.sent[0][0] and "B" in line.sent[0][0]


def test_unknown_delivery_keeps_marks_to_avoid_duplicates(service, line):
    import requests

    t = service.create_todo(TodoInput(title="今日", due_date=TODAY_S))
    line.fail_times = 2
    line.fail_with = requests.Timeout("read timeout")
    with pytest.raises(requests.Timeout):
        notifier.run_notifications(service, line, at(9))
    assert service.get_todo(t.id).notified_same_day_due == TODAY_S  # 記録は残す
    service.create_todo(TodoInput(title="別件", due_date=TODAY_S))
    notifier.run_notifications(service, line, at(10))
    # 次回は「別件」だけが送られ、「今日」は再送されない
    assert len(line.sent) == 1 and "別件" in line.sent[0][0] and "・[中] 今日" not in line.sent[0][0]


def test_timeout_then_rejection_still_counts_as_unknown(service, line):
    import requests

    t = service.create_todo(TodoInput(title="今日", due_date=TODAY_S))

    class Seq:
        attempts = 0

        def push_text(self, text, key):
            self.attempts += 1
            if self.attempts == 1:
                raise requests.ConnectionError("reset")
            raise line_client.LineSendError(500)

    with pytest.raises(line_client.LineSendError):
        notifier.run_notifications(service, Seq(), at(9))
    assert service.get_todo(t.id).notified_same_day_due == TODAY_S


def test_retry_uses_identical_key_and_message(service):
    service.create_todo(TodoInput(title="今日", due_date=TODAY_S))
    seen = []

    class Rec:
        def push_text(self, text, key):
            seen.append((text, key))
            if len(seen) == 1:
                raise line_client.LineSendError(503)
            return "duplicate"  # 1回目が実は受理されていたケース

    notifier.run_notifications(service, Rec(), at(9))
    assert len(seen) == 2 and seen[0] == seen[1]
