"""Check that a topic names something that actually exists, before writing about it.

Why: on 2026-10-11 and 10-12 the mystery pipeline produced
「長岡の夢見ヶ原の失われた黄金船」and「船橋市のピアノマン失踪（2022/6/15）」,
narrated both as real events, and published them. Neither exists. Asked for "an
unsolved case that performs well on YouTube", the model invents one, and nothing
downstream can tell an invented case from a real one — a prompt saying "don't
make things up" is not a check, it is a wish.

So this module is the check. It asks Japanese Wikipedia whether the subject has
an article, which is the same bar config.py states for these genres. Wikipedia
is not a perfect authority, but it is a real external source, it needs no API
key, and a fabricated case name reliably fails it.

Scope: only genres that assert real-world facts need this (mystery, urban).
Fiction genres (kaidan) must NOT be gated — their topics are invented on
purpose, and a Wikipedia article would be a reason for concern, not comfort.
"""
from __future__ import annotations
import re
import urllib.parse

import requests

_API = "https://ja.wikipedia.org/w/api.php"
_UA = "sekai-zatsugaku-pipeline/1.0 (topic existence check)"
_TIMEOUT = 20

# 事件名から落としても意味が変わらない飾り（検索ヒット率を上げるため）。
_NOISE = re.compile(
    r"(の謎|の真相|の真実|その後|徹底解説|完全解説|解説|考察|とは|について|"
    r"【.*?】|\(.*?\)|（.*?）)")


def _candidates(topic: str) -> list[str]:
    """Query strings to try, most specific first."""
    t = topic.strip()
    out = [t]
    stripped = _NOISE.sub("", t).strip("　 ・-—–、。")
    if stripped and stripped != t:
        out.append(stripped)
    # 「船橋市のピアノマン失踪」→「ピアノマン失踪」: 先頭の地名修飾を外した形も試す。
    m = re.match(r"^[^\s　]{2,8}(?:市|町|村|県|区|島|山|湖|駅)の(.+)$", stripped or t)
    if m:
        out.append(m.group(1))
    seen, uniq = set(), []
    for q in out:
        if q and q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq


def _search(query: str) -> list[dict]:
    r = requests.get(_API, params={
        "action": "query", "list": "search", "srsearch": query,
        "srlimit": 5, "format": "json", "utf8": 1,
    }, headers={"User-Agent": _UA}, timeout=_TIMEOUT)
    r.raise_for_status()
    return (r.json().get("query") or {}).get("search") or []


def _tokens(s: str) -> list[str]:
    """Distinctive 2-gram-ish chunks of a Japanese phrase, for loose matching."""
    s = re.sub(r"[\s　のがをにはでとやへもから、。・]", "", s)
    return [s[i:i + 2] for i in range(0, max(0, len(s) - 1))]


def _looks_like_same_subject(topic: str, article_title: str) -> bool:
    """Does the found article plausibly cover the asked-about subject?

    A search for an invented case still returns articles — for the city, for a
    song called ピアノマン — so a hit alone proves nothing. Require real overlap
    between the topic's wording and the article's title.

    The overlap has to be measured both ways. Scoring only what share of the
    article's title appears in the topic passes 「船橋市」 for
    「船橋市のピアノマン失踪」: a short, generic article is fully contained in
    the fabricated case's name, which is how a city article would have waved
    through the very topic this module exists to catch. So the article must also
    account for most of what the topic actually says.
    """
    a, t = _tokens(article_title), _tokens(topic)
    if not a or not t:
        return False
    tset, aset = set(t), set(a)
    article_in_topic = sum(1 for g in a if g in tset) / len(a)
    topic_in_article = sum(1 for g in t if g in aset) / len(t)
    # 0.75 で「北海道の謎」が「北海道」で通るのを防げる。漠然とした題材こそ捏造が
    # 紛れ込む余地なので、ここは緩めない。飾り語は _candidates() が段階的に落とすため、
    # 本物の事件名は短い候補形で一致する。
    return article_in_topic >= 0.6 and topic_in_article >= 0.75


def verify(topic: str) -> tuple[bool, str]:
    """Return (exists, reason). `reason` is for the run log and the report mail.

    An unreachable Wikipedia returns False: when the check cannot run, the
    honest outcome is to not publish, not to assume the subject is real.
    """
    for q in _candidates(topic):
        try:
            hits = _search(q)
        except Exception as e:  # noqa: BLE001
            return False, f"Wikipediaに照会できませんでした（{type(e).__name__}: {e}）。検証不能のため中止します。"
        for h in hits:
            title = h.get("title", "")
            if _looks_like_same_subject(topic, title):
                url = "https://ja.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
                return True, f"実在を確認: ja.wikipedia「{title}」({url}) / 検索語「{q}」"
        if hits:
            near = "・".join(h.get("title", "") for h in hits[:3])
            last = f"検索語「{q}」の上位ヒット（{near}）はいずれも主題が一致しません"
        else:
            last = f"検索語「{q}」でヒット0件"
    return False, (f"ja.wikipediaで実在を確認できませんでした（{last}）。"
                   "AIが事件を創作した可能性が高いため、この題材では台本を書きません。")


def requires_verification(genre: dict) -> bool:
    return bool(genre.get("verify_real_world"))


if __name__ == "__main__":  # 手動確認用
    import sys
    for arg in sys.argv[1:]:
        ok, why = verify(arg)
        print(("OK   " if ok else "FAIL ") + arg + " -> " + why)
