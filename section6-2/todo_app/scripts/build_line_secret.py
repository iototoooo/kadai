"""ローカルの .env から Secret Manager 用のLINE設定JSONを作り、標準出力へ書く。

画面に秘密情報を表示しないよう、標準出力が端末の場合は実行を拒否する。
必ず gcloud にパイプして使う:

    python build_line_secret.py <.envのパス> | gcloud secrets create todo-app-line --data-file=- ...
"""

import json
import sys

from dotenv import dotenv_values


def main() -> int:
    if sys.stdout.isatty():
        print("標準出力が端末です。秘密情報を表示しないため、gcloud へパイプして実行してください。", file=sys.stderr)
        return 2
    if len(sys.argv) != 2:
        print("使い方: build_line_secret.py <.envのパス>", file=sys.stderr)
        return 2
    env = dotenv_values(sys.argv[1])
    token = (env.get("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()
    to = (env.get("LINE_DEFAULT_TO") or "").strip()
    if not token or not to:
        print("LINE_CHANNEL_ACCESS_TOKEN / LINE_DEFAULT_TO が .env にありません", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps({"channel_access_token": token, "to": to}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
