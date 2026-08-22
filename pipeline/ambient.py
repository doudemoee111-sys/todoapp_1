"""Long-form ambient renderer for the sleep channel (L2 / L3).

The existing `assemble.py` builds a video whose length follows the narration:
one Ken-Burns segment per image, concatenated, then the voice track muxed on
top. That is exactly right for an 8-15 minute explainer and completely wrong
for a 3-8 hour sleep track — rendering hours of `zoompan` is not viable, and
there is no narration to derive the length from in the first place.

So this module renders the other way round: the audio decides the length, and
the picture is a single still.

Two things make hour-long output cheap:

  * The noise is *synthesised*, not licensed and not looped from a sample.
    `anoisesrc` produces arbitrary duration directly, so there is no seam every
    N minutes, no licence fee, and no Content ID claim — which matters a lot
    when a single claim on an 8-hour video takes the whole video's revenue.
  * The video is encoded **once** as a short loop segment and then repeated
    with `-stream_loop … -c:v copy`. Encoding cost is therefore flat: a 3-hour
    and an 8-hour video both cost the same ~8 seconds of video encoding.

Masking, not "healing music". The point of L2 is to cover a partner's snoring,
which sits roughly in the 100-500 Hz band, so the noise is shaped to put its
energy there rather than to sound pleasant. Left and right channels are
generated from *different seeds*: decorrelated stereo masks far better than the
same mono signal sent to both ears.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path

from config import (VIDEO_W, VIDEO_H, FPS, AMBIENT_FPS, AMBIENT_CRF,
                    AMBIENT_LOOP_SECONDS, AMBIENT_AUDIO_BITRATE,
                    AMBIENT_TARGET_LUFS)


def _ffmpeg() -> str:
    """ffmpeg from PATH (setup.sh installs it); fall back to a bundled build."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("ffmpeg が見つかりません。`bash pipeline/setup.sh` を実行してください。") from e


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


# ---- per-video variation ----------------------------------------------------
# Every video must differ from its siblings, or the channel drifts towards the
# "inauthentic content" definition (templated mass production). Varying the
# seeds alone would be inaudible, so the band shaping moves too.
_COLORS = ["brown", "brown", "pink"]          # brown weighted: lowest, least hissy
_LOW_CENTRES = [160, 180, 200, 220]
_MID_CENTRES = [340, 380, 420, 460]
_CEILINGS = [1600, 1800, 2000]


@dataclass
class NoiseParams:
    seed_l: int
    seed_r: int
    color: str
    low_hz: int
    mid_hz: int
    ceiling_hz: int

    def filter_chain(self) -> str:
        return (f"highpass=f=40,lowpass=f={self.ceiling_hz},"
                f"equalizer=f={self.low_hz}:t=q:w=1.0:g=6,"
                f"equalizer=f={self.mid_hz}:t=q:w=1.2:g=4")


def variation(key: str) -> NoiseParams:
    """Derive stable-but-different noise parameters from a per-video key.

    Deterministic on purpose: the same video rebuilt after a failure produces
    the same sound, while the next video sounds different.
    """
    raw = str(key).encode("utf-8")
    h = abs(int.from_bytes(raw[-8:].ljust(8, b"\0"), "big"))
    return NoiseParams(
        seed_l=h % 900_000 + 1_000,
        seed_r=(h // 7) % 900_000 + 100_000,
        color=_COLORS[h % len(_COLORS)],
        low_hz=_LOW_CENTRES[(h // 3) % len(_LOW_CENTRES)],
        mid_hz=_MID_CENTRES[(h // 5) % len(_MID_CENTRES)],
        ceiling_hz=_CEILINGS[(h // 11) % len(_CEILINGS)],
    )


# ---- audio ------------------------------------------------------------------
def synthesize_masking_noise(out_path: str | Path, seconds: int, params: NoiseParams,
                             fade_in: int = 20, fade_out: int = 30) -> Path:
    """Generate `seconds` of decorrelated stereo masking noise.

    Note the `aresample=48000` after `loudnorm`: loudnorm resamples its output
    to 192 kHz internally, and without this the AAC encoder silently lands on
    96 kHz — a wasteful and needlessly exotic sample rate for a noise track.
    """
    out_path = Path(out_path)
    eq = params.filter_chain()
    fade_out_start = max(0, seconds - fade_out)
    fc = (f"[0:a]{eq}[l];[1:a]{eq}[r];"
          f"[l][r]amerge=inputs=2,"
          f"loudnorm=I={AMBIENT_TARGET_LUFS}:TP=-2:LRA=11,"
          f"aresample=48000,"
          f"afade=t=in:st=0:d={fade_in},"
          f"afade=t=out:st={fade_out_start}:d={fade_out}[a]")
    _run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
          "-f", "lavfi", "-i",
          f"anoisesrc=d={seconds}:c={params.color}:r=48000:a=0.9:seed={params.seed_l}",
          "-f", "lavfi", "-i",
          f"anoisesrc=d={seconds}:c={params.color}:r=48000:a=0.9:seed={params.seed_r}",
          "-filter_complex", fc, "-map", "[a]", "-ac", "2",
          "-c:a", "aac", "-b:a", AMBIENT_AUDIO_BITRATE, str(out_path)])
    return out_path




# ---- video ------------------------------------------------------------------
def _still_loop_segment(still: Path, out: Path, fps: int, seconds: int,
                        crf: int, preset: str = "veryfast",
                        width: int = VIDEO_W, height: int = VIDEO_H) -> None:
    """Encode one short segment of the still image, with a keyframe at its head.

    `-g` is set to the segment's frame count so every repeat of the segment
    begins on an IDR frame, which is what makes the stream-copy loop below
    produce a decodable file.
    """
    frames = max(1, fps * seconds)
    _run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
          "-loop", "1", "-i", str(still), "-t", str(seconds),
          "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                 f"crop={width}:{height},setsar=1,format=yuv420p",
          "-c:v", "libx264", "-tune", "stillimage", "-preset", preset,
          "-r", str(fps), "-g", str(frames), "-keyint_min", str(frames),
          "-pix_fmt", "yuv420p", "-crf", str(crf), "-an", str(out)])


def render_ambient(still: str | Path, audio: str | Path, out_path: str | Path,
                   total_seconds: float, fps: int = AMBIENT_FPS,
                   crf: int = AMBIENT_CRF) -> Path:
    """L2: one still + one long audio track. Cost is flat in the duration.

    `total_seconds` is passed in rather than probed: the caller generated the
    audio and already knows its length, so probing would only add an ffprobe
    dependency to a step that needs nothing but ffmpeg.
    """
    still, audio, out_path = Path(still), Path(audio), Path(out_path)
    total = float(total_seconds)
    tmp = Path(tempfile.mkdtemp(prefix="ambient_"))
    seg = tmp / "loop.mp4"
    _still_loop_segment(still, seg, fps, AMBIENT_LOOP_SECONDS, crf)
    # +1 so the video always outlasts the audio; -shortest trims it back.
    loops = int(total // AMBIENT_LOOP_SECONDS) + 1
    print(f"  [ambient] {total/3600:.2f}h ({AMBIENT_LOOP_SECONDS}s × {loops} loops, video re-encode: none)")
    _run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
          "-stream_loop", str(loops), "-i", str(seg), "-i", str(audio),
          "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "copy",
          "-shortest", "-movflags", "+faststart", str(out_path)])
    return out_path


def combine_narration_and_ambient(narration_audio: str | Path, ambient_audio: str | Path,
                                  out_path: str | Path, crossfade: int = 8) -> Path:
    """L3: the spoken part dissolves into the ambient bed rather than cutting.

    Both sides are resampled to 48 kHz stereo first — Google TTS returns 24 kHz
    mono MP3, and `acrossfade` will not join streams of differing formats.
    """
    out_path = Path(out_path)
    fc = ("[0:a]aresample=48000,aformat=channel_layouts=stereo[a0];"
          "[1:a]aresample=48000,aformat=channel_layouts=stereo[a1];"
          f"[a0][a1]acrossfade=d={crossfade}:c1=tri:c2=tri[a]")
    _run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
          "-i", str(narration_audio), "-i", str(ambient_audio),
          "-filter_complex", fc, "-map", "[a]", "-ac", "2",
          "-c:a", "aac", "-b:a", AMBIENT_AUDIO_BITRATE, str(out_path)])
    return out_path


def assemble_guide(images: list[Path], combined_audio: str | Path, intro_seconds: float,
                   total_seconds: float, out_path: str | Path, sub_segments=None,
                   width: int = VIDEO_W, height: int = VIDEO_H) -> Path:
    """L3: Ken-Burns over the spoken intro, then a still for the ambient tail.

    Every segment — the Ken-Burns ones and the still tail — is encoded with the
    same parameters at `config.FPS`, which is what lets the concat demuxer join
    them with a stream copy instead of re-encoding hours of video.
    """
    from assemble import _ken_burns_segment, _srt_from_segments, _JP_FONT

    combined_audio, out_path = Path(combined_audio), Path(out_path)
    tail = max(0.0, float(total_seconds) - intro_seconds)
    tmp = Path(tempfile.mkdtemp(prefix="guide_"))

    segs: list[Path] = []
    per = intro_seconds / max(1, len(images))
    for i, img in enumerate(images):
        seg = tmp / f"seg_{i:03d}.mp4"
        _ken_burns_segment(img, max(0.8, per), i, seg, width, height)
        segs.append(seg)
        print(f"  [guide] intro segment {i+1}/{len(images)}")

    def _concat(parts: list[Path], dest: Path) -> Path:
        listfile = dest.with_suffix(".txt")
        listfile.write_text("".join(f"file '{p}'\n" for p in parts))
        _run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
              "-f", "concat", "-safe", "0", "-i", str(listfile),
              "-c", "copy", str(dest)])
        return dest

    intro = _concat(segs, tmp / "intro.mp4") if len(segs) > 1 else segs[0]

    # Subtitles cover the spoken intro only; the ambient tail stays clean so the
    # screen is dark and still for someone falling asleep.
    #
    # They are burned HERE, onto the intro alone, before the hours-long tail is
    # attached. Doing it after the concat re-encodes the whole video and undoes
    # the stream-copy the rest of this function is built around: measured on this
    # pipeline, a 1080p30 subtitle burn runs at about 2.3x real time, so a 2-hour
    # guide costs ~50 minutes there against ~4 minutes for a 10-minute intro.
    srt = tmp / "subs.srt"
    if sub_segments and _srt_from_segments(sub_segments, intro_seconds, srt):
        style = (f"FontName={_JP_FONT},FontSize=26,PrimaryColour=&H00FFFFFF,"
                 f"OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=1,"
                 f"MarginV=60,Alignment=2")
        subbed = tmp / "intro_sub.mp4"
        try:
            _run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
                  "-i", str(intro),
                  "-vf", f"subtitles={srt.as_posix()}:force_style='{style}'",
                  "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                  "-pix_fmt", "yuv420p", "-an", str(subbed)])
            intro = subbed
        except subprocess.CalledProcessError:
            # The video is still worth publishing without subtitles.
            print("  [guide] 字幕焼き込みに失敗 → 字幕なしで続行します")

    parts = [intro]
    if tail > 1:
        loop = tmp / "tail_loop.mp4"
        # crf 20 / preset medium to match _ken_burns_segment's output exactly.
        _still_loop_segment(images[-1], loop, FPS, AMBIENT_LOOP_SECONDS,
                            crf=20, preset="medium", width=width, height=height)
        tail_file = tmp / "tail.mp4"
        loops = int(tail // AMBIENT_LOOP_SECONDS) + 1
        _run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
              "-stream_loop", str(loops), "-i", str(loop), "-t", f"{tail:.3f}",
              "-c", "copy", str(tail_file)])
        parts.append(tail_file)
        print(f"  [guide] ambient tail {tail/3600:.2f}h")

    silent = _concat(parts, tmp / "silent.mp4") if len(parts) > 1 else intro

    _run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
          "-i", str(silent), "-i", str(combined_audio),
          "-map", "0:v", "-map", "1:a", "-c:v", "copy",
          "-c:a", "aac", "-b:a", AMBIENT_AUDIO_BITRATE,
          "-shortest", "-movflags", "+faststart", str(out_path)])
    return out_path


# ---- metadata ---------------------------------------------------------------
_AMBIENT_PKG_USER = """YouTubeの「{hours}時間の睡眠用マスキング音源」動画のメタデータをJSONで作成してください。

この動画の中身: 隣で寝ている人のいびきを覆い隠すために音響設計された、低音域を厚くしたノイズ音源。
画面は暗いまま変化しません。ナレーションはありません。

想定視聴者: 40〜50代。自分がいびきをかくのではなく、**隣の人のいびきで夜中に起こされている側**。

要件:
- title: 100文字以内。冒頭に【】で用途を示し、「{hours}時間」「広告なし」等の実用情報を含める。
  検索語（いびき／かき消す／マスキング／睡眠用／ホワイトノイズ）を自然に含める。
  効果を断定しない（「消える」「解消」は使わない。「覆う」「かき消す」は可）。
- description: 日本語200〜400字。使い方（就寝前に再生、音量は小さめから）と、
  この音がどういう仕組みで話し声やいびきを覆うのかの中立的な説明を含める。
- tags: 日本語中心のキーワード10〜15個。
- image_prompt: 静止画1枚の英語プロンプト。とても暗い夜の情景。文字・ロゴ・人物を含めない。
  長時間見ても目が疲れず、暗い部屋で眩しくないこと。
JSON: {{"title":str,"description":str,"tags":[str,...],"image_prompt":str}}"""


def build_package(genre: dict, seconds: int, avoid_titles: list[str] | None = None) -> dict:
    """Title / description / tags / still-image prompt for an L2 video."""
    import json
    from llm_script import _chat, _avoid_block

    hours = round(seconds / 3600, 1)
    hours = int(hours) if float(hours).is_integer() else hours
    user = _AMBIENT_PKG_USER.format(hours=hours) + _avoid_block(avoid_titles)
    data = json.loads(_chat([{"role": "system", "content": "YouTube運用のプロ。出力はJSONのみ。"},
                             {"role": "user", "content": user}], json_mode=True))
    return {
        "topic": f"masking-noise-{hours}h",
        "title": (data.get("title") or f"【いびき対策】マスキングノイズ {hours}時間")[:100],
        "narration": "",
        "description": data.get("description", ""),
        "tags": (data.get("tags") or genre["tags"])[:15],
        "image_prompts": [data.get("image_prompt") or genre["image_style"]],
        "thumbnail_text": f"隣のいびきを\n覆う{hours}時間",
        "thumbnail_prompt": data.get("image_prompt") or genre["image_style"],
    }


def params_record(p: NoiseParams) -> dict:
    """Persisted into result.json so each video's sound is auditable later."""
    return asdict(p)
