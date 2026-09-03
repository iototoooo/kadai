"""
Google Meet の録画(Google Drive 上)から議事録を自動生成し、Google ドキュメントに保存するツール。

処理の流れ:
  1. Google Drive から録画ファイルをダウンロード
     (--file-id で直接指定、または --folder-id でフォルダ内の最新の動画/音声を自動選択)
  2. 同梱の ffmpeg(imageio-ffmpeg)で音声だけを 16kHz モノラルに圧縮
     - 先頭と末尾の無音を除去する(--no-trim-silence で無効化)。録音末尾の無音・雑音で
       文字起こしモデルが同じ語を繰り返す暴走を防ぐため(会話中の間は残す)
  3. OpenAI の文字起こしモデルで文字起こし(日本語)
     - 25MB を超える、またはモデルの音声長上限(gpt-4o-transcribe は約1400秒)を
       超える場合は時間で分割して逐次文字起こしし、結果を連結する
     - 連続して繰り返される語句(モデルの暴走)は1回に圧縮する
  4. (任意) --chat-file-id で指定した Drive 上のチャットログ(テキスト/Google ドキュメント)を読み込む
  5. OpenAI Chat API で社内共有用の議事録に要約
  6. Google ドキュメントを新規作成し、「議事録 + 参考:全文文字起こし」を1つの文書に書き込む
     - --out-folder-id / 環境変数 MEET_MINUTES_FOLDER_ID で保存先フォルダを指定
       (未指定ならマイドライブ直下に作成)

事前準備:
    pip install -r requirements.txt

    Google Cloud Console で「Google Drive API」と「Google Docs API」を有効化し、
    OAuth クライアント(デスクトップアプリ)の認証情報を section4-3/credentials.json として
    配置しておくこと(既存の他スクリプトと同じファイルを流用できる)。
    初回実行時はブラウザが開き、Google アカウントでの認可が必要。
    許可後は section5-1/token_meet_minutes.json にトークンが保存され、以降は自動で認証される。
    (このスクリプト専用のスコープのため、他スクリプトの token.json とは分離している)

    リポジトリ直下の .env に以下を設定しておくこと:
      OPENAI_API_KEY            (必須)
      OPENAI_MODEL             (任意、要約用。未設定なら gpt-4o-mini)
      OPENAI_TRANSCRIBE_MODEL  (任意、文字起こし用。未設定なら whisper-1。
                                gpt-4o-transcribe 系は長い音声で出力が途中で
                                切れることがあるため既定にしていない)
      MEET_MINUTES_FOLDER_ID   (任意、議事録の保存先 Drive フォルダ ID。未設定ならマイドライブ直下)

実行例:
    # Drive のファイル ID を直接指定
    python meet_minutes.py --file-id 1AbcDEF...XYZ

    # フォルダ内の最新の録画を自動で選ぶ
    python meet_minutes.py --folder-id 1Folder...ID --meeting-title "週次定例MTG"

    # チャットログも一緒に渡す
    python meet_minutes.py --file-id 1Abc... --chat-file-id 1Chat...

    # 文字起こしまでで止める(結果はローカルの transcript_*.txt に保存)
    python meet_minutes.py --file-id 1Abc... --transcript-only

    # 文字起こし済みテキストから議事録だけ作り直す(要約プロンプト調整用)
    python meet_minutes.py --from-transcript transcript_週次定例MTG_20260903_101500.txt
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

import imageio_ffmpeg
from dotenv import load_dotenv
from openai import OpenAI

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# OAuth 認証情報は既存スクリプトと共通のものを流用する
CREDENTIALS_FILE = os.path.join(SCRIPT_DIR, "..", "section4-3", "credentials.json")
# トークンはこのスクリプト専用スコープのため他スクリプトと分離する
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token_meet_minutes.json")

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TRANSCRIBE_MODEL = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
MEET_MINUTES_FOLDER_ID = os.environ.get("MEET_MINUTES_FOLDER_ID", "")

JST = ZoneInfo("Asia/Tokyo")

# 文字起こし API のアップロード上限は 25MB。余裕を持たせてこのサイズで分割判定する。
MAX_AUDIO_BYTES = 24 * 1024 * 1024
# gpt-4o-transcribe 系は音声長 1400 秒が上限。余裕を持たせて超過分は分割する
# (whisper-1 には長さ上限は無いが、分割しても問題はない)。
MAX_AUDIO_SECONDS = 1350
# 分割時の1チャンクの長さ(秒)。上限 1350 秒に収まるようにする。
SEGMENT_SECONDS = 20 * 60
# 無音除去フィルタ: 音声の「先頭と末尾」の無音だけを落とす(会話中の間は残す)。
# 録音末尾の無音・雑音で文字起こしモデルが暴走するのを防ぐのが目的。
# areverse で前後を反転させ、両端に同じ start トリムを適用する定番の書き方。
SILENCE_FILTER = (
    "silenceremove=start_periods=1:start_duration=0:start_threshold=-40dB,"
    "areverse,"
    "silenceremove=start_periods=1:start_duration=0:start_threshold=-40dB,"
    "areverse"
)

openai_client = OpenAI(api_key=OPENAI_API_KEY)

MINUTES_SYSTEM_PROMPT = """あなたは日本語の議事録作成アシスタントです。
会議の文字起こし(および任意でチャットログ)から、社内共有用の議事録を作成します。

出力ルール:
- 見出しは必ず「## セクション名」の形式のみ使う(「#」単体や「###」は使わない)。
- 本文は簡潔な箇条書き(行頭「- 」)で書く。
- 文字起こしから読み取れない項目は「(記載なし)」と書く。憶測で内容を補わない。
- 発言者が特定できる場合は要点の末尾に (氏名) を添える。

セクション構成(この順・この見出し名で必ずすべて出力する):
## 会議概要
- 日時 / 参加者 / 目的 を分かる範囲で1行ずつ
## アジェンダ
## 議論の要点
- 議題ごとに要点をまとめる
## 決定事項
## ネクストアクション
- 1アクションを1行で「- 担当: <氏名または(未定)> ／ 期限: <期日または(未定)> ／ 内容: <タスク>」の形式で書く
- アクションが無ければ「- (記載なし)」の1行のみにする
## 保留・懸念事項
## 次回に向けて
"""


def get_services():
    """Drive / Docs の API クライアントを OAuth 認証で取得する。"""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                # 保存済みのリフレッシュトークンが失効/取り消し済み。ブラウザ認証をやり直す。
                creds = None

        if not creds or not creds.valid:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"OAuth 認証情報が見つかりません: {CREDENTIALS_FILE}\n"
                    "Google Cloud Console でデスクトップアプリの認証情報を作成し、"
                    "credentials.json として配置してください。"
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    drive = build("drive", "v3", credentials=creds)
    docs = build("docs", "v1", credentials=creds)
    return drive, docs


def get_file_metadata(drive, file_id: str) -> dict:
    return (
        drive.files()
        .get(
            fileId=file_id,
            fields="id, name, mimeType, createdTime, size",
            supportsAllDrives=True,
        )
        .execute()
    )


def pick_latest_recording(drive, folder_id: str) -> dict:
    """フォルダ内で最も新しい動画/音声ファイルを1件返す。"""
    query = (
        f"'{folder_id}' in parents and trashed = false and "
        "(mimeType contains 'video/' or mimeType contains 'audio/')"
    )
    response = (
        drive.files()
        .list(
            q=query,
            orderBy="createdTime desc",
            pageSize=1,
            fields="files(id, name, mimeType, createdTime, size)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = response.get("files", [])
    if not files:
        raise RuntimeError(
            f"フォルダ内に録画(動画/音声)ファイルが見つかりません: {folder_id}"
        )
    return files[0]


def download_file(drive, file_id: str, dest_path: str) -> None:
    request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    with open(dest_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                print(f"\r  ダウンロード中... {int(status.progress() * 100)}%", end="", flush=True)
    print("\r  ダウンロード完了            ")


def download_text_file(drive, file_id: str) -> str:
    """テキストファイル、または Google ドキュメントをプレーンテキストとして取得する。"""
    meta = (
        drive.files()
        .get(fileId=file_id, fields="mimeType, name", supportsAllDrives=True)
        .execute()
    )
    mime = meta.get("mimeType", "")
    if mime == "application/vnd.google-apps.document":
        data = drive.files().export(fileId=file_id, mimeType="text/plain").execute()
    elif mime.startswith("application/vnd.google-apps"):
        raise RuntimeError(f"チャットログとして読めない形式です: {mime}")
    else:
        data = drive.files().get_media(fileId=file_id, supportsAllDrives=True).execute()

    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return str(data)


def _ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def extract_audio(src_path: str, dst_path: str, trim_silence: bool = True) -> None:
    """録画から音声のみを取り出し、16kHz モノラル AAC(32kbps)に圧縮する。

    trim_silence=True のときは長い無音区間を除去する。録音末尾の無音や雑音で
    文字起こしモデルが同じ語を延々と繰り返す暴走を防ぐため。
    """
    cmd = [_ffmpeg(), "-y", "-i", src_path, "-vn", "-ac", "1", "-ar", "16000"]
    if trim_silence:
        cmd += ["-af", SILENCE_FILTER]
    cmd += ["-c:a", "aac", "-b:a", "32k", dst_path]

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not os.path.exists(dst_path):
        raise RuntimeError(f"音声の抽出に失敗しました:\n{proc.stderr[-2000:]}")


def get_audio_duration(path: str) -> float | None:
    """ffmpeg の出力から音声の長さ(秒)を取得する。取れなければ None。"""
    proc = subprocess.run(
        [_ffmpeg(), "-i", path], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr or "")
    if not m:
        return None
    h, mm, ss = m.groups()
    return int(h) * 3600 + int(mm) * 60 + float(ss)


def split_audio(src_path: str, out_dir: str) -> list[str]:
    """音声を SEGMENT_SECONDS 秒ごとのチャンクに分割する(念のため再エンコードする)。"""
    pattern = os.path.join(out_dir, "chunk_%03d.m4a")
    cmd = [
        _ffmpeg(), "-y", "-i", src_path,
        "-f", "segment", "-segment_time", str(SEGMENT_SECONDS),
        "-reset_timestamps", "1", "-ac", "1", "-ar", "16000",
        "-c:a", "aac", "-b:a", "32k",
        pattern,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"音声の分割に失敗しました:\n{proc.stderr[-2000:]}")

    chunks = sorted(
        os.path.join(out_dir, name)
        for name in os.listdir(out_dir)
        if re.match(r"chunk_\d+\.m4a$", name)
    )
    if not chunks:
        raise RuntimeError("音声の分割結果が見つかりません。")
    return chunks


def _collapse_repeats(text: str) -> str:
    """連続して繰り返される語句を1回に圧縮する(文字起こしモデルの暴走対策)。

    「断 断 断 断 ...」「血がね 血がね ...」のように、同じ短い並びが3回以上
    連続する箇所を1回だけに減らす。正当な「はい はい はい」等もまれに縮むが、
    議事録用途では影響は小さい。
    """
    collapsed = re.sub(r"(.{1,40}?)(?:[ 　\n]*\1){2,}", r"\1", text)
    # 1文字の連続(句読点や記号を除く)も畳む
    collapsed = re.sub(r"([^\s\W])(?:[ 　]*\1){3,}", r"\1", collapsed)
    return collapsed


def transcribe_file(path: str) -> str:
    with open(path, "rb") as f:
        result = openai_client.audio.transcriptions.create(
            model=OPENAI_TRANSCRIBE_MODEL,
            file=f,
            language="ja",
            response_format="text",
        )
    # response_format="text" のときは文字列が返る。念のため両対応にしておく。
    return result if isinstance(result, str) else getattr(result, "text", str(result))


def transcribe_audio(audio_path: str, work_dir: str) -> str:
    size = os.path.getsize(audio_path)
    # 音声長の上限があるのは gpt-4o-transcribe 系のみ。whisper-1 は長さ無制限なので
    # 25MB 以内なら分割せず1回で処理する(分割の継ぎ目を作らない)。
    has_duration_limit = OPENAI_TRANSCRIBE_MODEL.startswith("gpt-4o")
    duration = get_audio_duration(audio_path) if has_duration_limit else None
    too_long = duration is not None and duration > MAX_AUDIO_SECONDS

    if size <= MAX_AUDIO_BYTES and not too_long:
        print(f"  文字起こし中(1ファイル, {size / 1024 / 1024:.1f}MB)...")
        return _collapse_repeats(transcribe_file(audio_path).strip())

    reason = "サイズ超過" if size > MAX_AUDIO_BYTES else f"長さ超過({duration:.0f}秒)"
    print(f"  {reason}のため分割します({size / 1024 / 1024:.1f}MB)...")
    chunk_dir = os.path.join(work_dir, "chunks")
    os.makedirs(chunk_dir, exist_ok=True)
    chunks = split_audio(audio_path, chunk_dir)

    texts = []
    for i, chunk in enumerate(chunks, 1):
        csize = os.path.getsize(chunk)
        print(f"  文字起こし中({i}/{len(chunks)}, {csize / 1024 / 1024:.1f}MB)...")
        if csize > MAX_AUDIO_BYTES:
            raise RuntimeError(
                f"分割後のチャンクがまだ 25MB を超えています: {chunk}\n"
                "meet_minutes.py の SEGMENT_SECONDS を小さくして再実行してください。"
            )
        texts.append(transcribe_file(chunk).strip())
    return _collapse_repeats("\n".join(t for t in texts if t).strip())


def summarize_to_minutes(transcript: str, chat_log: str, meeting_title: str) -> str:
    user_parts = [f"会議名: {meeting_title}", "", "【会議の文字起こし】", transcript]
    if chat_log:
        user_parts += ["", "【チャットログ】", chat_log]

    response = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": MINUTES_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(user_parts)},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()


def _u16len(s: str) -> int:
    """Google Docs API のインデックスは UTF-16 コード単位で数えるため、その長さを返す。"""
    return len(s.encode("utf-16-le")) // 2


def build_blocks(
    meeting_title: str, minutes_md: str, transcript: str, meta_lines: list[str]
) -> list[tuple[str, str | None]]:
    """ドキュメントに書き込む (段落テキスト, 見出しスタイル) のリストを組み立てる。"""
    blocks: list[tuple[str, str | None]] = [(f"議事録: {meeting_title}\n", "HEADING_1")]
    for line in meta_lines:
        blocks.append((line + "\n", None))
    blocks.append(("\n", None))

    for raw in minutes_md.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            blocks.append((line[3:].strip() + "\n", "HEADING_2"))
        elif line.startswith("# "):
            blocks.append((line.lstrip("# ").strip() + "\n", "HEADING_2"))
        else:
            blocks.append((line + "\n", None))

    blocks.append(("\n", None))
    blocks.append(("参考: 全文文字起こし\n", "HEADING_1"))
    blocks.append((transcript + "\n", None))
    return blocks


def create_minutes_doc(docs, drive, doc_title: str, blocks, out_folder_id: str | None) -> str:
    doc = docs.documents().create(body={"title": doc_title}).execute()
    doc_id = doc["documentId"]

    full_text = "".join(text for text, _ in blocks)

    requests = []
    # insertText は1リクエストのサイズ制限を避けるため小分けにし、先頭から順に挿入する
    chunk_size = 4000
    index = 1
    for start in range(0, len(full_text), chunk_size):
        piece = full_text[start:start + chunk_size]
        requests.append({"insertText": {"location": {"index": index}, "text": piece}})
        index += _u16len(piece)

    # 見出し段落へのスタイル適用は、挿入完了後の最終テキスト上の位置で指定する
    pos = 1
    for text, style in blocks:
        length = _u16len(text)
        if style:
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": pos, "endIndex": pos + length},
                        "paragraphStyle": {"namedStyleType": style},
                        "fields": "namedStyleType",
                    }
                }
            )
        pos += length

    docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

    if out_folder_id:
        meta = drive.files().get(fileId=doc_id, fields="parents", supportsAllDrives=True).execute()
        prev_parents = ",".join(meta.get("parents", []))
        drive.files().update(
            fileId=doc_id,
            addParents=out_folder_id,
            removeParents=prev_parents,
            fields="id, parents",
            supportsAllDrives=True,
        ).execute()

    return doc_id


def _parse_drive_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(JST)
    except ValueError:
        return None


def _title_from_path(path: str) -> str:
    name = os.path.splitext(os.path.basename(path))[0]
    name = re.sub(r"^transcript_", "", name)
    name = re.sub(r"_\d{8}_\d{6}$", "", name)
    return name or "meeting"


def _save_transcript(meeting_title: str, transcript: str) -> str:
    ts = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^\w\-]+", "_", meeting_title).strip("_")[:60] or "meeting"
    path = os.path.join(SCRIPT_DIR, f"transcript_{safe}_{ts}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(transcript + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(
        description="Google Meet の録画から議事録を生成し Google ドキュメントに保存する"
    )
    parser.add_argument("--file-id", help="録画ファイルの Google Drive ファイル ID")
    parser.add_argument("--folder-id", help="このフォルダ内の最新の録画(動画/音声)を自動で使う")
    parser.add_argument(
        "--chat-file-id",
        help="チャットログ(テキスト/Google ドキュメント)の Drive ファイル ID(任意)",
    )
    parser.add_argument(
        "--out-folder-id",
        default=MEET_MINUTES_FOLDER_ID,
        help="議事録の保存先 Drive フォルダ ID(未指定なら環境変数 MEET_MINUTES_FOLDER_ID、それも無ければマイドライブ直下)",
    )
    parser.add_argument(
        "--meeting-title", help="議事録のタイトルに使う会議名(未指定なら録画ファイル名)"
    )
    parser.add_argument(
        "--from-transcript",
        help="文字起こし済みテキストファイルから議事録だけを作成する(ダウンロード・文字起こしを行わない)",
    )
    parser.add_argument(
        "--transcript-only",
        action="store_true",
        help="文字起こしまで実行してファイルに保存し、要約・ドキュメント作成は行わない",
    )
    parser.add_argument(
        "--no-trim-silence",
        action="store_true",
        help="音声の無音除去を行わない(既定は無音を除去して文字起こしの暴走を防ぐ)",
    )
    parser.add_argument(
        "--keep-audio", action="store_true", help="一時的な音声ファイルを削除せず残す"
    )
    args = parser.parse_args()

    if not args.file_id and not args.folder_id and not args.from_transcript:
        parser.error("--file-id / --folder-id / --from-transcript のいずれかを指定してください。")

    drive = docs = None
    recording_dt = None

    # --- 文字起こしフェーズ ---
    if args.from_transcript:
        if not os.path.exists(args.from_transcript):
            parser.error(f"ファイルが見つかりません: {args.from_transcript}")
        with open(args.from_transcript, encoding="utf-8") as f:
            transcript = f.read().strip()
        meeting_title = args.meeting_title or _title_from_path(args.from_transcript)
        transcript_path = args.from_transcript
        print(f"文字起こしファイルを読み込みました: {args.from_transcript}")
    else:
        drive, docs = get_services()
        if args.file_id:
            meta = get_file_metadata(drive, args.file_id)
        else:
            print(f"フォルダ内の最新の録画を検索中: {args.folder_id}")
            meta = pick_latest_recording(drive, args.folder_id)
        print(f"対象の録画: {meta['name']} ({meta.get('mimeType')})")

        meeting_title = args.meeting_title or os.path.splitext(meta["name"])[0]
        recording_dt = _parse_drive_time(meta.get("createdTime"))

        work_dir = tempfile.mkdtemp(prefix="meet_minutes_")
        try:
            src_ext = os.path.splitext(meta["name"])[1] or ".mp4"
            src_path = os.path.join(work_dir, f"recording{src_ext}")
            print("録画をダウンロードしています...")
            download_file(drive, meta["id"], src_path)

            audio_path = os.path.join(work_dir, "audio.m4a")
            print("音声を抽出・圧縮しています...")
            extract_audio(src_path, audio_path, trim_silence=not args.no_trim_silence)

            transcript = transcribe_audio(audio_path, work_dir)
        finally:
            if args.keep_audio:
                print(f"一時ファイルを残しました: {work_dir}")
            else:
                shutil.rmtree(work_dir, ignore_errors=True)

        if not transcript:
            print("文字起こし結果が空でした。処理を中止します。")
            return

        transcript_path = _save_transcript(meeting_title, transcript)
        print(f"文字起こしを保存しました: {transcript_path}")

    if args.transcript_only:
        print("--transcript-only のためここで終了します。")
        return

    # --- チャットログ(任意) ---
    chat_log = ""
    if args.chat_file_id:
        if drive is None:
            drive, docs = get_services()
        print("チャットログを読み込んでいます...")
        try:
            chat_log = download_text_file(drive, args.chat_file_id).strip()
        except (HttpError, RuntimeError) as e:
            print(f"チャットログの読み込みに失敗しました(スキップします): {e}")

    # --- 要約フェーズ ---
    print(f"OpenAI ({OPENAI_MODEL}) で議事録を作成しています...")
    minutes_md = summarize_to_minutes(transcript, chat_log, meeting_title)

    # --- Google ドキュメント作成 ---
    if docs is None:
        drive, docs = get_services()

    date_str = (recording_dt or datetime.now(JST)).strftime("%Y-%m-%d")
    doc_title = f"議事録_{date_str}_{meeting_title}"
    meta_lines = [
        f"会議日時: {recording_dt.strftime('%Y-%m-%d %H:%M') if recording_dt else '(記載なし)'}",
        f"議事録作成: {datetime.now(JST).strftime('%Y-%m-%d %H:%M')}",
        f"文字起こし: OpenAI {OPENAI_TRANSCRIBE_MODEL} / 要約: OpenAI {OPENAI_MODEL}",
        f"チャットログ: {'あり' if chat_log else 'なし'}",
    ]
    blocks = build_blocks(meeting_title, minutes_md, transcript, meta_lines)

    print("Google ドキュメントを作成しています...")
    doc_id = create_minutes_doc(docs, drive, doc_title, blocks, args.out_folder_id or None)

    print("\n完了しました。")
    print(f"タイトル: {doc_title}")
    print(f"URL: https://docs.google.com/document/d/{doc_id}/edit")


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as e:
        print(f"\n{e}")
        sys.exit(1)
    except HttpError as e:
        print(f"\nGoogle API エラー: {e}")
        print(
            "Google Cloud Console で Drive API / Docs API が有効か、"
            "認可したアカウントに対象ファイルの閲覧権限があるか確認してください。"
        )
        sys.exit(1)
