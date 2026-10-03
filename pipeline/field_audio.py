"""実録音 — a bed built from a recording somebody actually made (D-2).

The synthesised textures in ambient.py solve a real problem well: arbitrary
duration, no licence, no Content ID claim, and a claim on a two-hour video
takes 100% of that video's revenue. They will stay for as long as that trade
holds.

What they cannot solve is the other problem. A procedurally generated two-hour
bed under a synthesised voice is, by construction, interchangeable with the
next one — and "interchangeable with the next one" is the definition YouTube's
inauthentic-content policy actually uses. This channel has already had one AI
judgment against it. Making *more* procedural hours is the one direction that
can only make that worse.

A recording of actual rain on an actual window is original by definition. It is
also, usefully, the cheapest authenticity in the catalogue: one twenty-minute
recording becomes a two-hour bed, and the recording itself is a phone in a
window for twenty minutes.

Three things this module is careful about:

  * **Seamless looping.** A hard cut every three minutes is the single most
    recognisable flaw in a long ambient video, and it is the thing the comments
    find first. The loop unit is built by crossfading the recording's tail into
    its own head, so the join is the same join every time and there is no seam
    to find.
  * **Provenance.** Every recording carries when, where and on what, and that
    goes in the description. A recording whose origin is not stated is worth no
    more than a synthesised one — the point is that it is checkable.
  * **What else got recorded.** A phone left in a window also records a radio
    two rooms away. That is somebody else's copyright on a two-hour video, so
    the registry asks the question explicitly and the guide says to listen back.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import date
from pathlib import Path

import config

REG_FILE = config.ASSETS_DIR / "field_recordings.json"
AUDIO_DIR = config.ASSETS_DIR / "field"

REQUIRED = ("id", "date", "subject", "where", "device", "source")

# Shorter than this and the loop is audible however well it is crossfaded:
# the ear finds a repeating pattern in about a minute.
MIN_SOURCE_SECONDS = 120
CROSSFADE_MAX = 6.0


class FieldAudioError(RuntimeError):
    """The registry exists but would publish something it should not."""


def _ffmpeg() -> str:
    from ambient import _ffmpeg as f
    return f()


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def load() -> dict:
    if not REG_FILE.exists():
        return {"records": []}
    try:
        return json.loads(REG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise FieldAudioError(f"assets/field_recordings.json が壊れています: {e}") from e


def source_path(rec: dict) -> Path:
    """Where the audio lives. Relative entries resolve under assets/field/."""
    p = Path(rec.get("source", ""))
    return p if p.is_absolute() else (AUDIO_DIR / p)


def check(data: dict | None = None) -> None:
    """Validate the registry. Called from preflight."""
    data = data or load()
    problems: list[str] = []
    seen: set[str] = set()
    for i, r in enumerate(data.get("records") or []):
        name = r.get("id") or f"（{i}番目・idなし）"
        for key in REQUIRED:
            if not r.get(key):
                problems.append(f"{name}: 「{key}」が空です")
        if r.get("id") in seen:
            problems.append(f"{name}: id が重複しています")
        seen.add(r.get("id"))
        if r.get("ready") and r.get("cleared_of_other_audio") is not True:
            problems.append(
                f"{name}: cleared_of_other_audio が true ではありません。"
                "通して聴いて、テレビ・ラジオ・音楽・人の声が入っていないことを"
                "確認してから true にしてください（2時間動画の著作権申立ては全収益を失います）")
        if r.get("ready") and not source_path(r).exists():
            problems.append(f"{name}: 音源が見つかりません → {source_path(r)}")
    if problems:
        raise FieldAudioError(
            "assets/field_recordings.json に問題があります:\n  - " + "\n  - ".join(problems))


def pending(data: dict | None = None) -> list[dict]:
    """Recordings that are registered, cleared, present on disk, and unused."""
    out = []
    for r in (data or load()).get("records") or []:
        if not r.get("ready") or r.get("used_in"):
            continue
        if r.get("cleared_of_other_audio") is not True:
            continue
        if any(not r.get(k) for k in REQUIRED) or not source_path(r).exists():
            continue
        out.append(r)
    out.sort(key=lambda r: str(r.get("date", "")))
    return out


def take(data: dict | None = None) -> dict | None:
    p = pending(data)
    return p[0] if p else None


def mark_used(rec_id: str, video_id: str) -> None:
    data = load()
    for r in data.get("records") or []:
        if r.get("id") == rec_id:
            r.setdefault("used_in", []).append(
                {"video_id": video_id, "date": date.today().isoformat()})
            break
    else:
        print(f"  [field] 使用記録を書けません（id {rec_id} が見つかりません）")
        return
    REG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")


def description_block(rec: dict | None) -> str:
    """Provenance for the description. This is the whole point of D-2."""
    if not rec:
        return ""
    lines = ["▼ この動画の音について",
             f"録音日: {rec['date']}",
             f"録音したもの: {rec['subject']}",
             f"場所: {rec['where']}",
             f"機材: {rec['device']}"]
    lines.append(f"編集: {rec.get('processing') or '音量の調整と、頭と終わりのフェードのみ'}")
    lines.append("合成音ではなく、実際に録った音を使っています。"
                 "長さを出すために、継ぎ目が分からないようつないで繰り返しています。")
    if rec.get("notes"):
        lines.append(rec["notes"])
    return "\n".join(lines)


# ---- duration ---------------------------------------------------------------
_TIME = re.compile(r"time=(\d+):(\d\d):(\d\d\.\d+)")


def duration(path: Path) -> float:
    """Length in seconds. ffprobe when present, otherwise a decode pass.

    The fallback exists because `ffmpeg` can come from imageio_ffmpeg, which
    ships the encoder and not ffprobe. Decoding a few minutes of audio to null
    costs well under a second and is better than a missing-binary failure
    twenty minutes into a render.
    """
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            check=True, capture_output=True, text=True).stdout.strip()
        return float(out)
    except (OSError, subprocess.CalledProcessError, ValueError):
        pass
    proc = subprocess.run([_ffmpeg(), "-hide_banner", "-i", str(path), "-f", "null", "-"],
                          capture_output=True, text=True)
    times = _TIME.findall(proc.stderr)
    if not times:
        raise FieldAudioError(f"音源の長さを測れませんでした: {path}")
    h, m, s = times[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


# ---- the bed ----------------------------------------------------------------
def _loop_unit(src: Path, dest: Path, length: float, fade: float) -> float:
    """Build a unit that joins to itself without a seam. Returns its length.

    The recording's last `fade` seconds are crossfaded into its first `fade`
    seconds, and that joint is appended to the untouched middle. Playing the
    result end-to-end therefore always passes through the same crossfade, so
    there is no discontinuity anywhere — the repeat is still a repeat, but it
    has no edge for the ear to lock onto.
    """
    unit_len = length - fade
    fc = (
        f"[0:a]atrim=0:{fade},asetpts=PTS-STARTPTS,"
        "aresample=48000,aformat=channel_layouts=stereo[head];"
        f"[0:a]atrim={fade}:{length - fade},asetpts=PTS-STARTPTS,"
        "aresample=48000,aformat=channel_layouts=stereo[mid];"
        f"[0:a]atrim={length - fade}:{length},asetpts=PTS-STARTPTS,"
        "aresample=48000,aformat=channel_layouts=stereo[tail];"
        f"[tail][head]acrossfade=d={fade}:c1=tri:c2=tri[joint];"
        "[mid][joint]concat=n=2:v=0:a=1[u]"
    )
    _run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
          "-filter_complex", fc, "-map", "[u]", "-ac", "2", "-ar", "48000",
          "-c:a", "pcm_s16le", str(dest)])
    return unit_len


def build_bed(rec: dict, out_path: str | Path, seconds: int,
              fade_in: int = 20, fade_out: int = 30) -> Path:
    """`seconds` of bed built from this recording, normalised and faded.

    The chain mirrors the synthesised path deliberately — the same highpass to
    drop handling rumble and traffic infrasound, the same -23 LUFS target, the
    same `aresample` after loudnorm (loudnorm works internally at 192 kHz and
    without this the AAC encoder lands on 96 kHz) — so an L3 built either way
    plays back at the same level. A listener who found the channel through a
    synthesised video should not be woken by the next one.
    """
    import tempfile
    from config import AMBIENT_AUDIO_BITRATE, AMBIENT_TARGET_LUFS

    out_path = Path(out_path)
    src = source_path(rec)
    length = duration(src)
    if length < MIN_SOURCE_SECONDS:
        raise FieldAudioError(
            f"{rec['id']}: 音源が {length:.0f} 秒しかありません。"
            f"{MIN_SOURCE_SECONDS} 秒以上の録音にしてください"
            "（短いと、継ぎ目を消しても繰り返しが聞こえます）")

    tmp = Path(tempfile.mkdtemp(prefix="field_"))
    fade = min(CROSSFADE_MAX, length / 4)
    unit = tmp / "unit.wav"
    unit_len = _loop_unit(src, unit, length, fade)
    loops = int(seconds // unit_len) + 1
    print(f"  [field] 録音 {length:.0f}秒 → 継ぎ目なしの単位 {unit_len:.0f}秒 × {loops}回 "
          f"= {seconds/3600:.2f}h（{rec['subject']}）")

    fade_out_start = max(0, seconds - fade_out)
    fc = (f"[0:a]highpass=f=40,"
          f"loudnorm=I={AMBIENT_TARGET_LUFS}:TP=-2:LRA=11,"
          f"aresample=48000,"
          f"afade=t=in:st=0:d={fade_in},"
          f"afade=t=out:st={fade_out_start}:d={fade_out}[a]")
    _run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
          "-stream_loop", str(loops), "-i", str(unit), "-t", str(seconds),
          "-filter_complex", fc, "-map", "[a]", "-ac", "2",
          "-c:a", "aac", "-b:a", AMBIENT_AUDIO_BITRATE, str(out_path)])
    return out_path


def stock_warning() -> str:
    try:
        n = len(pending())
    except FieldAudioError as e:
        return str(e)
    if n == 0:
        return ("実録音の在庫が 0 件です。長尺回は合成音で作ります。"
                "録り方は pipeline/assets/field_recording_guide.md にあります。")
    return ""


if __name__ == "__main__":
    check()
    for r in pending():
        print(f"  - [{r['date']}] {r['id']}: {r['subject']} "
              f"（{duration(source_path(r)):.0f}秒）")
    print(f"使える実録音: {len(pending())}件")
    w = stock_warning()
    if w:
        print(f"[警告] {w}")
