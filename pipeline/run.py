"""End-to-end orchestrator: one video from topic -> upload.

Usage:
  python run.py --genre space               # make + schedule-upload a space video
  python run.py --genre urban
  python run.py --alternate                 # pick next genre from rotation state
  python run.py --genre space --no-upload   # build only (skip YouTube)
  python run.py --genre space --topic "..." # force a specific topic

Stages: script (OpenAI) -> TTS (Google) -> images (Stability) -> assemble (ffmpeg)
        -> thumbnail -> upload (YouTube, scheduled at genre's JST peak hour).
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

import config
from config import (GENRES, OUTPUT_DIR, STATE_FILE, ROTATION, ROTATION_PHASE,
                    DEFAULT_GENRE, UPLOAD_PRIVACY)


class PreflightError(RuntimeError):
    """Raised when the run can't possibly succeed, before any work is done."""


def preflight(do_upload: bool) -> None:
    """Fail fast, and loudly, if a prerequisite is missing.

    Scheduled runs execute in fresh, ephemeral sessions, so the whole
    environment (credentials, system tools, even the checkout) has to be
    reconstructed each time. When something is missing it is far better to
    stop here with a precise list than to spend ~15 minutes half-building a
    video or, worse, silently producing a broken one. Every message names the
    exact fix.
    """
    problems: list[str] = []

    # --- credentials ---------------------------------------------------------
    if not os.environ.get("OPENAI_API_KEY"):
        problems.append("OPENAI_API_KEY 未設定 → 台本生成に必須（環境変数に追加）")
    if not os.environ.get("STABILITY_API_KEY"):
        problems.append("STABILITY_API_KEY 未設定 → 画像生成に必須（環境変数に追加）")
    if config.TTS_PROVIDER == "google" and not (
            os.environ.get("GOOGLE_TTS_API_KEY")
            or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")):
        problems.append(
            "GOOGLE_TTS_API_KEY（または GOOGLE_APPLICATION_CREDENTIALS）未設定 "
            "→ Google TTS に必須")
    if do_upload:
        for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
            if not os.environ.get(k):
                problems.append(f"{k} 未設定 → YouTube アップロードに必須")

    # --- system tools --------------------------------------------------------
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            problems.append(f"{tool} が PATH にない → `bash pipeline/setup.sh` を先に実行")

    if problems:
        raise PreflightError(
            "事前チェック(preflight)に失敗しました。以下を解消してから再実行してください:\n  - "
            + "\n  - ".join(problems))
    print(f"[preflight] OK — credentials{'（upload込み）' if do_upload else ''}・"
          f"ffmpeg・コード すべて揃っています。")


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_genre": None}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def _next_genre(state: dict) -> str:
    last = state.get("last_genre")
    if last is None or last not in ROTATION:
        return DEFAULT_GENRE
    return ROTATION[(ROTATION.index(last) + 1) % len(ROTATION)]


def _date_genre(d: "date | None" = None) -> str:
    """Stateless daily rotation: pick the genre from the calendar day.

    Consecutive days advance by one ordinal, so with a 2-genre ROTATION the
    genre alternates every day without needing a persisted state file. This is
    what the daily scheduled run uses, because each run is a fresh ephemeral
    session with no state.json carried over.

    ROTATION_PHASE offsets the cycle so the automated schedule stays in step
    with videos already posted by hand. The first manual video (2026-08-15)
    was "space", so the phase is set to make that day resolve to "space" and
    the next day resolve to "urban", giving clean day-by-day alternation.
    """
    from datetime import date as _date
    d = d or _date.today()
    return ROTATION[(d.toordinal() + ROTATION_PHASE) % len(ROTATION)]


def run(genre_key: str, topic: str | None, do_upload: bool, subtitles: bool) -> dict:
    from llm_script import generate_script
    from tts import synthesize, audio_duration
    from images import generate_images
    from assemble import assemble
    from thumbnail import make_thumbnail

    genre = GENRES[genre_key]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work = OUTPUT_DIR / f"{genre_key}_{stamp}"
    work.mkdir(parents=True, exist_ok=True)
    print(f"== {genre['label']} == work dir: {work}")

    # 1. Script
    print("[1/6] script generation (OpenAI)…")
    # Pull recent titles from YouTube (scheduled/private included) so the model
    # avoids repeating a theme across days. Stateless — no local history needed.
    from youtube_upload import fetch_recent_titles
    avoid_titles = fetch_recent_titles() if topic is None else []
    if avoid_titles:
        print(f"      重複回避: 直近 {len(avoid_titles)} 件のタイトルを回避対象にします")
    pkg = generate_script(genre_key, topic, avoid_titles=avoid_titles)
    (work / "script.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=2))
    print(f"      topic: {pkg['topic']}")
    print(f"      title: {pkg['title']}")
    print(f"      narration chars: {len(pkg['narration'])}  image prompts: {len(pkg['image_prompts'])}")

    # 2. TTS
    print(f"[2/6] TTS ({config.TTS_PROVIDER})…")
    audio = work / "narration.mp3"
    synthesize(pkg["narration"], audio)
    dur = audio_duration(audio)
    print(f"      audio duration: {dur:.1f}s ({dur/60:.1f} min)")

    # 3. Images
    print(f"[3/6] images (Stability, {len(pkg['image_prompts'])})…")
    imgs = generate_images(pkg["image_prompts"], genre["image_style"], work / "img")

    # 4. Assemble
    print("[4/6] assemble video (ffmpeg)…")
    video = work / "video.mp4"
    assemble(imgs, audio, video, narration=pkg["narration"], subtitles=subtitles)
    print(f"      video: {video}")

    # 5. Thumbnail
    print("[5/6] thumbnail…")
    thumb = work / "thumbnail.png"
    try:
        make_thumbnail(pkg["thumbnail_text"] or pkg["title"], pkg["thumbnail_prompt"], thumb)
    except Exception as e:  # noqa: BLE001
        print(f"      thumbnail failed: {e}")
        thumb = None

    result = {"genre": genre_key, "work_dir": str(work), "video": str(video),
              "title": pkg["title"], "topic": pkg["topic"], "duration_s": dur}

    # 6. Upload (scheduled)
    if do_upload:
        print("[6/6] upload (YouTube, scheduled)…")
        from youtube_upload import upload_video, next_publish_at
        pub = next_publish_at(genre["publish_hour_jst"])
        vid = upload_video(video, pkg["title"], pkg["description"], pkg["tags"],
                           genre["youtube_category_id"], pub, thumb, UPLOAD_PRIVACY)
        result["video_id"] = vid
        result["publish_at_jst"] = pub.isoformat()
        print(f"      scheduled publish: {pub.isoformat()} (JST)  https://youtu.be/{vid}")
    else:
        print("[6/6] upload skipped (--no-upload)")

    (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--genre", choices=list(GENRES.keys()))
    ap.add_argument("--alternate", action="store_true", help="pick next genre from rotation state (state.json)")
    ap.add_argument("--rotate-date", action="store_true",
                    help="pick genre deterministically from the calendar day (stateless; use this for daily scheduled runs)")
    ap.add_argument("--topic", default=None)
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--no-subtitles", action="store_true")
    ap.add_argument("--check-auth", action="store_true",
                    help="verify the YouTube OAuth credential works, print the channel, then exit")
    args = ap.parse_args()

    if args.check_auth:
        from youtube_upload import check_auth
        title = check_auth()
        print(f"[check-auth] OK — 認証成功。投稿先チャンネル: 「{title}」")
        return

    do_upload = not args.no_upload
    preflight(do_upload)  # stop now if a prerequisite is missing

    state = _load_state()
    if args.rotate_date:
        genre_key = _date_genre()
    elif args.alternate:
        genre_key = _next_genre(state)
    elif args.genre:
        genre_key = args.genre
    else:
        genre_key = DEFAULT_GENRE

    t0 = time.time()
    result = run(genre_key, args.topic, do_upload=do_upload, subtitles=not args.no_subtitles)
    state["last_genre"] = genre_key
    _save_state(state)
    print(f"\nDONE in {time.time()-t0:.0f}s -> {result.get('video_id', '(not uploaded)')}")


if __name__ == "__main__":
    main()
