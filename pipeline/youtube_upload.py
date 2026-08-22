"""Upload a video to YouTube via the Data API v3 using an OAuth refresh token.

Auth env: YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN.
The video is uploaded as `private` with a `publishAt` timestamp so YouTube
publishes it automatically at the scheduled time (JST peak hour).
"""
from __future__ import annotations
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
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


class ChannelMismatch(RuntimeError):
    """The credential authorises a different channel than this run expects."""


def current_channel() -> dict:
    """Verify the OAuth credential works and report which channel it controls.

    Forces a token refresh (channels.list triggers it) so an expired/revoked
    refresh token fails here cheaply, instead of after ~15 min of video build.
    Returns {"id": ..., "title": ...}.
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
    return {"id": items[0]["id"], "title": items[0]["snippet"]["title"]}


def expected_channel_id(genre: dict | None = None) -> tuple[str, str]:
    """Which channel this run is allowed to post to, and where that came from.

    Two sources, and the genre wins:

    * ``genre["channel_id"]`` in config.py — travels with `git pull`, cannot be
      forgotten when an environment is set up, and shows in a diff.
    * ``EXPECTED_CHANNEL_ID`` in the environment — the fallback for genres that
      have not declared one yet.

    Returns ("", "") when neither is set. If both are set and disagree, that is
    a configuration error rather than a credential error, and it is raised as
    such: silently trusting either one would hide a real mistake.
    """
    from_genre = (genre or {}).get("channel_id") or ""
    from_env = os.environ.get("EXPECTED_CHANNEL_ID", "").strip()
    if from_genre and from_env and from_genre != from_env:
        raise ChannelMismatch(
            "設定が矛盾しています。アップロードを中止しました。\n"
            f"  config.py のジャンル定義  : {from_genre}\n"
            f"  環境変数 EXPECTED_CHANNEL_ID: {from_env}\n"
            "どちらかが誤りです。この環境で動かすべきチャンネルを確認し、片方に揃えてください。")
    if from_genre:
        return from_genre, "config.py のジャンル定義"
    if from_env:
        return from_env, "環境変数 EXPECTED_CHANNEL_ID"
    return "", ""


def assert_expected_channel(channel: dict | None = None,
                            genre: dict | None = None) -> dict:
    """Refuse to run when the credential points at the wrong channel.

    Several channels are driven from the same `pipeline/` code, each needing
    its own environment with its own YOUTUBE_* triple. Nothing used to notice
    when those got crossed — a shared environment whose token had been
    overwritten would happily upload one channel's video to the other, and the
    mistake only became visible once the upload was already scheduled. That
    happened twice.

    Relying on an environment variable to prevent it was not enough: the
    variable has to be remembered at setup time, and it was not. So a genre can
    now name its channel in config.py, where it cannot be forgotten. When
    either source names a channel the check is mandatory and the run aborts
    before uploading.

    The channel *id* is what gets pinned, never the title — a channel can be
    renamed at any moment (this one was), and a rename must not break
    production.
    """
    channel = channel or current_channel()
    expected, source = expected_channel_id(genre)
    if not expected:
        return channel
    if expected != channel["id"]:
        raise ChannelMismatch(
            "投稿先チャンネルが想定と違います。アップロードを中止しました。\n"
            f"  想定 ({source}): {expected}\n"
            f"  実際に認証されたチャンネル : {channel['id']}（「{channel['title']}」）\n"
            "この環境の YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN が、"
            "別チャンネル用の値になっている可能性があります。\n"
            "1つの環境は1チャンネル専用です。共有せず、チャンネルごとに環境を分けてください"
            "（pipeline/assets/CHANNELS.md を参照）。")
    return channel


def check_auth() -> str:
    """Back-compat wrapper: returns the authorised channel's title."""
    return current_channel()["title"]


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


def fetch_recent_videos(max_results: int = 5) -> list[tuple[str, str]]:
    """(title, videoId) of the channel's most recent uploads, newest first.

    Feeds the "other videos" block in the description. Best-effort like
    fetch_recent_titles: an empty list just means the block is omitted, never a
    failed run.
    """
    try:
        yt = _service()
        items = yt.channels().list(part="contentDetails", mine=True).execute().get("items", [])
        if not items:
            return []
        uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        # Over-fetch: unlisted/private uploads are dropped below, and a replaced
        # video that is now plain private would otherwise become a dead link in
        # every later description.
        resp = yt.playlistItems().list(part="contentDetails", playlistId=uploads,
                                       maxResults=max(max_results * 4, 10)).execute()
        ids = [(it.get("contentDetails") or {}).get("videoId")
               for it in resp.get("items", [])]
        ids = [i for i in ids if i]
        if not ids:
            return []
        det = yt.videos().list(part="snippet,status", id=",".join(ids[:50])).execute()
        out = []
        for v in det.get("items", []):
            st, sn = v.get("status", {}), v.get("snippet", {})
            # public now, or private with a publishAt (it will be public shortly)
            if st.get("privacyStatus") != "public" and not st.get("publishAt"):
                continue
            if sn.get("title"):
                out.append((sn["title"], v["id"]))
            if len(out) >= max_results:
                break
        return out
    except Exception as e:  # noqa: BLE001
        print(f"  [related] 既存動画の取得をスキップ: {e}")
        return []


def add_to_playlist(video_id: str, playlist_title: str, description: str = "") -> str | None:
    """Put the video in the channel's playlist of this name, creating it once.

    A playlist is the most direct suggested-video lever available from the API:
    it gives YouTube an explicit "these belong together" signal and gives a
    finishing viewer a next video on this channel rather than someone else's.

    Looked up by title rather than a stored id because every scheduled run
    starts from a fresh container with no local state. Best-effort: a failure
    here must not undo an upload that already succeeded.
    """
    try:
        yt = _service()
        playlist_id = None
        req = yt.playlists().list(part="snippet", mine=True, maxResults=50)
        while req is not None and playlist_id is None:
            resp = req.execute()
            for pl in resp.get("items", []):
                if (pl.get("snippet") or {}).get("title") == playlist_title:
                    playlist_id = pl["id"]
                    break
            req = yt.playlists().list_next(req, resp)

        if playlist_id is None:
            created = yt.playlists().insert(part="snippet,status", body={
                "snippet": {"title": playlist_title, "description": description},
                "status": {"privacyStatus": "public"},
            }).execute()
            playlist_id = created["id"]
            print(f"  [playlist] 再生リストを新規作成: 「{playlist_title}」")

        # A playlist created moments ago is not consistently readable yet: the
        # first insert after creation returns 409 SERVICE_UNAVAILABLE. That is
        # exactly the path the very first scheduled run takes, so retry rather
        # than silently leaving the opening video out of its own series.
        for attempt in range(4):
            try:
                yt.playlistItems().insert(part="snippet", body={
                    "snippet": {"playlistId": playlist_id,
                                "resourceId": {"kind": "youtube#video", "videoId": video_id}},
                }).execute()
                break
            except HttpError as e:
                if e.resp.status != 409 or attempt == 3:
                    raise
                wait = 2 ** attempt
                print(f"  [playlist] 反映待ち（409）… {wait}s 後に再試行 ({attempt+1}/3)")
                time.sleep(wait)
        print(f"  [playlist] 「{playlist_title}」に追加しました")
        return playlist_id
    except Exception as e:  # noqa: BLE001
        print(f"  [playlist] 追加をスキップ（本編は投稿済み）: {e}")
        return None


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
                 category_id: str, publish_at_jst: datetime,
                 thumbnail_path: str | Path | None = None,
                 privacy: str = "private") -> str:
    yt = _service()
    publish_at_utc = publish_at_jst.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "publishAt": publish_at_utc,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(str(video_path), mimetype="video/*", resumable=True, chunksize=8 * 1024 * 1024)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"  [upload] {int(status.progress() * 100)}%")
    video_id = resp["id"]
    print(f"  [upload] done videoId={video_id} publishAt={publish_at_utc}")

    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumbnail_path))).execute()
            print("  [upload] thumbnail set")
        except Exception as e:  # noqa: BLE001
            print(f"  [upload] thumbnail failed: {e}")
    return video_id
