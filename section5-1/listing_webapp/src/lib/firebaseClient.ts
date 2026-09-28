/**
 * Firebase Client SDK のブラウザ側初期化。
 * ここではGoogleサインインのみに使用する(Firestore/Storageへブラウザから直接アクセスしない)。
 * NEXT_PUBLIC_ プレフィックスの値は公開情報として扱ってよいもの(Firebase公式の仕様通り)。
 */

"use client";

import { initializeApp, getApps, type FirebaseOptions } from "firebase/app";
import { getAuth, GoogleAuthProvider, connectAuthEmulator } from "firebase/auth";

const firebaseConfig: FirebaseOptions = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};

export function getFirebaseClientApp() {
  const apps = getApps();
  return apps.length > 0 ? apps[0]! : initializeApp(firebaseConfig);
}

export function getClientAuth() {
  const auth = getAuth(getFirebaseClientApp());
  if (process.env.NEXT_PUBLIC_USE_AUTH_EMULATOR === "true") {
    connectAuthEmulator(auth, "http://127.0.0.1:9099", { disableWarnings: true });
  }
  return auth;
}

export function newGoogleProvider() {
  const provider = new GoogleAuthProvider();
  // 許可アカウントを絞り込みたいので、可能な場合はドメイン/アカウント選択ヒントを渡す。
  provider.setCustomParameters({ prompt: "select_account" });
  return provider;
}
