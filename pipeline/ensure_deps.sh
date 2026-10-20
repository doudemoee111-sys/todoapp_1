#!/usr/bin/env bash
# Make a fresh container runnable, cheaply and idempotently.
#
# Why this exists: the routine prompts used to guard setup.sh behind
# `command -v ffmpeg` to avoid re-running apt on every fire. When an
# environment ships ffmpeg pre-installed, that guard skipped setup.sh
# entirely — and with it the pip install — so run.py died on
# `ModuleNotFoundError: google`. The two parts have different costs and
# must be decided separately: apt is slow and only needed once, pip is
# fast when the wheels are already present and must never be skipped.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

if command -v ffmpeg >/dev/null 2>&1; then
  echo "[deps] ffmpeg present — skipping apt"
else
  echo "[deps] installing ffmpeg + Noto CJK fonts…"
  sudo mkdir -p /etc/apt/disabled.bak || true
  for f in /etc/apt/sources.list.d/*deadsnakes* /etc/apt/sources.list.d/*ondrej*; do
    [ -e "$f" ] && sudo mv "$f" /etc/apt/disabled.bak/ || true
  done
  sudo apt-get update -qq
  sudo apt-get install -y -qq ffmpeg fonts-noto-cjk
fi

echo "[deps] installing Python deps (always — cheap when cached)…"
python3 -m pip install -q --user -r "$HERE/requirements.txt"

# Pillow は apt の python3-pil と pip の Pillow が混ざると、PIL/__init__.py は
# 読めるのに _imaging(C拡張) が見つからず `from PIL import Image` だけが落ちる。
# 2026/10/20 の環境音がこれで死んだうえ、当時の検証は `import PIL` だけだったので
# 壊れたまま「deps OK」と通していた。だから実際に使う名前で検証し、壊れていたら直す。
if ! python3 -c "from PIL import Image, ImageDraw, ImageFont" >/dev/null 2>&1; then
  echo "[deps] Pillow が壊れています（apt版とpip版の混在）。入れ直します…"
  sudo apt-get remove -y -qq python3-pil python3-pil.imagetk 2>/dev/null || true
  python3 -m pip install -q --user --force-reinstall --no-cache-dir pillow
fi

echo "[deps] verifying…"
ffmpeg -version | head -1
python3 -c "
import openai, google.auth, googleapiclient, requests
from PIL import Image, ImageDraw, ImageFont
print('[deps] python deps OK')"
