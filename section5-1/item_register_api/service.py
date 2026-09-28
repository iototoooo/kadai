"""登録処理の本体ロジック(採番・行挿入・検証・request_id管理をまとめる)。"""

import threading
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from . import request_log, sheets_client
from .config import TIMEZONE_NAME
from .logging_utils import log_registration_event
from .models import ItemRegisterRequest, RegisterItemResponse

JST = ZoneInfo(TIMEZONE_NAME)

# 各列で維持されているべき入力規則の種類。行挿入後にこれが消えていないかを検証する。
EXPECTED_VALIDATIONS = {
    sheets_client.COL_GENRE: "ONE_OF_LIST",
    sheets_client.COL_STYLE: "ONE_OF_LIST",
    sheets_client.COL_CONDITION: "ONE_OF_LIST",
    sheets_client.COL_SEASON: "ONE_OF_LIST",
    sheets_client.COL_SALES_CHANNEL: "ONE_OF_LIST",
    sheets_client.COL_MERCARI_ACCOUNT: "ONE_OF_LIST",
}

# 数式が引き継がれているべき列。
FORMULA_COLUMNS = list(sheets_client.FORMULA_TEMPLATES.keys())


class RegistrationError(Exception):
    """バリデーション以外の理由で登録に失敗したことを表す。"""


def build_final_description(description: str, management_number: str, storage_location: str) -> str:
    base = description.rstrip("\n")
    return f"{base}\n\n（S/N：{management_number}）\n{storage_location}"


class RegisterItemService:
    def __init__(self, client: Optional[sheets_client.SheetsClient] = None):
        self._client = client or sheets_client.SheetsClient()
        self._lock = threading.Lock()

    def register(self, req: ItemRegisterRequest) -> RegisterItemResponse:
        item_sheet = self._client.item_sheet
        log_sheet = self._client.get_request_log_sheet()

        existing = request_log.find_entry(log_sheet, req.request_id)
        if existing is not None:
            return RegisterItemResponse(
                success=True,
                already_registered=True,
                management_number=existing.management_number,
                storage_location=existing.storage_location,
                description=existing.description,
            )

        # 採番から書き込み・ログ記録までを1つのロックで直列化する。
        # (Cloud Runへのデプロイ時は --concurrency=1 --max-instances=1 を推奨。
        #  詳細はREADME/デプロイ手順を参照。複数インスタンスを許容する場合は
        #  Firestore等を使った分散ロックへの置き換えが必要。)
        with self._lock:
            # ロック取得までの間に別リクエストが同じrequest_idを処理済みかもしれないため再確認する。
            existing = request_log.find_entry(log_sheet, req.request_id)
            if existing is not None:
                return RegisterItemResponse(
                    success=True,
                    already_registered=True,
                    management_number=existing.management_number,
                    storage_location=existing.storage_location,
                    description=existing.description,
                )

            now = datetime.now(JST)
            yymm = now.strftime("%y%m")

            max_seq = sheets_client.get_max_management_number(item_sheet, yymm)
            management_number = sheets_client.build_management_number(yymm, max_seq + 1)

            # 書き込み直前に、算出した番号がまだ使われていないことを再確認する。
            recheck_max = sheets_client.get_max_management_number(item_sheet, yymm)
            if recheck_max >= max_seq + 1:
                management_number = sheets_client.build_management_number(yymm, recheck_max + 1)

            listed_date = now.strftime("%Y/%m/%d")
            row = sheets_client.build_item_row(
                row_number=2,
                management_number=management_number,
                title=req.title,
                genre=req.genre,
                style=req.style,
                brand=req.brand,
                sale_price=req.sale_price,
                condition=req.condition,
                season=req.season,
                listed_date=listed_date,
                storage_location=req.storage_location,
                mercari_account=req.mercari_account,
            )

            try:
                sheets_client.insert_item_row(item_sheet, row)
            except Exception as e:
                log_registration_event(
                    request_id=req.request_id,
                    management_number=management_number,
                    processed_at_jst=now.isoformat(),
                    success=False,
                    error=f"シートへの行挿入に失敗: {e}",
                )
                raise RegistrationError(f"スプレッドシートへの書き込みに失敗しました: {e}") from e

            final_description = build_final_description(req.description, management_number, req.storage_location)

            error = self._verify_row(item_sheet, management_number=management_number, req=req)
            if error:
                log_registration_event(
                    request_id=req.request_id,
                    management_number=management_number,
                    processed_at_jst=now.isoformat(),
                    success=False,
                    error=error,
                )
                # 既に行は書き込まれているため、request_idは「成功」としてログに残さない。
                # (呼び出し側が同じrequest_idで再送してきた場合、改めて採番・検証をやり直す)
                raise RegistrationError(f"書き込み後の検証に失敗しました: {error}")

            entry = request_log.RequestLogEntry(
                request_id=req.request_id,
                management_number=management_number,
                storage_location=req.storage_location,
                description=final_description,
                created_at_jst=now.isoformat(),
                status=request_log.STATUS_SUCCESS,
            )
            request_log.append_entry(log_sheet, entry)

            log_registration_event(
                request_id=req.request_id,
                management_number=management_number,
                processed_at_jst=now.isoformat(),
                success=True,
            )

            return RegisterItemResponse(
                success=True,
                already_registered=False,
                management_number=management_number,
                storage_location=req.storage_location,
                description=final_description,
            )

    def _verify_row(self, item_sheet, *, management_number: str, req: ItemRegisterRequest) -> str:
        """新規2行目を再取得して整合性を確認する。問題なければ空文字、問題があればエラー内容を返す。"""
        try:
            values = sheets_client.read_written_row_unformatted(item_sheet, 2)
            formulas = sheets_client.read_written_row_formulas(item_sheet, 2)
        except Exception as e:
            return f"検証のための再取得に失敗: {e}"

        def cell(values_list, col):
            idx = col - 1
            return values_list[idx] if idx < len(values_list) else ""

        checks = []
        if str(cell(values, sheets_client.COL_MANAGEMENT_NUMBER)) != management_number:
            checks.append("A列(管理番号)が一致しません")
        if str(cell(values, sheets_client.COL_TITLE)) != req.title:
            checks.append("B列(商品名)が一致しません")
        if str(cell(values, sheets_client.COL_GENRE)) != req.genre:
            checks.append("C列(ジャンル)が一致しません")
        try:
            if int(cell(values, sheets_client.COL_PRICE)) != req.sale_price:
                checks.append("F列(出品価格)が一致しません")
        except (TypeError, ValueError):
            checks.append("F列(出品価格)が数値として取得できません")
        if str(cell(values, sheets_client.COL_MEMO)) != req.storage_location:
            checks.append("AL列(メモ/保管場所)が一致しません")
        if not cell(values, sheets_client.COL_LISTED_DATE):
            checks.append("O列(出品日)が空です")
        if str(cell(values, sheets_client.COL_SALES_CHANNEL)) != "メルカリ":
            checks.append("R列(販売場所)がメルカリになっていません")

        for col in FORMULA_COLUMNS:
            if not str(cell(formulas, col)).startswith("="):
                checks.append(f"{col}列目の数式が見つかりません")

        try:
            validations = self._client.get_row_data_validations(item_sheet, 2)
            for col, expected_type in EXPECTED_VALIDATIONS.items():
                if validations.get(col) != expected_type:
                    checks.append(f"{col}列目の入力規則({expected_type})が維持されていません")
        except Exception as e:
            checks.append(f"入力規則の検証に失敗: {e}")

        return " / ".join(checks)
