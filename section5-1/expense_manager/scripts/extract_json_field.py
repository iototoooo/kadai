"""JSONファイルから特定キーの値だけを別ファイルへ抜き出す小さなツール。

drive_oauth_result.json のような「秘密情報を含むJSON」から、Secret Manager登録に
必要な1つの値だけを、画面に一切表示せず別ファイルへ書き出すために使う。

パスはコマンドライン引数(sys.argv)として渡すこと。Pythonの文字列リテラルへ
Windowsパスを直接埋め込むと、"C:\\Users\\..." のようなパス中の "\\U" が
unicodeエスケープ(\\UXXXXXXXX)と誤解釈されて構文エラーになるため、
-c オプションでの埋め込みではなく、このファイルをargv経由で呼び出すこと。

使い方:
    python extract_json_field.py <入力JSONファイル> <出力ファイル> <キー名>

例:
    python extract_json_field.py drive_oauth_result.json out.json GOOGLE_DRIVE_OAUTH_JSON
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    if len(sys.argv) != 4:
        print("usage: extract_json_field.py <input.json> <output.txt> <key>", file=sys.stderr)
        sys.exit(1)

    input_path, output_path, key = sys.argv[1], sys.argv[2], sys.argv[3]

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    if key not in data:
        print(f"エラー: キー '{key}' が {input_path} に見つかりません。", file=sys.stderr)
        sys.exit(1)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(data[key])

    # 値そのものは一切標準出力に出さない。
    print(f"OK: キー '{key}' の値を {output_path} へ書き出しました(中身は表示していません)。")


if __name__ == "__main__":
    main()
