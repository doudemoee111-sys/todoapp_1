"""YouTube Data API v3 で動画を非公開アップロード+予約公開する"""

import datetime
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import config

SCOPES = ["https://www.googleapis.com/auth/youtube"]  # アップロード+チャンネル管理(バナー/概要欄)
CLIENT_SECRET_FILE = config.BASE_DIR / "client_secret.json"
TOKEN_FILE = config.BASE_DIR / "token.json"
CATEGORY_ID = "24"  # エンタメ
TOKEN_URI = "https://oauth2.googleapis.com/token"

# ---- チャンネルガード(別組織の睡眠チャンネル等への誤投稿を防ぐ安全装置) ----------
# FactSpark のショートは「世界の雑学王」チャンネルにだけ投稿する。環境変数
# YOUTUBE_REFRESH_TOKEN 等が万一別チャンネル(睡眠系など)の認可だった場合、アップロード
# 前に停止する。長尺パイプライン(todoapp_1/pipeline)の同名ガードと対になる措置。
# 名称ゆらぎに備え env YOUTUBE_EXPECTED_CHANNEL で上書き可。空文字にすると無効化。
EXPECTED_CHANNEL_TITLE = os.environ.get("YOUTUBE_EXPECTED_CHANNEL", "世界の雑学王")


class WrongChannelError(RuntimeError):
    """認可されたトークンが、投稿してはいけないチャンネルを指している。"""


def _assert_expected_channel(youtube) -> None:
    """認証されたチャンネル名が期待と違えば、投稿前に停止する。睡眠チャンネル等の
    別組織へショートを誤爆させないための最終ガード。"""
    exp = (EXPECTED_CHANNEL_TITLE or "").strip()
    if not exp:
        return  # ガード無効
    try:
        resp = youtube.channels().list(part="snippet", mine=True).execute()
        title = (resp.get("items") or [{}])[0].get("snippet", {}).get("title", "").strip()
    except Exception as e:  # noqa: BLE001  (チャンネル読取の一時失敗ではアップロードを止めない)
        print(f"  [guard] チャンネル確認をスキップ(読取失敗: {e})")
        return
    if exp not in title and title not in exp:
        raise WrongChannelError(
            f"投稿先チャンネルが期待と異なります(認証: 「{title}」／期待: 「{exp}」)。"
            f"FactSpark は『{exp}』専用です。睡眠チャンネル等の別組織へは投稿しません。"
            "この環境の YOUTUBE_REFRESH_TOKEN が正しいチャンネルの認可か確認してください"
            "(3点一致・『世界の雑学王』のGoogleアカウントで発行)。処理を中断しました。")
    print(f"  [guard] 投稿先チャンネル確認OK: 「{title}」")


def _get_credentials() -> Credentials:
    """認証情報を取得する。

    クラウド(無人実行): 環境変数 YOUTUBE_REFRESH_TOKEN / YOUTUBE_CLIENT_ID /
    YOUTUBE_CLIENT_SECRET があれば、それだけで認証情報を組み立てる(ブラウザ操作不要)。
    ローカル(従来): token.json / client_secret.json を使い、必要ならブラウザで再認証する。
    """
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    if refresh_token and client_id and client_secret:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=TOKEN_URI,
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )
        creds.refresh(Request())  # refresh_token からアクセストークンを取得
        return creds

    # --- ここから下は従来のローカル(ファイル)経路 ---
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET_FILE.exists():
                raise SystemExit(
                    f"エラー: {CLIENT_SECRET_FILE} が見つかりません。\n"
                    "Google Cloud ConsoleでダウンロードしたOAuthクライアント(デスクトップアプリ)の"
                    "JSONファイルを client_secret.json として配置してください。"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_FILE), SCOPES)
            creds = flow.run_local_server(port=0, open_browser=False)
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    return creds


def fetch_recent_titles(max_results: int = 250) -> list[str]:
    """このチャンネルの直近アップロード(予約投稿含む)動画のタイトル一覧を返す。

    ※参照範囲について: このチャンネルは1日に長尺・ショート・予告編で複数本を投稿するため、
    60件では約12日分しか遡れず、それ以前に扱った題材(例: 「ワニが涙を流す本当の理由」)を
    重複して選んでしまう。250件(≒40〜50日分)まで広げてネタ被り回避の精度を上げる。
    playlistItems.list は1ページ50件・1quota と安価なので範囲拡大の負荷は小さい。

    クラウドではリポジトリを毎回クローンし直すため topic_history.json による履歴の
    永続化ができない。その代わりに、YouTube側の実データ(直近の投稿タイトル)を都度
    取得して「ネタ被り回避(avoid_titles)」に使う。新しい順で返す。
    """
    creds = _get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    channels_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_playlist_id = (
        channels_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    )

    titles: list[str] = []
    page_token = None
    while len(titles) < max_results:
        resp = (
            youtube.playlistItems()
            .list(
                part="snippet",
                playlistId=uploads_playlist_id,
                maxResults=50,
                pageToken=page_token,
            )
            .execute()
        )
        titles.extend(item["snippet"]["title"] for item in resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return titles[:max_results]


def count_scheduled_future_videos() -> int:
    """このチャンネルの「予約投稿(private + publishAtが未来)」動画の本数を数える。

    2026-08-11: 1日の生成本数を5→10に増やすかどうかの判定に使う
    (「先にYouTube上に5本以上の予約投稿がある日だけ10本まで許容する」というユーザー指示)。
    アップロード直後の動画をカウントに含めるため、daily_routine.py はこの関数を
    ルーチン開始時(=その日まだ1本もアップロードしていない時点)に呼ぶこと。
    """
    creds = _get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    channels_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_playlist_id = (
        channels_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    )

    video_ids: list[str] = []
    page_token = None
    # 直近アップロード分だけ見れば十分(予約投稿は基本的に直近数日以内のものしかない)。
    # 念のため最大3ページ(150件)まで遡る。
    for _ in range(3):
        playlist_resp = (
            youtube.playlistItems()
            .list(
                part="contentDetails",
                playlistId=uploads_playlist_id,
                maxResults=50,
                pageToken=page_token,
            )
            .execute()
        )
        video_ids.extend(
            item["contentDetails"]["videoId"] for item in playlist_resp.get("items", [])
        )
        page_token = playlist_resp.get("nextPageToken")
        if not page_token:
            break

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    count = 0
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        videos_resp = youtube.videos().list(part="status", id=",".join(batch)).execute()
        for item in videos_resp.get("items", []):
            status = item["status"]
            publish_at = status.get("publishAt")
            if status.get("privacyStatus") == "private" and publish_at:
                publish_dt = datetime.datetime.strptime(
                    publish_at, "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=datetime.timezone.utc)
                if publish_dt > now_utc:
                    count += 1

    return count


def upload_video(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    publish_at: datetime.datetime,
) -> str:
    """動画を非公開でアップロードし、publish_atに自動公開されるよう予約する。動画IDを返す。"""
    creds = _get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    # 誤投稿ガード: 認証チャンネルが「世界の雑学王」でなければ、ここで停止する。
    _assert_expected_channel(youtube)

    if publish_at.tzinfo is None:
        publish_at = publish_at.astimezone()
    publish_at_utc = publish_at.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": CATEGORY_ID,
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at_utc,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _, response = request.next_chunk()

    return response["id"]


if __name__ == "__main__":
    # 初回のブラウザ認証専用実行: python youtube_upload.py
    _get_credentials()
    print(f"認証に成功しました。{TOKEN_FILE} を保存しました。")
