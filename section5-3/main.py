"""LINE Messaging API × Dify Chatflow 連携 Bot（Cloud Run 用 FastAPI アプリ）。

LINE → POST /webhook → Dify /chat-messages → LINE Reply API
"""

import asyncio
import json
import logging

import httpx
from fastapi import FastAPI, Request, Response

import conversation_store
import dify_api
import line_api

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("line-dify-bot")

app = FastAPI(title="line-dify-bot")

ERROR_REPLY_TEXT = "申し訳ありません、ただいま応答できませんでした。少し時間をおいてもう一度お送りください。"
EMPTY_ANSWER_TEXT = "申し訳ありません、うまく回答を作成できませんでした。別の言い方でもう一度お送りください。"


@app.get("/")
@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request) -> Response:
    body = await request.body()
    signature = request.headers.get("x-line-signature")

    try:
        valid = line_api.verify_signature(body, signature)
    except Exception:
        logger.exception("署名検証中にエラーが発生しました（LINE_CHANNEL_SECRET 未設定の可能性）")
        return Response(status_code=500)
    if not valid:
        logger.warning("x-line-signature の検証に失敗しました")
        return Response(status_code=400)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        logger.exception("Webhook ボディの JSON 解析に失敗しました")
        return Response(status_code=200)

    # LINE Developers の「検証」ボタンは events が空配列で届くので、そのまま 200 を返す
    events = payload.get("events", [])
    if events:
        async with httpx.AsyncClient() as client:
            await asyncio.gather(*(handle_event(client, event) for event in events))

    return Response(status_code=200)


def extract_text_message(event: dict) -> tuple[str, str, str] | None:
    """テキストメッセージイベントなら (replyToken, userId, text) を返す。それ以外は None。"""
    if event.get("type") != "message":
        return None
    message = event.get("message") or {}
    if message.get("type") != "text":
        return None

    reply_token = event.get("replyToken")
    user_id = (event.get("source") or {}).get("userId")
    text = message.get("text")
    if not reply_token or not user_id or not text:
        return None
    return reply_token, user_id, text


async def ask_dify(client: httpx.AsyncClient, user_id: str, text: str) -> str:
    """ユーザーのメッセージを Dify に送り、返信テキストを返す。"""
    conversation_id = await conversation_store.get_conversation_id(user_id)
    reply = await dify_api.send_chat_message(client, text, user_id, conversation_id)
    if reply.conversation_id:
        await conversation_store.save_conversation_id(user_id, reply.conversation_id)
    return reply.answer or EMPTY_ANSWER_TEXT


async def handle_event(client: httpx.AsyncClient, event: dict) -> None:
    """1イベントを処理する。例外はログに残して握りつぶし、Webhook 全体は正常終了させる。"""
    extracted = extract_text_message(event)
    if extracted is None:
        logger.info("処理対象外のイベントをスキップ: type=%s", event.get("type"))
        return
    reply_token, user_id, text = extracted

    try:
        answer = await ask_dify(client, user_id, text)
    except Exception:
        logger.exception("Dify 呼び出しに失敗しました: userId=%s", user_id)
        answer = ERROR_REPLY_TEXT

    try:
        await line_api.reply_text(client, reply_token, answer)
    except Exception:
        logger.exception("LINE への返信に失敗しました: userId=%s", user_id)
