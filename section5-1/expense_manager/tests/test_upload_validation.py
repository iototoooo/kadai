"""アップロードファイルのサイズ・形式検証(upload_validation.py)を検証する。"""

import pytest

from expense_manager import config
from expense_manager.upload_validation import UploadValidationError, validate_upload


def test_valid_jpeg_within_size_limit_passes():
    validate_upload(b"x" * 1024, "image/jpeg")  # 例外が発生しなければOK


def test_oversized_file_is_rejected_with_safe_message():
    oversized = b"x" * (config.MAX_UPLOAD_FILE_SIZE_BYTES + 1)
    with pytest.raises(UploadValidationError) as exc_info:
        validate_upload(oversized, "image/jpeg")
    message = str(exc_info.value)
    assert "大きすぎます" in message
    assert "15MB" in message


def test_file_exactly_at_limit_is_accepted():
    exactly_at_limit = b"x" * config.MAX_UPLOAD_FILE_SIZE_BYTES
    validate_upload(exactly_at_limit, "image/jpeg")  # 例外が発生しなければOK


def test_unsupported_content_type_is_rejected():
    with pytest.raises(UploadValidationError) as exc_info:
        validate_upload(b"small", "application/zip")
    assert "対応していないファイル形式" in str(exc_info.value)


def test_missing_content_type_is_rejected():
    with pytest.raises(UploadValidationError):
        validate_upload(b"small", None)


@pytest.mark.parametrize(
    "content_type",
    ["image/jpeg", "image/png", "image/webp", "image/heic", "application/pdf"],
)
def test_all_currently_supported_content_types_are_allowed(content_type):
    validate_upload(b"small", content_type)  # 例外が発生しなければOK
