"""Make each video differ from the last one — in shape, in substance, in voice.

YouTube's inauthentic-content policy is not aimed at whether a machine helped;
it is aimed at catalogues where every entry is the same entry. This channel was
producing exactly that: eight chapters every time, 3,200 characters every time,
thirty images every time, the same closing sentence every time. A viewer would
not notice on one video. It is unmistakable across twenty.

Four things happen here.

1. `variance()` gives each video a different shape, derived from its topic so
   the same topic always renders the same way (reviewable, reproducible) while
   different topics differ.
2. `editorial_note()` pulls in what the channel owner actually wrote. This is
   the one thing no generator supplies and the one thing that makes a video
   somebody's rather than anybody's.
3. `check_template_tells()` catches the stock phrases that make generated prose
   recognisable — the ones that appear in every video of this kind on YouTube.
4. `record_bookends()` / `recent_bookends()` remember how previous videos opened
   and closed, so the next one can be told not to repeat them. Stored in the
   repo, because the container that generated the last video is already gone.

None of this hides that synthesis is involved. Disclosure is a separate
obligation and is not this module's business.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
EDITORIAL_FILE = ASSETS / "editorial.md"
BOOKENDS_FILE = ASSETS / "bookends.json"
KEEP_BOOKENDS = 12


def _seed(topic: str) -> int:
    return int(hashlib.sha256(topic.encode("utf-8")).hexdigest()[:12], 16)


def variance(topic: str, base_chars: int) -> dict:
    """Per-video shape. Ranges are wide enough to read as different videos.

    Derived from the topic rather than randomly so a re-run produces the same
    video — a retry after an upload failure should not silently become a
    different length.
    """
    h = _seed(topic)
    return {
        "chapters": 6 + h % 5,                       # 6..10
        "narration_chars": int(base_chars * (0.85 + (h >> 4) % 31 / 100)),   # ±15%
        "num_images": 22 + (h >> 9) % 13,            # 22..34
    }


def editorial_note() -> str:
    """What the channel owner wrote, if anything. Blank is allowed."""
    if not EDITORIAL_FILE.exists():
        return ""
    lines = [l for l in EDITORIAL_FILE.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.lstrip().startswith(("#", "<!--", "-->"))]
    return "\n".join(lines).strip()


# Phrases that appear in essentially every generated Japanese explainer. They are
# not wrong; they are unmarked. A viewer who has seen three of these videos
# recognises the fourth before the first sentence ends.
TEMPLATE_TELLS = [
    "いかがでしたでしょうか", "いかがでしたか",
    "本日は", "今回は", "皆さんは",
    "ぜひ最後まで", "最後までご覧",
    "参考になれば", "お役に立てれば",
    "と言えるでしょう", "ではないでしょうか",
    "重要なポイント", "大切なポイント",
    "まとめると", "以上、",
]


def check_template_tells(text: str) -> list[str]:
    return [p for p in TEMPLATE_TELLS if p in text]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[。！？])", text or "") if s.strip()]


def bookends(narration: str) -> tuple[str, str]:
    """The first and last sentence — where repetition is most visible."""
    s = _sentences(narration)
    return (s[0] if s else ""), (s[-1] if s else "")


def _load_bookends() -> list[dict]:
    if not BOOKENDS_FILE.exists():
        return []
    try:
        return json.loads(BOOKENDS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def recent_bookends(limit: int = 6) -> list[dict]:
    return _load_bookends()[-limit:]


def record_bookends(title: str, narration: str) -> None:
    opening, closing = bookends(narration)
    if not opening:
        return
    history = _load_bookends()
    history.append({"title": title, "opening": opening, "closing": closing})
    BOOKENDS_FILE.write_text(
        json.dumps(history[-KEEP_BOOKENDS:], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def avoid_bookends_block(limit: int = 6) -> str:
    """Prompt fragment listing how recent videos opened and closed."""
    past = recent_bookends(limit)
    if not past:
        return ""
    lines = []
    for p in past:
        if p.get("opening"):
            lines.append(f"・書き出し: {p['opening']}")
        if p.get("closing"):
            lines.append(f"・締め: {p['closing']}")
    return ("\n\n【繰り返してはいけない言い回し】直近の動画は次のように始まり、終わっています。"
            "同じ形・同じ語り口を再利用せず、今回は別の入り方・別の終わり方にしてください。\n"
            + "\n".join(lines))
