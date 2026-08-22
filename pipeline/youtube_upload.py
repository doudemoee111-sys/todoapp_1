"""Upload a video to YouTube via the Data API v3 using an OAuth refresh token.

Auth env: YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN.
The video is uploaded as `private` with a `publishAt` timestamp so YouTube
publishes it automatically at the scheduled time (JST peak hour).
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

JST = timezone(timedelta(hours=9))
_SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
           "https://www.googleapis.com/auth/youtube"]


def _service():
    # Note: do NOT pass `scopes` on refresh — Google returns invalid_scope if the
    # requested scopes differ from what the refresh token was originally granted.
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def check_auth() -> str:
    """Verify the YouTube OAuth credential actually works, without uploading.

    Forces a token refresh (channels.list triggers it) so an expired/revoked
    refresh token fails here cheaply, instead of after ~15 min of video build.
    Returns the authorized channel's title on success.
    """
    yt = _service()
    try:
        resp = yt.channels().list(part="snippet", mine=True).execute()
    except RefreshError as e:
        raise RuntimeError(
            f"YouTube 認証に失敗しました（{e}）。YOUTUBE_REFRESH_TOKEN が失効/取り消し済み、"
            "または CLIENT_ID/SECRET と不一致の可能性があります。OAuth Playground で再発行し、"
            "OAuth同意画面を『本番』に公開してから、環境変数を上書きしてください。") from e
    items = resp.get("items", [])
    if not items:
        raise RuntimeError(
            "認証は通りましたが、このアカウントに YouTube チャンネルが見つかりません。"
            "投稿先チャンネルの Google アカウントで認可し直してください。")
    title = items[0]["snippet"]["title"]
    _assert_expected_channel(title)
    return title


class WrongChannelError(RuntimeError):
    """The authorized token points at a channel this pipeline must NOT post to."""


def _assert_expected_channel(title: str) -> None:
    """Guard against posting to the wrong channel. The sleep channel is a
    SEPARATE org/project and must never receive this pipeline's videos. If the
    token authorizes anything other than the expected channel, stop hard."""
    from config import EXPECTED_CHANNEL_TITLE
    exp = (EXPECTED_CHANNEL_TITLE or "").strip()
    if not exp:
        return  # guard disabled
    t = (title or "").strip()
    if exp not in t and t not in exp:
        raise WrongChannelError(
            f"投稿先チャンネルが期待と異なります（認証されたチャンネル: 「{t}」／"
            f"期待: 「{exp}」）。この自動化は『{exp}』専用です。睡眠チャンネル等の別組織へは"
            "投稿しません。env_01H7 の YOUTUBE_REFRESH_TOKEN が正しいチャンネルの認可か確認して"
            "ください（3点一致・『{exp}』のGoogleアカウントで再発行）。処理を中断しました。")


def post_comment(video_id: str, text: str) -> bool:
    """Post a top-level comment on the video as the channel owner (best-effort).

    Used to place the long-form link under a teaser short. Pinning must be done
    manually in YouTube Studio — the Data API has no pin endpoint. Requires the
    youtube.force-ssl scope; if the token lacks it this fails gracefully and the
    description link still carries the funnel.
    """
    try:
        yt = _service()
        yt.commentThreads().insert(
            part="snippet",
            body={"snippet": {"videoId": video_id,
                              "topLevelComment": {"snippet": {"textOriginal": text}}}},
        ).execute()
        print("  [comment] 本編リンクのコメントを投稿しました（ピン留めはStudioで手動）")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  [comment] コメント投稿はスキップ（スコープ不足の可能性: {e}）。概要欄リンクは有効です。")
        return False


def fetch_recent_titles(max_results: int = 40) -> list[str]:
    """Titles of the channel's most recent videos (newest first), scheduled/
    private uploads included.

    Used to steer topic selection away from themes we just covered. Every run
    clones the repo fresh, so there is no local history to trust and pushing a
    history file back fails from the unprivileged scheduled sessions — YouTube
    itself is the durable source of truth (the shorts pipeline uses the same
    trick). Best-effort: returns [] on any error so generation never blocks on
    this read.
    """
    try:
        yt = _service()
        ch = yt.channels().list(part="contentDetails", mine=True).execute()
        items = ch.get("items", [])
        if not items:
            return []
        uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        titles: list[str] = []
        req = yt.playlistItems().list(part="snippet", playlistId=uploads, maxResults=50)
        while req is not None and len(titles) < max_results:
            resp = req.execute()
            for it in resp.get("items", []):
                t = (it.get("snippet") or {}).get("title")
                if t:
                    titles.append(t)
            req = yt.playlistItems().list_next(req, resp)
        return titles[:max_results]
    except Exception as e:  # noqa: BLE001
        print(f"  [dedup] 直近タイトルの取得に失敗（重複回避はスキップ）: {e}")
        return []


def ensure_playlist(title: str, description: str = "") -> str | None:
    """Return the id of the channel's playlist named `title`, creating it if
    absent. Playlists chain our videos into a binge session — higher session
    watch-time is a strong signal for the suggested-video algorithm, so each new
    upload is appended to its genre playlist. Best-effort: returns None on error."""
    try:
        yt = _service()
        req = yt.playlists().list(part="snippet", mine=True, maxResults=50)
        while req is not None:
            resp = req.execute()
            for pl in resp.get("items", []):
                if (pl.get("snippet") or {}).get("title") == title:
                    return pl["id"]
            req = yt.playlists().list_next(req, resp)
        created = yt.playlists().insert(
            part="snippet,status",
            body={"snippet": {"title": title[:150], "description": description[:5000]},
                  "status": {"privacyStatus": "public"}},
        ).execute()
        print(f"  [playlist] 新規プレイリスト作成: 「{title}」")
        return created["id"]
    except Exception as e:  # noqa: BLE001
        print(f"  [playlist] プレイリスト準備に失敗（回遊設定はスキップ）: {e}")
        return None


def add_to_playlist(video_id: str, playlist_id: str) -> bool:
    """Append a video to a playlist (best-effort)."""
    if not playlist_id:
        return False
    try:
        yt = _service()
        yt.playlistItems().insert(
            part="snippet",
            body={"snippet": {"playlistId": playlist_id,
                              "resourceId": {"kind": "youtube#video", "videoId": video_id}}},
        ).execute()
        print(f"  [playlist] 動画をプレイリストに追加（回遊導線）")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  [playlist] プレイリスト追加に失敗: {e}")
        return False


def next_publish_at(hour_jst: int, min_lead_hours: int = 3) -> datetime:
    """Next occurrence of hour_jst (JST) that is at least min_lead_hours from now.

    YouTube requires scheduled times to be in the future; we also leave lead time
    so generation/upload completes well before publication.
    """
    now = datetime.now(JST)
    cand = now.replace(hour=hour_jst, minute=0, second=0, microsecond=0)
    while cand <= now + timedelta(hours=min_lead_hours):
        cand += timedelta(days=1)
    return cand


def upload_video(video_path: str | Path, title: str, description: str, tags: list[str],
                 category_id: str, publish_at_jst: datetime | None = None,
                 thumbnail_path: str | Path | None = None,
                 privacy: str = "private") -> str:
    yt = _service()
    # Hard channel guard: never upload to the wrong channel (別組織の睡眠チャンネル等)。
    try:
        me = yt.channels().list(part="snippet", mine=True).execute()
        _assert_expected_channel(me["items"][0]["snippet"]["title"])
    except WrongChannelError:
        raise
    except Exception as e:  # noqa: BLE001  (channel read failed — do not block upload on a transient read error)
        print(f"  [guard] チャンネル確認をスキップ（読み取り失敗: {e}）")
    status_body = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    # publishAt (予約公開) は private の時だけ有効。public/unlisted で即時公開する
    # 場合や publish_at 未指定の場合は付けない(付けると API が弾く/無視するため)。
    publish_at_utc = None
    if publish_at_jst is not None and privacy == "private":
        publish_at_utc = publish_at_jst.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        status_body["publishAt"] = publish_at_utc
    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": category_id,
        },
        "status": status_body,
    }
    media = MediaFileUpload(str(video_path), mimetype="video/*", resumable=True, chunksize=8 * 1024 * 1024)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"  [upload] {int(status.progress() * 100)}%")
    video_id = resp["id"]
    print(f"  [upload] done videoId={video_id} privacy={privacy} publishAt={publish_at_utc or '(即時)'}")

    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumbnail_path))).execute()
            print("  [upload] thumbnail set")
        except Exception as e:  # noqa: BLE001
            print(f"  [upload] thumbnail failed: {e}")
    return video_id
