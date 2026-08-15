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
import time
from datetime import datetime
from pathlib import Path

import config
from config import (GENRES, OUTPUT_DIR, STATE_FILE, ROTATION, ROTATION_PHASE,
                    DEFAULT_GENRE, UPLOAD_PRIVACY)


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
    pkg = generate_script(genre_key, topic)
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
    args = ap.parse_args()

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
    result = run(genre_key, args.topic, do_upload=not args.no_upload, subtitles=not args.no_subtitles)
    state["last_genre"] = genre_key
    _save_state(state)
    print(f"\nDONE in {time.time()-t0:.0f}s -> {result.get('video_id', '(not uploaded)')}")


if __name__ == "__main__":
    main()
