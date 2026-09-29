// static/new.js の重複警告UI(通常の「登録する」ボタンの表示/非表示制御)を検証する。
// 実際のブラウザ・npm依存を使わず、Node.js組み込みの node:test / node:vm のみで
// static/new.js を直接読み込んで実行する(再実装ではなく本物のスクリプトを検証する)。
//
// 実行方法: expense_manager ディレクトリで `node --test tests_js/new_ui.test.mjs`

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT_PATH = path.join(__dirname, "..", "static", "new.js");
const SOURCE = fs.readFileSync(SCRIPT_PATH, "utf-8");

class MiniElement {
  constructor(id, elements) {
    this.id = id;
    this._elements = elements;
    this.style = {};
    this.textContent = "";
    this.disabled = false;
    this.value = "";
    this.href = "";
    this.type = "";
    this.files = [];
    this._innerHTML = "";
    this._listeners = {};
  }

  addEventListener(type, fn) {
    (this._listeners[type] = this._listeners[type] || []).push(fn);
  }

  // クリックイベントをシミュレートする。リスナーの戻り値(Promiseの場合を含む)を返す。
  click() {
    let result;
    for (const fn of this._listeners["click"] || []) result = fn();
    return result;
  }

  appendChild(_child) {
    // select要素へのoption追加等。中身の検証はしないため何もしない。
  }

  set innerHTML(html) {
    this._innerHTML = html;
    // 簡易パーサ: innerHTMLで注入されたid="..."要素(重複警告内の動的ボタン等)を
    // 後からdocument.getElementByIdで取得できるよう、id出現時点で自動登録する。
    const re = /id="([^"]+)"/g;
    let m;
    while ((m = re.exec(html))) {
      const id = m[1];
      if (!this._elements[id]) this._elements[id] = new MiniElement(id, this._elements);
    }
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

function loadScript({ document, fetchImpl }) {
  const sandbox = {
    document,
    fetch: fetchImpl,
    URL: { createObjectURL: () => "blob://fake" },
    FormData: class {
      append() {}
    },
    console,
  };
  vm.createContext(sandbox);
  vm.runInContext(SOURCE, sandbox);
  return sandbox;
}

// vmコンテキスト(new.js実行realm)自身のTypeErrorコンストラクタを取得する。
// sandbox.TypeError のようにオブジェクトの直接プロパティとしては生えないため
// (createContext直後は未設定)、runInContextで式評価して取得する必要がある。
// これで作った例外は、new.js内の `e instanceof TypeError` が正しくtrueと
// 判定する、vm内realmのTypeErrorインスタンスになる。
function getVmTypeError(sandbox) {
  return vm.runInContext("TypeError", sandbox);
}

function fakeChoicesResponse() {
  return { ok: true, json: async () => ({ account_categories: [], business_segments: [] }) };
}

// new.js側のボタンクリックリスナーはPromiseを返さない(fire-and-forgotパターン)箇所があるため、
// クリック後の非同期処理(fetch→JSON解析→DOM更新)が完了するまで短時間ポーリングして待つ。
async function waitUntil(conditionFn, { timeoutMs = 500, intervalMs = 5 } = {}) {
  const start = Date.now();
  while (!conditionFn()) {
    if (Date.now() - start > timeoutMs) {
      throw new Error("waitUntil: タイムアウトしました");
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

// fileInputの"change"イベントを模し、選択ファイルをセットする。
function selectFile(elements, file) {
  elements.fileInput.files = [file];
  for (const fn of elements.fileInput._listeners["change"] || []) fn();
}

test("possible_duplicate警告表示中、通常の登録するボタンが非表示になる", async () => {
  const { document, elements } = buildDom();
  const fetchImpl = async (url) => {
    if (url === "/api/choices") return fakeChoicesResponse();
    if (url === "/api/register") {
      return {
        status: 409,
        ok: false,
        json: async () => ({
          reason: "possible_duplicate",
          message: "同じ経費の可能性がある登録が見つかりました",
          duplicate_candidates: [
            { management_number: "EX2609001", transaction_date: "2026-09-27", payee: "はま寿司", amount: 2519, account_category: "接待交際費", business_segment: "FP・紹介" },
          ],
        }),
      };
    }
    throw new Error("unexpected fetch: " + url);
  };
  loadScript({ document, fetchImpl });

  assert.equal(elements.registerBtn.style.display, undefined); // 初期状態では非表示指定なし
  await elements.registerBtn.click();

  assert.equal(elements.registerBtn.style.display, "none", "警告表示中は登録するボタンを隠す");
  assert.equal(elements.duplicateWarning.style.display, "block");
  assert.ok(elements.forcePossible, "「重複ではないので登録する」ボタンが存在する");
  assert.ok(elements.cancelPossible, "「登録をやめる」ボタンが存在する");
});

test("duplicate_hash警告表示中も、通常の登録するボタンが非表示になる", async () => {
  const { document, elements } = buildDom();
  const fetchImpl = async (url) => {
    if (url === "/api/choices") return fakeChoicesResponse();
    if (url === "/api/register") {
      return {
        status: 409,
        ok: false,
        json: async () => ({ reason: "duplicate_hash", message: "同一画像が既に登録されています" }),
      };
    }
    throw new Error("unexpected fetch: " + url);
  };
  loadScript({ document, fetchImpl });

  await elements.registerBtn.click();

  assert.equal(elements.registerBtn.style.display, "none");
  assert.ok(elements.forceHash, "「同一画像でも登録する」ボタンが存在する");
  assert.ok(elements.cancelHash, "「登録をやめる」ボタンが存在する");
});

test("「登録をやめる」を押すと、通常の登録するボタンが再表示される", async () => {
  const { document, elements } = buildDom();
  const fetchImpl = async (url) => {
    if (url === "/api/choices") return fakeChoicesResponse();
    if (url === "/api/register") {
      return {
        status: 409,
        ok: false,
        json: async () => ({
          reason: "possible_duplicate",
          message: "同じ経費の可能性がある登録が見つかりました",
          duplicate_candidates: [],
        }),
      };
    }
    throw new Error("unexpected fetch: " + url);
  };
  loadScript({ document, fetchImpl });

  await elements.registerBtn.click();
  assert.equal(elements.registerBtn.style.display, "none");

  elements.cancelPossible.click();

  assert.equal(elements.registerBtn.style.display, "", "登録をやめる後は登録するボタンが再表示される");
  assert.equal(elements.duplicateWarning.style.display, "none");
});

test("重複ではないので登録するを押すと、override付きで再送信され成功時に完了画面へ進む", async () => {
  const { document, elements } = buildDom();
  let registerCallCount = 0;
  const fetchImpl = async (url) => {
    if (url === "/api/choices") return fakeChoicesResponse();
    if (url === "/api/register") {
      registerCallCount += 1;
      if (registerCallCount === 1) {
        return {
          status: 409,
          ok: false,
          json: async () => ({
            reason: "possible_duplicate",
            message: "同じ経費の可能性がある登録が見つかりました",
            duplicate_candidates: [],
          }),
        };
      }
      // 2回目(override後)は成功として扱う。
      return {
        status: 200,
        ok: true,
        json: async () => ({ management_number: "EX2609002", drive_file_url: "https://example.invalid/x" }),
      };
    }
    throw new Error("unexpected fetch: " + url);
  };
  loadScript({ document, fetchImpl });

  await elements.registerBtn.click();
  assert.equal(elements.registerBtn.style.display, "none");

  // forcePossibleのクリックリスナーはsubmitRegister()の完了を待たない実装のため、
  // DOM状態が更新されるまでポーリングして待つ。
  elements.forcePossible.click();
  await waitUntil(() => elements["step-complete"].style.display === "block");

  assert.equal(registerCallCount, 2, "override後に登録APIが再送信される");
  assert.equal(elements["step-confirm"].style.display, "none");
  assert.equal(elements["step-complete"].style.display, "block");
});

test("重複候補は1件ずつカード形式(duplicate-candidate)で表示され、ボタンはbtn-groupで囲まれる", async () => {
  const { document, elements } = buildDom();
  const fetchImpl = async (url) => {
    if (url === "/api/choices") return fakeChoicesResponse();
    if (url === "/api/register") {
      return {
        status: 409,
        ok: false,
        json: async () => ({
          reason: "possible_duplicate",
          message: "同じ経費の可能性がある登録が見つかりました",
          duplicate_candidates: [
            {
              management_number: "EX2609001",
              transaction_date: "2026-09-27",
              payee: "株式会社はま寿司 板橋徳丸店",
              amount: 2519,
              account_category: "接待交際費",
              business_segment: "FP・紹介",
            },
          ],
        }),
      };
    }
    throw new Error("unexpected fetch: " + url);
  };
  loadScript({ document, fetchImpl });

  await elements.registerBtn.click();

  const html = elements.duplicateWarning.innerHTML;
  assert.ok(html.includes('class="duplicate-candidate"'), "候補ごとにduplicate-candidateカードで表示される");
  assert.ok(html.includes("EX2609001"));
  assert.ok(html.includes('class="btn-group"'), "選択肢ボタンがbtn-groupでまとめられている(スマホでの折り返し対応)");
});

test("次の経費を登録すると、警告状態が残らずリセットされる", async () => {
  const { document, elements } = buildDom();
  const fetchImpl = async (url) => {
    if (url === "/api/choices") return fakeChoicesResponse();
    if (url === "/api/register") {
      return {
        status: 409,
        ok: false,
        json: async () => ({
          reason: "possible_duplicate",
          message: "同じ経費の可能性がある登録が見つかりました",
          duplicate_candidates: [],
        }),
      };
    }
    throw new Error("unexpected fetch: " + url);
  };
  loadScript({ document, fetchImpl });

  // 警告を表示させた状態を作る(前回サイクルの残留を再現)。
  await elements.registerBtn.click();
  assert.equal(elements.registerBtn.style.display, "none");

  elements.nextBtn.click();

  assert.equal(elements.registerBtn.style.display, "", "次の登録開始時に登録するボタンが再表示される");
  assert.equal(elements.duplicateWarning.style.display, "none", "次の登録開始時に警告表示がリセットされる");
});

// --- 通信エラー時の自動再試行・安全なメッセージ表示 ---
//
// fetch()自体が失敗した場合、ブラウザは(実装依存の)TypeErrorを投げる
// (Safari: "Load failed", Chrome: "Failed to fetch"等)。
// このテストファイルのfetchImplはNode.jsの外側realmで定義されるため、そこで
// `throw new TypeError(...)` してもnew.js側(vmの内側realm)から見ると別realmの
// TypeErrorとなり`instanceof`が偽になってしまう。そのため、loadScript実行後の
// サンドボックス自身のTypeErrorコンストラクタ(sandbox.TypeError)を使って
// エラーを生成する。

test("analyze通信失敗(TypeError)→自動的に1回だけ再試行→成功", async () => {
  const { document, elements } = buildDom();
  let vmTypeError;
  let analyzeCallCount = 0;
  const fetchImpl = async (url) => {
    if (url === "/api/choices") return fakeChoicesResponse();
    if (url === "/api/analyze") {
      analyzeCallCount += 1;
      if (analyzeCallCount === 1) throw new vmTypeError("Load failed");
      return {
        ok: true,
        json: async () => ({
          request_id: "expense-retry-ok",
          fields: { transaction_date: "2026-09-20", payee: "テスト商店", amount: 1000 },
        }),
      };
    }
    throw new Error("unexpected fetch: " + url);
  };
  const sandbox = loadScript({ document, fetchImpl });
  vmTypeError = getVmTypeError(sandbox);

  selectFile(elements, { name: "receipt.jpg", type: "image/jpeg" });
  await elements.analyzeBtn.click();

  assert.equal(analyzeCallCount, 2, "TypeError失敗後、自動的にもう1回fetchされる(合計2回)");
  assert.equal(elements.analyzeError.textContent, "", "再試行で成功した場合はエラー表示なし");
  assert.equal(elements["step-confirm"].style.display, "block");
});

test("analyze通信失敗(TypeError)→再試行も失敗→安全な日本語メッセージを表示し、Load failed等の生メッセージは出さない", async () => {
  const { document, elements } = buildDom();
  let vmTypeError;
  let analyzeCallCount = 0;
  const fetchImpl = async (url) => {
    if (url === "/api/choices") return fakeChoicesResponse();
    if (url === "/api/analyze") {
      analyzeCallCount += 1;
      throw new vmTypeError("Load failed");
    }
    throw new Error("unexpected fetch: " + url);
  };
  const sandbox = loadScript({ document, fetchImpl });
  vmTypeError = getVmTypeError(sandbox);

  selectFile(elements, { name: "receipt.jpg", type: "image/jpeg" });
  await elements.analyzeBtn.click();

  assert.equal(analyzeCallCount, 2, "自動再試行は1回だけ行われ、2回目も失敗した時点で打ち切る");
  assert.equal(
    elements.analyzeError.textContent,
    "通信が不安定なため、処理結果を受信できませんでした。電波状況の良い場所でもう一度お試しください。"
  );
  assert.ok(!elements.analyzeError.textContent.includes("Load failed"));
  assert.ok(!elements.analyzeError.textContent.includes("Failed to fetch"));
});

test("register通信失敗(TypeError)→自動的に1回だけ再試行→成功", async () => {
  const { document, elements } = buildDom();
  let vmTypeError;
  let registerCallCount = 0;
  const fetchImpl = async (url) => {
    if (url === "/api/choices") return fakeChoicesResponse();
    if (url === "/api/analyze") {
      return {
        ok: true,
        json: async () => ({ request_id: "expense-abc", fields: { payee: "テスト商店" } }),
      };
    }
    if (url === "/api/register") {
      registerCallCount += 1;
      if (registerCallCount === 1) throw new vmTypeError("Load failed");
      return {
        status: 200,
        ok: true,
        json: async () => ({ management_number: "EX2609099", drive_file_url: "https://example.invalid/y" }),
      };
    }
    throw new Error("unexpected fetch: " + url);
  };
  const sandbox = loadScript({ document, fetchImpl });
  vmTypeError = getVmTypeError(sandbox);

  selectFile(elements, { name: "receipt.jpg", type: "image/jpeg" });
  await elements.analyzeBtn.click();
  assert.equal(elements["step-confirm"].style.display, "block");

  await elements.registerBtn.click();

  assert.equal(registerCallCount, 2, "TypeError失敗後、自動的にもう1回fetchされる(合計2回)");
  assert.equal(elements.registerError.textContent, "");
  assert.equal(elements["step-complete"].style.display, "block");
});

test("HTTP 409(重複警告)のJSON応答が正常に返った場合は自動再試行しない", async () => {
  const { document, elements } = buildDom();
  let registerCallCount = 0;
  const fetchImpl = async (url) => {
    if (url === "/api/choices") return fakeChoicesResponse();
    if (url === "/api/register") {
      registerCallCount += 1;
      return {
        status: 409,
        ok: false,
        json: async () => ({ reason: "duplicate_hash", message: "同一画像が既に登録されています" }),
      };
    }
    throw new Error("unexpected fetch: " + url);
  };
  loadScript({ document, fetchImpl });

  await elements.registerBtn.click();

  assert.equal(
    registerCallCount,
    1,
    "409はfetch()自体が例外を投げず正常に解決するため、自動再試行は行われない"
  );
});

test("HTTP 503(Gemini混雑)のJSON応答が正常に返った場合は自動再試行せず、サーバーの安全なメッセージをそのまま表示する", async () => {
  const { document, elements } = buildDom();
  let analyzeCallCount = 0;
  const fetchImpl = async (url) => {
    if (url === "/api/choices") return fakeChoicesResponse();
    if (url === "/api/analyze") {
      analyzeCallCount += 1;
      return {
        status: 503,
        ok: false,
        json: async () => ({ error: "AI解析が混み合っています。しばらくしてからもう一度お試しください。" }),
      };
    }
    throw new Error("unexpected fetch: " + url);
  };
  loadScript({ document, fetchImpl });

  selectFile(elements, { name: "receipt.jpg", type: "image/jpeg" });
  await elements.analyzeBtn.click();

  assert.equal(
    analyzeCallCount,
    1,
    "503はfetch()自体が例外を投げず正常に解決するため、自動再試行は行われない"
  );
  assert.equal(
    elements.analyzeError.textContent,
    "AI解析が混み合っています。しばらくしてからもう一度お試しください。"
  );
});
