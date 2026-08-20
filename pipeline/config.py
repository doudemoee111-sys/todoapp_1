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

# ---- Ambient / sleep long-form ----------------------------------------------
# L2 (masking noise) and L3 (narrated intro + ambient bed) are rendered by
# ambient.py, not assemble.py: their length comes from the audio, not from a
# narration, and hours of Ken Burns is not renderable. See ambient.py.
AMBIENT_SECONDS = int(os.environ.get("AMBIENT_SECONDS", "10800"))   # L2 total, 3h to start
AMBIENT_FPS = 1                 # a still image needs no more; keeps the file small
AMBIENT_CRF = 30
AMBIENT_LOOP_SECONDS = 60       # video encoded once at this length, then stream-copied
AMBIENT_AUDIO_BITRATE = "128k"
AMBIENT_TARGET_LUFS = -23       # deliberately quiet: this plays all night, in a bedroom
GUIDE_NUM_IMAGES = 10           # L3 intro: fewer images than a full explainer
GUIDE_NARRATION_CHARS = 3000    # ~9-10 min spoken before the bed takes over
GUIDE_AMBIENT_SECONDS = int(os.environ.get("GUIDE_AMBIENT_SECONDS", "7200"))  # 2h tail

# ---- Teaser short ("CM" for a mystery long-form) ----------------------------
SHORT_W, SHORT_H = 1080, 1920   # vertical 9:16 (YouTube Shorts)
SHORT_NUM_IMAGES = 6            # fewer, punchy scenes for a ~50s teaser
SHORT_FONT_SIZE = 36            # larger burned subtitles for vertical/mobile
TEASER_TARGET_CHARS = 170       # ~45-55s of narration

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
    "mystery": {
        "key": "mystery",
        "label": "未解決事件・ミステリー解説",
        "publish_hour_jst": 19,
        "youtube_category_id": "24",   # Entertainment
        "narration_target": 3900,      # ~15 min of JP narration
        "image_style": (
            "dark cinematic documentary illustration, moody atmospheric, muted "
            "desaturated tones, fog and deep shadow, film grain, tense mysterious "
            "mood, realistic, 8k, no text, no watermark"
        ),
        "topic_seed_prompt": (
            "日本のYouTubeで再生数が伸びやすい『未解決事件・ミステリー解説』の長尺動画テーマを1つ提案してください。"
            "実在の未解決事件・失踪・謎の現象など、公表された事実をもとに約15分しっかり語れて、"
            "意外性と考察の余地がある題材にすること。存命の個人を誹謗中傷せず、事実の範囲で扱えるテーマにすること。"
        ),
        "narration_style": (
            "落ち着いた低めのトーンで、緊張感を保ちながら語る。冒頭は挨拶を一切せず、"
            "事件の核心や結末の一部をチラ見せして視聴者を引き込む。『謎の提示→状況説明→"
            "意外な事実の発覚→結論と独自の考察』という起承転結のストーリーテリングで構成する。"
        ),
        "tags": ["未解決事件", "ミステリー", "解説", "都市伝説", "謎", "考察", "実話", "怖い話", "事件"],
    },
    # --- Sleep channel -------------------------------------------------------
    # Posted to its OWN channel (separate YOUTUBE_REFRESH_TOKEN), not mixed in
    # with space/urban/mystery: YouTube learns a viewer cluster per channel, and
    # 40-50s looking for snoring help have nothing in common with the audience
    # for unsolved-mystery videos. Mixing them costs both sides their CTR.
    #
    # The audience is written for deliberately: not the person who snores, but
    # the partner being kept awake by it. That person is the one searching at
    # 2am, the one who buys, and the one who shows the video to the snorer.
    # Every competitor writes to the snorer.
    "sleep": {
        "key": "sleep",
        "label": "睡眠・いびき解説",
        "publish_hour_jst": 21,        # the target audience is heading to bed
        "youtube_category_id": "26",   # Howto & Style
        "narration_target": 3200,      # ~9-11 min
        # Turns on compliance.py. Without this key the gate is skipped entirely,
        # which is how the existing genres stay unaffected.
        "compliance": "medical",
        "image_style": (
            "calm dark nocturnal illustration, deep navy and charcoal tones, soft "
            "low-key lighting, quiet bedroom and night-time imagery, clean medical "
            "diagram aesthetic, restful and non-alarming, subtle grain, 8k, "
            "no text, no watermark, no faces"
        ),
        "topic_seed_prompt": (
            "『いびき・睡眠時無呼吸・夜中の目覚め』をテーマにした、日本のYouTube長尺解説動画の"
            "テーマを1つ提案してください。\n"
            "【最重要】視聴者は『いびきをかく本人』ではなく、"
            "『隣で寝ていて、いびきに毎晩起こされている家族・パートナー』です。"
            "その人が深夜にスマホで検索する具体的な悩みを題材にしてください。\n"
            "40〜50代が対象。8〜10分で語れる具体的なテーマにすること。\n"
            "医学的に確認できる範囲で語れる題材にし、特定商品の効能を主張する題材は避けること。"
        ),
        "narration_style": (
            "落ち着いた低めのトーンで、夜に聞いても不安をあおらないように語る。"
            "冒頭は挨拶をせず、『隣のいびきで夜中に目が覚めてしまう』という具体的な場面描写から入る。"
            "断定を避け、『〜と報告されています』『〜という研究があります』と出典ベースで話す。"
            "視聴者を診断せず、判断が必要な場面では医療機関への相談を促す。"
            "専門用語は必ずかみ砕いて言い換える。"
        ),
        "tags": ["いびき", "睡眠", "睡眠時無呼吸", "中途覚醒", "自律神経", "熟睡",
                 "40代", "50代", "睡眠の質", "不眠", "いびき対策", "快眠"],
        # Prepended to every description, above the LLM-written summary. The
        # affiliate line has to sit in the first two lines to survive YouTube's
        # description fold on mobile.
        "description_prefix": (
            "▼ いびき・睡眠の記録に使えるものと、受診の目安はこちら\n"
            "（リンクは順次このチャンネルの固定コメントにも掲載します）\n"
        ),
    },
}

# Rotation order when running in "alternate" mode.
# The sleep genre is deliberately absent: it lives on its own channel and its
# schedule is driven by four dedicated cron triggers (L1 火/土, L3 木, L2 日),
# not by the day-of-week rotation used by the entertainment channel.
ROTATION = ["space", "urban"]
# Phase offset for date-based rotation (--rotate-date). Chosen so 2026-08-15
# resolves to "space" (the first hand-posted video) and the next day to
# "urban", keeping the automated schedule alternating in step with it.
ROTATION_PHASE = int(os.environ.get("ROTATION_PHASE", "1"))
DEFAULT_GENRE = "space"   # ユーザー指定: まず宇宙・科学から

# ---- Upload -----------------------------------------------------------------
# "private" + publishAt => YouTube schedules it public at that time.
UPLOAD_PRIVACY = "private"
