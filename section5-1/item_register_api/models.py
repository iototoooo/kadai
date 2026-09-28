"""GPT Actionから受け取るリクエスト/レスポンスのスキーマとバリデーション。"""

from typing import Optional

from pydantic import BaseModel, Field, field_validator

GENRE_CHOICES = ["トップス", "ボトムス", "アウター", "ワンピース", "小物", "その他"]
STYLE_CHOICES = ["古着", "ストリート", "きれいめ", "スポーツ", "Y2K", "その他"]
CONDITION_CHOICES = ["新品", "未使用", "目立った傷なし", "やや傷あり"]
SEASON_CHOICES = ["春夏", "秋冬", "オールシーズン"]


def _choice_validator(field_name: str, choices: list):
    def _validate(cls, v: str) -> str:
        if v not in choices:
            raise ValueError(f"{field_name}は次のいずれかを指定してください: {', '.join(choices)} (受信値: {v!r})")
        return v

    return _validate


class ItemRegisterRequest(BaseModel):
    title: str = Field(..., min_length=1)
    genre: str
    style: str
    brand: Optional[str] = None
    sale_price: int = Field(..., ge=0)
    condition: str
    season: str
    storage_location: str = Field(..., min_length=1)
    mercari_account: Optional[str] = None
    description: str = Field(..., min_length=1)
    request_id: str = Field(..., min_length=1)

    _validate_genre = field_validator("genre")(_choice_validator("genre", GENRE_CHOICES))
    _validate_style = field_validator("style")(_choice_validator("style", STYLE_CHOICES))
    _validate_condition = field_validator("condition")(_choice_validator("condition", CONDITION_CHOICES))
    _validate_season = field_validator("season")(_choice_validator("season", SEASON_CHOICES))

    @field_validator("title", "storage_location", "description", "request_id")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("空文字は許可されていません")
        return v

    @field_validator("storage_location")
    @classmethod
    def _storage_location_as_is(cls, v: str) -> str:
        # storage_locationはユーザーの入力をそのまま保存する(ラベル付与や変換をしない)。
        return v

    @field_validator("brand", "mercari_account")
    @classmethod
    def _empty_string_as_none(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if v.strip() == "":
            return None
        return v


class RegisterItemResponse(BaseModel):
    success: bool
    already_registered: bool
    management_number: str
    storage_location: str
    description: str


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
