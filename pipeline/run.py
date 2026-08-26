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


class WrongBranchGenreError(RuntimeError):
    """A genre belonging to another channel/branch was requested on this one."""


def assert_genre_scope(genre_key: str) -> None:
    """混在防止(コード側の相互アイソレーション)。

    このブランチは「世界の雑学王」専用。睡眠チャンネルは別組織・別ブランチで管理して
    おり、その sleep 等のジャンルはここには存在しない。存在しないジャンルを要求されたら、
    API を一切叩かず(=1円も使わず)に停止する。睡眠部門が自ブランチで当チャンネルの
    ジャンル(space/urban/mystery)を弾いたのと対になる措置。
    """
    if genre_key in GENRES:
        return
    from config import BRANCH_LABEL, FOREIGN_GENRE_OWNERS
    avail = " / ".join(GENRES.keys())
    owner = FOREIGN_GENRE_OWNERS.get(genre_key)
    if owner:
        raise WrongBranchGenreError(
            f"ジャンル「{genre_key}」はこのブランチには存在しません。"
            f"このブランチは『{BRANCH_LABEL}』専用です（利用可能: {avail}）。"
            f"「{genre_key}」は別チャンネル（{owner}）のジャンルです。"
            "混在防止のため、動画を生成せず・APIを一切呼ばずに停止しました。")
    raise WrongBranchGenreError(
        f"未知のジャンル「{genre_key}」です（利用可能: {avail}）。"
        f"このブランチは『{BRANCH_LABEL}』専用です。")


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


def run(genre_key: str, topic: str | None, do_upload: bool, subtitles: bool,
        narration: str | None = None, title: str | None = None,
        make_teaser: bool = False, publish_now: bool = False) -> dict:
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
        make_thumbnail(pkg["thumbnail_text"] or pkg["title"], pkg["thumbnail_prompt"], thumb,
                       genre_key=genre_key)
    except Exception as e:  # noqa: BLE001
        print(f"      thumbnail failed: {e}")
        thumb = None

    result = {"genre": genre_key, "work_dir": str(work), "video": str(video),
              "title": pkg["title"], "topic": pkg["topic"], "duration_s": dur}

    # 6. Upload (scheduled)
    if do_upload:
        print("[6/6] upload (YouTube, scheduled)…")
        from youtube_upload import (upload_video, next_publish_at,
                                    ensure_playlist, add_to_playlist)

        # 6a. Related-video boost: align metadata to the popular-video cluster so
        #     we surface in their "next up / suggested" rail.
        try:
            from related_boost import build_related_boost, merge_boost
            merge_boost(pkg, build_related_boost(genre_key, pkg["topic"], pkg["title"]))
        except Exception as e:  # noqa: BLE001
            print(f"      [related] 関連動画最適化はスキップ: {e}")

        pub = None
        if publish_now:
            # Immediate public post (make-up for a missed day). The channel guard
            # in upload_video still blocks the wrong channel.
            vid = upload_video(video, pkg["title"], pkg["description"], pkg["tags"],
                               genre["youtube_category_id"], None, thumb, "public")
            result["video_id"] = vid
            result["published"] = "public (即時公開)"
            print(f"      published NOW (public)  https://youtu.be/{vid}")
        else:
            pub = next_publish_at(genre["publish_hour_jst"])
            vid = upload_video(video, pkg["title"], pkg["description"], pkg["tags"],
                               genre["youtube_category_id"], pub, thumb, UPLOAD_PRIVACY)
            result["video_id"] = vid
            result["publish_at_jst"] = pub.isoformat()
            print(f"      scheduled publish: {pub.isoformat()} (JST)  https://youtu.be/{vid}")

        # 6b. Playlist回遊: chain into the genre playlist (session watch-time boost).
        pl_title = genre.get("playlist_title") or f"【保存版】{genre['label']}まとめ"
        pl_id = ensure_playlist(pl_title, genre.get("channel_tagline", ""))
        if pl_id and add_to_playlist(vid, pl_id):
            result["playlist"] = pl_title

        # 6c. External promotion: 予約投稿なので自動投稿はせず、公開後に手動投稿する
        #     ための Threads 下書きを毎回作って報告に出す（ユーザー方針＝都度手動投稿）。
        try:
            from social_promote import promote_everywhere, format_draft_block
            promo = promote_everywhere(pkg["title"], vid, pkg, genre_key, publish_at_jst=pub)
            result["promo"] = promo
            if promo.get("draft_text"):
                print(format_draft_block(promo))
                (work / "threads_draft_long.txt").write_text(promo["draft_text"], encoding="utf-8")
                result.setdefault("threads_drafts", []).append(
                    {k: promo.get(k) for k in ("kind", "draft_text", "url", "publish_at_jst")})
        except Exception as e:  # noqa: BLE001
            print(f"      [promo] Threads下書きはスキップ: {e}")

        # 7. Teaser short ("CM" for this long-form): same topic, linked back.
        if make_teaser:
            try:
                result["teaser"] = _build_and_upload_teaser(genre_key, pkg, vid, pub, work)
                if result["teaser"].get("threads_draft"):
                    result.setdefault("threads_drafts", []).append(result["teaser"]["threads_draft"])
            except Exception as e:  # noqa: BLE001
                print(f"[teaser] 予告編ショートの生成に失敗（本編は投稿済み）: {e}")
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
    from config import SHORT_W, SHORT_H, SHORT_FONT_SIZE, SHORT_SUB_MAXLEN

    genre = GENRES[genre_key]
    long_url = f"https://youtu.be/{long_video_id}"
    print("[7/7] teaser short (CM) generation…")
    t = generate_teaser(genre_key, source_pkg["topic"], source_pkg["narration"])
    tdir = work / "teaser"
    tdir.mkdir(exist_ok=True)
    audio = tdir / "narration.mp3"
    # Short captions for the narrow vertical frame (1-2 lines each).
    audio, sub_segments = synthesize_timed(t["narration"], audio, max_sub_len=SHORT_SUB_MAXLEN)
    imgs = generate_images(t["image_prompts"], genre["image_style"], tdir / "img",
                           aspect="9:16", width=SHORT_W, height=SHORT_H)
    video = tdir / "teaser.mp4"
    assemble(imgs, audio, video, narration=t["narration"], subtitles=True,
             width=SHORT_W, height=SHORT_H, font_size=SHORT_FONT_SIZE, margin_v=180,
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
    teaser_result = {"video_id": vid, "url": url, "title": title, "links_to": long_url}
    # 予告編ショート用の Threads 下書きも都度作成（公開後に手動投稿）。
    try:
        from social_promote import promote_everywhere, format_draft_block
        tdraft = promote_everywhere(title, vid, t, genre_key, publish_at_jst=publish_at_jst)
        if tdraft.get("draft_text"):
            print(format_draft_block(tdraft))
            (tdir / "threads_draft_teaser.txt").write_text(tdraft["draft_text"], encoding="utf-8")
            teaser_result["threads_draft"] = {
                k: tdraft.get(k) for k in ("kind", "draft_text", "url", "publish_at_jst")}
    except Exception as e:  # noqa: BLE001
        print(f"[teaser] Threads下書きはスキップ: {e}")
    return teaser_result


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
    ap.add_argument("--genre",
                    help="genre key (space/urban/mystery). 別チャンネルのジャンル(sleep等)は"
                         "assert_genre_scope が無料で停止する")
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
    ap.add_argument("--publish-now", action="store_true",
                    help="publish immediately as public (make-up for a missed day) instead of scheduling")
    args = ap.parse_args()

    if args.check_auth:
        from youtube_upload import check_auth
        title = check_auth()
        print(f"[check-auth] OK — 認証成功。投稿先チャンネル: 「{title}」")
        return

    do_upload = not args.no_upload

    state = _load_state()
    if args.rotate_date:
        genre_key = _date_genre()
    elif args.alternate:
        genre_key = _next_genre(state)
    elif args.genre:
        genre_key = args.genre
    else:
        genre_key = DEFAULT_GENRE

    # 混在防止: 別チャンネル(睡眠)のジャンルなら、preflight や API 呼び出しの前に
    # 1円も使わず停止する。睡眠部門の相互アイソレーションと対になる措置。
    try:
        assert_genre_scope(genre_key)
    except WrongBranchGenreError as e:
        print(f"[scope] {e}")
        return

    preflight(do_upload)  # stop now if a prerequisite is missing

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
                 narration=narration, title=title_override, make_teaser=args.teaser,
                 publish_now=args.publish_now)
    state["last_genre"] = genre_key
    _save_state(state)
    print(f"\nDONE in {time.time()-t0:.0f}s -> {result.get('video_id', '(not uploaded)')}")


if __name__ == "__main__":
    main()
