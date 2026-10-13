"""LINE Messaging API まわりの処理（署名検証・返信）。"""

import base64
import hashlib
import hmac
import logging

import httpx

from config import LINE_API_BASE_URL, get_secret

logger = logging.getLogger(__name__)

# LINE のテキストメッセージ1通あたりの上限文字数
LINE_TEXT_MAX_LENGTH = 5000


def verify_signature(body: bytes, signature: str | None) -> bool:
    """x-line-signature を LINE_CHANNEL_SECRET で検証する。"""
    if not signature:
        return False
    channel_secret = get_secret("LINE_CHANNEL_SECRET")
    digest = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


async def reply_text(client: httpx.AsyncClient, reply_token: str, text: str) -> None:
    """Reply API でテキストを1通返信する。"""
    if len(text) > LINE_TEXT_MAX_LENGTH:
        text = text[: LINE_TEXT_MAX_LENGTH - 1] + "…"

    access_token = get_secret("LINE_CHANNEL_ACCESS_TOKEN")
    response = await client.post(
        f"{LINE_API_BASE_URL}/message/reply",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": text}],
        },
        timeout=10,
    )
    if response.status_code != 200:
        logger.error("LINE Reply API エラー: status=%s body=%s", response.status_code, response.text)
        response.raise_for_status()
