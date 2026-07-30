import mimetypes
import os

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]
SERVICE_ACCOUNT_FILE = "service_account.json"

# 共有フォルダにアップロードする場合はフォルダIDを指定（空文字ならサービスアカウントのDrive直下）
FOLDER_ID = ""


def get_drive_service():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
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
