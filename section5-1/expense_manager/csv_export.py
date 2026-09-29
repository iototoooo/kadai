"""経費データのCSV出力。

会計ソフト等への移行時に情報を落とさないよう、Sheetsの全列(A管理番号〜P画像ハッシュ)を
そのまま出力する。Windows Excelで日本語が文字化けしないよう UTF-8 with BOM(utf-8-sig)で
エンコードする。
"""

from __future__ import annotations

import csv
import io

from .sheets_client import HEADER_ROW

# Sheets側の列名(HEADER_ROW)そのものは変更せず、CSV出力時の表示名のみ調整する。
# 「金額」が税込金額であることをCSV単体で見ても分かるようにするための対応。
_CSV_DISPLAY_HEADER = {"金額": "金額（税込）"}

CSV_FIELDNAMES = [_CSV_DISPLAY_HEADER.get(h, h) for h in HEADER_ROW]


def build_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDNAMES)
    writer.writeheader()
    for row in rows:
        # rowのキーはHEADER_ROW(Sheets側の列名)のままなので、CSV表示名へ変換する。
        renamed = {_CSV_DISPLAY_HEADER.get(k, k): v for k, v in row.items()}
        writer.writerow(renamed)
    return buf.getvalue().encode("utf-8-sig")
