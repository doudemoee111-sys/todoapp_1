# FX/ゴールド データ自動化システム（クラウド版）

> **【管理スコープ・混在防止】** これは独立事業です。作業は**このブランチ
> (`claude/cloud-business-automation-4kqckb`) の `fx/` 配下だけ**で行うこと。
> YouTube 認証・アップロードは**一切使わない**（データ→ページ→Drive反映のみ）。
> 雑学（`pipeline/`／別ブランチ）・睡眠（別部門）・FactSpark（別リポジトリ）とは
> 混ぜない・跨がない。引き継ぎ先が決まるまで雑学ジャンル管理者が分離管理する。
> 全体地図は `docs/管理スコープ_事業分離マップ.md`（雑学ブランチ）を参照。

ローカル（Windows タスクスケジューラ）版を、**PC の電源に依存しない**クラウド上の
仕組みに移植したものです。毎朝スケジュール実行で日足データを取り込み、2 つの HTML
ページ（ローソク足・統計分析ダッシュボード）を再生成してこのリポジトリにコミットします。

対象銘柄: ドル円 / ユーロ円 / ポンド円 / ユーロドル / ポンドドル / ゴールド（GC=F）

---

## 全体像

| # | いつ | 何を | 実行主体 |
|---|------|------|----------|
| 1 | 毎朝 07:00 JST | 6 銘柄の当日 OHLC を取得 → `data/*.csv` に追記 → 2 ページを再生成 → コミット & プッシュ | クラウド Routine（新規セッション） |
| 2 | 必要なとき | 公開 URL（claude.ai artifact）へ反映 | チャットで「Web版を最新化して」（人の在席が必要） |

ローカル版と同じく、**公開 artifact の更新だけは無人実行から行えません**（claude.ai の
仕様で対話的な承認が必須）。生成物はリポジトリに毎朝コミットされるので、そこから
いつでも取得でき、公開ページはチャットで一言頼めば数秒で最新化されます。

---

## クラウドならではの制約（重要）

この環境の外向き通信は**許可リスト方式**で、GitHub・Anthropic・パッケージレジストリ
以外はすべて遮断されています。**Yahoo Finance など市場データのサイトには
`curl`／Python／`WebFetch` のいずれからもアクセスできません**（403）。

そのため:

- **10 年分の履歴**は取得系 API から一括ダウンロードできません。→ 手元の
  `FX_10年間データ.xlsx` / CSV を `data/` に置くのが正攻法です（下記）。
- **当日の追記**は Claude の `WebSearch`（Anthropic 側で実行され、遮断対象外）で
  当日レートを拾って行います。日中の正確な高値・安値までは取れないことがあり、
  値は**概算**になる場合があります。精度が必要な足は手元データで上書きしてください。

---

## ファイル構成

```
fx/
  data/                     日足データ（基準履歴。1 銘柄 1 CSV, date,open,high,low,close）
    USDJPY.csv EURJPY.csv GBPJPY.csv EURUSD.csv GBPUSD.csv GOLD.csv
    daily/                  日次差分（YYYY-MM-DD.json）。毎朝の Routine が 1 日 1 ファイル追加
  web/                      生成物（毎朝上書き）
    fx_candlestick.html     🕯️ ローソク足チャート
    fx_dashboard.html       📊 統計分析ダッシュボード
  scripts/
    lib.mjs                 銘柄定義・CSV パース・基準履歴＋日次差分のマージ
    build_pages.mjs         data/（基準 + daily 差分）から 2 ページを生成
    append_delta.mjs        当日 OHLC を受け取り data/daily/<日付>.json を作成（無人 Routine 用）
    append_daily.mjs        当日 OHLC を基準 CSV に直接追記（対話セッション用）
    make_sample_data.mjs    動作確認用のサンプル履歴を生成
    smoke.mjs               Chromium で描画を検証しスクショ保存（開発用）
    templates/              ページの土台（デザイン・計算ロジックはここを編集）
```

**データの二層構造**: `data/*.csv` が正確な基準履歴（Excel 由来。Excel 再アップ時に上書き）、
`data/daily/*.json` が毎朝の小さな追記。`build_pages` は両者をマージし、同一日付は差分が優先。
無人 Routine が大きな CSV を書き換える必要がなく、**極小ファイル 1 個を GitHub API でコミット**
するだけなので、書き込み権限が限られたクラウド環境でも確実に永続化できる。

> `data/*.csv` と `web/*.html` は**ソースから再生成できるビルド生成物**のため
> リポジトリには含めていません。下記の 2 コマンドで生成できます。
> `data/` は現状 `make_sample_data.mjs` による合成サンプル（約 3 年分・決定論的）を
> 想定しており、実データに差し替えると即座に本物のチャートになります。

```bash
node fx/scripts/make_sample_data.mjs   # data/*.csv を生成（実データがあれば不要）
node fx/scripts/build_pages.mjs        # web/*.html を生成
```

---

## 使い方

### 1. 実データを入れる（推奨）

`FX_10年間データ.xlsx` を CSV で書き出し、各シートを `data/<銘柄>.csv` として保存します。
列は `date,open,high,low,close`。日本語ヘッダ（日付/始値/高値/安値/終値）や `YYYY/M/D`
形式もそのまま読めます。並び順・重複は `build_pages` 実行時に整えられます。
（`.xlsx` のままチャットに添付いただければ、こちらで CSV 変換して配置します。）

### 2. ページを生成

```bash
node fx/scripts/build_pages.mjs
```

`fx/web/*.html` が更新されます。ブラウザで開くだけで動く自己完結 HTML です
（外部 CDN 不使用・ライト/ダーク対応）。

### 3. 当日分を追記（自動更新が内部で行う処理）

```bash
echo '{"date":"2026-08-13","USDJPY":{"open":159.29,"high":159.46,"low":158.61,"close":159.32}}' \
  | node fx/scripts/append_daily.mjs -
node fx/scripts/build_pages.mjs
```

---

## 自動更新（Routine）

毎朝 07:00 JST（= 22:00 UTC）に新規クラウドセッションが起動し、次を実行します。

1. このブランチを取得
2. `WebSearch` で 6 銘柄の当日レートを収集
3. `append_delta.mjs` で `data/daily/<日付>.json` を作成 → `build_pages.mjs` で再生成
4. その差分 1 ファイルを **GitHub API（`create_or_update_file`）でコミット**
5. 生成した 2 つの HTML をチャットに送付

**なぜ GitHub API 経由なのか**: この環境では無人（スケジュール起動）セッションの
`git push` が read-only で拒否される一方、GitHub App トークンによる API 書き込みは
許可されている。そのため Routine は `git push` ではなく GitHub コネクタ（MCP）でコミットする。
→ **Routine には GitHub コネクタの付与が必須**。claude.ai の Routines 画面でこの Routine を
編集し、GitHub コネクタを有効化しておくこと（無いと手順 4 のコミットができない）。

Routine の管理は claude.ai の Routines 画面、または当セッションの
Claude Code Remote ツール（`list_triggers` / `update_trigger` / `delete_trigger`）から
行えます。ブランチをマージして本番を `main` に移す場合は、Routine のプロンプト内の
対象ブランチ名を更新してください。

---

## ページでできること

**🕯️ ローソク足チャート** — 6 銘柄・期間（1M/3M/6M/1年/全期間/カスタム）を切替。
バーにカーソル（スマホはタップ）で OHLC をツールチップ表示。陽線は中抜き、陰線は
塗りで色以外でも判別可能。

**📊 統計分析ダッシュボード** — ローソク足＋以下が通貨ペアと連動（土日は集計除外）:
曜日/第N週/月フィルタ付き統計（件数・平均値幅・標準偏差・平均騰落・陽線率）、
本日の予想レンジ（始値入力→平均/±1σ/±2σ/±3σ）、日付検索、季節性グラフ 4 枚。

## 注意

予想レンジ・統計値はいずれも過去の値動きに基づく参考値で、将来のレートを保証する
ものではありません。ゴールドはドル建てスポット金（XAU/USD）です（手元データに準拠。
2016 年の約 1,339 ドルから 2026 年の約 4,469 ドルまでの実データ）。
