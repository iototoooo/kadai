"""LINE Messaging API のプッシュ送信。

チャネルアクセストークンと送信先ID(userId)は TODO_LINE_CONFIG(Secret Manager由来のJSON)から読み、
ログ・例外メッセージ・画面には一切含めない。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import requests

from . import config

logger = logging.getLogger("todo_app.line")

PUSH_URL = "https://api.line.me/v2/bot/message/push"
TEXT_MAX_LENGTH = 5000


class LineNotConfiguredError(Exception):
    pass


class LineSendError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"LINE push failed: status={status_code}")
        self.status_code = status_code


@dataclass(frozen=True)
class LineConfig:
    channel_access_token: str
    to: str


def load_line_config() -> LineConfig:
    try:
        data = json.loads(config.TODO_LINE_CONFIG) if config.TODO_LINE_CONFIG else {}
    except ValueError as e:
        raise LineNotConfiguredError("TODO_LINE_CONFIG がJSONとして読めません") from e
    token = str(data.get("channel_access_token", "")).strip()
    to = str(data.get("to", "")).strip()
    if not token or not to:
        raise LineNotConfiguredError("LINEの送信設定がありません")
    return LineConfig(channel_access_token=token, to=to)


def is_configured() -> bool:
    try:
        load_line_config()
    except LineNotConfiguredError:
        return False
    return True


class LineClient:
    def __init__(self, line_config: LineConfig | None = None, session: requests.Session | None = None):
        self._config = line_config
        self._session = session or requests.Session()

    def push_text(self, text: str, retry_key: str) -> str:
        """テキストを1通送る。戻り値: "sent" / "duplicate"(同じretry_keyで受付済み)。

        X-Line-Retry-Key により、同じキーでの再送はLINE側で重複配信されない(409が返る)。
        """
        cfg = self._config or load_line_config()
        if len(text) > TEXT_MAX_LENGTH:
            text = text[: TEXT_MAX_LENGTH - 1] + "…"
        res = self._session.post(
            PUSH_URL,
            headers={
                "Authorization": f"Bearer {cfg.channel_access_token}",
                "Content-Type": "application/json",
                "X-Line-Retry-Key": retry_key,
            },
            json={"to": cfg.to, "messages": [{"type": "text", "text": text}]},
            timeout=10,
        )
        if res.status_code == 200:
            return "sent"
        if res.status_code == 409:
            return "duplicate"
        # レスポンス本文には送信先IDなどが含まれうるため、ログにはステータスのみ残す。
        logger.error("LINE push failed: status=%s", res.status_code)
        raise LineSendError(res.status_code)
