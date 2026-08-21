from datetime import datetime

import requests
from dotenv import load_dotenv

from line_send_message import push_message
from zoom_create_meeting import create_meeting

# zoom_create_meeting.py の認証設定（ZOOM_ACCOUNT_ID 等）と
# line_send_message.py の認証設定（LINE_CHANNEL_ACCESS_TOKEN）が両方必要
# 通知先のLINE userId/groupId/roomId を .env の LINE_DEFAULT_TO に設定しておくと入力を省略できる
load_dotenv()


def build_line_text(meeting: dict) -> str:
    """Zoomミーティング情報からLINE通知用のテキストを組み立てる"""
    lines = [
        f"「{meeting.get('topic')}」のZoomミーティングを作成しました",
        f"日時: {meeting.get('start_time')}",
        f"会議ID: {meeting.get('id')}",
        f"パスワード: {meeting.get('password')}",
        f"参加リンク: {meeting.get('join_url')}",
    ]
    return "\n".join(lines)


def create_meeting_and_notify(
    to: str,
    topic: str,
    start_time: str,
    duration_minutes: int,
    user_id: str = "me",
) -> dict:
    """Zoomミーティングを作成し、参加リンクを含む情報をLINEへ通知する"""
    meeting = create_meeting(topic, start_time, duration_minutes, user_id)
    text = build_line_text(meeting)
    push_message(to, text)
    return meeting


def main():
    print("Zoom ミーティング作成 → LINE自動通知")
    print("-" * 40)

    from line_send_message import LINE_DEFAULT_TO

    prompt = "通知先LINE ID（userId / groupId / roomId）"
    prompt += f"（未入力でデフォルト: {LINE_DEFAULT_TO}）" if LINE_DEFAULT_TO else ""
    to = input(f"{prompt}: ").strip() or LINE_DEFAULT_TO or ""
    if not to:
        print("通知先IDは必須です。")
        return

    topic = input("会議名: ").strip() or "新しい会議"

    start_time_input = input(
        "開始日時 YYYY-MM-DDTHH:MM:SS（空欄で現在時刻）: "
    ).strip()
    start_time = start_time_input or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    duration_input = input("所要時間（分、空欄で60分）: ").strip()
    duration_minutes = int(duration_input) if duration_input else 60

    try:
        meeting = create_meeting_and_notify(to, topic, start_time, duration_minutes)
    except requests.exceptions.HTTPError as e:
        print(f"\nAPIエラーが発生しました: {e}")
        print(f"レスポンス: {e.response.text}")
        return

    print("\nミーティングを作成し、LINEに通知しました")
    print(f"会議ID: {meeting.get('id')}")
    print(f"パスワード: {meeting.get('password')}")
    print(f"参加リンク: {meeting.get('join_url')}")
    print(f"ホスト開始リンク: {meeting.get('start_url')}")


if __name__ == "__main__":
    main()
