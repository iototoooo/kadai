/**
 * POST /api/session
 * ブラウザでGoogleサインインして得たFirebase IDトークンを受け取り、
 * 許可アカウント(ALLOWED_LOGIN_EMAIL)であることを確認したうえでセッションCookieを発行する。
 * このルートのみ、ログイン前(セッションCookie無し)でも呼べる(middleware.tsのPUBLIC_PATHS参照)。
 */

import { NextResponse } from "next/server";
import { adminAuth } from "@/lib/firebaseAdmin";
import { createSessionCookie, SESSION_COOKIE_NAME } from "@/lib/sessionAuth";

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const idToken = body?.idToken;
  if (!idToken || typeof idToken !== "string") {
    return NextResponse.json({ error: "idTokenが必要です" }, { status: 400 });
  }

  let decoded;
  try {
    decoded = await adminAuth().verifyIdToken(idToken);
  } catch {
    return NextResponse.json({ error: "IDトークンが無効です" }, { status: 401 });
  }

  const allowedEmail = process.env.ALLOWED_LOGIN_EMAIL;
  if (!decoded.email || !allowedEmail || decoded.email.toLowerCase() !== allowedEmail.toLowerCase()) {
    return NextResponse.json({ error: "このアカウントではログインできません" }, { status: 403 });
  }

  const sessionCookie = await createSessionCookie(idToken);

  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE_NAME, sessionCookie, {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: 14 * 24 * 60 * 60,
  });
  return response;
}
