/**
 * 「次の商品へ」ボタンのための、出品待ちキュー内での次アイテム選択ロジック。
 * Firestoreに依存しない純粋関数として切り出し、単体テストしやすくしている。
 */

import type { Item, ItemStatus } from "./types";

/** ③画面の「次の商品へ」で遷移対象とみなすステータス(まだ出品済みになっていないもの)。 */
export const ACTIVE_QUEUE_STATUSES: ItemStatus[] = ["pending", "sheet_registered"];

/**
 * created_at昇順に並んだアイテム一覧の中から、currentIdの次にある
 * ACTIVE_QUEUE_STATUSESの商品IDを返す。見つからなければnull(②一覧へ戻る)。
 *
 * currentId自身が(出品済みへ変更済み等で)一覧に含まれていない場合は、
 * 一覧内の先頭のアクティブな商品を返す。
 */
export function selectNextQueueItemId(itemsSortedByCreatedAtAsc: Item[], currentId: string): string | null {
  const active = itemsSortedByCreatedAtAsc.filter((item) => ACTIVE_QUEUE_STATUSES.includes(item.status));
  if (active.length === 0) return null;

  const currentIndex = active.findIndex((item) => item.id === currentId);
  if (currentIndex === -1) {
    // 現在の商品は既にアクティブ一覧から外れている(例: 直前にlistedへ変更した)。
    // 先頭のアクティブな商品へ進む。
    return active[0]!.id;
  }
  if (currentIndex === active.length - 1) {
    // 最後の商品だった場合、次はない。
    return null;
  }
  return active[currentIndex + 1]!.id;
}
