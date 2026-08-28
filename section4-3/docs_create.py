import os

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/documents"]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"


def get_docs_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                # 保存済みのリフレッシュトークンが失効/取り消し済み。ブラウザ認証をやり直す。
                creds = None

        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("docs", "v1", credentials=creds)


def create_document(title: str, text: str) -> dict:
    service = get_docs_service()

    document = service.documents().create(body={"title": title}).execute()
    document_id = document["documentId"]

    requests = [
        {
            "insertText": {
                "location": {"index": 1},
                "text": text,
            }
        }
    ]
    service.documents().batchUpdate(
        documentId=document_id, body={"requests": requests}
    ).execute()

    return document


def main():
    print("Google Docs 新規ドキュメント作成")
    print("-" * 40)

    title = input("ドキュメントのタイトル: ").strip()
    text = input("挿入するテキスト: ").strip()

    document = create_document(title, text)
    document_id = document["documentId"]

    print(f"\nドキュメントを作成しました: {document['title']}")
    print(f"ドキュメントID: {document_id}")
    print(f"URL: https://docs.google.com/document/d/{document_id}/edit")


if __name__ == "__main__":
    main()
