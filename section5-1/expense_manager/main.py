"""経費管理Webアプリ本体。

画面: /login(ログイン), /(経費一覧), /new(アップロード→確認・修正→登録完了)
API : /api/session, /api/expenses, /api/expenses/export.csv, /api/analyze, /api/register
"""

from __future__ import annotations

import logging
import os

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, config
from .choices import ACCOUNT_CATEGORIES, BUSINESS_SEGMENTS
from .drive_client import DriveAuthExpiredError
from .expense_service import DriveSaveError, DuplicateBlockedError, ExpenseService, SheetsRegistrationError
from .gemini_client import GeminiAnalysisError
from .models import ExpenseFields
from .upload_validation import UploadValidationError, validate_upload

logger = logging.getLogger("expense_manager.main")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="経費管理Webアプリ", version="1.0.0")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

_service: ExpenseService | None = None


def get_service() -> ExpenseService:
    global _service
    if _service is None:
        _service = ExpenseService()
    return _service


class RedirectToLogin(Exception):
    def __init__(self, next_path: str):
        self.next_path = next_path


@app.exception_handler(RedirectToLogin)
async def _handle_redirect_to_login(request: Request, exc: RedirectToLogin):
    return RedirectResponse(url=f"/login?next={exc.next_path}")


def require_session_page(request: Request) -> auth.SessionUser:
    try:
        return auth.get_current_user(request)
    except auth.UnauthorizedError:
        raise RedirectToLogin(next_path=request.url.path)


def require_session_api(request: Request) -> auth.SessionUser:
    try:
        return auth.get_current_user(request)
    except auth.UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


def _firebase_web_config() -> dict:
    return {
        "apiKey": config.FIREBASE_WEB_API_KEY,
        "authDomain": config.FIREBASE_WEB_AUTH_DOMAIN,
        "projectId": config.FIREBASE_PROJECT_ID or "",
        "appId": config.FIREBASE_WEB_APP_ID,
    }


# --- ページ ---


@app.get("/login")
def login_page(request: Request):
    next_path = request.query_params.get("next", "/")
    return templates.TemplateResponse(
        request, "login.html", {"firebase_config": _firebase_web_config(), "next_path": next_path}
    )


@app.get("/")
def list_page(request: Request, user: auth.SessionUser = Depends(require_session_page)):
    return templates.TemplateResponse(request, "list.html", {})


@app.get("/new")
def new_page(request: Request, user: auth.SessionUser = Depends(require_session_page)):
    return templates.TemplateResponse(request, "new.html", {})


# --- セッション ---


@app.post("/api/session")
async def create_session(request: Request):
    body = await request.json()
    id_token = body.get("idToken")
    if not id_token:
        return JSONResponse({"error": "idTokenが必要です"}, status_code=400)

    try:
        decoded = auth.verify_id_token(id_token)
    except Exception:
        return JSONResponse({"error": "IDトークンが無効です"}, status_code=401)

    email = decoded.get("email")
    if not email or not config.ALLOWED_LOGIN_EMAIL or email.lower() != config.ALLOWED_LOGIN_EMAIL.lower():
        return JSONResponse({"error": "このアカウントではログインできません"}, status_code=403)

    session_cookie = auth.create_session_cookie(id_token)
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


@app.post("/api/session/logout")
async def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(config.SESSION_COOKIE_NAME, path="/")
    return response


# --- 経費一覧・CSV ---


@app.get("/api/choices")
def get_choices(user: auth.SessionUser = Depends(require_session_api)):
    return {"account_categories": ACCOUNT_CATEGORIES, "business_segments": BUSINESS_SEGMENTS}


@app.get("/api/expenses")
def list_expenses(
    year: str | None = None,
    month: str | None = None,
    business_segment: str | None = None,
    user: auth.SessionUser = Depends(require_session_api),
    service: ExpenseService = Depends(get_service),
):
    items = service.list_expenses(year=year, month=month, business_segment=business_segment)
    return {"items": [item.model_dump() for item in items]}


@app.get("/api/expenses/export.csv")
def export_csv(
    year: str | None = None,
    month: str | None = None,
    business_segment: str | None = None,
    user: auth.SessionUser = Depends(require_session_api),
    service: ExpenseService = Depends(get_service),
):
    from .csv_export import build_csv

    rows = service.list_raw_rows(year=year, month=month, business_segment=business_segment)
    csv_bytes = build_csv(rows)
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="expenses.csv"'},
    )


# --- 解析・登録 ---


@app.post("/api/analyze")
async def analyze(
    file: UploadFile,
    user: auth.SessionUser = Depends(require_session_api),
    service: ExpenseService = Depends(get_service),
):
    image_bytes = await file.read()
    try:
        validate_upload(image_bytes, file.content_type)
    except UploadValidationError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    try:
        result = service.analyze(image_bytes, file.content_type or "application/octet-stream")
    except GeminiAnalysisError as e:
        # Gemini側の生のエラー内容・APIキー等は含めない安全なメッセージのみを返す
        # (詳細はgemini_client.py側でCloud Loggingへ記録済み)。
        return JSONResponse({"error": str(e)}, status_code=503)
    except Exception as e:  # noqa: BLE001
        # 生の例外内容(型名以外)はユーザーへ返さない。詳細はログにのみ記録する
        # (register()側の同種のハンドラと同じ方針)。
        logger.error("解析処理で予期しないエラーが発生しました: exception_type=%s", type(e).__name__)
        return JSONResponse(
            {"error": "AI解析に失敗しました。しばらくしてからもう一度お試しください。"}, status_code=502
        )
    return result.model_dump()


@app.post("/api/register")
async def register(
    file: UploadFile,
    request_id: str = Form(...),
    transaction_date: str | None = Form(None),
    payee: str | None = Form(None),
    amount: int | None = Form(None),
    tax_amount: int | None = Form(None),
    tax_rate: str | None = Form(None),
    tax_rate_10_base: int | None = Form(None),
    tax_rate_10_amount: int | None = Form(None),
    tax_rate_8_base: int | None = Form(None),
    tax_rate_8_amount: int | None = Form(None),
    invoice_registration_number: str | None = Form(None),
    description: str | None = Form(None),
    payment_method: str | None = Form(None),
    account_category: str | None = Form(None),
    business_segment: str | None = Form(None),
    memo: str | None = Form(None),
    override_hash_duplicate: bool = Form(False),
    override_possible_duplicate: bool = Form(False),
    user: auth.SessionUser = Depends(require_session_api),
    service: ExpenseService = Depends(get_service),
):
    image_bytes = await file.read()
    try:
        validate_upload(image_bytes, file.content_type)
    except UploadValidationError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    fields = ExpenseFields(
        transaction_date=transaction_date,
        payee=payee,
        amount=amount,
        tax_amount=tax_amount,
        tax_rate=tax_rate,
        tax_rate_10_base=tax_rate_10_base,
        tax_rate_10_amount=tax_rate_10_amount,
        tax_rate_8_base=tax_rate_8_base,
        tax_rate_8_amount=tax_rate_8_amount,
        invoice_registration_number=invoice_registration_number,
        description=description,
        payment_method=payment_method,
        account_category=account_category,
        business_segment=business_segment,
        memo=memo,
    )
    try:
        result = service.register(
            request_id=request_id,
            fields=fields,
            image_bytes=image_bytes,
            content_type=file.content_type or "application/octet-stream",
            override_hash_duplicate=override_hash_duplicate,
            override_possible_duplicate=override_possible_duplicate,
        )
    except DuplicateBlockedError as e:
        return JSONResponse(e.response.model_dump(), status_code=409)
    except DriveAuthExpiredError as e:
        # refresh tokenの失効・取消。Sheets書き込み(register内でDrive保存の後に実行)には
        # 到達していないため、中途半端なデータは残らない。
        return JSONResponse({"error": str(e), "reason": "drive_auth_expired"}, status_code=503)
    except DriveSaveError as e:
        # Drive APIの生のエラー内容は含めない安全なメッセージのみを返す
        # (詳細はexpense_service.py側でCloud Loggingへ記録済み)。
        return JSONResponse({"error": str(e)}, status_code=502)
    except SheetsRegistrationError as e:
        # Sheets APIの生のエラー内容は含めない安全なメッセージのみを返す
        # (詳細はexpense_service.py側でCloud Loggingへ記録済み)。
        return JSONResponse({"error": str(e)}, status_code=502)
    except Exception as e:  # noqa: BLE001
        logger.error("登録処理で予期しないエラーが発生しました: exception_type=%s", type(e).__name__)
        return JSONResponse(
            {"error": "登録処理に失敗しました。しばらくしてからもう一度お試しください。"}, status_code=502
        )

    return result.model_dump()


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
