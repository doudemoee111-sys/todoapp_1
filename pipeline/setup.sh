#!/usr/bin/env bash
# Provision a fresh (ephemeral) container to run the pipeline.
# Safe to run every session — installs system ffmpeg + Japanese fonts + Python deps.
set -euo pipefail

echo "[setup] disabling broken 3rd-party PPAs (if present)…"
sudo mkdir -p /etc/apt/disabled.bak || true
for f in /etc/apt/sources.list.d/*deadsnakes* /etc/apt/sources.list.d/*ondrej* ; do
  [ -e "$f" ] && sudo mv "$f" /etc/apt/disabled.bak/ || true
done

echo "[setup] installing ffmpeg + Noto CJK fonts…"
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg fonts-noto-cjk

echo "[setup] installing Python deps…"
python3 -m pip install -q --user -r "$(dirname "$0")/requirements.txt"

echo "[setup] verifying…"
ffmpeg -version | head -1
python3 -c "import openai, googleapiclient, requests, PIL; print('python deps OK')"
# Import the upload auth stack too — it pulls in cryptography, which fails late
# (after a ~16 min build) rather than here if the wrong build is installed.
python3 -c "from google.oauth2.credentials import Credentials; print('upload auth OK')"
echo "[setup] done."
