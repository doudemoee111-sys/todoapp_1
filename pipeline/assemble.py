"""Assemble the final MP4 from images + narration audio with ffmpeg.

Pipeline:
  1. Render one Ken-Burns (slow zoom/pan) segment per image, each shown for
     total_audio_duration / N seconds.
  2. Concat the silent segments (stream copy).
  3. Mux narration audio; optionally burn soft Japanese subtitles derived from
     the narration (timed proportionally to sentence length).

Everything is defensive: subtitle burning falls back to a plain copy on error.
"""
from __future__ import annotations
import re
import subprocess
import tempfile
from pathlib import Path

from config import VIDEO_W, VIDEO_H, FPS
from tts import audio_duration

_JP_FONT = "Noto Sans CJK JP"


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _ken_burns_segment(img: Path, dur: float, idx: int, out: Path,
                       width: int = VIDEO_W, height: int = VIDEO_H) -> None:
    frames = max(1, round(FPS * dur))
    zi = 0.0006  # zoom increment / frame -> ~+11% over ~8s
    # Alternate horizontal pan direction for variety.
    if idx % 2 == 0:
        x_expr = "x='(iw-iw/zoom)/2+(iw*0.04)*on/{f}'".format(f=frames)
    else:
        x_expr = "x='(iw-iw/zoom)/2-(iw*0.04)*on/{f}'".format(f=frames)
    vf = (
        f"scale={width*2}:{height*2}:force_original_aspect_ratio=increase,"
        f"crop={width*2}:{height*2},"
        f"zoompan=z='min(zoom+{zi},1.15)':d={frames}:{x_expr}:"
        f"y='(ih-ih/zoom)/2':s={width}x{height}:fps={FPS},setsar=1,format=yuv420p"
    )
    _run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(img),
          "-t", f"{dur:.3f}", "-vf", vf,
          # preset=veryfast: スライドショー(静止画+ズーム)では medium と体感差が無く、
          # エンコード時間を大幅短縮。30セグメント分の合計時間を削減する。
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
          "-pix_fmt", "yuv420p", "-r", str(FPS), "-t", f"{dur:.3f}", str(out)])


def _cues_from_narration(narration: str, total: float) -> list[tuple[float, float, str]]:
    """Proportional fallback timing when no measured segments are available:
    split into sentences and allot time by character length."""
    sents = [s.strip() for s in re.split(r"(?<=[。！？\n])", narration) if s.strip()]
    if not sents:
        return []
    weights = [len(s) for s in sents]
    tot_w = sum(weights) or 1
    cues, t = [], 0.0
    for s, w in zip(sents, weights):
        seg = total * w / tot_w
        start, end = t, min(total, t + seg)
        t = end
        cues.append((start, end, s))
    return cues


def _cues_from_segments(segments, total: float) -> list[tuple[float, float, str]]:
    """Exact cues from measured per-unit timings. Each cue is held until the next
    unit actually begins (clamped to the true audio length) so a subtitle never
    disappears before its narration has finished — the viewer always gets the
    full spoken duration to read the line."""
    segs = [s for s in (segments or []) if s and str(s[0]).strip()]
    cues = []
    for i, (text, start, end) in enumerate(segs):
        nxt = segs[i + 1][1] if i + 1 < len(segs) else total
        end = min(total, max(end, nxt))
        start = min(start, end)
        cues.append((start, end, str(text).strip()))
    return cues


def _ass_ts(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600); m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _write_ass(cues, path: Path, width: int, height: int,
               font_size: int, margin_v: int, font: str = _JP_FONT) -> bool:
    """Write an ASS subtitle file with an explicit PlayResX/PlayResY equal to the
    real video size, so FontSize is in TRUE pixels and never gets silently
    upscaled. (Burning a bare SRT lets libass default to a 384x288 layout canvas
    and rescale the font by height/288 — a ~6.7x blow-up on a 1080x1920 vertical
    video, which made captions overflow the frame. ASS with PlayRes fixes that.)"""
    cues = [c for c in cues if c[2].strip()]
    if not cues:
        return False
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: D,{font},{font_size},&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,"
        f"100,100,0,0,1,{max(2, round(font_size/16))},2,2,{max(40, width//14)},"
        f"{max(40, width//14)},{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    def _clean(t: str) -> str:
        return t.replace("\\", " ").replace("{", "(").replace("}", ")").replace("\n", " ").strip()
    body = "".join(
        f"Dialogue: 0,{_ass_ts(s)},{_ass_ts(e)},D,,0,0,0,,{_clean(txt)}\n"
        for s, e, txt in cues)
    path.write_text(header + body, encoding="utf-8")
    return True


def assemble(images: list[Path], audio_path: str | Path, out_path: str | Path,
             narration: str = "", subtitles: bool = True,
             width: int = VIDEO_W, height: int = VIDEO_H,
             font_size: int = 52, margin_v: int = 90,
             sub_segments=None) -> Path:
    audio_path = Path(audio_path)
    out_path = Path(out_path)
    dur = audio_duration(audio_path)
    n = len(images)
    per = dur / n
    tmp = Path(tempfile.mkdtemp(prefix="assemble_"))

    # 1. per-image Ken Burns segments
    segs = []
    for i, img in enumerate(images):
        seg = tmp / f"seg_{i:03d}.mp4"
        d = per if i < n - 1 else (dur - per * (n - 1)) + 0.5  # last absorbs remainder
        _ken_burns_segment(img, max(0.8, d), i, seg, width, height)
        segs.append(seg)
        print(f"  [assemble] segment {i+1}/{n}")

    # 2. concat silent video
    listfile = tmp / "list.txt"
    listfile.write_text("".join(f"file '{s}'\n" for s in segs))
    silent = tmp / "silent.mp4"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
          "-i", str(listfile), "-c", "copy", str(silent)])

    # 3. mux audio (+ optional burned subtitles)
    #    Prefer measured per-unit timings (sub_segments) so each line stays on
    #    screen exactly as long as it is spoken; fall back to proportional split.
    #    Burn as ASS with real PlayRes so the font size is honoured in true pixels
    #    (a bare SRT would be upscaled off-screen on vertical video).
    ass = tmp / "subs.ass"
    if subtitles and sub_segments:
        cues = _cues_from_segments(sub_segments, dur)
    elif subtitles and narration:
        cues = _cues_from_narration(narration, dur)
    else:
        cues = []
    have_subs = _write_ass(cues, ass, width, height, font_size, margin_v)
    if have_subs:
        try:
            vf = f"subtitles={ass.as_posix()}"
            # ★最重要のボトルネック対策: 約10分の動画にASS字幕を焼き込む「全体再エンコード」。
            # preset=medium は重く、生成セッションの時間枠を圧迫していた(診断で特定)。
            # preset=veryfast で画質はほぼ同等のまま、この工程を大幅に高速化する。
            _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(audio_path),
                  "-vf", vf, "-map", "0:v", "-map", "1:a",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_path)])
            return out_path
        except subprocess.CalledProcessError:
            print("  [assemble] subtitle burn failed; muxing without subtitles")

    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(audio_path),
          "-map", "0:v", "-map", "1:a", "-c:v", "copy",
          "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_path)])
    return out_path
