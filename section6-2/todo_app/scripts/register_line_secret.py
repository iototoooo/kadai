"""ローカルの .env にあるLINE設定を、Secret Manager の todo-app-line に登録する。

秘密情報の扱い:
- トークン・送信先IDは画面に表示しない。コマンドライン引数にも載せない(シェル履歴・プロセス一覧に残らない)。
- gcloud には標準入力で直接バイト列を渡す(シェルのパイプを経由しないため、PowerShellの文字コード変換や
  改行付加の影響を受けない)。
- gcloud の標準出力は表示しない(versions access の出力=秘密値を含むため)。表示するのは成否と件数のみ。

手順:
1. .env から LINE_CHANNEL_ACCESS_TOKEN / LINE_DEFAULT_TO を読む
2. LINE API(読み取り専用: bot情報・友だち確認)でトークンの有効性を確認する。メッセージは送らない
3. Secret を作成(既に存在する場合は中止。上書きはしない)
4. 登録された値を読み戻し、元の値と一致するか確認する(値は表示せず「一致/不一致」のみ)

使い方:
    python register_line_secret.py --env <.envのパス> --project <GCPプロジェクトID> [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys

import requests
from dotenv import dotenv_values

SECRET_NAME = "todo-app-line"


def gcloud(args: list[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    exe = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not exe:
        raise SystemExit("gcloud が見つかりません")
    return subprocess.run([exe, *args], input=input_bytes, capture_output=True, check=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--dry-run", action="store_true", help="確認のみ行い、Secretは作成しない")
    args = parser.parse_args()

    env = dotenv_values(args.env)
    token = (env.get("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()
    to = (env.get("LINE_DEFAULT_TO") or "").strip()
    if not token or not to:
        print("NG: .env に LINE_CHANNEL_ACCESS_TOKEN / LINE_DEFAULT_TO がありません")
        return 1
    if not re.fullmatch(r"U[0-9a-f]{32}", to):
        print("NG: LINE_DEFAULT_TO がLINEのuserId形式ではありません")
        return 1
    print("1/4 .env の読み込み: OK(値は表示しません)")

    headers = {"Authorization": f"Bearer {token}"}
    info = requests.get("https://api.line.me/v2/bot/info", headers=headers, timeout=10)
    profile = requests.get(f"https://api.line.me/v2/bot/profile/{to}", headers=headers, timeout=10)
    if info.status_code != 200 or profile.status_code != 200:
        print(f"NG: LINEトークン確認に失敗しました(bot info={info.status_code}, 友だち確認={profile.status_code})")
        return 1
    print("2/4 LINEトークンの有効性・送信先の友だち登録: OK")

    exists = gcloud(["secrets", "describe", SECRET_NAME, "--project", args.project, "--format=value(name)"])
    if exists.returncode == 0:
        print(f"NG: Secret {SECRET_NAME} は既に存在します。上書きはしないので中止します")
        return 1

    payload = json.dumps({"channel_access_token": token, "to": to}).encode("utf-8")
    if args.dry_run:
        check = gcloud(["--version"])
        print(f"3/4 (dry-run) gcloud 呼び出し確認: {'OK' if check.returncode == 0 else 'NG'} / Secretは作成していません")
        return 0 if check.returncode == 0 else 1

    created = gcloud(
        ["secrets", "create", SECRET_NAME, "--project", args.project,
         "--replication-policy=automatic", "--data-file=-"],
        input_bytes=payload,
    )
    if created.returncode != 0:
        # gcloudのエラー出力に秘密値は含まれない(入力は標準入力で渡しているため)
        print("NG: Secretの作成に失敗しました:", created.stderr.decode("utf-8", "replace").strip()[:500])
        return 1
    print(f"3/4 Secret {SECRET_NAME} の作成: OK")

    readback = gcloud(["secrets", "versions", "access", "latest", "--secret", SECRET_NAME, "--project", args.project])
    if readback.returncode != 0 or readback.stdout != payload:
        print("NG: 登録内容の読み戻し確認で不一致がありました。Secretを確認してください")
        return 1
    print("4/4 登録内容の読み戻し確認: 一致(値は表示しません)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
