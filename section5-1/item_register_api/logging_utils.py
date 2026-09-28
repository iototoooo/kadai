"""登録処理のログ出力。

Cloud Runは標準出力・標準エラー出力を自動でCloud Loggingに取り込むため、
1件のログをJSON1行として出力する(Cloud Logging上で構造化ログとして検索しやすくなる)。
"""

import json
import logging
import sys

logger = logging.getLogger("item_register_api")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


def log_registration_event(
    *,
    request_id: str,
    management_number: str,
    processed_at_jst: str,
    success: bool,
    already_registered: bool = False,
    error: str = "",
) -> None:
    payload = {
        "request_id": request_id,
        "management_number": management_number,
        "processed_at_jst": processed_at_jst,
        "success": success,
        "already_registered": already_registered,
        "error": error,
    }
    line = json.dumps(payload, ensure_ascii=False)
    if success:
        logger.info(line)
    else:
        logger.error(line)
