"""Generate scene images with Stability AI (Stable Image Core).

Each narrative prompt is combined with the genre's visual style and rendered
to a 16:9 image. Failures on a single image fall back to a solid-colour frame
so one bad prompt never kills the whole run.
"""
from __future__ import annotations
import os
import subprocess
from pathlib import Path

import requests

from config import STABILITY_ENDPOINT, VIDEO_W, VIDEO_H


def _generate_one(prompt: str, out_path: Path, negative: str = "") -> bool:
    api_key = os.environ.get("STABILITY_API_KEY")
    if not api_key:
        raise RuntimeError("STABILITY_API_KEY が未設定です。")
    resp = requests.post(
        STABILITY_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "image/*"},
        files={"none": ""},
        data={"prompt": prompt, "negative_prompt": negative,
              "aspect_ratio": "16:9", "output_format": "png"},
        timeout=120,
    )
    if resp.status_code == 200:
        out_path.write_bytes(resp.content)
        return True
    print(f"  [images] Stability {resp.status_code}: {resp.text[:160]}")
    return False


def _solid_fallback(out_path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"color=c=0x0b1026:s={VIDEO_W}x{VIDEO_H}", "-frames:v", "1", str(out_path)],
        check=True)


def generate_images(prompts: list[str], style: str, out_dir: str | Path) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    negative = "text, watermark, signature, blurry, deformed, extra limbs, low quality"
    paths: list[Path] = []
    for i, p in enumerate(prompts):
        out = out_dir / f"img_{i:03d}.png"
        full_prompt = f"{p}. {style}"
        ok = False
        try:
            ok = _generate_one(full_prompt, out, negative)
        except Exception as e:  # noqa: BLE001
            print(f"  [images] error on {i}: {e}")
        if not ok:
            _solid_fallback(out)
        paths.append(out)
        print(f"  [images] {i+1}/{len(prompts)} -> {out.name}")
    return paths


if __name__ == "__main__":
    from config import GENRES
    ps = ["a vast spiral galaxy glowing in deep space",
          "a lone astronaut floating near a giant ringed planet"]
    generate_images(ps, GENRES["space"]["image_style"], "output/_img_test")
