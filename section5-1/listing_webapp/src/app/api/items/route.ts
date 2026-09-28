/**
 * GET  /api/items?status=pending,sheet_registered  一覧取得(②画面用)
 * POST /api/items  新規商品の保存(①画面「出品待ちに保存」用)
 */

import { NextResponse } from "next/server";
import { withSession } from "@/lib/apiHandler";
import { createItem, listItems } from "@/lib/firestoreItems";
import type { Item, ItemStatus } from "@/lib/types";

const VALID_STATUSES: ItemStatus[] = ["draft", "pending", "sheet_registered", "listed"];

export async function GET(request: Request) {
  return withSession(async () => {
    const url = new URL(request.url);
    const statusParam = url.searchParams.get("status");
    const statuses = statusParam
      ? (statusParam.split(",").filter((s): s is ItemStatus => VALID_STATUSES.includes(s as ItemStatus)))
      : undefined;

    const items = await listItems(statuses);
    return NextResponse.json({ items });
  });
}

export async function POST(request: Request) {
  return withSession(async () => {
    const body = await request.json().catch(() => null);
    if (!body) {
      return NextResponse.json({ error: "リクエストボディが不正です" }, { status: 400 });
    }

    const required = [
      "title",
      "genre",
      "style",
      "sale_price",
      "condition",
      "season",
      "storage_location",
      "description",
      "raw_gpt_text",
    ] as const;
    const missing = required.filter((key) => body[key] === undefined || body[key] === null || body[key] === "");
    if (missing.length > 0) {
      return NextResponse.json({ error: `必須項目が不足しています: ${missing.join(", ")}` }, { status: 400 });
    }

    const item: Item = await createItem(
      {
        title: body.title,
        genre: body.genre,
        style: body.style,
        brand: body.brand ?? null,
        sale_price: Number(body.sale_price),
        condition: body.condition,
        season: body.season,
        storage_location: body.storage_location,
        description: body.description,
        mercari_account: body.mercari_account ?? null,
        raw_gpt_text: body.raw_gpt_text,
      },
      "pending"
    );

    return NextResponse.json({ item }, { status: 201 });
  });
}
