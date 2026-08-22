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

# ---- Teaser short ("CM" for a long-form) ------------------------------------
# Per-genre copy for the teaser. Everything here used to be hard-coded for the
# mystery channel ("事件の全貌・結末は本編で"), which reads as nonsense under a
# sleep explainer and, worse, skipped the medical gate. Keep the mystery values
# byte-identical to what shipped so its shorts do not change.
TEASER_PROFILES = {
    "sleep": {
        "framing": "長尺の睡眠・いびき解説動画",
        "hook": ("冒頭3秒で「隣のいびきで夜中に目が覚めてしまう」という具体的な場面描写から入る"
                 "(挨拶は一切しない)。夜に見る人を想定し、不安をあおらない。"),
        "withhold": "気づきのきっかけまでは見せ、具体的な手順の全体は本編に残す。",
        "cta_spoken": "最後に「続きと具体的な手順は本編で。概要欄と固定コメントのリンクから」と本編へ誘導する。",
        "image_hint": ("夜の寝室の静かな情景を1文で具体的に。人物の顔は写さない。"
                       "暗い紺とチャコールの落ち着いた色調で、不安をあおる表現は避ける。"),
        "desc_cta": "▼ 具体的な手順と受診の目安は本編で（約10分）",
        "comment_cta": "👇 続きと具体的な手順はこちら（本編・約10分）",
        "hashtags": ["#Shorts", "#いびき", "#睡眠", "#睡眠時無呼吸", "#快眠"],
    },
}
TEASER_DEFAULT = TEASER_PROFILES["sleep"]


def teaser_profile(genre_key: str) -> dict:
    """Teaser copy for a genre. Only the sleep channel lives on this branch."""
    return TEASER_PROFILES.get(genre_key, TEASER_DEFAULT)


# ---- Teaser short geometry --------------------------------------------------
SHORT_W, SHORT_H = 1080, 1920   # vertical 9:16 (YouTube Shorts)
SHORT_NUM_IMAGES = 6            # fewer, punchy scenes for a ~50s teaser
SHORT_FONT_SIZE = 36            # larger burned subtitles for vertical/mobile
TEASER_TARGET_CHARS = 170       # ~45-55s of narration

# ---- TTS --------------------------------------------------------------------
# provider: "google" (chosen) with fallback "openai" for smoke tests.
TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "google")
# Chirp3-HD is Google's newest JP tier (30 voices) and is markedly less
# mechanical than Neural2, which the narration was judged on. Chirp3-HD takes
# plain text and speakingRate exactly as Neural2 did — the only thing that
# changes is the voice name — but it does not accept SSML, so keep synthesis
# on input.text. Higher billing tier than Neural2.
GOOGLE_TTS_VOICE = os.environ.get("GOOGLE_TTS_VOICE", "ja-JP-Chirp3-HD-Umbriel")  # calm JP male
GOOGLE_TTS_SPEAKING_RATE = float(os.environ.get("GOOGLE_TTS_RATE", "1.05"))
OPENAI_TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "onyx")

# ---- Models -----------------------------------------------------------------
SCRIPT_MODEL = os.environ.get("SCRIPT_MODEL", "gpt-4o")
STABILITY_ENDPOINT = "https://api.stability.ai/v2beta/stable-image/generate/core"

# ---- Genres -----------------------------------------------------------------
# publish_hour is JST (Asia/Tokyo) derived from the research (median-view peak).
GENRES = {
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
        # Which channel this genre is allowed to post to. Declaring it here
        # rather than in an environment variable is deliberate: an env var has
        # to be remembered, and twice now it was not — a shared environment got
        # one channel's token written over another's and nothing noticed until
        # the upload was already scheduled. A value in the code cannot be
        # forgotten, travels with `git pull`, and is reviewable in a diff.
        # When set, the check is mandatory: the run aborts before uploading if
        # the credentials authorise a different channel.
        "channel_id": "UCrCoZaskQrz6nBkRmS1SAJQ",   # 睡眠・安眠チャンネル2
        "image_style": (
            "calm dark nocturnal illustration, deep navy and charcoal tones, soft "
            "low-key lighting, quiet bedroom and night-time imagery, clean medical "
            "diagram aesthetic, restful and non-alarming, subtle grain, 8k, "
            "no text, no watermark, no faces"
        ),
        # One seed prompt asked the same question every run, so the model kept
        # returning the same few topics and _is_duplicate rejected them until the
        # retry budget ran out (seen at video 3, with only 2 videos to avoid).
        # Rotating an axis in widens the well without moving the audience: every
        # entry is still a problem the partner of a snorer has, not the snorer.
        "topic_axes": [
            "いびきが鳴る仕組みと、単純いびきと睡眠時無呼吸の違い",
            "隣で寝ている人が気づける観察のポイント（呼吸の止まり方、体位、時間帯）",
            "寝室の環境づくり（音・光・温度・湿度・寝具の配置）",
            "音から自分を守る方法（耳栓やホワイトノイズの選び方と、その限界）",
            "同じ部屋で寝るか、別室にするかの判断と、その関係への影響",
            "相手を責めずに切り出す伝え方と、受診をすすめる会話の進め方",
            "受診の実際（何科にかかるか、簡易検査と精密検査の流れ）",
            "治療にどんな選択肢があるかの全体像（効果を断定せず、種類の紹介にとどめる）",
            "生活習慣といびきの関係（体重・飲酒・喫煙・就寝前の習慣）",
            "寝る姿勢と枕（横向き寝、枕の高さ）",
            "起こされる側の睡眠負債と、日中への影響、自分自身のケア",
            "経過の記録のとり方（録音やアプリ、受診時に役立てる残し方）",
            "家族の年代によるいびきの違い（子ども、高齢の家族で気をつける点）",
            "季節や体調による変動（鼻づまり、花粉、風邪をひいたとき）",
            "いびきをきっかけに気づかれることがある他の睡眠の問題（歯ぎしり、脚のむずむず、寝言）",
        ],
        # 15, not 14: the rotation steps by calendar day and the schedule repeats
        # weekly, so an axis count sharing a factor with 7 makes each weekday
        # revisit the same few axes forever. 14 reached only 6 of them. 15 is
        # coprime with 7, so every weekday walks the whole list.
        "topic_seed_prompt": (
            "『いびき・睡眠時無呼吸・夜中の目覚め』をテーマにした、日本のYouTube長尺解説動画の"
            "テーマを1つ提案してください。\n"
            "【最重要】視聴者は『いびきをかく本人』ではなく、"
            "『隣で寝ていて、いびきに毎晩起こされている家族・パートナー』です。"
            "その人が深夜にスマホで検索する具体的な悩みを題材にしてください。\n"
            "40〜50代が対象。8〜10分で語れる具体的なテーマにすること。\n"
            "医学的に確認できる範囲で語れる題材にし、特定商品の効能を主張する題材は避けること。"
        ),
        # narration_style is injected into EVERY chapter prompt, so it must describe
        # voice only. An opening instruction lived here and made all 8 chapters open
        # with the same sentence; it now lives in opening_style, used for ch.1 only.
        "opening_style": (
            "冒頭は挨拶をせず、『隣のいびきで夜中に目が覚めてしまう』という具体的な場面描写から入る。"
        ),
        "narration_style": (
            "落ち着いた低めのトーンで、夜に聞いても不安をあおらないように語る。"
            "断定を避け、『〜と報告されています』『〜という研究があります』と出典ベースで話す。"
            "視聴者を診断せず、判断が必要な場面では医療機関への相談を促す。"
            "専門用語は必ずかみ砕いて言い換える。"
        ),
        "tags": ["いびき", "睡眠", "睡眠時無呼吸", "中途覚醒", "自律神経", "熟睡",
                 "40代", "50代", "睡眠の質", "不眠", "いびき対策", "快眠"],
        # Prepended to every description, above the LLM-written summary. The
        # affiliate line has to sit in the first two lines to survive YouTube's
        # description fold on mobile.
        "playlist_title": "いびきに悩む家族のための睡眠ガイド",
        "playlist_description": (
            "隣のいびきで眠れない家族・パートナーに向けた解説シリーズ。"
            "観察のしかた、寝室の整え方、受診の目安までを1本ずつ扱います。"
        ),
        "description_prefix": (
            "隣のいびきで眠れない夜に。原因の見分け方から受診の目安まで、"
            "40代・50代向けに具体的にお話しします。\n"
        ),
    },
}

# This branch drives ONE channel: 睡眠・安眠チャンネル2.
#
# The entertainment channel's genres (space / urban / mystery) used to live in
# this same file, and twice that came close to costing a channel: a run started
# in this environment would have built one of them and tried to upload it here.
# They are removed from this branch rather than commented out — a commented-out
# genre is one uncomment away from shipping. They remain on the branch that
# serves that channel, and in this file's history.
#
# Consequently there is nothing to rotate between. --alternate and --rotate-date
# still work; they resolve to the only genre there is.
ROTATION = ["sleep"]
ROTATION_PHASE = int(os.environ.get("ROTATION_PHASE", "0"))
DEFAULT_GENRE = "sleep"

# ---- Upload -----------------------------------------------------------------
# "private" + publishAt => YouTube schedules it public at that time.
UPLOAD_PRIVACY = "private"
