# Routine プロンプト集（コピペ用）

`claude.ai/code/routines` で3つのRoutineを作成し、それぞれの「プロンプト」欄に下の文をそのまま貼ります。
リポジトリは3つとも `video-automation`（Step 1で作ったもの）を指定します。
時刻は日本時間（JST）で入力すればWeb側がUTCに換算します。

---

## Routine 1: ShortsResearchAndPromptTuning（毎日 5:00 JST）

```
video-automation リポジトリの research/genre_research.py を実行し、雑学・都市伝説・名言・海外の反応の
ジャンル別Shorts再生数データを取得してください。research/output/ 配下の過去CSVおよび直近24〜48時間の
Web検索結果と比較し、伸びている題材・タイトルの傾向を分析してください。

運用ルール（CLAUDE.md準拠）:
- 軽微な言い回し調整は generator/script_gen.py の SYSTEM_PROMPT を直接編集し、CLAUDE.md に変更履歴を追記して
  main ブランチにコミットしてください（翌6:00の生成に反映させるため）。
- 投稿本数・言語・新規有料APIなど大きな変更はコードを変えず、research/output/improvement_proposals.md に
  提案として追記するだけにとどめてください。
- 新規CSVは research/output/ にコミットして蓄積を継続してください。

APIキー・トークンは環境変数から読み込まれます。完了後、変更点を日本語で簡潔に報告してください。
```

---

## Routine 2: ShortsAutoRoutine（毎日 6:00 JST）― 本体

```
video-automation リポジトリの generator/daily_routine.py を実行し、本日分のYouTube Shorts動画を生成・
予約投稿してください。

- YouTube上の未公開予約投稿が5本以上あれば最大10枠、未満なら通常5枠で生成します（既存の _resolve_post_times ロジック）。
- 各動画は privacy=private・未来の publishAt を付けてYouTubeへアップロードしてください（公開前レビュー猶予を維持）。
- 動画1本ごとに try/except で継続し、1本の失敗が他を止めないようにしてください。
- APIキー・YouTube OAuth情報は環境変数から読み込まれます。
- 動画の保存先は一時ディレクトリを使い、アップロード後は破棄してください（永続保存は不要）。
- 字幕フォントは Noto Sans JP Bold（/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc）を使用してください。
- ネタ被り回避は、topic_history.json ではなくYouTubeの直近投稿タイトルを取得して判定してください（案A）。

完了後、生成できた本数・各動画のタイトルと予約時刻・失敗があればその内容を日本語で報告してください。
```

> ⚠️ 初回は必ず「Run now（今すぐ実行）」で1本テストし、フォントの見た目と所要時間を確認してから
> 本番スケジュールを有効にしてください。

---

## Routine 3: ShortsDailyRoutineCheck（毎日 7:00 JST）

```
本日のShorts自動投稿（ShortsAutoRoutine）が正常に完了したかをヘルスチェックしてください。

確認方法（ログファイルに依存しない方式）:
1. ShortsAutoRoutine の直近の実行結果（成功/失敗）を確認する。
2. YouTube Data API で、本日新たに予約投稿された本数が想定件数（5 または 10）と一致するかを確認する。
3. エラーや欠落があれば、原因を推測して具体的に指摘する。

読み取り専用のタスクです。コードやデータは変更しないでください。
結果を日本語で簡潔に報告してください（正常なら1〜2文、異常があれば原因の推測を添えて）。
```

---

## メモ

- **ヘルスチェックの通知先**を広げたい場合（メールやSlackに異常を飛ばす等）は、Routineのコネクタ機能で追加できます。
  希望があればこのプロンプトに「異常時はメールで通知」等を足せます。
- 3つとも、実行履歴は `claude.ai/code` に残るので、スマホ・ブラウザからいつでも確認できます。
