"""1日10本の動画(日本語のみ)を自動生成し、指定時刻に予約投稿する日次ルーチン

2026-08-09: 多言語版(9言語)は撤退し、日本語のみに変更(コンテンツ量抑制のためユーザー指示)。
多言語生成そのもの(generate_multilang_videos)は main.py に残しているので、
将来また多言語展開したくなった場合はそちらを呼び出す形に戻せる。

2026-08-14: PCとの並行運転に伴い、クラウド版の予約投稿時刻・本数をユーザー指示で調整。
2026-08-15: 1日10本の固定スケジュールに変更。予約時刻は POST_TIMES の10枠(日本時間)。
題材の重複回避は script_gen 側で行う。タイトルに加えシナリオ全文(avoid_texts)も渡し、
似すぎる場合はスキップせず別題材で作り直すため、本数は10本を維持する。

Windowsタスクスケジューラ/クラウドのRoutineから毎朝実行される想定:
    python daily_routine.py
"""

import datetime
import json
import traceback

import config
from main import generate_video
from youtube_upload import fetch_recent_titles, upload_video

HISTORY_FILE = config.BASE_DIR / "topic_history.json"
LOG_FILE = config.BASE_DIR / "daily_routine_log.txt"
# 1日2枠(日本時間)。総本数を絞り、各本に初速テスト枠と登録者の視聴を集中させる。
# ユーザー指定により 12:00 / 17:00 JST に予約公開する(元の実績枠 7:00 → 12:00 に変更)。
POST_TIMES = [
    (12, 0), (17, 0),
]
# 全ジャンル共通のタグ。ジャンル名は各動画の script["genre"] から動的に付与する(main()参照)。
BASE_TAGS = ["shorts"]


def _log(message: str) -> None:
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _load_history() -> list[str]:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return []


def _initial_avoid_titles() -> list[str]:
    """ネタ被り回避に使う直近タイトル一覧を用意する。

    まずYouTube側の実データ(直近アップロード/予約投稿のタイトル)を取得する。
    クラウドではリポジトリを毎回クローンし直すため topic_history.json が引き継げないので、
    この方式なら状態ファイルに依存せずネタ被りを回避できる。
    取得に失敗した場合のみ、従来の topic_history.json にフォールバックする。
    """
    try:
        titles = fetch_recent_titles()
        if titles:
            _log(f"YouTubeから直近{len(titles)}件のタイトルを取得し、ネタ被り回避に使います。")
            return titles
        _log("YouTubeから取得したタイトルが0件でした。topic_history.json にフォールバックします。")
    except Exception:
        _log(
            "YouTubeからのタイトル取得に失敗したため、topic_history.json にフォールバックします:\n"
            f"{traceback.format_exc()}"
        )
    return _load_history()


def _save_history(history: list[str]) -> None:
    HISTORY_FILE.write_text(
        json.dumps(history[-200:], ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _script_fulltext(script: dict) -> str:
    """タイトル+シナリオ(lines)を連結した、類似判定用の全文を返す。"""
    lines = script.get("lines") or []
    return str(script.get("title", "")) + "\n" + "\n".join(lines)


JST = datetime.timezone(datetime.timedelta(hours=9))


def _next_slot_datetime(hour: int, minute: int) -> datetime.datetime:
    """指定した時:分(JST)の次の日時を返す(本日分がすでに過ぎていれば翌日)。

    POST_TIMES は日本時間で指定する運用のため、実行環境のTZ(クラウドはUTC)に依存
    しないよう、明示的にJSTで判定する。upload_video 側でUTCへ変換して予約する。
    """
    now = datetime.datetime.now(JST)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += datetime.timedelta(days=1)
    return candidate


def main() -> None:
    _log("=== 日次ルーチン開始 ===")
    history = _initial_avoid_titles()
    # その日すでに生成した台本の全文(タイトル+シナリオ)。内容の類似回避に使う。
    avoid_texts: list[str] = []

    post_times = list(POST_TIMES)
    total = len(post_times)
    for i, (hour, minute) in enumerate(post_times, start=1):
        publish_at = _next_slot_datetime(hour, minute)
        try:
            _log(f"[トピック{i}/{total}] 動画を生成中(日本語のみ)...")
            output_path, script = generate_video(
                topic=None, avoid_titles=history, avoid_texts=avoid_texts
            )
            history.append(script["title"])
            avoid_texts.append(_script_fulltext(script))
            _save_history(history)

            try:
                _log(f"[トピック{i}/{total}] YouTubeへアップロード中...(公開予定: {publish_at})")
                tags = BASE_TAGS + [script.get("genre", "雑学"), script["title"][:20]]
                video_id = upload_video(
                    video_path=output_path,
                    title=script["title"],
                    description=script["youtube_description"],
                    tags=tags,
                    publish_at=publish_at,
                )
                _log(
                    f"[トピック{i}/{total}] 完了: "
                    f"https://youtube.com/watch?v={video_id}（予約: {publish_at}）"
                )
            except Exception:
                _log(f"[トピック{i}/{total}] アップロード失敗:\n{traceback.format_exc()}")
        except SystemExit as e:
            _log(f"[トピック{i}/{total}] 生成エラーで中断: {e}")
        except Exception:
            _log(f"[トピック{i}/{total}] 予期しないエラー:\n{traceback.format_exc()}")

    _log("=== 日次ルーチン終了 ===\n")


if __name__ == "__main__":
    main()
