"""環境変数から設定値を読み込む。

Secret はコードに直接書かず、Cloud Run では Secret Manager を環境変数としてマウントする。
起動時ではなく利用時に読むので、Secret 未設定でもヘルスチェックは 200 を返せる。
"""

import os

DIFY_API_BASE_URL = os.environ.get("DIFY_API_BASE_URL", "https://api.dify.ai/v1").rstrip("/")
DIFY_TIMEOUT_SECONDS = float(os.environ.get("DIFY_TIMEOUT_SECONDS", "50"))
LINE_API_BASE_URL = "https://api.line.me/v2/bot"


def get_secret(name: str) -> str:
    """環境変数から Secret を取得する。Secret Manager の値に付きがちな末尾改行は除去する。"""
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"環境変数 {name} が設定されていません")
    return value
