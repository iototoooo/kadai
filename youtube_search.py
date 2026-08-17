import os

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Google Cloud Console で「YouTube Data API v3」を有効化し、APIキーを発行しておくこと
load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")
MAX_RESULTS = 10


def search_videos(query: str, max_results: int = MAX_RESULTS) -> list[dict]:
    youtube = build("youtube", "v3", developerKey=API_KEY)

    response = (
        youtube.search()
        .list(
            q=query,
            part="snippet",
            type="video",
            maxResults=max_results,
        )
        .execute()
    )

    videos = []
    for item in response.get("items", []):
        video_id = item["id"]["videoId"]
        title = item["snippet"]["title"]
        videos.append(
            {
                "title": title,
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }
        )
    return videos


def main():
    print("YouTube 動画検索")
    print("-" * 40)

    if not API_KEY:
        print("YOUTUBE_API_KEY が設定されていません。.env を確認してください。")
        return

    keyword = input("検索キーワード: ").strip()
    if not keyword:
        print("キーワードを入力してください。")
        return

    try:
        videos = search_videos(keyword)
    except HttpError as e:
        print(f"\nAPIエラーが発生しました: {e}")
        print("Google Cloud ConsoleでYouTube Data API v3が有効化されているか確認してください。")
        return

    if not videos:
        print("該当する動画が見つかりませんでした。")
        return

    print(f"\n「{keyword}」の検索結果（{len(videos)}件）")
    print("-" * 40)
    for i, video in enumerate(videos, start=1):
        print(f"{i}. {video['title']}")
        print(f"   {video['url']}")


if __name__ == "__main__":
    main()
