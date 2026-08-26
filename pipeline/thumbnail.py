"""Create a 1280x720 YouTube thumbnail.

Design: "documentary poster" — one strong Stability-generated focal subject,
edge/vignette darkening + a bottom scrim so the headline is ALWAYS readable
regardless of the underlying image, a large left-aligned WHITE headline (max
contrast), and a consistent series identity (gold left rule + channel wordmark).

Rationale (長尺グロース診断): the old thumbnail was a same-for-every-video
template — AI background darkened 28% + centered yellow text, no focal subject,
low contrast, no series identity → weak CTR. Top faceless channels use a single
strong subject, few big words, high contrast, and a recognizable series look.
"""
from __future__ import annotations
import os
import textwrap
from pathlib import Path

from http_retry import request_with_retry
from PIL import Image, ImageDraw, ImageFont

from config import STABILITY_ENDPOINT

_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]

W, H = 1280, 720
BRAND = "世界の雑学王"
GOLD = (242, 194, 54)          # シリーズ識別のアクセント（統一）

# ジャンル別に「実写寄せ／被写体の焦点」を背景プロンプトへ足すヒント。
_GENRE_BG_HINT = {
    "space": ("one striking single celestial subject (planet, black hole, nebula) "
              "as the clear focal point, realistic astrophotography, NASA/JWST style, "
              "photoreal, deep space"),
    "mystery": ("one strong ominous focal subject, dark cinematic documentary still, "
                "muted desaturated tones, fog and deep shadow, tense mysterious mood"),
    "urban": ("one eerie symbolic focal subject, moody atmospheric, dark cinematic tone, "
              "fog, dramatic shadows, film grain"),
}


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


def _bg(prompt: str, genre_key: str | None, out: Path) -> None:
    api_key = os.environ.get("STABILITY_API_KEY")
    hint = _GENRE_BG_HINT.get(genre_key or "", "one strong focal subject, cinematic")
    full = (f"{prompt}. {hint}. dramatic rim lighting, high contrast, strong depth, "
            "cinematic, eye-catching, empty darker space toward the bottom for a caption, "
            "8k, photoreal, no text, no words, no watermark, no logo")
    try:
        resp = request_with_retry(
            "POST", STABILITY_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "image/*"},
            files={"none": ""},
            data={"prompt": full, "aspect_ratio": "16:9", "output_format": "png"},
            timeout=120,
        )
        if resp.status_code == 200:
            out.write_bytes(resp.content)
            return
    except Exception as e:  # noqa: BLE001
        print(f"      [thumb] 背景生成に失敗、フォールバック使用: {e}")
    Image.new("RGB", (W, H), (11, 16, 38)).save(out)


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Resize to fully cover w×h, center-crop the overflow (no distortion)."""
    scale = max(w / img.width, h / img.height)
    nw, nh = int(img.width * scale) + 1, int(img.height * scale) + 1
    img = img.resize((nw, nh), Image.LANCZOS)
    x0, y0 = (nw - w) // 2, (nh - h) // 2
    return img.crop((x0, y0, x0 + w, y0 + h))


def _bottom_scrim(img: Image.Image) -> Image.Image:
    """Darken the bottom band (and slightly the whole frame) so text is legible
    on any underlying image, while keeping the subject bright up top."""
    # subtle global darken for consistency
    img = Image.blend(img, Image.new("RGB", img.size, (0, 0, 0)), 0.14)
    # bottom gradient scrim via an L mask (0 top → strong bottom)
    mask = Image.new("L", (1, H), 0)
    start = int(H * 0.42)
    for y in range(H):
        a = 0 if y < start else int(225 * ((y - start) / (H - start)) ** 1.15)
        mask.putpixel((0, y), a)
    mask = mask.resize((W, H))
    return Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, mask)


def _fit_lines(text: str, max_w: int, hi: int = 190, lo: int = 74):
    """Choose a wrap + font size so the headline fills the width in ≤2 big lines.
    thumbnail_text is now a short 一撃ワード (≤9字), so this usually lands large."""
    text = (text or "").strip().replace("\r", "")
    for size in range(hi, lo - 1, -6):
        font = _font(size)
        # honor explicit newlines; otherwise wrap to 2 lines by width
        if "\n" in text:
            lines = [ln for ln in text.split("\n") if ln][:2]
        else:
            per = max(3, len(text) // 2 + len(text) % 2) if len(text) > 6 else len(text)
            lines = textwrap.wrap(text, width=per) or [text]
            lines = lines[:2]
        d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        widest = max((d.textlength(ln, font=font) for ln in lines), default=0)
        line_h = int(size * 1.16)
        if widest <= max_w and line_h * len(lines) <= int(H * 0.5):
            return lines, font, line_h
    return [text], _font(lo), int(lo * 1.16)


def make_thumbnail(text: str, bg_prompt: str, out_path: str | Path,
                   genre_key: str | None = None) -> Path:
    out_path = Path(out_path)
    raw = out_path.with_name("_thumb_bg.png")
    _bg(bg_prompt, genre_key, raw)

    img = _cover(Image.open(raw).convert("RGB"), W, H)
    img = _bottom_scrim(img)
    draw = ImageDraw.Draw(img)

    pad_l = 84          # left padding (left-aligned, off-center = editorial)
    rule_x = 50         # gold vertical rule position
    max_w = W - pad_l - 70
    lines, font, line_h = _fit_lines(text, max_w)

    total_h = line_h * len(lines)
    y = int(H * 0.90) - total_h        # sit in the lower third, above the wordmark
    top_y = y

    stroke = max(6, font.size // 18)
    for ln in lines:
        x = pad_l
        # drop shadow
        draw.text((x + 4, y + 5), ln, font=font, fill=(0, 0, 0))
        # heavy outline for contrast on any image
        draw.text((x, y), ln, font=font, fill=(255, 255, 255),
                  stroke_width=stroke, stroke_fill=(0, 0, 0))
        y += line_h

    # gold left vertical rule spanning the headline (series identity + color pop)
    draw.rectangle([rule_x, top_y + 6, rule_x + 12, top_y + total_h - 6], fill=GOLD)

    # channel wordmark, bottom-right, in the brand gold (consistent across videos)
    wm = _font(38)
    ww = draw.textlength(BRAND, font=wm)
    draw.text((W - ww - 40, H - 62), BRAND, font=wm, fill=GOLD,
              stroke_width=3, stroke_fill=(0, 0, 0))

    img.save(out_path, "PNG")
    raw.unlink(missing_ok=True)
    return out_path


if __name__ == "__main__":
    make_thumbnail("消えた\n村人", "an abandoned foggy mountain village at dusk",
                   "output/_thumb_test.png", genre_key="mystery")
    print("thumbnail written")
