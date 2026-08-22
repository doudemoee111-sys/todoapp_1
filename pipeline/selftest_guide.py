#!/usr/bin/env python3
"""Render the L3 (入眠ガイド) video path end to end without touching any API.

L3 is the only mode whose renderer had never been run start to finish, and it
is the one that runs unattended on Thursdays. This substitutes a tone for the
narration and flat images for the generated ones, so the parts that can
actually break — the concat, the subtitle burn, the ambient tail, the audio
mux — are exercised for free, in about a minute, before a scheduled run pays
for a script and a voice only to fail at the assembly step.

    python3 selftest_guide.py            # 5 minute stand-in
    python3 selftest_guide.py --seconds 600

Checks, and what a failure means:
  duration   the tail length or the crossfade arithmetic is wrong
  48 kHz     loudnorm's 192 kHz output is reaching the encoder again
  subtitles  the burn landed on the tail, or the JP font is missing
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _probe(path: Path) -> str:
    """ffmpeg -i, not ffprobe: ffprobe is not installed everywhere this runs."""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path)],
                         capture_output=True, text=True)
    return out.stderr


def _duration(info: str) -> float:
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", info)
    if not m:
        raise AssertionError("動画の長さを取得できませんでした")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def _frame(video: Path, at: float, dest: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", f"{at}", "-i", str(video), "-frames:v", "1", str(dest)],
                   check=True)
    return dest


def _brightest(path: Path) -> int:
    from PIL import Image
    return max(Image.open(path).convert("L").getdata())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=300, help="stand-in ambient tail")
    ap.add_argument("--keep", action="store_true", help="leave the render on disk")
    args = ap.parse_args()

    from PIL import Image, ImageDraw
    from ambient import (variation, synthesize_masking_noise,
                         combine_narration_and_ambient, assemble_guide)

    work = Path(tempfile.mkdtemp(prefix="guide_selftest_"))
    intro_s, crossfade = 24.0, 8
    print(f"== L3 セルフテスト（解説 {intro_s:.0f}秒 + アンビエント {args.seconds}秒）==\n{work}")

    images = []
    for i in range(4):
        im = Image.new("RGB", (1920, 1080), (8 + i * 4, 12 + i * 5, 26 + i * 8))
        ImageDraw.Draw(im).ellipse([300 + i * 120, 160, 700 + i * 120, 560],
                                   fill=(40 + i * 9, 60, 96))
        f = work / f"img_{i}.png"
        im.save(f)
        images.append(f)

    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"sine=frequency=220:duration={intro_s:.0f}",
                    "-c:a", "libmp3lame", str(work / "narration.mp3")], check=True)

    t0 = time.time()
    bed = synthesize_masking_noise(work / "bed.m4a", args.seconds,
                                   variation("selftest"), fade_in=2)
    combined = combine_narration_and_ambient(work / "narration.mp3", bed,
                                             work / "audio.m4a", crossfade=crossfade)
    total_s = intro_s + args.seconds - crossfade
    subs = [("隣のいびきで、夜中に目が覚めてしまう。", 0.0, 6.0),
            ("その音は、体からの合図かもしれません。", 6.0, 13.0),
            ("今夜は、その仕組みからお話しします。", 13.0, 22.0)]
    video = assemble_guide(images, combined, intro_s, total_s,
                           work / "video.mp4", sub_segments=subs)
    elapsed = time.time() - t0

    info = _probe(video)
    failures: list[str] = []

    got = _duration(info)
    if abs(got - total_s) > 1.0:
        failures.append(f"長さが {got:.1f}s（期待 {total_s:.1f}s）")

    if "48000 Hz" not in info:
        failures.append("音声が 48kHz ではありません（loudnorm の再サンプリング漏れ）")
    if "Audio: aac" not in info:
        failures.append("音声ストリームが AAC ではありません")

    # Burned white subtitles are far brighter than this deliberately dark art,
    # so one bright pixel in the intro and none in the tail is the whole test.
    intro_px = _brightest(_frame(video, 4, work / "f_intro.png"))
    tail_px = _brightest(_frame(video, intro_s + min(60, args.seconds / 2),
                                work / "f_tail.png"))
    if intro_px < 200:
        failures.append(f"解説パートに字幕が見当たりません（最大輝度 {intro_px}）")
    if tail_px > 200:
        failures.append(f"アンビエント部に字幕が焼き込まれています（最大輝度 {tail_px}）")

    print(f"\n所要 {elapsed:.0f}s / {video.stat().st_size/1e6:.0f} MB / {got:.1f}s")
    print(f"輝度: 解説パート {intro_px}（字幕あり） / アンビエント部 {tail_px}（字幕なし）")

    if failures:
        print("\n❌ 失敗:")
        for f in failures:
            print(f"  - {f}")
        print(f"\n生成物はそのまま残しています: {work}")
        return 1

    print("\n✅ L3 のレンダリング経路は正常です。")
    if not args.keep:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"生成物: {work}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
