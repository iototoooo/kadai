"""環境変数からの設定読み込み。

expense_manager/config.py と同じ方針: 認証情報や書き込み先はコードに直書きせず、
すべて環境変数(または .env)から読む。import時点では値の有無を検証しない。
"""

import os

from dotenv import load_dotenv

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

# --- Firebase Authentication (Googleサインイン、許可アカウント1件のみ) ---
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "")
ALLOWED_LOGIN_EMAIL = os.getenv("ALLOWED_LOGIN_EMAIL", "")
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "todo_app_session")
SESSION_EXPIRES_SECONDS = 14 * 24 * 60 * 60  # 14日

# Firebase Web SDK向けの公開設定値(ブラウザに渡って問題ない値のみ)。
FIREBASE_WEB_API_KEY = os.getenv("FIREBASE_WEB_API_KEY", "")
FIREBASE_WEB_AUTH_DOMAIN = os.getenv("FIREBASE_WEB_AUTH_DOMAIN", "")
FIREBASE_WEB_APP_ID = os.getenv("FIREBASE_WEB_APP_ID", "")

# --- Google Sheets ---
# 認証はApplication Default Credentials(Cloud Run上では実行サービスアカウント)。
# サービスアカウントJSONキーは使わない。スコープはSheetsのみ(Driveは不要)。
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TODO_SPREADSHEET_ID = os.getenv("TODO_SPREADSHEET_ID", "")
TODO_SHEET_NAME = os.getenv("TODO_SHEET_NAME", "Todo")

TIMEZONE_NAME = "Asia/Tokyo"
