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


def preflight(do_upload: bool, need_tts: bool = True) -> None:
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
    if need_tts and config.TTS_PROVIDER == "google" and not (
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


def run(genre_key: str, topic: str | None, do_upload: bool, subtitles: bool,
        narration: str | None = None, title: str | None = None,
        make_teaser: bool = False) -> dict:
    from llm_script import generate_script, build_from_narration
    from tts import synthesize_timed, audio_duration
    from images import generate_images
    from assemble import assemble
    from thumbnail import make_thumbnail

    genre = GENRES[genre_key]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work = OUTPUT_DIR / f"{genre_key}_{stamp}"
    work.mkdir(parents=True, exist_ok=True)
    print(f"== {genre['label']} == work dir: {work}")

    # 1. Script
    if narration:
        # Provided (hand-written) script: use the narration as-is, generate only
        # the image prompts / description / tags to match it.
        print("[1/6] script from provided narration…")
        pkg = build_from_narration(genre_key, narration, title)
    else:
        print("[1/6] script generation (OpenAI)…")
        # Pull recent titles from YouTube (scheduled/private included) so the
        # model avoids repeating a theme across days. Stateless — no local file.
        from youtube_upload import fetch_recent_titles
        avoid_titles = fetch_recent_titles() if topic is None else []
        if avoid_titles:
            print(f"      重複回避: 直近 {len(avoid_titles)} 件のタイトルを回避対象にします")
        pkg = generate_script(genre_key, topic, avoid_titles=avoid_titles)

    # 1b. Compliance gate — a no-op unless the genre declares compliance:
    # "medical". Runs before TTS so a flagged script is never voiced, and
    # raises rather than publishing something it could not fix.
    import compliance
    pkg = compliance.enforce(pkg, genre)

    (work / "script.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=2))
    print(f"      topic: {pkg['topic']}")
    print(f"      title: {pkg['title']}")
    print(f"      narration chars: {len(pkg['narration'])}  image prompts: {len(pkg['image_prompts'])}")

    # 2. TTS — synthesize per subtitle-unit and measure each unit's real
    #    duration, so burned subtitles stay in sync with the voice.
    print(f"[2/6] TTS ({config.TTS_PROVIDER})…")
    audio = work / "narration.mp3"
    audio, sub_segments = synthesize_timed(pkg["narration"], audio)
    dur = audio_duration(audio)
    print(f"      audio duration: {dur:.1f}s ({dur/60:.1f} min), {len(sub_segments)} subtitle units")

    # 3. Images
    print(f"[3/6] images (Stability, {len(pkg['image_prompts'])})…")
    imgs = generate_images(pkg["image_prompts"], genre["image_style"], work / "img")

    # 4. Assemble
    print("[4/6] assemble video (ffmpeg)…")
    video = work / "video.mp4"
    assemble(imgs, audio, video, narration=pkg["narration"], subtitles=subtitles,
             sub_segments=sub_segments)
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
        vid = upload_video(video, pkg["title"], _description(genre, pkg), pkg["tags"],
                           genre["youtube_category_id"], pub, thumb, UPLOAD_PRIVACY)
        result["video_id"] = vid
        result["publish_at_jst"] = pub.isoformat()
        print(f"      scheduled publish: {pub.isoformat()} (JST)  https://youtu.be/{vid}")

        # 7. Teaser short ("CM" for this long-form): same topic, linked back.
        if make_teaser:
            try:
                result["teaser"] = _build_and_upload_teaser(genre_key, pkg, vid, pub, work)
            except Exception as e:  # noqa: BLE001
                print(f"[teaser] 予告編ショートの生成に失敗（本編は投稿済み）: {e}")
    else:
        print("[6/6] upload skipped (--no-upload)")

    (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _description(genre: dict, pkg: dict) -> str:
    """Final description text: the genre's fixed lead block, then the summary.

    The lead block goes first because YouTube folds the description after the
    first two lines on mobile — anything below the fold is effectively unread
    by someone lying in bed.
    """
    prefix = genre.get("description_prefix") or ""
    body = pkg.get("description") or ""
    return f"{prefix}\n{body}".strip() if prefix else body


def run_ambient(genre_key: str, do_upload: bool, seconds: int | None = None) -> dict:
    """L2: a masking-noise video. No narration, no TTS, no Ken Burns.

    Its job is watch time. A viewer keeps this running for the whole night, and
    that time counts towards the 4,000-hour threshold in full — unlike Shorts
    feed or ad-driven views, which do not count at all.
    """
    from ambient import (build_package, variation, synthesize_masking_noise,
                         render_ambient, params_record)
    from images import generate_images
    from thumbnail import make_thumbnail

    genre = GENRES[genre_key]
    seconds = seconds or config.AMBIENT_SECONDS
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work = OUTPUT_DIR / f"{genre_key}_ambient_{stamp}"
    work.mkdir(parents=True, exist_ok=True)
    print(f"== {genre['label']} / マスキング音源 {seconds/3600:.1f}h == work dir: {work}")

    print("[1/5] メタデータ生成…")
    avoid = []
    if do_upload:
        from youtube_upload import fetch_recent_titles
        avoid = fetch_recent_titles()
    pkg = build_package(genre, seconds, avoid)

    import compliance
    pkg = compliance.enforce(pkg, genre)
    print(f"      title: {pkg['title']}")

    print("[2/5] 静止画（Stability, 1枚）…")
    imgs = generate_images(pkg["image_prompts"], genre["image_style"], work / "img")

    params = variation(pkg["title"])
    print(f"[3/5] マスキングノイズ合成… {params.color} / "
          f"{params.low_hz}Hz・{params.mid_hz}Hz強調 / 上限{params.ceiling_hz}Hz")
    audio = synthesize_masking_noise(work / "noise.m4a", seconds, params)

    print("[4/5] レンダリング（静止画＋長時間音源）…")
    video = render_ambient(imgs[0], audio, work / "video.mp4", seconds)
    print(f"      video: {video} ({video.stat().st_size/1e6:.0f} MB)")

    thumb = work / "thumbnail.png"
    try:
        make_thumbnail(pkg["thumbnail_text"], pkg["thumbnail_prompt"], thumb)
    except Exception as e:  # noqa: BLE001
        print(f"      thumbnail failed: {e}")
        thumb = None

    result = {"genre": genre_key, "mode": "ambient", "work_dir": str(work),
              "video": str(video), "title": pkg["title"], "duration_s": seconds,
              "noise_params": params_record(params)}

    if do_upload:
        print("[5/5] upload (YouTube, scheduled)…")
        from youtube_upload import upload_video, next_publish_at
        pub = next_publish_at(genre["publish_hour_jst"])
        vid = upload_video(video, pkg["title"], _description(genre, pkg), pkg["tags"],
                           genre["youtube_category_id"], pub, thumb, UPLOAD_PRIVACY)
        result["video_id"] = vid
        result["publish_at_jst"] = pub.isoformat()
        print(f"      scheduled publish: {pub.isoformat()} (JST)  https://youtu.be/{vid}")
    else:
        print("[5/5] upload skipped (--no-upload)")

    (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def run_guide(genre_key: str, topic: str | None, do_upload: bool,
              ambient_seconds: int | None = None) -> dict:
    """L3: a spoken explainer that dissolves into an ambient bed.

    The bridge between L1 and L2 — someone who came for the explanation stays
    asleep on the same video, so the watch time of an explainer lands closer to
    that of a noise track.
    """
    from llm_script import generate_script
    from tts import synthesize_timed, audio_duration
    from images import generate_images
    from ambient import (variation, synthesize_masking_noise,
                         combine_narration_and_ambient, assemble_guide, params_record)
    from thumbnail import make_thumbnail

    genre = GENRES[genre_key]
    ambient_seconds = ambient_seconds or config.GUIDE_AMBIENT_SECONDS
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work = OUTPUT_DIR / f"{genre_key}_guide_{stamp}"
    work.mkdir(parents=True, exist_ok=True)
    print(f"== {genre['label']} / 入眠ガイド（解説＋{ambient_seconds/3600:.1f}h） == {work}")

    print("[1/6] 台本生成…")
    avoid = []
    if do_upload:
        from youtube_upload import fetch_recent_titles
        avoid = fetch_recent_titles()
    pkg = generate_script(genre_key, topic, avoid_titles=avoid)

    import compliance
    pkg = compliance.enforce(pkg, genre)
    print(f"      title: {pkg['title']}")

    print("[2/6] TTS…")
    narration_audio, sub_segments = synthesize_timed(pkg["narration"], work / "narration.mp3")
    intro_s = audio_duration(narration_audio)
    print(f"      解説パート: {intro_s/60:.1f} 分")

    print(f"[3/6] 画像（{config.GUIDE_NUM_IMAGES}枚）…")
    imgs = generate_images(pkg["image_prompts"][:config.GUIDE_NUM_IMAGES],
                           genre["image_style"], work / "img")

    params = variation(pkg["title"])
    print(f"[4/6] アンビエント合成 {ambient_seconds/3600:.1f}h…")
    bed = synthesize_masking_noise(work / "bed.m4a", ambient_seconds, params, fade_in=2)
    crossfade = 8
    combined = combine_narration_and_ambient(narration_audio, bed, work / "audio.m4a",
                                             crossfade=crossfade)
    total_s = intro_s + ambient_seconds - crossfade

    print("[5/6] レンダリング（Ken Burns → 静止画）…")
    video = assemble_guide(imgs, combined, intro_s, total_s, work / "video.mp4",
                           sub_segments=sub_segments)
    print(f"      video: {video} ({video.stat().st_size/1e6:.0f} MB)")

    thumb = work / "thumbnail.png"
    try:
        make_thumbnail(pkg["thumbnail_text"] or pkg["title"], pkg["thumbnail_prompt"], thumb)
    except Exception as e:  # noqa: BLE001
        print(f"      thumbnail failed: {e}")
        thumb = None

    result = {"genre": genre_key, "mode": "guide", "work_dir": str(work),
              "video": str(video), "title": pkg["title"], "topic": pkg["topic"],
              "intro_s": intro_s, "ambient_s": ambient_seconds,
              "noise_params": params_record(params)}

    if do_upload:
        print("[6/6] upload (YouTube, scheduled)…")
        from youtube_upload import upload_video, next_publish_at
        pub = next_publish_at(genre["publish_hour_jst"])
        vid = upload_video(video, pkg["title"], _description(genre, pkg), pkg["tags"],
                           genre["youtube_category_id"], pub, thumb, UPLOAD_PRIVACY)
        result["video_id"] = vid
        result["publish_at_jst"] = pub.isoformat()
        print(f"      scheduled publish: {pub.isoformat()} (JST)  https://youtu.be/{vid}")
    else:
        print("[6/6] upload skipped (--no-upload)")

    (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _build_and_upload_teaser(genre_key: str, source_pkg: dict, long_video_id: str,
                             publish_at_jst, work) -> dict:
    """Build a vertical teaser short for a just-uploaded long-form and schedule
    it at the same time, linking back to the full video (description + comment)."""
    from llm_script import generate_teaser
    from tts import synthesize_timed
    from images import generate_images
    from assemble import assemble
    from youtube_upload import upload_video, post_comment
    from config import SHORT_W, SHORT_H, SHORT_FONT_SIZE

    genre = GENRES[genre_key]
    long_url = f"https://youtu.be/{long_video_id}"
    print("[7/7] teaser short (CM) generation…")
    t = generate_teaser(genre_key, source_pkg["topic"], source_pkg["narration"])
    tdir = work / "teaser"
    tdir.mkdir(exist_ok=True)
    audio = tdir / "narration.mp3"
    audio, sub_segments = synthesize_timed(t["narration"], audio)
    imgs = generate_images(t["image_prompts"], genre["image_style"], tdir / "img",
                           aspect="9:16", width=SHORT_W, height=SHORT_H)
    video = tdir / "teaser.mp4"
    assemble(imgs, audio, video, narration=t["narration"], subtitles=True,
             width=SHORT_W, height=SHORT_H, font_size=SHORT_FONT_SIZE, margin_v=140,
             sub_segments=sub_segments)

    title = t["title"] if "#Shorts" in t["title"] else (t["title"][:88] + " #Shorts")
    desc = (f"{t['narration'][:70]}…\n\n"
            f"▼ 事件の全貌・結末は本編で（約15分）\n{long_url}\n\n"
            + " ".join(t.get("hashtags") or ["#Shorts", "#未解決事件", "#ミステリー"]))
    vid = upload_video(video, title, desc, t["tags"], genre["youtube_category_id"],
                       publish_at_jst, None, UPLOAD_PRIVACY)
    post_comment(vid, f"👇 事件の全貌・結末はこちら（本編・約15分）\n{long_url}")
    url = f"https://youtu.be/{vid}"
    print(f"[7/7] teaser done {url} -> links to {long_url}")
    return {"video_id": vid, "url": url, "title": title, "links_to": long_url}


def _load_narration(path: str) -> str:
    """Read a narration script. If it is the structured storyboard markdown
    (with 【ナレーション】 / 【画面指示】 markers) extract only the narration lines;
    otherwise return the file text as-is.
    """
    text = Path(path).read_text(encoding="utf-8")
    if "【ナレーション】" not in text:
        return text.strip()
    out, capture = [], False
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("【ナレーション】"):
            capture = True
            continue
        if s[:1] in ("【", "#", "-", "※", "*") or s.startswith("---"):
            capture = False
            continue
        if capture and s:
            out.append(s)
    return "\n".join(out).strip()


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
    ap.add_argument("--narration-file", default=None,
                    help="build the video from this provided narration script instead of generating one")
    ap.add_argument("--title", default=None, help="explicit video title (for --narration-file / --intro-seed)")
    ap.add_argument("--intro-seed", default=None,
                    help="one-time intro: build from this seed script only while its --intro-title is not yet "
                         "on the channel; once published, fall through to normal research+generate")
    ap.add_argument("--intro-title", default=None, help="title/dedup key for --intro-seed")
    ap.add_argument("--teaser", action="store_true",
                    help="after the long-form upload, also build+upload a vertical teaser short linking to it")
    ap.add_argument("--mode", choices=["narrated", "ambient", "guide"], default="narrated",
                    help="narrated = the standard explainer (default); "
                         "ambient = a masking-noise track (no narration); "
                         "guide = a spoken intro that dissolves into an ambient bed")
    ap.add_argument("--seconds", type=int, default=None,
                    help="override the ambient length in seconds (--mode ambient/guide)")
    args = ap.parse_args()

    if args.check_auth:
        from youtube_upload import check_auth
        title = check_auth()
        print(f"[check-auth] OK — 認証成功。投稿先チャンネル: 「{title}」")
        return

    do_upload = not args.no_upload
    # --mode ambient never speaks, so it must not be blocked on a TTS key.
    preflight(do_upload, need_tts=args.mode != "ambient")

    if args.mode in ("ambient", "guide"):
        genre_key = args.genre or DEFAULT_GENRE
        t0 = time.time()
        fn = run_ambient if args.mode == "ambient" else run_guide
        result = (fn(genre_key, do_upload, args.seconds) if args.mode == "ambient"
                  else fn(genre_key, args.topic, do_upload, args.seconds))
        print(f"\nDONE in {time.time()-t0:.0f}s -> {result.get('video_id', '(not uploaded)')}")
        return

    state = _load_state()
    if args.rotate_date:
        genre_key = _date_genre()
    elif args.alternate:
        genre_key = _next_genre(state)
    elif args.genre:
        genre_key = args.genre
    else:
        genre_key = DEFAULT_GENRE

    # Optional: build from a provided narration (hand-written script).
    narration = None
    title_override = args.title
    if args.narration_file:
        narration = _load_narration(args.narration_file)
        print(f"[script] 台本ファイルを使用: {args.narration_file}（{len(narration)}字）")
    elif args.intro_seed:
        from youtube_upload import fetch_recent_titles
        recent = fetch_recent_titles()
        itl = args.intro_title or ""
        already = bool(itl) and any(itl[:12] in t for t in recent)
        if already:
            print(f"[intro] シード動画『{itl[:20]}…』は既に投稿済み → 通常の調査＋生成に切替")
        else:
            narration = _load_narration(args.intro_seed)
            title_override = itl or title_override
            print(f"[intro] 初回シード台本でビルド: {args.intro_seed}（{len(narration)}字）")

    t0 = time.time()
    result = run(genre_key, args.topic, do_upload=do_upload, subtitles=not args.no_subtitles,
                 narration=narration, title=title_override, make_teaser=args.teaser)
    state["last_genre"] = genre_key
    _save_state(state)
    print(f"\nDONE in {time.time()-t0:.0f}s -> {result.get('video_id', '(not uploaded)')}")


if __name__ == "__main__":
    main()
