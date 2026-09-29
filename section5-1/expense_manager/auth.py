"""Firebase Authenticationのセッションcookie発行・検証。

listing_webapp(Next.js版)のsrc/lib/sessionAuth.tsと同じ設計方針:
- サービスアカウントJSONキーは発行せず、Application Default Credentials(ADC)で
  Firebase Admin SDKを初期化する。Cloud Run上では実行サービスアカウントの権限が
  自動的に使われる。
- セッションcookieの検証(verify_session_cookie, check_revoked=True)に加えて、
  ALLOWED_LOGIN_EMAIL と一致するかどうかをアプリ側でチェックする(Firebase自体には
  「特定1アカウントのみ許可」という機能が無いため)。
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import firebase_admin
from fastapi import Request
from firebase_admin import auth as fb_auth
from firebase_admin import credentials

from . import config


def _get_app() -> firebase_admin.App:
    if firebase_admin._apps:  # noqa: SLF001
        return firebase_admin.get_app()
    if not config.FIREBASE_PROJECT_ID:
        raise RuntimeError("FIREBASE_PROJECT_ID が設定されていません")
    cred = credentials.ApplicationDefault()
    return firebase_admin.initialize_app(cred, {"projectId": config.FIREBASE_PROJECT_ID})


def create_session_cookie(id_token: str) -> str:
    _get_app()
    expires_in = datetime.timedelta(seconds=config.SESSION_EXPIRES_SECONDS)
    return fb_auth.create_session_cookie(id_token, expires_in=expires_in)


def verify_id_token(id_token: str) -> dict:
    _get_app()
    return fb_auth.verify_id_token(id_token)


class UnauthorizedError(Exception):
    pass


@dataclass
class SessionUser:
    uid: str
    email: str


def get_current_user(request: Request) -> SessionUser:
    """現在のリクエストのセッションcookieを検証し、許可アカウントであることまで確認する。"""
    cookie = request.cookies.get(config.SESSION_COOKIE_NAME)
    if not cookie:
        raise UnauthorizedError("セッションCookieがありません")

    _get_app()
    try:
        decoded = fb_auth.verify_session_cookie(cookie, check_revoked=True)
    except Exception as e:  # noqa: BLE001
        raise UnauthorizedError("セッションCookieが無効です") from e

    email = decoded.get("email")
    if not email or not config.ALLOWED_LOGIN_EMAIL or email.lower() != config.ALLOWED_LOGIN_EMAIL.lower():
        raise UnauthorizedError("許可されていないアカウントです")

    return SessionUser(uid=decoded["uid"], email=email)
