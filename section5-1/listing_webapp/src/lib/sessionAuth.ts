/**
 * セッションCookieの発行・検証。
 *
 * セキュリティモデル:
 * - middleware.ts はCookieの「存在」だけを見て未ログイン時に/loginへリダイレクトする
 *   (Edge runtimeではFirebase Admin SDKが使えないための軽量チェック)。
 * - 実際の認可(Cookieの署名検証 + 許可メールアドレス一致確認)は、
 *   各API route / server componentがこのモジュールの requireSession() を呼んで行う。
 *   ここを通らないコードパスでFirestore/Storageへアクセスしてはならない。
 */

import "server-only";
import { cookies } from "next/headers";
import { adminAuth } from "./firebaseAdmin";

export const SESSION_COOKIE_NAME = process.env.SESSION_COOKIE_NAME || "listing_webapp_session";
const SESSION_EXPIRES_IN_MS = 14 * 24 * 60 * 60 * 1000; // 14日

export async function createSessionCookie(idToken: string): Promise<string> {
  return adminAuth().createSessionCookie(idToken, { expiresIn: SESSION_EXPIRES_IN_MS });
}

export interface SessionUser {
  uid: string;
  email: string;
}

export class UnauthorizedError extends Error {
  constructor(message = "認証されていません") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

/**
 * 現在のリクエストのセッションCookieを検証し、許可アカウントであることまで確認する。
 * 未ログイン・不正Cookie・許可アカウント以外の場合はUnauthorizedErrorを投げる。
 */
export async function requireSession(): Promise<SessionUser> {
  const cookieStore = cookies();
  const sessionCookie = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!sessionCookie) {
    throw new UnauthorizedError("セッションCookieがありません");
  }

  let decoded;
  try {
    decoded = await adminAuth().verifySessionCookie(sessionCookie, true);
  } catch {
    throw new UnauthorizedError("セッションCookieが無効です");
  }

  const email = decoded.email;
  const allowedEmail = process.env.ALLOWED_LOGIN_EMAIL;
  if (!email || !allowedEmail || email.toLowerCase() !== allowedEmail.toLowerCase()) {
    throw new UnauthorizedError("許可されていないアカウントです");
  }

  return { uid: decoded.uid, email };
}
