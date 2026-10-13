"""Dify Chatflow API（POST /chat-messages）の呼び出し。"""

import logging
from dataclasses import dataclass

import httpx

from config import DIFY_API_BASE_URL, DIFY_TIMEOUT_SECONDS, get_secret

logger = logging.getLogger(__name__)


@dataclass
class DifyReply:
    answer: str
    conversation_id: str


async def send_chat_message(
    client: httpx.AsyncClient,
    query: str,
    user_id: str,
    conversation_id: str = "",
) -> DifyReply:
    """Dify にメッセージを送り、answer と conversation_id を返す。

    conversation_id を空文字にすると Dify 側で新規会話になる。
    """
    api_key = get_secret("DIFY_API_KEY")
    response = await client.post(
        f"{DIFY_API_BASE_URL}/chat-messages",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "inputs": {},
            "query": query,
            "response_mode": "blocking",
            "conversation_id": conversation_id,
            "user": user_id,
        },
        timeout=DIFY_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        logger.error("Dify API エラー: status=%s body=%s", response.status_code, response.text)
        response.raise_for_status()

    data = response.json()
    return DifyReply(
        answer=(data.get("answer") or "").strip(),
        conversation_id=data.get("conversation_id") or "",
    )
