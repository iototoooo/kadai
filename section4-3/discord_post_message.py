import os

import requests
from dotenv import load_dotenv

# Discordサーバーの「サーバー設定」→「連携サービス」→「ウェブフック」で
# 通知したいチャンネル宛のWebhook URLを発行し、.env の DISCORD_WEBHOOK_URL に設定しておくこと
# （Botアカウントの作成やトークン発行は不要。Webhook URLだけで投稿できる）
load_dotenv()

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")


def post_message(content: str, webhook_url: str | None = None, username: str | None = None) -> None:
    """指定のDiscordチャンネル（Webhook URLに紐づくチャンネル）にメッセージを投稿する

    webhook_url を省略した場合は環境変数 DISCORD_WEBHOOK_URL を使用する
    username を指定すると投稿時の表示名を上書きできる
    """
    url = webhook_url or DISCORD_WEBHOOK_URL
    if not url:
        raise RuntimeError("Webhook URLが指定されていません。.env の DISCORD_WEBHOOK_URL を確認してください。")

    payload = {"content": content}
    if username:
        payload["username"] = username

    response = requests.post(url, json=payload)
    response.raise_for_status()


def main():
    print("Discord メッセージ投稿")
    print("-" * 40)

    text = input("メッセージ本文: ").strip()
    if not text:
        print("メッセージ本文は必須です。")
        return

    try:
        post_message(text)
    except requests.exceptions.HTTPError as e:
        print(f"\nHTTPエラーが発生しました: {e}")
        print(f"レスポンス: {e.response.text}")
        return
    except RuntimeError as e:
        print(f"\n{e}")
        return

    print("\nメッセージを投稿しました")


if __name__ == "__main__":
    main()
