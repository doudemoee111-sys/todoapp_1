"""マスコット画像とテキストを合成し、YouTubeバナー(セーフゾーン対応)を作る"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BRANDING_DIR = Path(__file__).parent / "branding"
WIDTH, HEIGHT = 2560, 1440
# YouTubeバナーの安全表示領域(全デバイスで確実に見える中央部分)
SAFE_W, SAFE_H = 1546, 423
SAFE_X0 = (WIDTH - SAFE_W) // 2
SAFE_Y0 = (HEIGHT - SAFE_H) // 2

TOP_COLOR = (31, 36, 52)
BOTTOM_COLOR = (55, 50, 80)

TITLE = "FactSpark"
SUBTITLE = "Daily Trivia Shorts  ✦  毎日の雑学ショート"


def make_gradient() -> Image.Image:
    ramp = np.linspace(0, 1, HEIGHT).reshape(HEIGHT, 1, 1)
    top = np.array(TOP_COLOR)
    bottom = np.array(BOTTOM_COLOR)
    grad = top * (1 - ramp) + bottom * ramp
    grad = np.broadcast_to(grad, (HEIGHT, WIDTH, 3)).astype(np.uint8)
    return Image.fromarray(grad, "RGB")


def main():
    canvas = make_gradient().convert("RGBA")

    mascot = Image.open(BRANDING_DIR / "profile_raw.png").convert("RGBA")
    mascot_size = SAFE_H - 20
    mascot = mascot.resize((mascot_size, mascot_size), Image.LANCZOS)
    mascot_x = SAFE_X0
    mascot_y = SAFE_Y0 + (SAFE_H - mascot_size) // 2
    canvas.paste(mascot, (mascot_x, mascot_y), mascot)

    draw = ImageDraw.Draw(canvas)
    text_x = mascot_x + mascot_size + 40
    title_font = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 110)
    subtitle_font = ImageFont.truetype(r"C:\Windows\Fonts\meiryo.ttc", 46)

    title_y = SAFE_Y0 + 90
    draw.text((text_x, title_y), TITLE, font=title_font, fill="white")

    subtitle_y = title_y + 130
    draw.text((text_x, subtitle_y), SUBTITLE, font=subtitle_font, fill=(230, 230, 235))

    canvas = canvas.convert("RGB")
    out_path = BRANDING_DIR / "banner_final.png"
    canvas.save(out_path)
    print(f"保存しました: {out_path} size={canvas.size}")

    # デバッグ用: セーフゾーンを可視化した確認画像も出力
    debug = canvas.copy()
    ddraw = ImageDraw.Draw(debug)
    ddraw.rectangle(
        [SAFE_X0, SAFE_Y0, SAFE_X0 + SAFE_W, SAFE_Y0 + SAFE_H], outline="red", width=6
    )
    debug.save(BRANDING_DIR / "banner_final_safezone_debug.png")


if __name__ == "__main__":
    main()
