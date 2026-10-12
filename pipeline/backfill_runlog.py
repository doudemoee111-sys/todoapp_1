"""Rebuild the runlog rows that a scheduled run could not push.

`run.py` appends a row and pushes it. The push has never once succeeded from a
scheduled container — the only runlog commits in the history came from manual
runs — so the file, which exists to be the evidence that a run happened, is
missing exactly the runs nobody watched. By 2026-10-12 it was three videos
behind, and the gap grows by three a week.

The channel knows what the file does not: every upload is there, with its
length, its title and its soundscape label. So the rows can be reconstructed —
not completely, but in the part that matters, which is "a video exists for that
slot". What cannot be recovered is marked rather than guessed:

  * 段階 reads **復元** (reconstructed), never 完了, so no one mistakes a row
    this wrote for a row a run wrote.
  * 所要 and 切口 are left as "-". The elapsed time and the topic axis exist
    only inside the container that is gone.
  * 日時 is the publish time, not the generation time. For a video that is
    already public, snippet.publishedAt IS the publish time; the upload time it
    held while scheduled is overwritten. Stating 21:00 as though it were the
    run's start would be a small lie in a file whose whole job is to be true.

Run from the weekly review. Idempotent: a video already in the file is skipped,
so running it twice costs two API calls and changes nothing.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone

import config

RUNLOG = config.ASSETS_DIR / "runlog.md"
JST = timezone(timedelta(hours=9))
_ISO_DUR = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?")


def _minutes(iso: str) -> int:
    m = _ISO_DUR.match(iso or "")
    if not m:
        return 0
    h, mi, s = (float(x) if x else 0.0 for x in m.groups())
    return int(h * 60 + mi + s / 60)


def _published() -> list[dict]:
    from youtube_upload import _service
    yt = _service()
    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, page = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=uploads,
                                    maxResults=50, pageToken=page).execute()
        ids += [i["contentDetails"]["videoId"] for i in r["items"]]
        page = r.get("nextPageToken")
        if not page:
            break
    out = []
    for i in range(0, len(ids), 50):
        r = yt.videos().list(part="snippet,status,contentDetails",
                             id=",".join(ids[i:i + 50])).execute()
        out += r["items"]
    return out


def _texture(title: str) -> str:
    from ambient import TEXTURE_LABEL
    for tex, label in TEXTURE_LABEL.items():
        if title.startswith(f"【{label}】"):
            return tex
    return "-"


def backfill(apply: bool = True) -> int:
    if not RUNLOG.exists():
        print("runlog.md がありません")
        return 0
    text = RUNLOG.read_text(encoding="utf-8")
    rows = []
    for v in _published():
        vid = v["id"]
        if vid in text:
            continue
        sn, st = v["snippet"], v["status"]
        when = st.get("publishAt") or sn["publishedAt"]
        jst = datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(JST)
        mins = _minutes(v["contentDetails"]["duration"])
        # Over an hour is an L3; the explainers run 8-15 minutes and the
        # ambient tail is two hours, so there is no overlap to get wrong.
        mode = "guide" if mins > 60 else "narrated"
        title = sn["title"].replace("\n", " ").replace("|", "／")[:34]
        # A still-private upload has no publish time to report, and printing
        # its upload time in that column would read as "went out at 11:29",
        # which is the one thing the column is supposed to tell you.
        slot = (f"{jst:%m-%dT%H:%M}" if st.get("privacyStatus") == "public"
                else f"（{st.get('privacyStatus', '?')}）")
        rows.append((jst, f"| {jst:%m/%d %H:%M} | ✔ 復元 | {mode} | - | {title} "
                          f"| （復元・不明） | {_texture(sn['title'])} | — "
                          f"| {mins}分 | - | {vid} | {slot} |\n"))
    if not rows:
        print("実行記録に穴はありません")
        return 0
    rows.sort(key=lambda r: r[0])
    print(f"実行記録に {len(rows)} 本ぶんの穴があります（定期実行が push できなかった分）:")
    for _, line in rows:
        print("  " + line.rstrip())
    if apply:
        with RUNLOG.open("a", encoding="utf-8") as f:
            f.writelines(line for _, line in rows)
        print(f"\n{RUNLOG.name} に追記しました。commit して push してください。")
    return len(rows)


if __name__ == "__main__":
    sys.exit(0 if backfill(apply="--dry-run" not in sys.argv) >= 0 else 1)
