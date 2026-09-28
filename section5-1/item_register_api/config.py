"""環境変数からの設定読み込み。

認証情報や書き込み先はコードに直書きせず、すべて環境変数(または .env)から読む。
既存の mercari_to_sheets.py と同じ環境変数名を使い、設定を使い回せるようにしている。
"""

import os

from dotenv import load_dotenv

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# まずこのモジュール専用の .env を読み、次にリポジトリ直下の .env で不足分を補う。
load_dotenv(os.path.join(SCRIPT_DIR, ".env"))
load_dotenv()

# ローカル実行時のデフォルト: リポジトリ直下の section4-3/service_account.json
DEFAULT_SERVICE_ACCOUNT_FILE = os.path.join(SCRIPT_DIR, "..", "..", "section4-3", "service_account.json")

# Cloud Run では Secret Manager 等からサービスアカウントJSONの中身を直接
# 環境変数に入れる運用を想定し、こちらが設定されていれば優先して使う。
GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE", DEFAULT_SERVICE_ACCOUNT_FILE)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SPREADSHEET_ID = os.getenv("MERCARI_SHEETS_SPREADSHEET_ID", "1xMq7gy4d9nPGRGLCX1bltXWxBKXDT1rr66za7zvpmGQ")
SHEET_NAME = os.getenv("ITEM_REGISTER_SHEET_NAME", "商品管理")
REQUEST_LOG_SHEET_NAME = os.getenv("ITEM_REGISTER_LOG_SHEET_NAME", "登録ログ(自動)")

# GPT Actions からのリクエストを認証するための任意のAPIキー。
# 未設定の場合は認証チェックをスキップする(ローカル検証用)。本番では必ず設定すること。
API_KEY = os.getenv("ITEM_REGISTER_API_KEY")

TIMEZONE_NAME = "Asia/Tokyo"
