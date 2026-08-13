import os

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Google Cloud Console で「Google Meet API」を有効化しておくこと
SCOPES = [
    "https://www.googleapis.com/auth/meetings.space.created",
    "https://www.googleapis.com/auth/meetings.space.readonly",
]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token_meet.json"  # Meet専用スコープのため他スクリプトのtoken.jsonとは分離


def get_meet_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                creds = None

        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("meet", "v2", credentials=creds)


def create_meeting_space() -> dict:
    """新しいGoogle Meetミーティングスペースを作成し、参加リンクを発行する

    会議コードとリンクはGoogle側で自動生成されるため、
    APIから任意の値を指定することはできない。
    """
    service = get_meet_service()
    return service.spaces().create(body={}).execute()


def get_meeting_space(space_id_or_code: str) -> dict:
    """既存のミーティングスペース（spaceID または会議コード）から参加リンクを取得する"""
    service = get_meet_service()
    name = space_id_or_code.strip()
    if not name.startswith("spaces/"):
        name = f"spaces/{name}"
    return service.spaces().get(name=name).execute()


def main():
    print("Google Meet ミーティング作成 / 参加リンク取得")
    print("-" * 40)
    print("1: 新しいミーティングを作成する")
    print("2: 既存のミーティング（spaceIDまたは会議コード）の参加リンクを取得する")
    choice = input("選択 (1/2): ").strip()

    try:
        if choice == "2":
            key = input("spaceID または 会議コード（例: abc-defg-hij）: ").strip()
            space = get_meeting_space(key)
            print("\nミーティング情報を取得しました")
        else:
            space = create_meeting_space()
            print("\n新しいミーティングを作成しました")

        print(f"参加リンク: {space.get('meetingUri')}")
        print(f"会議コード: {space.get('meetingCode')}")
        print(f"リソース名: {space.get('name')}")
    except HttpError as e:
        print(f"\nAPIエラーが発生しました: {e}")
        print("Google Cloud ConsoleでGoogle Meet APIが有効化されているか確認してください。")


if __name__ == "__main__":
    main()
