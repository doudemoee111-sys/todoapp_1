"""Stability AI(Stable Diffusion)でアニメ風の背景イラストを生成する"""

import sys
from pathlib import Path

from http_retry import request_with_retry

import config

STABILITY_URL = "https://api.stability.ai/v2beta/stable-image/generate/core"


def generate_images(image_prompts: list[str], out_dir: Path) -> list[Path]:
    api_key = config.load_stability_key()
    out_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "image/*",
    }

    paths = []
    for i, scene in enumerate(image_prompts):
        prompt = f"{scene}. {config.IMAGE_STYLE_SUFFIX}"
        data = {
            "prompt": prompt,
            "aspect_ratio": config.STABILITY_ASPECT_RATIO,
            "output_format": "png",
        }
        resp = request_with_retry(
            "POST",
            STABILITY_URL,
            headers=headers,
            data=data,
            files={"none": ""},  # multipart/form-data を強制するためのダミー
            timeout=60,
        )
        if resp.status_code != 200:
            sys.exit(f"エラー: Stability AI APIエラー ({resp.status_code}): {resp.text[:300]}")

        path = out_dir / f"scene_{i}.png"
        path.write_bytes(resp.content)
        paths.append(path)

    return paths
