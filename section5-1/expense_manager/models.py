"""リクエスト/レスポンスのスキーマ。"""

from typing import Optional

from pydantic import BaseModel, Field


class ExpenseFields(BaseModel):
    """AI抽出結果、および確認・修正画面での編集後データ。すべて未確定なら空欄(None)を許容する。"""

    transaction_date: Optional[str] = None  # "YYYY-MM-DD"
    payee: Optional[str] = None
    amount: Optional[int] = Field(default=None, ge=0)
    tax_amount: Optional[int] = Field(default=None, ge=0)  # 消費税額の合計(単一・混在税率どちらでも常に合計)
    tax_rate: Optional[str] = None  # 単一税率は"10%"等、混在時は"10%・8%"等の要約表示用
    # 8%・10%混在レシート対応。レシートに明記された内訳のみを保持し、計算・推測では埋めない。
    # 単一税率レシートでは該当する側のみ値が入り、もう一方はNoneのままになる。
    tax_rate_10_base: Optional[int] = Field(default=None, ge=0)  # 10%対象額(税抜)
    tax_rate_10_amount: Optional[int] = Field(default=None, ge=0)  # 10%消費税額
    tax_rate_8_base: Optional[int] = Field(default=None, ge=0)  # 8%対象額(税抜)
    tax_rate_8_amount: Optional[int] = Field(default=None, ge=0)  # 8%消費税額
    invoice_registration_number: Optional[str] = None
    description: Optional[str] = None
    payment_method: Optional[str] = None
    account_category: Optional[str] = None
    business_segment: Optional[str] = None
    memo: Optional[str] = None


class AnalyzeResponse(BaseModel):
    request_id: str
    fields: ExpenseFields
    notes: list[str] = []  # Geminiが読み取れなかった項目等の注記


class DuplicateCandidate(BaseModel):
    management_number: str
    transaction_date: str
    payee: str
    amount: int
    account_category: str
    business_segment: str


class RegisterResult(BaseModel):
    success: bool = True
    already_registered: bool = False
    management_number: str
    drive_file_url: str
    notes: list[str] = []


class RegisterBlockedResponse(BaseModel):
    success: bool = False
    reason: str  # "duplicate_hash" | "possible_duplicate" | "invalid_fields"
    message: str
    duplicate_candidates: list[DuplicateCandidate] = []


class ExpenseListItem(BaseModel):
    management_number: str
    transaction_date: str
    payee: str
    amount: Optional[int] = None
    account_category: str
    business_segment: str
    drive_file_url: str
