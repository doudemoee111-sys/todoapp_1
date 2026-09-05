"""Re-check every published video against today's 薬機法 dictionary.

Why this exists, in one sentence: the gate only ever sees a video once, on the
day it is made, and the dictionary keeps growing after that.

The concrete failure. A video went out on 2026-08-25 at 12:00 UTC titled
「…いびき軽減法：姿勢と枕の調整で夜が変わる」. The gate passed it, correctly —
the patterns for 「軽減法」 and 「が変わる」 were added to compliance.py at 13:45
UTC the same day, one hour and forty-five minutes after it was already public.
Nothing re-read that title afterwards, so it stayed up. Worse, _description()
embeds sibling titles verbatim, so the same phrase was copied into three later
descriptions, and a tag reading 「いびき解消法」 sat on another video for weeks
because tags were not scanned at all.

A dictionary that grows is a good thing; a back catalogue that never gets
re-read is the bug. This script is the missing re-read. It is cheap — two API
calls for a channel this size — so it runs at the end of every generation as a
warning, and standalone in the weekly review.

    python3 audit_published.py            # report
    python3 audit_published.py --fix-tags # also strip offending tags via the API

Titles and descriptions are never edited automatically. A tag is a keyword and
deleting it is the whole remedy; a title is editorial and someone should choose
its replacement.
"""
from __future__ import annotations

import argparse
import re
import sys

import compliance

FIELDS = ("title", "description", "tags")


def channel_videos(yt) -> list[dict]:
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
        out += yt.videos().list(part="snippet,status",
                                id=",".join(ids[i:i + 50])).execute()["items"]
    return out


# Both link shapes the pipeline has emitted: the early videos used a bare
# youtu.be link, the later ones a watch?v=…&list= link so the playlist keeps
# auto-playing. Either way the video id is the thing that does not change.
_RELATED_LINE = re.compile(
    r"^・(?P<title>.+)\n[ \t]*(?P<url>https?://(?:youtu\.be/(?P<v1>[\w-]{11})"
    r"|www\.youtube\.com/watch\?v=(?P<v2>[\w-]{11}))\S*)$", re.M)


def refresh_related(videos: list[dict], yt, write: bool = False) -> int:
    """Re-point the 「▼ このチャンネルの他の動画」 block at current titles.

    The block stores each sibling's title as text, captured at the moment the
    description was written. Titles move — one was renamed by hand, another had
    to be rewritten for 薬機法 — and every copy elsewhere goes stale silently.
    The video id in the link is the stable thing, so the title is looked up
    again from it rather than trusted.

    An entry whose current title still breaks the dictionary is removed
    outright: linking to it is how the phrase spread in the first place.
    """
    titles = {v["id"]: v["snippet"]["title"] for v in videos}
    changed = 0
    for v in videos:
        sn = v["snippet"]
        desc = sn.get("description", "")

        def _sub(m: re.Match) -> str:
            vid = m.group("v1") or m.group("v2")
            now = titles.get(vid)
            if now is None:                      # deleted or not ours: leave it
                return m.group(0)
            if compliance.scan(now, "title"):
                print(f"    - 除外: {vid}「{now[:34]}」は現在も指摘があります")
                return ""
            if now == m.group("title"):
                return m.group(0)
            print(f"    - 差替: {vid}\n        旧「{m.group('title')[:38]}」"
                  f"\n        新「{now[:38]}」")
            return f"・{now}\n  {m.group('url')}"

        fixed = _RELATED_LINE.sub(_sub, desc)
        # A removed entry leaves a blank line behind; collapse runs of them so
        # the description does not grow a gap every time this runs.
        fixed = re.sub(r"\n{3,}", "\n\n", fixed).strip()
        if fixed == desc:
            continue
        print(f"\n■ {v['id']}  {sn['title'][:40]}")
        changed += 1
        if write:
            yt.videos().update(part="snippet", body={
                "id": v["id"],
                "snippet": {"title": sn["title"], "description": fixed,
                            "categoryId": sn.get("categoryId", "22"),
                            "tags": sn.get("tags") or [],
                            "defaultLanguage": sn.get("defaultLanguage", "ja")},
            }).execute()
            print("    → 更新しました")
    return changed


def findings_for(video: dict) -> list[tuple[str, compliance.Finding]]:
    sn = video["snippet"]
    hits: list[tuple[str, compliance.Finding]] = []
    hits += [("title", f) for f in compliance.scan(sn.get("title", ""), "title")]
    hits += [("description", f)
             for f in compliance.scan(sn.get("description", ""), "description")]
    for tag in sn.get("tags") or []:
        hits += [("tags", f) for f in compliance.scan(tag, "tags")]
    return hits


def audit(fix_tags: bool = False) -> int:
    """Return the number of findings. 0 means the back catalogue is clean."""
    from youtube_upload import _service
    yt = _service()
    videos = channel_videos(yt)
    total = 0
    for v in videos:
        hits = findings_for(v)
        if not hits:
            continue
        total += len(hits)
        sn, vid = v["snippet"], v["id"]
        print(f"\n■ {vid}  [{v['status']['privacyStatus']}]  {sn['title'][:44]}")
        for where, f in hits:
            print(f"    [{where}] 「{f.match}」… {f.reason}")
            if where != "title":
                print(f"        …{f.excerpt.strip()[:60]}…")
        if fix_tags and any(w == "tags" for w, _ in hits):
            keep, drop = compliance.clean_tags(sn.get("tags") or [])
            yt.videos().update(part="snippet", body={
                "id": vid,
                "snippet": {"title": sn["title"], "description": sn.get("description", ""),
                            "categoryId": sn.get("categoryId", "22"), "tags": keep},
            }).execute()
            print(f"    → タグを {len(drop)} 件削除しました: {', '.join(drop)}")

    print(f"\n走査 {len(videos)}本 / 指摘 {total}件"
          + ("" if total else " — 公開済みは現在の辞書で全て問題ありません"))
    if total:
        print("タイトルと概要欄は自動で書き換えません。文面を決めてから直してください。")
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fix-tags", action="store_true",
                    help="指摘されたタグをAPIで削除する（タイトル・概要欄は触らない）")
    ap.add_argument("--fix-related", action="store_true",
                    help="関連動画欄の題名を現在の題名に貼り直す（違反する題名の項目は削除）")
    ap.add_argument("--dry-run", action="store_true",
                    help="--fix-related で何が変わるかだけ表示する")
    ap.add_argument("--strict", action="store_true",
                    help="指摘が1件でもあれば終了コード1で終わる（定期実行の失敗検知用）")
    args = ap.parse_args()
    if args.fix_related:
        from youtube_upload import _service
        yt = _service()
        vids = channel_videos(yt)
        print("関連動画欄の題名を照合します"
              + ("（--dry-run: 書き込みません）" if args.dry_run else ""))
        n = refresh_related(vids, yt, write=not args.dry_run)
        print(f"\n{n}本の概要欄に差分がありました")
    n = audit(fix_tags=args.fix_tags)
    sys.exit(1 if (args.strict and n) else 0)


if __name__ == "__main__":
    main()
