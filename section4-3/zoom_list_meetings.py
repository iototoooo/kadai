from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from zoom_create_meeting import API_BASE, get_access_token

# zoom_create_meeting.py と同じ認証設定（ZOOM_ACCOUNT_ID 等）を使用する
load_dotenv()

JST = ZoneInfo("Asia/Tokyo")


def list_upcoming_meetings(user_id: str = "me") -> list[dict]:
    """今後予定されているZoomミーティング一覧を取得する（type=upcoming）

    ライブ中の会議・今後6か月以内に開始予定の会議が対象（Zoom APIの仕様）
    """
    access_token = get_access_token()
    meetings: list[dict] = []
    next_page_token = ""

    while True:
        params = {"type": "upcoming", "page_size": 300}
        if next_page_token:
            params["next_page_token"] = next_page_token

        response = requests.get(
            f"{API_BASE}/users/{user_id}/meetings",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )
        response.raise_for_status()
        data = response.json()
        meetings.extend(data.get("meetings", []))

        next_page_token = data.get("next_page_token")
        if not next_page_token:
            break

    return meetings


def parse_start_time(meeting: dict) -> datetime | None:
    """ミーティングの start_time（UTC文字列）をJSTのdatetimeに変換する

    start_time を持たない会議（一部の繰り返し設定など）は None を返す
    """
    start_time = meeting.get("start_time")
    if not start_time:
        return None
    start_time_utc = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    return start_time_utc.astimezone(JST)


def main():
    print("Zoom 予定ミーティング一覧")
    print("-" * 40)

    try:
        meetings = list_upcoming_meetings()
    except requests.exceptions.HTTPError as e:
        print(f"\nAPIエラーが発生しました: {e}")
        print(f"レスポンス: {e.response.text}")
        return

    dated = [(parse_start_time(m), m) for m in meetings]
    dated = [(t, m) for t, m in dated if t is not None]
    dated.sort(key=lambda pair: pair[0])

    if not dated:
        print("予定されているミーティングはありません")
        return

    for start, m in dated:
        print(f"{start.strftime('%Y-%m-%d %H:%M')}  {m.get('topic')}")
        print(f"  会議ID: {m.get('id')}  参加リンク: {m.get('join_url')}")


if __name__ == "__main__":
    main()
