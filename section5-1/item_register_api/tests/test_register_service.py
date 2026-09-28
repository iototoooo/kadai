"""実際のGoogle Sheetsに接続せず、service.pyの採番・書き込み・二重登録防止ロジックを検証する。"""

import datetime

from item_register_api.models import ItemRegisterRequest
from item_register_api.service import RegisterItemService, build_final_description
from item_register_api.sheets_client import build_management_number, get_max_management_number

from .fakes import FakeSheetsClient, FakeWorksheet


def make_request(**overrides) -> ItemRegisterRequest:
    data = dict(
        title="BILLABONG バック立体ロゴ パーカー 杢グレー Y2K",
        genre="トップス",
        style="Y2K",
        brand="BILLABONG",
        sale_price=3980,
        condition="目立った傷なし",
        season="秋冬",
        storage_location="B",
        mercari_account="メイン",
        description="商品説明のサンプル\n#AddOneVintage",
        request_id="req-001",
    )
    data.update(overrides)
    return ItemRegisterRequest(**data)


def test_build_final_description_appends_management_number_and_location():
    result = build_final_description("#AddOneVintage", "2609-013", "B")
    assert result == "#AddOneVintage\n\n（S/N：2609-013）\nB"


def test_get_max_management_number_ignores_other_months_and_gaps():
    ws = FakeWorksheet([""] * 46)
    for num in ["2609-009", "2609-010", "2609-012", "2608-099"]:
        ws.rows.append([num] + [""] * 45)
    assert get_max_management_number(ws, "2609") == 12
    assert build_management_number("2609", 13) == "2609-013"


def test_register_first_item_gets_sequence_001_and_writes_expected_columns():
    service = RegisterItemService(client=FakeSheetsClient())
    resp = service.register(make_request())

    assert resp.success is True
    assert resp.already_registered is False
    yymm = datetime.datetime.now().strftime("%y%m")
    assert resp.management_number == f"{yymm}-001"
    assert resp.storage_location == "B"
    assert resp.description.endswith(f"（S/N：{resp.management_number}）\nB")

    row = service._client.item_sheet.rows[1]
    assert row[0] == resp.management_number  # A: 管理番号
    assert row[1] == "BILLABONG バック立体ロゴ パーカー 杢グレー Y2K"  # B: 商品名
    assert row[2] == "トップス"  # C: ジャンル
    assert row[5] == 3980  # F: 出品価格
    assert row[13] == 1  # N: 出品点数
    assert row[17] == "メルカリ"  # R: 販売場所
    assert row[37] == "B"  # AL: メモ
    assert row[44] == "メイン"  # AS: メルカリアカウント
    assert row[10].startswith("=")  # K: 数式が入っている


def test_register_increments_sequence_from_existing_numbers():
    client = FakeSheetsClient()
    yymm = datetime.datetime.now().strftime("%y%m")
    client.item_sheet.rows.append([f"{yymm}-009"] + [""] * 45)
    client.item_sheet.rows.append([f"{yymm}-012"] + [""] * 45)

    service = RegisterItemService(client=client)
    resp = service.register(make_request(request_id="req-002"))
    assert resp.management_number == f"{yymm}-013"


def test_duplicate_request_id_does_not_add_new_row_and_returns_same_result():
    client = FakeSheetsClient()
    service = RegisterItemService(client=client)

    first = service.register(make_request(request_id="req-dup"))
    rows_after_first = len(client.item_sheet.rows)

    second = service.register(make_request(request_id="req-dup", title="別タイトルに変わっていても無視される"))

    assert second.already_registered is True
    assert second.management_number == first.management_number
    assert second.description == first.description
    assert len(client.item_sheet.rows) == rows_after_first  # 新規行は追加されない


def test_optional_fields_can_be_blank():
    service = RegisterItemService(client=FakeSheetsClient())
    resp = service.register(make_request(request_id="req-003", brand=None, mercari_account=""))
    row = service._client.item_sheet.rows[1]
    assert row[4] == ""  # E: ブランド
    assert row[44] == ""  # AS: メルカリアカウント
    assert resp.success is True


def test_invalid_genre_is_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        make_request(genre="存在しないジャンル")
