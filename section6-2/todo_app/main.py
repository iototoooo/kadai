"""Todoリスト Webアプリ本体。

画面: /login, /(一覧), /todos/new(新規登録), /todos/{id}/edit(編集)
API : /api/session, /api/session/logout, /api/todos, /api/todos/{id}
画面・APIともすべてサーバー側でセッションcookieと許可アカウントを検証する。
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel

from . import auth, config
from .models import TodoInput
from .todo_service import TodoNotFoundError, TodoService

logger = logging.getLogger("todo_app.main")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Todoリスト", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

TODO_ID_PATTERN = r"^[0-9a-f]{32}$"
GENERIC_ERROR = "処理に失敗しました。時間をおいて再度お試しください。"

_service: TodoService | None = None


def get_service() -> TodoService:
    global _service
    if _service is None:
        _service = TodoService()
    return _service


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
    user: auth.SessionUser = Depends(require_session_api),
    service: TodoService = Depends(get_service),
):
    return {"items": [t.model_dump() for t in service.list_todos()]}


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
