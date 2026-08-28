import mimetypes
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"

# アップロード先フォルダID（空文字なら自分のDrive直下）
FOLDER_ID = "1SBKgN20BhgPd0oFEba76i8U-fj1jemKF"


def get_drive_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def upload_file(local_file_path: str, folder_id: str = FOLDER_ID) -> dict:
    if not os.path.isfile(local_file_path):
        raise FileNotFoundError(f"ファイルが見つかりません: {local_file_path}")

    service = get_drive_service()
    file_name = os.path.basename(local_file_path)
    mime_type, _ = mimetypes.guess_type(local_file_path)
    mime_type = mime_type or "application/octet-stream"

    file_metadata = {"name": file_name}
    if folder_id:
        file_metadata["parents"] = [folder_id]

    media = MediaFileUpload(local_file_path, mimetype=mime_type, resumable=True)
    uploaded_file = (
        service.files()
        .create(body=file_metadata, media_body=media, fields="id, name, webViewLink")
        .execute()
    )
    return uploaded_file


def main():
    print("Google Drive ファイルアップロード")
    print("-" * 40)

    local_file_path = input("アップロードするファイルのパス: ").strip().strip('"')
    folder_id = input("アップロード先フォルダID（省略可）: ").strip()

    uploaded_file = upload_file(local_file_path, folder_id or FOLDER_ID)

    print(f"\nアップロード完了: {uploaded_file['name']}")
    print(f"ファイルID: {uploaded_file['id']}")
    print(f"URL: {uploaded_file.get('webViewLink', '（URLなし）')}")


if __name__ == "__main__":
    main()
