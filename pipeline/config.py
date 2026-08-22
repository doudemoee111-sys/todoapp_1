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

# ---- Channel guard (別組織の睡眠チャンネルへの誤投稿を防ぐ安全装置) -----------
# この自動化が投稿してよいのは「世界の雑学王」チャンネルだけ。睡眠チャンネルは
# 別組織・別プロジェクトで管理しており、ここからは絶対に投稿しない。認証トークンが
# 万一この期待チャンネル以外を指していたら、check_auth / アップロード時に停止する。
# 名称ゆらぎに備え env で上書き可（YOUTUBE_EXPECTED_CHANNEL）。空文字にすると無効化。
EXPECTED_CHANNEL_TITLE = os.environ.get("YOUTUBE_EXPECTED_CHANNEL", "世界の雑学王")

# ---- Video spec -------------------------------------------------------------
VIDEO_W, VIDEO_H = 1920, 1080
FPS = 30
NUM_IMAGES = 30                 # "画像多め": ~30 scene images per video
TARGET_MIN_SECONDS = 480        # 8 minutes minimum
NARRATION_TARGET_CHARS = 3200   # ~8-10 min of JP narration at normal TTS speed

# ---- Teaser short ("CM" for a mystery long-form) ----------------------------
SHORT_W, SHORT_H = 1080, 1920   # vertical 9:16 (YouTube Shorts)
SHORT_NUM_IMAGES = 8            # scene variety for a ~55s substantive teaser
SHORT_FONT_SIZE = 66            # burned-subtitle size in TRUE px (ASS PlayRes=1080x1920)
SHORT_SUB_MAXLEN = 12           # split vertical captions short so each fits one line
# 実測: 区切りごとの合成では 304字=61.1秒 ≈ 約5.0字/秒。60秒制限に収めるため
# 280字前後(≈56秒)を目標にする(組み立て時に末尾+0.5秒の余白が付くため余裕を持たせる)。
# 予告編は「ただの誘導」ではなく、具体的な引き(事実・エピソード)を2〜3個入れて
# 単体でも面白い尺にするため、170→280字に拡張(_ensure_teaser_lengthで下限も担保)。
TEASER_TARGET_CHARS = 280       # ~56s: hook + 具体的な引き2〜3個 + 寸止め + CTA

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
}

# ---- Branch scope guard (別ブランチ=睡眠チャンネルのジャンル混入を無料で停止) -----
# このブランチ(claude/web-automation-setup-ifetgk)は「世界の雑学王」専用。睡眠チャンネル
# は別組織・別ブランチ(claude/youtube-sleep-content-automation-4k28y3)で管理され、その
# ジャンル(sleep 等)はここには存在しない。睡眠部門がコード側で当チャンネルのジャンル
# (space/urban/mystery)を弾いたのと対になる相互アイソレーションとして、こちらでは睡眠系
# ジャンルを弾く。万一この環境に睡眠側のトリガーが混ざって sleep を要求してきても、API を
# 一切叩かず(=1円も使わず)に停止する。チャンネルガード(EXPECTED_CHANNEL_TITLE)と二段構え。
BRANCH_LABEL = "世界の雑学王"
FOREIGN_GENRE_OWNERS = {
    "sleep": "睡眠・安眠チャンネル2（別組織・別ブランチ claude/youtube-sleep-content-automation-4k28y3）",
    "ambient": "睡眠・安眠チャンネル2（別組織・別ブランチ）",
    "narrated": "睡眠・安眠チャンネル2（別組織・別ブランチ）",
    "guide": "睡眠・安眠チャンネル2（別組織・別ブランチ）",
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
