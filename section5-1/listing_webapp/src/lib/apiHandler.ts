/**
 * API route共通のセッション確認ラッパー。UnauthorizedErrorを401 JSONへ変換する。
 */

import "server-only";
import { NextResponse } from "next/server";
import { requireSession, UnauthorizedError, type SessionUser } from "./sessionAuth";

export async function withSession<T>(
  handler: (user: SessionUser) => Promise<T>
): Promise<T | NextResponse> {
  try {
    const user = await requireSession();
    return await handler(user);
  } catch (e) {
    if (e instanceof UnauthorizedError) {
      return NextResponse.json({ error: e.message }, { status: 401 });
    }
    console.error(e);
    return NextResponse.json({ error: `想定外のエラー: ${(e as Error).message}` }, { status: 500 });
  }
}
