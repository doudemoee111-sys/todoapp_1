"""チャンネルのプロフィール画像・バナー背景を生成する(一回限りのブランディング用スクリプト)"""

from pathlib import Path

import requests

import config

STABILITY_URL = "https://api.stability.ai/v2beta/stable-image/generate/core"
OUT_DIR = config.BASE_DIR / "branding"

PROFILE_PROMPT = (
    "A cute chibi owl mascot character wearing tiny round glasses, holding a glowing "
    "lightbulb in one wing, big sparkling curious eyes, sitting on a small stack of "
    "books. Centered composition with generous padding around the subject on all "
    "sides so it crops well into a circle. "
    "Style: cute anime illustration, chibi style, soft pastel colors, warm and "
    "friendly, flat vector art, gentle lighting, simple clean background, "
    "no text, no letters, no words, no watermark."
)

BANNER_PROMPT = (
    "A wide horizontal banner illustration. A cute chibi owl mascot character is "
    "small and confined entirely to the bottom-left corner of the frame, occupying "
    "no more than the left 20 percent of the width. A few small floating lightbulbs "
    "and stars decorate only the far left and far right edges of the frame. "
    "The entire center 70 percent of the image, both horizontally and vertically, "
    "is a completely plain, smooth, uncluttered soft pastel gradient sky with "
    "absolutely no owl, no lightbulbs, no stars, no objects, no clutter there — "
    "empty negative space reserved for text. "
    "Style: cute anime illustration, chibi style, soft pastel colors, warm and "
    "friendly, flat vector art, gentle lighting, "
    "no text, no letters, no words, no watermark."
)


def _generate(prompt: str, aspect_ratio: str, out_path: Path) -> None:
    api_key = config.load_stability_key()
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "image/*"}
    data = {"prompt": prompt, "aspect_ratio": aspect_ratio, "output_format": "png"}
    resp = requests.post(
        STABILITY_URL, headers=headers, data=data, files={"none": ""}, timeout=60
    )
    if resp.status_code != 200:
        raise SystemExit(f"エラー: Stability AI APIエラー ({resp.status_code}): {resp.text[:300]}")
    out_path.write_bytes(resp.content)
    print(f"生成しました: {out_path}")


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _generate(PROFILE_PROMPT, "1:1", OUT_DIR / "profile_raw.png")
    _generate(BANNER_PROMPT, "16:9", OUT_DIR / "banner_raw.png")
