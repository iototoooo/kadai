"""Gemini API(Google AI Studio)によるレシート・領収書画像解析。

使用モデルは config.GEMINI_MODEL(環境変数 GEMINI_MODEL)で切り替え可能。
第1モデルが一時エラー(最大3回リトライ後も失敗)・日次クォータ超過等で利用できない
場合は、config.GEMINI_FALLBACK_MODEL(環境変数 GEMINI_FALLBACK_MODEL)へ自動的に
フォールバックする。

最重要要件(要件定義書§18): 画像から明確に読み取れない項目は推測で埋めず、
null/空欄のまま返すようプロンプトで明示的に指示する。

旧 google-generativeai パッケージは公式にサポート終了(deprecated)となったため、
後継の google-genai パッケージ(google.genai.Client)を使用する。

【このファイルの構造】
- GeminiAnalysisError            : ユーザー向けの安全なエラー(公開)
- _DailyQuotaExhaustedError       : 日次クォータ超過を表す内部シグナル(非公開)
- FIELD_KEYS / _build_prompt 等   : プロンプト・JSON抽出まわりのユーティリティ
- _get_client                    : genai.Clientのシングルトン
- _is_daily_quota_exhausted      : 429が日次クォータ超過かどうかの判定だけを行う
- _call_model_with_retry         : 1モデルに対するリトライ処理だけを行う
- analyze_receipt_image          : 第1モデル→第2モデルのフォールバック制御だけを行う
"""

from __future__ import annotations

import json
import logging
import random
import re
import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from . import config
from .choices import ACCOUNT_CATEGORIES, BUSINESS_SEGMENTS

logger = logging.getLogger("expense_manager.gemini")
# ルートロガーの既定レベル(WARNING)だとinfoログがCloud Loggingに出ないため、
# このロガー専用にINFO以上を確実に出力する設定を行う(item_register_apiの
# logging_utils.pyと同様の方針。秘密情報は一切含めない)。
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False

# 一時的なエラーとみなしてリトライする対象のHTTPステータスコード。
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
# 1モデルあたりの最大試行回数(初回呼び出しを含む合計回数)。Primary/Fallbackとも
# この定数を共有するため、値を1箇所変更するだけで両方に反映される。
# ユーザーの待ち時間を抑えるため2回とする(最悪ケースでもPrimary+Fallback合計で
# 最大4回のAPI呼び出し・バックオフ待機は1モデルあたり最大1回に収まる)。
MAX_ATTEMPTS = 2
_BASE_DELAY_SECONDS = 1.0
_MAX_JITTER_SECONDS = 0.5


class GeminiAnalysisError(Exception):
    """Gemini解析が(第1・第2モデルともに)失敗したことを表す。

    このメッセージはユーザー画面にそのまま表示して問題ない、安全な日本語文言のみを
    保持する。Gemini側の生のエラー内容・APIキー・スタックトレース等は一切含めない
    (それらは呼び出し時点でログにのみ記録する)。
    """

    def __init__(
        self,
        user_message: str = "AI解析が混み合っています。しばらくしてからもう一度お試しください。",
    ):
        super().__init__(user_message)


class _DailyQuotaExhaustedError(Exception):
    """429のうち、構造化されたエラー詳細から日次クォータ超過だと確実に判定できた
    ことを表す内部シグナル(ユーザーへは公開しない)。リトライせず即座にフォールバックへ
    進むための合図として使う。
    """


# --- プロンプト・JSON抽出まわりのユーティリティ ---

FIELD_KEYS = [
    "transaction_date",
    "payee",
    "amount",
    "tax_amount",
    "tax_rate",
    "tax_rate_10_base",
    "tax_rate_10_amount",
    "tax_rate_8_base",
    "tax_rate_8_amount",
    "invoice_registration_number",
    "description",
    "payment_method",
    "account_category",
    "business_segment",
    "memo",
]


def _build_prompt() -> str:
    categories = "、".join(ACCOUNT_CATEGORIES)
    segments = "、".join(BUSINESS_SEGMENTS)
    return f"""あなたは経費精算のためのレシート・領収書画像解析アシスタントです。
与えられた画像から、以下のキーを持つJSONオブジェクトのみを出力してください。
説明文・コードブロック({'```'}等)は一切含めないでください。

{{
  "transaction_date": "YYYY-MM-DD形式の文字列。読み取れなければnull",
  "payee": "支払先の名称。読み取れなければnull",
  "amount": 支払金額(税込・整数円)。読み取れなければnull,
  "tax_amount": 消費税額の合計(整数円)。単一税率・8%と10%混在のどちらでも合計額を記載。記載が無ければnull,
  "tax_rate": "単一税率のみの場合は「10%」「8%」のように記載。8%と10%が両方記載されている場合は「10%・8%」と記載。読み取れなければnull",
  "tax_rate_10_base": 10%対象額(税抜・整数円)。レシートに明記されている場合のみ転記し、他の金額から計算・逆算しないこと。10%対象の記載が無ければnull,
  "tax_rate_10_amount": 10%消費税額(整数円)。レシートに明記されている場合のみ転記し、他の金額から計算・逆算しないこと。10%対象の記載が無ければnull,
  "tax_rate_8_base": 8%対象額(税抜・整数円)。レシートに明記されている場合のみ転記し、他の金額から計算・逆算しないこと。8%対象の記載が無ければnull,
  "tax_rate_8_amount": 8%消費税額(整数円)。レシートに明記されている場合のみ転記し、他の金額から計算・逆算しないこと。8%対象の記載が無ければnull,
  "invoice_registration_number": "T+13桁等の適格請求書発行事業者登録番号。記載が無ければnull",
  "description": "内容・品目の要約(短い文章)。読み取れなければnull",
  "payment_method": "支払方法。単一の支払方法のみの場合は「現金」「iD」「クレジットカード」のように記載。複数の支払方法とそれぞれの金額が明確に読み取れる場合は、省略せずすべて「方法名 金額円」の形式で「 / 」区切りで連結してください(例: 「現金 2,128円 / Usappyポイント 200円」)。読み取れなければnull",
  "account_category": "次のいずれか一つ: {categories}。判断できなければ「判定不能」",
  "business_segment": "次のいずれか一つ: {segments}。判断できなければ「未判定」",
  "memo": "摘要として使える短い要約文。読み取れなければnull"
}}

重要な制約:
- 画像から明確に読み取れない項目は、絶対に推測や創作をせず null にしてください。
- 金額を確信を持って読み取れない場合は amount を null にしてください(誤った金額を記載することは、無回答より悪い結果です)。
- 勘定科目・事業区分は、上記の選択肢に無い文字列を出力しないでください。
- payment_methodについて、レシートに明記されていない支払方法・金額を推測して追加しないでください。複数の支払方法とそれぞれの金額が画像上で確認できる場合は、省略せずすべて記録してください。
- tax_rate_10_base/tax_rate_10_amount/tax_rate_8_base/tax_rate_8_amountは、レシート上に明記されている数値のみを転記してください。合計金額や消費税額合計から逆算・計算して埋めないでください。8%と10%の両方がレシートに記載されている場合は、どちらか一方だけを選ばず、両方とも出力してください。
- 出力はJSONオブジェクトのみとし、前後に説明文を付けないでください。
"""


_PROMPT = None  # 遅延生成(choices変更時にも追従できるよう関数化しているが、通常は不変)


def _get_prompt() -> str:
    global _PROMPT
    if _PROMPT is None:
        _PROMPT = _build_prompt()
    return _PROMPT


def _extract_json(text: str) -> dict:
    """Geminiの応答からJSONオブジェクトを取り出す。
    response_mime_type="application/json" を指定していても、まれに前後に
    説明文やコードフェンスが付くことがあるため、念のため頑健にパースする。
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"Geminiの応答からJSONを取り出せませんでした: {text[:200]!r}")
    return json.loads(match.group(0))


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY が設定されていません")
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _sleep_with_backoff(attempt_index: int) -> None:
    """attempt_index: 0始まり(1回目の失敗後の待機に0を渡す)。指数バックオフ+ジッター。"""
    delay = _BASE_DELAY_SECONDS * (2**attempt_index) + random.uniform(0, _MAX_JITTER_SECONDS)
    time.sleep(delay)


# --- 429の内訳判定・リトライ・フォールバック ---


def _is_daily_quota_exhausted(error: genai_errors.APIError) -> bool:
    """429エラーが「短時間のリトライでは改善しない日次クォータ超過」だと確実に
    判定できる場合のみTrueを返す。それ以外はこの関数の責務ではない。

    Googleが返す構造化エラー詳細(QuotaFailure.violations[].quotaId、実際に
    "GenerateRequestsPerDayPerProjectPerModel-FreeTier" のような値になることを
    本番環境で確認済み)を見て判定する。エラーメッセージの文言(message)に対する
    脆い文字列一致には依存しない(表記がGoogle側の都合で変わりうるため)。

    構造が想定と異なる・取得できない等、確実に判定できない場合は安全側として
    Falseを返す(=通常の一時エラーとして扱い、リトライ対象から安易に除外しない)。
    """
    try:
        details = error.details
        if not isinstance(details, dict):
            return False
        error_details = details.get("error", {}).get("details", [])
        for d in error_details:
            if not isinstance(d, dict):
                continue
            if not str(d.get("@type", "")).endswith("QuotaFailure"):
                continue
            for v in d.get("violations", []):
                quota_id = str(v.get("quotaId", ""))
                if "PerDay" in quota_id:
                    return True
    except Exception:  # noqa: BLE001 - 判定できない場合は安全側(False)にする
        return False
    return False


def _describe_failure_reason(error: Exception) -> str:
    """Cloud Loggingへ残す、秘密情報を含まない短い失敗理由の文字列を作る。"""
    if isinstance(error, _DailyQuotaExhaustedError):
        return "quota_exhausted"
    if isinstance(error, genai_errors.APIError):
        return f"api_error_status_{error.code}"
    return f"exception_{type(error).__name__}"


def _should_fallback(error: Exception) -> bool:
    """第1モデルの失敗が、第2モデルへ切り替える価値のある「一時的な失敗」かどうかを
    判定する。

    フォールバックする(True):
    - 日次クォータ超過(_DailyQuotaExhaustedError)
    - 429/500/502/503/504でリトライを使い切った場合
      (_call_model_with_retryが最終的に送出するAPIError.codeがRETRYABLE_STATUS_CODESに
      含まれる場合。これはリトライ上限到達を意味する)

    フォールバックしない(False):
    - 400等の非リトライ対象APIError(リクエスト自体の問題である可能性が高く、
      第2モデルでも同様に失敗する可能性が高いため、無駄なAPI呼び出し・待機時間を避ける)
    - APIError以外の例外(JSON抽出失敗等、一時的なサーバー側エラーではないため)
    """
    if isinstance(error, _DailyQuotaExhaustedError):
        return True
    if isinstance(error, genai_errors.APIError) and error.code in RETRYABLE_STATUS_CODES:
        return True
    return False


def _call_model_with_retry(client: genai.Client, model_name: str, image_bytes: bytes, mime_type: str) -> dict:
    """1つのモデルに対して、最大MAX_ATTEMPTS回まで一時エラー(429/500/502/503/504)を
    指数バックオフでリトライしながら呼び出す。このモデル単体のリトライ処理だけを行い、
    他モデルへのフォールバック判断は行わない(呼び出し元の責務)。

    429のうち日次クォータ超過だと確実に判定できた場合は、リトライせず
    _DailyQuotaExhaustedErrorを即座に送出する。それ以外の失敗(リトライ上限到達・
    非リトライ対象エラー等)は元の例外をそのまま送出する。ここでは安全な
    メッセージへの変換は行わない(ユーザーへの最終的な表示判断は呼び出し元に委ねる)。
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[
                    _get_prompt(),
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                ],
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            data = _extract_json(response.text)
            logger.info(
                "Gemini解析に成功しました: model=%s, attempt=%d/%d, status=200, result=success",
                model_name,
                attempt,
                MAX_ATTEMPTS,
            )
            return {key: data.get(key) for key in FIELD_KEYS}

        except genai_errors.APIError as e:
            status_code = e.code

            if status_code == 429 and _is_daily_quota_exhausted(e):
                logger.warning(
                    "Geminiで日次クォータ超過を検知しました。このモデルでのリトライは"
                    "行わず打ち切ります: model=%s, status=%s, attempt=%d/%d, result=quota_exhausted",
                    model_name,
                    status_code,
                    attempt,
                    MAX_ATTEMPTS,
                )
                raise _DailyQuotaExhaustedError() from e

            if status_code in RETRYABLE_STATUS_CODES and attempt < MAX_ATTEMPTS:
                logger.warning(
                    "Geminiから一時的エラーを受信しました。リトライします: "
                    "model=%s, status=%s, attempt=%d/%d, result=retrying",
                    model_name,
                    status_code,
                    attempt,
                    MAX_ATTEMPTS,
                )
                _sleep_with_backoff(attempt - 1)
                continue

            logger.error(
                "Gemini解析が失敗しました: model=%s, status=%s, attempt=%d/%d, result=failed",
                model_name,
                status_code,
                attempt,
                MAX_ATTEMPTS,
            )
            raise

        except Exception as e:  # noqa: BLE001 - APIError以外(JSON抽出失敗・通信エラー等)はリトライ対象外
            logger.error(
                "Gemini解析が失敗しました(リトライ対象外の例外): "
                "model=%s, exception_type=%s, attempt=%d/%d, result=failed",
                model_name,
                type(e).__name__,
                attempt,
                MAX_ATTEMPTS,
            )
            raise


def analyze_receipt_image(image_bytes: bytes, mime_type: str) -> dict:
    """画像を解析し、FIELD_KEYSに沿ったdictを返す(欠けているキーはNoneで補完)。

    第1モデル(config.GEMINI_MODEL)→第2モデル(config.GEMINI_FALLBACK_MODEL)への
    フォールバック制御だけを行う(各モデル単体のリトライは_call_model_with_retryの
    責務)。フォールバックするのは、第1モデルの失敗が一時的なもの
    (429/500/502/503/504でリトライ上限到達、または日次クォータ超過を検知)の場合
    のみ(_should_fallback)。400等の非一時エラーや、APIError以外の例外
    (JSON抽出失敗等)は、第2モデルでも同様に失敗する可能性が高いため、
    フォールバックせず第1モデルの失敗時点で即座にGeminiAnalysisErrorを送出する。
    フォールバック未設定(GEMINI_FALLBACK_MODELが空、またはGEMINI_MODELと同一)の
    場合も同様。第2モデルへフォールバックしても失敗した場合に限り、同じく
    GeminiAnalysisErrorを送出する。

    Cloud Loggingには使用モデル・試行回数・HTTPステータス・フォールバック開始有無/理由・
    最終的に成功したモデルのみを記録し、画像・APIキー・Geminiの生エラー全文は
    一切含めない。呼び出し元(ユーザー)へは常にGeminiAnalysisErrorの安全な
    メッセージのみを返す。
    """
    client = _get_client()
    primary_model = config.GEMINI_MODEL
    fallback_model = config.GEMINI_FALLBACK_MODEL

    try:
        return _call_model_with_retry(client, primary_model, image_bytes, mime_type)
    except Exception as first_error:
        fallback_reason = _describe_failure_reason(first_error)

        if not fallback_model or fallback_model == primary_model:
            logger.error(
                "第1モデルが失敗しましたが、フォールバック先が未設定/同一のため終了します: "
                "primary_model=%s, fallback_reason=%s, fallback=false, result=failed",
                primary_model,
                fallback_reason,
            )
            raise GeminiAnalysisError() from first_error

        if not _should_fallback(first_error):
            logger.error(
                "第1モデルが非一時エラーで失敗したため、フォールバックせず終了します: "
                "primary_model=%s, fallback_reason=%s, fallback=false, result=failed",
                primary_model,
                fallback_reason,
            )
            raise GeminiAnalysisError() from first_error

        logger.warning(
            "第1モデルが一時的エラーで失敗したため第2モデルへフォールバックします: "
            "primary_model=%s, fallback_model=%s, fallback=true, fallback_reason=%s",
            primary_model,
            fallback_model,
            fallback_reason,
        )
        try:
            result = _call_model_with_retry(client, fallback_model, image_bytes, mime_type)
            logger.info(
                "フォールバックにより解析に成功しました: primary_model=%s, "
                "fallback_model=%s, final_success_model=%s, fallback=true, result=success",
                primary_model,
                fallback_model,
                fallback_model,
            )
            return result
        except Exception as second_error:
            second_reason = _describe_failure_reason(second_error)
            logger.error(
                "第2モデルも失敗しました: primary_model=%s, fallback_model=%s, "
                "primary_fallback_reason=%s, fallback_failure_reason=%s, fallback=true, result=failed",
                primary_model,
                fallback_model,
                fallback_reason,
                second_reason,
            )
            raise GeminiAnalysisError() from second_error
