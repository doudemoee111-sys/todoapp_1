#!/usr/bin/env python3
"""Cancel a video's scheduled publication, leaving it private.

Needed when a scheduled video is replaced: the old upload still carries a
publishAt and YouTube will publish it at that time regardless of whatever went
up in its place. Clearing publishAt while keeping privacyStatus=private stops
that without deleting anything, so the video can be re-scheduled or published by
hand later if the replacement turns out worse.

    python3 unschedule.py kaa5EUPWEvw

Prints the video's title and current state and asks for confirmation before
writing, unless --yes is given. Refuses to touch a video on a channel other than
the one this environment authenticates as.
"""
from __future__ import annotations

import sys

from youtube_upload import _service, current_channel


def _get(yt, video_id: str) -> dict:
    resp = yt.videos().list(part="snippet,status", id=video_id).execute()
    items = resp.get("items") or []
    if not items:
        sys.exit(f"動画が見つかりません（このチャンネルの動画ではない可能性があります）: {video_id}")
    return items[0]


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--yes"]
    assume_yes = "--yes" in sys.argv[1:]
    if len(args) != 1:
        sys.exit(f"usage: {sys.argv[0].split('/')[-1]} <videoId> [--yes]")
    video_id = args[0]

    yt = _service()
    channel = current_channel()
    print(f"[unschedule] チャンネル: 「{channel['title']}」({channel['id']})")

    v = _get(yt, video_id)
    status, snippet = v["status"], v["snippet"]
    publish_at = status.get("publishAt")
    print(f"[unschedule] タイトル : {snippet['title']}")
    print(f"[unschedule] 現在の状態: privacyStatus={status['privacyStatus']}"
          f" / publishAt={publish_at or '(なし)'}")

    if not publish_at:
        print("[unschedule] 予約公開は設定されていません。変更は不要です。")
        return

    if not assume_yes:
        try:
            if input("[unschedule] この予約公開を取り消しますか？ [y/N] ").strip().lower() != "y":
                sys.exit("[unschedule] 中止しました。")
        except EOFError:
            sys.exit("[unschedule] 確認できないため中止しました（非対話環境では --yes を付けてください）。")

    # videos.update replaces the whole status part, so omitting publishAt clears
    # it. privacyStatus stays private: the video keeps existing, just unscheduled.
    yt.videos().update(part="status", body={
        "id": video_id,
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": status.get("selfDeclaredMadeForKids", False),
        },
    }).execute()

    after = _get(yt, video_id)["status"]
    print(f"[unschedule] 変更後  : privacyStatus={after['privacyStatus']}"
          f" / publishAt={after.get('publishAt') or '(なし)'}")
    if after.get("publishAt"):
        sys.exit("[unschedule] 予約公開が残っています。YouTube Studio で確認してください。")
    print(f"[unschedule] OK — 予約公開を取り消しました https://youtu.be/{video_id}")


if __name__ == "__main__":
    main()
