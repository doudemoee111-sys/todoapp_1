# 自動投稿ルーティン用プロンプト

Claude Code on the web の Routine（cron）に登録して、毎回まっさらなコンテナで
1本を生成→予約投稿させるためのプロンプト例です。各ルーティンは
「新しいセッションを毎回作成」モードで登録してください。

---

## 宇宙・科学（毎日 19:00 JST 公開 / 生成は数時間前に実行）

登録 cron（UTC）例: `0 7 * * *`（= 16:00 JST に生成開始、当日19:00 JST公開を予約）

プロンプト:

```
リポジトリの pipeline ディレクトリで長尺動画を1本、自動生成して予約投稿してください。
手順:
1. `bash pipeline/setup.sh` を実行（ffmpeg・フォント・Python依存を導入）。
2. `python pipeline/run.py --genre space` を実行。
   - GOOGLE_TTS_API_KEY が設定されていれば本番のGoogle音声で生成されます。
3. 実行ログの最後に出る「scheduled publish」の時刻とURL、動画のタイトル・尺を報告してください。
4. エラーが出たら原因を特定し、pipeline配下のコードを修正してから再実行してください。
APIキーの値は絶対に出力しないこと。
```

## 都市伝説（毎日 20:00 JST 公開）

登録 cron（UTC）例: `0 8 * * *`（= 17:00 JST に生成開始）

プロンプト: 上と同じで `--genre space` を `--genre urban` に変更。

## 交互運用にする場合

1つのルーティンだけ登録し、`run.py --alternate` を使う。
`pipeline/state.json` に前回ジャンルが記録され、実行のたびに space ⇄ urban が切り替わります。
（state.json はコンテナ揮発。交互を厳密に保つなら state を Git 管理下に移すか、
曜日で `--genre` を出し分けるルーティンを2本登録する運用が確実です。）

---

補足:
- 予約公開は `private + publishAt`。指定時刻(JST)にYouTubeが自動公開します。
- 生成〜アップロードは十数分かかります。cron は公開時刻より数時間前に設定してください
  （`next_publish_at` は最低3時間のリードタイムを確保して翌日の枠に回します）。
