import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ItemRegisterApiError,
  buildRegisterItemPayload,
  registerItemToSheet,
} from "../src/lib/itemRegisterClient";
import type { Item } from "../src/lib/types";

function fakeItem(overrides: Partial<Item> = {}): Item {
  return {
    id: "item1",
    status: "pending",
    title: "商品名",
    genre: "トップス",
    style: "古着",
    brand: null,
    sale_price: 1000,
    condition: "目立った傷なし",
    season: "オールシーズン",
    storage_location: "棚A",
    description: "説明 #AddOneVintage",
    mercari_account: null,
    photo_paths: [],
    request_id: "webapp-item1",
    management_number: null,
    raw_gpt_text: "{}",
    created_at: 0,
    updated_at: 0,
    sheet_registered_at: null,
    listed_at: null,
    cancelled_at: null,
    ...overrides,
  };
}

test("buildRegisterItemPayload: item-register-apiが期待する形にマッピングされる", () => {
  const payload = buildRegisterItemPayload(fakeItem());
  assert.equal(payload.title, "商品名");
  assert.equal(payload.request_id, "webapp-item1");
  assert.equal(payload.brand, undefined); // null -> undefinedに変換される
});

function withEnv(vars: Record<string, string>, fn: () => Promise<void>) {
  const original: Record<string, string | undefined> = {};
  for (const key of Object.keys(vars)) {
    original[key] = process.env[key];
    process.env[key] = vars[key];
  }
  return fn().finally(() => {
    for (const key of Object.keys(vars)) {
      if (original[key] === undefined) delete process.env[key];
      else process.env[key] = original[key];
    }
  });
}

test("registerItemToSheet: 200成功時はレスポンスをそのまま返す", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(
      JSON.stringify({
        success: true,
        already_registered: false,
        management_number: "2609-001",
        storage_location: "棚A",
        description: "説明",
      }),
      { status: 200 }
    )) as typeof fetch;

  try {
    await withEnv(
      { ITEM_REGISTER_API_BASE_URL: "https://example.invalid", ITEM_REGISTER_API_KEY: "key" },
      async () => {
        const result = await registerItemToSheet(fakeItem());
        assert.equal(result.management_number, "2609-001");
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("registerItemToSheet: 401はkind=authのItemRegisterApiErrorになる", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ success: false, error: "APIキーが正しくありません" }), { status: 401 })) as typeof fetch;

  try {
    await withEnv(
      { ITEM_REGISTER_API_BASE_URL: "https://example.invalid", ITEM_REGISTER_API_KEY: "key" },
      async () => {
        await assert.rejects(
          () => registerItemToSheet(fakeItem()),
          (err: unknown) => err instanceof ItemRegisterApiError && err.kind === "auth"
        );
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("registerItemToSheet: 400はkind=validationのItemRegisterApiErrorになる", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ success: false, error: "genreが不正です" }), { status: 400 })) as typeof fetch;

  try {
    await withEnv(
      { ITEM_REGISTER_API_BASE_URL: "https://example.invalid", ITEM_REGISTER_API_KEY: "key" },
      async () => {
        await assert.rejects(
          () => registerItemToSheet(fakeItem()),
          (err: unknown) => err instanceof ItemRegisterApiError && err.kind === "validation"
        );
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("registerItemToSheet: 500はkind=serverのItemRegisterApiErrorになる", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ success: false, error: "サーバーエラー" }), { status: 500 })) as typeof fetch;

  try {
    await withEnv(
      { ITEM_REGISTER_API_BASE_URL: "https://example.invalid", ITEM_REGISTER_API_KEY: "key" },
      async () => {
        await assert.rejects(
          () => registerItemToSheet(fakeItem()),
          (err: unknown) => err instanceof ItemRegisterApiError && err.kind === "server"
        );
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

// --- 完成版description(末尾「（S/N：管理番号）\n保管場所」)の受け渡し ---
// markSheetRegistered(Firestore書き込み)に渡す直前の値がここで組み立てられるため、
// この関数の戻り値が正しい完成版descriptionを持つことを担保する。
// (markSheetRegistered自体はFirebase Admin SDK/Firestoreへの実書き込みを伴うため、
//  GCP接続なしの本テストスイートの対象外。実際の保存確認はデプロイ後の結合テストで行う。)

test("registerItemToSheet: 新規登録時、レスポンスのdescriptionが完成版フォーマット(末尾「（S/N：管理番号）\\n保管場所」)であること", async () => {
  const originalFetch = globalThis.fetch;
  const finalDescription = "説明 #AddOneVintage\n\n（S/N：2609-037）\nB";
  globalThis.fetch = (async () =>
    new Response(
      JSON.stringify({
        success: true,
        already_registered: false,
        management_number: "2609-037",
        storage_location: "B",
        description: finalDescription,
      }),
      { status: 200 }
    )) as typeof fetch;

  try {
    await withEnv(
      { ITEM_REGISTER_API_BASE_URL: "https://example.invalid", ITEM_REGISTER_API_KEY: "key" },
      async () => {
        const result = await registerItemToSheet(fakeItem({ storage_location: "B" }));
        assert.equal(result.description, finalDescription);
        assert.match(result.description, /\n\n（S\/N：2609-037）\nB$/);
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("registerItemToSheet: already_registered:true の場合も同じ完成版descriptionが返ること", async () => {
  const originalFetch = globalThis.fetch;
  const finalDescription = "説明 #AddOneVintage\n\n（S/N：2609-037）\nB";
  globalThis.fetch = (async () =>
    new Response(
      JSON.stringify({
        success: true,
        already_registered: true,
        management_number: "2609-037",
        storage_location: "B",
        description: finalDescription,
      }),
      { status: 200 }
    )) as typeof fetch;

  try {
    await withEnv(
      { ITEM_REGISTER_API_BASE_URL: "https://example.invalid", ITEM_REGISTER_API_KEY: "key" },
      async () => {
        const result = await registerItemToSheet(fakeItem({ storage_location: "B" }));
        assert.equal(result.already_registered, true);
        assert.equal(result.description, finalDescription);
        assert.match(result.description, /\n\n（S\/N：2609-037）\nB$/);
      }
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
