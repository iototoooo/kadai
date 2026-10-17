"""Todoリスト Webアプリ本体。

画面: /login, /(一覧), /todos/new(新規登録), /todos/{id}/edit(編集), /settings(通知設定)
API : /api/session, /api/session/logout, /api/todos, /api/todos/{id}, /api/todos/{id}/completion,
      /api/settings/notifications, /api/notifications/test
内部: /internal/notify(Cloud Schedulerからの定期通知。OIDCトークンで呼び出し元を検証)
画面・API(/internal以外)はすべてサーバー側でセッションcookieと許可アカウントを検証する。
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

import google.auth.transport.requests
import google.oauth2.id_token
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel

from . import auth, config, line_client, notifier
from .models import CompletionInput, NotificationSettings, TodoInput
from .todo_service import TodoNotFoundError, TodoService

logger = logging.getLogger("todo_app.main")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TODO_ID_PATTERN = r"^[0-9a-f]{32}$"
GENERIC_ERROR = "処理に失敗しました。時間をおいて再度お試しください。"

_service: TodoService | None = None


def get_service() -> TodoService:
    global _service
    if _service is None:
        _service = TodoService()
    return _service


def get_line_client():
    return line_client.LineClient()


def jst_now() -> datetime.datetime:
    return datetime.datetime.now(ZoneInfo(config.TIMEZONE_NAME))


def startup_sheets_check() -> bool:
    """起動時にシートへ接続し、旧形式からの移行(バックアップ→ヘッダー追記)と設定シートの準備まで行い、
    結果をログに残す。

    失敗しても起動自体は止めない(ログで原因を確認できるようにするための自己診断)。
    """
    if not config.TODO_SPREADSHEET_ID:
        logger.warning("startup sheets check skipped: TODO_SPREADSHEET_ID is not set")
        return False
    try:
        migration = get_service().check_connection()
    except Exception as e:  # noqa: BLE001
        logger.error("startup sheets check failed: %s: %s", type(e).__name__, str(e)[:300])
        return False
    logger.info("startup sheets check OK (sheet=%s, migration=%s)", config.TODO_SHEET_NAME, migration)
    return True


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await asyncio.to_thread(startup_sheets_check)
    yield


app = FastAPI(
    title="Todoリスト", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None, lifespan=_lifespan
)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


# --- 共通: セキュリティヘッダー・エラー処理 ---


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class RedirectToLogin(Exception):
    def __init__(self, next_path: str):
        self.next_path = next_path


@app.exception_handler(RedirectToLogin)
async def _handle_redirect_to_login(request: Request, exc: RedirectToLogin):
    return RedirectResponse(url=f"/login?next={exc.next_path}", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def _handle_http_exception(request: Request, exc: StarletteHTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


_FIELD_ERRORS = {
    "title": "タイトルは1〜100文字で入力してください",
    "content": "内容は2000文字以内で入力してください",
    "due_date": "期日はYYYY-MM-DD形式の正しい日付で入力してください",
    "importance": "重要度は高・中・低から選んでください",
    "day_before_hour": "通知時刻は0〜23時で指定してください",
    "same_day_hour": "通知時刻は0〜23時で指定してください",
}


@app.exception_handler(RequestValidationError)
async def _handle_validation_error(request: Request, exc: RequestValidationError):
    messages = []
    for err in exc.errors():
        field = err.get("loc", [None])[-1]
        msg = _FIELD_ERRORS.get(field, "入力内容が正しくありません")
        if msg not in messages:
            messages.append(msg)
    return JSONResponse({"error": "\n".join(messages) or "入力内容が正しくありません"}, status_code=422)


@app.exception_handler(Exception)
async def _handle_unexpected(request: Request, exc: Exception):
    # 内部エラーの詳細はサーバーログにのみ残し、利用者には汎用メッセージだけ返す。
    logger.exception("unexpected error: %s %s", request.method, request.url.path)
    return JSONResponse({"error": GENERIC_ERROR}, status_code=500)


# --- 認証・CSRF対策の依存関数 ---


def require_session_page(request: Request) -> auth.SessionUser:
    try:
        return auth.get_current_user(request)
    except auth.UnauthorizedError:
        raise RedirectToLogin(next_path=request.url.path)


def require_session_api(request: Request) -> auth.SessionUser:
    try:
        return auth.get_current_user(request)
    except auth.UnauthorizedError as e:
        logger.info("unauthorized api access: %s", e)
        raise HTTPException(status_code=401, detail="ログインが必要です") from e


def require_same_origin(request: Request) -> None:
    """状態を変更するリクエストは、同一オリジンのページから送られたものだけ受け付ける。"""
    origin = request.headers.get("origin")
    host = request.headers.get("host")
    if not origin or not host or urlsplit(origin).netloc != host:
        raise HTTPException(status_code=403, detail="不正なリクエストです")


def _safe_next_path(value: str | None) -> str:
    # オープンリダイレクト防止: 自サイト内の絶対パスのみ許可する。
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value


def _firebase_web_config() -> dict:
    return {
        "apiKey": config.FIREBASE_WEB_API_KEY,
        "authDomain": config.FIREBASE_WEB_AUTH_DOMAIN,
        "projectId": config.FIREBASE_PROJECT_ID,
        "appId": config.FIREBASE_WEB_APP_ID,
    }


# --- 画面 ---


@app.get("/login")
def login_page(request: Request):
    next_path = _safe_next_path(request.query_params.get("next"))
    return templates.TemplateResponse(
        request, "login.html", {"firebase_config": _firebase_web_config(), "next_path": next_path}
    )


@app.get("/")
def list_page(request: Request, user: auth.SessionUser = Depends(require_session_page)):
    return templates.TemplateResponse(request, "list.html", {})


@app.get("/todos/new")
def new_page(request: Request, user: auth.SessionUser = Depends(require_session_page)):
    return templates.TemplateResponse(request, "form.html", {"todo_id": ""})


@app.get("/todos/{todo_id}/edit")
def edit_page(
    request: Request,
    todo_id: str = Path(pattern=TODO_ID_PATTERN),
    user: auth.SessionUser = Depends(require_session_page),
):
    return templates.TemplateResponse(request, "form.html", {"todo_id": todo_id})


@app.get("/settings")
def settings_page(request: Request, user: auth.SessionUser = Depends(require_session_page)):
    return templates.TemplateResponse(request, "settings.html", {})


@app.get("/healthz")
def healthz():
    return {"ok": True}


# --- セッション ---


class SessionRequest(BaseModel):
    idToken: str


@app.post("/api/session", dependencies=[Depends(require_same_origin)])
def create_session(body: SessionRequest):
    try:
        decoded = auth.verify_id_token(body.idToken)
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "ログインに失敗しました"}, status_code=401)

    if not decoded.get("email_verified", False) or not auth.is_allowed_email(decoded.get("email")):
        logger.info("login rejected for non-allowed account")
        return JSONResponse({"error": "このアカウントではログインできません"}, status_code=403)

    session_cookie = auth.create_session_cookie(body.idToken)
    response = JSONResponse({"ok": True})
    response.set_cookie(
        key=config.SESSION_COOKIE_NAME,
        value=session_cookie,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=config.SESSION_EXPIRES_SECONDS,
    )
    return response


@app.post("/api/session/logout", dependencies=[Depends(require_same_origin)])
def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(config.SESSION_COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax")
    return response


# --- Todo API ---


@app.get("/api/todos")
def list_todos(
    status: Literal["open", "done", "all"] = Query("open"),
    sort: Literal["due", "importance"] = Query("due"),
    user: auth.SessionUser = Depends(require_session_api),
    service: TodoService = Depends(get_service),
):
    return {"items": [t.model_dump() for t in service.list_todos(status=status, sort=sort)]}


@app.get("/api/todos/{todo_id}")
def get_todo(
    todo_id: str = Path(pattern=TODO_ID_PATTERN),
    user: auth.SessionUser = Depends(require_session_api),
    service: TodoService = Depends(get_service),
):
    try:
        return service.get_todo(todo_id).model_dump()
    except TodoNotFoundError:
        raise HTTPException(status_code=404, detail="Todoが見つかりません")


@app.post("/api/todos", status_code=201, dependencies=[Depends(require_same_origin)])
def create_todo(
    data: TodoInput,
    user: auth.SessionUser = Depends(require_session_api),
    service: TodoService = Depends(get_service),
):
    return service.create_todo(data).model_dump()


@app.put("/api/todos/{todo_id}", dependencies=[Depends(require_same_origin)])
def update_todo(
    data: TodoInput,
    todo_id: str = Path(pattern=TODO_ID_PATTERN),
    user: auth.SessionUser = Depends(require_session_api),
    service: TodoService = Depends(get_service),
):
    try:
        return service.update_todo(todo_id, data).model_dump()
    except TodoNotFoundError:
        raise HTTPException(status_code=404, detail="Todoが見つかりません")


@app.patch("/api/todos/{todo_id}/completion", dependencies=[Depends(require_same_origin)])
def set_completion(
    data: CompletionInput,
    todo_id: str = Path(pattern=TODO_ID_PATTERN),
    user: auth.SessionUser = Depends(require_session_api),
    service: TodoService = Depends(get_service),
):
    try:
        return service.set_completion(todo_id, data.completed).model_dump()
    except TodoNotFoundError:
        raise HTTPException(status_code=404, detail="Todoが見つかりません")


# --- 通知設定・テスト通知 ---


@app.get("/api/settings/notifications")
def get_notification_settings(
    user: auth.SessionUser = Depends(require_session_api),
    service: TodoService = Depends(get_service),
):
    return {"settings": service.get_settings().model_dump(), "line_configured": line_client.is_configured()}


@app.put("/api/settings/notifications", dependencies=[Depends(require_same_origin)])
def put_notification_settings(
    data: NotificationSettings,
    user: auth.SessionUser = Depends(require_session_api),
    service: TodoService = Depends(get_service),
):
    return {"settings": service.save_settings(data).model_dump(), "line_configured": line_client.is_configured()}


TEST_NOTIFICATION_INTERVAL_SECONDS = 30
_test_lock = threading.Lock()
_last_test_sent_at = 0.0


@app.post("/api/notifications/test", dependencies=[Depends(require_same_origin)])
def send_test_notification(
    user: auth.SessionUser = Depends(require_session_api),
    client=Depends(get_line_client),
):
    global _last_test_sent_at
    if not line_client.is_configured():
        raise HTTPException(status_code=503, detail="LINE通知が設定されていません")
    with _test_lock:
        # 連打で無料枠(月200通)を消費しないよう、一定間隔を空ける。
        if time.monotonic() - _last_test_sent_at < TEST_NOTIFICATION_INTERVAL_SECONDS:
            raise HTTPException(status_code=429, detail="少し時間をおいてから再度お試しください")
        _last_test_sent_at = time.monotonic()
    try:
        client.push_text("【Todoリスト】テスト通知です。この通知が届けば設定は完了しています。", str(uuid.uuid4()))
    except line_client.LineSendError:
        raise HTTPException(status_code=502, detail="LINEへの送信に失敗しました")
    return {"ok": True}


# --- 定期通知(Cloud Scheduler専用) ---


def verify_scheduler_token(token: str) -> dict:
    return google.oauth2.id_token.verify_oauth2_token(
        token, google.auth.transport.requests.Request(), audience=config.NOTIFY_AUDIENCE
    )


def require_scheduler(request: Request) -> None:
    """Cloud Schedulerが todo-notifier SA で発行したOIDCトークンだけを受け付ける。"""
    if not config.NOTIFY_AUDIENCE or not config.NOTIFIER_SERVICE_ACCOUNT:
        raise HTTPException(status_code=403, detail="forbidden")
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthorized")
    try:
        claims = verify_scheduler_token(header[len("Bearer "):])
    except Exception as e:  # noqa: BLE001
        logger.info("scheduler token rejected: %s", type(e).__name__)
        raise HTTPException(status_code=401, detail="unauthorized") from e
    if claims.get("email") != config.NOTIFIER_SERVICE_ACCOUNT or not claims.get("email_verified", False):
        logger.info("scheduler token from unexpected identity rejected")
        raise HTTPException(status_code=403, detail="forbidden")


@app.post("/internal/notify", dependencies=[Depends(require_scheduler)])
def internal_notify(
    service: TodoService = Depends(get_service),
    client=Depends(get_line_client),
):
    if not line_client.is_configured():
        logger.warning("notify skipped: LINE is not configured")
        return {"sent": 0, "skipped": "line_not_configured"}
    try:
        result = notifier.run_notifications(service, client, jst_now(), app_url=config.APP_BASE_URL)
    except line_client.LineSendError as e:
        raise HTTPException(status_code=502, detail="line send failed") from e
    return {"sent": result["sent"]}
