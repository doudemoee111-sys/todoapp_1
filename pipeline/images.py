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


class ImagesMostlyFailedError(RuntimeError):
    """画像生成の大半が失敗（＝Stability全滅：残高切れ/キー/レート等）。単色フォールバック
    だけで“画像のない動画”を公開しないよう、生成段階で中断させるための例外。"""


# 半分以上が単色フォールバックに落ちたら、その動画は実質「画像なし」なので中断する。
# 1〜数枚の単発失敗は従来どおり許容（フォールバックで穴埋め）する。
_MAX_FALLBACK_RATIO = 0.5


def generate_images(prompts: list[str], style: str, out_dir: str | Path,
                    aspect: str = "16:9", width: int = VIDEO_W, height: int = VIDEO_H) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    negative = "text, watermark, signature, blurry, deformed, extra limbs, low quality"
    paths: list[Path] = []
    failed = 0
    for i, p in enumerate(prompts):
        out = out_dir / f"img_{i:03d}.png"
        full_prompt = f"{p}. {style}"
        ok = False
        try:
            ok = _generate_one(full_prompt, out, negative, aspect=aspect)
        except Exception as e:  # noqa: BLE001
            print(f"  [images] error on {i}: {e}")
        if not ok:
            failed += 1
            _solid_fallback(out, width, height)
        paths.append(out)
        print(f"  [images] {i+1}/{len(prompts)} -> {out.name}{'  (fallback)' if not ok else ''}")
    total = len(prompts) or 1
    if failed / total >= _MAX_FALLBACK_RATIO:
        raise ImagesMostlyFailedError(
            f"画像生成が大半失敗しました（{failed}/{total}枚が単色フォールバック）。"
            "Stabilityの残高切れ/キー/レート制限の可能性が高いです。"
            "画像のない動画を公開しないため、この動画の生成を中断します。"
            "Stabilityの残高・キーを確認してから再実行してください。")
    if failed:
        print(f"  [images] 注意: {failed}/{total}枚がフォールバック（許容範囲内で続行）")
    return paths


if __name__ == "__main__":
    from config import GENRES
    ps = ["a vast spiral galaxy glowing in deep space",
          "a lone astronaut floating near a giant ringed planet"]
    generate_images(ps, GENRES["space"]["image_style"], "output/_img_test")
