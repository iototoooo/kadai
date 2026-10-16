"""Firebase Authenticationのセッションcookie発行・検証。

expense_manager/auth.py と同じ設計方針:
- Firebase Admin SDKはApplication Default Credentials(ADC)で初期化する
  (サービスアカウントJSONキーは発行しない)。
- セッションcookieの検証(check_revoked=True)に加えて、ALLOWED_LOGIN_EMAIL と
  一致するかをアプリ側でチェックする(Firebase自体に「特定1アカウントのみ許可」機能は無いため)。
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import firebase_admin
from fastapi import Request
from firebase_admin import auth as fb_auth
from firebase_admin import credentials

from . import config


class UnauthorizedError(Exception):
    pass


@dataclass
class SessionUser:
    uid: str
    email: str


def _get_app() -> firebase_admin.App:
    if firebase_admin._apps:  # noqa: SLF001
        return firebase_admin.get_app()
    if not config.FIREBASE_PROJECT_ID:
        raise RuntimeError("FIREBASE_PROJECT_ID が設定されていません")
    cred = credentials.ApplicationDefault()
    return firebase_admin.initialize_app(cred, {"projectId": config.FIREBASE_PROJECT_ID})


def is_allowed_email(email: str | None) -> bool:
    allowed = config.ALLOWED_LOGIN_EMAIL
    return bool(email) and bool(allowed) and email.strip().lower() == allowed.strip().lower()


def verify_id_token(id_token: str) -> dict:
    _get_app()
    return fb_auth.verify_id_token(id_token)


def create_session_cookie(id_token: str) -> str:
    _get_app()
    expires_in = datetime.timedelta(seconds=config.SESSION_EXPIRES_SECONDS)
    return fb_auth.create_session_cookie(id_token, expires_in=expires_in)


def verify_session_cookie(cookie: str) -> dict:
    _get_app()
    return fb_auth.verify_session_cookie(cookie, check_revoked=True)


def get_current_user(request: Request) -> SessionUser:
    """リクエストのセッションcookieを検証し、許可アカウントであることまで確認する。"""
    cookie = request.cookies.get(config.SESSION_COOKIE_NAME)
    if not cookie:
        raise UnauthorizedError("セッションCookieがありません")

    try:
        decoded = verify_session_cookie(cookie)
    except Exception as e:  # noqa: BLE001
        raise UnauthorizedError("セッションCookieが無効です") from e

    email = decoded.get("email")
    if not decoded.get("email_verified", False) or not is_allowed_email(email):
        raise UnauthorizedError("許可されていないアカウントです")

    return SessionUser(uid=decoded["uid"], email=email)
