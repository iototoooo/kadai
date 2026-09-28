"""GPT Actionsから呼び出す商品登録API。

POST /register-item に古着商品の情報を送ると、Googleスプレッドシート「商品管理」の
ヘッダー直下(2行目)へ新規行として登録し、管理番号と完成した商品説明を返す。
"""

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.security.api_key import APIKeyHeader

from . import config
from .models import ErrorResponse, ItemRegisterRequest, RegisterItemResponse
from .service import RegisterItemService, RegistrationError

app = FastAPI(
    title="古着商品登録API",
    description="GPT ActionからGoogleスプレッドシート「商品管理」へ新規商品を登録する。",
    version="1.0.0",
)

_service: RegisterItemService = None

# GPT Actionsの「Authentication」= API Key (Custom Header: X-API-Key) として設定できるよう、
# OpenAPIのsecuritySchemeとして公開する。
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_service() -> RegisterItemService:
    global _service
    if _service is None:
        _service = RegisterItemService()
    return _service


def verify_api_key(api_key: str = Security(_api_key_header)) -> None:
    if config.API_KEY and api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="APIキーが正しくありません")


@app.post(
    "/register-item",
    operation_id="register_item",
    response_model=RegisterItemResponse,
    responses={
        401: {"model": ErrorResponse, "description": "APIキーが正しくありません"},
        400: {"model": ErrorResponse, "description": "リクエスト内容が不正です(バリデーションエラー)"},
        500: {"model": ErrorResponse, "description": "サーバー内部エラー(シート書き込み/検証失敗など)"},
    },
)
def register_item(payload: ItemRegisterRequest, _: None = Depends(verify_api_key)):
    try:
        service = get_service()
        result = service.register(payload)
        return result
    except RegistrationError as e:
        return JSONResponse(status_code=500, content=ErrorResponse(error=str(e)).model_dump())
    except Exception as e:  # 想定外のエラーも success:false で返す
        return JSONResponse(status_code=500, content=ErrorResponse(error=f"想定外のエラー: {e}").model_dump())


@app.exception_handler(RequestValidationError)
def handle_validation_error(request: Request, exc: RequestValidationError):
    messages = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
    return JSONResponse(status_code=400, content=ErrorResponse(error=messages).model_dump())


@app.exception_handler(HTTPException)
def handle_http_exception(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content=ErrorResponse(error=str(exc.detail)).model_dump())


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


def custom_openapi():
    """FastAPIが自動付与する422(Validation Error)をスキーマから取り除く。

    RequestValidationErrorは上の handle_validation_error で捕捉して常に400(ErrorResponse)
    として返しており、422が実際にクライアントへ返ることは無い。実挙動とスキーマを
    一致させるため、自動生成後に422エントリだけ削除する。
    """
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            operation.get("responses", {}).pop("422", None)
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi
