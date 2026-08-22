#!/usr/bin/env python3
"""Rebuild an uploaded video's description and tags without re-rendering it.

The description gained a chapter list and links to sibling videos, and the tag
prompt was rewritten to produce search phrases rather than bare words. Videos
uploaded before that keep the old metadata, and re-running the whole pipeline to
fix text would spend ~26 minutes and a fresh set of image credits to produce a
different video.

    python3 refresh_metadata.py PtHX7a2Jq7k          # preview only
    python3 refresh_metadata.py PtHX7a2Jq7k --write  # apply

Chapter times come from segments.json when the run saved one. Older runs did not,
so the timings are re-measured by synthesizing the same narration through the
same code path; the total is checked against the published audio and the chapter
list is dropped if it does not line up, rather than publishing timestamps that
point at the wrong moment.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import config
from config import GENRES
from run import _description
from youtube_upload import _service, current_channel, fetch_recent_videos

HERE = Path(__file__).resolve().parent
DRIFT_TOLERANCE = 0.03      # 3% — beyond this the timings are not the published ones


def _work_dir(video_id: str) -> Path:
    for result in sorted(HERE.glob("output/*/result.json"), reverse=True):
        try:
            if json.loads(result.read_text()).get("video_id") == video_id:
                return result.parent
        except (OSError, ValueError):
            continue
    sys.exit(f"output/ に {video_id} の result.json が見つかりません。")


def _segments(work: Path, narration: str) -> list[tuple[str, float, float]]:
    saved = work / "segments.json"
    if saved.exists():
        data = json.loads(saved.read_text())
        print(f"[refresh] segments.json から {len(data)} 単位の実測時刻を読みました")
        return [(d["text"], d["start"], d["end"]) for d in data]

    from tts import synthesize_timed, audio_duration
    published = work / "narration.mp3"
    print("[refresh] segments.json が無いため、同じ経路で時刻を再測定します…")
    with tempfile.TemporaryDirectory() as tmp:
        _, segs = synthesize_timed(narration, Path(tmp) / "measure.mp3")
    if published.exists() and segs:
        want, got = audio_duration(published), segs[-1][2]
        drift = abs(got - want) / want
        print(f"[refresh] 再測定 {got:.1f}s / 公開済み {want:.1f}s （ずれ {drift*100:.1f}%）")
        if drift > DRIFT_TOLERANCE:
            print("[refresh] ずれが大きすぎます。目次は付けません。")
            return []
    return segs


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    write = "--write" in sys.argv[1:]
    if len(args) != 1:
        sys.exit(f"usage: {Path(sys.argv[0]).name} <videoId> [--write]")
    video_id = args[0]

    yt = _service()
    channel = current_channel()
    print(f"[refresh] チャンネル: 「{channel['title']}」")

    resp = yt.videos().list(part="snippet", id=video_id).execute()
    items = resp.get("items") or []
    if not items:
        sys.exit(f"動画が見つかりません: {video_id}")
    snippet = items[0]["snippet"]

    work = _work_dir(video_id)
    pkg = json.loads((work / "script.json").read_text())
    genre = GENRES[json.loads((work / "result.json").read_text())["genre"]]
    print(f"[refresh] 素材: {work.name}")

    segs = _segments(work, pkg["narration"])
    related = [(t, v) for t, v in fetch_recent_videos(4) if v != video_id][:3]
    description = _description(genre, pkg, segs, related)

    # script.json holds the tags the old prompt produced — bare words like
    # 「リラックス」that nobody types into search. Regenerate them through the
    # rewritten prompt so a refreshed video matches a newly generated one.
    tags = pkg.get("tags") or snippet.get("tags") or []
    if "--keep-tags" not in sys.argv[1:]:
        from llm_script import _desc_and_tags
        _, fresh = _desc_and_tags(genre, snippet["title"], pkg["narration"])
        if fresh:
            tags = fresh

    print("\n--- 新しい概要欄 ---")
    print(description)
    print("--- タグ ---")
    print("  " + " / ".join(tags))
    print(f"\n概要欄 {len(description)} 文字 / タグ {len(tags)} 個")

    if not write:
        print("\n[refresh] プレビューのみ。適用するには --write を付けてください。")
        return

    # videos.update replaces the whole snippet part: title and categoryId must be
    # carried over or they are cleared.
    yt.videos().update(part="snippet", body={
        "id": video_id,
        "snippet": {
            "title": snippet["title"],
            "categoryId": snippet["categoryId"],
            "description": description,
            "tags": tags,
            "defaultLanguage": snippet.get("defaultLanguage", "ja"),
        },
    }).execute()

    # Read-after-write is not immediately consistent here: the first read back
    # returns the previous description even though the update succeeded, which
    # looked like a failed write on a video that had in fact been updated.
    import time
    for attempt in range(5):
        after = yt.videos().list(part="snippet", id=video_id).execute()["items"][0]["snippet"]
        if after.get("description") == description:
            print(f"\n[refresh] OK — 更新しました https://youtu.be/{video_id}")
            return
        if attempt < 4:
            time.sleep(2 ** attempt)
    sys.exit("[refresh] 反映が確認できませんでした。YouTube Studio で概要欄を確認してください"
             "（更新自体は成功している場合があります）。")


if __name__ == "__main__":
    main()
