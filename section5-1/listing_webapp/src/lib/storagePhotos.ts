/**
 * 商品写真のCloud Storage操作(アップロード・ストリーミング読み出し・自動削除用メタデータ設定)。
 * サーバー側(API route)からのみ呼ぶこと。ブラウザはバケットへ直接アクセスしない。
 *
 * 自動削除の仕組み:
 *   「出品済み」に変更されたタイミングで、その商品の全写真オブジェクトに
 *   GCSの customTime メタデータ = listed_at を設定する。
 *   バケット側に「daysSinceCustomTime >= PHOTO_RETENTION_DAYS で削除」という
 *   ライフサイクルルールを設定しておくことで、Cloud Schedulerや自前バッチなしに
 *   GCSが自動的に削除してくれる(このルール自体はGCPリソース変更のため、
 *   ユーザー承認を得たうえでバケット作成時に設定する)。
 */

import "server-only";
import { randomUUID } from "node:crypto";
import { adminStorageBucket } from "./firebaseAdmin";

function photoObjectPath(itemId: string, index: number, extension: string): string {
  return `items/${itemId}/${index}_${randomUUID()}${extension}`;
}

function extensionFromContentType(contentType: string): string {
  switch (contentType) {
    case "image/jpeg":
      return ".jpg";
    case "image/png":
      return ".png";
    case "image/webp":
      return ".webp";
    case "image/heic":
      return ".heic";
    default:
      return "";
  }
}

export interface UploadPhotoResult {
  path: string;
}

export async function uploadItemPhoto(
  itemId: string,
  index: number,
  bytes: Buffer,
  contentType: string
): Promise<UploadPhotoResult> {
  const bucket = adminStorageBucket();
  const path = photoObjectPath(itemId, index, extensionFromContentType(contentType));
  const file = bucket.file(path);
  await file.save(bytes, {
    contentType,
    resumable: false,
    metadata: { cacheControl: "private, max-age=0, no-transform" },
  });
  return { path };
}

export interface StreamedPhoto {
  stream: NodeJS.ReadableStream;
  contentType: string;
}

/** 写真プロキシ配信用。オブジェクトが存在しない場合(30日経過後の自動削除後など)はnullを返す。 */
export async function readItemPhotoStream(path: string): Promise<StreamedPhoto | null> {
  const bucket = adminStorageBucket();
  const file = bucket.file(path);
  const [exists] = await file.exists();
  if (!exists) return null;

  const [metadata] = await file.getMetadata();
  return {
    stream: file.createReadStream(),
    contentType: (metadata.contentType as string) || "application/octet-stream",
  };
}

/**
 * 「出品済み」への変更時に呼ぶ。指定した写真パス全てへcustomTimeを設定し、
 * GCSライフサイクルルールによる自動削除の起点にする。
 * 個々のオブジェクトが既に無い場合(再実行など)はスキップする。
 */
export async function markPhotosForRetentionCountdown(photoPaths: string[], listedAtMs: number): Promise<void> {
  const bucket = adminStorageBucket();
  const customTime = new Date(listedAtMs).toISOString();
  await Promise.all(
    photoPaths.map(async (path) => {
      const file = bucket.file(path);
      const [exists] = await file.exists();
      if (!exists) return;
      await file.setMetadata({ customTime });
    })
  );
}
