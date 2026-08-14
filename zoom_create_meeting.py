import os
from datetime import datetime

import requests
from dotenv import load_dotenv

# Zoom App Marketplace で「Server-to-Server OAuth」アプリを作成し、
# Account ID / Client ID / Client Secret を .env に設定しておくこと
# （必須スコープ: meeting:write:meeting / meeting:write:meeting:admin など）
load_dotenv()

ACCOUNT_ID = os.environ["ZOOM_ACCOUNT_ID"]
CLIENT_ID = os.environ["ZOOM_CLIENT_ID"]
CLIENT_SECRET = os.environ["ZOOM_CLIENT_SECRET"]

TOKEN_URL = "https://zoom.us/oauth/token"
API_BASE = "https://api.zoom.us/v2"


def get_access_token() -> str:
    """Server-to-Server OAuth でアクセストークンを取得する"""
    response = requests.post(
        TOKEN_URL,
        params={"grant_type": "account_credentials", "account_id": ACCOUNT_ID},
        auth=(CLIENT_ID, CLIENT_SECRET),
    )
    response.raise_for_status()
    return response.json()["access_token"]


def create_meeting(topic: str, start_time: str, duration_minutes: int, user_id: str = "me") -> dict:
    """Zoomミーティングを作成し、ID・パスワード・参加リンクを含む情報を返す

    start_time は "YYYY-MM-DDTHH:MM:SS" 形式（例: 2026-08-20T10:00:00）
    """
    access_token = get_access_token()

    body = {
        "topic": topic,
        "type": 2,  # 2: 予約制のミーティング
        "start_time": start_time,
        "duration": duration_minutes,
        "timezone": "Asia/Tokyo",
        "password": None,  # Noneのままにすると Zoom がパスワードを自動生成する
        "settings": {
            "join_before_host": False,
            "waiting_room": True,
            "meeting_authentication": False,
        },
    }
    body = {k: v for k, v in body.items() if v is not None}

    response = requests.post(
        f"{API_BASE}/users/{user_id}/meetings",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=body,
    )
    response.raise_for_status()
    return response.json()


def main():
    print("Zoom ミーティング作成")
    print("-" * 40)

    topic = input("会議名: ").strip() or "新しい会議"

    start_time_input = input(
        "開始日時 YYYY-MM-DDTHH:MM:SS（空欄で現在時刻）: "
    ).strip()
    start_time = start_time_input or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    duration_input = input("所要時間（分、空欄で60分）: ").strip()
    duration_minutes = int(duration_input) if duration_input else 60

    try:
        meeting = create_meeting(topic, start_time, duration_minutes)
    except requests.exceptions.HTTPError as e:
        print(f"\nAPIエラーが発生しました: {e}")
        print(f"レスポンス: {e.response.text}")
        return

    print("\nミーティングを作成しました")
    print(f"会議ID: {meeting.get('id')}")
    print(f"パスワード: {meeting.get('password')}")
    print(f"参加リンク: {meeting.get('join_url')}")
    print(f"ホスト開始リンク: {meeting.get('start_url')}")


if __name__ == "__main__":
    main()
