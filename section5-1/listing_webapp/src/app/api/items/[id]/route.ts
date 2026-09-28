/**
 * GET   /api/items/:id   商品1件取得(③画面用)
 * PATCH /api/items/:id   商品編集(文字数超過やタグ欠落の修正など)
 */

import { NextResponse } from "next/server";
import { withSession } from "@/lib/apiHandler";
import { getItem, updateItemFields } from "@/lib/firestoreItems";

const EDITABLE_FIELDS = [
  "title",
  "genre",
  "style",
  "brand",
  "sale_price",
  "condition",
  "season",
  "storage_location",
  "description",
  "mercari_account",
] as const;

export async function GET(_request: Request, { params }: { params: { id: string } }) {
  return withSession(async () => {
    const item = await getItem(params.id);
    if (!item) {
      return NextResponse.json({ error: "商品が見つかりません" }, { status: 404 });
    }
    return NextResponse.json({ item });
  });
}

export async function PATCH(request: Request, { params }: { params: { id: string } }) {
  return withSession(async () => {
    const body = await request.json().catch(() => null);
    if (!body || typeof body !== "object") {
      return NextResponse.json({ error: "リクエストボディが不正です" }, { status: 400 });
    }

    const patch: Record<string, unknown> = {};
    for (const key of EDITABLE_FIELDS) {
      if (key in body) patch[key] = body[key];
    }
    if (Object.keys(patch).length === 0) {
      return NextResponse.json({ error: "更新対象のフィールドがありません" }, { status: 400 });
    }

    const existing = await getItem(params.id);
    if (!existing) {
      return NextResponse.json({ error: "商品が見つかりません" }, { status: 404 });
    }

    const item = await updateItemFields(params.id, patch);
    return NextResponse.json({ item });
  });
}
