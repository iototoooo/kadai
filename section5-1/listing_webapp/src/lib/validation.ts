/**
 * GPT出力JSONの解析・検証、および「Google Sheetsへ登録」ボタンの許可/禁止ロジック。
 *
 * 文字数超過(title/description)は①保存画面では警告のみで保存を妨げないが、
 * ③画面からのSheets登録はブロックする。#AddOneVintage欠落は警告のうえ、
 * 利用者が明示的に確認した場合のみ例外的に登録を許可する(overrideTagWarning)。
 */

import { z } from "zod";
import {
  ADD_ONE_VINTAGE_TAG,
  CONDITION_CHOICES,
  DESCRIPTION_MAX_LENGTH,
  GENRE_CHOICES,
  GptItemJson,
  SEASON_CHOICES,
  STYLE_CHOICES,
  TITLE_MAX_LENGTH,
} from "./types";

const gptItemJsonSchema = z.object({
  title: z.string().min(1, "商品名が空です"),
  genre: z.enum(GENRE_CHOICES, {
    errorMap: () => ({ message: `ジャンルは次のいずれかを指定してください: ${GENRE_CHOICES.join(", ")}` }),
  }),
  style: z.enum(STYLE_CHOICES, {
    errorMap: () => ({ message: `系統は次のいずれかを指定してください: ${STYLE_CHOICES.join(", ")}` }),
  }),
  brand: z.string().nullable().optional(),
  sale_price: z.number({ invalid_type_error: "出品価格は数値で指定してください" }).int().nonnegative(),
  condition: z.enum(CONDITION_CHOICES, {
    errorMap: () => ({ message: `商品の状態は次のいずれかを指定してください: ${CONDITION_CHOICES.join(", ")}` }),
  }),
  season: z.enum(SEASON_CHOICES, {
    errorMap: () => ({ message: `季節は次のいずれかを指定してください: ${SEASON_CHOICES.join(", ")}` }),
  }),
  storage_location: z.string().min(1, "保管場所が空です"),
  description: z.string().min(1, "商品説明が空です"),
});

export interface ParseGptJsonResult {
  ok: boolean;
  data: GptItemJson | null;
  errors: string[];
}

/** ①画面に貼り付けられたテキストをGPT出力JSONとしてパース・検証する。 */
export function parseGptJson(rawText: string): ParseGptJsonResult {
  let parsedUnknown: unknown;
  try {
    parsedUnknown = JSON.parse(rawText);
  } catch (e) {
    return { ok: false, data: null, errors: [`JSONとして読み取れませんでした: ${(e as Error).message}`] };
  }

  const result = gptItemJsonSchema.safeParse(parsedUnknown);
  if (!result.success) {
    const errors = result.error.errors.map((issue) => `${issue.path.join(".") || "(root)"}: ${issue.message}`);
    return { ok: false, data: null, errors };
  }

  return { ok: true, data: result.data as GptItemJson, errors: [] };
}

export function isTitleTooLong(title: string): boolean {
  return title.length > TITLE_MAX_LENGTH;
}

export function isDescriptionTooLong(description: string): boolean {
  return description.length > DESCRIPTION_MAX_LENGTH;
}

export function hasAddOneVintageTag(description: string): boolean {
  return description.includes(ADD_ONE_VINTAGE_TAG);
}

export interface RegistrationEligibility {
  /** trueならSheets登録ボタンを押せる。 */
  canRegister: boolean;
  /** 例外操作なしでは解消できないブロック理由(文字数超過)。1件でもあれば登録不可。 */
  hardBlockReasons: string[];
  /** 利用者が「警告を確認して登録する」を選べば解除できる理由。 */
  overridableReasons: string[];
}

/**
 * Sheets登録ボタンの活性/非活性を判定する。
 * @param overrideTagWarning 利用者が#AddOneVintage欠落の警告を確認して続行を選んだ場合true。
 */
export function evaluateRegistrationEligibility(
  item: { title: string; description: string },
  overrideTagWarning: boolean
): RegistrationEligibility {
  const hardBlockReasons: string[] = [];
  const overridableReasons: string[] = [];

  if (isTitleTooLong(item.title)) {
    hardBlockReasons.push(`商品名が${TITLE_MAX_LENGTH}文字を超えています(現在${item.title.length}文字)`);
  }
  if (isDescriptionTooLong(item.description)) {
    hardBlockReasons.push(`商品説明が${DESCRIPTION_MAX_LENGTH}文字を超えています(現在${item.description.length}文字)`);
  }
  if (!hasAddOneVintageTag(item.description)) {
    overridableReasons.push(`商品説明に${ADD_ONE_VINTAGE_TAG}が含まれていません`);
  }

  const blockedByTag = overridableReasons.length > 0 && !overrideTagWarning;
  const canRegister = hardBlockReasons.length === 0 && !blockedByTag;

  return { canRegister, hardBlockReasons, overridableReasons };
}
