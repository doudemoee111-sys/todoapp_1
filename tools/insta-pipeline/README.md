# insta-pipeline

Instagram の日次投稿を、**自動化してよい範囲だけ**自動化するパイプライン。

`OpenAI API` / `Stability AI` / `Google Cloud TTS` の3キーで動きます。依存パッケージはゼロ（Node 20+ の標準機能と ffmpeg のみ）。

関連ドキュメント: [自動化マップ](../../docs/instagram-automation-map.md) ／ [ジャンル分析](../../docs/ai-instagram-affiliate-analysis.md)

---

## 1. 何が自動化され、何が自動化されないか

| # | 工程 | 自動化 | 使うもの |
|---|---|---|---|
| 01 | 企画（ネタ選定・在庫が切れたら自動補充） | 🟢 | OpenAI |
| 02 | 台本生成（フック／シーン／CTA） | 🟢 | OpenAI |
| 03 | シーン画像生成 | 🟢 | Stability AI |
| 04 | ナレーション生成 | 🟢 | Google TTS |
| 05 | 動画合成（テロップ焼き込み・音声結合） | 🟢 | ffmpeg |
| 06 | キャプション＋ハッシュタグ（**PR表記を強制付与**） | 🟢 | OpenAI |
| 07 | 法務セルフチェック（景表法・薬機法・金商法） | 🟡 | ローカル正規表現 + OpenAI |
| — | **画面録画（一次情報）の収録** | 🔴 **人間** | あなた |
| — | **最終承認** | 🔴 **人間** | `APPROVED` ファイル |
| 08 | 投稿 | 🟢 | Instagram Graph API |
| 09 | 週次インサイトレポート | 🟢 | Instagram Graph API + OpenAI |
| — | **改善の意思決定** | 🔴 **人間** | あなた |

**人間の実働は 1日あたり「収録」＋「レビュー承認」の約15〜20分。**

---

## 2. キーの代替可否

| 元の構成 | このパイプラインでの代替 | 可否 |
|---|---|---|
| 生成AI（企画・台本・キャプション） | **OpenAI API** | ✅ 完全代替 |
| Canva（カバー画像・図解） | **Stability AI** | ✅ 完全代替 |
| Vrew（ナレーション・テロップ） | **Google TTS + ffmpeg** | ✅ 代替可 |
| Meta Business Suite（予約投稿） | **Instagram Graph API** | ⚠️ **別途トークンが必要**（無料・§6参照） |
| インサイト（分析） | 同上 | ⚠️ 同じトークン |
| LINE公式（リスト化） | 代替不要（無料枠で足りる） | — |

> **トークンが無くても運用できます。** その場合 07 までを自動生成し、`out/YYYY-MM-DD/reel.mp4` と `caption.txt` を **Meta Business Suite に手動でアップ**してください（1日5分）。

---

## 3. セットアップ

```bash
cd tools/insta-pipeline

cp .env.example .env          # キーを記入
cp config.example.json config.json   # ジャンル・ペルソナ・禁止表現を自分用に編集

# ffmpeg（動画合成に必要）
#   macOS:  brew install ffmpeg
#   Ubuntu: sudo apt-get install -y ffmpeg fonts-noto-cjk
#   Windows: winget install Gyan.FFmpeg

node src/run.mjs --doctor     # 環境チェック
node src/run.mjs --dry-run    # APIを叩かずに一連の流れを確認
```

`config.json` で最低限いじるところ:

- `account.genre` / `account.persona` … 誰に何を届けるか
- `post.ctaText` … 導線の一言
- `compliance.bannedPatterns` … 禁止表現（**正規表現**で書けます）

---

## 4. 毎日の運用

### 前夜〜当日朝（人間・10〜15分）
その日のネタを **画面録画** して置くだけ。

```
assets/recordings/2026-08-24.mp4
```

> 録画が無い場合は生成画像のスライドショーにフォールバックしますが、**2026年5月のオリジナルコンテンツ優遇アップデート以降、一次情報の無い投稿はリーチが構造的に不利になります。** 録画を置くことがこのパイプラインで最も費用対効果の高い作業です。

### 朝7:00（自動）
cron が素材一式を生成 → `out/2026-08-24/` に出力。

```
out/2026-08-24/
├── plan.json        企画
├── script.json      台本
├── images/          シーン画像
├── audio/           ナレーション
├── reel.mp4         ★ 完成動画
├── caption.txt      ★ 投稿キャプション（冒頭にPR表記）
├── compliance.json  法務チェック結果
├── REVIEW.md        ★ 人間用チェックシート
└── state.json       進捗（再実行時はスキップされる）
```

### 確認（人間・5分）
`REVIEW.md` を開いてチェック → 問題なければ承認。

```bash
touch out/2026-08-24/APPROVED
```

### 19:00（自動 or 手動）
- **自動**: `node src/steps/08-publish.mjs`（`APPROVED` があるものだけ投稿）
- **手動**: `reel.mp4` と `caption.txt` を Meta Business Suite にアップして予約

### 毎週月曜（自動）
`scripts/weekly-report.sh` が `out/_reports/report-YYYY-MM-DD.md` を生成。
**平均保存率**と、AIによる「伸びた要因／来週のアクション」が出ます。判断は人間が行ってください。

---

## 5. cron の設定

`scripts/crontab.example` をそのまま `crontab -e` に貼り、パスだけ書き換えます。

```cron
NODE_BIN=/usr/local/bin/node
PIPELINE=/path/to/todoapp_1/tools/insta-pipeline

0 7 * * *  cd $PIPELINE && NODE_BIN=$NODE_BIN ./scripts/daily.sh
0 8 * * 1  cd $PIPELINE && NODE_BIN=$NODE_BIN ./scripts/weekly-report.sh
```

macOS でスリープ中も動かしたい場合は cron ではなく `launchd`（`StartCalendarInterval`）を使ってください。

---

## 6. Instagram Graph API トークンの取り方（無料）

自動投稿・インサイトを使う場合のみ必要です。**キーを購入するのではなく、Meta開発者アプリから発行します。**

1. Instagramアカウントを **プロアカウント（ビジネス or クリエイター）** に切り替える
2. Facebookページを作成し、Instagramアカウントと連携する
3. [developers.facebook.com](https://developers.facebook.com/) でアプリを作成（タイプ: ビジネス）
4. 「Instagram Graph API」製品を追加
5. グラフAPIエクスプローラで権限 `instagram_basic` / `instagram_content_publish` / `pages_show_list` / `pages_read_engagement` を付けてトークンを発行
6. **長期トークンに交換**する（短期は1時間で失効）
7. `me/accounts` → `instagram_business_account` で **IG_USER_ID** を取得
8. `.env` に `IG_USER_ID` と `IG_ACCESS_TOKEN` を記入

### ⚠️ 動画の公開URLが必要

Graph API は**インターネットからアクセスできるURL**の動画しか受け付けません。ローカルファイルは直接渡せません。`PUBLIC_ASSET_BASE_URL` に S3 / R2 / GCS などのベースURLを設定し、`{BASE}/{date}/reel.mp4` に置ける状態にしてください。

これが面倒なら、**自動投稿は使わず Meta Business Suite への手動アップで運用する**のが現実的です（差は1日5分）。

---

## 7. 規約上のガードレール（実装済み）

このパイプラインは、Instagram/Meta の規約に触れる操作を**構造的にできないように**作ってあります。

| 守っていること | 実装 |
|---|---|
| 公式API経由のみ | Graph API のみ使用。スクレイピング・非公式API・パスワード入力は一切なし |
| 自動いいね／自動フォローをしない | **機能として存在しない** |
| 一斉DMを送らない | **機能として存在しない** |
| PR表記（ステマ規制） | キャプション冒頭に強制付与。無ければ 07 が **block** |
| 薬機法・景表法・金商法 | 正規表現 + AIレビューの二段チェック。block があると 08 が投稿を拒否 |
| ハッシュタグ過剰付与 | 3〜5個に制限（超過で warn） |
| 25投稿/24時間 | 1日1本の設計なので構造的に到達しない |
| 人間の最終責任 | `APPROVED` ファイルが無ければ**絶対に投稿しない** |

**AIラベルについて**: AI生成素材（Stability AIの画像、TTS音声）を含む投稿は、Instagram側でAIラベルの申告が必要です。これはAPI経由では設定できないため、`REVIEW.md` のチェック項目に入れてあります。投稿後にアプリ側で確認してください。

---

## 8. コマンド一覧

```bash
node src/run.mjs --doctor              # 環境チェック
node src/run.mjs --dry-run             # APIを叩かずに動作確認
node src/run.mjs                       # 今日の分を生成
node src/run.mjs 2026-08-24            # 日付指定
node src/run.mjs --only=script,caption --force   # 特定ステップだけ再実行
node src/run.mjs --publish             # 生成 → 承認済みなら投稿まで
node src/steps/08-publish.mjs 2026-08-24         # 投稿だけ
node src/steps/09-insights.mjs         # 週次レポート
```

- 各ステップは `state.json` で完了管理され、**再実行しても既存ステップはスキップ**されます（`--force` で上書き）
- API呼び出しは 429/5xx を指数バックオフで最大4回リトライします

---

## 9. 制限事項（正直な注記）

- **動画合成（05）は実機未検証です。** 開発環境に ffmpeg を導入できなかったため、構文チェックと引数生成・エスケープの検証までしか行えていません。初回は必ず `node src/run.mjs --only=video --force` を単体で回し、`out/<date>/reel.mp4` を目視確認してください。
- 日本語テロップには日本語フォントが必要です。未検出時はテロップをスキップして音声のみで書き出します（`FONT_FILE` で明示指定可）。
- `--dry-run` は API を一切叩かず、ダミーの画像・音声・テキストを生成します。課金なしで配線確認ができます。
- Graph API の仕様（レート制限・フィールド名）は Meta 側で変更されます。動かなくなった場合はまず `IG_API_VERSION` を上げてください。
