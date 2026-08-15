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
