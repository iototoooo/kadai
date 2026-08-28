import os

import requests
from dotenv import load_dotenv

# LINE Developers (https://developers.line.biz/) でMessaging APIチャネルを作成し、
# 「Messaging API設定」タブでチャネルアクセストークン（長期）を発行して
# .env の LINE_CHANNEL_ACCESS_TOKEN に設定しておくこと
# 送信先の userId は、チャネル設定のWebhook経由で取得するか、
# 自分自身のuserIdは「Messaging API設定」タブの「あなたのユーザーID」欄で確認できる
# 毎回入力するのが手間な場合は .env の LINE_DEFAULT_TO にデフォルトの送信先IDを設定しておくと、
# 実行時に送信先IDの入力を空欄のままEnterで済ませられる
load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_DEFAULT_TO = os.environ.get("LINE_DEFAULT_TO")

API_URL = "https://api.line.me/v2/bot/message/push"


def push_message(to: str, text: str) -> None:
    """指定のLINEユーザー（またはグループ/トーク）宛にメッセージを送信する

    to はLINEの userId / groupId / roomId を指定する
    """
    response = requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        json={"to": to, "messages": [{"type": "text", "text": text}]},
    )
    response.raise_for_status()


def main():
    print("LINE メッセージ送信")
    print("-" * 40)

    prompt = "送信先ID（userId / groupId / roomId）"
    prompt += f"（未入力でデフォルト: {LINE_DEFAULT_TO}）" if LINE_DEFAULT_TO else ""
    to = input(f"{prompt}: ").strip() or LINE_DEFAULT_TO or ""
    text = input("メッセージ本文: ").strip()

    if not to or not text:
        print("送信先IDとメッセージ本文は必須です。")
        return

    try:
        push_message(to, text)
    except requests.exceptions.HTTPError as e:
        print(f"\nHTTPエラーが発生しました: {e}")
        print(f"レスポンス: {e.response.text}")
        return

    print("\nメッセージを送信しました")


if __name__ == "__main__":
    main()
