"""
Zoomの予定ミーティングについて、LINEへ以下の通知を行う常駐スクリプト

  - 毎朝8:00に「本日開催予定の会議」一覧を通知
  - 各会議の開始10分前に個別リマインドを通知

事前準備:
  - zoom_create_meeting.py の認証設定（ZOOM_ACCOUNT_ID / ZOOM_CLIENT_ID / ZOOM_CLIENT_SECRET）
  - line_send_message.py の認証設定（LINE_CHANNEL_ACCESS_TOKEN）
  - .env の LINE_DEFAULT_TO に通知先のuserId/groupId/roomIdを設定（必須）
  - Windows の場合、タイムゾーン変換に tzdata パッケージが必要
    （requirements.txt に追加済み。 pip install -r requirements.txt で導入）

実行方法:
  python zoom_line_reminder_daemon.py

このプロセスを起動したまま動かし続ける必要がある（PCスリープ中は動作しない）。
Windowsで常駐させる場合はタスクスケジューラで「ログオン時」または
「PC起動時」トリガーのタスクとして本スクリプトを実行するとよい。

送信済みの通知はスクリプトと同じフォルダの zoom_reminder_state.json に記録し、
二重送信や再起動時の重複通知を防ぐ。
"""
import json
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from line_send_message import LINE_DEFAULT_TO, push_message
from zoom_list_meetings import list_upcoming_meetings, parse_start_time

load_dotenv()

JST = ZoneInfo("Asia/Tokyo")
STATE_FILE = Path(__file__).parent / "zoom_reminder_state.json"

DAILY_REMINDER_HOUR = 8  # 朝の一覧通知を送る時刻（時）
BEFORE_MINUTES = 10  # 開始何分前にリマインドするか
CHECK_INTERVAL_SECONDS = 60  # 何秒おきに確認するか


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"daily_sent_date": None, "reminded_meeting_ids": []}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def build_daily_text(meetings: list[dict], today: date) -> str | None:
    todays = [
        (parse_start_time(m), m) for m in meetings
    ]
    todays = [(t, m) for t, m in todays if t is not None and t.date() == today]
    if not todays:
        return None

    todays.sort(key=lambda pair: pair[0])
    lines = [f"本日（{today.strftime('%Y-%m-%d')}）の会議予定"]
    for start, m in todays:
        lines.append(f"- {start.strftime('%H:%M')} {m.get('topic')}\n  {m.get('join_url')}")
    return "\n".join(lines)


def build_before_text(meeting: dict, start: datetime) -> str:
    return (
        f"【まもなく開始】{meeting.get('topic')}\n"
        f"開始: {start.strftime('%H:%M')}（あと{BEFORE_MINUTES}分以内）\n"
        f"参加リンク: {meeting.get('join_url')}"
    )


def run_once(state: dict, to: str) -> dict:
    now = datetime.now(JST)
    today_str = now.date().isoformat()

    # 日付が変わったら送信履歴をリセット
    if state.get("daily_sent_date") != today_str:
        state["reminded_meeting_ids"] = []

    try:
        meetings = list_upcoming_meetings()
    except Exception as e:
        print(f"[{now:%Y-%m-%d %H:%M:%S}] ミーティング取得に失敗しました: {e}")
        return state

    # 朝の会議一覧通知（8:00以降、その日まだ送っていなければ1回だけ）
    if now.hour >= DAILY_REMINDER_HOUR and state.get("daily_sent_date") != today_str:
        text = build_daily_text(meetings, now.date())
        if text:
            push_message(to, text)
            print(f"[{now:%Y-%m-%d %H:%M:%S}] 本日の会議一覧を通知しました")
        state["daily_sent_date"] = today_str

    # 開始10分前リマインド
    reminded = set(state.get("reminded_meeting_ids", []))
    for m in meetings:
        start = parse_start_time(m)
        if start is None:
            continue
        minutes_until = (start - now).total_seconds() / 60
        meeting_key = f"{m.get('id')}_{start.isoformat()}"
        if 0 <= minutes_until <= BEFORE_MINUTES and meeting_key not in reminded:
            push_message(to, build_before_text(m, start))
            reminded.add(meeting_key)
            print(f"[{now:%Y-%m-%d %H:%M:%S}] 開始前リマインドを通知しました: {m.get('topic')}")
    state["reminded_meeting_ids"] = list(reminded)

    return state


def main():
    to = LINE_DEFAULT_TO
    if not to:
        raise SystemExit(".env の LINE_DEFAULT_TO に通知先IDを設定してください")

    print("Zoom会議リマインドデーモンを起動しました（Ctrl+Cで終了）")
    state = load_state()
    while True:
        state = run_once(state, to)
        save_state(state)
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
