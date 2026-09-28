/**
 * GET /api/items/:id/next
 * ③画面「次の商品へ」。出品待ちキュー内でcurrent idの次にあるアクティブな商品IDを返す。
 * 無ければ nextItemId: null (②一覧へ戻る)。
 */

import { NextResponse } from "next/server";
import { withSession } from "@/lib/apiHandler";
import { listItems } from "@/lib/firestoreItems";
import { ACTIVE_QUEUE_STATUSES, selectNextQueueItemId } from "@/lib/queueOrder";

export async function GET(_request: Request, { params }: { params: { id: string } }) {
  return withSession(async () => {
    const items = await listItems(ACTIVE_QUEUE_STATUSES);
    const nextItemId = selectNextQueueItemId(items, params.id);
    return NextResponse.json({ nextItemId });
  });
}
