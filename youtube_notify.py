import argparse
import json
import os
import re
from datetime import datetime

from dotenv import load_dotenv
from googleapiclient.errors import HttpError

from gmail_send import send_email
from youtube_search import search_videos

load_dotenv()

STATE_DIR = "youtube_notify_state"


def state_file_path(keyword: str) -> str:
    safe_keyword = re.sub(r"[^\w]+", "_", keyword).strip("_") or "keyword"
    return os.path.join(STATE_DIR, f"seen_{safe_keyword}.json")


def load_seen_ids(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        return set(json.load(f))


def save_seen_ids(path: str, video_ids: set[str]) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(video_ids), f, ensure_ascii=False, indent=2)


def build_email_body(keyword: str, videos: list[dict]) -> str:
    lines = [f'キーワード「{keyword}」で新着動画が見つかりました。', ""]
    for i, video in enumerate(videos, start=1):
        lines.append(f"{i}. {video['title']}")
        lines.append(f"   {video['url']}")
    return "\n".join(lines)


def check_and_notify(keyword: str, to: str, max_results: int) -> None:
    path = state_file_path(keyword)
    seen_ids = load_seen_ids(path)
    is_first_run = len(seen_ids) == 0

    videos = search_videos(keyword, max_results=max_results)
    current_ids = {v["url"].split("v=")[1] for v in videos}

    if is_first_run:
        save_seen_ids(path, current_ids)
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 初回実行のため、現在の{len(videos)}件をベースラインとして記録しました（通知なし）。")
        return

    new_videos = [v for v in videos if v["url"].split("v=")[1] not in seen_ids]

    if not new_videos:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 新着動画はありませんでした。")
        return

    subject = f"【YouTube新着】{keyword}（{len(new_videos)}件）"
    body = build_email_body(keyword, new_videos)
    send_email(to, subject, body)

    save_seen_ids(path, seen_ids | current_ids)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 新着{len(new_videos)}件を {to} に通知しました。")


def main():
    parser = argparse.ArgumentParser(description="YouTube新着動画をメール通知する")
    parser.add_argument(
        "--keyword",
        default=os.getenv("YOUTUBE_NOTIFY_KEYWORD"),
        help="検索キーワード（未指定時は環境変数 YOUTUBE_NOTIFY_KEYWORD を使用）",
    )
    parser.add_argument(
        "--to",
        default=os.getenv("YOUTUBE_NOTIFY_TO"),
        help="通知先メールアドレス（未指定時は環境変数 YOUTUBE_NOTIFY_TO を使用）",
    )
    parser.add_argument("--max-results", type=int, default=10, help="1回の検索で取得する件数")
    args = parser.parse_args()

    if not args.keyword:
        parser.error("キーワードを --keyword または環境変数 YOUTUBE_NOTIFY_KEYWORD で指定してください。")
    if not args.to:
        parser.error("通知先を --to または環境変数 YOUTUBE_NOTIFY_TO で指定してください。")
    if not os.getenv("YOUTUBE_API_KEY"):
        parser.error("YOUTUBE_API_KEY が設定されていません。.env を確認してください。")

    try:
        check_and_notify(args.keyword, args.to, args.max_results)
    except HttpError as e:
        print(f"APIエラーが発生しました: {e}")


if __name__ == "__main__":
    main()
