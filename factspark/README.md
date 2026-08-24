# factspark/ — 世界の雑学王 ショート動画 生成モジュール

このフォルダは **FactSpark（雑学ショート動画）** の生成パイプラインです。長尺パイプライン
（`pipeline/`）とは **別フォルダに分離** して同居させています（コードは混在させません）。
両者とも投稿先は同一チャンネル **「世界の雑学王」** で、当チャンネルの管轄です。

## なぜ todoapp_1 に取り込んだか（重要）

FactSpark は元々 `doudemoee111-sys/video-automation` リポジトリにありました。しかし
**スケジュール実行（無人の新規セッション）は video-automation を clone できません**
（`403 GitHub access to this repository is not enabled for this session` / add_repo は
無人セッションから使えない）。一方 **todoapp_1 はこの環境で認証済みで clone できる** ため、
生成コードを todoapp_1 に取り込み、FactSpark トリガーが todoapp_1 を clone して
`factspark/generator/daily_routine.py` を実行する構成にしました。これで別リポジトリ依存が
無くなり、毎日のショート投稿が安定して回ります。

- 取り込み元: `video-automation`（main ブランチ、チャンネルガード等の修正込み）を `generator/`
  以下にそのままベンダリング（`config.BASE_DIR` は自ファイル相対なので場所非依存で動く）。
- **原本の扱い**: 今後クラウドで動くのは **この todoapp_1/factspark 側** です。video-automation
  側は事実上のアーカイブになります（両方を変更しないよう、変更はこちらに集約）。

## 実行方法（トリガーが行う手順）

```bash
cd ~/todoapp_1 && git checkout claude/web-automation-setup-ifetgk && git pull
bash factspark/setup.sh                       # 依存＋日本語フォント（診断行を出す）
cd factspark/generator && python3 daily_routine.py   # 2本生成→12:00/17:00 JSTに予約投稿
```

## 安全装置

- **チャンネルガード**: `generator/youtube_upload.py` が投稿前に認証チャンネル名を検査し、
  『世界の雑学王』でなければ `WrongChannelError` で停止（睡眠等の別chへは投稿しない）。
- 生成に必要な鍵（`YOUTUBE_*` / `ANTHROPIC*` / `STABILITY_API_KEY` 等）は sekai 環境の
  環境変数から読み込む。値はログに出さない。エラー時にダミーで成功に見せない。

## 予約枠

`generator/daily_routine.py` の `POST_TIMES = [(12,0),(17,0)]`（JST）。空き枠を自動判定して
予約公開する。
