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
        # 15切り口では、1切り口あたり年24本。同じ観点を月2回書けば、
        # 題材は必ず擦り切れる。細分化は収益導線の話に見えて、実際には
        # まず originality の話になっている。
        # 収益面では、提携済みの寝具3件が乗る枠が1つ（旧9）しかなく、
        # 3件を1回に並べると推薦ではなく物販に見えるため出し分けられなかった。
        # 分割後は寝具が3枠（5・7・8）に分かれ、1回1〜2件で成立する。
        # ★この配列の並び順は assets/affiliate_links.json の axes（添字）が
        #   指している。並べ替え・挿入・削除をしたら、必ず同ファイルの
        #   axes と axis_keys を更新すること。affiliate.check_axis_map() が
        #   実行前に照合し、ずれていれば止まる。
        "topic_axes": [
            "いびきが鳴る仕組みと、単純いびきと睡眠時無呼吸の違い",
            "隣で寝ている人が気づける観察のポイント（呼吸の止まり方、体位、時間帯）",
            "経過の記録のとり方（録音やアプリ、受診時に役立てる残し方）",
            "寝室の音環境（生活音、壁とドア、ベッドの位置関係）",
            "寝室の光・温度・湿度の整え方",
            "寝床を分ける工夫（ベッドを2台にする、掛け布団を分ける、部屋の使い方）",
            "横向きの姿勢を保つ工夫（抱き枕、背中側の支え、寝返りとの兼ね合い）",
            "枕の高さと素材の選び方（首の角度、寝返りのしやすさ）",
            "マットレスの硬さと沈み込みが寝姿勢に与えること",
            "音から自分を守る方法（耳栓やホワイトノイズの選び方と、その限界）",
            "同じ部屋で寝るか、別室にするかの判断と、その関係への影響",
            "相手を責めずに切り出す、最初の会話の進め方",
            "受診に気が進まない相手と、どう話を続けるか",
            "起こされる側の睡眠負債と、日中への影響",
            "起こされる側自身の休息のとり方（仮眠、週末の回復、寝る時間帯の工夫）",
            "我慢が限界に近づくとき、関係のこじれ方と距離のとり方",
            "何科にかかるか、受診前に用意しておくもの",
            "自宅でできる簡易検査の流れと、結果の見方の基本",
            "精密検査（終夜睡眠ポリグラフ）と、診断がついたあとの流れ",
            "CPAPという選択肢の概要（仕組みと、日々の運用で語られること）",
            "マウスピース（口腔内装置）という選択肢の概要",
            "鼻や喉の要因と外科的な選択肢の概要（鼻づまり、扁桃）",
            "体重・首まわりといびきの関係",
            "飲酒・喫煙と、就寝前の習慣",
            "鼻呼吸と口呼吸、口まわりの習慣",
            "子どものいびきで気をつける点",
            "高齢の家族のいびきと、加齢による変化",
            "女性の年代による変化（更年期前後で語られること）",
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

    # --- Bedroom measurement (D-1) ------------------------------------------
    # Same channel, same audience, different footing.
    #
    # Why this exists: the sleep genre above talks about a body — snoring, apnea,
    # symptoms — and that put every script inside 薬機法 and the 医療広告
    # ガイドライン. Four weeks of it cost nine dictionary patches, three aborted
    # runs, and a steady pressure towards vague titles, because the only safe way
    # to say "this helps you sleep" is to say nothing. 2 subscribers and 226 views
    # over 17 videos is the result.
    #
    # This genre talks about a ROOM and the OBJECTS in it: decibels, lux, degrees,
    # centimetres, newtons. None of that is a medical claim, so the gate stops
    # firing — and, far more importantly, every video can carry a number the
    # channel owner measured themselves. That measured number is the one thing a
    # mass-produced catalogue cannot have, and it is the direct answer to the
    # AI judgment this channel received in August.
    #
    # The compliance gate stays ON. Removing the pressure is not the same as
    # removing the guard: "この枕でいびきが改善" is exactly the sentence a writer
    # drifts into on axis 12, and it is still a 薬機法 violation here.
    #
    # ★ Same index contract as sleep: assets/affiliate_links.json targets.room
    #   indexes into this list, pinned by keyword. affiliate.check_axis_map()
    #   stops the run if they drift apart.
    "room": {
        "key": "room",
        "label": "寝室の実測",
        "publish_hour_jst": 21,
        "youtube_category_id": "26",   # Howto & Style
        "narration_target": 3200,
        "compliance": "medical",
        # Turns on measurement.py. Without it the measurement machinery is
        # inert — which is what the sleep genre needs, and what it did not get
        # on 2026-10-06: the no-data framing was injected into every genre, so a
        # sleep video came out as a decibel-methodology piece wearing a sleep
        # description. The flag exists so that never depends on remembering.
        "measurement_based": True,
        "channel_id": "UCrCoZaskQrz6nBkRmS1SAJQ",   # 睡眠・安眠チャンネル2
        # Measured data is the point of this genre, so it must be visible: the
        # instruments, the readings, the room. Brighter than the sleep genre's
        # night imagery because a measurement video is watched awake, and the
        # thumbnails moved to a bright palette for the same reason.
        "image_style": (
            "clean documentary photograph of a quiet Japanese bedroom and its "
            "objects, soft daylight through a window, measuring instruments on a "
            "nightstand, pale warm neutrals with muted teal accents, calm and "
            "uncluttered, shallow depth of field, 8k, no text, no watermark, "
            "no faces, no people"
        ),
        # 30 axes, coprime with 7, so the weekly schedule walks the whole list
        # instead of revisiting six of them forever.
        "topic_axes": [
            "寝室の騒音を測る（測り方、単位、どの時間帯に何が鳴っているか）",
            "壁・ドア・窓から入る音を、どこから入っているか測り分ける",
            "隣の寝息やいびきが届く経路（壁越しと空気を伝わる分の違い）",
            "耳栓の遮音値（NRR・SNR）の読み方と、実際に測った値との差",
            "耳栓の素材ごとの付け心地と、一晩つけたあとの状態",
            "ホワイトノイズ機器やアプリの音量を測る（何デシベルで何が覆われるか）",
            "寝室の温度を測る（就寝時から朝までの推移）",
            "寝室の湿度を測る（加湿器のあるなしでの推移）",
            "エアコンの設定温度と、実際の枕元の温度の差",
            "寝室の明るさを測る（ルクス、常夜灯・街灯・家電のランプ）",
            "遮光カーテンの等級と、実際に入ってくる光の量",
            "スマホや時計、家電の待機ランプの明るさと、置き場所",
            "枕の高さを測る（仰向けと横向きでの首の角度の差）",
            "枕の素材ごとの沈み込みと、朝までの復元",
            "マットレスの硬さ（N値）と、沈み込みの実測",
            "マットレスの経年（何年でどれだけへたるか、へたりの測り方）",
            "敷きパッド・ベッドパッドで変わる寝床の温度",
            "掛け布団の重さと、朝までの保温の実測",
            "寝床内の温度と湿度（布団の中の環境を測る）",
            "ベッドの配置と、壁や窓からの距離で変わる音と温度",
            "ベッドを2台に分ける場合の、実際の置き方と寸法",
            "寝返りに必要な幅を測る（シングル・セミダブルの実寸）",
            "ベッドフレームやすのこのきしみ音を測る",
            "加湿器の種類ごとの運転音と、実際の加湿量",
            "空気清浄機・サーキュレーターの運転音（弱運転で何デシベルか）",
            "間接照明と調光で、就寝前1時間の明るさをどう落とすか",
            "寝室の空気（二酸化炭素濃度を測る、換気のあるなし）",
            "季節で変わる寝室環境（夏と冬で何がどれだけ違うか）",
            "集合住宅と戸建てで違う、寝室の音と温度",
            "寝具を買う前に、自分の寝室で測っておくとよい数値",
        ],
        "topic_seed_prompt": (
            "『寝室の環境を実際に測って確かめる』をテーマにした、"
            "日本のYouTube長尺解説動画のテーマを1つ提案してください。\n"
            "【最重要】扱うのは体ではなく、部屋とモノです。"
            "音・光・温度・湿度・寸法・硬さなど、数字で測れるものを題材にしてください。"
            "症状や体への効果を題材にしないこと。\n"
            "視聴者は『隣の人のいびきで眠れず、寝室をどうにかしたいと思っている40〜50代』です。\n"
            "8〜10分で語れる具体的なテーマにすること。"
        ),
        "opening_style": (
            "冒頭は挨拶をせず、測った数字そのものか、測っている場面の描写から入る。"
            "例:『枕元で測ったら、深夜1時の寝室は42デシベルありました。』"
            "一般論の問題提起から入らない。"
        ),
        "narration_style": (
            "落ち着いた低めのトーンで、測定結果を淡々と報告する語り口。"
            "測った条件（いつ・どこで・何で測ったか）を必ず添える。"
            "数字から言えることだけを言い、言えないことは『これは分かりません』とそのまま言う。"
            "体への効果や症状の改善には踏み込まず、必要なら医療機関への相談に渡す。"
            "専門用語は必ずかみ砕いて言い換える。"
        ),
        "tags": ["寝室", "睡眠環境", "快眠グッズ", "騒音", "デシベル", "遮光",
                 "枕", "マットレス", "耳栓", "温湿度", "40代", "50代"],
        # The SAME playlist as the sleep genre, by id. Giving this genre its own
        # title created a second playlist on 2026-10-08, which split a 20-video
        # series from its continuation: the new videos' sibling links carried a
        # &list= that did not contain the videos they pointed at, and a viewer
        # finishing one got nothing to autoplay. To a viewer these are one
        # series about one bedroom; the genre change is an internal matter.
        # Pinned by id so the playlist can be renamed in Studio without
        # splitting it again — only the id is load-bearing now.
        "playlist_id": "PLP9ausaDhr0Q",
        "playlist_title": "いびきに悩む家族のための睡眠ガイド",
        "playlist_description": (
            "寝室の音・光・温度・寸法を実際に測った記録です。"
            "体への効果ではなく、部屋とモノの数字だけを扱います。"
        ),
        "description_prefix": (
            "寝室を実際に測った記録です。測定の条件は概要欄の最後に載せています。\n"
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
ROTATION = ["room"]
ROTATION_PHASE = int(os.environ.get("ROTATION_PHASE", "0"))
DEFAULT_GENRE = "room"

# ---- Upload -----------------------------------------------------------------
# "private" + publishAt => YouTube schedules it public at that time.
UPLOAD_PRIVACY = "private"
