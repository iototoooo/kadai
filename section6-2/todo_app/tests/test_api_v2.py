"""課題2で追加したAPI: 絞り込み・並び替え・完了切り替え・通知設定・テスト通知・定期通知エンドポイント。"""

import pytest
from fastapi.testclient import TestClient

from todo_app import auth, config, line_client, main
from todo_app.tests.fakes import FakeClock, FakeLineClient, FakeSheetsClient, FakeWorksheet, SequentialIds
from todo_app.tests.test_main import ALLOWED, ORIGIN, _fake_verify_session_cookie, login, post, put
from todo_app.todo_service import TodoService

NOTIFIER_SA = "todo-notifier@example.iam.gserviceaccount.com"
AUDIENCE = "https://testserver/internal/notify"
LINE_CONFIG = '{"channel_access_token": "tok", "to": "U00000000000000000000000000000000"}'


@pytest.fixture
def ws():
    return FakeWorksheet()


@pytest.fixture
def line():
    return FakeLineClient()


@pytest.fixture
def service(ws):
    return TodoService(sheets=FakeSheetsClient(ws), now=FakeClock(), new_id=SequentialIds())


@pytest.fixture
def client(monkeypatch, service, line):
    monkeypatch.setattr(config, "ALLOWED_LOGIN_EMAIL", ALLOWED)
    monkeypatch.setattr(config, "TODO_SPREADSHEET_ID", "")
    monkeypatch.setattr(config, "TODO_LINE_CONFIG", LINE_CONFIG)
    monkeypatch.setattr(config, "NOTIFY_AUDIENCE", AUDIENCE)
    monkeypatch.setattr(config, "NOTIFIER_SERVICE_ACCOUNT", NOTIFIER_SA)
    monkeypatch.setattr(auth, "verify_session_cookie", _fake_verify_session_cookie)
    monkeypatch.setattr(main, "_last_test_sent_at", 0.0)
    main.app.dependency_overrides[main.get_service] = lambda: service
    main.app.dependency_overrides[main.get_line_client] = lambda: line
    with TestClient(main.app, base_url=ORIGIN) as c:
        yield c
    main.app.dependency_overrides.clear()


def patch(client, path, json, origin=ORIGIN):
    headers = {"Origin": origin} if origin else {}
    return client.patch(path, json=json, headers=headers)


# --- ① 重要度・並び替え ---


def test_create_with_importance_and_sort(client):
    login(client)
    low = post(client, "/api/todos", {"title": "低", "due_date": "2026-10-18", "importance": "低"}).json()
    high = post(client, "/api/todos", {"title": "高", "due_date": "2026-10-30", "importance": "高"}).json()
    default = post(client, "/api/todos", {"title": "指定なし"}).json()
    assert default["importance"] == "中"

    by_due = [t["id"] for t in client.get("/api/todos?sort=due").json()["items"]]
    by_imp = [t["id"] for t in client.get("/api/todos?sort=importance").json()["items"]]
    assert by_due == [low["id"], high["id"], default["id"]]
    assert by_imp == [high["id"], default["id"], low["id"]]


def test_edit_importance(client):
    login(client)
    t = post(client, "/api/todos", {"title": "x"}).json()
    res = put(client, f"/api/todos/{t['id']}", {"title": "x", "importance": "高"})
    assert res.status_code == 200 and res.json()["importance"] == "高"


def test_invalid_importance_and_query_values(client):
    login(client)
    res = post(client, "/api/todos", {"title": "x", "importance": "超"})
    assert res.status_code == 422 and "重要度" in res.json()["error"]
    assert client.get("/api/todos?sort=random").status_code == 422
    assert client.get("/api/todos?status=deleted").status_code == 422


# --- ③ 完了チェック・絞り込み ---


def test_completion_toggle_and_filter(client, ws):
    login(client)
    a = post(client, "/api/todos", {"title": "A"}).json()
    b = post(client, "/api/todos", {"title": "B"}).json()

    res = patch(client, f"/api/todos/{a['id']}/completion", {"completed": True})
    assert res.status_code == 200 and res.json()["completed"] is True

    ids = lambda q: [t["id"] for t in client.get(f"/api/todos{q}").json()["items"]]  # noqa: E731
    assert ids("") == [b["id"]]  # 既定は未完了のみ
    assert ids("?status=done") == [a["id"]]
    assert set(ids("?status=all")) == {a["id"], b["id"]}

    patch(client, f"/api/todos/{a['id']}/completion", {"completed": False})
    assert set(ids("?status=open")) == {a["id"], b["id"]}
    assert len(ws.rows) == 3  # 行は増えない


def test_completion_errors(client):
    login(client)
    assert patch(client, f"/api/todos/{'a' * 32}/completion", {"completed": True}).status_code == 404
    t = post(client, "/api/todos", {"title": "x"}).json()
    assert patch(client, f"/api/todos/{t['id']}/completion", {"completed": "maybe"}).status_code == 422
    assert patch(client, f"/api/todos/{t['id']}/completion", {"completed": True}, origin=None).status_code == 403


# --- 通知設定 ---


def test_settings_get_and_put(client):
    login(client)
    res = client.get("/api/settings/notifications").json()
    assert res["settings"] == {
        "day_before_enabled": True, "day_before_hour": 20, "same_day_enabled": True, "same_day_hour": 8
    }
    assert res["line_configured"] is True

    new = {"day_before_enabled": False, "day_before_hour": 19, "same_day_enabled": True, "same_day_hour": 6}
    assert put(client, "/api/settings/notifications", new).json()["settings"] == new
    assert client.get("/api/settings/notifications").json()["settings"] == new


def test_settings_validation(client):
    login(client)
    bad = {"day_before_enabled": True, "day_before_hour": 24, "same_day_enabled": True, "same_day_hour": 8}
    res = put(client, "/api/settings/notifications", bad)
    assert res.status_code == 422 and "0〜23" in res.json()["error"]


def test_settings_page_requires_login(client):
    assert client.get("/settings", follow_redirects=False).status_code == 303
    login(client)
    assert "通知設定" in client.get("/settings").text


def test_settings_response_never_contains_line_secrets(client):
    login(client)
    text = client.get("/api/settings/notifications").text
    assert "tok" not in text.replace("todo", "") and "U0000" not in text


# --- テスト通知 ---


def test_test_notification_sends_and_is_rate_limited(client, line):
    login(client)
    assert post(client, "/api/notifications/test", {}).status_code == 200
    assert len(line.sent) == 1
    res = post(client, "/api/notifications/test", {})
    assert res.status_code == 429
    assert len(line.sent) == 1


def test_test_notification_when_line_not_configured(client, monkeypatch, line):
    monkeypatch.setattr(config, "TODO_LINE_CONFIG", "")
    login(client)
    assert post(client, "/api/notifications/test", {}).status_code == 503
    assert line.attempts == 0


def test_test_notification_send_failure(client, line):
    line.fail_times = 1
    line.fail_with = line_client.LineSendError(500)
    login(client)
    res = post(client, "/api/notifications/test", {})
    assert res.status_code == 502 and "tok" not in res.text.replace("todo", "")


# --- 新APIへの認証の適用 ---


NEW_APIS = [
    ("patch", f"/api/todos/{'1' * 32}/completion", {"completed": True}),
    ("get", "/api/settings/notifications", None),
    ("put", "/api/settings/notifications", {"day_before_enabled": True, "day_before_hour": 20,
                                            "same_day_enabled": True, "same_day_hour": 8}),
    ("post", "/api/notifications/test", {}),
]


@pytest.mark.parametrize("session", [None, "garbage", "other", "unverified"])
@pytest.mark.parametrize("method,path,body", NEW_APIS)
def test_new_apis_reject_unauthorized(client, line, session, method, path, body):
    if session:
        login(client, session)
    kwargs = {"headers": {"Origin": ORIGIN}}
    if body is not None:
        kwargs["json"] = body
    res = getattr(client, method)(path, **kwargs)
    assert res.status_code == 401
    assert line.attempts == 0


@pytest.mark.parametrize("method,path,body", [m for m in NEW_APIS if m[0] != "get"])
def test_new_write_apis_require_same_origin(client, line, method, path, body):
    login(client)
    res = getattr(client, method)(path, json=body, headers={"Origin": "https://evil.example.com"})
    assert res.status_code == 403
    assert line.attempts == 0


# --- 定期通知エンドポイント(/internal/notify) ---


def _token_verifier(claims_by_token):
    def verify(token):
        if token not in claims_by_token:
            raise ValueError("bad token")
        return claims_by_token[token]

    return verify


@pytest.fixture
def scheduler_tokens(monkeypatch):
    monkeypatch.setattr(
        main,
        "verify_scheduler_token",
        _token_verifier(
            {
                "good": {"email": NOTIFIER_SA, "email_verified": True},
                "other-sa": {"email": "attacker@example.iam.gserviceaccount.com", "email_verified": True},
                "unverified": {"email": NOTIFIER_SA, "email_verified": False},
            }
        ),
    )


def test_internal_notify_with_valid_token_sends(client, scheduler_tokens, service, line, monkeypatch):
    import datetime

    monkeypatch.setattr(main, "jst_now", lambda: datetime.datetime(2026, 10, 17, 9, 0))
    service.create_todo(main.TodoInput(title="今日の締切", due_date="2026-10-17"))
    res = client.post("/internal/notify", headers={"Authorization": "Bearer good"})
    assert res.status_code == 200 and res.json() == {"sent": 1}
    assert len(line.sent) == 1
    # 2回目(次の毎時実行)では重複送信しない
    assert client.post("/internal/notify", headers={"Authorization": "Bearer good"}).json() == {"sent": 0}
    assert len(line.sent) == 1


@pytest.mark.parametrize(
    "headers,status",
    [
        ({}, 401),
        ({"Authorization": "Basic abc"}, 401),
        ({"Authorization": "Bearer forged"}, 401),
        ({"Authorization": "Bearer other-sa"}, 403),
        ({"Authorization": "Bearer unverified"}, 403),
    ],
)
def test_internal_notify_rejects_invalid_callers(client, scheduler_tokens, service, line, headers, status):
    service.create_todo(main.TodoInput(title="今日", due_date=main.jst_now().date().isoformat()))
    res = client.post("/internal/notify", headers=headers)
    assert res.status_code == status
    assert line.attempts == 0


def test_internal_notify_rejects_session_cookie_user(client, scheduler_tokens, line):
    login(client)  # ログイン済みの利用者でもSchedulerのトークンが無ければ拒否
    assert client.post("/internal/notify", headers={"Origin": ORIGIN}).status_code == 401


def test_internal_notify_disabled_without_config(client, scheduler_tokens, monkeypatch, line):
    monkeypatch.setattr(config, "NOTIFIER_SERVICE_ACCOUNT", "")
    assert client.post("/internal/notify", headers={"Authorization": "Bearer good"}).status_code == 403


def test_internal_notify_skips_when_line_not_configured(client, scheduler_tokens, monkeypatch, line):
    monkeypatch.setattr(config, "TODO_LINE_CONFIG", "")
    res = client.post("/internal/notify", headers={"Authorization": "Bearer good"})
    assert res.status_code == 200 and res.json()["sent"] == 0


def test_internal_notify_line_failure_returns_502(client, scheduler_tokens, service, line, monkeypatch):
    import datetime

    monkeypatch.setattr(main, "jst_now", lambda: datetime.datetime(2026, 10, 17, 9, 0))
    service.create_todo(main.TodoInput(title="今日", due_date="2026-10-17"))
    line.fail_times = 2
    line.fail_with = line_client.LineSendError(500)
    res = client.post("/internal/notify", headers={"Authorization": "Bearer good"})
    assert res.status_code == 502
