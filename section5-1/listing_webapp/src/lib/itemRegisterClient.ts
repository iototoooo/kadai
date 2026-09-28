/**
 * 既存の item-register-api (Cloud Run) の POST /register-item を呼び出す薄いクライアント。
 * サーバー側(API route)からのみ呼ぶこと。APIキーはここでのみ読み、ブラウザには渡さない。
 */

import type { Item } from "./types";

export interface RegisterItemApiResponse {
  success: boolean;
  already_registered: boolean;
  management_number: string;
  storage_location: string;
  description: string;
}

export interface RegisterItemApiError {
  success: false;
  error: string;
}

export class ItemRegisterApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly kind: "auth" | "validation" | "server" | "network"
  ) {
    super(message);
    this.name = "ItemRegisterApiError";
  }
}

function getConfig() {
  const baseUrl = process.env.ITEM_REGISTER_API_BASE_URL;
  const apiKey = process.env.ITEM_REGISTER_API_KEY;
  if (!baseUrl) throw new Error("ITEM_REGISTER_API_BASE_URL が設定されていません");
  if (!apiKey) throw new Error("ITEM_REGISTER_API_KEY が設定されていません");
  return { baseUrl, apiKey };
}

/** Firestoreの`Item`から item-register-api のリクエストボディを組み立てる。 */
export function buildRegisterItemPayload(item: Item) {
  return {
    title: item.title,
    genre: item.genre,
    style: item.style,
    brand: item.brand ?? undefined,
    sale_price: item.sale_price,
    condition: item.condition,
    season: item.season,
    storage_location: item.storage_location,
    mercari_account: item.mercari_account ?? undefined,
    description: item.description,
    request_id: item.request_id,
  };
}

export async function registerItemToSheet(item: Item): Promise<RegisterItemApiResponse> {
  const { baseUrl, apiKey } = getConfig();
  const payload = buildRegisterItemPayload(item);

  let res: Response;
  try {
    res = await fetch(`${baseUrl}/register-item`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "X-API-Key": apiKey,
      },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    throw new ItemRegisterApiError(`item-register-apiへの接続に失敗しました: ${(e as Error).message}`, 0, "network");
  }

  const body = (await res.json().catch(() => null)) as RegisterItemApiResponse | RegisterItemApiError | null;

  if (res.ok && body && "management_number" in body) {
    return body;
  }

  const errorMessage = body && "error" in body ? body.error : `不明なエラー(HTTP ${res.status})`;
  const kind = res.status === 401 ? "auth" : res.status === 400 ? "validation" : "server";
  throw new ItemRegisterApiError(errorMessage, res.status, kind);
}
