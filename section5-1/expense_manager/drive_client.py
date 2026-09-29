"""証憑画像のGoogle Drive保存。

【認証方式】OAuth 2.0ユーザー委任(drive.fileスコープ)。サービスアカウントは
個人のGoogleアカウントでは実質ストレージ容量を持たず、Driveへのファイル作成が
"storageQuotaExceeded" で失敗するため使わない。代わりに、あなた自身の
Googleアカウントへ委任したOAuthユーザー資格情報(refresh token)でDrive APIを呼ぶ。
(Google Sheetsの読み書きは引き続きサービスアカウント方式のまま、変更なし。)

drive.fileスコープは「このアプリ自身が作成したファイル/フォルダ」にのみ
恒久的にアクセスできる(単なる共有や既存フォルダの流用では対象にならない)。
そのため EXPENSE_DRIVE_ROOT_FOLDER_ID は、このOAuth資格情報自身が
scripts/authorize_drive.py で作成したフォルダのIDである必要がある。

フォルダ構造: {ROOT}/{年}/{月}/{管理番号}.{拡張子}

refresh tokenは失効・取消される可能性がある前提で設計する(「永久に有効」とは
みなさない)。失効を検知した場合は DriveAuthExpiredError を送出し、
呼び出し側(expense_service.py)がSheets書き込み前にエラーとして扱えるようにする。
"""

from __future__ import annotations

import io
import json

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from . import config

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


class DriveAuthExpiredError(Exception):
    """OAuthのrefresh tokenが失効・取消されたことを表す。再認可(scripts/authorize_drive.pyの
    再実行とSecret Manager更新)が必要であることを呼び出し元に伝える。
    """


def _build_credentials() -> UserCredentials:
    if not config.GOOGLE_DRIVE_OAUTH_JSON:
        raise RuntimeError("GOOGLE_DRIVE_OAUTH_JSON が設定されていません")
    info = json.loads(config.GOOGLE_DRIVE_OAUTH_JSON)
    return UserCredentials(
        token=None,
        refresh_token=info["refresh_token"],
        client_id=info["client_id"],
        client_secret=info["client_secret"],
        token_uri=info.get("token_uri", config.DRIVE_OAUTH_TOKEN_URI),
        scopes=config.DRIVE_OAUTH_SCOPES,
    )


def _is_invalid_grant(error: HttpError) -> bool:
    if error.resp.status not in (400, 401, 403):
        return False
    try:
        body = json.loads(error.content.decode("utf-8"))
    except (ValueError, AttributeError):
        return "invalid_grant" in str(error).lower()
    message = json.dumps(body).lower()
    return "invalid_grant" in message or "invalid_rapt" in message


class DriveClient:
    def __init__(self, credentials: UserCredentials | None = None, service: Resource | None = None):
        """credentials/serviceはテスト用の差し替え口。通常は両方Noneのまま呼び、
        credentialsはconfig.GOOGLE_DRIVE_OAUTH_JSONから自動構築する。
        """
        creds = credentials or _build_credentials()
        self._service = service or build("drive", "v3", credentials=creds, cache_discovery=False)

    def _execute(self, request):
        """Drive APIリクエストを実行し、refresh token失効時はDriveAuthExpiredErrorへ変換する。"""
        try:
            return request.execute()
        except RefreshError as e:
            raise DriveAuthExpiredError(
                "Google Driveへの保存権限(OAuth認可)が失効しています。再認可が必要です。"
            ) from e
        except HttpError as e:
            if _is_invalid_grant(e):
                raise DriveAuthExpiredError(
                    "Google Driveへの保存権限(OAuth認可)が失効しています。再認可が必要です。"
                ) from e
            raise

    def _find_or_create_folder(self, parent_id: str, name: str) -> str:
        query = (
            f"'{parent_id}' in parents and name = '{name}' and "
            f"mimeType = '{FOLDER_MIME_TYPE}' and trashed = false"
        )
        res = self._execute(
            self._service.files().list(q=query, fields="files(id, name)", spaces="drive")
        )
        files = res.get("files", [])
        if files:
            return files[0]["id"]

        metadata = {"name": name, "mimeType": FOLDER_MIME_TYPE, "parents": [parent_id]}
        created = self._execute(self._service.files().create(body=metadata, fields="id"))
        return created["id"]

    def create_root_folder(self, name: str) -> tuple[str, str]:
        """初回セットアップ専用: ルートフォルダをMy Driveの直下に新規作成する。
        このOAuth資格情報自身が作成することで、以降drive.fileスコープで
        恒久的にアクセスできるようになる(scripts/authorize_drive.pyから呼ぶ)。
        戻り値: (folder_id, webViewLink)
        """
        metadata = {"name": name, "mimeType": FOLDER_MIME_TYPE}
        created = self._execute(
            self._service.files().create(body=metadata, fields="id, webViewLink")
        )
        return created["id"], created["webViewLink"]

    def upload_receipt_image(
        self,
        *,
        year: str,
        month: str,
        management_number: str,
        file_bytes: bytes,
        content_type: str,
        extension: str,
    ) -> tuple[str, str]:
        """年/月フォルダを(無ければ作成して)特定し、{管理番号}.{拡張子}で画像をアップロードする。
        戻り値: (file_id, webViewLink)
        """
        if not config.EXPENSE_DRIVE_ROOT_FOLDER_ID:
            raise RuntimeError("EXPENSE_DRIVE_ROOT_FOLDER_ID が設定されていません")

        year_folder_id = self._find_or_create_folder(config.EXPENSE_DRIVE_ROOT_FOLDER_ID, year)
        month_folder_id = self._find_or_create_folder(year_folder_id, month)

        filename = f"{management_number}{extension}"
        media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=content_type, resumable=False)
        metadata = {"name": filename, "parents": [month_folder_id]}
        created = self._execute(
            self._service.files().create(body=metadata, media_body=media, fields="id, webViewLink")
        )
        return created["id"], created["webViewLink"]

    def delete_file(self, file_id: str) -> None:
        """アップロード済みファイルを削除する。Sheets書き込み失敗時のロールバック用
        (expense_service.py参照)。drive.fileスコープは、このアプリ自身が作成した
        ファイルの削除を許可する。
        """
        self._execute(self._service.files().delete(fileId=file_id))
