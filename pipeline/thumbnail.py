"""Create a 1280x720 YouTube thumbnail: Stability background + big JP text overlay."""
from __future__ import annotations
import os
import textwrap
from pathlib import Path

from config import GENRES
from http_retry import request_with_retry
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from config import STABILITY_ENDPOINT

_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _bg(prompt: str, out: Path, style: str = "") -> None:
    api_key = os.environ.get("STABILITY_API_KEY")
    resp = request_with_retry(
        "POST",
        STABILITY_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "image/*"},
        files={"none": ""},
        # The genre's style has to reach the thumbnail too. Without it this
        # asked for "dramatic, cinematic, 8k" and got a photoreal human face on
        # a channel whose style string says "illustration ... no faces" — which
        # broke the look and put a realistic depiction of a scene that never
        # happened on the most-seen surface the channel has.
        data={"prompt": f"{prompt}. {style} high contrast, eye-catching, no text".strip(),
              "aspect_ratio": "16:9", "output_format": "png"},
        timeout=120,
    )
    if resp.status_code == 200:
        out.write_bytes(resp.content)
    else:
        Image.new("RGB", (1280, 720), (11, 16, 38)).save(out)


def make_thumbnail(text: str, bg_prompt: str, out_path: str | Path,
                   style: str = "") -> Path:
    out_path = Path(out_path)
    raw = out_path.with_name("_thumb_bg.png")
    _bg(bg_prompt, raw, style)

    img = Image.open(raw).convert("RGB").resize((1280, 720))
    # darken for text legibility
    overlay = Image.new("RGB", img.size, (0, 0, 0))
    img = Image.blend(img, overlay, 0.28)
    draw = ImageDraw.Draw(img)

    # wrap Japanese text ~6 chars/line
    lines = textwrap.wrap(text, width=6) or [text]
    size = 150 if len(lines) <= 2 else 110
    font = _font(size)
    line_h = int(size * 1.25)
    total_h = line_h * len(lines)
    y = (720 - total_h) // 2

    for line in lines:
        w = draw.textlength(line, font=font)
        x = (1280 - w) // 2
        # thick outline
        for dx in range(-4, 5, 2):
            for dy in range(-4, 5, 2):
                draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 220, 40))
        y += line_h

    img.save(out_path, "PNG")
    raw.unlink(missing_ok=True)
    return out_path


if __name__ == "__main__":
    make_thumbnail("眠れないのは\n私の方",
                   "a quiet dark bedroom at night, moonlight on an empty pillow",
                   "output/_thumb_test.png",
                   style=GENRES["sleep"]["image_style"])
    print("thumbnail written")
