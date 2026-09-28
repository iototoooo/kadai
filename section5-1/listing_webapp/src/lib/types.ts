/**
 * 出品待ち管理Webアプリのドメイン型定義。
 *
 * item_register_api (Cloud Run) の models.py / config.py に合わせた選択肢を
 * ここでも同じ文字列でハードコードしている。シート側の入力規則を変更した場合は
 * こちらも合わせて更新すること。
 */

export const GENRE_CHOICES = ["トップス", "ボトムス", "アウター", "ワンピース", "小物", "その他"] as const;
export const STYLE_CHOICES = ["古着", "ストリート", "きれいめ", "スポーツ", "Y2K", "その他"] as const;
export const CONDITION_CHOICES = ["新品", "未使用", "目立った傷なし", "やや傷あり"] as const;
export const SEASON_CHOICES = ["春夏", "秋冬", "オールシーズン"] as const;

export type Genre = (typeof GENRE_CHOICES)[number];
export type Style = (typeof STYLE_CHOICES)[number];
export type Condition = (typeof CONDITION_CHOICES)[number];
export type Season = (typeof SEASON_CHOICES)[number];

/** 商品ステータス(5段階)。cancelledは「出品待ちから外す」操作(draft/pendingのみ)で遷移する終端状態。 */
export type ItemStatus = "draft" | "pending" | "sheet_registered" | "listed" | "cancelled";

export const TITLE_MAX_LENGTH = 40;
export const DESCRIPTION_MAX_LENGTH = 1000;
export const ADD_ONE_VINTAGE_TAG = "#AddOneVintage";

/** GPTがJSON形式で出力する商品データ(貼り付け入力の想定スキーマ)。 */
export interface GptItemJson {
  title: string;
  genre: string;
  style: string;
  brand?: string | null;
  sale_price: number;
  condition: string;
  season: string;
  storage_location: string;
  description: string;
}

/** Firestore `items` コレクションの1ドキュメント。 */
export interface Item {
  id: string;
  status: ItemStatus;
  title: string;
  genre: string;
  style: string;
  brand: string | null;
  sale_price: number;
  condition: string;
  season: string;
  storage_location: string;
  description: string;
  mercari_account: string | null;
  photo_paths: string[];
  request_id: string;
  management_number: string | null;
  raw_gpt_text: string;
  /** ミリ秒epoch。FirestoreのTimestampをAPI/クライアント境界ではnumberに変換して扱う。 */
  created_at: number;
  updated_at: number;
  sheet_registered_at: number | null;
  listed_at: number | null;
  cancelled_at: number | null;
}

/** ①画面での新規作成・保存に必要な最小フィールド。 */
export type NewItemInput = Omit<
  Item,
  | "id"
  | "status"
  | "request_id"
  | "management_number"
  | "created_at"
  | "updated_at"
  | "sheet_registered_at"
  | "listed_at"
  | "cancelled_at"
  | "photo_paths"
  | "mercari_account"
> & {
  mercari_account?: string | null;
};
