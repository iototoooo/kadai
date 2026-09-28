import { test } from "node:test";
import assert from "node:assert/strict";
import { evaluateRegistrationEligibility, hasAddOneVintageTag, parseGptJson } from "../src/lib/validation";

const VALID_JSON = JSON.stringify({
  title: "テスト商品",
  genre: "トップス",
  style: "古着",
  brand: "TestBrand",
  sale_price: 1000,
  condition: "目立った傷なし",
  season: "オールシーズン",
  storage_location: "棚A",
  description: "説明文 #AddOneVintage",
});

test("parseGptJson: 正常なJSONをパースできる", () => {
  const result = parseGptJson(VALID_JSON);
  assert.equal(result.ok, true);
  assert.equal(result.data?.title, "テスト商品");
  assert.equal(result.data?.storage_location, "棚A");
});

test("parseGptJson: 壊れたJSONはエラーになる", () => {
  const result = parseGptJson("{title: broken");
  assert.equal(result.ok, false);
  assert.ok(result.errors.length > 0);
});

test("parseGptJson: 不正なenum値はエラーになる", () => {
  const bad = JSON.parse(VALID_JSON);
  bad.genre = "存在しないジャンル";
  const result = parseGptJson(JSON.stringify(bad));
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((e) => e.includes("genre")));
});

test("parseGptJson: 必須項目(storage_location)欠落はエラーになる", () => {
  const bad = JSON.parse(VALID_JSON);
  delete bad.storage_location;
  const result = parseGptJson(JSON.stringify(bad));
  assert.equal(result.ok, false);
});

test("hasAddOneVintageTag: タグの有無を判定できる", () => {
  assert.equal(hasAddOneVintageTag("説明文 #AddOneVintage"), true);
  assert.equal(hasAddOneVintageTag("タグなしの説明文"), false);
});

test("evaluateRegistrationEligibility: 全条件クリアなら登録可能", () => {
  const item = { title: "短い商品名", description: "説明 #AddOneVintage" };
  const result = evaluateRegistrationEligibility(item, false);
  assert.equal(result.canRegister, true);
  assert.equal(result.hardBlockReasons.length, 0);
  assert.equal(result.overridableReasons.length, 0);
});

test("evaluateRegistrationEligibility: 商品名40文字超過はハードブロック(overrideでも解除不可)", () => {
  const item = { title: "あ".repeat(41), description: "説明 #AddOneVintage" };
  const withoutOverride = evaluateRegistrationEligibility(item, false);
  const withOverride = evaluateRegistrationEligibility(item, true);
  assert.equal(withoutOverride.canRegister, false);
  assert.equal(withOverride.canRegister, false);
  assert.ok(withOverride.hardBlockReasons.length > 0);
});

test("evaluateRegistrationEligibility: 商品説明1000文字超過はハードブロック", () => {
  const item = { title: "商品名", description: "あ".repeat(1001) };
  const result = evaluateRegistrationEligibility(item, true);
  assert.equal(result.canRegister, false);
});

test("evaluateRegistrationEligibility: #AddOneVintage欠落はoverrideTagWarning=trueで解除できる", () => {
  const item = { title: "商品名", description: "タグなしの説明文" };
  const blocked = evaluateRegistrationEligibility(item, false);
  const overridden = evaluateRegistrationEligibility(item, true);
  assert.equal(blocked.canRegister, false);
  assert.equal(overridden.canRegister, true);
  assert.ok(overridden.overridableReasons.length > 0);
});
