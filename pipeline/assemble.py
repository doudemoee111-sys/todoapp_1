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


def _ken_burns_segment(img: Path, dur: float, idx: int, out: Path) -> None:
    frames = max(1, round(FPS * dur))
    zi = 0.0006  # zoom increment / frame -> ~+11% over ~8s
    # Alternate horizontal pan direction for variety.
    if idx % 2 == 0:
        x_expr = "x='(iw-iw/zoom)/2+(iw*0.04)*on/{f}'".format(f=frames)
    else:
        x_expr = "x='(iw-iw/zoom)/2-(iw*0.04)*on/{f}'".format(f=frames)
    vf = (
        f"scale={VIDEO_W*2}:{VIDEO_H*2}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_W*2}:{VIDEO_H*2},"
        f"zoompan=z='min(zoom+{zi},1.15)':d={frames}:{x_expr}:"
        f"y='(ih-ih/zoom)/2':s={VIDEO_W}x{VIDEO_H}:fps={FPS},setsar=1,format=yuv420p"
    )
    _run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(img),
          "-t", f"{dur:.3f}", "-vf", vf,
          "-c:v", "libx264", "-preset", "medium", "-crf", "20",
          "-pix_fmt", "yuv420p", "-r", str(FPS), "-t", f"{dur:.3f}", str(out)])


def _build_srt(narration: str, total: float, srt_path: Path) -> bool:
    sents = [s for s in re.split(r"(?<=[。！？\n])", narration) if s.strip()]
    if not sents:
        return False
    weights = [len(s) for s in sents]
    tot_w = sum(weights) or 1
    t = 0.0
    lines = []
    for i, (s, w) in enumerate(zip(sents, weights), 1):
        seg = total * w / tot_w
        start, end = t, min(total, t + seg)
        t = end
        lines.append(f"{i}\n{_ts(start)} --> {_ts(end)}\n{s.strip()}\n")
    srt_path.write_text("\n".join(lines), encoding="utf-8")
    return True


def _ts(sec: float) -> str:
    h = int(sec // 3600); m = int((sec % 3600) // 60)
    s = int(sec % 60); ms = int((sec - int(sec)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def assemble(images: list[Path], audio_path: str | Path, out_path: str | Path,
             narration: str = "", subtitles: bool = True) -> Path:
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
        _ken_burns_segment(img, max(0.8, d), i, seg)
        segs.append(seg)
        print(f"  [assemble] segment {i+1}/{n}")

    # 2. concat silent video
    listfile = tmp / "list.txt"
    listfile.write_text("".join(f"file '{s}'\n" for s in segs))
    silent = tmp / "silent.mp4"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
          "-i", str(listfile), "-c", "copy", str(silent)])

    # 3. mux audio (+ optional burned subtitles)
    srt = tmp / "subs.srt"
    have_subs = subtitles and narration and _build_srt(narration, dur, srt)
    if have_subs:
        try:
            style = (f"FontName={_JP_FONT},FontSize=18,PrimaryColour=&H00FFFFFF,"
                     f"OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,"
                     f"MarginV=40,Alignment=2")
            vf = f"subtitles={srt.as_posix()}:force_style='{style}'"
            _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(audio_path),
                  "-vf", vf, "-map", "0:v", "-map", "1:a",
                  "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_path)])
            return out_path
        except subprocess.CalledProcessError:
            print("  [assemble] subtitle burn failed; muxing without subtitles")

    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(audio_path),
          "-map", "0:v", "-map", "1:a", "-c:v", "copy",
          "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_path)])
    return out_path
