"""指定した画像を、本番アプリと全く同じプロンプト・JSON形式でGemini解析だけ試す
一時的な検証スクリプト。

【安全性】
- Google Driveへの保存は一切行わない
- Google Sheetsへの登録は一切行わない
- 管理番号は発番しない
- 本番データは一切変更しない(読み取り専用)
- Gemini解析(client.models.generate_content)のみを実行する

プロンプト(_get_prompt)・JSON抽出(_extract_json)・必須項目(FIELD_KEYS)は
expense_manager/gemini_client.py の実装をそのままimportして使う
(コピーではなく本物のロジックを使うことで、本番と完全に同一であることを保証する)。

使い方:
  python scripts/test_gemini_analyze.py <画像ファイルパス> [モデル名]

例:
  python scripts/test_gemini_analyze.py C:\\path\\to\\receipt.jpg gemini-3.5-flash-lite

GEMINI_API_KEYはSecret Manager(expense-manager-gemini-api-key)から取得し、
画面・ログには一切表示しない。
"""

from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))  # expense_manager/scripts
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # section5-1/ (expense_managerパッケージの親)
sys.path.insert(0, PROJECT_ROOT)

GCLOUD = r"C:\Users\iotot\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
DEFAULT_MODEL = "gemini-3.5-flash-lite"


def get_secret(name: str) -> str:
    result = subprocess.run(
        [GCLOUD, "secrets", "versions", "access", "latest", f"--secret={name}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def main() -> None:
    if len(sys.argv) < 2:
        print("使い方: python test_gemini_analyze.py <画像ファイルパス> [モデル名]")
        sys.exit(1)

    image_path = sys.argv[1]
    model_name = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODEL

    with open(image_path, "rb") as f:
        image_bytes = f.read()
    content_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"

    api_key = get_secret("expense-manager-gemini-api-key")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    api_key = None  # 以降参照しない

    from expense_manager.gemini_client import FIELD_KEYS, _extract_json, _get_prompt

    print(f"=== モデル: {model_name} ===")
    print(f"画像: {image_path} ({len(image_bytes)} bytes, {content_type})")

    start = time.monotonic()
    response = client.models.generate_content(
        model=model_name,
        contents=[_get_prompt(), types.Part.from_bytes(data=image_bytes, mime_type=content_type)],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    elapsed = time.monotonic() - start

    data = _extract_json(response.text)
    result = {key: data.get(key) for key in FIELD_KEYS}

    print(f"応答時間: {elapsed:.2f}秒\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
