/**
 * GET /api/photos/:itemId/:filename
 * 商品写真の配信プロキシ。ブラウザはCloud Storageへ直接アクセスせず、必ずここを経由する
 * (認証チェック + オブジェクトが存在しない場合の30日経過後フォールバック表示のため)。
 */

import { NextResponse } from "next/server";
import { withSession } from "@/lib/apiHandler";
import { readItemPhotoStream } from "@/lib/storagePhotos";

export async function GET(_request: Request, { params }: { params: { itemId: string; filename: string } }) {
  return withSession(async () => {
    const path = `items/${params.itemId}/${params.filename}`;
    const photo = await readItemPhotoStream(path);
    if (!photo) {
      // 30日経過後の自動削除、またはアップロード直後の一時的な不整合。
      return NextResponse.json({ error: "写真は保存期間(30日)を過ぎたため削除されたか、見つかりません" }, { status: 404 });
    }

    // NodeのReadableStreamをResponseのBodyInitへ変換する。
    const webStream = new ReadableStream({
      start(controller) {
        photo.stream.on("data", (chunk: Buffer) => controller.enqueue(chunk));
        photo.stream.on("end", () => controller.close());
        photo.stream.on("error", (err) => controller.error(err));
      },
      cancel() {
        (photo.stream as NodeJS.ReadableStream & { destroy?: () => void }).destroy?.();
      },
    });

    return new Response(webStream, {
      headers: {
        "Content-Type": photo.contentType,
        "Cache-Control": "private, max-age=3600",
      },
    });
  });
}
