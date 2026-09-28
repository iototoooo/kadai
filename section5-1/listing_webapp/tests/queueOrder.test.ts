import { test } from "node:test";
import assert from "node:assert/strict";
import { selectNextQueueItemId } from "../src/lib/queueOrder";
import type { Item, ItemStatus } from "../src/lib/types";

function fakeItem(id: string, status: ItemStatus, createdAt: number): Item {
  return {
    id,
    status,
    title: `商品${id}`,
    genre: "トップス",
    style: "古着",
    brand: null,
    sale_price: 1000,
    condition: "目立った傷なし",
    season: "オールシーズン",
    storage_location: "棚A",
    description: "説明",
    mercari_account: null,
    photo_paths: [],
    request_id: `webapp-${id}`,
    management_number: null,
    raw_gpt_text: "{}",
    created_at: createdAt,
    updated_at: createdAt,
    sheet_registered_at: null,
    listed_at: null,
    cancelled_at: null,
  };
}

test("selectNextQueueItemId: created_at昇順で次のアクティブな商品を返す", () => {
  const items = [
    fakeItem("a", "pending", 1),
    fakeItem("b", "sheet_registered", 2),
    fakeItem("c", "pending", 3),
  ];
  assert.equal(selectNextQueueItemId(items, "a"), "b");
  assert.equal(selectNextQueueItemId(items, "b"), "c");
});

test("selectNextQueueItemId: 最後の商品なら次はnull", () => {
  const items = [fakeItem("a", "pending", 1), fakeItem("b", "pending", 2)];
  assert.equal(selectNextQueueItemId(items, "b"), null);
});

test("selectNextQueueItemId: listed/draftはキューから除外される", () => {
  const items = [
    fakeItem("a", "pending", 1),
    fakeItem("b", "listed", 2),
    fakeItem("c", "draft", 3),
    fakeItem("d", "sheet_registered", 4),
  ];
  assert.equal(selectNextQueueItemId(items, "a"), "d");
});

test("selectNextQueueItemId: 現在の商品が直前にlistedへ変わり一覧から消えた場合、先頭のアクティブな商品を返す", () => {
  const items = [fakeItem("b", "pending", 2), fakeItem("c", "sheet_registered", 3)];
  // "a" は既にlistedになって渡されたitems(アクティブ一覧)には含まれていない。
  assert.equal(selectNextQueueItemId(items, "a"), "b");
});

test("selectNextQueueItemId: アクティブな商品が無ければnull", () => {
  const items = [fakeItem("a", "listed", 1), fakeItem("b", "draft", 2)];
  assert.equal(selectNextQueueItemId(items, "a"), null);
});
