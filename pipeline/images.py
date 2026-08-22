"""Generate scene images with Stability AI (Stable Image Core).

Each narrative prompt is combined with the genre's visual style and rendered
to a 16:9 image. Failures on a single image fall back to a solid-colour frame
so one bad prompt never kills the whole run.
"""
from __future__ import annotations
import os
import subprocess
from pathlib import Path

from http_retry import request_with_retry

from config import STABILITY_ENDPOINT, VIDEO_W, VIDEO_H


def _generate_one(prompt: str, out_path: Path, negative: str = "",
                  aspect: str = "16:9") -> bool:
    api_key = os.environ.get("STABILITY_API_KEY")
    if not api_key:
        raise RuntimeError("STABILITY_API_KEY が未設定です。")
    resp = request_with_retry(
        "POST",
        STABILITY_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "image/*"},
        files={"none": ""},
        data={"prompt": prompt, "negative_prompt": negative,
              "aspect_ratio": aspect, "output_format": "png"},
        timeout=120,
    )
    if resp.status_code == 200:
        out_path.write_bytes(resp.content)
        return True
    print(f"  [images] Stability {resp.status_code}: {resp.text[:160]}")
    return False


def _solid_fallback(out_path: Path, width: int = VIDEO_W, height: int = VIDEO_H) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"color=c=0x0b1026:s={width}x{height}", "-frames:v", "1", str(out_path)],
        check=True)


def generate_images(prompts: list[str], style: str, out_dir: str | Path,
                    aspect: str = "16:9", width: int = VIDEO_W, height: int = VIDEO_H) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    negative = "text, watermark, signature, blurry, deformed, extra limbs, low quality"
    paths: list[Path] = []
    for i, p in enumerate(prompts):
        out = out_dir / f"img_{i:03d}.png"
        full_prompt = f"{p}. {style}"
        ok = False
        try:
            ok = _generate_one(full_prompt, out, negative, aspect=aspect)
        except Exception as e:  # noqa: BLE001
            print(f"  [images] error on {i}: {e}")
        if not ok:
            _solid_fallback(out, width, height)
        paths.append(out)
        print(f"  [images] {i+1}/{len(prompts)} -> {out.name}")
    return paths


if __name__ == "__main__":
    from config import GENRES
    ps = ["a quiet dark bedroom at night, moonlight through a gap in the curtains",
          "a lone astronaut floating near a giant ringed planet"]
    generate_images(ps, GENRES["sleep"]["image_style"], "output/_img_test")
