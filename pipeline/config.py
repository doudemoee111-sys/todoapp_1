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
        "publish_hour_jst": 20,   # ミステリー(19時)と初速が食い合わないよう20時に分離
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
        # API実測(2026/10): 未解決事件の勝ち筋は中央32分、ヒットは20〜62分。15分では短い。
        # 自社の0:30保持率61%(風船おじさん事件)＝この形式が最も視聴者を掴めている実証あり。
        # 実測(2026/10/10 怪談 meOKMSYMVrA): 6,000字 → 音声17.3分。日本語TTSは約350字/分
        # なので、20〜25分帯の下限を割らないよう7,600字に引き上げる。
        "narration_target": 7600,      # ~22 min of JP narration
        "image_style": (
            "dark cinematic documentary illustration, moody atmospheric, muted "
            "desaturated tones, fog and deep shadow, film grain, tense mysterious "
            "mood, realistic, 8k, no text, no watermark"
        ),
        # 実測した勝者のタイトル型: 【】を2〜4個／固有名詞で具体化／「…」で寸止め／
        # 権威付け(NASAの研究者が論文に・元捜査一課が明かす)／断定の逆説(UFOは宇宙人じゃない)。
        "title_style": (
            "『【キーワード】＋ 固有名詞を含む具体的な謎 ＋ 「…」で寸止め』の型。"
            "例:「【八王子ナンペイ事件】犯人はここまで絞られていた…未解決30年の真相」"
            "【】は2〜4個使い、末尾に【ゆっくり解説】【未解決事件】等の検索語を足す。"
            "固有名詞(事件名・地名・年代)を必ず前半に置く。虚偽・過度な釣りは禁止。"
        ),
        # 0:30で61%を出した構造を明文化（冒頭で結末の断片を見せて引き込む）。
        "structure_hint": (
            "冒頭15秒で『事件の最も不可解な一点』を提示し結末の断片をチラ見せ→状況と時系列→"
            "捜査で判明した意外な事実を3〜5個→各事実に『なぜ説明がつかないのか』の独自考察→"
            "有力説の比較検証→結論は断定せず視聴者に問いを残す。章ごとに次章への引きを置く。"
        ),
        "topic_seed_prompt": (
            "日本のYouTubeで再生数が伸びやすい『未解決事件・ミステリー解説』の長尺動画テーマを1つ提案してください。"
            "実在の未解決事件・失踪・謎の現象など、公表された事実をもとに約20〜25分しっかり語れて、"
            "意外性と考察の余地がある題材にすること。存命の個人を誹謗中傷せず、事実の範囲で扱えるテーマにすること。"
        ),
        "narration_style": (
            "落ち着いた低めのトーンで、緊張感を保ちながら語る。冒頭は挨拶を一切せず、"
            "事件の核心や結末の一部をチラ見せして視聴者を引き込む。『謎の提示→状況説明→"
            "意外な事実の発覚→結論と独自の考察』という起承転結のストーリーテリングで構成する。"
        ),
        "tags": ["未解決事件", "ミステリー", "解説", "都市伝説", "謎", "考察", "実話", "怖い話", "事件"],
    },
    # japan: 実データでこのチャンネルのショートが最も強いのは「海外が驚く日本の文化・
    # おもてなし・日常」系(号泣/おしぼり/トイレの清潔さ 等が1,100〜1,200再生)。現登録者は
    # この“日本のここがすごい／海外の反応”層。宇宙長尺(平均81再生)と層がズレているため、
    # 視聴者に合った長尺として週1でテスト投入する。
    "japan": {
        "key": "japan",
        "label": "海外が驚く日本の文化・雑学",
        "publish_hour_jst": 20,
        "youtube_category_id": "24",   # Entertainment
        "image_style": (
            "warm cinematic photoreal illustration of everyday and traditional Japan, "
            "clean and tasteful, Japanese streets, food, craftsmanship, hospitality and "
            "daily life, soft natural light, high detail, 8k, no text, no watermark"
        ),
        "topic_seed_prompt": (
            "日本のYouTubeで再生数が伸びやすい『海外が驚く日本の文化・おもてなし・日常の雑学』の"
            "長尺動画テーマを1つ提案してください。当チャンネルはショートで"
            "「海外の人が感動する日本の駅・おしぼり文化・トイレの清潔さ」等の"
            "“日本のここがすごい／海外の反応”系が実際に強く伸びています。その路線で、"
            "8〜10分しっかり語れて、具体的な事例・数字・海外との対比を複数盛り込める、"
            "意外性のあるテーマにしてください。特定の実在人物を扱わず、事実ベースで語れること。"
        ),
        "narration_style": (
            "明るく誇らしいトーンで、視聴者が『日本ってすごい』と再発見できるように語りかける。"
            "冒頭は挨拶を省き、海外の人が驚いた具体エピソードや数字を結論先出しでチラ見せして引き込む。"
            "『海外の驚き→なぜ日本では当たり前なのか→歴史・文化的背景→現代の具体事例→まとめ』で構成する。"
        ),
        # 海外の反応/日本称賛ジャンルで実証済みのタイトル型（【海外の反応】＋具体題材＋ギャップ語）。
        "title_style": (
            "『【海外の反応】＋ 具体的な日本の題材（駅／おしぼり／ゴミ分別／接客／コンビニ 等）＋ "
            "ギャップ語（別次元／合理的すぎ／なぜ／衝撃／世界がざわついた）』の型。28文字以内で、"
            "前半に具体題材を置く。過度な釣り・虚偽は禁止（釣りサムネは維持率で負ける）。「○選」は使わない。"
        ),
        # このニッチで維持率が出る章構成（15秒フック→複数の具体例→各例に海外反応＋独自解説）。
        "structure_hint": (
            "15秒フックで最も驚く一撃→『海外が驚いた日本の具体例』を章ごとに3〜5個→"
            "各章で海外の反応＋“なぜ日本では当たり前なのか”の独自解説→結論を2〜3回言い直す"
        ),
        "tags": ["日本", "雑学", "海外の反応", "日本文化", "インバウンド", "おもてなし",
                 "日本のここがすごい", "解説", "豆知識"],
    },
    # kaidan: API実測(2026/10)で「登録1万人以下×10万再生超」のヒットが最も多かった唯一の
    # ニッチ（4件／他カテゴリは0〜1件）。コワバナ(4,960登録)が10万超を2本＝再現性あり。
    # 中央尺69分と長く、視聴時間(8,000h)に直結する。
    # ★TTS対策: 勝者の一つ「欄外採録」は“怪異記録アーカイブ”の淡々とした記録調で、
    #   人間の声優的な演技を要求しない。AI音声の弱点を避けるため、この記録調に寄せる。
    # ★著作権: 既存の実話怪談/2ch投稿を転載せず、毎回オリジナルの創作怪談を生成する。
    "kaidan": {
        "key": "kaidan",
        "label": "怪談朗読（創作・記録調）",
        "publish_hour_jst": 22,        # 深夜帯＝作業用/睡眠用の需要が立つ時間
        "youtube_category_id": "24",   # Entertainment
        # 初回(meOKMSYMVrA)は6,000字で17.3分＝目標20〜25分を下回った。350字/分換算で7,600字。
        "narration_target": 7600,      # ~22 min（勝者は16〜48分。まず20分級から）
        "image_style": (
            "dark eerie Japanese night scene, desaturated muted tones, fog, dim "
            "streetlight, empty corridor or old apartment, unsettling stillness, "
            "cinematic film grain, photoreal, no people, 8k, no text, no watermark"
        ),
        # 勝者の型: 【怪談朗読】＋具体的な一話のタイトル＋【作業用／睡眠用BGM】の検索語。
        "title_style": (
            "『【怪談朗読】＋ 具体的で不穏な一話のタイトル ＋【作業用／睡眠用BGM】』の型。"
            "例:「【怪談朗読】誰もいない404号室から足音がする【作業用／睡眠用BGM】」。"
            "数字・部屋番号・時刻など具体的なディテールをタイトルに入れると強い。"
            "総集編なら『全◯話』を明記。虚偽の実話主張はしない（創作である旨は概要欄に記載）。"
        ),
        "structure_hint": (
            "独立した短編を3〜4話のオムニバスで構成し、各話の冒頭に『記録番号・場所・日時』を"
            "淡々と提示する“怪異記録アーカイブ”調にする。感情的な絶叫や過度な演技を前提にせず、"
            "事実を淡々と積み上げることで不気味さを出す。各話は『日常→わずかな違和感→"
            "説明のつかない事象→回収されない結末』で閉じ、次の話へ静かに移る。"
            "★実話と誤認させないこと（初回 meOKMSYMVrA は「2023年10月5日、東京都内」のように"
            "実在の年月日と実在の地名を事実として断定していた）。記録番号・曜日・時刻は具体的に"
            "書いてよいが、年月日は「数年前の秋」「十月のある晩」のようにぼかし、地名は"
            "『北関東のある県営団地』『私鉄沿線のS駅』のように架空化・匿名化する。実在の自治体名・"
            "施設名・事件名は使わない。『これは実際にあった話です』等の実話主張も書かない。"
        ),
        "topic_seed_prompt": (
            "YouTubeの怪談朗読チャンネル向けに、完全オリジナルの創作怪談のテーマを1つ提案してください。"
            "既存の実話怪談・ネット上の投稿・著名な怪談作品の転載や翻案は絶対に避け、独自の設定にすること。"
            "日本の日常（団地・駅・学校・病院・山道・社宅など）に潜むわずかな違和感から始まり、"
            "説明のつかない事象へ静かに展開する題材。約20〜25分で3〜4話のオムニバスにできること。"
            "実在の個人・団体を特定できる形では扱わない。"
        ),
        "narration_style": (
            "低く落ち着いた、淡々とした記録調で読み上げる。絶叫・過剰な抑揚は使わない。"
            "怖がらせようとせず、事実を淡々と report するほど不気味さが増す語り口にする。"
            "冒頭の挨拶は省き、1話目の記録番号と状況説明から静かに入る。"
        ),
        "tags": ["怪談", "怪談朗読", "作業用BGM", "睡眠用BGM", "怖い話", "都市伝説",
                 "ホラー", "朗読", "オリジナル怪談"],
        # 実話と誤認させないための明示（概要欄に自動付与）。
        "description_note": (
            "\n\n※この作品はすべて創作（フィクション）です。実在の人物・団体・事件とは"
            "一切関係ありません。実話として投稿されたものではありません。"
        ),
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

# ---- Long-session soundscape (作業用BGM / 環境音) ----------------------------
# 戦略シフト(視聴時間効率): watch hours = 再生数 × 平均視聴時間。1〜3時間の環境音は
# 1再生あたりの視聴“時間”が短尺雑学の20〜40倍で、言語の壁がなく evergreen。収益化の
# 核心として最重要なのは「音源が完全自作（ffmpegのノイズ＋トーン合成）」である点——
# 既存曲のContent-IDに一致しようがなく、作業用/集中/リラックスという実需の付加価値が
# あるため、YouTube 2025「量産型」ポリシーにも抵触しにくい。毎回ミックスを乱数で振って
# テンプレ複製化を避ける。画像はStability1枚（失敗時はffmpegグラデにフォールバック）。
# これは「世界の雑学王」の長時間型転換用。睡眠チャンネル(別組織・別ブランチ)の
# ambient/sleep ジャンルとは別物として、独立したキー soundscape で管理する。
SOUNDSCAPE_CATEGORY_ID = os.environ.get("SOUNDSCAPE_CATEGORY_ID", "10")  # Music
SOUNDSCAPE_PUBLISH_HOUR_JST = int(os.environ.get("SOUNDSCAPE_PUBLISH_HOUR_JST", "20"))
SOUNDSCAPE_DEFAULT_SECONDS = int(os.environ.get("SOUNDSCAPE_SECONDS", "10800"))  # 3h
SOUNDSCAPE_PLAYLIST_TITLE = "【作業用BGM・環境音】集中できる世界の音"
SOUNDSCAPE_COMMON_TAGS = [
    "作業用BGM", "環境音", "集中", "勉強用BGM", "リラックス", "睡眠用BGM",
    "作業用", "ヒーリング", "癒し", "ambient", "白noise", "world sounds",
]
# theme: 音の処方(audio recipe)＋静止画プロンプト＋表示名。audio は soundscape.py が
# このキーで ffmpeg フィルタグラフを組む。brand の橋渡しとして「世界の○○」に寄せる。
SOUNDSCAPE_THEMES = {
    # 各テーマに word(サムネ用の短い語)・bg(グラデ2色 上→下)・accent(テキスト差し色)を
    # 持たせる。Stability残高切れ(402)でも、テーマごとに配色の違う静止画＋日本語テキスト
    # 入りサムネを自前生成できるようにするため(=画像が毎回同じに見える問題の解消)。
    "rain": {
        "label": "雨音", "title_core": "雨の音", "word": "雨 の 音",
        "bg": ("#0b1a2a", "#2a5c86"), "accent": "#9fd0ff",
        "image_prompt": ("rain streaming down a dark window at night, soft bokeh city "
                         "lights beyond, cozy calm cinematic, moody blue tones"),
        "tags": ["雨音", "雨の音", "rain sounds", "雨"],
    },
    "waves": {
        "label": "波の音", "title_core": "波の音", "word": "波 の 音",
        "bg": ("#07222e", "#1f6b7a"), "accent": "#aef0ee",
        "image_prompt": ("a calm ocean shore at dusk, gentle waves, soft golden and "
                         "indigo sky, serene minimal cinematic, wide horizon"),
        "tags": ["波の音", "海", "ocean waves", "波音"],
    },
    "fire": {
        "label": "焚き火", "title_core": "焚き火の音", "word": "焚き火",
        "bg": ("#160d07", "#7a3f18"), "accent": "#ffc489",
        "image_prompt": ("a warm crackling campfire at night, glowing embers, soft "
                         "bokeh, cozy cinematic, deep warm orange tones"),
        "tags": ["焚き火", "焚き火の音", "campfire", "暖炉"],
    },
    "forest": {
        "label": "森のせせらぎ", "title_core": "森と小川の音", "word": "森 の 音",
        "bg": ("#0c1f18", "#226b45"), "accent": "#b6f0c4",
        "image_prompt": ("a misty green forest with a gentle clear stream, soft morning "
                         "light through trees, tranquil cinematic, lush nature"),
        "tags": ["森", "川のせせらぎ", "自然音", "forest"],
    },
    "night": {
        "label": "夜の静けさ", "title_core": "夜の虫の音", "word": "夜 の 静けさ",
        "bg": ("#0b0e1c", "#35336b"), "accent": "#c7c3ff",
        "image_prompt": ("a quiet starry countryside night, silhouettes of grass and "
                         "distant hills, deep blue calm sky, serene cinematic"),
        "tags": ["夜の音", "虫の音", "night ambience", "安眠"],
    },
    "brown": {
        "label": "ブラウンノイズ", "title_core": "ブラウンノイズ（集中）", "word": "集中 ノイズ",
        "bg": ("#101214", "#3a3f48"), "accent": "#d8dde4",
        "image_prompt": ("a minimalist calm abstract gradient, soft deep teal and navy, "
                         "smooth subtle grain, serene distraction-free, cinematic"),
        "tags": ["ブラウンノイズ", "brown noise", "集中音", "ホワイトノイズ"],
    },
    # テーマを増やして、グリッドでの見た目の重複(同じサムネの連発)を減らす。
    "wind": {
        "label": "風の音", "title_core": "高原の風の音", "word": "風 の 音",
        "bg": ("#0e1620", "#415a70"), "accent": "#cfe0ee",
        "image_prompt": ("windswept grassy highland under a vast sky, soft moving clouds, "
                         "serene cinematic, muted cool tones, gentle motion"),
        "tags": ["風の音", "wind sounds", "自然音", "ホワイトノイズ"],
    },
    "river": {
        "label": "渓流の音", "title_core": "渓流のせせらぎ", "word": "渓流",
        "bg": ("#07211c", "#1f7a5e"), "accent": "#a9f0d8",
        "image_prompt": ("a clear mountain stream rushing over mossy rocks, lush green, "
                         "dappled sunlight, fresh vivid cinematic"),
        "tags": ["渓流", "川の音", "water sounds", "自然音"],
    },
    "thunder": {
        "label": "雨と雷", "title_core": "雨と遠雷の音", "word": "雨 と 雷",
        "bg": ("#0a0e1a", "#2b3457"), "accent": "#aab6e0",
        "image_prompt": ("rainy night cityscape with soft distant lightning glow on the "
                         "clouds, moody atmospheric cinematic, deep blue tones"),
        "tags": ["雨の音", "雷の音", "thunderstorm", "安眠"],
    },
    "snow": {
        "label": "雪の夜", "title_core": "雪の降る夜の静けさ", "word": "雪 の 夜",
        "bg": ("#111722", "#48546e"), "accent": "#dfe7f2",
        "image_prompt": ("quiet snowfall at night over a still village, soft blue hush, "
                         "serene cinematic, gentle falling snow, calm"),
        "tags": ["雪の音", "ホワイトノイズ", "安眠", "冬"],
    },
}
