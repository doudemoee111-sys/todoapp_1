# 長尺YouTube自動生成パイプライン

日本市場向けの **8〜10分の長尺解説動画** を、テーマ選定 → 台本 → ナレーション音声 →
AI画像(約30枚) → 動画合成(Ken Burns + 日本語字幕) → サムネ → **YouTube予約投稿** まで全自動で生成します。

リサーチ結果（中央値再生数）に基づき、次の2ジャンルを対象にしています:

| ジャンル | 中央値再生数 | 投稿時刻(JST) | カテゴリ |
|---|---:|---|---|
| 宇宙・科学解説 (`space`) | 約54万 | **19:00** | 教育 |
| 都市伝説解説 (`urban`) | 約44万 | **20:00** | エンタメ |

まずは `space` から運用し、`--alternate` で交互投稿に切り替えられます。

---

## セットアップ

```bash
bash pipeline/setup.sh          # ffmpeg + Noto CJK フォント + Python依存 を導入
```

### 必要な環境変数（シークレット）

| 変数 | 用途 | 状態 |
|---|---|---|
| `OPENAI_API_KEY` | 台本生成（＋暫定の音声） | 設定済み |
| `STABILITY_API_KEY` | 画像・サムネ生成 | 設定済み |
| `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` / `YOUTUBE_REFRESH_TOKEN` | アップロード | 設定済み |
| **`GOOGLE_TTS_API_KEY`** | **Google Cloud TTS（本番の音声）** | 設定済み |

> これらは **クラウド環境（Environment）の環境変数** に登録します。登録後は
> **新しいセッション（コンテナ再起動後）から反映** される点に注意（実行中セッションには入りません）。
> `run.py` は起動時に `preflight()` でこれらの有無を検査し、欠けていれば即座に停止します。

### Google Cloud TTS のキー取得（本番音声に必須）

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成（または既存を選択）
2. **Cloud Text-to-Speech API** を有効化
3. 「APIとサービス」→「認証情報」→「認証情報を作成」→ **APIキー**
4. （推奨）そのAPIキーを Text-to-Speech API のみに制限
5. 発行された値を環境変数に設定: `GOOGLE_TTS_API_KEY=...`
6. 課金を有効化（TTSは従量課金。Neural2音声で概ね月100万文字まで無料枠あり）

> サービスアカウントJSONを使う場合は `GOOGLE_APPLICATION_CREDENTIALS` にパスを設定すればそちらが使われます。
> どちらも無い場合、本番音声は動きません（`TTS_PROVIDER=openai` で暫定運用は可能）。

---

## 使い方

```bash
# 宇宙・科学を1本作って予約投稿（本番）
python pipeline/run.py --genre space

# 交互ローテーション（前回の続きのジャンルを自動選択。state.json を使う）
python pipeline/run.py --alternate

# 日付ベースの交互ローテーション（状態ファイル不要。★スケジュール実行はこれを使う）
python pipeline/run.py --rotate-date

# ビルドのみ（アップロードしない）— 動画を手元で確認したいとき
python pipeline/run.py --genre space --no-upload

# テーマを指定
python pipeline/run.py --genre urban --topic "きさらぎ駅の謎"

# 暫定でOpenAI音声を使う（Google TTSキーが未設定のとき）
TTS_PROVIDER=openai python pipeline/run.py --genre space --no-upload
```

生成物は `pipeline/output/<genre>_<timestamp>/` に保存されます
（`script.json` / `narration.mp3` / `img/` / `video.mp4` / `thumbnail.png` / `result.json`）。

投稿は `private + publishAt` で予約されるため、指定時刻(JST)に自動で公開されます。

---

## 全自動スケジュール投稿（ルーティン / トリガー）

毎日 **17:00 JST（08:00 UTC, cron `0 8 * * *`）** にトリガーが起動し、`--rotate-date` で
宇宙↔都市伝説を日替わり交互に生成→予約投稿します（宇宙=19時 / 都市伝説=20時 JST 公開）。

### スケジュール実行の大前提（★再発防止の要点）

トリガーは **毎回まっさらな新セッション** を起動します。その新セッションには
**リポジトリも依存関係も無い** ため、プロンプトの中で「取得 → 準備 → 実行」を
自分で行う必要があります。これを怠ると `pipeline/` が見つからず何も実行できません
（実際に一度この失敗が起きました。下の「ポストモーテム」参照）。

トリガーのプロンプトは必ず次の順序を守ること:

```bash
# 1) リポジトリを取得（新セッションには存在しないので自分でclone。認証はプロキシ経由で通る）
if [ -d ~/todoapp_1/.git ]; then
  cd ~/todoapp_1 && git fetch origin claude/web-automation-setup-ifetgk \
    && git checkout claude/web-automation-setup-ifetgk \
    && git pull origin claude/web-automation-setup-ifetgk
else
  git clone --branch claude/web-automation-setup-ifetgk \
    https://github.com/doudemoee111-sys/todoapp_1.git ~/todoapp_1 && cd ~/todoapp_1
fi
# 2) 依存を導入
bash pipeline/setup.sh
# 3) 生成＋予約投稿（preflight が前提を検査してから走る）
cd pipeline && python3 run.py --rotate-date
```

### 多層の再発防止

| 層 | 仕組み | 何を防ぐか |
|---|---|---|
| プロンプト | 手順1で必ず `clone`（既存なら `fetch`）する | 新セッションにコードが無い問題 |
| `run.py` の `preflight()` | 実行前に鍵・ffmpeg を検査し、欠ければ即停止＋原因を明示 | 鍵/ツール欠落のまま走り、時間と課金を浪費する事故 |
| ジャンル選択 `--rotate-date` | 日付から決定的に算出（状態ファイル不要） | ephemeral セッションで `state.json` が消え交互にならない問題 |
| 明示的な失敗報告 | エラー時はダミー音声・プレースホルダで代替せず中断・報告 | 「壊れた動画を正常として投稿」する事故 |

### ポストモーテム（2026-08-16 の失敗）

- **事象**: 初回のスケジュール実行が「`/home/user` が空・Gitリポジトリ未紐付け」で失敗。
- **原因**: トリガーの新セッションにソースリポジトリが紐づいておらず、プロンプトも
  `clone` を行っていなかったため、`pipeline/` を取得できなかった。
- **対策**: プロンプト手順1に `clone`/`fetch` を追加、`run.py` に `preflight()` を追加、
  本節に前提と手順を明文化。以後は同じ失敗を検知・防止できる。

## モジュール構成

| ファイル | 役割 |
|---|---|
| `config.py` | ジャンル定義・尺・投稿時刻・プロバイダ設定 |
| `llm_script.py` | OpenAIで台本パッケージ生成（タイトル/章/画像プロンプト/説明/タグ） |
| `tts.py` | Google Cloud TTS（REST/APIキー）＋OpenAI暫定、チャンク分割・結合 |
| `images.py` | Stabilityで約30枚のシーン画像を生成 |
| `assemble.py` | Ken Burns＋日本語字幕焼き込み＋音声mux（ffmpeg） |
| `thumbnail.py` | Stability背景＋日本語大テキストのサムネ生成 |
| `youtube_upload.py` | リフレッシュトークンで予約アップロード＋サムネ設定 |
| `run.py` | 一連の工程をオーケストレーション |
