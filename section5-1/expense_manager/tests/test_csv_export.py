from expense_manager.csv_export import build_csv
from expense_manager.sheets_client import HEADER_ROW


def test_build_csv_includes_header_and_utf8_bom():
    rows = [dict(zip(HEADER_ROW, ["EX2609001", "2026-09-15", "サンプル文具店"] + [""] * 13))]
    csv_bytes = build_csv(rows)

    assert csv_bytes.startswith(b"\xef\xbb\xbf")  # utf-8-sig BOM (Excel対応)
    text = csv_bytes.decode("utf-8-sig")
    assert "管理番号" in text.splitlines()[0]
    assert "EX2609001" in text
    assert "サンプル文具店" in text


def test_build_csv_renames_amount_column_to_indicate_tax_included():
    """CSVの「金額」列は税込であることが分かるよう「金額（税込）」と表示され、
    Sheets側のHEADER_ROW自体(「金額」)は変更されていないこと。"""
    assert "金額" in HEADER_ROW  # Sheets側の列名は変更しない
    assert "金額（税込）" not in HEADER_ROW

    row = dict(zip(HEADER_ROW, ["EX2609001", "2026-09-27", "はま寿司", "2519"] + [""] * 12))
    csv_bytes = build_csv([row])
    text = csv_bytes.decode("utf-8-sig")

    header_line = text.splitlines()[0]
    assert "金額（税込）" in header_line
    assert "金額," not in header_line  # 素の「金額」列名が別に残っていないこと

    data_line = text.splitlines()[1]
    assert "2519" in data_line


def test_build_csv_includes_tax_rate_breakdown_columns():
    """8%・10%混在税率対応で追加したQ〜T列がCSVにも含まれること。
    既存A〜P列の列名・並び順は変更されていないこと。"""
    assert HEADER_ROW[:16] == [
        "管理番号",
        "取引日",
        "支払先",
        "金額",
        "消費税額",
        "税率",
        "インボイス登録番号",
        "内容・品目",
        "勘定科目",
        "事業区分",
        "摘要",
        "支払方法",
        "証憑画像URL",
        "登録日時",
        "request_id",
        "画像ハッシュ",
    ]
    assert HEADER_ROW[16:] == ["10%対象額", "10%消費税額", "8%対象額", "8%消費税額"]

    row = dict(
        zip(
            HEADER_ROW,
            ["EX2609099", "2026-09-29", "ダイソー", "2307", "202", "10%・8%"]
            + [""] * 10
            + ["1700", "170", "400", "32"],
        )
    )
    csv_bytes = build_csv([row])
    text = csv_bytes.decode("utf-8-sig")

    header_line = text.splitlines()[0]
    assert "10%対象額" in header_line
    assert "10%消費税額" in header_line
    assert "8%対象額" in header_line
    assert "8%消費税額" in header_line

    data_line = text.splitlines()[1]
    assert "1700" in data_line
    assert "170" in data_line
    assert "400" in data_line
    assert "32" in data_line
