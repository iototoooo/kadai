/**
 * Edge runtimeで動くミドルウェア。セッションCookieの「存在」だけを見て
 * 未ログイン時に/loginへリダイレクトするUX目的の軽量チェック。
 *
 * 重要: これは本当の認可ではない(Edge runtimeではFirebase Admin SDKによる
 * 署名検証ができないため)。実際のセキュリティ境界は各API route /
 * server componentが lib/sessionAuth.ts の requireSession() を呼んで
 * Cookieを検証することで確保している。ここを通っただけのリクエストを
 * 信頼してFirestore/Storageへアクセスしてはならない。
 */

import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE_NAME = process.env.SESSION_COOKIE_NAME || "listing_webapp_session";

const PUBLIC_PATHS = ["/login", "/api/session"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const isPublic =
    PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`)) ||
    pathname.startsWith("/_next") ||
    pathname === "/favicon.ico";

  if (isPublic) {
    return NextResponse.next();
  }

  const hasSessionCookie = Boolean(request.cookies.get(SESSION_COOKIE_NAME)?.value);
  if (!hasSessionCookie) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
