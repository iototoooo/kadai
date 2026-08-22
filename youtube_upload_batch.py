import mimetypes
import os

import requests
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# credentials.json（drive_upload.py等と共通のOAuthクライアント）を使うが、
# 動画アップロードに加えて再生リストへの追加も行うため youtube スコープ（管理権限）が必要。
# そのため token は別ファイルに保存する。
# 初回実行時はブラウザでの認可時に「YouTube Data API v3」が有効なプロジェクトであること、
# かつログインするGoogleアカウントがアップロード先のYouTubeチャンネルを所有していることを確認すること。
# なお videos.insert は1回あたり約1600ユニット消費するため、デフォルトの1日10,000ユニット枠では
# 1日に数本程度が上限の目安。
SCOPES = ["https://www.googleapis.com/auth/youtube"]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token_youtube_upload.json"

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".wmv", ".flv", ".mkv", ".webm", ".m4v"}

PRIVACY_STATUS = "unlisted"  # private / unlisted / public
CATEGORY_ID = "22"  # People & Blogs

# アップロード対象の動画フォルダ（固定）。実行のたびにこの中の動画すべてが対象になる。
FOLDER_PATH = r"C:\Users\iotot\OneDrive\デスクトップ\サッカー動画アップロード"

# アップロード先として想定しているチャンネルのハンドル。認証したアカウントのチャンネルが
# これと異なる場合は誤ったアカウントとみなして自動的に中止する。
EXPECTED_CHANNEL_HANDLE = "@NSC2024-lj7fk"

load_dotenv()


def get_youtube_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def list_video_files(folder_path: str) -> list[str]:
    return sorted(
        f
        for f in os.listdir(folder_path)
        if os.path.isfile(os.path.join(folder_path, f))
        and os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS
    )


def upload_video(
    youtube,
    file_path: str,
    title: str,
    description: str = "",
    privacy_status: str = PRIVACY_STATUS,
    category_id: str = CATEGORY_ID,
) -> dict:
    mime_type, _ = mimetypes.guess_type(file_path)
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
        },
    }
    media = MediaFileUpload(
        file_path,
        mimetype=mime_type or "video/*",
        chunksize=8 * 1024 * 1024,
        resumable=True,
    )
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"    アップロード中... {int(status.progress() * 100)}%")

    return response


def get_current_channel_info(youtube) -> dict | None:
    response = youtube.channels().list(part="snippet", mine=True).execute()
    items = response.get("items", [])
    if not items:
        return None
    snippet = items[0]["snippet"]
    return {"title": snippet.get("title"), "handle": snippet.get("customUrl")}


def list_my_playlists(youtube) -> list[dict]:
    playlists = []
    request = youtube.playlists().list(part="snippet", mine=True, maxResults=50)
    while request is not None:
        response = request.execute()
        playlists.extend(response.get("items", []))
        request = youtube.playlists().list_next(request, response)
    return playlists


def choose_playlist(youtube) -> str | None:
    playlists = list_my_playlists(youtube)
    if not playlists:
        print("\n再生リストが見つかりませんでした。再生リストへの追加はスキップします。")
        return None

    print("\n再生リストを選択してください（今回アップロードする動画すべてに適用されます）:")
    print("  0. 追加しない")
    for i, playlist in enumerate(playlists, start=1):
        print(f"  {i}. {playlist['snippet']['title']}")

    choice = input("番号（未入力で追加なし）: ").strip()
    if not choice or choice == "0":
        return None

    if not choice.isdigit() or not (1 <= int(choice) <= len(playlists)):
        print("入力が不正なため、再生リストへの追加はスキップします。")
        return None

    return playlists[int(choice) - 1]["id"]


def add_video_to_playlist(youtube, playlist_id: str, video_id: str) -> None:
    youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        },
    ).execute()


def build_line_summary(results: list[tuple[str, str]]) -> str:
    lines = [f"YouTubeに{len(results)}件の動画をアップロードしました（限定公開）", ""]
    for i, (title, url) in enumerate(results, start=1):
        lines.append(f"{i}. {title}")
        lines.append(f"   {url}")
    return "\n".join(lines)


def build_line_summary_playlist(playlist_id: str, count: int) -> str:
    playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
    return f"YouTubeに{count}件の動画をアップロードしました（限定公開）\n再生リスト: {playlist_url}"


def main():
    print("YouTube 一括アップロード → LINE通知")
    print("-" * 40)

    if not os.path.isdir(FOLDER_PATH):
        print(f"フォルダが見つかりません: {FOLDER_PATH}")
        return

    filenames = list_video_files(FOLDER_PATH)
    if not filenames:
        print(f"対象の動画ファイル（mp4, mov, avi, wmv, flv, mkv, webm, m4v）が {FOLDER_PATH} に見つかりませんでした。")
        return

    print(f"\n{len(filenames)}件の動画が見つかりました。それぞれタイトルを入力してください。")
    jobs = []
    for filename in filenames:
        default_title = os.path.splitext(filename)[0]
        title = input(f"  [{filename}] タイトル（未入力で「{default_title}」）: ").strip() or default_title
        jobs.append((filename, title))

    youtube = get_youtube_service()

    channel_info = get_current_channel_info(youtube)
    if not channel_info:
        print("認証したアカウントに紐づくチャンネルが見つかりませんでした。")
        return

    print(f"\nアップロード先チャンネル: {channel_info['title']} ({channel_info['handle']})")

    if (channel_info["handle"] or "").lower() != EXPECTED_CHANNEL_HANDLE.lower():
        print(
            f"想定しているチャンネル（{EXPECTED_CHANNEL_HANDLE}）と異なります。"
            f"認証しているGoogleアカウントを確認するか、{TOKEN_FILE} を削除して正しいアカウントで再認証してください。"
        )
        return

    playlist_id = choose_playlist(youtube)

    results = []
    for filename, title in jobs:
        file_path = os.path.join(FOLDER_PATH, filename)
        print(f"\nアップロード中: {filename} → 「{title}」")
        try:
            response = upload_video(youtube, file_path, title)
        except HttpError as e:
            print(f"  アップロードに失敗しました: {e}")
            continue
        video_id = response["id"]
        url = f"https://youtu.be/{video_id}"
        print(f"  完了: {url}")

        if playlist_id:
            try:
                add_video_to_playlist(youtube, playlist_id, video_id)
                print("  再生リストに追加しました")
            except HttpError as e:
                print(f"  再生リストへの追加に失敗しました: {e}")

        results.append((title, url))

    if not results:
        print("\nアップロードに成功した動画がなかったため、LINE通知は行いません。")
        return

    from line_send_message import LINE_DEFAULT_TO, push_message

    prompt = "\n通知先LINE ID（userId / groupId / roomId）"
    prompt += f"（未入力でデフォルト: {LINE_DEFAULT_TO}）" if LINE_DEFAULT_TO else ""
    to = input(f"{prompt}: ").strip() or LINE_DEFAULT_TO or ""
    if not to:
        print("通知先IDが未指定のため、LINE通知はスキップしました。")
        return

    text = (
        build_line_summary_playlist(playlist_id, len(results))
        if playlist_id
        else build_line_summary(results)
    )
    try:
        push_message(to, text)
    except requests.exceptions.HTTPError as e:
        print(f"\nLINE通知でHTTPエラーが発生しました: {e}")
        print(f"レスポンス: {e.response.text}")
        return

    print(f"\n{len(results)}件のリンクをLINEに通知しました。")


if __name__ == "__main__":
    main()
