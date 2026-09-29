"""環境変数からの設定読み込み。

item_register_api/config.py と同じ方針: 認証情報や書き込み先はコードに直書きせず、
すべて環境変数(または .env)から読む。import時点では値の有無を検証しない
(未設定でもアプリの起動・ルーティング自体は失敗させず、実際にその値を使う
処理が呼ばれた時点で初めてエラーにする)。
"""

import os

from dotenv import load_dotenv

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(SCRIPT_DIR, ".env"))
load_dotenv()

# --- Firebase Authentication (Googleサインイン、許可アカウント1件のみ) ---
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
ALLOWED_LOGIN_EMAIL = os.getenv("ALLOWED_LOGIN_EMAIL")
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "expense_manager_session")
SESSION_EXPIRES_SECONDS = 14 * 24 * 60 * 60  # 14日

# Firebase Web SDK向けの公開設定値(ブラウザに渡って問題ない値のみ)。
# ビルド時埋め込みは不要(サーバーサイドレンダリングのテンプレートに実行時に埋め込むため)。
FIREBASE_WEB_API_KEY = os.getenv("FIREBASE_WEB_API_KEY", "")
FIREBASE_WEB_AUTH_DOMAIN = os.getenv("FIREBASE_WEB_AUTH_DOMAIN", "")
FIREBASE_WEB_APP_ID = os.getenv("FIREBASE_WEB_APP_ID", "")

# --- Gemini API (Google AI Studio APIキー) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# 使用モデルはコードに固定せず環境変数で切り替え可能にする(要件通り)。
# デフォルト値は2026-09-28時点でGoogle公式ドキュメント(ai.google.dev/gemini-api/docs/models)を
# 確認して設定したもの。以前のデフォルト値だった gemini-2.0-flash は同時点で
# "Shut down"(提供終了)と明記されていたため変更した。無料ティアの対象モデルは
# 今後もGoogle側の提供状況により変わるため、デプロイ前に必ず最新状況を
# Google AI Studio等で確認し、必要であれば環境変数 GEMINI_MODEL で上書きすること。
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
# 第1モデルが一時エラー(3回リトライ後も失敗)、または日次クォータ超過等で利用できない場合に
# 自動的に切り替える第2モデル。空文字/GEMINI_MODELと同一の場合はフォールバックを行わない。
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")

# --- Google Sheets / Drive (サービスアカウント、item-register-apiと共通の想定) ---
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
DEFAULT_SERVICE_ACCOUNT_FILE = os.path.join(SCRIPT_DIR, "..", "..", "section4-3", "service_account.json")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", DEFAULT_SERVICE_ACCOUNT_FILE)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# 新規作成予定のスプレッドシート(未作成の間は空文字のまま)。
EXPENSE_SPREADSHEET_ID = os.getenv("EXPENSE_SPREADSHEET_ID", "")
EXPENSE_SHEET_NAME = os.getenv("EXPENSE_SHEET_NAME", "経費")
EXPENSE_SUMMARY_SHEET_NAME = os.getenv("EXPENSE_SUMMARY_SHEET_NAME", "集計")

# Google Driveの証憑保存ルートフォルダID。
# このフォルダは下記のOAuthユーザー資格情報自身が作成したものである必要がある
# (drive.fileスコープは「このアプリが作成した/ユーザーがPickerで開いたファイル」にしか
# アクセスできないため。サービスアカウント作成物や単なる共有では対象にならない)。
EXPENSE_DRIVE_ROOT_FOLDER_ID = os.getenv("EXPENSE_DRIVE_ROOT_FOLDER_ID", "")

# --- Google Drive専用のOAuth 2.0ユーザー委任資格情報 ---
# サービスアカウントは個人のGoogleアカウントでは実質ストレージ容量を持たず、
# Driveへのファイル作成が "storageQuotaExceeded" で失敗するため、Drive操作のみ
# あなた自身のGoogleアカウントに委任したOAuthユーザー資格情報を使う。
# Sheetsの読み書きは引き続き上記のサービスアカウント方式を使う(変更なし)。
#
# GOOGLE_DRIVE_OAUTH_JSON の中身: 初回認可スクリプト(scripts/authorize_drive.py)が
# 出力するJSON文字列 {"refresh_token": ..., "client_id": ..., "client_secret": ...,
# "token_uri": "https://oauth2.googleapis.com/token"}。
GOOGLE_DRIVE_OAUTH_JSON = os.getenv("GOOGLE_DRIVE_OAUTH_JSON")

# drive.file: 非機密スコープ(Restricted scopeではない)。このアプリが作成した
# ファイル/フォルダにのみアクセスできる、最小権限のスコープ。
DRIVE_OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
DRIVE_OAUTH_TOKEN_URI = "https://oauth2.googleapis.com/token"

TIMEZONE_NAME = "Asia/Tokyo"

# アップロードファイル(レシート画像/PDF)のサイズ上限。Gemini/Driveへ送信する前に
# main.py側で拒否するために使う。以下を踏まえて15MBに設定している:
# - Gemini APIへのinlineデータは合計リクエストサイズ約20MBが上限(base64化で約33%膨張するため、
#   元ファイルはこれより十分小さくする必要がある)。
# - Cloud Runの既定のリクエストサイズ上限は32MB。
# - Cloud Runのメモリ上限(512Mi)に対し、読み込み・base64変換等での複数回のコピーが
#   発生しても安全な範囲に収める必要がある。
# - 一般的なスマホ写真(iPhoneのHEICは概ね1〜4MB、高解像度JPEGでも数MB〜10MB程度)であれば
#   通常の撮影で十分収まるサイズ。
MAX_UPLOAD_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15MB

# 「登録する」処理中に発生しうる同時実行を避けるため、Cloud Runへのデプロイ時は
# --concurrency=1 --max-instances=1 を推奨(item-register-apiと同じ理由)。
