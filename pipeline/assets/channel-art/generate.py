"""Generate the YouTube banner and profile picture for 睡眠・安眠チャンネル2.

Design notes
------------
The channel is watched in a dark bedroom, at night, by someone already
irritated by noise. So the art is dark, low-contrast, and quiet: nothing here
should be the brightest thing in the room when the phone is unlocked at 2am.
That rules out the usual bright-thumbnail playbook.

The motif is a snore waveform that flattens — the apnea pause — and resumes.
It is the one image that says "this channel is about the sound next to you"
without a word, and it is the same mark used across the project's documents.

Banner geometry is not decorative: YouTube crops the 2048x1152 image
differently per device and only the centred 1235x338 "safe area" is guaranteed
to survive. Every word therefore lives inside that box; the waveform is what
fills the parts that get cropped away on a phone.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent / "channel_art"
OUT.mkdir(exist_ok=True)

BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
REG = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

# Same palette as the project's documents, so the channel and the plan match.
INK = (231, 237, 246)
MUTED = (150, 165, 190)
TEAL = (79, 199, 214)
BG_TOP = (8, 11, 20)
BG_BOT = (20, 30, 54)


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size, index=0)


def vertical_gradient(w: int, h: int, top, bottom) -> Image.Image:
    """A 1-pixel-wide gradient stretched to size: cheap and perfectly smooth."""
    grad = Image.new("RGB", (1, h))
    px = grad.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
    return grad.resize((w, h))


def glow(img: Image.Image, cx: int, cy: int, radius: int, colour, strength: float) -> None:
    """Soft radial light, painted on its own layer then screened in."""
    layer = Image.new("RGB", img.size, (0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
              fill=tuple(round(c * strength) for c in colour))
    layer = layer.filter(ImageFilter.GaussianBlur(radius * 0.55))
    img.paste(Image.blend(img, Image.blend(img, layer, 1.0).point(lambda v: v), 0), (0, 0))
    # screen blend: result = 1 - (1-a)(1-b)
    a, b = img.convert("RGB").split(), layer.split()
    merged = [Image.eval(Image.merge("L", (ch_a,)), lambda v: v) for ch_a in a]
    out = Image.merge("RGB", tuple(
        Image.eval(Image.merge("L", (x,)), lambda v: v) for x in a))
    px_a, px_b = out.load(), layer.load()
    w, h = img.size
    for y in range(0, h):
        for x in range(0, w):
            ra, ga, ba = px_a[x, y]
            rb, gb, bb = px_b[x, y]
            px_a[x, y] = (255 - (255 - ra) * (255 - rb) // 255,
                          255 - (255 - ga) * (255 - gb) // 255,
                          255 - (255 - ba) * (255 - bb) // 255)
    img.paste(out, (0, 0))


def snore_wave(draw: ImageDraw.ImageDraw, x0: int, x1: int, y: int, amp: int,
               gap: tuple[float, float], colour, width: int, fade: bool = True) -> None:
    """Breathing waveform with a flat stretch — the apnea pause — in the middle.

    `gap` is the flat span as a fraction of the width. Amplitude tapers toward
    both ends so the line dissolves into the background instead of being cut.
    """
    span = x1 - x0
    g0, g1 = x0 + span * gap[0], x0 + span * gap[1]
    pts = []
    step = 2
    for x in range(x0, x1 + 1, step):
        if g0 <= x <= g1:
            pts.append((x, y))
            continue
        # Two stacked sines: a slow breath cycle plus a faster rasp on top.
        t = (x - x0) / 26.0
        v = math.sin(t) * 0.72 + math.sin(t * 2.6) * 0.28
        taper = 1.0
        if fade:
            edge = min(x - x0, x1 - x) / (span * 0.28)
            taper = max(0.0, min(1.0, edge))
            # Ramp back up right after the pause: the gasp on resuming.
            if x > g1:
                taper *= min(1.0, (x - g1) / (span * 0.05))
            if x < g0:
                taper *= min(1.0, (g0 - x) / (span * 0.10) + 0.35)
        pts.append((x, y - v * amp * taper))
    draw.line(pts, fill=colour, width=width, joint="curve")


# --------------------------------------------------------------------------
def make_banner() -> Path:
    W, H = 2048, 1152
    SAFE_W, SAFE_H = 1235, 338          # guaranteed-visible box, centred
    sx0, sy0 = (W - SAFE_W) // 2, (H - SAFE_H) // 2

    img = vertical_gradient(W, H, BG_TOP, BG_BOT).convert("RGB")

    # A single low moon-light from the upper left, painted by hand so it stays
    # subtle — a bright hero glow would defeat the whole point.
    light = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(light).ellipse([-380, -520, 1180, 700], fill=(16, 40, 52))
    light = light.filter(ImageFilter.GaussianBlur(220))
    img = Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), 0.0)
    base_px, light_px = img.load(), light.load()
    for y in range(H):
        for x in range(W):
            r, g, b = base_px[x, y]
            lr, lg, lb = light_px[x, y]
            base_px[x, y] = (min(255, r + lr), min(255, g + lg), min(255, b + lb))

    d = ImageDraw.Draw(img)

    # The waveform runs the full width, but sits *inside* the safe area
    # vertically. On a TV the whole line shows; on a phone the crop keeps the
    # centre — which is exactly where the apnea pause is. The one element that
    # identifies this channel therefore survives the smallest crop.
    wy = sy0 + 46
    snore_wave(d, 60, W - 60, wy, 40, (0.455, 0.545), (28, 72, 90), 6)
    snore_wave(d, 60, W - 60, wy, 40, (0.455, 0.545), (58, 132, 152), 3)
    # The pause itself, marked in the warm accent — the only warm pixel here.
    d.line([(60 + (W - 120) * 0.455, wy), (60 + (W - 120) * 0.545, wy)],
           fill=(150, 108, 58), width=4)

    f_title = font(BOLD, 100)
    f_sub = font(REG, 38)
    f_meta = font(BOLD, 29)

    title = "睡眠・安眠チャンネル2"
    sub = "隣のいびきで眠れない夜に。40代・50代のための睡眠解説"
    meta = "毎週 火・木・土・日　21:00 更新"

    cx = W // 2
    ty = sy0 + 96
    d.text((cx, ty), title, font=f_title, fill=INK, anchor="mt")
    d.text((cx, ty + 136), sub, font=f_sub, fill=MUTED, anchor="mt")

    # Schedule chip, drawn as a hairline pill so it reads as metadata.
    mw = d.textlength(meta, font=f_meta)
    pw, ph = mw + 52, 54
    px0, py0 = cx - pw / 2, ty + 194
    d.rounded_rectangle([px0, py0, px0 + pw, py0 + ph], radius=4,
                        outline=(46, 92, 106), width=2)
    d.text((cx, py0 + ph / 2), meta, font=f_meta, fill=TEAL, anchor="mm")

    path = OUT / "banner_2048x1152.png"
    img.save(path, "PNG")
    return path


# --------------------------------------------------------------------------
def make_icon() -> Path:
    """800x800, cropped to a circle by YouTube and shown as small as 24px.

    At 24px a crescent and a waveform overlapping each other turn to mush, so
    they are separated: the moon owns the upper two-thirds, the waveform sits
    clear of it below. The composition is centred on the circle, because the
    corners of the square are thrown away.
    """
    S = 800
    SS = 4                                   # supersample, then downscale
    N = S * SS
    img = vertical_gradient(N, N, (10, 14, 24), (26, 39, 66)).convert("RGB")
    c = N // 2

    # Crescent: a disc with an offset disc knocked out. Kept crisp — a soft
    # edge reads as an out-of-focus blob once it is 24 pixels wide.
    moon = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(moon)
    r = int(N * 0.305)
    my = c - int(N * 0.085)                  # sits high; waveform takes below
    md.ellipse([c - r, my - r, c + r, my + r], fill=255)
    off = int(r * 0.46)
    md.ellipse([c - r + off, my - r - int(r * 0.10),
                c + r + off, my + r - int(r * 0.10)], fill=0)
    moon = moon.filter(ImageFilter.GaussianBlur(N * 0.0015))
    img.paste(Image.new("RGB", img.size, (214, 233, 240)), (0, 0), moon)

    # Waveform, clear of the moon, narrower so the strokes stay thick relative
    # to their length. The flat pause stays centred and readable.
    d = ImageDraw.Draw(img)
    wy = c + int(N * 0.29)
    snore_wave(d, int(N * 0.24), int(N * 0.76), wy,
               int(N * 0.055), (0.42, 0.58), TEAL, SS * 7)

    img = img.resize((S, S), Image.LANCZOS)
    path = OUT / "icon_800x800.png"
    img.save(path, "PNG")
    return path


def make_icon_preview(icon: Path) -> Path:
    """Show the icon as YouTube shows it: a circle, at the sizes that matter."""
    src = Image.open(icon).convert("RGB")
    sizes = [(176, "チャンネルページ"), (88, "動画ページ"), (48, "検索結果"), (24, "コメント欄")]
    pad, gap = 46, 76
    W = pad * 2 + sum(s for s, _ in sizes) + gap * (len(sizes) - 1)
    H = 262
    canvas = Image.new("RGB", (W, H), (242, 244, 248))
    d = ImageDraw.Draw(canvas)
    f = font(BOLD, 17)
    x = pad
    for s, label in sizes:
        thumb = src.resize((s, s), Image.LANCZOS)
        mask = Image.new("L", (s * 8, s * 8), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, s * 8 - 1, s * 8 - 1], fill=255)
        mask = mask.resize((s, s), Image.LANCZOS)
        y = 40 + (176 - s) // 2
        canvas.paste(thumb, (x, y), mask)
        d.text((x + s // 2, 226), f"{s}px", font=f, fill=(38, 44, 68), anchor="mb")
        d.text((x + s // 2, 244), label, font=font(REG, 15), fill=(110, 118, 146), anchor="mb")
        x += s + gap
    path = OUT / "icon_size_preview.png"
    canvas.save(path, "PNG")
    return path


# --------------------------------------------------------------------------
def make_safe_area_preview(banner: Path) -> Path:
    """Overlay the three crop regions so the layout can be checked at a glance."""
    img = Image.open(banner).convert("RGB")
    W, H = img.size
    d = ImageDraw.Draw(img)
    boxes = [
        ((1235, 338), (255, 90, 80), "スマホ表示（必ず見える範囲）"),
        ((1546, 423), (240, 180, 70), "タブレット表示"),
        ((2048, 1152), (110, 200, 230), "テレビ表示（全体）"),
    ]
    f = font(BOLD, 26)
    for (bw, bh), colour, label in boxes:
        x0, y0 = (W - bw) // 2, (H - bh) // 2
        d.rectangle([x0, y0, x0 + bw - 1, y0 + bh - 1], outline=colour, width=3)
        d.text((x0 + 12, y0 + 10), label, font=f, fill=colour)
    path = OUT / "banner_safearea_preview.png"
    img.save(path, "PNG")
    return path


if __name__ == "__main__":
    b = make_banner()
    i = make_icon()
    p = make_safe_area_preview(b)
    q = make_icon_preview(i)
    for f in (b, i, p, q):
        im = Image.open(f)
        print(f"{f.name:32} {im.size[0]}x{im.size[1]}  {f.stat().st_size/1024:.0f} KB")
