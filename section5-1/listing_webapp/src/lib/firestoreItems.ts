/**
 * Firestore `items` コレクションへのCRUD操作。
 * サーバー側(API route)からのみ呼ぶこと。
 *
 * 重要: Firestoreの商品ドキュメントは(要件により)削除しない。ステータスを
 * "listed" に変更しても履歴として残り続ける。写真のみCloud Storage側で
 * 30日後に自動削除される(storagePhotos.ts参照)。
 */

import "server-only";
import { Timestamp } from "firebase-admin/firestore";
import { adminFirestore } from "./firebaseAdmin";
import { markPhotosForRetentionCountdown } from "./storagePhotos";
import type { Item, ItemStatus, NewItemInput } from "./types";

const COLLECTION = "items";

type FirestoreItemDoc = Omit<
  Item,
  "id" | "created_at" | "updated_at" | "sheet_registered_at" | "listed_at" | "cancelled_at"
> & {
  created_at: Timestamp;
  updated_at: Timestamp;
  sheet_registered_at: Timestamp | null;
  listed_at: Timestamp | null;
  cancelled_at: Timestamp | null;
};

function toMillis(ts: Timestamp | null | undefined): number | null {
  return ts ? ts.toMillis() : null;
}

function fromDoc(id: string, data: FirestoreItemDoc): Item {
  return {
    ...data,
    id,
    created_at: data.created_at.toMillis(),
    updated_at: data.updated_at.toMillis(),
    sheet_registered_at: toMillis(data.sheet_registered_at),
    listed_at: toMillis(data.listed_at),
    // cancelled_atフィールドは今回追加。既存ドキュメントには存在しないため未定義の可能性があり、
    // toMillisの引数型にundefinedを許容してnullへフォールバックさせる。
    cancelled_at: toMillis(data.cancelled_at),
  };
}

export async function createItem(input: NewItemInput, status: Extract<ItemStatus, "draft" | "pending">): Promise<Item> {
  const db = adminFirestore();
  const ref = db.collection(COLLECTION).doc();
  const now = Timestamp.now();

  const doc: FirestoreItemDoc = {
    status,
    title: input.title,
    genre: input.genre,
    style: input.style,
    brand: input.brand ?? null,
    sale_price: input.sale_price,
    condition: input.condition,
    season: input.season,
    storage_location: input.storage_location,
    description: input.description,
    mercari_account: input.mercari_account ?? null,
    photo_paths: [],
    request_id: `webapp-${ref.id}`,
    management_number: null,
    raw_gpt_text: input.raw_gpt_text,
    created_at: now,
    updated_at: now,
    sheet_registered_at: null,
    listed_at: null,
    cancelled_at: null,
  };

  await ref.set(doc);
  return fromDoc(ref.id, doc);
}

export async function getItem(id: string): Promise<Item | null> {
  const db = adminFirestore();
  const snap = await db.collection(COLLECTION).doc(id).get();
  if (!snap.exists) return null;
  return fromDoc(snap.id, snap.data() as FirestoreItemDoc);
}

export async function listItems(statuses?: ItemStatus[]): Promise<Item[]> {
  const db = adminFirestore();
  let query = db.collection(COLLECTION).orderBy("created_at", "asc") as FirebaseFirestore.Query;
  if (statuses && statuses.length > 0) {
    query = query.where("status", "in", statuses);
  }
  const snap = await query.get();
  return snap.docs.map((d) => fromDoc(d.id, d.data() as FirestoreItemDoc));
}

/** ③画面での編集(文字数超過の修正など)。渡されたフィールドのみ更新する。 */
export async function updateItemFields(
  id: string,
  patch: Partial<
    Pick<
      Item,
      | "title"
      | "genre"
      | "style"
      | "brand"
      | "sale_price"
      | "condition"
      | "season"
      | "storage_location"
      | "description"
      | "mercari_account"
    >
  >
): Promise<Item> {
  const db = adminFirestore();
  const ref = db.collection(COLLECTION).doc(id);
  await ref.update({ ...patch, updated_at: Timestamp.now() });
  const updated = await getItem(id);
  if (!updated) throw new Error(`更新後に商品が見つかりません: ${id}`);
  return updated;
}

export async function addPhotoPath(id: string, path: string): Promise<Item> {
  const db = adminFirestore();
  const ref = db.collection(COLLECTION).doc(id);
  await db.runTransaction(async (tx) => {
    const snap = await tx.get(ref);
    if (!snap.exists) throw new Error(`商品が見つかりません: ${id}`);
    const data = snap.data() as FirestoreItemDoc;
    const photoPaths = [...data.photo_paths, path];
    tx.update(ref, { photo_paths: photoPaths, updated_at: Timestamp.now() });
  });
  const updated = await getItem(id);
  if (!updated) throw new Error(`更新後に商品が見つかりません: ${id}`);
  return updated;
}

/**
 * pending -> sheet_registered。Sheets登録成功後に呼ぶ。
 * finalDescription には item-register-api のレスポンスに含まれる完成版description
 * (末尾に「（S/N：管理番号）\n保管場所」が付与された文字列)をそのまま渡す。
 * これによりFirestore側のdescriptionも完成版に更新され、以降の画面表示・コピーに反映される。
 */
export async function markSheetRegistered(
  id: string,
  managementNumber: string,
  finalDescription: string
): Promise<Item> {
  const db = adminFirestore();
  const ref = db.collection(COLLECTION).doc(id);
  const now = Timestamp.now();
  await ref.update({
    status: "sheet_registered" satisfies ItemStatus,
    management_number: managementNumber,
    description: finalDescription,
    sheet_registered_at: now,
    updated_at: now,
  });
  const updated = await getItem(id);
  if (!updated) throw new Error(`更新後に商品が見つかりません: ${id}`);
  return updated;
}

/** sheet_registered -> listed。写真の30日後自動削除カウントダウンも同時に開始する。 */
export async function markListed(id: string): Promise<Item> {
  const db = adminFirestore();
  const ref = db.collection(COLLECTION).doc(id);
  const now = Timestamp.now();
  const snap = await ref.get();
  if (!snap.exists) throw new Error(`商品が見つかりません: ${id}`);
  const data = snap.data() as FirestoreItemDoc;

  await ref.update({
    status: "listed" satisfies ItemStatus,
    listed_at: now,
    updated_at: now,
  });

  // 写真削除カウントダウンの起点(customTime)を設定する。失敗してもステータス変更自体は成功させ、
  // エラーはログに残すのみとする(写真の自動削除は補助的な仕組みのため)。
  try {
    await markPhotosForRetentionCountdown(data.photo_paths, now.toMillis());
  } catch (e) {
    console.error(`写真のcustomTime設定に失敗しました(item=${id}):`, e);
  }

  const updated = await getItem(id);
  if (!updated) throw new Error(`更新後に商品が見つかりません: ${id}`);
  return updated;
}

/** draft -> pending。①画面での保存時。 */
export async function markPending(id: string): Promise<Item> {
  const db = adminFirestore();
  const ref = db.collection(COLLECTION).doc(id);
  await ref.update({ status: "pending" satisfies ItemStatus, updated_at: Timestamp.now() });
  const updated = await getItem(id);
  if (!updated) throw new Error(`更新後に商品が見つかりません: ${id}`);
  return updated;
}

/**
 * draft/pending -> cancelled(「出品待ちから外す」)。
 * Google Sheets・item-register-apiには一切アクセスしない(呼び出し元ルートも同様)。
 * Firestoreドキュメントは削除せず、終端ステータスとして履歴に残す。
 * 写真は削除せず、markListedと同じ仕組みでcustomTimeを設定し、
 * 既存の30日後自動削除ライフサイクルルールに乗せる。
 */
export async function markCancelled(id: string): Promise<Item> {
  const db = adminFirestore();
  const ref = db.collection(COLLECTION).doc(id);
  const now = Timestamp.now();
  const snap = await ref.get();
  if (!snap.exists) throw new Error(`商品が見つかりません: ${id}`);
  const data = snap.data() as FirestoreItemDoc;

  await ref.update({
    status: "cancelled" satisfies ItemStatus,
    cancelled_at: now,
    updated_at: now,
  });

  // 写真削除カウントダウンの起点(customTime)を設定する。失敗してもステータス変更自体は成功させ、
  // エラーはログに残すのみとする(markListedと同じフェイルセーフ方針)。
  try {
    await markPhotosForRetentionCountdown(data.photo_paths, now.toMillis());
  } catch (e) {
    console.error(`写真のcustomTime設定に失敗しました(item=${id}):`, e);
  }

  const updated = await getItem(id);
  if (!updated) throw new Error(`更新後に商品が見つかりません: ${id}`);
  return updated;
}
