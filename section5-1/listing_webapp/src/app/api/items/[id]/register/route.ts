/**
 * POST /api/items/:id/register
 * ③画面「Google Sheetsへ登録」。既存の item-register-api (Cloud Run) をサーバー側から呼ぶ。
 * APIキーはこのルート内でのみ使われ、ブラウザには一切渡らない。
 *
 * 文字数超過は例外なくブロックする。#AddOneVintage欠落は overrideTagWarning=true の場合のみ許可する。
 * これはクライアント側の evaluateRegistrationEligibility と同じロジックをサーバー側でも
 * 再検証する(クライアント側の判定はUXのためであり、信頼できる境界はサーバー側)。
 */

import { NextResponse } from "next/server";
import { withSession } from "@/lib/apiHandler";
import { getItem, markSheetRegistered } from "@/lib/firestoreItems";
import { ItemRegisterApiError, registerItemToSheet } from "@/lib/itemRegisterClient";
import { evaluateRegistrationEligibility } from "@/lib/validation";

export async function POST(request: Request, { params }: { params: { id: string } }) {
  return withSession(async () => {
    const item = await getItem(params.id);
    if (!item) {
      return NextResponse.json({ error: "商品が見つかりません" }, { status: 404 });
    }

    const body = await request.json().catch(() => ({}));
    const overrideTagWarning = body?.overrideTagWarning === true;

    const eligibility = evaluateRegistrationEligibility(item, overrideTagWarning);
    if (!eligibility.canRegister) {
      return NextResponse.json(
        {
          error: "登録条件を満たしていません",
          hardBlockReasons: eligibility.hardBlockReasons,
          overridableReasons: eligibility.overridableReasons,
        },
        { status: 422 }
      );
    }

    try {
      const result = await registerItemToSheet(item);
      const updated = await markSheetRegistered(params.id, result.management_number, result.description);
      return NextResponse.json({ item: updated, already_registered: result.already_registered });
    } catch (e) {
      if (e instanceof ItemRegisterApiError) {
        const status = e.kind === "auth" ? 502 : e.kind === "validation" ? 400 : 502;
        return NextResponse.json({ error: e.message, kind: e.kind }, { status });
      }
      throw e;
    }
  });
}
