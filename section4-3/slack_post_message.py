import os

import requests
from dotenv import load_dotenv

# Slack App (https://api.slack.com/apps) を作成し、
# 「OAuth & Permissions」で Bot Token Scopes に chat:write を追加してからワークスペースにインストールし、
# 発行された Bot User OAuth Token (xoxb-...) を .env の SLACK_BOT_TOKEN に設定しておくこと
# 投稿したいチャンネルには Bot を招待（/invite @ボット名）しておく必要がある
load_dotenv()

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]

API_URL = "https://slack.com/api/chat.postMessage"


def post_message(channel: str, text: str) -> dict:
    """指定のSlackチャンネルにメッセージを投稿する

    channel はチャンネルID（例: C0123456789）またはチャンネル名（例: #general）を指定できる
    """
    response = requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json={"channel": channel, "text": text},
    )
    response.raise_for_status()
    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(f"Slack APIエラー: {result.get('error')}")

    return result


def main():
    print("Slack メッセージ投稿")
    print("-" * 40)

    channel = input("投稿先チャンネル（例: #general または C0123456789）: ").strip()
    text = input("メッセージ本文: ").strip()

    if not channel or not text:
        print("チャンネルとメッセージ本文は必須です。")
        return

    try:
        result = post_message(channel, text)
    except requests.exceptions.HTTPError as e:
        print(f"\nHTTPエラーが発生しました: {e}")
        print(f"レスポンス: {e.response.text}")
        return
    except RuntimeError as e:
        print(f"\n{e}")
        return

    print("\nメッセージを投稿しました")
    print(f"チャンネル: {result.get('channel')}")
    print(f"投稿時刻(ts): {result.get('ts')}")


if __name__ == "__main__":
    main()
