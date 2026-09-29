"""gemini_client.py のリトライ・フォールバック・エラーハンドリング・安全な
ユーザー向けメッセージを実際のGemini APIに接続せず検証する。
google.genai.Client自体をフェイクに差し替える。
"""

import io
import json
import logging
from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from expense_manager import gemini_client

VALID_JSON_RESPONSE = json.dumps(
    {
        "transaction_date": "2026-09-15",
        "payee": "サンプル文具店",
        "amount": 1200,
        "tax_amount": 109,
        "tax_rate": "10%",
        "invoice_registration_number": None,
        "description": "ノート・ペン",
        "payment_method": "現金",
        "account_category": "消耗品費",
        "business_segment": "共通経費",
        "memo": None,
    }
)


class FakeModels:
    def __init__(self, responses):
        """responses: Exceptionまたは応答テキストのリスト。呼び出しごとに先頭から消費する。"""
        self._responses = list(responses)
        self.call_count = 0

    def generate_content(self, *, model, contents, config):
        self.call_count += 1
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(text=item)


class FakeClient:
    def __init__(self, responses):
        self.models = FakeModels(responses)


def _server_error(status_code: int, status_text: str = "UNAVAILABLE", message: str = "temporary error") -> genai_errors.APIError:
    return genai_errors.ServerError(status_code, {"message": message, "status": status_text})


def _client_error(status_code: int, status_text: str = "RESOURCE_EXHAUSTED", message: str = "temporary error") -> genai_errors.APIError:
    return genai_errors.ClientError(status_code, {"message": message, "status": status_text})


def _patch_client(monkeypatch, responses) -> FakeClient:
    """単一モデルのリトライ挙動だけを検証するテスト用。フォールバックは無効化する
    (GEMINI_FALLBACK_MODELをGEMINI_MODELと同一にし、フォールバックが発生しないようにする)。
    """
    fake_client = FakeClient(responses)
    monkeypatch.setattr(gemini_client, "_get_client", lambda: fake_client)
    # テストを高速化するため、実際の待機は行わない。
    monkeypatch.setattr(gemini_client, "_sleep_with_backoff", lambda attempt_index: None)
    monkeypatch.setattr(gemini_client.config, "GEMINI_MODEL", "primary-model")
    monkeypatch.setattr(gemini_client.config, "GEMINI_FALLBACK_MODEL", "primary-model")
    return fake_client


class FakeModelsMultiModel:
    """モデル名ごとに異なる応答キューを持つフェイク(フォールバック挙動の検証用)。"""

    def __init__(self, responses_by_model: dict):
        self._responses_by_model = {k: list(v) for k, v in responses_by_model.items()}
        self.calls: list[str] = []  # 呼び出されたモデル名を順番に記録する

    def generate_content(self, *, model, contents, config):
        self.calls.append(model)
        queue = self._responses_by_model.get(model)
        if not queue:
            raise AssertionError(f"想定外の呼び出し: model={model} に対する応答キューが空です")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(text=item)


class FakeClientMultiModel:
    def __init__(self, responses_by_model: dict):
        self.models = FakeModelsMultiModel(responses_by_model)


def _patch_fallback_client(
    monkeypatch, responses_by_model: dict, primary_model: str = "primary-model", fallback_model: str = "fallback-model"
) -> FakeClientMultiModel:
    fake_client = FakeClientMultiModel(responses_by_model)
    monkeypatch.setattr(gemini_client, "_get_client", lambda: fake_client)
    monkeypatch.setattr(gemini_client, "_sleep_with_backoff", lambda attempt_index: None)
    monkeypatch.setattr(gemini_client.config, "GEMINI_MODEL", primary_model)
    monkeypatch.setattr(gemini_client.config, "GEMINI_FALLBACK_MODEL", fallback_model)
    return fake_client


def _daily_quota_exhausted_429(message: str = "quota exceeded") -> genai_errors.APIError:
    """本番環境で実際に確認した構造(QuotaFailure.violations[].quotaIdに"PerDay"を
    含む)を再現した429エラー。"""
    return genai_errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "message": message,
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}],
                    }
                ],
            }
        },
    )


def _ambiguous_429(message: str = "rate limited, please retry shortly") -> genai_errors.APIError:
    """quotaId等の構造化情報が無く、日次クォータ超過かどうか確実に判定できない429。"""
    return genai_errors.ClientError(429, {"message": message, "status": "RESOURCE_EXHAUSTED"})


def test_503_then_success_retries_and_returns_result(monkeypatch):
    fake_client = _patch_client(monkeypatch, [_server_error(503), VALID_JSON_RESPONSE])

    result = gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert result["payee"] == "サンプル文具店"
    assert result["amount"] == 1200
    assert fake_client.models.call_count == 2


def test_503_persists_exhausts_max_attempts_and_raises_safe_error(monkeypatch):
    fake_client = _patch_client(
        monkeypatch,
        [_server_error(503) for _ in range(gemini_client.MAX_ATTEMPTS)],
    )

    with pytest.raises(gemini_client.GeminiAnalysisError) as exc_info:
        gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert fake_client.models.call_count == gemini_client.MAX_ATTEMPTS
    message = str(exc_info.value)
    assert message == "AI解析が混み合っています。しばらくしてからもう一度お試しください。"


def test_429_retries_then_succeeds(monkeypatch):
    fake_client = _patch_client(monkeypatch, [_client_error(429), VALID_JSON_RESPONSE])

    result = gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert result["amount"] == 1200
    assert fake_client.models.call_count == 2


def test_502_is_retried_then_succeeds(monkeypatch):
    fake_client = _patch_client(monkeypatch, [_server_error(502), VALID_JSON_RESPONSE])

    result = gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert result["payee"] == "サンプル文具店"
    assert fake_client.models.call_count == 2


def test_504_is_retried_then_succeeds(monkeypatch):
    fake_client = _patch_client(monkeypatch, [_server_error(504), VALID_JSON_RESPONSE])

    result = gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert result["payee"] == "サンプル文具店"
    assert fake_client.models.call_count == 2


def test_non_retryable_client_error_fails_immediately(monkeypatch):
    # 400(INVALID_ARGUMENT)はリトライ対象(429/500/502/503/504)に含まれない。
    fake_client = _patch_client(monkeypatch, [_client_error(400, "INVALID_ARGUMENT")])

    with pytest.raises(gemini_client.GeminiAnalysisError):
        gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert fake_client.models.call_count == 1


def test_non_api_exception_fails_immediately_without_retry(monkeypatch):
    # JSON抽出失敗など、APIError以外の例外もリトライ対象外として即終了する。
    fake_client = _patch_client(monkeypatch, ["not-valid-json-and-no-braces"])

    with pytest.raises(gemini_client.GeminiAnalysisError):
        gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert fake_client.models.call_count == 1


def test_user_facing_message_never_contains_raw_gemini_error_details(monkeypatch):
    secret_like_text = "api_key=SECRET_TOKEN_SHOULD_NOT_LEAK internal-stack-trace-detail"
    responses = [
        _server_error(503, message=secret_like_text) for _ in range(gemini_client.MAX_ATTEMPTS)
    ]
    _patch_client(monkeypatch, responses)

    with pytest.raises(gemini_client.GeminiAnalysisError) as exc_info:
        gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    message = str(exc_info.value)
    assert secret_like_text not in message
    assert "503" not in message
    assert "UNAVAILABLE" not in message


# --- フォールバック(第1モデル→第2モデル)のテスト ---


def test_primary_model_success_does_not_trigger_fallback(monkeypatch):
    fake_client = _patch_fallback_client(monkeypatch, {"primary-model": [VALID_JSON_RESPONSE]})

    result = gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert result["payee"] == "サンプル文具店"
    assert fake_client.models.calls == ["primary-model"]


def test_primary_transient_error_retries_then_succeeds_without_fallback(monkeypatch):
    """第1モデルが一時エラー後にリトライで成功した場合、第2モデルへは一切
    呼び出されないこと。"""
    fake_client = _patch_fallback_client(
        monkeypatch,
        {
            "primary-model": [_server_error(503), VALID_JSON_RESPONSE],
            "fallback-model": [VALID_JSON_RESPONSE],
        },
    )

    result = gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert result["payee"] == "サンプル文具店"
    assert fake_client.models.calls == ["primary-model", "primary-model"]


def test_primary_non_transient_400_does_not_fallback(monkeypatch):
    """400(非一時エラー)では、第1モデルのリトライも第2モデルへのフォールバックも
    行わず、即座に安全なエラーになること。"""
    fake_client = _patch_fallback_client(
        monkeypatch,
        {
            "primary-model": [_client_error(400, "INVALID_ARGUMENT")],
            "fallback-model": [VALID_JSON_RESPONSE],
        },
    )

    with pytest.raises(gemini_client.GeminiAnalysisError) as exc_info:
        gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert str(exc_info.value) == "AI解析が混み合っています。しばらくしてからもう一度お試しください。"
    # 第2モデルは一度も呼ばれていない(無駄なフォールバックをしない)。
    assert fake_client.models.calls == ["primary-model"]


def test_primary_503_exhausts_retries_then_fallback_succeeds(monkeypatch):
    fake_client = _patch_fallback_client(
        monkeypatch,
        {
            "primary-model": [_server_error(503), _server_error(503)],
            "fallback-model": [VALID_JSON_RESPONSE],
        },
    )

    result = gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert result["payee"] == "サンプル文具店"
    assert fake_client.models.calls == ["primary-model"] * gemini_client.MAX_ATTEMPTS + ["fallback-model"]


def test_primary_daily_quota_exhausted_skips_retry_and_falls_back_immediately(monkeypatch):
    fake_client = _patch_fallback_client(
        monkeypatch,
        {
            "primary-model": [_daily_quota_exhausted_429()],
            "fallback-model": [VALID_JSON_RESPONSE],
        },
    )

    result = gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert result["payee"] == "サンプル文具店"
    # 日次クォータ超過だと確実に判定できた場合、primary-modelへは1回しか呼ばれない
    # (2回目・3回目のリトライを行わず、即座にfallback-modelへ切り替わる)。
    assert fake_client.models.calls == ["primary-model", "fallback-model"]


def test_primary_ambiguous_429_is_retried_normally_not_treated_as_daily_quota(monkeypatch):
    fake_client = _patch_fallback_client(
        monkeypatch,
        {
            "primary-model": [_ambiguous_429(), _ambiguous_429()],
            "fallback-model": [VALID_JSON_RESPONSE],
        },
    )

    result = gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert result["payee"] == "サンプル文具店"
    # quotaId等の構造化情報が無く日次クォータ超過だと確実に判定できない429は、
    # 安全側として通常の一時エラーと同様にprimary-modelへMAX_ATTEMPTS回リトライしてから
    # フォールバックする(早まって切り替えない)。
    assert fake_client.models.calls == ["primary-model"] * gemini_client.MAX_ATTEMPTS + ["fallback-model"]


def test_fallback_model_retries_on_503_then_succeeds(monkeypatch):
    fake_client = _patch_fallback_client(
        monkeypatch,
        {
            "primary-model": [_server_error(503), _server_error(503)],
            "fallback-model": [_server_error(503), VALID_JSON_RESPONSE],
        },
    )

    result = gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert result["payee"] == "サンプル文具店"
    assert (
        fake_client.models.calls
        == ["primary-model"] * gemini_client.MAX_ATTEMPTS + ["fallback-model"] * gemini_client.MAX_ATTEMPTS
    )


def test_both_models_fail_returns_safe_japanese_error(monkeypatch):
    secret_like_text = "internal detail api_key=SHOULD_NOT_LEAK"
    fake_client = _patch_fallback_client(
        monkeypatch,
        {
            "primary-model": [_server_error(503, message=secret_like_text)] * gemini_client.MAX_ATTEMPTS,
            "fallback-model": [_server_error(503, message=secret_like_text)] * gemini_client.MAX_ATTEMPTS,
        },
    )

    with pytest.raises(gemini_client.GeminiAnalysisError) as exc_info:
        gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    message = str(exc_info.value)
    assert message == "AI解析が混み合っています。しばらくしてからもう一度お試しください。"
    assert secret_like_text not in message
    assert (
        fake_client.models.calls
        == ["primary-model"] * gemini_client.MAX_ATTEMPTS + ["fallback-model"] * gemini_client.MAX_ATTEMPTS
    )


def test_no_fallback_configured_fails_immediately_without_trying_second_model(monkeypatch):
    """GEMINI_FALLBACK_MODELが未設定(空文字)の場合、第1モデル失敗時点で
    フォールバックを試みず即座に安全なエラーになること。"""
    fake_client = _patch_fallback_client(
        monkeypatch,
        {"primary-model": [_server_error(503)] * gemini_client.MAX_ATTEMPTS},
        fallback_model="",
    )

    with pytest.raises(gemini_client.GeminiAnalysisError):
        gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert fake_client.models.calls == ["primary-model"] * gemini_client.MAX_ATTEMPTS


def test_logs_do_not_contain_secrets_or_raw_gemini_error_during_fallback(monkeypatch):
    """フォールバック発生時のログに、Geminiの生エラー内容が含まれないこと。
    一方でモデル名・フォールバック有無等の診断に必要な情報は記録されていること。
    """
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    gemini_client.logger.addHandler(handler)
    try:
        secret_like_text = "api_key=SECRET_SHOULD_NOT_APPEAR internal-stack-trace-detail"
        _patch_fallback_client(
            monkeypatch,
            {
                "primary-model": [_server_error(503, message=secret_like_text)] * gemini_client.MAX_ATTEMPTS,
                "fallback-model": [_server_error(503, message=secret_like_text)] * gemini_client.MAX_ATTEMPTS,
            },
        )
        with pytest.raises(gemini_client.GeminiAnalysisError):
            gemini_client.analyze_receipt_image(b"img", "image/jpeg")
        log_output = log_stream.getvalue()
    finally:
        gemini_client.logger.removeHandler(handler)

    assert secret_like_text not in log_output
    assert "primary-model" in log_output
    assert "fallback-model" in log_output


# --- 複数支払方法対応(プロンプト)のテスト ---


def test_prompt_instructs_multiple_payment_methods_without_guessing():
    prompt = gemini_client._get_prompt()

    assert "現金 2,128円 / Usappyポイント 200円" in prompt
    assert "推測" in prompt


def test_analyze_receipt_image_passes_through_multiple_payment_method_string(monkeypatch):
    multi_payment_response = json.dumps(
        {
            "transaction_date": "2026-09-29",
            "payee": "ガソリンスタンド",
            "amount": 2328,
            "tax_amount": 211,
            "tax_rate": "10%",
            "invoice_registration_number": None,
            "description": "ガソリン代",
            "payment_method": "現金 2,128円 / Usappyポイント 200円",
            "account_category": "旅費交通費",
            "business_segment": "共通経費",
            "memo": None,
        }
    )
    _patch_client(monkeypatch, [multi_payment_response])

    result = gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert result["payment_method"] == "現金 2,128円 / Usappyポイント 200円"
    assert result["amount"] == 2328


# --- 8%・10%混在税率対応(プロンプト)のテスト ---


def test_prompt_instructs_tax_rate_breakdown_without_guessing_and_keeps_both_rates():
    prompt = gemini_client._get_prompt()

    assert "tax_rate_10_base" in prompt
    assert "tax_rate_10_amount" in prompt
    assert "tax_rate_8_base" in prompt
    assert "tax_rate_8_amount" in prompt
    assert "逆算" in prompt
    assert "両方とも出力" in prompt


def test_field_keys_include_tax_rate_breakdown_fields():
    for key in ("tax_rate_10_base", "tax_rate_10_amount", "tax_rate_8_base", "tax_rate_8_amount"):
        assert key in gemini_client.FIELD_KEYS


def test_analyze_receipt_image_passes_through_mixed_tax_rate_breakdown(monkeypatch):
    """ダイソーの例(合計2,307円、消費税合計202円、10%税額170円、8%税額32円)を想定。"""
    mixed_tax_response = json.dumps(
        {
            "transaction_date": "2026-09-29",
            "payee": "ダイソー",
            "amount": 2307,
            "tax_amount": 202,
            "tax_rate": "10%・8%",
            "tax_rate_10_base": 1700,
            "tax_rate_10_amount": 170,
            "tax_rate_8_base": 400,
            "tax_rate_8_amount": 32,
            "invoice_registration_number": None,
            "description": "日用品",
            "payment_method": "現金",
            "account_category": "消耗品費",
            "business_segment": "共通経費",
            "memo": None,
        }
    )
    _patch_client(monkeypatch, [mixed_tax_response])

    result = gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert result["tax_amount"] == 202
    assert result["tax_rate"] == "10%・8%"
    assert result["tax_rate_10_base"] == 1700
    assert result["tax_rate_10_amount"] == 170
    assert result["tax_rate_8_base"] == 400
    assert result["tax_rate_8_amount"] == 32


def test_analyze_receipt_image_single_rate_leaves_other_rate_fields_none(monkeypatch):
    single_rate_response = json.dumps(
        {
            "transaction_date": "2026-09-29",
            "payee": "サンプル文具店",
            "amount": 1200,
            "tax_amount": 109,
            "tax_rate": "10%",
            "tax_rate_10_base": 1091,
            "tax_rate_10_amount": 109,
            "tax_rate_8_base": None,
            "tax_rate_8_amount": None,
            "invoice_registration_number": None,
            "description": "ノート",
            "payment_method": "現金",
            "account_category": "消耗品費",
            "business_segment": "共通経費",
            "memo": None,
        }
    )
    _patch_client(monkeypatch, [single_rate_response])

    result = gemini_client.analyze_receipt_image(b"img", "image/jpeg")

    assert result["tax_rate_10_base"] == 1091
    assert result["tax_rate_10_amount"] == 109
    assert result["tax_rate_8_base"] is None
    assert result["tax_rate_8_amount"] is None
