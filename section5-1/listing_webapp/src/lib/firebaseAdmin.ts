/**
 * Firebase Admin SDK のサーバー側初期化(サービスアカウント権限)。
 * API route / server component からのみimportすること(ブラウザバンドルに含めない)。
 *
 * 認証情報はサービスアカウントJSONキーを発行せず、Application Default Credentials(ADC)で解決する。
 * Cloud Run上では、サービスにアタッチされた実行サービスアカウントの権限をADCが自動的に使う
 * (メタデータサーバー経由。キーファイルの発行・保存・ローテーション管理が一切不要になる)。
 * ローカルでFirebase Emulator Suiteを使う場合は、Admin SDKが自動的に
 * FIRESTORE_EMULATOR_HOST / FIREBASE_AUTH_EMULATOR_HOST / FIREBASE_STORAGE_EMULATOR_HOST
 * を見て接続先を切り替える(コード変更不要)。
 *
 * ローカルでEmulatorを使わずに動作確認する場合は、事前に
 * `gcloud auth application-default login` を実行してユーザー資格情報をADCとして
 * 使えるようにする必要がある(この場合、ユーザー自身にFirestore/Storageの権限が必要)。
 */

import { applicationDefault, getApps, initializeApp, type App } from "firebase-admin/app";
import { getAuth } from "firebase-admin/auth";
import { getFirestore } from "firebase-admin/firestore";
import { getStorage } from "firebase-admin/storage";

function buildAdminApp(): App {
  const existing = getApps();
  if (existing.length > 0) {
    return existing[0]!;
  }

  const projectId = process.env.FIREBASE_PROJECT_ID;
  const storageBucket = process.env.FIREBASE_STORAGE_BUCKET;

  if (!projectId) {
    throw new Error("FIREBASE_PROJECT_ID が設定されていません");
  }

  // Emulator接続時(ローカルテスト)は認証情報無しでも動作させる。
  // Firestore/Auth/Storageいずれかのエミュレータが設定されていれば対象とする
  // (例: Storageエミュレータだけを使う場合でもADC解決を試みて失敗しないように)。
  const usingEmulator = Boolean(
    process.env.FIRESTORE_EMULATOR_HOST ||
      process.env.FIREBASE_AUTH_EMULATOR_HOST ||
      process.env.FIREBASE_STORAGE_EMULATOR_HOST
  );

  if (usingEmulator) {
    return initializeApp({ projectId, storageBucket });
  }

  // Cloud Run実行サービスアカウント(またはローカルのADCログイン)の権限を使う。
  return initializeApp({
    credential: applicationDefault(),
    projectId,
    storageBucket,
  });
}

let app: App | null = null;

function getAdminApp(): App {
  if (!app) {
    app = buildAdminApp();
  }
  return app;
}

export function adminAuth() {
  return getAuth(getAdminApp());
}

export function adminFirestore() {
  return getFirestore(getAdminApp());
}

export function adminStorageBucket() {
  const bucketName = process.env.FIREBASE_STORAGE_BUCKET;
  if (!bucketName) throw new Error("FIREBASE_STORAGE_BUCKET が設定されていません");
  return getStorage(getAdminApp()).bucket(bucketName);
}
