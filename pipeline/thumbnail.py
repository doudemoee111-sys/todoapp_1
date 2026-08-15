"""Create a 1280x720 YouTube thumbnail: Stability background + big JP text overlay."""
from __future__ import annotations
import os
import textwrap
from pathlib import Path

import requests
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


def _bg(prompt: str, out: Path) -> None:
    api_key = os.environ.get("STABILITY_API_KEY")
    resp = requests.post(
        STABILITY_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "image/*"},
        files={"none": ""},
        data={"prompt": f"{prompt}. dramatic, high contrast, eye-catching, cinematic, 8k, no text",
              "aspect_ratio": "16:9", "output_format": "png"},
        timeout=120,
    )
    if resp.status_code == 200:
        out.write_bytes(resp.content)
    else:
        Image.new("RGB", (1280, 720), (11, 16, 38)).save(out)


def make_thumbnail(text: str, bg_prompt: str, out_path: str | Path) -> Path:
    out_path = Path(out_path)
    raw = out_path.with_name("_thumb_bg.png")
    _bg(bg_prompt, raw)

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
    make_thumbnail("宇宙の\n最大の謎", "a glowing spiral galaxy in deep space", "output/_thumb_test.png")
    print("thumbnail written")
