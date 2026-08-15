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
| **`GOOGLE_TTS_API_KEY`** | **Google Cloud TTS（本番の音声）** | **要設定** |

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

# 交互ローテーション（前回の続きのジャンルを自動選択）
python pipeline/run.py --alternate

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

## 全自動スケジュール投稿

コンテナは毎回リセットされるため、スケジュール実行のたびに `setup.sh` を流してから `run.py` を実行します。
`assets/routine-prompt.md` にルーティン用のプロンプトを用意しています。

- 宇宙・科学: 毎日 or 隔日で `--genre space`（19時JST公開）
- 都市伝説: `--genre urban`（20時JST公開）
- 交互運用: `--alternate` を1日1回

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
