# Todoリスト Webアプリ (課題6-2)

FastAPI + Google Sheets + Firebase Authentication(Googleログイン)のTodoリスト。
許可した1つのGoogleアカウントだけが利用できる。Cloud Runサービス `todo-app` として公開する。

既存の `expense_manager` などとはコード・Cloud Runサービス・実行サービスアカウント・
スプレッドシートをすべて分離している(共用しているのはGCPプロジェクトとFirebase Authの設定のみ)。

## 機能
- Todoの新規登録・編集・一覧表示(タイトル・内容・期日)
- 重要度(高・中・低)の設定と、期日順・重要度順の並び替え
- 完了・未完了の切り替えと、未完了・完了・すべての絞り込み
- LINE期限通知(前日・当日。時刻は通知設定画面で変更可。完了済みには送らない)
- データはGoogleスプレッドシート「Todo管理」の `Todo` シート、通知設定は `設定` シートに保存
- 削除は未実装

## 画面 / API
| 種別 | パス | 説明 |
|---|---|---|
| 画面 | `/login` | Googleでログイン(未ログインでも表示可) |
| 画面 | `/` | 一覧(期日が近い順、期日なしは最後) |
| 画面 | `/todos/new`, `/todos/{id}/edit` | 新規登録・編集 |
| API | `POST /api/session`, `POST /api/session/logout` | セッションcookie発行・削除 |
| API | `GET /api/todos`, `GET /api/todos/{id}` | 一覧・1件取得 |
| API | `POST /api/todos`, `PUT /api/todos/{id}` | 登録・編集 |
| API | `GET /api/todos?status=open\|done\|all&sort=due\|importance` | 絞り込み・並び替え |
| API | `PATCH /api/todos/{id}/completion` | 完了・未完了の切り替え |
| 画面/API | `/settings`, `GET/PUT /api/settings/notifications` | 通知設定 |
| API | `POST /api/notifications/test` | テスト通知(30秒に1回まで) |
| 内部 | `POST /internal/notify` | Cloud Scheduler専用の定期通知(OIDCトークン検証) |

`/login` と `/healthz` 以外の画面・APIはすべてサーバー側でセッションcookieを検証し、
`ALLOWED_LOGIN_EMAIL` と一致するGoogleアカウント(メール確認済み)以外は拒否する。

## スプレッドシート
| 列 | A | B | C | D | E | F | G | H | I | J | K |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 内容 | ID(uuid4 hex) | タイトル | 内容 | 期日(YYYY-MM-DD) | 登録日時 | 更新日時 | 重要度 | 状態 | 完了日時 | 前日通知済み期日 | 当日通知済み期日 |

- 1行目が空なら、アプリが起動時にヘッダーを書き込む。想定外の内容があれば上書きせずエラーにする。
- **旧形式(A〜F列)からの移行**は起動時に自動で行う。手順は
  ①同じスプレッドシート内に `Todo_backup_YYYYMMDD_HHMMSS` タブを複製 → ②複製が元と完全一致するか確認 →
  ③1行目のG〜K列にヘッダーを追記、の順。データ行には一切書き込まない。
  どこかで失敗・不一致があれば、その時点で中止する(G列以降に既存の値がある場合も中止)。
- 旧形式の行は「重要度=中・未完了」として扱う(シートへの書き戻しは、その行を編集したときのみ)。
- 既存行の更新は、その操作で変わる列だけを書き込む(編集: B〜D・F〜G列、完了切替: F・H〜I列、通知記録: J/K列)。
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

## LINE期限通知
- Cloud Scheduler(毎時0分・日本時間)が `todo-notifier` SAのOIDCトークンを付けて `/internal/notify` を呼ぶ。
  アプリはトークンのaudienceと発行元SAを検証し、それ以外は401/403で拒否する。
- 未完了かつ期日が「今日」で当日通知の時刻を過ぎたもの、期日が「明日」で前日通知の時刻を過ぎたものを、
  1通のメッセージにまとめて送る(重要度の高い順)。
- 重複防止: J/K列に「通知済みの期日」を**送信前に**記録し、同じ期日では再送しない(期日を変更したら再度対象)。
  送信失敗時は同じ `X-Line-Retry-Key` で1回再試行(LINE側で重複配信されない)し、それでも失敗したら記録を戻す。
- チャネルアクセストークンと送信先ID は Secret Manager `todo-app-line` から環境変数 `TODO_LINE_CONFIG` として渡す。
  ログ・画面・APIレスポンスには出さない(LINEのエラー時もステータスコードのみ記録)。

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
