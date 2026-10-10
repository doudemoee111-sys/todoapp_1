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

echo "[deps] verifying…"
ffmpeg -version | head -1
python3 -c "import openai, google.auth, googleapiclient, requests, PIL; print('[deps] python deps OK')"
