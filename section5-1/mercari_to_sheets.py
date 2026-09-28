"""
自分のメルカリアカウントの出品一覧(ログイン後の管理画面)を取得し、
Googleスプレッドシート「商品管理」タブに新規行として追記するツール。

- 初回のみブラウザが表示され、手動でメルカリにログインする必要がある
  (以降はセッション情報を保存し、自動で再ログインする)
- ログイン後の「出品した商品」ページ(/mypage/listings)を「もっと見る」で
  最後まで読み込み、出品中の全商品を毎回もれなく取得する
  (公開の検索結果ページと違い、1回の実行で全件を確実に取得できる)
- 一覧ページに商品名・価格が直接表示されているため、商品詳細ページは開かない
- 「公開停止中」の商品は追加しない
- 既にスプレッドシートに登録済みの商品(AT列のURLで判定)はスキップ
- 新規追加のみ行う(売却済み・値下げ等による既存行の更新は行わない)
- 出品日(O列)は、並び替えを「出品の新しい順」にしたときだけ表示される
  「〇時間/日前に出品」表記から逆算する(「更新順」時の「〇前に更新」は
  値下げ等で変わってしまうため使わない)。ラベルが見つからない場合のみ、
  ツールの実行日を代わりに使う。

事前準備:
    pip install -r requirements.txt
    playwright install chromium

    リポジトリ直下の .env に以下を設定しておくこと(任意、未設定ならデフォルト値を使う):
      GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE (未設定時は section4-3/service_account.json を使う)
      MERCARI_SHEETS_SPREADSHEET_ID (未設定時はデフォルトのスプレッドシートIDを使う)

    さらに service_account.json の client_email を、
    書き込み対象のスプレッドシートに「編集者」として共有しておくこと。

実行例:
    python mercari_to_sheets.py
    python mercari_to_sheets.py --dry-run --limit 3
"""

import argparse
import datetime
import os
import re

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SERVICE_ACCOUNT_FILE = os.path.join(SCRIPT_DIR, "..", "section4-3", "service_account.json")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE", DEFAULT_SERVICE_ACCOUNT_FILE)
STORAGE_STATE_FILE = os.path.join(SCRIPT_DIR, "mercari_storage_state.json")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SPREADSHEET_ID = os.getenv("MERCARI_SHEETS_SPREADSHEET_ID", "1xMq7gy4d9nPGRGLCX1bltXWxBKXDT1rr66za7zvpmGQ")
SHEET_NAME = "商品管理"

# 商品管理シートの列 (1始まり)。A=1, B=2, ... Z=26, AA=27, ... AT=46
COL_NAME = 2       # B: 商品名
COL_PRICE = 6      # F: 出品価格
COL_LISTED_DATE = 15  # O: 出品日
COL_URL = 46       # AT: メルカリ商品URL/画像
ROW_WIDTH = COL_URL  # 新規行として書き込む配列の長さ(A〜ATまで)

# 既存行(例: 12行目=2608-090)に入っていた数式をそのまま流用する。
# どの行も「行番号を差し替えるだけ」の単純なパターンだったため、挿入先の行番号を
# {r} に埋め込んで生成する。列番号は 1始まり。
FORMULA_TEMPLATES = {
    11: '=IF(I{r}="","",I{r}+IF(J{r}="",0,J{r}))',  # K: 仕入れ合計コスト
    21: '=IF(Q{r}="","",IFS(R{r}="ラクマ","",R{r}="ヤフマ",ROUND(Q{r}*0.05),R{r}="メルカリ",ROUND(Q{r}*0.1),TRUE,ROUND(Q{r}*0.1)))',  # U: 販売手数料
    22: '=IF(Q{r}="","",Q{r}-IF(K{r}="",0,K{r})-IF(U{r}="",0,U{r})-IF(S{r}="",0,S{r})-IF(T{r}="",0,T{r}))',  # V: 利益
    23: '=IF(OR(Q{r}="",Q{r}=0),"",IFERROR(ROUND(V{r}/Q{r}*100,1),""))',  # W: 利益率
    24: '=IF(OR(K{r}="",K{r}=0),"",IFERROR(ROUND(V{r}/K{r}*100,1),""))',  # X: 仕入れ利益率
    25: '=IF(OR(P{r}="",O{r}=""),"",P{r}-O{r})',  # Y: リードタイム
    26: '=IF(OR(O{r}="",P{r}<>""),"",TODAY()-O{r})',  # Z: 在庫日数
    27: '=IF(O{r}="","",IF(P{r}="","在庫中","済"))',  # AA: 売却フラグ
    32: '=IF(OR(AD{r}="",AE{r}="",AE{r}=0),"",IFERROR(ROUND(AD{r}/AE{r}*100,1),""))',  # AF: 閲覧率
    37: '=IF(OR(AJ{r}="",P{r}=""),"",AJ{r}-P{r})',  # AK: 決済リードタイム
}

LISTINGS_URL = "https://jp.mercari.com/mypage/listings"
VIEWPORT = {"width": 1280, "height": 1200}


def get_worksheet():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    return spreadsheet.worksheet(SHEET_NAME)


def get_existing_urls(worksheet) -> set:
    """AT列(URL)から、すでに登録済みの商品URLの集合を作る。"""
    values = worksheet.col_values(COL_URL)
    return {v.strip() for v in values[1:] if v.strip()}  # 1行目はヘッダーなので除く


def ensure_logged_in_session(playwright) -> None:
    """保存済みのログインセッションがなければ、ブラウザを表示して手動ログインしてもらう。"""
    if os.path.exists(STORAGE_STATE_FILE):
        return

    print("初回のみメルカリへのログインが必要です。ブラウザが開きます。")
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(viewport=VIEWPORT)
    page = context.new_page()
    page.goto(LISTINGS_URL, wait_until="load")
    print("表示されたブラウザでメルカリにログインしてください(出品一覧が表示されるまで最大5分待ちます)。")

    page.wait_for_selector('a[data-testid="listed-item"]', timeout=300_000)
    context.storage_state(path=STORAGE_STATE_FILE)
    browser.close()
    print("ログインセッションを保存しました。次回以降は自動でログインします。")


LISTED_LABEL_RE = re.compile(r"(\d+)\s*(分|時間|日|週間|か月|年)前に出品")

# 分・時間前はいずれも「今日」扱いにする(日単位でしか記録しないため)
LISTED_LABEL_DAYS = {"分": 0, "時間": 0, "日": 1, "週間": 7, "か月": 30, "年": 365}


def parse_listed_date(card_text: str, today: datetime.date) -> str:
    """カード内の「〇時間/日前に出品」表記から出品日(YYYY/MM/DD)を計算する。
    「〇前に更新」ではなく「〇前に出品」表記(出品の新しい順ソート時のみ出る)を使うため、
    値下げ等の編集による表示のズレを受けない。
    """
    m = LISTED_LABEL_RE.search(card_text)
    if not m:
        return today.strftime("%Y/%m/%d")
    n = int(m.group(1))
    unit = m.group(2)
    days_ago = n * LISTED_LABEL_DAYS.get(unit, 0)
    return (today - datetime.timedelta(days=days_ago)).strftime("%Y/%m/%d")


def extract_card_data(card, today: datetime.date) -> dict:
    href = card.get_attribute("href")
    name = card.locator('[data-testid="item-label"]').inner_text().strip()
    price_text = card.locator('[data-testid="price"]').inner_text()
    digits = re.sub(r"[^\d]", "", price_text)
    price = int(digits) if digits else None
    card_text = card.inner_text()
    suspended = "公開停止中" in card_text
    return {
        "url": "https://jp.mercari.com" + href.split("?")[0],
        "name": name,
        "price": price,
        "suspended": suspended,
        "listed_date": parse_listed_date(card_text, today),
    }


SORT_TRIGGER_LABELS = ["更新順", "出品の新しい順", "出品の古い順"]


def select_newest_first_sort(page) -> None:
    """並び替えを「出品の新しい順」にする。
    値下げ等で「更新順」が変わってしまう問題を避けるため、出品日そのもので
    ソートする。挿入時は2行目から順に書き込むため、この順序(新しい商品が先頭)が
    そのままシートの上から並ぶ順番になる。案内バルーンがクリックを妨げることが
    あるため、実際のクリックではなく要素へのJSクリックで強制的に選択する。
    """
    try:
        trigger = None
        for label in SORT_TRIGGER_LABELS:
            candidate = page.get_by_text(label, exact=True)
            if candidate.count():
                trigger = candidate.first
                break
        if trigger is None:
            print("並び替えボタンが見つかりませんでした(デフォルトの順序のまま続行します)。")
            return

        trigger.evaluate("el => el.click()")
        page.wait_for_timeout(500)

        option = page.get_by_text("出品の新しい順", exact=True)
        if option.count():
            option.first.evaluate("el => el.click()")
            page.wait_for_timeout(1500)
        else:
            print("「出品の新しい順」の選択肢が見つかりませんでした(デフォルトの順序のまま続行します)。")
    except Exception as e:
        print(f"並び替えの変更に失敗しました(デフォルトの順序のまま続行します): {e}")


def collect_listing_items(page, today: datetime.date) -> list:
    """出品を「出品の新しい順」に並べ、「もっと見る」を最後まで押して全商品を集める。"""
    page.goto(LISTINGS_URL, wait_until="load")
    # 固定時間の待機だとメルカリ側の描画が遅い日に間に合わず、並び替えボタンや
    # 商品カードが「見つからない」まま処理が進んでしまうため、商品カードが
    # 実際に描画されるまで待つ(表示が遅いだけで0件ではないケースに対応)。
    try:
        page.wait_for_selector('a[data-testid="listed-item"]', timeout=15_000)
    except Exception:
        print("出品カードの表示待ちがタイムアウトしました(0件、または表示に失敗した可能性があります)。")

    select_newest_first_sort(page)

    while True:
        more_button = page.get_by_text("もっと見る", exact=True)
        if more_button.count() == 0:
            break
        more_button.first.scroll_into_view_if_needed()
        more_button.first.click()
        page.wait_for_timeout(1200)

    cards = page.locator('a[data-testid="listed-item"]')
    items = []
    seen = set()
    skipped_suspended = 0
    for i in range(cards.count()):
        item = extract_card_data(cards.nth(i), today)
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        if item["suspended"]:
            skipped_suspended += 1
            continue
        items.append(item)

    if skipped_suspended:
        print(f"公開停止中の商品を{skipped_suspended}件スキップしました。")
    return items


def build_row(item: dict, row_number: int) -> list:
    row = [""] * ROW_WIDTH
    row[COL_NAME - 1] = item["name"]
    row[COL_PRICE - 1] = item["price"] if item["price"] is not None else ""
    row[COL_LISTED_DATE - 1] = item["listed_date"]
    row[COL_URL - 1] = item["url"]
    for col, template in FORMULA_TEMPLATES.items():
        row[col - 1] = template.format(r=row_number)
    return row


def main():
    parser = argparse.ArgumentParser(description="メルカリの出品商品をスプレッドシートに反映する")
    parser.add_argument("--limit", type=int, default=None, help="新規追加する商品数の上限(テスト用)")
    parser.add_argument("--dry-run", action="store_true", help="スプレッドシートへの書き込みを行わず内容だけ表示する")
    args = parser.parse_args()

    worksheet = get_worksheet()
    existing_urls = get_existing_urls(worksheet)
    print(f"登録済み商品数: {len(existing_urls)}")

    today = datetime.date.today()

    with sync_playwright() as p:
        ensure_logged_in_session(p)

        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport=VIEWPORT, storage_state=STORAGE_STATE_FILE)
        page = context.new_page()

        print("出品一覧を確認中(もっと見るを最後まで読み込みます)...")
        items = collect_listing_items(page, today)
        print(f"確認できた出品数: {len(items)}")

        browser.close()

    new_items = [it for it in items if it["url"] not in existing_urls]
    if args.limit:
        new_items = new_items[: args.limit]
    print(f"新規に追加する商品数: {len(new_items)}")

    new_rows = [build_row(item, row_number=2 + i) for i, item in enumerate(new_items)]

    if not new_rows:
        print("追加対象の商品はありませんでした。")
        return

    if args.dry_run:
        print("\n--dry-run のためスプレッドシートへの書き込みは行いません。追加予定の内容:")
        for row in new_rows:
            print(row)
        return

    # 末尾追加(append_rows)だとシート下部の空行の先まで飛んでしまうため、
    # ヘッダーの直下(2行目)に挿入し、既存行を下に押し出す(新しい順で上から並ぶ)。
    # inherit_from_before=False: 挿入行の書式はヘッダー行ではなく、押し出される側の
    # データ行(元の2行目)から引き継ぐ。
    worksheet.insert_rows(new_rows, row=2, value_input_option="USER_ENTERED", inherit_from_before=False)
    print(f"{len(new_rows)}件をスプレッドシートに追加しました。")


if __name__ == "__main__":
    main()
