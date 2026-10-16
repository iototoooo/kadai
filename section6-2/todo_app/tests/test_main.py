"""画面・APIの認証、登録・編集・一覧のエンドツーエンド(Sheets/Firebaseはフェイク)。"""

import pytest
from fastapi.testclient import TestClient

from todo_app import auth, config, main
from todo_app.tests.fakes import FakeClock, FakeSheetsClient, FakeWorksheet, SequentialIds
from todo_app.todo_service import TodoService

ALLOWED = "owner@example.com"
ORIGIN = "https://testserver"
COOKIE = config.SESSION_COOKIE_NAME

# セッションcookie値 → Firebaseが返すはずのデコード結果
SESSIONS = {
    "valid": {"uid": "u1", "email": ALLOWED, "email_verified": True},
    "valid-upper": {"uid": "u1", "email": "Owner@Example.com", "email_verified": True},
    "other": {"uid": "u2", "email": "someone@example.com", "email_verified": True},
    "unverified": {"uid": "u3", "email": ALLOWED, "email_verified": False},
}


def _fake_verify_session_cookie(cookie):
    if cookie not in SESSIONS:
        raise ValueError("invalid cookie")
    return SESSIONS[cookie]


@pytest.fixture
def ws():
    return FakeWorksheet()


@pytest.fixture
def client(monkeypatch, ws):
    monkeypatch.setattr(config, "ALLOWED_LOGIN_EMAIL", ALLOWED)
    monkeypatch.setattr(config, "TODO_SPREADSHEET_ID", "")  # テストから本物のシートに接続しない
    monkeypatch.setattr(auth, "verify_session_cookie", _fake_verify_session_cookie)
    service = TodoService(sheets=FakeSheetsClient(ws), now=FakeClock(), new_id=SequentialIds())
    main.app.dependency_overrides[main.get_service] = lambda: service
    with TestClient(main.app, base_url=ORIGIN) as c:
        yield c
    main.app.dependency_overrides.clear()


def login(client, session="valid"):
    client.cookies.set(COOKIE, session)


def post(client, path, json, origin=ORIGIN):
    headers = {"Origin": origin} if origin else {}
    return client.post(path, json=json, headers=headers)


def put(client, path, json, origin=ORIGIN):
    headers = {"Origin": origin} if origin else {}
    return client.put(path, json=json, headers=headers)


# --- 登録・編集・一覧 ---


def test_create_edit_list_flow(client, ws):
    login(client)

    res = post(client, "/api/todos", {"title": "レポート提出", "content": "課題6-2", "due_date": "2026-10-31"})
    assert res.status_code == 201
    created = res.json()
    assert created["title"] == "レポート提出"
    assert len(ws.rows) == 2

    res = client.get("/api/todos")
    assert res.status_code == 200
    assert [t["id"] for t in res.json()["items"]] == [created["id"]]

    res = put(client, f"/api/todos/{created['id']}", {"title": "レポート提出(修正)", "content": "", "due_date": ""})
    assert res.status_code == 200
    assert res.json()["title"] == "レポート提出(修正)"
    assert res.json()["created_at"] == created["created_at"]

    res = client.get(f"/api/todos/{created['id']}")
    assert res.status_code == 200
    assert res.json()["due_date"] == ""
    assert len(ws.rows) == 2  # 編集で行が増えない


def test_update_unknown_returns_404(client):
    login(client)
    res = put(client, f"/api/todos/{'a' * 32}", {"title": "x"})
    assert res.status_code == 404
    assert res.json() == {"error": "Todoが見つかりません"}


def test_invalid_id_format_rejected(client):
    login(client)
    assert client.get("/api/todos/..%2F..%2Fetc").status_code in (404, 422)
    assert client.get("/api/todos/not-a-valid-id").status_code == 422


def test_validation_error_message(client, ws):
    login(client)
    res = post(client, "/api/todos", {"title": "", "due_date": "2026/10/31"})
    assert res.status_code == 422
    assert "タイトル" in res.json()["error"]
    assert "期日" in res.json()["error"]
    assert len(ws.rows) == 1


# --- 認証: 全Todo APIに適用 ---


API_CALLS = [
    ("get", "/api/todos", None),
    ("get", f"/api/todos/{'1' * 32}", None),
    ("post", "/api/todos", {"title": "x"}),
    ("put", f"/api/todos/{'1' * 32}", {"title": "x"}),
]


@pytest.mark.parametrize("session", [None, "garbage", "other", "unverified"])
@pytest.mark.parametrize("method,path,body", API_CALLS)
def test_api_rejects_unauthorized(client, ws, session, method, path, body):
    if session:
        login(client, session)
    kwargs = {"headers": {"Origin": ORIGIN}}
    if body is not None:
        kwargs["json"] = body
    res = getattr(client, method)(path, **kwargs)
    assert res.status_code == 401
    assert res.json() == {"error": "ログインが必要です"}
    assert len(ws.rows) == 1  # 何も書き込まれない


def test_email_comparison_is_case_insensitive(client):
    login(client, "valid-upper")
    assert client.get("/api/todos").status_code == 200


@pytest.mark.parametrize("path", ["/", "/todos/new", f"/todos/{'1' * 32}/edit"])
def test_pages_redirect_to_login_when_unauthenticated(client, path):
    res = client.get(path, follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == f"/login?next={path}"


@pytest.mark.parametrize("path", ["/", "/todos/new", f"/todos/{'1' * 32}/edit"])
def test_pages_reject_other_account(client, path):
    login(client, "other")
    res = client.get(path, follow_redirects=False)
    assert res.status_code == 303


def test_pages_render_when_logged_in(client):
    login(client)
    assert "Todoリスト" in client.get("/").text
    assert "新しいTodo" in client.get("/todos/new").text
    assert 'data-todo-id="' + "1" * 32 + '"' in client.get(f"/todos/{'1' * 32}/edit").text


def test_login_page_is_public_and_sanitizes_next(client):
    res = client.get("/login?next=//evil.example.com")
    assert res.status_code == 200
    assert "evil.example.com" not in res.text


# --- CSRF対策(Originチェック) ---


@pytest.mark.parametrize("origin", [None, "https://evil.example.com"])
def test_write_requests_require_same_origin(client, ws, origin):
    login(client)
    assert post(client, "/api/todos", {"title": "x"}, origin=origin).status_code == 403
    assert put(client, f"/api/todos/{'1' * 32}", {"title": "x"}, origin=origin).status_code == 403
    assert len(ws.rows) == 1


# --- セッション発行 ---


def test_session_issued_only_for_allowed_account(client, monkeypatch):
    tokens = {
        "tok-ok": {"email": ALLOWED, "email_verified": True},
        "tok-other": {"email": "someone@example.com", "email_verified": True},
    }
    monkeypatch.setattr(auth, "verify_id_token", lambda t: tokens[t])
    monkeypatch.setattr(auth, "create_session_cookie", lambda t: "issued-cookie")

    res = post(client, "/api/session", {"idToken": "tok-other"})
    assert res.status_code == 403
    assert COOKIE not in res.headers.get("set-cookie", "")

    res = post(client, "/api/session", {"idToken": "tok-ok"})
    assert res.status_code == 200
    set_cookie = res.headers["set-cookie"]
    assert f"{COOKIE}=issued-cookie" in set_cookie
    assert "HttpOnly" in set_cookie and "Secure" in set_cookie and "samesite=lax" in set_cookie.lower()


def test_session_invalid_token(client, monkeypatch):
    def boom(_):
        raise ValueError("bad token")

    monkeypatch.setattr(auth, "verify_id_token", boom)
    res = post(client, "/api/session", {"idToken": "x"})
    assert res.status_code == 401
    assert "bad token" not in res.text


def test_session_rejects_when_allowed_email_unset(client, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_LOGIN_EMAIL", "")
    monkeypatch.setattr(auth, "verify_id_token", lambda t: {"email": ALLOWED, "email_verified": True})
    assert post(client, "/api/session", {"idToken": "x"}).status_code == 403


def test_logout_clears_cookie(client):
    login(client)
    res = post(client, "/api/session/logout", None)
    assert res.status_code == 200
    assert f'{COOKIE}=""' in res.headers["set-cookie"] or "Max-Age=0" in res.headers["set-cookie"]


# --- 内部エラーを利用者に見せない ---


def test_internal_error_is_hidden(client):
    class BrokenService:
        def list_todos(self):
            raise RuntimeError("secret-internal-detail spreadsheet=abc123")

    main.app.dependency_overrides[main.get_service] = lambda: BrokenService()
    login(client)
    with TestClient(main.app, base_url=ORIGIN, raise_server_exceptions=False) as c:
        c.cookies.set(COOKIE, "valid")
        res = c.get("/api/todos")
    assert res.status_code == 500
    assert "secret-internal-detail" not in res.text
    assert res.json() == {"error": main.GENERIC_ERROR}


def test_security_headers(client):
    res = client.get("/login")
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["Cache-Control"] == "no-store"


# --- 起動時のシート接続チェック ---


def test_startup_check_skipped_without_spreadsheet_id(monkeypatch):
    monkeypatch.setattr(config, "TODO_SPREADSHEET_ID", "")
    monkeypatch.setattr(main, "get_service", lambda: pytest.fail("接続してはいけない"))
    assert main.startup_sheets_check() is False


def test_startup_check_writes_header_on_empty_sheet(monkeypatch):
    from todo_app import sheets_client

    ws = FakeWorksheet(header=[])

    class LazySheets:
        @property
        def worksheet(self):
            sheets_client.ensure_header(ws)
            return ws

    monkeypatch.setattr(config, "TODO_SPREADSHEET_ID", "dummy-id")
    monkeypatch.setattr(main, "get_service", lambda: TodoService(sheets=LazySheets()))
    assert main.startup_sheets_check() is True
    assert ws.rows[0] == sheets_client.HEADER_ROW


def test_startup_check_failure_does_not_raise(monkeypatch):
    class BrokenSheets:
        @property
        def worksheet(self):
            raise PermissionError("403 caller does not have permission")

    monkeypatch.setattr(config, "TODO_SPREADSHEET_ID", "dummy-id")
    monkeypatch.setattr(main, "get_service", lambda: TodoService(sheets=BrokenSheets()))
    assert main.startup_sheets_check() is False
