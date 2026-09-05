"""Create a 1280x720 YouTube thumbnail in the channel's daylight style.

History, because the reasoning matters more than the code:

The first version generated a background with Stability and overlaid text. That
produced photorealistic people — a distressed woman's face shipped on a video
about snoring — which broke a channel whose visual language is quiet, put the
single most common image in mass-produced health content on our shelf, and
depicted a scene that never happened, which is exactly what YouTube's
synthetic-content disclosure asks about.

The second version drew the image here instead, from the same elements as the
banner: a night gradient, two large lines of type, and the snore waveform. The
design brief was "nothing here should be the brightest thing in the room when a
phone is unlocked at 2am."

That brief was wrong, and the data said so. Over 28 days the channel took 8,390
impressions and converted 0.7% of them. 94% of those impressions were in the
suggested-videos rail — which is not a dark bedroom at 2am, it is a browsing
session, and a near-black 168px tile in a dark UI has no edge at all. The
constraint that belongs to the video had been applied to its shop window.

So this version inverts the luminance and keeps the hues. Pale ground, deep navy
type, the same teal and amber. It is the same channel; it is simply visible.

Legibility at the size it is actually judged decides everything else: 246px wide
in search, 168px in the suggested column. At 168px a 1280px canvas is displayed
at 13%, so a 200px headline arrives as 26px — about the smallest that survives.
That is why the headline is enormous, short, and dark on light, and why
everything else is allowed to disappear.
"""
from __future__ import annotations

import math
import os
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 720

# Same hues as the banner and the icon, re-tuned for a light ground. Contrast
# ratios against BG are what matter here, not the swatches: INK is ~13:1, TEAL
# ~5.3:1, both far above the 4.5:1 that stays readable when YouTube overlays its
# duration badge and hover state.
INK = (16, 26, 46)          # deep navy — the headline
TEAL = (11, 106, 122)       # darkened from the night palette so it reads on cream
AMBER = (214, 122, 26)      # the one warm mark, used solid rather than as text
MUTED = (86, 102, 128)
BG_TOP = (252, 248, 240)    # warm cream
BG_BOT = (214, 230, 238)    # pale sky
EDGE = (24, 38, 62)

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
    """Pale ground with one soft warm glow in the upper left.

    Morning light rather than a bedside lamp. The glow is there to stop the
    gradient reading as a flat placeholder at thumbnail size, nothing more.
    """
    img = _gradient(W, H, BG_TOP, BG_BOT).convert("RGB")
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(glow).ellipse([-300, -380, 720, 420], fill=(22, 16, 4))
    glow = glow.filter(ImageFilter.GaussianBlur(170))
    bp, gp = img.load(), glow.load()
    for y in range(H):
        for x in range(W):
            r, g, b = bp[x, y]
            gr, gg, gb = gp[x, y]
            bp[x, y] = (min(255, r + gr), min(255, g + gg), min(255, b + gb))
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


def _wave_band(img: Image.Image, y: int, amp: int = 28, width: int = 9) -> None:
    d = ImageDraw.Draw(img)
    _snore_wave(d, 56, W - 56, y, amp, (0.44, 0.56), TEAL, width)
    # The pause itself, in the only warm colour on the image and thick enough to
    # still be a mark rather than a hairline when the tile is 168px wide.
    d.line([(56 + (W - 112) * 0.44, y), (56 + (W - 112) * 0.56, y)],
           fill=AMBER, width=width + 5)


# A headline is read in the suggested rail in well under a second, so it has to
# be short before it has to be complete. Two short lines beat one long one every
# time: two lines of five characters can be set at 230px, where seven characters
# on one line have to shrink to 160px to fit. Size is the contrast we control, so
# the splitter breaks early and the renderer spends what it saves on scale.
MAX_PER_LINE = 5


def _split_lines(text: str) -> list[str]:
    """At most two lines, as short as the wording allows.

    An explicit newline from the script wins. Otherwise the text is broken at a
    Japanese punctuation mark when there is one near the middle, because a break
    after 「、」 reads as intended rather than as a wrap.
    """
    text = (text or "").strip().replace("｜", "\n")
    if "\n" in text:
        return [l.strip() for l in text.split("\n") if l.strip()][:2]
    if len(text) <= MAX_PER_LINE:
        return [text]
    best = None
    for mark in ("、", "。", "・", "？", "?"):
        i = text.find(mark)
        if 2 <= i <= len(text) - 2:
            keep = text[:i + 1] if mark in "？?" else text[:i]
            best = [keep, text[i + 1:]]
            break
    if best is None:
        best = textwrap.wrap(text, width=max(MAX_PER_LINE, (len(text) + 1) // 2))[:2]
    return [l for l in best if l] or [text]


def make_thumbnail(text: str, out_path: str | Path, subtitle: str = "") -> Path:
    """Render the thumbnail. `text` is the headline, `subtitle` the quiet line.

    Font size steps down as the headline grows so a long line never runs off the
    edge; the check is on the measured width, not a character count, because a
    Japanese line's width does not follow its length closely enough to guess.
    """
    out_path = Path(out_path)
    img = _ground()
    d = ImageDraw.Draw(img)

    lines = _split_lines(text)
    BAR_H, SUB_H, WAVE_Y, TOP_MIN = 20, 58, 672, 48
    ROOM = WAVE_Y - 44 - TOP_MIN          # vertical space the block may occupy

    def _block(size: int, with_sub: bool) -> int:
        return (len(lines) * int(size * 1.08)
                + (BAR_H + 22 if len(lines) > 1 else 0)
                + (SUB_H if with_sub else 0))

    # Size is bounded by the canvas on both axes. Width alone is not enough: two
    # short lines fit side to side at 240px but stand 560px tall, and the block
    # then runs into the waveform. Checking only width is what pushed the
    # subtitle onto the wave in the first version of this layout.
    size, has_sub = 240, bool(subtitle)
    while size > 96:
        f = _font(size)
        if (max(d.textlength(l, font=f) for l in lines) <= W - 132
                and _block(size, has_sub) <= ROOM):
            break
        size -= 6
    # The headline is the thing that earns the click; the subtitle is invisible
    # at 168px anyway. If they cannot both fit, the subtitle goes.
    if has_sub and _block(size, True) > ROOM:
        has_sub = False
    f = _font(size)
    line_h = int(size * 1.08)

    # The block is centred in the space above the waveform, so a headline that
    # had to shrink does not leave a hole where a reader expects the image.
    y = TOP_MIN + max(0, (ROOM - _block(size, has_sub)) // 2)

    for i, line in enumerate(lines):
        d.text((66, y), line, font=f, fill=INK if i == 0 else TEAL)
        y += line_h

    # A solid amber bar under the last line: at 168px the eye resolves a block of
    # colour long before it resolves a glyph, so the block is what earns the look
    # that then reads the words. Placed below the whole line box, never through
    # it — an earlier version put it at 90% of the font size and struck the text
    # out.
    if len(lines) > 1:
        w2 = d.textlength(lines[-1], font=f)
        d.rectangle([66, y + 4, 66 + w2 + 14, y + 4 + BAR_H], fill=AMBER)
        y += BAR_H + 22

    if has_sub:
        # Unreadable at 168px and barely there at 246px, so it is set for the
        # larger preview only and given no space the headline could have used.
        d.text((70, y), subtitle.strip()[:22], font=_font(44, bold=False), fill=MUTED)

    _wave_band(img, WAVE_Y)

    # A thin dark frame. On a pale tile this is what separates the thumbnail from
    # YouTube's own light-mode background; without it the image bleeds into the
    # page and loses the crispness that made it bright in the first place.
    d.rectangle([0, 0, W - 1, H - 1], outline=EDGE, width=6)

    img.save(out_path, "PNG")
    return out_path


if __name__ == "__main__":
    for i, (t, s) in enumerate([
        ("その枕、高すぎ", "いびきと寝る姿勢の話"),
        ("眠れないのは\n私の方", "いびきで起こされる家族へ"),
        ("明日の朝、どう言う", "責めずに受診をすすめる"),
        ("別室という選択", "関係と健康のバランス"),
    ]):
        p = make_thumbnail(t, f"output/_thumb_test_{i}.png", s)
        print(p, Image.open(p).size)
