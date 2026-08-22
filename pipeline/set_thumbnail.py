#!/usr/bin/env python3
"""Set (or retry) the custom thumbnail on an already-uploaded video.

The upload step sets the thumbnail inline, but that call fails with a 403
(youtube.thumbnail / forbidden) on channels that have not completed phone
verification. That failure is deliberately non-fatal there — the video is
already uploaded and scheduled, and losing it over a thumbnail would be worse.

This lets you finish the job afterwards, once the channel is verified, without
rebuilding the video:

    python3 set_thumbnail.py kaa5EUPWEvw output/sleep_20260822_020307/thumbnail.png

With no image argument it looks for thumbnail.png next to the newest result.json
that matches the given video id.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from googleapiclient.http import MediaFileUpload

from youtube_upload import _service, current_channel

HERE = Path(__file__).resolve().parent


def _find_thumbnail(video_id: str) -> Path | None:
    """Locate the thumbnail belonging to video_id under output/."""
    for result in sorted(HERE.glob("output/*/result.json"), reverse=True):
        try:
            if json.loads(result.read_text()).get("video_id") != video_id:
                continue
        except (OSError, ValueError):
            continue
        candidate = result.parent / "thumbnail.png"
        if candidate.exists():
            return candidate
    return None


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(f"usage: {Path(sys.argv[0]).name} <videoId> [thumbnail.png]")

    video_id = sys.argv[1]

    if len(sys.argv) >= 3:
        image = Path(sys.argv[2])
    else:
        found = _find_thumbnail(video_id)
        if found is None:
            sys.exit(f"サムネイル画像が見つかりません（output/ 配下に {video_id} の result.json なし）。"
                     f"パスを2つめの引数で指定してください。")
        image = found

    if not image.exists():
        sys.exit(f"サムネイル画像がありません: {image}")

    channel = current_channel()
    print(f"[thumbnail] 投稿先チャンネル: 「{channel['title']}」({channel['id']})")
    print(f"[thumbnail] videoId={video_id}")
    print(f"[thumbnail] 画像: {image} ({image.stat().st_size:,} bytes)")

    try:
        _service().thumbnails().set(
            videoId=video_id, media_body=MediaFileUpload(str(image))
        ).execute()
    except Exception as e:  # noqa: BLE001 — surface the API's own message verbatim
        sys.exit(f"[thumbnail] 失敗: {e}\n"
                 "403 forbidden の場合はチャンネルの電話番号認証が未完了です "
                 "（https://www.youtube.com/verify）。認証は反映まで数分かかることがあります。")

    print(f"[thumbnail] OK — 設定しました https://youtu.be/{video_id}")


if __name__ == "__main__":
    main()
