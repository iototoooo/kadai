# PROJECT_NOTES.md — AddOne Vintage 出品待ち管理プロジェクト

このドキュメントは、新しいClaude Codeセッションが本プロジェクトの構成・実装済み機能・注意点をすぐ把握できるようにするための引き継ぎ資料です。内容は実際のコード・GCP設定・READMEを確認したうえで事実ベースで記載しています。コードから確認できなかった項目は「要確認」と明記しています。

最終更新時点でのコードは **`git status` 上まだ未コミット**です（`section5-1/item_register_api/`・`section5-1/listing_webapp/`とも`??`のuntracked状態）。作業再開時はまずこの点を確認してください。

---

## 1. プロジェクト概要

- 「AddOne Vintage」名義で古着(主にメルカリ)を出品している個人事業者向けの、**出品待ち管理Webアプリ**。
- **スマホ完結**を前提とした運用フロー：
  1. スマホで商品を撮影
  2. 写真・採寸値・保管場所をChatGPT(GPT)に送り、商品情報をJSON形式で生成させる
  3. 生成されたJSONを`listing_webapp`の①保存画面に取り込み、Firestoreへ「出品待ち」として蓄積
  4. あとでまとめて、②一覧→③詳細画面から1件ずつ確認し、Google Sheets「商品管理」へ登録
  5. メルカリへは**手動で出品**する(写真はスマホの写真フォルダから手動選択、テキストはアプリ上のコピー機能を使う)
- **メルカリへの自動出品・自動転記は一切実装していない**。「メルカリを開く」ボタンはメルカリの出品ページを開くだけの単純なリンク。

## 2. システム構成

```
スマホ/PCブラウザ ──(Googleサインイン)──▶ listing-webapp (Cloud Run, Next.js)
                                                    │
                        ┌───────────────────────────┼───────────────────────────┐
                        ▼                           ▼                           ▼
                  Firestore                   Cloud Storage              item-register-api (Cloud Run, FastAPI)
                (商品データ・状態)              (商品写真)                            │
                                                                                    ▼
                                                                        Google Sheets「商品管理」
```

| コンポーネント | 役割 |
|---|---|
| **listing-webapp** | スマホ向けフロントエンド兼サーバー(Next.js App Router)。①保存/②一覧/③出品作業の3画面と、Firestore/Storage/item-register-apiへのアクセスを仲介するAPI routeを提供。ブラウザはFirestore/Storage/item-register-apiへ**直接アクセスしない**。 |
| **item-register-api** | 既存の独立したFastAPIサービス。`POST /register-item`でGoogle Sheets「商品管理」へ新規行を挿入し、管理番号を自動採番して返す。GPT ActionsやWebアプリなど複数のクライアントから呼ばれる想定で作られた汎用API。 |
| **Firestore** | `items`コレクションに商品データ・写真パス・ステータスを永続保存。Native mode、リージョン`asia-northeast1`。 |
| **Cloud Storage** | 商品写真の保存先。非公開バケット、`publicAccessPrevention: enforced`。 |
| **Firebase Authentication** | listing-webappのログイン(Googleサインイン)。許可アカウント1件のみ。 |
| **Google Sheets** | スプレッドシート「VV新・売上管理」内の「商品管理」シートが実際の商品台帳。item-register-api経由でのみ書き込む。 |
| **Secret Manager** | `item-register-api-key`(item-register-apiのAPIキー。listing-webappからも参照)、`item-register-sa-json`(item-register-api用サービスアカウントJSON)の2つ。listing-webapp自身はサービスアカウントJSONキーを持たない(ADC方式)。 |
| **Cloud Run** | 上記2サービス(listing-webapp、item-register-api)をホスト。 |

## 3. 本番URL・サービス名

(値は`gcloud`での読み取り専用コマンドで確認済み。Secret値・APIキーそのものは記載していません。)

| 項目 | 値 |
|---|---|
| GCP Project ID | `project-d3aeaeea-14fc-48ae-860` |
| リージョン | `asia-northeast1`(東京)。両Cloud Runサービス・Firestore・Cloud Storageとも統一 |
| listing-webapp サービス名 | `listing-webapp` |
| listing-webapp URL | `https://listing-webapp-221708489717.asia-northeast1.run.app`(または`https://listing-webapp-mstrp5kq5q-an.a.run.app`。同一サービスを指す別形式のURL) |
| listing-webapp 実行SA | `listing-webapp-run@project-d3aeaeea-14fc-48ae-860.iam.gserviceaccount.com`(専用SA、最小権限カスタムロール3種のみ付与) |
| item-register-api サービス名 | `item-register-api` |
| item-register-api URL | `https://item-register-api-221708489717.asia-northeast1.run.app`(または`https://item-register-api-mstrp5kq5q-an.a.run.app`) |
| item-register-api 実行SA | `221708489717-compute@developer.gserviceaccount.com`(デフォルトCompute SA。listing-webapp用SAとは別) |
| Cloud Storageバケット | `project-d3aeaeea-14fc-48ae-860-listing-photos` |
| Firestoreデータベース | `(default)`、Native mode |

## 4. 商品登録フロー(ステータス遷移)

`ItemStatus`(`src/lib/types.ts`)は5段階：`"draft" | "pending" | "sheet_registered" | "listed" | "cancelled"`

| ステータス | できること | 表示されるボタン(③詳細画面) | 次に遷移できる先 |
|---|---|---|---|
| `draft` | (現状、①画面はJSON保存時に常に`pending`として作成するため、通常のUI操作でこの状態になる経路は**現状存在しない**。型・APIとしては定義済み) | 「出品待ちから外す」(draft/pending共通) | `pending`(`mark_pending`) / `cancelled`(`mark_cancelled`) |
| `pending` | 商品説明・各項目を編集可能。写真を追加アップロード可能。文字数・`#AddOneVintage`チェックを満たせば「Google Sheetsへ登録」可能 | 「Google Sheetsへ登録」、「出品待ちから外す」 | `sheet_registered`(登録成功) / `cancelled`(外す) |
| `sheet_registered` | 商品名/説明/価格をコピー可能。「メルカリを開く」でメルカリの出品ページを開ける | 「メルカリを開く」、「出品済みにする」 | `listed`(`mark_listed`) |
| `listed` | 履歴として閲覧のみ。写真は30日後に自動削除対象(customTime設定済み) | (状態変更ボタンなし) | (終端状態) |
| `cancelled` | 履歴として閲覧のみ。「外した商品」タブでのみ確認 | (状態変更ボタンなし) | (終端状態) |

- 全ステータスとも「次の商品へ」ボタンは常に表示(`pending`/`sheet_registered`のみを対象にキュー内を巡回、`src/lib/queueOrder.ts`の`ACTIVE_QUEUE_STATUSES`)。
- 「編集」ボタン(商品名/ジャンル/系統/ブランド/価格/状態/季節/保管場所/商品説明の変更)は**ステータスを問わず常に表示**される(`item/[id]/page.tsx`の`!editing`分岐にステータス条件なし)。`sheet_registered`以降に説明文を編集すると、Sheets登録時に生成された完成版description(S/N付き)を上書きしてしまう可能性がある点は設計上のトレードオフとして残っている(要検討)。

## 5. 出品待ち一覧(`/queue`)

`src/app/queue/page.tsx`の`FILTERS`定義：

| タブキー | ラベル | 対象ステータス |
|---|---|---|
| `pending` | 出品待ち | `pending`(デフォルト表示) |
| `sheet_registered` | シート登録済み | `sheet_registered` |
| `listed` | 出品済み | `listed` |
| `draft` | 作成中 | `draft` |
| `cancelled` | 外した商品 | `cancelled` |
| `all` | すべて | `draft`,`pending`,`sheet_registered`,`listed`(**`cancelled`は含まない**) |

- 「次の商品へ」機能(`/api/items/:id/next` → `queueOrder.ts`)の対象ステータスは`pending`・`sheet_registered`のみ。`cancelled`/`listed`/`draft`は対象外。

## 6. Google Sheets登録仕様(item-register-api側の実装、`section5-1/item_register_api/`)

- 対象スプレッドシート：ID `1xMq7gy4d9nPGRGLCX1bltXWxBKXDT1rr66za7zvpmGQ`(スプレッドシート名「VV新・売上管理」)、シート名「商品管理」。
- **管理番号形式**：`{YYMM}-{NNN}`(例`2609-037`)。`YYMM`はJST(`Asia/Tokyo`)での実行時年月。`NNN`は同一`YYMM`内の既存最大連番+1(`get_max_management_number`→`build_management_number`)。書き込み直前にもう一度最大値を再確認し、競合していれば採番し直す(`service.py`の二段階チェック)。
- **`request_id`による冪等性**：`登録ログ(自動)`シート(同スプレッドシート内、非表示シート)に`request_id`ごとの登録結果を記録。同じ`request_id`で再度呼ばれた場合、`status: success`の既存ログが見つかれば新規行を作らず`already_registered: true`+既存の`management_number`/`description`をそのまま返す。
- **商品説明の完成版フォーマット**：`build_final_description()`が`{元のdescription}\n\n（S/N：{management_number}）\n{storage_location}`を組み立て、レスポンスの`description`フィールドとして返す。新規登録時・`already_registered: true`時のいずれも同じ完成版が返る。
- **listing-webapp側の反映**：`markSheetRegistered(id, managementNumber, finalDescription)`がFirestoreの`description`フィールドをこの完成版で上書きする。これにより`sheet_registered`以降の画面表示・コピーボタンは完成版descriptionを参照する(`item.description`をそのまま使うだけで、フロントエンド側に特別な分岐はない)。

## 7. Firestore仕様

`items`コレクション(Native mode、`asia-northeast1`)。1ドキュメント1商品。主要フィールド(`src/lib/types.ts`の`Item`型に対応)：

| フィールド | 型 | 備考 |
|---|---|---|
| `status` | string | 5値のいずれか |
| `title`/`genre`/`style`/`brand`/`sale_price`/`condition`/`season`/`storage_location`/`description`/`mercari_account` | 商品情報本体 |
| `photo_paths` | string[] | Cloud Storage上のオブジェクトパス一覧(`items/{id}/{連番}_{uuid}.拡張子`) |
| `request_id` | string | 商品作成時に`webapp-{FirestoreドキュメントID}`として1回だけ生成、以降使い回す |
| `management_number` | string\|null | Sheets登録成功後にのみ値が入る |
| `raw_gpt_text` | string | ①画面に貼り付けられた元のJSON文字列(デバッグ・再解析用) |
| `created_at`/`updated_at` | number(ミリ秒epoch) | Firestore TimestampをAPI/クライアント境界でnumberに変換 |
| `sheet_registered_at` | number\|null | Sheets登録成功時刻 |
| `listed_at` | number\|null | 「出品済みにする」実行時刻 |
| `cancelled_at` | number\|null | 「出品待ちから外す」実行時刻(今回追加) |

**商品データは通常削除しない方針**。`markListed`/`markCancelled`/`markSheetRegistered`はいずれも`ref.update()`のみで、Firestoreドキュメントを削除する処理はコード上どこにも存在しない。

## 8. Cloud Storage写真仕様

- 保存先パス形式：`items/{FirestoreドキュメントID}/{アップロード順の連番}_{uuid}{拡張子}`(`storagePhotos.ts`の`photoObjectPath`)。
- **`listed`または`cancelled`への遷移時**、その商品の全写真オブジェクトへGCSの`customTime`メタデータ(=`listed_at`または`cancelled_at`)を設定(`markPhotosForRetentionCountdown`、`markListed`/`markCancelled`両方から呼ばれる共通関数)。
- バケットのライフサイクルルール(`daysSinceCustomTime: 30` → `Delete`)が、`customTime`設定から30日後に自動削除する。GCS公式仕様上、`customTime`未設定のオブジェクトはこの条件に一切マッチしない(`pending`中の写真が誤削除されない根拠)。
- バケットは`uniform bucket-level access`有効・`publicAccessPrevention: enforced`(確認済み)。
- `listing-webapp-run`用カスタムロール`listingWebappStoragePhotos`の権限は`storage.objects.create`/`storage.objects.get`/`storage.objects.update`の3つのみで、**`storage.objects.delete`を含まない**(確認済み)。写真の削除はアプリコードからは一切行わず、GCSライフサイクルルールにのみ委ねる設計。

## 9. 「出品待ちから外す」機能(cancelled)

- 対象は`draft`/`pending`のみ(`sheet_registered`/`listed`では③画面にボタン自体が表示されない、`src/app/item/[id]/page.tsx`)。
- APIは`PATCH /api/items/:id/status`に`{action: "mark_cancelled"}`を送る形で実装(既存の`mark_pending`/`mark_listed`と同じルート)。ルート側で遷移元ステータスが`draft`/`pending`以外なら409エラー。
- Firestoreは`markCancelled()`が`status: "cancelled"`・`cancelled_at`・`updated_at`を`update()`するのみで**削除しない**。
- Google Sheets・item-register-apiへは**一切アクセスしない**(`markCancelled`の実装にそもそも該当する呼び出しコードがない)。管理番号は当然発番されない。
- 写真がある場合は`markPhotosForRetentionCountdown`を呼び、30日後自動削除の対象にする(§8と同じ仕組み)。
- 実行前にインライン2段階確認UI(「本当に出品待ちから外しますか？」→「はい、外す」/「キャンセル」)を表示。実行成功後は`/queue`へ遷移。
- `/queue`では「すべて」タブに表示されず、「外した商品」タブでのみ確認できる(§5参照)。

## 10. GPT JSON仕様

listing-webappが①画面で受け取ることを前提にしているJSON形式(`src/lib/types.ts`の`GptItemJson`、`src/lib/validation.ts`の`parseGptJson`でzodスキーマ検証)：

```json
{
  "title": "",
  "genre": "",
  "style": "",
  "brand": "",
  "sale_price": 0,
  "condition": "",
  "season": "",
  "storage_location": "",
  "description": ""
}
```

コードで実際に検証・制約している内容：
- `title`：空文字不可。**40文字超過は保存自体は可能だが、Sheets登録はブロック**(`TITLE_MAX_LENGTH`)
- `description`：空文字不可。**1000文字超過はSheets登録をブロック**(`DESCRIPTION_MAX_LENGTH`)。`#AddOneVintage`を含まない場合は警告表示され、明示的な「警告を確認して登録する」操作をしない限りSheets登録できない
- `sale_price`：0以上の整数(zodの`.int().nonnegative()`)
- `genre`/`style`/`condition`/`season`：それぞれ固定enum一致必須(§13参照)
- `brand`：空文字は`null`として扱う(必須ではない)

**要確認**：「写真から採寸値を推測しない」「ブランド・素材・年代・希少性等を根拠なく断定しない」という制約は、**GPT側のプロンプト設計・運用ルールに関するものであり、listing-webappのコード上には対応する検証ロジックが存在しない**。アプリ側はJSONの構文・enum・文字数のみを機械的にチェックしており、内容の真偽・推測の妥当性は検証していない。この制約がどこで(カスタムGPTの指示文など)定義されているかはこのリポジトリ内には見当たらず、要確認。

## 11. クリップボード読込機能

- `/new`画面(`src/app/new/page.tsx`)最上部に「クリップボードから読み込む」ボタン。
- `navigator.clipboard.readText()`でクリップボード文字列を取得し、`rawText`にセットしたうえで即座に`parseAndApply()`(既存のJSON解析ロジックを共通化した関数)を呼んで自動解析・フォーム展開。
- 既存の手動貼り付け用`<textarea>`はそのまま残しており、クリップボードAPIが使えない場合のフォールバックになっている。
- `navigator.clipboard.readText()`はSecure Context(HTTPS)必須のAPIで、Cloud Runは常時HTTPS配信のため要件を満たす。エラー種別(`NotAllowedError`、API非対応、クリップボード空)ごとに個別メッセージを表示。

## 12. 認証・セキュリティ

- **listing-webappのログイン**：Firebase Authentication、Googleサインインのみ(`src/lib/firebaseClient.ts`)。
- **`ALLOWED_LOGIN_EMAIL`による制限**：Firebase/Firestore/Storage自体には特定1アカウントのみに絞る機能はないため、`src/lib/sessionAuth.ts`の`requireSession()`がセッションCookie検証後に`decoded.email`と`process.env.ALLOWED_LOGIN_EMAIL`を照合し、不一致なら`UnauthorizedError`を投げる形でアプリ側が制限を実装している。
- **Cloud Runレイヤーとアプリ認証の関係**：両Cloud Runサービスとも`--allow-unauthenticated`(GCP IAM認証なしでネットワーク到達可能)でデプロイされている。listing-webappの実質的な認証層は上記のFirebase Auth+`ALLOWED_LOGIN_EMAIL`チェックであり、item-register-apiの実質的な認証層はアプリ内蔵の`X-API-Key`ヘッダー照合(`ITEM_REGISTER_API_KEY`)である。
- **`src/middleware.ts`は本当の認可ではない**：Edge runtimeで動くため、セッションCookieの「存在」だけを見て`/login`へリダイレクトするUX目的の軽量チェックに過ぎない。実際のセキュリティ境界は各API routeが`requireSession()`を呼ぶことで確保している(コード内コメントにも明記)。
- **Secret Managerの利用**：`item-register-api-key`(item-register-api自身の環境変数、およびlisting-webappの`ITEM_REGISTER_API_KEY`環境変数として`--set-secrets`経由で参照)、`item-register-sa-json`(item-register-api用サービスアカウントJSON、item-register-apiのみが参照。listing-webappはこのsecretへのアクセス権限を持たない)。
- **Application Default Credentials(ADC)**：listing-webappのFirebase Admin SDK初期化(`src/lib/firebaseAdmin.ts`)は`applicationDefault()`を使い、Cloud Run実行SA(`listing-webapp-run`)の権限をメタデータサーバー経由で自動解決する。**サービスアカウントJSONキーを新規発行・配布していない**。
- **公開Firebase Web SDK設定とSecretの違い**：`NEXT_PUBLIC_FIREBASE_API_KEY`等4つの値はFirebase公式仕様上ブラウザに公開されることを前提とした設定値であり、秘匿情報ではない(Dockerビルド時に`--build-arg`でクライアントバンドルへ埋め込む)。これと`ITEM_REGISTER_API_KEY`・サービスアカウント認証情報は**明確に別カテゴリ**であり、後者は一貫してSecret Manager/ADC経由でのみサーバー側が保持し、ブラウザ・ログ・画面には一切表示しない運用を継続している。
- **listing-webapp-run用カスタムIAMロール**(最小権限、`gcloud iam roles describe`で確認済み)：
  - `listingWebappFirestoreItems`：`datastore.databases.get`, `datastore.entities.create`, `datastore.entities.get`, `datastore.entities.list`, `datastore.entities.update`(削除権限なし)
  - `listingWebappStoragePhotos`：`storage.objects.create`, `storage.objects.get`, `storage.objects.update`(削除権限なし)
  - `listingWebappFirebaseAuthSession`：`firebaseauth.users.createSession`, `firebaseauth.users.get`(ユーザー作成・削除・認証設定変更等は含まない)

## 13. Google Sheets仕様(詳細)

- 対象スプレッドシート：ID `1xMq7gy4d9nPGRGLCX1bltXWxBKXDT1rr66za7zvpmGQ`(スプレッドシート名「VV新・売上管理」、`config.py`のデフォルト値。環境変数`MERCARI_SHEETS_SPREADSHEET_ID`で上書き可能)。
- 対象シート：「商品管理」(環境変数`ITEM_REGISTER_SHEET_NAME`で上書き可能)。
- **入力対象列**(`sheets_client.py`の`COL_*`定数、いずれも1始まり)：
  - A(1) 管理番号
  - B(2) 商品名
  - C(3) ジャンル
  - D(4) 系統
  - E(5) ブランド
  - F(6) 出品価格
  - G(7) 商品の状態
  - M(13) 季節
  - N(14) 出品点数(常に`1`固定で書き込み)
  - O(15) 出品日
  - R(18) 販売場所(常に`"メルカリ"`固定で書き込み)
  - AL(38) メモ(保管場所)
  - AS(45) メルカリアカウント
  - AT(46) メルカリ商品URL/画像 = `ROW_WIDTH`(書き込み範囲の右端)
- **数式列は上書きしない方針で、既存2行目の数式テンプレートをそのまま行番号だけ差し替えて複製する**(`FORMULA_TEMPLATES`辞書、行挿入時に`inherit_from_before=False`で既存データ行から書式・入力規則を引き継ぐ設計)。数式列一覧：
  - K(11) 仕入れ合計コスト
  - U(21) 販売手数料
  - V(22) 利益
  - W(23) 利益率
  - X(24) 仕入れ利益率
  - Y(25) リードタイム
  - Z(26) 在庫日数
  - AA(27) 売却フラグ
  - AF(32) 閲覧率
  - AK(37) 決済リードタイム
- **入力規則の主要enum**(`item_register_api/models.py`、listing-webapp側`src/lib/types.ts`にも同じ値を重複定義)：
  - ジャンル：トップス/ボトムス/アウター/ワンピース/小物/その他
  - 系統：古着/ストリート/きれいめ/スポーツ/Y2K/その他
  - 商品の状態：新品/未使用/目立った傷なし/やや傷あり
  - 季節：春夏/秋冬/オールシーズン

## 14. デプロイ手順(listing-webapp)

1. `cloudbuild.yaml`を使い、Cloud Buildで明示的にDockerビルドを実行する。
   - **理由**：`gcloud run deploy --source`の`--set-build-env-vars`はDockerfileビルドには効かないことをgcloud SDKのソースコード自体を読んで確認済み(buildpacksビルド専用の仕組みのため)。
2. `NEXT_PUBLIC_FIREBASE_API_KEY`/`NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`/`NEXT_PUBLIC_FIREBASE_PROJECT_ID`/`NEXT_PUBLIC_FIREBASE_APP_ID`の4つを`--build-arg`(`cloudbuild.yaml`の`_NEXT_PUBLIC_FIREBASE_*`置換変数経由)としてDockerビルドに渡す。`Dockerfile`のbuilderステージで`ARG`→`ENV`変換してから`npm run build`。
3. `cloudbuild.yaml`の`verify-embedded-values`ステップが、ビルド後のイメージ内`/app/.next/static/`をgrepし、`NEXT_PUBLIC_FIREBASE_API_KEY`の値が実際に埋め込まれているか自動検証する。埋め込まれていなければビルド自体が失敗する。
4. ビルド成功後、`gcloud artifacts docker images describe ...:latest --format="value(image_summary.digest)"`でsha256 digestを取得。
5. `gcloud run deploy listing-webapp --image=...@sha256:...`のように**`:latest`ではなく確認済みdigestを明示指定**してデプロイする(タグの意図しない書き換わりを防ぐため)。
6. デプロイ時、以下は毎回同じ値を維持する：
   - `--service-account listing-webapp-run@project-d3aeaeea-14fc-48ae-860.iam.gserviceaccount.com`
   - `--memory=512Mi --min-instances=0 --max-instances=1`
   - `--set-env-vars="FIREBASE_PROJECT_ID=...,FIREBASE_STORAGE_BUCKET=...,ALLOWED_LOGIN_EMAIL=...,ITEM_REGISTER_API_BASE_URL=..."`
   - `--set-secrets="ITEM_REGISTER_API_KEY=item-register-api-key:latest"`
7. デプロイ後、`/login`が200を返すこと、未ログイン状態で`/`等が`/login?next=...`へ307リダイレクトすることを確認する(読み取り専用のcurl確認)。
8. **item-register-apiは不用意に再デプロイしない**。listing-webapp側の変更はitem-register-apiに影響しないため、通常はlisting-webappのみを再デプロイすれば十分。

## 15. テスト方針

- `npm run typecheck`(`tsc --noEmit`)→`npm run build`(`next build`)→`npm test`(`node --import tsx --test tests/**/*.test.ts`)の順にローカル検証してから、Cloud Build/Cloud Runデプロイに進む。
- `npm test`はGCPに一切接続しない純粋ロジックテストのみ(現状21件、`tests/`配下)。`src/lib/firestoreItems.ts`等のFirestore Admin SDKを直接呼ぶコードは、既存のテストランナーからは検証できない(§16参照)。
- **実機テストが必要な項目**：Firebase Authenticationのログインフロー(Googleサインインのポップアップ)、写真アップロード(スマホのカメラロール/ファイル選択)、クリップボード読込(`navigator.clipboard.readText()`、実ブラウザのユーザージェスチャーが必要)。これらはFirebase Emulator Suiteでの結合テストも実施しておらず、常に実機で確認している。
- Firestore/Sheets/Storageの状態確認は、原則**読み取り専用コマンド**(`gcloud firestore`系REST API呼び出し、`gcloud storage ls`、Sheets APIのGET)で行う。書き込みが必要なテストは、実行前に送信データを提示しユーザーの承認を得てから1件のみ実行する運用を継続している。
- **本番データを使う前にテスト商品で確認する**運用を徹底している。テストで作成したFirestoreドキュメント・Sheets行・登録ログ・Storage写真は、確認完了後にユーザーの指示で削除している。
- **管理番号発番後のテストデータ削除は慎重に行う**：削除前に必ずシートの現在の行順を再確認し(本番商品の行が別の行番号にずれている可能性があるため)、対象行番号を確定させてから`batchUpdate`の`deleteDimension`を実行する。過去に、本番商品だと思っていたものが実はテストデータだった(逆のケースも)ため、削除対象は都度ユーザーに確認すること。

## 16. 既知の注意点

- `src/lib/firestoreItems.ts`は`import "server-only"`を含む。この`server-only`パッケージは`node_modules`に実体がなく(Next.jsのビルド機構が特別に解決する)、既存の`node --test`ベースのテスト基盤からは直接importできないことを確認済み。そのため`markCancelled`/`markSheetRegistered`等のFirestore書き込みロジック自体の単体テストは現状存在せず、実機またはFirestore Emulator導入まで対応不可。
- listing-webappはFirestore/Storageへの直接ブラウザアクセスを一切許可しない設計(`firestore.rules`/`storage.rules`はクライアントSDKからの読み書きを全面的に`false`で拒否するフェイルセーフ。実際のアクセスはすべてサーバー側API route経由)。
- `sheet_registered`/`listed`の商品は「出品待ちから外す」対象外(ボタン自体が表示されない)。
- 管理番号発番前(`draft`/`pending`)の商品だけ`cancelled`にできる。
- メルカリへの写真の自動転送は行わない。出品作業は「Webアプリの写真を見ながら、スマホの写真フォルダから該当写真を手動で選ぶ」運用を前提にしている。
- Webアプリ側に保存する写真は、識別用途であれば代表1枚でも運用上問題ない(複数枚アップロード自体は可能)。
- README.md(`section5-1/listing_webapp/README.md`)は初期実装時点の内容のままで、`cancelled`ステータス・クリップボード読込・description完成版反映修正など、後から追加した機能が反映されていない。**このPROJECT_NOTES.mdの方が新しく、実態に近い**。

## 17. 今後の改善候補(実装済み/未実装を明確化)

**未実装(候補のみ、コード上の対応なし)**：
- 売却後分析の結果を改善ルールとして蓄積する仕組み
- 「改善ルールシート」のようなフィードバックループ
- 上記の改善ルールを商品登録ロジック(GPTプロンプトやアプリのバリデーション)へ反映する仕組み
- PWA化(オフライン対応・ホーム画面追加等、現状は通常のレスポンシブWebアプリのまま)
- UI改善全般(README.mdの「未実装・注意点」に記載の通り、エラー表示・空状態表示は最小限)

これらはいずれも要望・アイデア段階で、コード・設計とも着手していない。

## 18. 触らない方がよいもの

- **item-register-apiの冪等性ロジック**(`service.py`の`request_id`チェック・ロック・再チェックの一連の流れ)。既に実機で二重登録防止を検証済みのため、変更する場合は再検証が必須。
- **`request_id`仕様**(`webapp-{FirestoreドキュメントID}`形式で1回だけ生成し使い回す)。この形式を変えるとitem-register-api側の重複防止ロジックとの整合性が崩れる。
- **管理番号採番ロジック**(`get_max_management_number`/`build_management_number`、YYMM+連番)。Google Sheets側の運用(手動で入力していた頃からの番号体系)と密接に結びついているため、変更は慎重に。
- **Secret Manager内の値**(`item-register-api-key`/`item-register-sa-json`の中身)。画面・ログに表示しない運用を一貫して継続している。
- **既存Google Sheets数式列**(§13の数式列一覧)。行挿入時に`inherit_from_before=False`で既存データ行から引き継ぐ設計になっており、数式自体をコードで生成・書き込みしているわけではない(既存2行目の数式を複製している)。数式の中身を変更する場合はシート側での修正が先。
- **既存本番商品データ**(Firestore・Google Sheets双方)。テストデータと混在させないよう、削除・確認作業の前には必ず現在の状態を読み取り専用で確認すること(§15参照)。

## 19. 作業再開時の最初の手順

新しいClaude Codeセッションでは、着手前に以下の順で確認すること：

1. この`PROJECT_NOTES.md`を読む
2. `git status`を確認する(本プロジェクトのコードは未コミットのuntracked状態である可能性が高い点に注意)
3. 現在のブランチ・差分を確認する
4. 対象機能の実コードを確認する(このドキュメントは要約であり、実装の詳細・最新の変更点は必ずコード自体で再確認すること)
5. 変更前に影響範囲をユーザーへ報告し、承認を得てから着手する(特にGCPリソースの変更・Cloud Runデプロイ・Google Sheets/Firestore/Storageへの書き込みは、既存の運用ルール通り事前承認が必須)
