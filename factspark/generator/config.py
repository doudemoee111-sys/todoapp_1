"""共通設定・APIキー読み込み

実行環境について:
- ローカル(Windows)ではAPIキーは *_api_key.txt から、動画はEドライブへ、字幕は
  Windows標準フォントを使う(従来どおり)。
- クラウド(Claude Code Routines / Linux)では、APIキーは環境変数から、動画は一時
  ディレクトリへ、字幕はLinux上の日本語Boldフォントを使う。
Windowsかどうか(sys.platform)で自動的に切り替わるので、コード側の手動変更は不要。
"""

import os
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "assets"
BGM_DIR = ASSETS_DIR / "bgm"
TMP_DIR = BASE_DIR / "tmp"

# 実行環境の判定: Windows(ローカルPC)以外は「クラウド(Linux)」とみなす
IS_WINDOWS = sys.platform.startswith("win")

# 動画の出力先。ローカル(Windows)はEドライブ、クラウド(Linux)は一時ディレクトリ。
# クラウドでは動画は生成後すぐYouTubeへアップロードされ、以降は不要になるため永続保存はしない。
if IS_WINDOWS:
    OUTPUT_DIR = Path(r"E:\ショート動画保存場所")
else:
    OUTPUT_DIR = Path(tempfile.gettempdir()) / "factspark_output"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ANTHROPIC_KEY_FILE = BASE_DIR / "anthropic_api_key.txt"
OPENAI_KEY_FILE = BASE_DIR / "openai_api_key.txt"
STABILITY_KEY_FILE = BASE_DIR / "stability_api_key.txt"

# 動画設定
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 30

# 字幕設定(フォントは実行環境で切り替える)
if IS_WINDOWS:
    FONT_PATH = r"C:\Windows\Fonts\meiryob.ttc"  # 日本語用(メイリオ ボールド)
    LATIN_FONT_PATH = r"C:\Windows\Fonts\arialbd.ttf"  # ラテン文字言語用
else:
    # クラウド(Linux): 実際に存在する日本語Boldフォントを候補から自動選択する。
    # ディストリやインストール方法でパスが異なるため、上から順に存在確認して最初の1つを使う。
    # 環境変数 FONT_PATH があれば最優先。全滅時も Noto の標準パスを既定値として残す。
    _font_candidates = [
        os.environ.get("FONT_PATH", ""),
        str(BASE_DIR / "assets" / "fonts" / "NotoSansJP-Bold.otf"),
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto-cjk/NotoSansCJK-Bold.ttc",
        # フォールバック: Noto CJK が入らない環境向け（apt fonts-ipafont-gothic）。
        # sekai 等で apt の Noto 導入が失敗しても、IPAゴシックがあれば字幕を焼ける。
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
        "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
        "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
    ]
    # 全滅時の既定も、存在しやすい IPAGothic を優先し、無ければ Noto を指す。
    _default_font = next(
        (p for p in (
            "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
            "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
        ) if os.path.exists(p)),
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    )
    FONT_PATH = next((p for p in _font_candidates if p and os.path.exists(p)), _default_font)
    LATIN_FONT_PATH = os.environ.get("LATIN_FONT_PATH", FONT_PATH)
FONT_SIZE = 72
CAPTION_COLOR = "white"
CAPTION_STROKE_COLOR = "black"
CAPTION_STROKE_WIDTH = 6

# 多言語展開設定(ラテン文字圏のみ。ヒンディー語/アラビア語/ウルドゥー語は複雑な文字組版が
# 必要なため、このPillow環境(raqm非対応)では未対応)
LANGUAGES = {
    "ja": "Japanese",
    "en": "English",
    "pt": "Portuguese (Brazilian)",
    "id": "Indonesian",
    "es": "Spanish",
    "de": "German",
    "vi": "Vietnamese",
    "tl": "Filipino (Tagalog)",
    "tr": "Turkish",
}

# モデル設定
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
OPENAI_TTS_MODEL = "gpt-4o-mini-tts"
OPENAI_TTS_VOICE = "nova"
TTS_INSTRUCTIONS = "Speak in a bright, cheerful, energetic tone with an upbeat smile in your voice, at a lively pace."

# 背景画像設定(Stability AI)
STABILITY_ASPECT_RATIO = "9:16"
NUM_BACKGROUND_IMAGES = 2
IMAGE_STYLE_SUFFIX = (
    "Style: cute anime illustration, chibi style, soft pastel colors, "
    "warm and friendly, flat vector art, gentle lighting, "
    "no text, no letters, no words, no captions, no watermark, no gore, not photorealistic."
)

BGM_VOLUME = 0.12  # ナレーションに対するBGM音量の割合


def _load_key(env_names, key_file: Path, service_name: str) -> str:
    """APIキーを読み込む。まず環境変数(クラウド)を順に探し、無ければファイル(ローカル)を見る。

    env_names は文字列または文字列のリスト。複数指定した場合は先頭から順に探す
    (例: Anthropic は予約名 ANTHROPIC_API_KEY を避けた別名を先に使う)。
    """
    if isinstance(env_names, str):
        env_names = [env_names]
    for name in env_names:
        env_val = os.environ.get(name)
        if env_val and env_val.strip():
            return env_val.strip()
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
        if key:
            return key
    sys.exit(
        f"エラー: {service_name} のAPIキーが見つかりません。\n"
        f"クラウドでは環境変数 {env_names[0]} を設定するか、"
        f"ローカルでは {key_file} にキーを1行だけ書いて保存してください。"
    )


def load_anthropic_key() -> str:
    # ANTHROPIC_API_KEY は Claude Code の予約環境変数(セッション認証用)で、
    # クラウド環境ではセッションに渡らない場合があるため、専用の別名を優先して読む。
    # 後方互換のため従来の ANTHROPIC_API_KEY とローカルファイルもフォールバックとして残す。
    return _load_key(
        [
            "PIPELINE_ANTHROPIC_KEY",
            "FACTSPARK_ANTHROPIC_KEY",
            "ANTHROPIC_KEY",
            "ANTHROPIC_API_KEY",
        ],
        ANTHROPIC_KEY_FILE,
        "Anthropic",
    )


def load_openai_key() -> str:
    return _load_key("OPENAI_API_KEY", OPENAI_KEY_FILE, "OpenAI")


def load_stability_key() -> str:
    return _load_key("STABILITY_API_KEY", STABILITY_KEY_FILE, "Stability AI")


def font_for_language(language_code: str) -> str:
    return FONT_PATH if language_code == "ja" else LATIN_FONT_PATH
