"""支払先の正規化(normalize_payee)と、重複候補検索(find_possible_duplicates)の
単体テスト。実際のSheets/Driveには接続せず、純粋なロジックのみを検証する。
"""

from expense_manager.sheets_client import ExistingRow, find_possible_duplicates, normalize_payee


def test_normalize_payee_removes_corporate_entity_and_repeated_word():
    """今回発生した表記揺れ(「はま寿司」の連続重複)が正規化後に一致すること。"""
    a = normalize_payee("株式会社はま寿司 板橋徳丸店")
    b = normalize_payee("株式会社はま寿司 はま寿司 板橋徳丸店")
    assert a == b


def test_normalize_payee_ignores_fullwidth_halfwidth_space_and_case():
    a = normalize_payee("ABC Store")
    b = normalize_payee("abc　store")  # 全角スペース + 大文字小文字違い
    assert a == b


def test_normalize_payee_ignores_various_corporate_entity_notations():
    variants = ["(株)テスト商店", "（株）テスト商店", "株式会社テスト商店", "テスト商店"]
    normalized = {normalize_payee(v) for v in variants}
    assert len(normalized) == 1


def test_normalize_payee_empty_input():
    assert normalize_payee(None) == ""
    assert normalize_payee("") == ""


def test_normalize_payee_does_not_collapse_non_consecutive_repeated_word():
    # 連続していない同一語は畳まない(意図的な仕様: あくまで「連続重複」のみ対応)。
    a = normalize_payee("寿司 板橋 寿司")
    b = normalize_payee("寿司 板橋")
    assert a != b


def _row(row_number, payee, amount, transaction_date="2026-09-27", invoice=""):
    return ExistingRow(
        row_number=row_number,
        management_number=f"EX26090{row_number:02d}",
        transaction_date=transaction_date,
        payee=payee,
        amount=amount,
        account_category="接待交際費",
        business_segment="FP・紹介",
        drive_file_url="https://example.invalid/x",
        request_id=f"req-{row_number}",
        image_hash=f"hash-{row_number}",
        invoice_registration_number=invoice,
    )


def test_find_possible_duplicates_detects_invoice_number_match_even_if_payee_differs():
    existing = [_row(2, "全く別の店名", 2519, invoice="T7010401052896")]
    candidates = find_possible_duplicates(
        existing, "2026-09-27", 2519, payee="別の店名(未知)", invoice_registration_number="T7010401052896"
    )
    assert len(candidates) == 1


def test_find_possible_duplicates_detects_normalized_payee_variance():
    existing = [_row(2, "株式会社はま寿司 板橋徳丸店", 2519)]
    candidates = find_possible_duplicates(
        existing, "2026-09-27", 2519, payee="株式会社はま寿司 はま寿司 板橋徳丸店", invoice_registration_number=""
    )
    assert len(candidates) == 1


def test_find_possible_duplicates_detects_weak_date_amount_only_match():
    existing = [_row(2, "全然違う店", 2519, invoice="T9999999999999")]
    candidates = find_possible_duplicates(
        existing, "2026-09-27", 2519, payee="別の何か", invoice_registration_number="T1111111111111"
    )
    # 支払先・インボイス番号どちらも一致しないが、取引日+金額のみで弱い候補として検出する
    assert len(candidates) == 1


def test_find_possible_duplicates_no_match_when_date_differs():
    existing = [_row(2, "同じ店", 2519, transaction_date="2026-09-27")]
    candidates = find_possible_duplicates(existing, "2026-09-28", 2519, payee="同じ店")
    assert candidates == []


def test_find_possible_duplicates_no_match_when_amount_differs():
    existing = [_row(2, "同じ店", 2519)]
    candidates = find_possible_duplicates(existing, "2026-09-27", 3000, payee="同じ店")
    assert candidates == []


def test_find_possible_duplicates_orders_stronger_matches_first():
    existing = [
        _row(2, "無関係な店", 2519, invoice=""),  # 弱い候補のみ
        _row(3, "対象の店", 2519, invoice="T7010401052896"),  # インボイス番号一致(最強)
    ]
    candidates = find_possible_duplicates(
        existing, "2026-09-27", 2519, payee="対象の店", invoice_registration_number="T7010401052896"
    )
    assert len(candidates) == 2
    assert candidates[0].row_number == 3  # インボイス番号一致が先頭
