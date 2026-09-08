"""Which soundscape earns the most watching? Join the runlog to live figures.

The channel rotates through the five textures in ambient.py and keeps whichever
performs best. That decision needs three things the system did not have:

  * an even sample — the texture used to be chosen by hashing the title, which
    gives lumpy coverage; it is now strict round-robin from a committed counter
  * a record of which video got which texture — read from the 【…】 prefix on
    each published title. runlog.md was tried first and does not work: the
    scheduled containers have never once managed to push it, so the record
    never leaves the machine that is about to be deleted. The title is on
    YouTube, which is the only storage here that cannot be lost.
  * a fair comparison — raw view counts favour whatever was published first, so
    everything here is per-day-since-publish

    python3 compare_textures.py

One thing the ranking now measures that it did not before: each title carries
its soundscape as a 【…】 prefix, so a viewer chooses between 「【波の音】…」 and
「【音楽】…」 without having heard either. The label and the audio are therefore
not separable here. That is the right thing to measure — nobody hears a video
before clicking it, so the label is the decision — but it means a win belongs to
the pair, and swapping the wording of a label invalidates the comparison so far.

Read the sample size before the ranking. Two ambient videos a week across five
textures is one full cycle every two and a half weeks, and view counts on a
young channel are dominated by which video the algorithm happened to test. The
script says how confident the current data allows you to be, and will say
"まだ判断できません" for as long as that is the honest answer.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone

from ambient import TEXTURES

MIN_PER_TEXTURE = 3     # below this, differences are noise on a channel this size


def rows(yt) -> list[tuple[str, str]]:
    """(texture, video_id) for every published video carrying a soundscape label."""
    from ambient import TEXTURE_LABEL
    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    items, page = [], None
    while True:
        r = yt.playlistItems().list(part="snippet", playlistId=uploads,
                                    maxResults=50, pageToken=page).execute()
        items += r["items"]
        page = r.get("nextPageToken")
        if not page:
            break
    by_marker = {f"【{lab}】": tex for tex, lab in TEXTURE_LABEL.items()}
    out = []
    for it in items:
        title = it["snippet"]["title"]
        for marker, tex in by_marker.items():
            if title.startswith(marker):
                out.append((tex, it["snippet"]["resourceId"]["videoId"]))
                break
    return out


def main() -> None:
    from youtube_upload import _service
    yt = _service()
    pairs = rows(yt)
    if not pairs:
        print("件名に【…】が付いた動画がまだありません。")
        print("音風景のラベルは 2026-09-08 の回から付き始めます。")
        return
    ids = [v for _, v in pairs]
    stats = {}
    for i in range(0, len(ids), 50):
        for it in yt.videos().list(part="snippet,statistics",
                                   id=",".join(ids[i:i + 50])).execute()["items"]:
            pub = datetime.fromisoformat(it["snippet"]["publishedAt"].replace("Z", "+00:00"))
            days = max(1.0, (datetime.now(timezone.utc) - pub).total_seconds() / 86400)
            stats[it["id"]] = (int(it["statistics"].get("viewCount", 0)), days)

    by: dict[str, list[float]] = {t: [] for t in TEXTURES}
    print(f"{'音風景':<8}{'動画':>4}{'総視聴':>7}{'1日あたり':>10}")
    for texture, vid in pairs:
        if vid in stats:
            views, days = stats[vid]
            by[texture].append(views / days)
    for t in TEXTURES:
        v = by[t]
        if v:
            total = sum(stats[vid][0] for tex, vid in pairs if tex == t and vid in stats)
            print(f"{t:<8}{len(v):>4}{total:>7}{statistics.mean(v):>10.2f}")
        else:
            print(f"{t:<8}{0:>4}{'-':>7}{'-':>10}")

    ready = [t for t in TEXTURES if len(by[t]) >= MIN_PER_TEXTURE]
    short = [t for t in TEXTURES if len(by[t]) < MIN_PER_TEXTURE]
    print()
    if len(ready) < 2:
        need = sum(MIN_PER_TEXTURE - len(by[t]) for t in TEXTURES)
        print(f"まだ判断できません。各音風景 {MIN_PER_TEXTURE}本ずつ必要で、あと {need}本 "
              f"（週2本のペースで約 {need / 2:.0f}週間）です。")
        print("不足:", "、".join(f"{t}({len(by[t])}本)" for t in short))
        return
    best = max(ready, key=lambda t: statistics.mean(by[t]))
    worst = min(ready, key=lambda t: statistics.mean(by[t]))
    gap = statistics.mean(by[best]) / max(1e-9, statistics.mean(by[worst]))
    print(f"暫定1位: {best}（1日あたり {statistics.mean(by[best]):.2f}回）")
    if gap < 1.5:
        print(f"ただし最下位 {worst} との差は {gap:.2f}倍。この規模では差とは言えません。")
    else:
        print(f"最下位 {worst} の {gap:.2f}倍。差として読める水準です。")
    if short:
        print("未達:", "、".join(f"{t}({len(by[t])}本)" for t in short))


if __name__ == "__main__":
    main()
