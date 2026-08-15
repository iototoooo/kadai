import base64
import os
from email.mime.text import MIMEText

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Google Cloud Console で「Gmail API」を有効化しておくこと
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token_gmail.json"  # Gmail専用スコープのため他スクリプトのtoken.jsonとは分離


def get_gmail_service():
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

    return build("gmail", "v1", credentials=creds)


def send_email(to: str, subject: str, body: str) -> dict:
    service = get_gmail_service()

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    return (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw_message})
        .execute()
    )


def main():
    print("Gmail メール送信")
    print("-" * 40)

    to = input("宛先メールアドレス: ").strip()
    subject = input("件名: ").strip()
    print("本文（入力後、空行でEnterを押すと送信します）:")
    lines = []
    while True:
        line = input()
        if line == "":
            break
        lines.append(line)
    body = "\n".join(lines)

    try:
        sent = send_email(to, subject, body)
        print(f"\nメールを送信しました（メッセージID: {sent['id']}）")
    except HttpError as e:
        print(f"\nAPIエラーが発生しました: {e}")
        print("Google Cloud ConsoleでGmail APIが有効化されているか確認してください。")


if __name__ == "__main__":
    main()
