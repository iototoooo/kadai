from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

SCOPES = ["https://www.googleapis.com/auth/calendar"]
SERVICE_ACCOUNT_FILE = "service_account.json"

creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build("calendar", "v3", credentials=creds)

CALENDAR_ID = "iototoooo@gmail.com"


def main():
    print("Googleカレンダー 予定追加")
    print("-" * 40)

    title = input("タイトル: ").strip()

    date_str = input("日付 (例: 2026-07-25): ").strip()
    time_str = input("開始時間 (例: 10:00): ").strip()
    duration = input("所要時間（分）[デフォルト: 60]: ").strip()
    duration = int(duration) if duration else 60

    start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    end_dt = start_dt + timedelta(minutes=duration)

    start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%S") + "+09:00"
    end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%S") + "+09:00"

    event = {
        "summary": title,
        "start": {"dateTime": start_str, "timeZone": "Asia/Tokyo"},
        "end":   {"dateTime": end_str,   "timeZone": "Asia/Tokyo"},
    }

    created_event = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
    print(f"\n予定を作成しました: {created_event.get('htmlLink')}")


if __name__ == "__main__":
    main()
