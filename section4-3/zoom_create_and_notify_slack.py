from datetime import datetime

import requests
from dotenv import load_dotenv

from slack_post_message import post_message
from zoom_create_meeting import create_meeting

# zoom_create_meeting.py の認証設定（ZOOM_ACCOUNT_ID 等）と
# slack_post_message.py の認証設定（SLACK_BOT_TOKEN）が両方必要
# 投稿先チャンネルには Bot を招待（/invite @ボット名）しておくこと
load_dotenv()


def build_slack_text(meeting: dict) -> str:
    """Zoomミーティング情報からSlack投稿用のテキストを組み立てる"""
    lines = [
        f"*{meeting.get('topic')}* のZoomミーティングを作成しました",
        f"日時: {meeting.get('start_time')}",
        f"会議ID: {meeting.get('id')}",
        f"パスワード: {meeting.get('password')}",
        f"参加リンク: {meeting.get('join_url')}",
    ]
    return "\n".join(lines)


def create_meeting_and_notify(
    channel: str,
    topic: str,
    start_time: str,
    duration_minutes: int,
    user_id: str = "me",
) -> tuple[dict, dict]:
    """Zoomミーティングを作成し、参加リンクを含む情報をSlackチャンネルへ投稿する"""
    meeting = create_meeting(topic, start_time, duration_minutes, user_id)
    text = build_slack_text(meeting)
    slack_result = post_message(channel, text)
    return meeting, slack_result


def main():
    print("Zoom ミーティング作成 → Slack自動共有")
    print("-" * 40)

    channel = input("共有先Slackチャンネル（例: #general または C0123456789）: ").strip()
    if not channel:
        print("共有先チャンネルは必須です。")
        return

    topic = input("会議名: ").strip() or "新しい会議"

    start_time_input = input(
        "開始日時 YYYY-MM-DDTHH:MM:SS（空欄で現在時刻）: "
    ).strip()
    start_time = start_time_input or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    duration_input = input("所要時間（分、空欄で60分）: ").strip()
    duration_minutes = int(duration_input) if duration_input else 60

    try:
        meeting, slack_result = create_meeting_and_notify(
            channel, topic, start_time, duration_minutes
        )
    except requests.exceptions.HTTPError as e:
        print(f"\nAPIエラーが発生しました: {e}")
        print(f"レスポンス: {e.response.text}")
        return
    except RuntimeError as e:
        print(f"\nSlackへの投稿に失敗しました: {e}")
        return

    print("\nミーティングを作成し、Slackに共有しました")
    print(f"会議ID: {meeting.get('id')}")
    print(f"パスワード: {meeting.get('password')}")
    print(f"参加リンク: {meeting.get('join_url')}")
    print(f"ホスト開始リンク: {meeting.get('start_url')}")
    print(f"投稿先チャンネル: {slack_result.get('channel')}")


if __name__ == "__main__":
    main()
