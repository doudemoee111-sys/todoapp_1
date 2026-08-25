"""Create a 1280x720 YouTube thumbnail in the channel's own typographic style.

This used to generate a background with Stability and overlay text on it. That
produced photorealistic people — a distressed woman's face shipped on a video
about snoring — which was wrong three times over: it broke a channel whose
visual language is dark and quiet, a stock human face is the single most common
image in mass-produced health content, and a realistic depiction of a scene that
never happened is exactly what YouTube's synthetic-content disclosure asks about.

So the image is drawn here instead, from the same elements as the banner and the
icon: a night gradient, one low light from the upper left, two very large lines
of type with the second in the channel's teal, and the snore waveform with its
apnea pause along the bottom. Nothing is generated, so nothing can surprise us
in the one place viewers always look.

It also costs nothing and takes about a second, where the old path spent
Stability credits on every video.

Legibility is the constraint that decides the layout: a thumbnail is judged at
246px wide in search results and 168px in the suggested column, so the headline
is set very large and everything else is allowed to disappear at that size.
"""
from __future__ import annotations

import math
import os
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 720

# Same palette as the banner, the icon, and the project's documents, so the
# channel reads as one thing wherever it appears.
INK = (238, 243, 250)
MUTED = (146, 162, 188)
TEAL = (79, 199, 214)
AMBER = (214, 158, 88)
BG_TOP = (8, 11, 20)
BG_BOT = (22, 32, 56)

_BOLD_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
]
_REG_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    for p in (_BOLD_CANDIDATES if bold else _REG_CANDIDATES):
        if os.path.exists(p):
            return ImageFont.truetype(p, size, index=0)
    return ImageFont.load_default()


def _gradient(w: int, h: int, top, bottom) -> Image.Image:
    """A 1-pixel-wide gradient stretched to size: cheap and perfectly smooth."""
    g = Image.new("RGB", (1, h))
    px = g.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
    return g.resize((w, h))


def _ground() -> Image.Image:
    """Night gradient with a single low light. Nothing here should be the
    brightest thing in the room when a phone is unlocked at 2am."""
    img = _gradient(W, H, BG_TOP, BG_BOT).convert("RGB")
    light = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(light).ellipse([-260, -340, 760, 460], fill=(14, 34, 46))
    light = light.filter(ImageFilter.GaussianBlur(150))
    bp, lp = img.load(), light.load()
    for y in range(H):
        for x in range(W):
            r, g, b = bp[x, y]
            lr, lg, lb = lp[x, y]
            bp[x, y] = (min(255, r + lr), min(255, g + lg), min(255, b + lb))
    return img


def _snore_wave(d: ImageDraw.ImageDraw, x0: int, x1: int, y: int, amp: int,
                gap: tuple[float, float], colour, width: int) -> None:
    """Breathing waveform with a flat stretch — the apnea pause — in the middle.

    The one mark that says what this channel is about without a word, and the
    same one used on the banner and the icon.
    """
    span = x1 - x0
    g0, g1 = x0 + span * gap[0], x0 + span * gap[1]
    pts = []
    for x in range(x0, x1 + 1, 2):
        if g0 <= x <= g1:
            pts.append((x, y))
            continue
        t = (x - x0) / 30.0
        v = math.sin(t) * 0.72 + math.sin(t * 2.6) * 0.28
        taper = max(0.0, min(1.0, min(x - x0, x1 - x) / (span * 0.26)))
        if x > g1:
            taper *= min(1.0, (x - g1) / (span * 0.05))
        pts.append((x, y - v * amp * taper))
    d.line(pts, fill=colour, width=width, joint="curve")


def _wave_band(img: Image.Image, y: int, amp: int = 38, width: int = 6) -> None:
    d = ImageDraw.Draw(img)
    _snore_wave(d, 40, W - 40, y, amp, (0.44, 0.56), (26, 66, 82), width + 4)
    _snore_wave(d, 40, W - 40, y, amp, (0.44, 0.56), (58, 138, 158), width)
    # The pause itself, in the only warm colour on the image.
    d.line([(40 + (W - 80) * 0.44, y), (40 + (W - 80) * 0.56, y)], fill=AMBER, width=width + 1)


def _split_lines(text: str) -> list[str]:
    """Two lines if we can manage it — the layout is built for two.

    An explicit newline from the script wins. Otherwise the text is broken at a
    Japanese punctuation mark when there is one near the middle, because a break
    after 「、」 reads as intended rather than as a wrap.
    """
    text = (text or "").strip()
    if "\n" in text:
        return [l.strip() for l in text.split("\n") if l.strip()][:3]
    if len(text) <= 7:
        return [text]
    for mark in ("、", "。", "｜", "・"):
        i = text.find(mark)
        if 2 <= i <= len(text) - 2:
            return [text[:i + 1], text[i + 1:]]
    return textwrap.wrap(text, width=max(6, (len(text) + 1) // 2))[:3] or [text]


def make_thumbnail(text: str, out_path: str | Path, subtitle: str = "") -> Path:
    """Render the thumbnail. `text` is the headline, `subtitle` the quiet line.

    Font size steps down as the headline grows so a long line never runs off the
    edge; the check is on the measured width, not a character count, because a
    Japanese line's width does not follow its length closely enough to guess.
    """
    out_path = Path(out_path)
    img = _ground()
    d = ImageDraw.Draw(img)
    _wave_band(img, 600)

    lines = _split_lines(text)
    # One line has nothing to balance against, so it sits lower; two is the
    # layout this design was built for; three only happens when the script
    # writes a long headline, and then everything shrinks to make room.
    size, top = {1: (150, 250), 2: (142, 120)}.get(len(lines), (112, 96))
    while size > 60:
        f = _font(size)
        if max(d.textlength(l, font=f) for l in lines) <= W - 144:
            break
        size -= 6
    f = _font(size)

    # The block sits above the waveform, with the second line in teal: one
    # accent, in one place, so the eye lands on the turn of the sentence.
    line_h = int(size * 1.14)
    y = top
    for i, line in enumerate(lines):
        d.text((72, y), line, font=f, fill=TEAL if i == 1 else INK)
        y += line_h

    if subtitle:
        # Clamped so it never crowds the headline above or the waveform below —
        # a caption touching either reads as a layout accident.
        sub_y = min(max(y + 26, 300), 496)
        d.text((72, sub_y), subtitle.strip()[:26], font=_font(44, bold=False), fill=MUTED)

    img.save(out_path, "PNG")
    return out_path


if __name__ == "__main__":
    for i, (t, s) in enumerate([
        ("その枕、高すぎるかも", "いびきと寝る姿勢の、わかっていること"),
        ("眠れないのは\n私の方", "いびきで起こされる家族へ"),
        ("明日の朝、どう言うか", "いびきを責めずに、受診をすすめる"),
    ]):
        p = make_thumbnail(t, f"output/_thumb_test_{i}.png", s)
        print(p, Image.open(p).size)
