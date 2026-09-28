# 出品待ち管理Webアプリ (listing_webapp)

スマホ完結型の「出品待ち管理」Webアプリ。GPTが生成した商品データ(JSON)を貼り付けて保存し、
出品時にGoogle Sheets(既存の`item-register-api`経由)へ登録して、メルカリへの出品作業を支援する。

設計の背景・全体構成・データ構造などは会話履歴の設計案を参照。このREADMEは実装・運用の要点のみ記載する。

## まだ行っていないこと(要承認)

以下はコード作成のみで、**実行・適用はしていない**。本番反映にはユーザーの承認が必要:

- ~~Firebase プロジェクトの作成・Firebase Authentication(Google Sign-In)の有効化~~ (完了済み。ユーザーがFirebase ConsoleでWebアプリ登録・Googleログイン有効化を実施)
- Firestore(Native mode)の有効化・複合インデックス(`firestore.indexes.json`)の適用
- Cloud Storageバケットの新規作成・ライフサイクルルール(`gcs-lifecycle.json`)の適用
- Cloud Run実行サービスアカウントの作成・IAM権限付与(Firestore/Storage/Firebase Auth用の最小権限。Firebase Authについては`firebaseauth.users.createSession`と`firebaseauth.users.get`のみを持つカスタムロールを推奨。`item-register-api-key`シークレットへのアクセス権限も別途必要)
- Cloud Run環境変数(`ITEM_REGISTER_API_KEY`等)・`NEXT_PUBLIC_FIREBASE_*`の設定
- Cloud Runへの新規サービスとしてのデプロイ

**認証情報の方針**: Firebase Admin SDKはサービスアカウントJSONキーを発行せず、Cloud Run実行サービスアカウントの権限をApplication Default Credentials(ADC)経由で使う(`src/lib/firebaseAdmin.ts`)。長期間有効な鍵ファイルを一切作成・保存しない。

## 画面構成

- `/login` ログイン(Googleサインイン、許可アカウント1件のみ)
- `/new` ①出品待ち保存画面(ログイン後デフォルト)
- `/queue` ②出品待ち一覧画面
- `/item/[id]` ③出品作業画面

## ディレクトリ構成

```
listing_webapp/
├── src/
│   ├── middleware.ts          # セッションCookie「存在」チェックのみ(Edge runtime)
│   ├── app/
│   │   ├── login/page.tsx
│   │   ├── new/page.tsx       # ①
│   │   ├── queue/page.tsx     # ②
│   │   ├── item/[id]/page.tsx # ③
│   │   └── api/
│   │       ├── session/route.ts         # ログイン(IDトークン→セッションCookie)
│   │       ├── session/logout/route.ts
│   │       ├── items/route.ts           # GET一覧 / POST新規保存
│   │       ├── items/[id]/route.ts      # GET1件 / PATCH編集
│   │       ├── items/[id]/photos/route.ts   # POST写真アップロード
│   │       ├── items/[id]/register/route.ts # POST Sheets登録(既存item-register-api呼び出し)
│   │       ├── items/[id]/status/route.ts   # PATCH ステータス変更
│   │       ├── items/[id]/next/route.ts     # GET 次の商品へ
│   │       └── photos/[itemId]/[filename]/route.ts # GET 写真配信プロキシ
│   ├── components/ (BottomNav / ItemCard / CopyButton / GoogleSignInButton)
│   └── lib/
│       ├── types.ts             # Item型・GptItemJson型・ステータス定義
│       ├── validation.ts        # GPT JSON解析・文字数チェック・#AddOneVintage判定・登録可否判定
│       ├── queueOrder.ts        # 「次の商品へ」の純粋ロジック(Firestore非依存)
│       ├── itemRegisterClient.ts # 既存item-register-api呼び出し(サーバー専用)
│       ├── firebaseAdmin.ts     # Firebase Admin SDK初期化(サーバー専用)
│       ├── firebaseClient.ts    # Firebase Client SDK(Googleサインインのみに使用)
│       ├── sessionAuth.ts       # セッションCookie発行・検証(サーバー専用、本当の認可境界)
│       ├── apiHandler.ts        # API route共通の認可ラッパー
│       ├── firestoreItems.ts    # Firestore CRUD(サーバー専用)
│       └── storagePhotos.ts     # Cloud Storageアップロード/配信/customTime設定(サーバー専用)
├── tests/                      # node:test による単体テスト(GCPに接続しない)
├── firestore.rules / storage.rules  # ブラウザからの直接アクセスを禁止するフェイルセーフ
├── firestore.indexes.json      # 未適用。一覧画面のstatusフィルタに必要な複合インデックス定義
├── gcs-lifecycle.json          # 未適用。写真の30日後自動削除ルール定義
├── firebase.json               # Emulator Suite設定(ローカルテスト用)
└── Dockerfile                  # 未ビルド。Cloud Run想定のstandalone出力
```

## 実装した機能

- **①保存画面**: GPT出力JSON貼り付け→解析→フィールド編集可能表示(`storage_location`はJSONから自動反映、手動修正可)、複数写真アップロード、保存後フォームを自動クリアして連続登録可能。
- **②一覧画面**: ステータス別フィルタ(出品待ち/シート登録済み/出品済み/作成中/すべて)、カード表示(サムネイル・商品名・価格・保管場所・ステータス・作成日時)。
- **③出品作業画面**: 写真一覧・詳細表示・インライン編集、商品名/商品説明/価格のワンタップコピー、Sheets登録(文字数超過は完全ブロック、`#AddOneVintage`欠落は警告+明示的な確認操作で登録可能)、管理番号表示、メルカリを開く、出品済みにする、次の商品へ(キュー内を直接遷移、②を経由しない)。
- **認証**: Firebase Authentication(Google Sign-In)。`ALLOWED_LOGIN_EMAIL`と一致する1アカウントのみサーバー側で許可。middlewareはCookie存在チェックのみ(UX用)、実際の認可は各API routeが`requireSession()`で行う。
- **Sheets連携**: サーバー側のみが`item-register-api`の`X-API-Key`を保持し、`request_id`をアイテム作成時に生成・使い回すことで冪等性を維持(既存APIの重複防止に依存)。
- **写真の自動削除設計**: 「出品済みにする」実行時に該当写真オブジェクトへ`customTime`(=`listed_at`)を設定。バケット側の`gcs-lifecycle.json`(未適用)を設定すれば、GCSが30日後に自動削除する(バッチ処理不要)。Firestoreの商品ドキュメント自体は削除しない(履歴として保持)。

## 未実装・注意点

- **Firebase Emulator Suiteでの結合テストは未実施**(Java実行環境の要否含め未確認)。現時点のローカルテストは、型チェック・ビルド・GCPに依存しない純粋ロジックの単体テストのみ。
- 写真アップロードは1枚ずつ逐次アップロード(並列化していない)。1回あたり数枚程度の想定であれば実用上問題ない見込み。
- HEIC形式の写真はContent-Typeとして許可しているが、ブラウザでのプレビュー表示(`<img>`)がHEICに対応していない可能性がある(iPhoneのデフォルト設定によってはJPEGへ自動変換されるため実害は小さい見込み)。
- `mercari_account`はGPT JSONの対象外のため未入力のまま(将来③画面の編集で追加可能な設計にはなっている)。
- 「メルカリを開く」は`https://jp.mercari.com/sell`への単純なリンク。自動転記・自動出品は要件通り未実装。
- エラーメッセージ・空状態表示は最小限。長期運用する場合はより丁寧なUI改善の余地あり。
- Cloud Run用の`Dockerfile`は作成したが、実際のビルド・デプロイは未実施。

## ローカル環境変数

`.env.example`を`.env.local`にコピーして値を設定する(Firebase/Firestore/Storage/Cloud Runへの実接続は承認後に値を用意する)。

## コマンド

```bash
npm install
npm run typecheck   # tsc --noEmit
npm run build        # next build
npm test              # node:test によるロジック単体テスト(GCP接続なし)
npm run dev            # ローカル開発サーバー
```
