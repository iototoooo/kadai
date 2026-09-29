// static/list.js が、スマホ幅で「証憑」リンクが縦に折り返されないようにするための
// 構造(expense-row-main / expense-row-link クラス)を正しく出力していることを検証する。
//
// 実行方法: expense_manager ディレクトリで `node --test tests_js/list_ui.test.mjs`

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT_PATH = path.join(__dirname, "..", "static", "list.js");
const SOURCE = fs.readFileSync(SCRIPT_PATH, "utf-8");

class MiniElement {
  constructor(id, elements) {
    this.id = id;
    this._elements = elements;
    this.style = {};
    this.textContent = "";
    this.value = "";
    this._innerHTML = "";
    this._listeners = {};
  }

  addEventListener(type, fn) {
    (this._listeners[type] = this._listeners[type] || []).push(fn);
  }

  appendChild(child) {
    // list.jsはcreateElementしたdivにinnerHTMLを設定してからappendChildするため、
    // 親のinnerHTMLへ子のinnerHTMLを連結して蓄積する(実DOMの表示結果を簡易的に再現)。
    this._innerHTML += child.innerHTML;
  }

  set innerHTML(html) {
    this._innerHTML = html;
  }

  get innerHTML() {
    return this._innerHTML;
  }
}

function buildDom() {
  const elements = {};
  const document = {
    getElementById(id) {
      if (!elements[id]) elements[id] = new MiniElement(id, elements);
      return elements[id];
    },
    createElement(_tag) {
      return new MiniElement(`created-${Math.random()}`, elements);
    },
  };
  return { elements, document };
}

async function waitUntil(conditionFn, { timeoutMs = 500, intervalMs = 5 } = {}) {
  const start = Date.now();
  while (!conditionFn()) {
    if (Date.now() - start > timeoutMs) throw new Error("waitUntil: タイムアウトしました");
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

test("経費一覧の各行が、証憑リンクの折り返し防止クラスと長い支払先名対応クラスを持つ", async () => {
  const { document, elements } = buildDom();

  const fetchImpl = async (url) => {
    if (url.startsWith("/api/choices")) {
      return { ok: true, json: async () => ({ account_categories: [], business_segments: [] }) };
    }
    if (url.startsWith("/api/expenses")) {
      return {
        ok: true,
        json: async () => ({
          items: [
            {
              management_number: "EX2609001",
              transaction_date: "2026-09-27",
              payee: "株式会社はま寿司 板橋徳丸店(非常に長い支払先名のテストケース)",
              amount: 2519,
              account_category: "接待交際費",
              business_segment: "FP・紹介",
              drive_file_url: "https://drive.example.invalid/x",
            },
          ],
        }),
      };
    }
    throw new Error("unexpected fetch: " + url);
  };

  const sandbox = { document, fetch: fetchImpl, console, URLSearchParams };
  vm.createContext(sandbox);
  vm.runInContext(SOURCE, sandbox);

  await waitUntil(() => elements.list && elements.list.innerHTML.includes("EX2609001"));

  const html = elements.list.innerHTML;
  assert.ok(html.includes('class="expense-row-main"'), "支払先等を含む側にexpense-row-mainクラスがある");
  assert.ok(html.includes('class="expense-row-link"'), "証憑リンク側にexpense-row-linkクラスがある(折り返し防止)");
  assert.ok(html.includes("証憑"), "証憑リンクのテキストが出力されている");
});
