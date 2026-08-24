"""背景・字幕・音声(・BGM)を合成して1本のmp4に書き出す"""

import random
from pathlib import Path

from moviepy import AudioFileClip, CompositeAudioClip, CompositeVideoClip
from moviepy.audio.fx import AudioLoop, MultiplyVolume

import config
from background import make_gradient_background_clip, make_image_background_clip
from captions import build_caption_clips


def _pick_bgm() -> Path | None:
    if not config.BGM_DIR.exists():
        return None
    candidates = list(config.BGM_DIR.glob("*.mp3")) + list(config.BGM_DIR.glob("*.wav"))
    return random.choice(candidates) if candidates else None


def assemble_video(
    lines: list[str],
    narration_audio_path: Path,
    output_path: Path,
    image_paths: list[Path] | None = None,
    font_path: str | None = None,
) -> Path:
    narration = AudioFileClip(str(narration_audio_path))
    duration = narration.duration

    if image_paths:
        background = make_image_background_clip(image_paths, duration)
    else:
        background = make_gradient_background_clip(duration)
    caption_clips = build_caption_clips(lines, duration, font_path=font_path)

    video = CompositeVideoClip([background, *caption_clips], size=(config.VIDEO_WIDTH, config.VIDEO_HEIGHT))
    video = video.with_duration(duration)

    bgm_path = _pick_bgm()
    if bgm_path:
        bgm = (
            AudioFileClip(str(bgm_path))
            .with_effects([AudioLoop(duration=duration), MultiplyVolume(config.BGM_VOLUME)])
        )
        final_audio = CompositeAudioClip([narration, bgm])
    else:
        final_audio = narration

    video = video.with_audio(final_audio)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    video.write_videofile(
        str(output_path),
        fps=config.VIDEO_FPS,
        codec="libx264",
        audio_codec="aac",
        logger=None,
    )
    return output_path
