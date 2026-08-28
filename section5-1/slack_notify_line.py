import argparse
import json
import os
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from openai import OpenAI

# Slack App (https://api.slack.com/apps) を作成し、
# 「OAuth & Permissions」で Bot Token Scopes に channels:history（公開チャンネル）
# または groups:history（プライベートチャンネル）と users:read を追加してから
# ワークスペースにインストールし、発行された Bot User OAuth Token (xoxb-...) を
# .env の SLACK_BOT_TOKEN に設定しておくこと
# 取得したいチャンネルには Bot を招待（/invite @ボット名）しておく必要がある
# 要約には OpenAI API を使用するため .env の OPENAI_API_KEY を設定しておくこと
# LINE送信は line_send_message.py と同じ LINE_CHANNEL_ACCESS_TOKEN / LINE_DEFAULT_TO を再利用する
load_dotenv()

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_DEFAULT_TO = os.environ.get("LINE_DEFAULT_TO")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

SLACK_API_BASE = "https://slack.com/api"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
STATE_FILE = os.path.join(os.path.dirname(__file__), "slack_notify_state.json")
DEFAULT_LOOKBACK_HOURS = 24

openai_client = OpenAI(api_key=OPENAI_API_KEY)


def load_last_fetched_ts() -> str:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)["last_fetched_ts"]
    default_dt = datetime.now(timezone.utc) - timedelta(hours=DEFAULT_LOOKBACK_HOURS)
    return str(default_dt.timestamp())


def save_last_fetched_ts(ts: str) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_fetched_ts": ts}, f)


def fetch_new_messages(channel: str, oldest_ts: str) -> list[dict]:
    """指定チャンネルの oldest_ts より後の新着メッセージを古い順に返す"""
    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
    messages = []
    cursor = None
    while True:
        params = {"channel": channel, "oldest": oldest_ts, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        response = requests.get(
            f"{SLACK_API_BASE}/conversations.history", headers=headers, params=params, timeout=10
        )
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(f"Slack APIエラー: {result.get('error')}")

        messages.extend(result["messages"])
        cursor = result.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    # 入退室などのシステムメッセージを除外し、古い順に並べ替え
    messages = [m for m in messages if "subtype" not in m and m.get("text")]
    messages.sort(key=lambda m: float(m["ts"]))
    return messages


def resolve_user_names(messages: list[dict]) -> dict:
    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
    user_ids = {m["user"] for m in messages if "user" in m}
    names = {}
    for uid in user_ids:
        response = requests.get(
            f"{SLACK_API_BASE}/users.info", headers=headers, params={"user": uid}, timeout=10
        )
        result = response.json()
        if result.get("ok"):
            profile = result["user"]["profile"]
            names[uid] = profile.get("display_name") or profile.get("real_name") or uid
        else:
            names[uid] = uid
    return names


def format_messages(messages: list[dict], user_names: dict) -> str:
    lines = [f"{user_names.get(m.get('user'), 'unknown')}: {m['text']}" for m in messages]
    return "\n".join(lines)


def summarize(messages_text: str) -> str:
    response = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "あなたはSlackチャンネルのメッセージを要約するアシスタントです。"
                    "重要な情報や決定事項、依頼事項を漏らさず、簡潔な日本語の箇条書きで要約してください。"
                ),
            },
            {
                "role": "user",
                "content": f"以下はSlackチャンネルの新着メッセージです。要約してください。\n\n{messages_text}",
            },
        ],
    )
    return response.choices[0].message.content.strip()


def push_line_message(to: str, text: str) -> None:
    response = requests.post(
        LINE_PUSH_URL,
        headers={
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        json={"to": to, "messages": [{"type": "text", "text": text[:5000]}]},
        timeout=10,
    )
    response.raise_for_status()


def main():
    parser = argparse.ArgumentParser(description="Slackの新着メッセージを要約してLINEに通知する")
    parser.add_argument(
        "--channel",
        default=os.getenv("SLACK_NOTIFY_CHANNEL"),
        help="対象チャンネルID（未指定時は環境変数 SLACK_NOTIFY_CHANNEL を使用）",
    )
    parser.add_argument(
        "--to",
        default=LINE_DEFAULT_TO,
        help="LINE送信先のuserId（未指定時は環境変数 LINE_DEFAULT_TO を使用）",
    )
    args = parser.parse_args()

    if not args.channel:
        parser.error("チャンネルIDを --channel または環境変数 SLACK_NOTIFY_CHANNEL で指定してください。")
    if not args.to:
        parser.error("LINE送信先を --to または環境変数 LINE_DEFAULT_TO で指定してください。")

    oldest_ts = load_last_fetched_ts()
    fetch_started_at = str(datetime.now(timezone.utc).timestamp())

    try:
        messages = fetch_new_messages(args.channel, oldest_ts)
    except requests.exceptions.HTTPError as e:
        print(f"Slackメッセージの取得に失敗しました: {e}")
        return
    except RuntimeError as e:
        print(f"{e}")
        return

    if not messages:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 新着メッセージはありませんでした。")
        save_last_fetched_ts(fetch_started_at)
        return

    user_names = resolve_user_names(messages)
    messages_text = format_messages(messages, user_names)
    summary = summarize(messages_text)

    try:
        push_line_message(args.to, f"【Slack要約】\n{summary}")
    except requests.exceptions.HTTPError as e:
        print(f"\nLINE送信でHTTPエラーが発生しました: {e}")
        print(f"レスポンス: {e.response.text}")
        return

    save_last_fetched_ts(fetch_started_at)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 新着{len(messages)}件を要約してLINEに送信しました。")


if __name__ == "__main__":
    main()
