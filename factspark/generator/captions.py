"""台本の各行を音声の長さに合わせて配分し、テロップ(TextClip)を生成する"""

from moviepy import TextClip

import config

# TikTok/YouTube Shortsのアプリ UI(キャプション欄・ユーザー名・操作ボタン等)と
# 被らないよう、字幕を画面上下のセーフゾーンの内側に収める
SAFE_TOP_RATIO = 0.12
SAFE_BOTTOM_RATIO = 0.80


def _safe_y(clip_height: int) -> int:
    top = int(config.VIDEO_HEIGHT * SAFE_TOP_RATIO)
    bottom = int(config.VIDEO_HEIGHT * SAFE_BOTTOM_RATIO)
    band_height = bottom - top
    y = top + (band_height - clip_height) // 2
    if y + clip_height > bottom:
        y = bottom - clip_height
    return max(y, top)


def build_caption_clips(
    lines: list[str], total_duration: float, font_path: str | None = None
) -> list[TextClip]:
    font_path = font_path or config.FONT_PATH
    total_chars = sum(len(line) for line in lines) or 1
    clips = []
    t = 0.0
    for line in lines:
        share = len(line) / total_chars
        line_duration = max(total_duration * share, 0.3)
        clip = (
            TextClip(
                font=font_path,
                text=line,
                font_size=config.FONT_SIZE,
                color=config.CAPTION_COLOR,
                stroke_color=config.CAPTION_STROKE_COLOR,
                stroke_width=config.CAPTION_STROKE_WIDTH,
                method="caption",
                size=(int(config.VIDEO_WIDTH * 0.85), None),
                text_align="center",
                margin=(config.CAPTION_STROKE_WIDTH * 2, config.CAPTION_STROKE_WIDTH * 4),
            )
            .with_start(t)
            .with_duration(line_duration)
        )
        clip = clip.with_position(("center", _safe_y(clip.h)))
        clips.append(clip)
        t += line_duration
    return clips
