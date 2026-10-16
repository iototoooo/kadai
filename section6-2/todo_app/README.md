# Todoリスト Webアプリ (課題6-2)

FastAPI + Google Sheets + Firebase Authentication(Googleログイン)のTodoリスト。
許可した1つのGoogleアカウントだけが利用できる。Cloud Runサービス `todo-app` として公開する。

既存の `expense_manager` などとはコード・Cloud Runサービス・実行サービスアカウント・
スプレッドシートをすべて分離している(共用しているのはGCPプロジェクトとFirebase Authの設定のみ)。

## 機能
- Todoの新規登録・編集・一覧表示(タイトル・内容・期日)
- データはGoogleスプレッドシート「Todo管理」の `Todo` シートに保存
- 削除・完了チェックは未実装(課題の必須範囲外)

## 画面 / API
| 種別 | パス | 説明 |
|---|---|---|
| 画面 | `/login` | Googleでログイン(未ログインでも表示可) |
| 画面 | `/` | 一覧(期日が近い順、期日なしは最後) |
| 画面 | `/todos/new`, `/todos/{id}/edit` | 新規登録・編集 |
| API | `POST /api/session`, `POST /api/session/logout` | セッションcookie発行・削除 |
| API | `GET /api/todos`, `GET /api/todos/{id}` | 一覧・1件取得 |
| API | `POST /api/todos`, `PUT /api/todos/{id}` | 登録・編集 |

`/login` と `/healthz` 以外の画面・APIはすべてサーバー側でセッションcookieを検証し、
`ALLOWED_LOGIN_EMAIL` と一致するGoogleアカウント(メール確認済み)以外は拒否する。

## スプレッドシート
| 列 | A | B | C | D | E | F |
|---|---|---|---|---|---|---|
| 内容 | ID(uuid4 hex) | タイトル | 内容 | 期日(YYYY-MM-DD) | 登録日時 | 更新日時 |

- 1行目が空なら、アプリが初回アクセス時にヘッダーを書き込む。別の内容があれば上書きせずエラーにする。
- 書き込みはすべて `RAW`(入力が `=` で始まっても数式にならない)。
- 日時は日本時間 `YYYY-MM-DD HH:MM:SS`。

## セキュリティ設計
- 秘密情報をコード・Gitに含めない。サービスアカウントJSONキーは使わず、Cloud Run実行SA
  `todo-app-run` のADCでSheetsとFirebase Admin SDKを利用する(Secret Manager不要)。
- `todo-app-run` の権限は最小限:
  - プロジェクトIAM: カスタムロール `todoAppFirebaseAuthSession`
    (`firebaseauth.users.createSession`, `firebaseauth.users.get`)のみ
  - Sheets: 「Todo管理」スプレッドシート1つだけに編集者として共有(スコープは `spreadsheets` のみ)
- セッションcookieは HttpOnly / Secure / SameSite=Lax。書き込み系APIは `Origin` ヘッダーが
  自オリジンであることを必須にしている(CSRF対策)。
- 画面の表示は `textContent` のみ(XSS対策)。エラーの詳細はサーバーログのみに出し、利用者には汎用メッセージを返す。
- `/docs` などのAPIドキュメントは無効化。

## ローカル開発
```bash
cd section6-2
python -m venv .venv
.venv/Scripts/python -m pip install -r todo_app/requirements-dev.txt
.venv/Scripts/python -m pytest todo_app/tests -q
```
テストはSheets/Firebaseをフェイクに差し替えており、本物のスプレッドシートには書き込まない。

## Cloud Runデプロイ
```bash
gcloud run deploy todo-app \
  --source section6-2/todo_app \
  --project project-d3aeaeea-14fc-48ae-860 --region asia-northeast1 \
  --service-account todo-app-run@project-d3aeaeea-14fc-48ae-860.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --min-instances 0 --max-instances 1 --concurrency 1 \
  --cpu 1 --memory 512Mi \
  --set-env-vars "FIREBASE_PROJECT_ID=...,ALLOWED_LOGIN_EMAIL=...,FIREBASE_WEB_API_KEY=...,FIREBASE_WEB_AUTH_DOMAIN=...,FIREBASE_WEB_APP_ID=...,TODO_SPREADSHEET_ID=..."
```
- `--allow-unauthenticated` はネットワーク到達のみを許可する設定で、実際の認証はアプリ側
  (Firebaseセッションcookie + 許可アカウント照合)で行う。
- デプロイ後、Firebase Authenticationの承認済みドメインに
  `todo-app-221708489717.asia-northeast1.run.app` を追加する(既存ドメインは残したまま追加のみ)。
