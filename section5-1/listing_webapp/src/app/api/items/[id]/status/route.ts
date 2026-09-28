/**
 * PATCH /api/items/:id/status
 * body: { action: "mark_pending" | "mark_listed" | "mark_cancelled" }
 *
 * - mark_pending  : ①画面の「出品待ちに保存」(draft -> pending)
 * - mark_listed   : ③画面の「出品済みにする」(sheet_registered -> listed)。
 *                   写真の30日後自動削除カウントダウンも同時に開始する(firestoreItems.markListed参照)。
 * - mark_cancelled: ③画面の「出品待ちから外す」(draft/pending -> cancelled)。
 *                   Google Sheets・item-register-apiには一切アクセスしない。
 *                   写真の30日後自動削除カウントダウンも同時に開始する(firestoreItems.markCancelled参照)。
 */

import { NextResponse } from "next/server";
import { withSession } from "@/lib/apiHandler";
import { getItem, markCancelled, markListed, markPending } from "@/lib/firestoreItems";

const ACTIONS = ["mark_pending", "mark_listed", "mark_cancelled"] as const;
type Action = (typeof ACTIONS)[number];

export async function PATCH(request: Request, { params }: { params: { id: string } }) {
  return withSession(async () => {
    const body = await request.json().catch(() => null);
    const action = body?.action as Action | undefined;
    if (!action || !ACTIONS.includes(action)) {
      return NextResponse.json({ error: `actionは次のいずれかを指定してください: ${ACTIONS.join(", ")}` }, { status: 400 });
    }

    const existing = await getItem(params.id);
    if (!existing) {
      return NextResponse.json({ error: "商品が見つかりません" }, { status: 404 });
    }

    if (action === "mark_pending") {
      if (existing.status !== "draft") {
        return NextResponse.json({ error: `現在のステータス(${existing.status})からは実行できません` }, { status: 409 });
      }
      const item = await markPending(params.id);
      return NextResponse.json({ item });
    }

    if (action === "mark_cancelled") {
      if (existing.status !== "draft" && existing.status !== "pending") {
        return NextResponse.json({ error: `現在のステータス(${existing.status})からは実行できません` }, { status: 409 });
      }
      const item = await markCancelled(params.id);
      return NextResponse.json({ item });
    }

    // mark_listed
    if (existing.status !== "sheet_registered") {
      return NextResponse.json({ error: `現在のステータス(${existing.status})からは実行できません` }, { status: 409 });
    }
    const item = await markListed(params.id);
    return NextResponse.json({ item });
  });
}
