"""End-to-end orchestrator: one video from topic -> upload.

This branch serves ONE channel: 睡眠・安眠チャンネル2. The entertainment
channel's genres are not defined here; see config.py.

Usage:
  python run.py                              # narrated video, scheduled upload
  python run.py --mode guide                 # 解説 + アンビエント（入眠ガイド）
  python run.py --mode ambient --seconds 300 # マスキング音源
  python run.py --no-upload                  # build only (skip YouTube)
  python run.py --topic "..."                # force a specific topic

Stages: script (OpenAI) -> TTS (Google) -> images (Stability) -> assemble (ffmpeg)
        -> thumbnail -> upload (YouTube, scheduled at genre's JST peak hour).
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import config
from config import (GENRES, OUTPUT_DIR, STATE_FILE, ROTATION, ROTATION_PHASE,
                    DEFAULT_GENRE, UPLOAD_PRIVACY)


class PreflightError(RuntimeError):
    """Raised when the run can't possibly succeed, before any work is done."""


# Set by --publish-at. None means "use the genre's fixed peak hour", which is the
# scheduled-run behaviour; an explicit value is for the manual case where that
# slot is already taken (a re-run after a partial failure, or a second video on
# a day whose slot is filled).
PUBLISH_AT_OVERRIDE: datetime | None = None


def _publish_at(genre: dict) -> datetime:
    """When to schedule this video, honouring --publish-at over the genre default."""
    from youtube_upload import next_publish_at
    if PUBLISH_AT_OVERRIDE is not None:
        return PUBLISH_AT_OVERRIDE
    return next_publish_at(genre["publish_hour_jst"])


def preflight(do_upload: bool, need_tts: bool = True, genre: dict | None = None) -> None:
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

    # Channel guard. Engages when the genre names its channel in config.py or
    # the environment sets EXPECTED_CHANNEL_ID; a genre with neither is left
    # exactly as it was. Runs here rather than at upload time so a crossed
    # credential costs one API unit instead of a full generation.
    if do_upload:
        from youtube_upload import assert_expected_channel, expected_channel_id
        want, source = expected_channel_id(genre)
        if want:
            ch = assert_expected_channel(genre=genre)
            print(f"[preflight] 投稿先チャンネル確認: 「{ch['title']}」({ch['id']}) "
                  f"— {source} と一致")
        else:
            print("[preflight] 警告: 投稿先チャンネルが固定されていません。"
                  "config.py のジャンルに channel_id を入れるか、環境変数 "
                  "EXPECTED_CHANNEL_ID を設定してください")

    # The advertising block is gated on the topic axis, and that gate is a list
    # index. Check it here, where a mismatch costs nothing, rather than
    # discovering it in a published description.
    if genre and genre.get("topic_axes"):
        from affiliate import check_axis_map, AffiliateError
        try:
            check_axis_map()
        except AffiliateError as e:
            raise PreflightError(str(e)) from e
        print("[preflight] アフィリエイトの切り口指定: topic_axes と一致")

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

    Kept because --rotate-date is still a valid flag, but on this branch ROTATION
    holds a single genre, so it always resolves to that one. It mattered when
    this file also carried the entertainment channel's genres; it no longer does.
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
    t0 = time.time()
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
    # Persist the measurements: rebuilding a description later (chapters) needs
    # them, and re-synthesising just to recover timings costs an API round-trip
    # and risks drifting from the audio that was actually published.
    (work / "segments.json").write_text(json.dumps(
        [{"text": t, "start": a, "end": b} for t, a, b in sub_segments],
        ensure_ascii=False, indent=2))
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
        make_thumbnail(pkg["thumbnail_text"] or pkg["title"], thumb,
                       subtitle=pkg.get("topic", ""))
    except Exception as e:  # noqa: BLE001
        print(f"      thumbnail failed: {e}")
        thumb = None

    result = {"genre": genre_key, "mode": "narrated", "work_dir": str(work),
              "video": str(video), "title": pkg["title"], "topic": pkg["topic"],
              "axis": pkg.get("axis"), "thumbnail_text": pkg.get("thumbnail_text", ""),
              "duration_s": dur}

    # 6. Upload (scheduled)
    if do_upload:
        print("[6/6] upload (YouTube, scheduled)…")
        from youtube_upload import (upload_video, fetch_recent_videos,
                                    add_to_playlist, ensure_playlist)
        pub = _publish_at(genre)
        related = fetch_recent_videos(3)
        # Resolved BEFORE the upload so the description can carry &list= links.
        playlist_id = (ensure_playlist(genre["playlist_title"],
                                       genre.get("playlist_description", ""))
                       if genre.get("playlist_title") else None)
        vid = upload_video(video, pkg["title"],
                           _description(genre, pkg, sub_segments, related, playlist_id), pkg["tags"],
                           genre["youtube_category_id"], pub, thumb, UPLOAD_PRIVACY)
        result["video_id"] = vid
        result["publish_at_jst"] = pub.isoformat()
        if genre.get("playlist_title"):
            add_to_playlist(vid, genre["playlist_title"],
                            genre.get("playlist_description", ""))
        _series_comment(vid, related, playlist_id)
        print(f"      scheduled publish: {pub.isoformat()} (JST)  https://youtu.be/{vid}")

        # 7. Teaser short ("CM" for this long-form): same topic, linked back.
        if make_teaser:
            try:
                result["teaser"] = _build_and_upload_teaser(genre_key, pkg, vid, pub, work)
            except Exception as e:  # noqa: BLE001
                print(f"[teaser] 予告編ショートの生成に失敗（本編は投稿済み）: {e}")
    else:
        print("[6/6] upload skipped (--no-upload)")

    result["elapsed_s"] = round(time.time() - t0)
    (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    append_runlog(result)
    push_runlog(f"chore(runlog): {result.get('mode', 'narrated')} 完了 "
                f"{result.get('video_id', '(未投稿)')}")
    return result


def _chapter_timestamps(pkg: dict, sub_segments) -> list[tuple[float, str]]:
    """(start_seconds, heading) per chapter, from the measured subtitle timings.

    YouTube turns a timestamp list in the description into chapter markers, which
    give the video key-moment entries in search and let a viewer jump to the part
    they came for. The timings are real measurements from synthesize_timed, not a
    proportional guess, so they line up with the burned subtitles.

    Matching is done on whitespace-stripped text because the subtitle units are
    re-split and stripped copies of the narration.
    """
    chapters = [c for c in (pkg.get("chapters") or []) if c.get("heading")]
    if len(chapters) < 3 or not sub_segments:
        return []   # YouTube ignores a chapter list shorter than 3 anyway

    def bare(t: str) -> str:
        return "".join((t or "").split())

    # Character offset where each chapter starts, in the whitespace-free narration.
    bounds, acc = [], 0
    for c in chapters:
        bounds.append(acc)
        acc += len(bare(c["narration"]))

    out, ci, pos = [], 0, 0
    for text, start, _end in sub_segments:
        while ci < len(bounds) and pos >= bounds[ci]:
            out.append((start if ci else 0.0, chapters[ci]["heading"]))
            ci += 1
        pos += len(bare(text))
    while ci < len(chapters):      # trailing chapters the units never reached
        out.append((sub_segments[-1][1], chapters[ci]["heading"]))
        ci += 1
    return out


def _fmt_ts(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


RUNLOG = config.ASSETS_DIR / "runlog.md"


def push_runlog(message: str) -> bool:
    """Commit and push runlog.md from inside the pipeline, not from the caller.

    The trigger prompt also has a push step, but a run that is cut short never
    reaches it — which is exactly the case the log exists to detect. Pushing from
    here means the evidence survives the failure it is meant to record.

    Two files are staged, and only these two, so a half-finished working tree
    cannot ride along. runlog.md is the record of the run. bookends.json is the
    memory the next run reads to avoid opening with the sentence this one used —
    it exists precisely to cross container boundaries, so leaving it unpushed
    made it a file that was rewritten from scratch every night and never read.
    Best-effort throughout: a repository this code cannot push to is a reporting
    problem, never a reason to fail a video that already uploaded.
    """
    repo = config.ROOT.parent
    branch = "claude/youtube-sleep-content-automation-4k28y3"
    carried = [RUNLOG, config.ASSETS_DIR / "bookends.json"]
    rels = [str(p.relative_to(repo)) for p in carried if p.exists()]
    try:
        for attempt in range(3):
            subprocess.run(["git", "add", *rels], cwd=repo, check=True,
                           capture_output=True, timeout=60)
            done = subprocess.run(["git", "commit", "-m", message], cwd=repo,
                                  capture_output=True, text=True, timeout=60)
            if done.returncode != 0 and "nothing to commit" in done.stdout:
                return True
            pushed = subprocess.run(["git", "push", "origin", branch], cwd=repo,
                                    capture_output=True, text=True, timeout=180)
            if pushed.returncode == 0:
                print(f"  [runlog] push しました: {message}")
                return True
            # Someone else pushed first; rebase onto them and try again.
            subprocess.run(["git", "pull", "--rebase", "origin", branch], cwd=repo,
                           capture_output=True, timeout=180)
            time.sleep(2 ** attempt)
        print("  [runlog] push できませんでした（記録はローカルに残ります）")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"  [runlog] push に失敗（続行）: {e}")
        return False


def abort_runlog(mode: str, error: BaseException) -> None:
    """Write why a run stopped, and push it.

    The message matters more than the fact: "GOOGLE_TTS_API_KEY 未設定" and
    "ChannelMismatch" call for completely different fixes, and neither is
    visible from outside the container otherwise.
    """
    reason = f"{type(error).__name__}: {str(error)}".replace("\n", " ")[:110]
    append_runlog({"mode": mode, "title": reason}, phase="abort")
    from datetime import timezone, timedelta
    stamp = datetime.now(timezone(timedelta(hours=9))).strftime("%m/%d %H:%M")
    push_runlog(f"chore(runlog): {stamp} {mode} 中断")


def start_runlog(genre_key: str, mode: str, axis=None) -> None:
    """Record that a run began, and push it immediately.

    Written before any generation so that a run which dies mid-way still leaves
    a trace. A start row with no matching finish row is the signal that the
    session was cut off — which nothing else in this system can tell us from
    outside the container.
    """
    append_runlog({"mode": mode, "axis": axis, "title": "（実行開始）",
                   "genre": genre_key}, phase="start")
    from datetime import timezone, timedelta
    stamp = datetime.now(timezone(timedelta(hours=9))).strftime("%m/%d %H:%M")
    push_runlog(f"chore(runlog): {stamp} {mode} 開始")


def append_runlog(result: dict, phase: str = "done") -> None:
    """Leave one line of evidence per run, in the repository.

    A scheduled run happens in a container nobody can reach afterwards, and it
    pushes nothing, so from outside there is no way to tell a finished video from
    a run that died after two minutes. The routine's own recorded duration does
    not answer it either — it reads ~110s whether the mode is a 10-minute
    explainer or a 2-hour guide, so it is measuring the session hand-off, not the
    work.

    One appended row fixes that: whoever looks at the repo next can see what ran,
    what it produced, and how long it took. Best-effort — a logging failure must
    never cost an upload that already succeeded.
    """
    try:
        from datetime import timezone, timedelta
        jst = datetime.now(timezone(timedelta(hours=9))).strftime("%m/%d %H:%M")
        mark = {"start": "▶ 開始", "abort": "✖ 中断", "done": "✔ 完了"}[phase]
        row = (f"| {jst} | {mark} "
               f"| {result.get('mode', 'narrated')} "
               f"| {result.get('axis', '-')} "
               f"| {str(result.get('title', ''))[:110 if phase == 'abort' else 34]} "
               f"| {result.get('thumbnail_text', '')[:14]} "
               f"| {result.get('duration_s', 0) / 60:.0f}分 "
               f"| {result.get('elapsed_s', 0) / 60:.0f}分 "
               f"| {result.get('video_id', '(未投稿)')} "
               f"| {str(result.get('publish_at_jst', ''))[5:16]} |\n")
        if not RUNLOG.exists():
            RUNLOG.write_text(
                "# 実行記録\n\n"
                "定期実行が残す唯一の証跡。リポジトリの外からは実行の成否が見えないため、\n"
                "実行の開始時と完了時に1行ずつ追記し、その都度pushする。\n"
                "**▶開始 の行があるのに ✔完了 の行が無ければ、その実行は途中で切られている。**\n\n"
                "| 日時(JST) | 段階 | mode | 切口 | タイトル | サムネ | 尺 | 所要 | videoId | 公開予定 |\n"
                "|---|---|---|---|---|---|---|---|---|---|\n", encoding="utf-8")
        with RUNLOG.open("a", encoding="utf-8") as f:
            f.write(row)
        print(f"  [runlog] {RUNLOG.name} に追記しました")
    except Exception as e:  # noqa: BLE001
        print(f"  [runlog] 追記に失敗（続行）: {e}")


def playlist_url(playlist_id: str | None) -> str:
    return f"https://www.youtube.com/playlist?list={playlist_id}" if playlist_id else ""


def watch_url(video_id: str, playlist_id: str | None = None) -> str:
    """A watch link that keeps the viewer inside the series when possible.

    Plain string building, kept out of youtube_upload deliberately: that module
    constructs an API client on import, and a description should be renderable
    (and checkable) without credentials installed.
    """
    if playlist_id:
        return f"https://www.youtube.com/watch?v={video_id}&list={playlist_id}"
    return f"https://youtu.be/{video_id}"


def _description(genre: dict, pkg: dict, sub_segments=None,
                 related: list[tuple[str, str]] | None = None,
                 playlist_id: str | None = None) -> str:
    """Final description: lead block, chapters, summary, then links to siblings.

    The lead block goes first because YouTube folds the description after the
    first two lines on mobile — anything below the fold is effectively unread
    by someone lying in bed.

    Chapters come next: YouTube reads a timestamp list starting at 0:00 as
    chapter markers, which surface as key moments in search and let a viewer
    jump to the part they came for instead of bouncing.

    The sibling links are the cheapest suggested-video lever available here —
    a viewer who finishes has somewhere on this channel to go next.
    """
    parts = []

    # The affiliate block goes FIRST, above the channel's own lead line. YouTube
    # folds a description after roughly two lines on mobile, and under the 2023
    # ステマ規制 the advertising has to be identifiable — a disclosure the viewer
    # must tap "もっと見る" to reach is not. The hook lives in the title and the
    # thumbnail anyway; the first description line is a poor place to spend it,
    # and it is the affiliate, not the advertiser, who is sanctioned here.
    #
    # Empty until assets/affiliate_links.json has a URL. A 薬機法 violation in a
    # hand-written label stops the run rather than publishing it: the labels are
    # static, so a failure means the file needs an edit, not a retry.
    from affiliate import description_block
    links = description_block(pkg.get("axis"))
    if links:
        parts.append(links)

    if genre.get("description_prefix"):
        parts.append(genre["description_prefix"].rstrip())

    chapters = _chapter_timestamps(pkg, sub_segments) if sub_segments else []
    if chapters:
        parts.append("\n".join(["【目次】"] + [f"{_fmt_ts(t)} {h}" for t, h in chapters]))

    if pkg.get("description"):
        parts.append(pkg["description"].strip())

    if related:
        # &list= rather than a bare youtu.be link: entering through the playlist
        # is what makes the next video auto-play when this one ends. A bare link
        # drops the viewer out of the series at the very moment they were most
        # likely to keep watching.
        parts.append("\n".join(
            ["▼ このチャンネルの他の動画"]
            + [f"・{t}\n  {watch_url(v, playlist_id)}" for t, v in related]))

    if playlist_id:
        parts.append(f"▼ 続けて見る（再生リスト・自動で次が再生されます）\n"
                     f"{playlist_url(playlist_id)}")

    return "\n\n".join(parts).strip()


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
    t0 = time.time()
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
        make_thumbnail(pkg["thumbnail_text"], thumb, subtitle=pkg.get("topic", ""))
    except Exception as e:  # noqa: BLE001
        print(f"      thumbnail failed: {e}")
        thumb = None

    result = {"genre": genre_key, "mode": "ambient", "work_dir": str(work),
              "axis": pkg.get("axis"), "thumbnail_text": pkg.get("thumbnail_text", ""),
              "video": str(video), "title": pkg["title"], "duration_s": seconds,
              "noise_params": params_record(params)}

    if do_upload:
        print("[5/5] upload (YouTube, scheduled)…")
        from youtube_upload import (upload_video, fetch_recent_videos,
                                    add_to_playlist, ensure_playlist)
        pub = _publish_at(genre)
        related = fetch_recent_videos(3)
        # Resolved BEFORE the upload so the description can carry &list= links.
        playlist_id = (ensure_playlist(genre["playlist_title"],
                                       genre.get("playlist_description", ""))
                       if genre.get("playlist_title") else None)
        vid = upload_video(video, pkg["title"],
                           _description(genre, pkg, None, related, playlist_id), pkg["tags"],
                           genre["youtube_category_id"], pub, thumb, UPLOAD_PRIVACY)
        result["video_id"] = vid
        result["publish_at_jst"] = pub.isoformat()
        if genre.get("playlist_title"):
            add_to_playlist(vid, genre["playlist_title"],
                            genre.get("playlist_description", ""))
        _series_comment(vid, related, playlist_id)
        print(f"      scheduled publish: {pub.isoformat()} (JST)  https://youtu.be/{vid}")
    else:
        print("[5/5] upload skipped (--no-upload)")

    result["elapsed_s"] = round(time.time() - t0)
    (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    append_runlog(result)
    push_runlog(f"chore(runlog): {result.get('mode', 'narrated')} 完了 "
                f"{result.get('video_id', '(未投稿)')}")
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
    t0 = time.time()
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
        make_thumbnail(pkg["thumbnail_text"] or pkg["title"], thumb,
                       subtitle=pkg.get("topic", ""))
    except Exception as e:  # noqa: BLE001
        print(f"      thumbnail failed: {e}")
        thumb = None

    result = {"genre": genre_key, "mode": "guide", "work_dir": str(work),
              "axis": pkg.get("axis"), "thumbnail_text": pkg.get("thumbnail_text", ""),
              "video": str(video), "title": pkg["title"], "topic": pkg["topic"],
              "intro_s": intro_s, "ambient_s": ambient_seconds,
              "noise_params": params_record(params)}

    if do_upload:
        print("[6/6] upload (YouTube, scheduled)…")
        from youtube_upload import (upload_video, fetch_recent_videos,
                                    add_to_playlist, ensure_playlist)
        pub = _publish_at(genre)
        related = fetch_recent_videos(3)
        # Resolved BEFORE the upload so the description can carry &list= links.
        playlist_id = (ensure_playlist(genre["playlist_title"],
                                       genre.get("playlist_description", ""))
                       if genre.get("playlist_title") else None)
        vid = upload_video(video, pkg["title"],
                           _description(genre, pkg, sub_segments, related, playlist_id), pkg["tags"],
                           genre["youtube_category_id"], pub, thumb, UPLOAD_PRIVACY)
        result["video_id"] = vid
        result["publish_at_jst"] = pub.isoformat()
        if genre.get("playlist_title"):
            add_to_playlist(vid, genre["playlist_title"],
                            genre.get("playlist_description", ""))
        _series_comment(vid, related, playlist_id)
        print(f"      scheduled publish: {pub.isoformat()} (JST)  https://youtu.be/{vid}")
    else:
        print("[6/6] upload skipped (--no-upload)")

    result["elapsed_s"] = round(time.time() - t0)
    (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    append_runlog(result)
    push_runlog(f"chore(runlog): {result.get('mode', 'narrated')} 完了 "
                f"{result.get('video_id', '(未投稿)')}")
    return result


def _series_comment(video_id: str, related, playlist_id: str | None) -> None:
    """Put the next step in a comment as well as the description.

    The description is folded on mobile and the sibling links sit below the
    fold; the top comment is visible without tapping anything. Pinning still has
    to be done by hand — the Data API has no pin endpoint — so this prints a
    reminder rather than pretending it is finished.
    """
    from youtube_upload import post_comment
    lines = []
    if related:
        title, vid = related[0]
        lines.append(f"👇 続けて見るなら\n・{title}\n  {watch_url(vid, playlist_id)}")
    if playlist_id:
        lines.append(f"▼ 再生リスト（自動で次が再生されます）\n{playlist_url(playlist_id)}")
    if not lines:
        return
    if post_comment(video_id, "\n\n".join(lines)):
        print("  [comment] 次の動画への導線をコメントしました"
              "（固定はStudioで手動: コメント右上の︙→「固定」）")


def _build_and_upload_teaser(genre_key: str, source_pkg: dict, long_video_id: str,
                             publish_at_jst, work) -> dict:
    """Build a vertical teaser short for a just-uploaded long-form and schedule
    it at the same time, linking back to the full video (description + comment)."""
    from llm_script import generate_teaser
    from tts import synthesize_timed
    from images import generate_images
    from assemble import assemble
    from youtube_upload import upload_video, post_comment
    from config import SHORT_W, SHORT_H, SHORT_FONT_SIZE, teaser_profile

    genre = GENRES[genre_key]
    prof = teaser_profile(genre_key)
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
            f"{prof['desc_cta']}\n{long_url}\n\n"
            + " ".join(t.get("hashtags") or prof["hashtags"]))
    vid = upload_video(video, title, desc, t["tags"], genre["youtube_category_id"],
                       publish_at_jst, None, UPLOAD_PRIVACY)
    post_comment(vid, f"{prof['comment_cta']}\n{long_url}")
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


def _assert_known_genre(key: str) -> str:
    """Fail with an explanation, not a KeyError, when a genre is not on this branch.

    The likely cause is a trigger or a command left over from the entertainment
    channel. Running one here would build that channel's video against this
    channel's credentials — the exact accident this branch is arranged to
    prevent — so it stops before spending anything.
    """
    if key in GENRES:
        return key
    raise PreflightError(
        f"ジャンル「{key}」はこのブランチには存在しません。\n"
        f"  このブランチは睡眠・安眠チャンネル2の専用です（利用可能: {', '.join(GENRES)}）。\n"
        "  space / urban / mystery は別チャンネルのジャンルです。\n"
        "  そちらのブランチと環境で実行してください。")


def _resolve_genre(args, state: dict) -> str:
    """The one place that decides which genre this invocation runs.

    --rotate-date and --alternate only make sense for the daily entertainment
    rotation, so they are ignored for the sleep modes, which are driven by a
    fixed weekday schedule instead.
    """
    if args.genre:
        return _assert_known_genre(args.genre)
    if args.mode in ("ambient", "guide"):
        return _assert_known_genre(DEFAULT_GENRE)
    if args.rotate_date:
        return _assert_known_genre(_date_genre())
    if args.alternate:
        return _assert_known_genre(_next_genre(state))
    return _assert_known_genre(DEFAULT_GENRE)


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
    ap.add_argument("--publish-at", default=None, metavar="'YYYY-MM-DD HH:MM'",
                    help="schedule publication at this JST time instead of the genre's peak hour; "
                         "use when that slot is already taken")
    args = ap.parse_args()

    if args.publish_at:
        from youtube_upload import JST
        try:
            when = datetime.strptime(args.publish_at, "%Y-%m-%d %H:%M").replace(tzinfo=JST)
        except ValueError:
            raise SystemExit(f"--publish-at は 'YYYY-MM-DD HH:MM'（JST）の形式で指定してください: {args.publish_at!r}")
        if when <= datetime.now(JST):
            raise SystemExit(f"--publish-at は未来の時刻を指定してください（JST 現在 "
                             f"{datetime.now(JST):%Y-%m-%d %H:%M}、指定 {when:%Y-%m-%d %H:%M}）。")
        globals()["PUBLISH_AT_OVERRIDE"] = when
        print(f"[publish-at] 予約公開を {when:%Y-%m-%d %H:%M} JST に固定します（ジャンル既定の時刻は使いません）")

    if args.check_auth:
        from youtube_upload import current_channel, assert_expected_channel
        g = GENRES.get(args.genre) if args.genre else None
        ch = current_channel()
        assert_expected_channel(ch, genre=g)   # raises when it is the wrong channel
        print(f"[check-auth] OK — 認証成功。投稿先チャンネル: 「{ch['title']}」")
        print(f"[check-auth] channelId: {ch['id']}")
        if not os.environ.get("EXPECTED_CHANNEL_ID", "").strip():
            print("[check-auth] ヒント: この channelId を環境変数 EXPECTED_CHANNEL_ID に設定すると、"
                  "認証情報が他チャンネルのものに入れ替わったとき、投稿前に中断します。")
        return

    do_upload = not args.no_upload
    state = _load_state()

    # Resolve the genre once, before anything else: preflight needs it to know
    # which channel this run is allowed to post to, and every path below needs
    # the same answer. Deciding it twice is how the two disagree.
    genre_key = _resolve_genre(args, state)

    # --mode ambient never speaks, so it must not be blocked on a TTS key.
    # Announce the run before anything can stop it. preflight raises on a missing
    # key, a crossed channel or a missing tool, and until now that path wrote
    # nothing anywhere reachable — the run simply vanished.
    start_runlog(genre_key, args.mode)
    try:
        preflight(do_upload, need_tts=args.mode != "ambient", genre=GENRES[genre_key])
    except Exception as e:  # noqa: BLE001
        abort_runlog(args.mode, e)
        raise

    if args.mode in ("ambient", "guide"):
        t0 = time.time()
        fn = run_ambient if args.mode == "ambient" else run_guide
        try:
            result = (fn(genre_key, do_upload, args.seconds) if args.mode == "ambient"
                      else fn(genre_key, args.topic, do_upload, args.seconds))
        except Exception as e:  # noqa: BLE001
            abort_runlog(args.mode, e)
            raise
        print(f"\nDONE in {time.time()-t0:.0f}s -> {result.get('video_id', '(not uploaded)')}")
        return

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
    try:
        result = run(genre_key, args.topic, do_upload=do_upload, subtitles=not args.no_subtitles,
                     narration=narration, title=title_override, make_teaser=args.teaser)
    except Exception as e:  # noqa: BLE001
        abort_runlog(args.mode, e)
        raise
    state["last_genre"] = genre_key
    _save_state(state)
    print(f"\nDONE in {time.time()-t0:.0f}s -> {result.get('video_id', '(not uploaded)')}")


if __name__ == "__main__":
    main()
