"""Central configuration for the automated long-form YouTube pipeline.

All secrets are read from environment variables (never hard-coded):
  OPENAI_API_KEY          - script generation
  STABILITY_API_KEY       - image / thumbnail generation
  GOOGLE_TTS_API_KEY      - Google Cloud Text-to-Speech (REST, API-key auth)   [primary]
    or GOOGLE_APPLICATION_CREDENTIALS -> service-account json                  [alt]
  YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN - upload
"""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
ASSETS_DIR = ROOT / "assets"
STATE_FILE = ROOT / "state.json"
OUTPUT_DIR.mkdir(exist_ok=True)
ASSETS_DIR.mkdir(exist_ok=True)

# ---- Video spec -------------------------------------------------------------
VIDEO_W, VIDEO_H = 1920, 1080
FPS = 30
NUM_IMAGES = 30                 # "画像多め": ~30 scene images per video
TARGET_MIN_SECONDS = 480        # 8 minutes minimum
NARRATION_TARGET_CHARS = 3200   # ~8-10 min of JP narration at normal TTS speed

# ---- TTS --------------------------------------------------------------------
# provider: "google" (chosen) with fallback "openai" for smoke tests.
TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "google")
GOOGLE_TTS_VOICE = os.environ.get("GOOGLE_TTS_VOICE", "ja-JP-Neural2-B")  # natural JP female
GOOGLE_TTS_SPEAKING_RATE = float(os.environ.get("GOOGLE_TTS_RATE", "1.05"))
OPENAI_TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "onyx")

# ---- Models -----------------------------------------------------------------
SCRIPT_MODEL = os.environ.get("SCRIPT_MODEL", "gpt-4o")
STABILITY_ENDPOINT = "https://api.stability.ai/v2beta/stable-image/generate/core"

# ---- Genres -----------------------------------------------------------------
# publish_hour is JST (Asia/Tokyo) derived from the research (median-view peak).
GENRES = {
    "space": {
        "key": "space",
        "label": "宇宙・科学解説",
        "publish_hour_jst": 19,
        "youtube_category_id": "27",   # Education
        "image_style": (
            "cinematic ultra-detailed space and science illustration, deep cosmos, "
            "nebulae, planets, galaxies, realistic astrophotography style, dramatic "
            "lighting, 8k, no text, no watermark"
        ),
        "topic_seed_prompt": (
            "日本のYouTubeで再生数が伸びやすい『宇宙・科学解説』の長尺動画テーマを1つ提案してください。"
            "視聴者の知的好奇心を強く刺激し、8〜10分でしっかり語れる具体的で意外性のあるテーマにしてください。"
            "実在の存命人物の肖像を必要としない、事実ベースで語れるテーマにすること。"
        ),
        "narration_style": "落ち着いた知的なトーンで、視聴者に語りかけるように。専門用語はかみ砕いて説明する。",
        "tags": ["宇宙", "科学", "解説", "宇宙の謎", "天文", "サイエンス", "ゆっくり解説風", "宇宙開発"],
    },
    "urban": {
        "key": "urban",
        "label": "都市伝説解説",
        "publish_hour_jst": 20,
        "youtube_category_id": "24",   # Entertainment
        "image_style": (
            "moody atmospheric mysterious illustration, dark cinematic tone, fog, "
            "eerie symbolic imagery, dramatic shadows, film grain, 8k, no text, no watermark"
        ),
        "topic_seed_prompt": (
            "日本のYouTubeで再生数が伸びやすい『都市伝説・ミステリー解説』の長尺動画テーマを1つ提案してください。"
            "8〜10分で語れる、興味を強く引く題材にしてください。特定の実在人物を誹謗中傷しない、"
            "エンタメとして楽しめる内容にすること。"
        ),
        "narration_style": "少しミステリアスで引き込むトーン。緊張感を持たせつつ聞き取りやすく。",
        "tags": ["都市伝説", "ミステリー", "解説", "怖い話", "不思議", "オカルト", "考察"],
    },
}

# Rotation order when running in "alternate" mode.
ROTATION = ["space", "urban"]
# Phase offset for date-based rotation (--rotate-date). Chosen so 2026-08-15
# resolves to "space" (the first hand-posted video) and the next day to
# "urban", keeping the automated schedule alternating in step with it.
ROTATION_PHASE = int(os.environ.get("ROTATION_PHASE", "1"))
DEFAULT_GENRE = "space"   # ユーザー指定: まず宇宙・科学から

# ---- Upload -----------------------------------------------------------------
# "private" + publishAt => YouTube schedules it public at that time.
UPLOAD_PRIVACY = "private"
