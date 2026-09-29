"""Google Drive OAuth 2.0ユーザー委任の初回認可 + ルートフォルダ作成スクリプト。

【これはアプリ本体(main.py)には含まれない、一度だけ手動で実行するツールです。】

前提:
- Google Cloud Console で OAuth 2.0 クライアントID(種類: デスクトップアプリ)を作成し、
  ダウンロードした client_secret.json を、このスクリプトと同じディレクトリに置いておくこと。
  (client_secret.json は絶対にGitへコミットしないこと。.gitignore対象。)
- OAuth同意画面のテストユーザーに iototoooo@gmail.com が追加済みであること。

実行すると:
1. ブラウザが自動で開き、Googleアカウントでのログイン・drive.fileスコープの同意を求められる
   (この操作は今だけ必要。以降は不要)。
2. 同意後、取得した資格情報(refresh_token等)を使って、Driveの「経費管理」フォルダを
   このOAuthアプリ自身が作成する(既存の別フォルダを流用しない。理由はdrive_client.pyの
   モジュールDocstring参照)。
3. 作成したフォルダへ、小さなテストファイルを1件アップロード→取得→削除して、
   実際に保存・取得できることをその場で確認する。
4. 最後に、Secret Manager等へ設定すべき環境変数の値を標準出力に印字する
   (このスクリプト自身はどこにも保存しない。画面に出た値は自分でコピーして安全に扱うこと)。

使い方:
    python authorize_drive.py
"""

from __future__ import annotations

import json
import os
import sys

# このスクリプト単体の実行のために、リポジトリのsection5-1をsys.pathへ追加する
# (expense_manager パッケージをこのディレクトリの外から相対インポートできるようにするため)。
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SECTION5_1_DIR = os.path.dirname(_THIS_DIR)
sys.path.insert(0, os.path.dirname(_SECTION5_1_DIR))

CLIENT_SECRET_PATH = os.path.join(_THIS_DIR, "client_secret.json")
RESULT_PATH = os.path.join(_THIS_DIR, "drive_oauth_result.json")  # .gitignore対象。ローカルにのみ残す。
ROOT_FOLDER_NAME = "経費管理"
DRIVE_FILE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main() -> None:
    if not os.path.exists(CLIENT_SECRET_PATH):
        print(f"エラー: {CLIENT_SECRET_PATH} が見つかりません。")
        print("Google Cloud ConsoleでOAuthクライアントID(デスクトップアプリ)を作成し、")
        print("ダウンロードしたJSONをこのファイル名で配置してください。")
        sys.exit(1)

    from google_auth_oauthlib.flow import InstalledAppFlow

    print("=== ステップ1: ブラウザでのGoogle認可 ===")
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, scopes=DRIVE_FILE_SCOPES)
    creds = flow.run_local_server(port=0)
    print("認可に成功しました。")

    from expense_manager import config
    from expense_manager.drive_client import DriveClient

    drive = DriveClient(credentials=creds)

    print(f"\n=== ステップ2: ルートフォルダ「{ROOT_FOLDER_NAME}」を新規作成 ===")
    folder_id, folder_link = drive.create_root_folder(ROOT_FOLDER_NAME)
    print(f"作成しました: id={folder_id}")
    print(f"リンク: {folder_link}")

    # upload_receipt_image() は本番アプリと同じく config.EXPENSE_DRIVE_ROOT_FOLDER_ID を参照する。
    # 本番環境では環境変数から読み込まれる値だが、この初回認可スクリプトの中だけは
    # 環境変数を別途用意しなくても完結するよう、たった今作成したfolder_idをそのまま
    # プロセス内でこの設定値に反映する(drive_client.py自体は変更しない)。
    config.EXPENSE_DRIVE_ROOT_FOLDER_ID = folder_id

    print("\n=== ステップ3: テストアップロードで動作確認 ===")
    test_bytes = b"expense_manager drive.file scope verification test"
    file_id, file_link = drive.upload_receipt_image(
        year="TEST",
        month="TEST",
        management_number="oauth-verify",
        file_bytes=test_bytes,
        content_type="text/plain",
        extension=".txt",
    )
    print(f"アップロード成功: id={file_id}")
    print(f"リンク: {file_link}")

    confirm = input("\n上記リンクをブラウザで開いて内容が見えることを確認できましたか？ [y/N]: ")
    if confirm.strip().lower() != "y":
        print("確認できなかったため、テストファイルはそのまま残しています。手動でご確認ください。")
    else:
        try:
            drive._service.files().delete(fileId=file_id).execute()
            print("テストファイルを削除しました。")
        except Exception as e:  # noqa: BLE001
            print(f"テストファイルの削除に失敗しました(手動で削除してください): {e}")

    oauth_json = json.dumps(
        {
            "refresh_token": creds.refresh_token,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "token_uri": creds.token_uri,
        },
        ensure_ascii=False,
    )
    # refresh_token/client_secretは画面に印字せず、ローカルファイル(.gitignore対象)にのみ書き出す。
    # Secret Manager登録時は `gcloud secrets create ... --data-file=drive_oauth_result.json` のように
    # ファイルパスを直接指定し、中身をターミナル/チャット等に一切表示しないこと。
    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump({"GOOGLE_DRIVE_OAUTH_JSON": oauth_json, "EXPENSE_DRIVE_ROOT_FOLDER_ID": folder_id}, f, ensure_ascii=False)

    print("\n=== 完了 ===")
    print(f"認可結果を次のファイルに保存しました(中身は画面に表示していません):")
    print(f"  {RESULT_PATH}")
    print(f"新しいDriveルートフォルダID: {folder_id}  (これ自体は秘密情報ではありません)")
    print("\nこのファイルの中身(GOOGLE_DRIVE_OAUTH_JSON)は、後ほどSecret Manager登録時に")
    print("ファイルパス指定で直接読み込みます。チャット等へ貼り付けたり、画面共有で映したりしないでください。")


if __name__ == "__main__":
    main()
