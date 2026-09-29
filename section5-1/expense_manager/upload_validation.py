"""アップロードされたレシート画像/PDFの安全性チェック(サイズ・形式)。

Gemini API・Google Driveへ送信する前に、main.pyのルートハンドラ内で使う。
"""

from __future__ import annotations

from typing import Optional

from . import config
from .expense_service import EXTENSION_BY_CONTENT_TYPE

# アプリが実際に処理できる(EXTENSION_BY_CONTENT_TYPEで拡張子が定義されている)
# content_typeのみを許可する。ブラウザ側のaccept属性はUIヒントに過ぎず、
# サーバー側でも独立して検証する。
ALLOWED_UPLOAD_CONTENT_TYPES = frozenset(EXTENSION_BY_CONTENT_TYPE.keys())


class UploadValidationError(Exception):
    """アップロードファイルのサイズ・形式が不正なことを表す。

    メッセージはユーザー画面にそのまま表示して問題ない、安全な日本語文言のみを保持する。
    """


def validate_upload(image_bytes: bytes, content_type: Optional[str]) -> None:
    """サイズ・形式が不正な場合はUploadValidationErrorを送出する。問題なければ何もしない。"""
    if len(image_bytes) > config.MAX_UPLOAD_FILE_SIZE_BYTES:
        limit_mb = config.MAX_UPLOAD_FILE_SIZE_BYTES // (1024 * 1024)
        raise UploadValidationError(
            f"ファイルサイズが大きすぎます(上限: {limit_mb}MB)。画像を縮小するか、別の写真でお試しください。"
        )
    if not content_type or content_type not in ALLOWED_UPLOAD_CONTENT_TYPES:
        raise UploadValidationError(
            "対応していないファイル形式です。JPEG/PNG/WEBP/HEIC画像またはPDFファイルを選択してください。"
        )
