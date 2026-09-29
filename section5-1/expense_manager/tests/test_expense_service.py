"""実際のGoogle Sheets/Drive/Geminiに接続せず、expense_service.pyの
重複チェック・採番・Sheets書き込みロジックを検証する。
"""

import pytest

from expense_manager.drive_client import DriveAuthExpiredError
from expense_manager.expense_service import (
    DriveSaveError,
    DuplicateBlockedError,
    ExpenseService,
    SheetsRegistrationError,
)
from expense_manager.models import ExpenseFields
from expense_manager.sheets_client import build_management_number, get_max_management_number

from .fakes import FakeDriveClient, FakeSheetsClient, FakeWorksheet


def make_fields(**overrides) -> ExpenseFields:
    data = dict(
        transaction_date="2026-09-15",
        payee="サンプル文具店",
        amount=1200,
        tax_amount=109,
        tax_rate="10%",
        invoice_registration_number="T1234567890123",
        description="ノート・ペン",
        payment_method="現金",
        account_category="消耗品費",
        business_segment="共通経費",
        memo="事務用品",
    )
    data.update(overrides)
    return ExpenseFields(**data)


def make_service():
    client = FakeSheetsClient()
    drive = FakeDriveClient()
    return ExpenseService(client=client, drive=drive), client, drive


def test_get_max_management_number_ignores_other_months():
    ws = FakeWorksheet([""] * 16)
    for num in ["EX2609009", "EX2609010", "EX2609012", "EX2608099"]:
        ws.rows.append([num] + [""] * 15)
    assert get_max_management_number(ws, "2609") == 12
    assert build_management_number("2609", 13) == "EX2609013"


def test_register_first_item_gets_sequence_001_and_writes_expected_columns():
    service, client, drive = make_service()
    result = service.register(
        request_id="req-001",
        fields=make_fields(),
        image_bytes=b"fake-image-bytes",
        content_type="image/jpeg",
    )

    assert result.already_registered is False
    assert result.management_number == "EX2609001"
    assert result.drive_file_url.endswith("EX2609001.jpg")

    row = client.expense_sheet.rows[1]
    assert row[0] == "EX2609001"  # A: 管理番号
    assert row[1] == "2026-09-15"  # B: 取引日
    assert row[2] == "サンプル文具店"  # C: 支払先
    assert row[3] == 1200  # D: 金額
    assert row[8] == "消耗品費"  # I: 勘定科目
    assert row[9] == "共通経費"  # J: 事業区分
    assert row[14] == "req-001"  # O: request_id
    assert len(row[15]) == 64  # P: sha256ハッシュ(16進64文字)

    assert len(drive.uploaded) == 1
    assert drive.uploaded[0]["management_number"] == "EX2609001"

    # 8%・10%混在税率対応で追加したQ〜T列。既存の単一税率登録では空欄のまま
    # (既存データEX2609001等との互換性を壊さない)。
    assert row[16] == ""  # Q: 10%対象額
    assert row[17] == ""  # R: 10%消費税額
    assert row[18] == ""  # S: 8%対象額
    assert row[19] == ""  # T: 8%消費税額


# --- 8%・10%混在税率対応のテスト ---


def test_register_single_10_percent_only_stores_breakdown_and_leaves_8_percent_blank():
    service, client, _drive = make_service()
    service.register(
        request_id="req-tax-10-only",
        fields=make_fields(
            tax_rate="10%",
            tax_amount=100,
            tax_rate_10_base=1000,
            tax_rate_10_amount=100,
            tax_rate_8_base=None,
            tax_rate_8_amount=None,
        ),
        image_bytes=b"img-tax-10-only",
        content_type="image/jpeg",
    )
    row = client.expense_sheet.rows[1]
    assert row[16] == 1000  # Q: 10%対象額
    assert row[17] == 100  # R: 10%消費税額
    assert row[18] == ""  # S: 8%対象額(該当なし)
    assert row[19] == ""  # T: 8%消費税額(該当なし)


def test_register_single_8_percent_only_stores_breakdown_and_leaves_10_percent_blank():
    service, client, _drive = make_service()
    service.register(
        request_id="req-tax-8-only",
        fields=make_fields(
            tax_rate="8%",
            tax_amount=80,
            tax_rate_10_base=None,
            tax_rate_10_amount=None,
            tax_rate_8_base=1000,
            tax_rate_8_amount=80,
        ),
        image_bytes=b"img-tax-8-only",
        content_type="image/jpeg",
    )
    row = client.expense_sheet.rows[1]
    assert row[16] == ""  # Q: 10%対象額(該当なし)
    assert row[17] == ""  # R: 10%消費税額(該当なし)
    assert row[18] == 1000  # S: 8%対象額
    assert row[19] == 80  # T: 8%消費税額


def test_register_mixed_8_and_10_percent_stores_both_breakdowns():
    """ダイソーの例(合計2,307円、消費税合計202円、10%税額170円、8%税額32円)を想定。"""
    service, client, _drive = make_service()
    service.register(
        request_id="req-tax-mixed",
        fields=make_fields(
            amount=2307,
            tax_amount=202,
            tax_rate="10%・8%",
            tax_rate_10_base=1700,
            tax_rate_10_amount=170,
            tax_rate_8_base=400,
            tax_rate_8_amount=32,
        ),
        image_bytes=b"img-tax-mixed",
        content_type="image/jpeg",
    )
    row = client.expense_sheet.rows[1]
    assert row[3] == 2307  # D: 金額
    assert row[4] == 202  # E: 消費税額(合計、従来通り)
    assert row[5] == "10%・8%"  # F: 税率(従来通り、混在表示)
    assert row[16] == 1700  # Q: 10%対象額
    assert row[17] == 170  # R: 10%消費税額
    assert row[18] == 400  # S: 8%対象額
    assert row[19] == 32  # T: 8%消費税額


def test_register_increments_sequence_from_existing_numbers():
    service, client, _drive = make_service()
    client.expense_sheet.rows.append(["EX2609009"] + [""] * 15)
    client.expense_sheet.rows.append(["EX2609012"] + [""] * 15)

    result = service.register(
        request_id="req-002",
        fields=make_fields(),
        image_bytes=b"bytes-2",
        content_type="image/jpeg",
    )
    assert result.management_number == "EX2609013"


def test_duplicate_request_id_does_not_add_new_row_or_upload():
    service, client, drive = make_service()

    first = service.register(
        request_id="req-dup", fields=make_fields(), image_bytes=b"bytes-a", content_type="image/jpeg"
    )
    rows_after_first = len(client.expense_sheet.rows)
    uploads_after_first = len(drive.uploaded)

    second = service.register(
        request_id="req-dup",
        fields=make_fields(payee="別の支払先に変わっていても無視される"),
        image_bytes=b"different-bytes",
        content_type="image/jpeg",
    )

    assert second.already_registered is True
    assert second.management_number == first.management_number
    assert len(client.expense_sheet.rows) == rows_after_first  # 新規行は追加されない
    assert len(drive.uploaded) == uploads_after_first  # Driveへの再アップロードも発生しない


def test_duplicate_image_hash_blocks_registration_by_default():
    service, _client, _drive = make_service()
    image_bytes = b"identical-receipt-image"

    service.register(
        request_id="req-hash-1", fields=make_fields(), image_bytes=image_bytes, content_type="image/jpeg"
    )

    with pytest.raises(DuplicateBlockedError) as exc_info:
        service.register(
            request_id="req-hash-2",  # request_idは別だが画像は同一
            fields=make_fields(),
            image_bytes=image_bytes,
            content_type="image/jpeg",
        )
    assert exc_info.value.response.reason == "duplicate_hash"


def test_duplicate_image_hash_can_be_overridden():
    service, client, _drive = make_service()
    image_bytes = b"identical-receipt-image-2"

    service.register(request_id="req-hash-a", fields=make_fields(), image_bytes=image_bytes, content_type="image/jpeg")
    rows_before = len(client.expense_sheet.rows)

    # 取引日・支払先・金額を変えて、この検証で「取引日+支払先+金額一致」の
    # 別ゲート(possible_duplicate)が誤って発火しないようにし、画像ハッシュの
    # overrideだけを単独で検証する。
    result = service.register(
        request_id="req-hash-b",
        fields=make_fields(payee="別の支払先", amount=999),
        image_bytes=image_bytes,
        content_type="image/jpeg",
        override_hash_duplicate=True,
    )
    assert result.already_registered is False
    assert len(client.expense_sheet.rows) == rows_before + 1  # overrideにより新規行が追加される


def test_possible_duplicate_warns_but_does_not_hard_block_with_override():
    service, client, _drive = make_service()

    service.register(
        request_id="req-x1", fields=make_fields(), image_bytes=b"img-1", content_type="image/jpeg"
    )

    # 同じ取引日・支払先・金額だが別画像(ハッシュは異なる) -> 「候補」警告の対象。
    with pytest.raises(DuplicateBlockedError) as exc_info:
        service.register(
            request_id="req-x2", fields=make_fields(), image_bytes=b"img-2-different", content_type="image/jpeg"
        )
    assert exc_info.value.response.reason == "possible_duplicate"
    assert len(exc_info.value.response.duplicate_candidates) == 1

    result = service.register(
        request_id="req-x2",
        fields=make_fields(),
        image_bytes=b"img-2-different",
        content_type="image/jpeg",
        override_possible_duplicate=True,
    )
    assert result.already_registered is False
    assert result.management_number == "EX2609002"


def test_possible_duplicate_detects_invoice_number_match_with_different_payee():
    """取引日+金額+インボイス登録番号が一致すれば、支払先の表記が
    まったく違っても重複候補として検出されること。"""
    service, _client, _drive = make_service()
    service.register(
        request_id="req-inv-1",
        fields=make_fields(invoice_registration_number="T7010401052896"),
        image_bytes=b"img-inv-1",
        content_type="image/jpeg",
    )
    with pytest.raises(DuplicateBlockedError) as exc_info:
        service.register(
            request_id="req-inv-2",
            fields=make_fields(payee="全く別の店名表記", invoice_registration_number="T7010401052896"),
            image_bytes=b"img-inv-2-different",
            content_type="image/jpeg",
        )
    assert exc_info.value.response.reason == "possible_duplicate"
    candidate = exc_info.value.response.duplicate_candidates[0]
    assert candidate.account_category == "消耗品費"
    assert candidate.business_segment == "共通経費"


def test_possible_duplicate_detects_hama_sushi_style_payee_wording_variance():
    """今回発生した「株式会社はま寿司 板橋徳丸店」/「株式会社はま寿司 はま寿司 板橋徳丸店」
    のような表記揺れが、インボイス番号が一致しなくても重複候補として検出されること。"""
    service, _client, _drive = make_service()
    service.register(
        request_id="req-hama-1",
        fields=make_fields(payee="株式会社はま寿司 板橋徳丸店", invoice_registration_number="T1111111111111"),
        image_bytes=b"img-hama-1",
        content_type="image/jpeg",
    )
    with pytest.raises(DuplicateBlockedError) as exc_info:
        service.register(
            request_id="req-hama-2",
            fields=make_fields(
                payee="株式会社はま寿司 はま寿司 板橋徳丸店", invoice_registration_number="T2222222222222"
            ),
            image_bytes=b"img-hama-2-different",
            content_type="image/jpeg",
        )
    assert exc_info.value.response.reason == "possible_duplicate"


def test_possible_duplicate_detects_weak_date_amount_only_match():
    """支払先・インボイス番号のどちらも一致しなくても、取引日+金額のみで
    「弱い重複候補」として検出され、自動拒否ではなく警告として扱われること。"""
    service, _client, _drive = make_service()
    service.register(
        request_id="req-weak-1",
        fields=make_fields(payee="お店A", invoice_registration_number="T1111111111111"),
        image_bytes=b"img-weak-1",
        content_type="image/jpeg",
    )
    with pytest.raises(DuplicateBlockedError) as exc_info:
        service.register(
            request_id="req-weak-2",
            fields=make_fields(payee="全く違うお店B", invoice_registration_number="T2222222222222"),
            image_bytes=b"img-weak-2",
            content_type="image/jpeg",
        )
    assert exc_info.value.response.reason == "possible_duplicate"

    # overrideすれば正常に登録できる(自動拒否ではないことの確認)。
    result = service.register(
        request_id="req-weak-2",
        fields=make_fields(payee="全く違うお店B", invoice_registration_number="T2222222222222"),
        image_bytes=b"img-weak-2",
        content_type="image/jpeg",
        override_possible_duplicate=True,
    )
    assert result.already_registered is False


def test_no_duplicate_warning_when_date_or_amount_differs_for_normal_expenses():
    """取引日・金額のいずれかが異なる通常の経費登録では、重複候補の警告が
    出ないこと(過検出しないことの確認)。"""
    service, _client, _drive = make_service()
    service.register(
        request_id="req-normal-1", fields=make_fields(), image_bytes=b"img-normal-1", content_type="image/jpeg"
    )

    result_diff_amount = service.register(
        request_id="req-normal-2",
        fields=make_fields(amount=999),
        image_bytes=b"img-normal-2",
        content_type="image/jpeg",
    )
    assert result_diff_amount.already_registered is False

    result_diff_date = service.register(
        request_id="req-normal-3",
        fields=make_fields(transaction_date="2026-09-16"),
        image_bytes=b"img-normal-3",
        content_type="image/jpeg",
    )
    assert result_diff_date.already_registered is False


def test_missing_transaction_date_falls_back_to_current_month_with_note():
    service, _client, _drive = make_service()
    result = service.register(
        request_id="req-no-date",
        fields=make_fields(transaction_date=None),
        image_bytes=b"img-no-date",
        content_type="image/jpeg",
    )
    assert result.already_registered is False
    assert any("取引日が未入力" in note for note in result.notes)


def test_list_expenses_filters_by_year_month_and_segment():
    service, client, _drive = make_service()
    service.register(request_id="r1", fields=make_fields(transaction_date="2026-09-01"), image_bytes=b"a", content_type="image/jpeg")
    service.register(
        request_id="r2",
        fields=make_fields(transaction_date="2026-10-01", business_segment="古着物販", payee="別の店"),
        image_bytes=b"b",
        content_type="image/jpeg",
    )

    all_items = service.list_expenses()
    assert len(all_items) == 2

    september_items = service.list_expenses(year="2026", month="09")
    assert len(september_items) == 1
    assert september_items[0].payee == "サンプル文具店"

    segment_items = service.list_expenses(business_segment="古着物販")
    assert len(segment_items) == 1
    assert segment_items[0].payee == "別の店"


def test_sheets_write_failure_rolls_back_uploaded_drive_file():
    """Drive保存が成功した後にSheets書き込みが失敗した場合、
    Drive上にだけ証憑ファイルが残る「部分登録」が発生しないことを確認する。
    また、ユーザーへは安全なメッセージ(SheetsRegistrationError)のみが伝わり、
    Sheets APIの生のエラー内容は含まれないことを確認する。
    """
    service, client, drive = make_service()
    client.expense_sheet.fail_append_with = RuntimeError("Sheets API一時エラー(内部詳細)")

    with pytest.raises(SheetsRegistrationError) as exc_info:
        service.register(
            request_id="req-rollback-1",
            fields=make_fields(),
            image_bytes=b"img-for-rollback",
            content_type="image/jpeg",
        )
    assert str(exc_info.value) == "経費データの登録に失敗しました。しばらくしてからもう一度お試しください。"
    assert "Sheets API一時エラー" not in str(exc_info.value)

    # Driveへは1回アップロードされたが、そのファイルはロールバックで削除されている。
    assert len(drive.uploaded) == 1
    uploaded_file_id = drive.uploaded[0]["file_id"]
    assert drive.deleted_ids == [uploaded_file_id]

    # Sheets側には行が追加されていない(ヘッダーのみ)。
    assert len(client.expense_sheet.rows) == 1


def test_sheets_write_failure_with_rollback_failure_still_raises_safe_error():
    """Driveのロールバック自体が失敗しても、エラーが握りつぶされず(サイレントな
    失敗にせず)安全なSheetsRegistrationErrorとして呼び出し元へ伝播すること。
    """
    service, client, drive = make_service()
    client.expense_sheet.fail_append_with = RuntimeError("Sheets API一時エラー")

    def failing_delete(file_id):
        raise RuntimeError("Drive削除も失敗")

    drive.delete_file = failing_delete

    with pytest.raises(SheetsRegistrationError):
        service.register(
            request_id="req-rollback-2",
            fields=make_fields(),
            image_bytes=b"img-for-rollback-2",
            content_type="image/jpeg",
        )


def test_drive_upload_failure_raises_safe_error_and_does_not_write_sheets():
    """Drive保存自体が失敗した場合、DriveSaveError(安全なメッセージ)のみが
    伝わり、Drive APIの生のエラー内容(内部フォルダID等)は含まれないこと。
    また、Drive保存前にSheetsへの書き込みは発生しないため、中途半端な
    データが残らないことを確認する。
    """
    service, client, drive = make_service()
    drive.fail_upload_with = Exception("HttpError 404: File not found: some-internal-folder-id")

    with pytest.raises(DriveSaveError) as exc_info:
        service.register(
            request_id="req-drive-fail",
            fields=make_fields(),
            image_bytes=b"img-drive-fail",
            content_type="image/jpeg",
        )
    assert str(exc_info.value) == "証憑画像の保存に失敗しました。しばらくしてからもう一度お試しください。"
    assert "some-internal-folder-id" not in str(exc_info.value)
    assert "HttpError" not in str(exc_info.value)

    # Sheetsには行が追加されていない(ヘッダーのみ)。
    assert len(client.expense_sheet.rows) == 1
    assert len(drive.uploaded) == 0


def test_drive_auth_expired_error_passes_through_unchanged():
    """DriveAuthExpiredError(既に安全なメッセージを持つ)はDriveSaveErrorへ
    変換されず、そのまま呼び出し元へ伝播すること(main.py側の専用ハンドリングのため)。
    """
    service, _client, drive = make_service()

    def failing_upload(**kwargs):
        raise DriveAuthExpiredError("Google Driveへの保存権限(OAuth認可)が失効しています。再認可が必要です。")

    drive.upload_receipt_image = failing_upload

    with pytest.raises(DriveAuthExpiredError):
        service.register(
            request_id="req-auth-expired",
            fields=make_fields(),
            image_bytes=b"img-auth-expired",
            content_type="image/jpeg",
        )


def test_sheets_read_failure_raises_safe_error():
    """重複チェック・採番のためのSheets読み取り自体が失敗した場合も、
    安全なSheetsRegistrationErrorに変換され、生のエラー内容が含まれないこと。
    """
    service, client, drive = make_service()
    client.expense_sheet.fail_get_all_values_with = RuntimeError("Sheets API 403: permission denied")

    with pytest.raises(SheetsRegistrationError) as exc_info:
        service.register(
            request_id="req-read-fail",
            fields=make_fields(),
            image_bytes=b"img-read-fail",
            content_type="image/jpeg",
        )
    assert str(exc_info.value) == "経費データの登録に失敗しました。しばらくしてからもう一度お試しください。"
    assert "permission denied" not in str(exc_info.value)
    assert len(drive.uploaded) == 0


def test_analyze_never_constructs_sheets_or_drive_clients(monkeypatch):
    """/api/analyze はGemini解析のみを必要とし、Sheets/Driveへの接続は不要。
    ExpenseService()をclient/drive未注入(実運用と同じデフォルト)で構築しても、
    Sheets/Driveへ接続できない状況でGemini解析自体は実行できることを確認する
    (Sheets/Driveの初期化はregister()/list_expenses()等、実際に必要な操作の
    タイミングまで遅延される設計になっていることの検証)。
    """

    def _boom(*args, **kwargs):
        raise RuntimeError("analyze()中にSheets/Driveへ接続しようとした(遅延初期化になっていない)")

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

    service = ExpenseService()  # client/driveを注入しない(本番と同じデフォルト構築)
    result = service.analyze(b"fake-image-bytes", "image/jpeg")

    assert result.fields.payee == "サンプル文具店"
    assert result.fields.amount == 1200


def test_analyze_passes_through_mixed_tax_rate_breakdown_fields(monkeypatch):
    """ExpenseService.analyze()が、Geminiの解析結果(raw)から8%・10%混在の
    税率内訳4項目(tax_rate_10_base等)を欠落させずExpenseFieldsへ引き継ぐこと。
    (ダイソーの例: 合計2,307円、消費税合計202円、10%対象額1,705円、10%税額170円、
    8%対象額400円、8%税額32円を想定)
    """
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

    service = ExpenseService()
    result = service.analyze(b"fake-image-bytes", "image/jpeg")

    assert result.fields.amount == 2307
    assert result.fields.tax_amount == 202
    assert result.fields.tax_rate == "10%・8%"
    assert result.fields.tax_rate_10_base == 1705
    assert result.fields.tax_rate_10_amount == 170
    assert result.fields.tax_rate_8_base == 400
    assert result.fields.tax_rate_8_amount == 32


def test_analyze_single_rate_leaves_other_rate_fields_none(monkeypatch):
    """単一税率(10%のみ)の場合、8%側の項目はNoneのまま(アプリ側で0や逆算値を
    補完しない)ことを確認する。"""
    monkeypatch.setattr(
        "expense_manager.expense_service.gemini_client.analyze_receipt_image",
        lambda image_bytes, content_type: {
            "transaction_date": "2026-09-15",
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
        },
    )

    service = ExpenseService()
    result = service.analyze(b"fake-image-bytes", "image/jpeg")

    assert result.fields.tax_rate_10_base == 1091
    assert result.fields.tax_rate_10_amount == 109
    assert result.fields.tax_rate_8_base is None
    assert result.fields.tax_rate_8_amount is None
