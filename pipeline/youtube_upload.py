"""Upload a video to YouTube via the Data API v3 using an OAuth refresh token.

Auth env: YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN.
Optional: YOUTUBE_EXPECTED_CHANNEL_ID pins the destination channel, so a token
minted for the wrong Google account can never publish to this channel.
The video is uploaded as `private` with a `publishAt` timestamp so YouTube
publishes it automatically at the scheduled time (JST peak hour).
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import OperatorError
from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

JST = timezone(timedelta(hours=9))
_SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
           "https://www.googleapis.com/auth/youtube"]


def _env(name: str) -> str:
    """Read a credential, tolerating the whitespace a copy-paste leaves behind.

    A secret pasted into a web form picks up a stray newline or trailing space
    far more often than it picks up a wrong character, and Google rejects both
    the same way (invalid_client), so the error never points at the real cause.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        raise OperatorError(
            f"{name} が未設定です。クラウド環境の環境変数に設定してください。"
            "CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN は、必ず同じ1つの"
            "OAuthクライアントから発行した3点セットを使います。")
    return raw.strip()


def expected_channel_id() -> str:
    """The channel this pipeline is pinned to, or "" when unpinned."""
    return (os.environ.get("YOUTUBE_EXPECTED_CHANNEL_ID") or "").strip()


# Google reports every credential problem as one of a handful of OAuth codes,
# and the fix differs sharply between them — spelling each one out here turns a
# generic "認証に失敗しました" into the single next action to take.
_AUTH_HINTS = {
    "invalid_client": (
        "CLIENT_ID と CLIENT_SECRET の組み合わせが Google に拒否されました"
        "（シークレットの誤り／無効化済み／クライアント削除済み）。"
        "Google Cloud Console で OAuth クライアントを作り直し、3点セットを取り直してください。"),
    "unauthorized_client": (
        "REFRESH_TOKEN が、この CLIENT_ID とは別のクライアントで発行されています。"
        "OAuth Playground の⚙で『Use your own OAuth credentials』に自分の ID/シークレットを"
        "貼ってから、トークンを取り直してください。"),
    "invalid_grant": (
        "REFRESH_TOKEN が失効/取り消し済みです。OAuth同意画面が『テスト中』のままだと"
        "7日で失効します。『本番』に公開してからトークンを再発行してください。"),
    "invalid_scope": (
        "リフレッシュ時に、付与済みと異なるスコープが要求されました。"
        "youtube.upload と youtube を付けてトークンを再発行してください。"),
}


def _auth_error(e: RefreshError) -> OperatorError:
    detail = str(e)
    for code, hint in _AUTH_HINTS.items():
        if code in detail:
            return OperatorError(f"YouTube 認証に失敗しました [{code}] {hint}（原文: {detail}）")
    return OperatorError(
        f"YouTube 認証に失敗しました: {detail}。CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN の"
        "3点が同一クライアント由来か確認してください。")


def _service():
    # Note: do NOT pass `scopes` on refresh — Google returns invalid_scope if the
    # requested scopes differ from what the refresh token was originally granted.
    creds = Credentials(
        token=None,
        refresh_token=_env("YOUTUBE_REFRESH_TOKEN"),
        client_id=_env("YOUTUBE_CLIENT_ID"),
        client_secret=_env("YOUTUBE_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _authorized_channel() -> tuple[str, str]:
    """(title, channelId) of the channel this credential actually controls.

    channels.list forces a token refresh, so an expired or mismatched
    credential fails here — cheaply — instead of after a ~15 min video build.
    """
    yt = _service()
    try:
        resp = yt.channels().list(part="snippet", mine=True).execute()
    except RefreshError as e:
        raise _auth_error(e) from e
    items = resp.get("items", [])
    if not items:
        raise OperatorError(
            "認証は通りましたが、このアカウントに YouTube チャンネルが見つかりません。"
            "チャンネルがブランドアカウントの場合、認可時のアカウント選択で"
            "個人アカウントではなく対象チャンネルを選ぶ必要があります。")
    return items[0]["snippet"]["title"], items[0]["id"]


def assert_expected_channel(title: str, channel_id: str) -> None:
    """Refuse to act when the credential points at some other channel.

    Publishing to the wrong channel is not undone by deleting the video: the
    recommender has already been told who that channel is for. So this is a
    hard stop, re-checked immediately before every upload rather than only at
    --check-auth time — the token can be swapped between the two.
    """
    want = expected_channel_id()
    if want and want != channel_id:
        raise OperatorError(
            f"投稿先チャンネルが一致しません。期待 {want} / 実際 {channel_id}（「{title}」）。"
            "別の Google アカウント（またはブランドアカウント）で認可された可能性があります。"
            "投稿先を変えたのであれば YOUTUBE_EXPECTED_CHANNEL_ID を更新してください。")


def check_auth() -> tuple[str, str]:
    """Verify the credential works and, when pinned, targets the right channel.

    Returns (title, channelId) of the authorized channel.
    """
    title, channel_id = _authorized_channel()
    assert_expected_channel(title, channel_id)
    return title, channel_id


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
    # Last gate before the irreversible part: verify the destination channel
    # here too, not just at --check-auth, so a run that started hours earlier
    # with a different token can't publish to the wrong place.
    if expected_channel_id():
        assert_expected_channel(*_authorized_channel())
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
