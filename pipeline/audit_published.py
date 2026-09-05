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
    ap.add_argument("--strict", action="store_true",
                    help="指摘が1件でもあれば終了コード1で終わる（定期実行の失敗検知用）")
    args = ap.parse_args()
    n = audit(fix_tags=args.fix_tags)
    sys.exit(1 if (args.strict and n) else 0)


if __name__ == "__main__":
    main()
