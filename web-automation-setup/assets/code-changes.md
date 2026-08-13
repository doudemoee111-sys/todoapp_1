# クラウド用コード改修の指示書

> **使い方:** この文書を、`video-automation` フォルダを開いているローカルのClaude Codeに渡し、
> 「この1〜4を、ローカルでも今までどおり動くように（後方互換を保って）適用して」と依頼してください。
> 各改修は**環境変数が無ければ従来のファイル/パスを使うフォールバック**を必ず残すのが原則です。

---

## 1. APIキー・認証情報を環境変数から読む

**対象:** `config.py`（および `youtube_upload.py`）

各キーの読み込みを「環境変数優先・ファイルフォールバック」にします。例:

```python
import os

def _load_secret(env_name: str, fallback_file: str | None = None) -> str:
    val = os.environ.get(env_name)
    if val:
        return val.strip()
    if fallback_file and os.path.exists(fallback_file):
        with open(fallback_file, encoding="utf-8") as f:
            return f.read().strip()
    raise RuntimeError(f"{env_name} が環境変数にもファイルにも見つかりません")

ANTHROPIC_API_KEY = _load_secret("ANTHROPIC_API_KEY", "anthropic_api_key.txt")
OPENAI_API_KEY    = _load_secret("OPENAI_API_KEY",    "openai_api_key.txt")
STABILITY_API_KEY = _load_secret("STABILITY_API_KEY", "stability_api_key.txt")
```

リサーチ用（`research/genre_research.py`）も同様に `YOUTUBE_RESEARCH_API_KEY`（fallback: `research/api_key.txt`）へ。

---

## 2. YouTube OAuth を環境変数の refresh_token から組み立てる

**対象:** `youtube_upload.py`（`token.json` / `client_secret.json` を読んでいる箇所）

`token.json` ファイルの代わりに、環境変数から `Credentials` を直接構築します:

```python
import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

def _build_credentials():
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if refresh_token:  # クラウド（環境変数）経路
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.environ["YOUTUBE_CLIENT_ID"],
            client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
            scopes=["https://www.googleapis.com/auth/youtube"],
        )
        creds.refresh(Request())
        return creds
    # ローカル（従来）経路：token.json / client_secret.json をそのまま使う
    return _build_credentials_from_files()  # 既存のファイル読み込みロジックを残す
```

これにより、クラウドではブラウザ認可なしでアップロードできます。

---

## 3. 出力先（OUTPUT_DIR）とフォントパスをOSで切り替える

**対象:** `config.py`

```python
import os, sys, tempfile

IS_CLOUD = os.environ.get("YOUTUBE_REFRESH_TOKEN") is not None  # 環境変数の有無で判定
# ↑ もっと明示的にしたい場合は Routine 側で CLOUD=1 を環境変数に設定し、それを見てもよい

# 動画の保存先：クラウドでは一時ディレクトリ（アップロード後に破棄）
if IS_CLOUD:
    OUTPUT_DIR = tempfile.mkdtemp(prefix="factspark_")
else:
    OUTPUT_DIR = r"E:\ショート動画保存場所"

# 字幕フォント：Linux(クラウド) は Noto Sans JP Bold、Windows は従来のメイリオ
if sys.platform.startswith("win"):
    FONT_PATH       = r"C:\Windows\Fonts\meiryob.ttc"
    LATIN_FONT_PATH = r"C:\Windows\Fonts\arialbd.ttf"
else:
    FONT_PATH       = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
    LATIN_FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
```

> フォントの見た目が変わる可能性があるため、テスト実行で1本だけ字幕を目視確認してください。

---

## 4. topic_history.json をやめ、YouTubeから直近タイトルを取得（案A・推奨）

**対象:** `youtube_upload.py`（新規関数）＋ `daily_routine.py`（avoid_titles の作り方）

クラウドは毎回リポジトリを取り直すため、ファイル追記が引き継げません。
状態ファイルの代わりに、チャンネルの直近アップロード済み/予約済みタイトルを取得して重複回避に使います。

```python
def fetch_recent_titles(youtube, max_results: int = 50) -> list[str]:
    """自チャンネルの直近アップロード（予約含む）のタイトル一覧を返す。"""
    # 自分のアップロード用プレイリストIDを取得
    ch = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    titles, page = [], None
    while len(titles) < max_results:
        resp = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_id, maxResults=50, pageToken=page
        ).execute()
        titles += [it["snippet"]["title"] for it in resp.get("items", [])]
        page = resp.get("nextPageToken")
        if not page:
            break
    return titles[:max_results]
```

`daily_routine.py` 側では、従来 `topic_history.json` から作っていた `avoid_titles` を
`fetch_recent_titles(youtube)` の結果に置き換えます。
ローカル互換のため「YouTube取得に失敗したら従来の topic_history.json を読む」フォールバックを残すと安全です。

---

## 改修後の確認

1. ローカルで（環境変数を設定せずに）今までどおり動くこと。
2. `requirements.txt` があれば、上記で使う `google-auth` 等が含まれているか確認（無ければ追記）。
3. 変更点を CLAUDE.md に追記（クラウド移行対応、日付入り）。

> これらの改修が終わってコードがGitHubに上がれば、クラウド側のClaudeがそのリポジトリに直接アクセスして
> テスト実行・微調整まで代行できます。
