/**
 * POST /api/items/:id/photos
 * multipart/form-data (`file`フィールド)で写真を1枚受け取り、Cloud Storageへ保存する。
 * ①画面から商品ごとに複数回呼び出すことで複数枚アップロードに対応する。
 */

import { NextResponse } from "next/server";
import { withSession } from "@/lib/apiHandler";
import { addPhotoPath, getItem } from "@/lib/firestoreItems";
import { uploadItemPhoto } from "@/lib/storagePhotos";

const ALLOWED_CONTENT_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic"];
const MAX_PHOTO_BYTES = 15 * 1024 * 1024; // 15MB(スマホ写真1枚を十分許容)

export async function POST(request: Request, { params }: { params: { id: string } }) {
  return withSession(async () => {
    const existing = await getItem(params.id);
    if (!existing) {
      return NextResponse.json({ error: "商品が見つかりません" }, { status: 404 });
    }

    const formData = await request.formData().catch(() => null);
    const file = formData?.get("file");
    if (!file || !(file instanceof File)) {
      return NextResponse.json({ error: "fileフィールドが必要です" }, { status: 400 });
    }
    if (!ALLOWED_CONTENT_TYPES.includes(file.type)) {
      return NextResponse.json({ error: `対応していない画像形式です: ${file.type}` }, { status: 400 });
    }
    if (file.size > MAX_PHOTO_BYTES) {
      return NextResponse.json({ error: "画像サイズが大きすぎます(上限15MB)" }, { status: 400 });
    }

    const bytes = Buffer.from(await file.arrayBuffer());
    const nextIndex = existing.photo_paths.length + 1;
    const { path } = await uploadItemPhoto(params.id, nextIndex, bytes, file.type);
    const item = await addPhotoPath(params.id, path);

    return NextResponse.json({ item, photo_path: path }, { status: 201 });
  });
}
