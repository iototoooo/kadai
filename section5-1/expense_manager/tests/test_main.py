"""main.py の /api/analyze エンドポイントをHTTPレベルで検証する。
Firebase認証・Sheets/Drive・Geminiには一切接続せず、app.dependency_overridesと
モジュール関数のmonkeypatchで差し替える。
"""

import io

from fastapi.testclient import TestClient

from expense_manager import config, main
from expense_manager.auth import SessionUser
from expense_manager.expense_service import DriveSaveError, ExpenseService, SheetsRegistrationError
from expense_manager.gemini_client import GeminiAnalysisError

from .fakes import FakeDriveClient, FakeSheetsClient

FAKE_USER = SessionUser(uid="test-uid", email="test@example.com")


def _client_with_service(service: ExpenseService) -> TestClient:
    main.app.dependency_overrides[main.require_session_api] = lambda: FAKE_USER
    main.app.dependency_overrides[main.get_service] = lambda: service
    client = TestClient(main.app)
    return client


def _clear_overrides():
    main.app.dependency_overrides.clear()


def test_analyze_endpoint_does_not_leak_raw_gemini_error(monkeypatch):
    """Gemini解析が最終的に失敗した場合、ユーザー画面(APIレスポンス)には
    安全な日本語メッセージのみが返り、Geminiの生のエラー内容は含まれないこと。
    """
    secret_like_text = "api_key=SECRET_SHOULD_NOT_LEAK internal-detail-503-UNAVAILABLE"

    class FailingService:
        def analyze(self, image_bytes, content_type):
            # gemini_client.py側で生成される、安全なメッセージのみを持つ例外を模す。
            raise GeminiAnalysisError()

    try:
        client = _client_with_service(FailingService())
        response = client.post(
            "/api/analyze",
            files={"file": ("receipt.jpg", io.BytesIO(b"fake-bytes"), "image/jpeg")},
        )
        assert response.status_code == 503
        body = response.json()
        assert body["error"] == "AI解析が混み合っています。しばらくしてからもう一度お試しください。"
        assert secret_like_text not in response.text
    finally:
        _clear_overrides()


def test_analyze_endpoint_works_when_sheets_and_drive_are_unavailable(monkeypatch):
    """Sheets/Driveへ接続できない状態でも、/api/analyze のGemini解析自体は
    実行できること(ExpenseServiceの遅延初期化により、analyze()はSheets/Driveへ
    一切触れないため)。
    """

    def _boom(*args, **kwargs):
        raise RuntimeError("Sheets/Driveへ接続しようとした(analyze中に呼ばれてはならない)")

    monkeypatch.setattr("expense_manager.expense_service.sheets_client.SheetsClient", _boom)
    monkeypatch.setattr("expense_manager.expense_service.drive_client.DriveClient", _boom)
    monkeypatch.setattr(
        "expense_manager.expense_service.gemini_client.analyze_receipt_image",
        lambda image_bytes, content_type: {
            "transaction_date": "2026-09-15",
            "payee": "サンプル文具店",
            "amount": 1200,
            "tax_amount": 109,
            "tax_rate": "10%",
            "invoice_registration_number": None,
            "description": "ノート",
            "payment_method": "現金",
            "account_category": "消耗品費",
            "business_segment": "共通経費",
            "memo": None,
        },
    )

    real_service = ExpenseService()  # client/drive未注入(本番と同じデフォルト構築)

    try:
        client = _client_with_service(real_service)
        response = client.post(
            "/api/analyze",
            files={"file": ("receipt.jpg", io.BytesIO(b"fake-bytes"), "image/jpeg")},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["fields"]["payee"] == "サンプル文具店"
        assert body["fields"]["amount"] == 1200
    finally:
        _clear_overrides()


def test_analyze_endpoint_response_includes_mixed_tax_rate_breakdown_fields(monkeypatch):
    """/api/analyzeのレスポンスJSONに、8%・10%混在の税率内訳4項目が
    欠落せず含まれること(expense_service.analyze()の実装漏れの再発防止)。"""
    monkeypatch.setattr(
        "expense_manager.expense_service.gemini_client.analyze_receipt_image",
        lambda image_bytes, content_type: {
            "transaction_date": "2026-09-29",
            "payee": "ダイソー",
            "amount": 2307,
            "tax_amount": 202,
            "tax_rate": "10%・8%",
            "tax_rate_10_base": 1705,
            "tax_rate_10_amount": 170,
            "tax_rate_8_base": 400,
            "tax_rate_8_amount": 32,
            "invoice_registration_number": None,
            "description": "日用品",
            "payment_method": "現金",
            "account_category": "消耗品費",
            "business_segment": "共通経費",
            "memo": None,
        },
    )

    real_service = ExpenseService()

    try:
        client = _client_with_service(real_service)
        response = client.post(
            "/api/analyze",
            files={"file": ("receipt.jpg", io.BytesIO(b"fake-bytes"), "image/jpeg")},
        )
        assert response.status_code == 200
        fields = response.json()["fields"]
        assert fields["amount"] == 2307
        assert fields["tax_amount"] == 202
        assert fields["tax_rate"] == "10%・8%"
        assert fields["tax_rate_10_base"] == 1705
        assert fields["tax_rate_10_amount"] == 170
        assert fields["tax_rate_8_base"] == 400
        assert fields["tax_rate_8_amount"] == 32
    finally:
        _clear_overrides()


def _post_register(client: TestClient):
    return client.post(
        "/api/register",
        data={"request_id": "req-http-test"},
        files={"file": ("receipt.jpg", io.BytesIO(b"fake-bytes"), "image/jpeg")},
    )


def test_register_endpoint_does_not_leak_raw_drive_error():
    """Drive保存失敗時、ユーザー画面にはDriveSaveErrorの安全なメッセージのみが
    返り、Drive APIの生のエラー内容(内部フォルダID等)は含まれないこと。
    """
    secret_like_text = "HttpError 404: File not found: 10b7yortedVCCwPut_F-1YwK-Zn7j01G1"

    class FailingService:
        def register(self, **kwargs):
            raise DriveSaveError()

    try:
        client = _client_with_service(FailingService())
        response = _post_register(client)
        assert response.status_code == 502
        body = response.json()
        assert body["error"] == "証憑画像の保存に失敗しました。しばらくしてからもう一度お試しください。"
        assert secret_like_text not in response.text
    finally:
        _clear_overrides()


def test_register_endpoint_does_not_leak_raw_sheets_error():
    """Sheets登録失敗時、ユーザー画面にはSheetsRegistrationErrorの安全な
    メッセージのみが返り、Sheets APIの生のエラー内容は含まれないこと。
    """
    secret_like_text = "gspread.exceptions.APIError: 403 PERMISSION_DENIED"

    class FailingService:
        def register(self, **kwargs):
            raise SheetsRegistrationError()

    try:
        client = _client_with_service(FailingService())
        response = _post_register(client)
        assert response.status_code == 502
        body = response.json()
        assert body["error"] == "経費データの登録に失敗しました。しばらくしてからもう一度お試しください。"
        assert secret_like_text not in response.text
    finally:
        _clear_overrides()


def test_register_endpoint_falls_back_to_generic_safe_message_for_unexpected_errors():
    """DriveSaveError/SheetsRegistrationError/DuplicateBlockedError/
    DriveAuthExpiredErrorのいずれにも該当しない予期しない例外の場合も、
    生の例外内容(スタックトレース等)を含めず、固定の安全なメッセージのみ返すこと。
    """
    secret_like_text = "Traceback (most recent call last): internal bug detail"

    class FailingService:
        def register(self, **kwargs):
            raise ValueError(secret_like_text)

    try:
        client = _client_with_service(FailingService())
        response = _post_register(client)
        assert response.status_code == 502
        body = response.json()
        assert body["error"] == "登録処理に失敗しました。しばらくしてからもう一度お試しください。"
        assert secret_like_text not in response.text
    finally:
        _clear_overrides()


class _NeverCalledService:
    """アップロード検証で弾かれるべきリクエストがGemini/Driveへ到達していないことを
    確認するためのフェイク。analyze/registerが呼ばれたら即座にテストを失敗させる。
    """

    def analyze(self, *args, **kwargs):
        raise AssertionError("アップロード検証を通過する前にanalyze()が呼ばれてはならない")

    def register(self, *args, **kwargs):
        raise AssertionError("アップロード検証を通過する前にregister()が呼ばれてはならない")


def test_analyze_endpoint_rejects_oversized_file_before_calling_gemini():
    oversized_bytes = b"x" * (config.MAX_UPLOAD_FILE_SIZE_BYTES + 1)
    try:
        client = _client_with_service(_NeverCalledService())
        response = client.post(
            "/api/analyze",
            files={"file": ("receipt.jpg", io.BytesIO(oversized_bytes), "image/jpeg")},
        )
        assert response.status_code == 400
        assert "大きすぎます" in response.json()["error"]
    finally:
        _clear_overrides()


def test_analyze_endpoint_rejects_unsupported_content_type_before_calling_gemini():
    try:
        client = _client_with_service(_NeverCalledService())
        response = client.post(
            "/api/analyze",
            files={"file": ("virus.exe", io.BytesIO(b"fake-bytes"), "application/x-msdownload")},
        )
        assert response.status_code == 400
        assert "対応していないファイル形式" in response.json()["error"]
    finally:
        _clear_overrides()


def test_register_endpoint_rejects_oversized_file_before_calling_drive_or_sheets():
    oversized_bytes = b"x" * (config.MAX_UPLOAD_FILE_SIZE_BYTES + 1)
    try:
        client = _client_with_service(_NeverCalledService())
        response = client.post(
            "/api/register",
            data={"request_id": "req-oversized"},
            files={"file": ("receipt.jpg", io.BytesIO(oversized_bytes), "image/jpeg")},
        )
        assert response.status_code == 400
        assert "大きすぎます" in response.json()["error"]
    finally:
        _clear_overrides()


def test_analyze_endpoint_generic_exception_does_not_leak_internal_exception_text(monkeypatch):
    """GeminiAnalysisError以外の予期しない例外(通信断・ライブラリ内部エラー等)の場合も、
    main.pyの汎用except節でstr(e)をそのまま返さず、固定の安全な日本語メッセージのみを
    返すこと(内部例外のテキスト・APIキー・内部構成情報等を含めない)。
    """
    secret_like_text = "api_key=SECRET_SHOULD_NOT_LEAK internal traceback detail xyz123"

    class FailingService:
        def analyze(self, image_bytes, content_type):
            raise RuntimeError(secret_like_text)

    try:
        client = _client_with_service(FailingService())
        response = client.post(
            "/api/analyze",
            files={"file": ("receipt.jpg", io.BytesIO(b"fake-bytes"), "image/jpeg")},
        )
        assert response.status_code == 502
        body = response.json()
        assert body["error"] == "AI解析に失敗しました。しばらくしてからもう一度お試しください。"
        assert secret_like_text not in response.text
    finally:
        _clear_overrides()


def test_register_endpoint_duplicate_request_id_via_two_calls_does_not_duplicate():
    """フロントエンドのネットワーク層自動再試行(通信エラー時のみ1回)を想定し、
    同一request_idで/api/registerを2回呼んでも、Sheetsに行が2件追加されたり
    Driveへ証憑が2回アップロードされたりしないこと(既存のrequest_id冪等性が
    HTTP経由の呼び出しでも機能することの回帰防止)。
    """
    sheets = FakeSheetsClient()
    drive = FakeDriveClient()
    service = ExpenseService(client=sheets, drive=drive)

    try:
        client = _client_with_service(service)
        data = {
            "request_id": "req-network-retry-001",
            "transaction_date": "2026-09-15",
            "payee": "サンプル文具店",
            "amount": "1200",
            "tax_amount": "109",
            "tax_rate": "10%",
            "account_category": "消耗品費",
            "business_segment": "共通経費",
        }
        files = {"file": ("receipt.jpg", io.BytesIO(b"fake-bytes"), "image/jpeg")}

        first = client.post("/api/register", data=data, files=files)
        files = {"file": ("receipt.jpg", io.BytesIO(b"fake-bytes"), "image/jpeg")}
        second = client.post("/api/register", data=data, files=files)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["management_number"] == second.json()["management_number"]
        assert len(sheets.expense_sheet.rows) == 2  # ヘッダー + 1件のみ(2件目は追加されない)
        assert len(drive.uploaded) == 1  # Driveへの再アップロードも発生しない
    finally:
        _clear_overrides()


def test_register_endpoint_rejects_unsupported_content_type_before_calling_drive_or_sheets():
    try:
        client = _client_with_service(_NeverCalledService())
        response = client.post(
            "/api/register",
            data={"request_id": "req-bad-type"},
            files={"file": ("note.txt", io.BytesIO(b"not an image"), "text/plain")},
        )
        assert response.status_code == 400
        assert "対応していないファイル形式" in response.json()["error"]
    finally:
        _clear_overrides()
