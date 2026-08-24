"""背景動画を生成する(AI画像+ゆっくりズーム、またはグラデーション)"""

import colorsys
from pathlib import Path

import numpy as np
from moviepy import VideoClip
from PIL import Image

import config

CYCLE_SECONDS = 20.0  # 色が一巡するのにかかる秒数
KEN_BURNS_ZOOM = 0.15  # 各シーン内でのズーム量(1.0 -> 1.15)


def _load_cover_image(path: Path, width: int, height: int) -> Image.Image:
    """画像を指定サイズを覆うようにリサイズする(cover fit)"""
    img = Image.open(path).convert("RGB")
    scale = max(width / img.width, height / img.height)
    new_size = (int(img.width * scale) + 1, int(img.height * scale) + 1)
    return img.resize(new_size, Image.LANCZOS)


def _ken_burns_frame(img: Image.Image, progress: float, width: int, height: int) -> np.ndarray:
    zoom = 1.0 + KEN_BURNS_ZOOM * progress
    crop_w = width / zoom
    crop_h = height / zoom
    x0 = (img.width - crop_w) / 2
    y0 = (img.height - crop_h) / 2
    frame = img.crop((x0, y0, x0 + crop_w, y0 + crop_h)).resize((width, height), Image.LANCZOS)
    return np.array(frame)


def make_image_background_clip(image_paths: list[Path], duration: float) -> VideoClip:
    """複数のシーン画像を等分割し、各シーンにゆっくりズームをかけて繋げる"""
    width, height = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
    n = len(image_paths)
    segment_duration = duration / n
    scenes = [_load_cover_image(p, width, height) for p in image_paths]

    def make_frame(t: float) -> np.ndarray:
        idx = min(int(t // segment_duration), n - 1)
        local_progress = (t - idx * segment_duration) / segment_duration
        return _ken_burns_frame(scenes[idx], local_progress, width, height)

    return VideoClip(make_frame, duration=duration).with_fps(config.VIDEO_FPS)


def _color_pair(t: float) -> tuple[np.ndarray, np.ndarray]:
    phase = (t % CYCLE_SECONDS) / CYCLE_SECONDS
    hue1 = phase
    hue2 = (phase + 0.35) % 1.0
    rgb1 = np.array(colorsys.hsv_to_rgb(hue1, 0.55, 0.55)) * 255
    rgb2 = np.array(colorsys.hsv_to_rgb(hue2, 0.55, 0.30)) * 255
    return rgb1, rgb2


def make_gradient_background_clip(duration: float) -> VideoClip:
    """AI画像生成に失敗した場合のフォールバック背景"""
    height = config.VIDEO_HEIGHT
    width = config.VIDEO_WIDTH
    ramp = np.linspace(0.0, 1.0, height, dtype=np.float32).reshape(height, 1, 1)

    def make_frame(t: float) -> np.ndarray:
        rgb1, rgb2 = _color_pair(t)
        gradient = rgb1 * (1 - ramp) + rgb2 * ramp  # (height, 1, 3)
        frame = np.broadcast_to(gradient, (height, width, 3)).astype(np.uint8)
        return frame

    return VideoClip(make_frame, duration=duration).with_fps(config.VIDEO_FPS)
