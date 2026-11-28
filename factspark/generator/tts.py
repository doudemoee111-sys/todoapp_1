"""OpenAI TTS APIでナレーション音声を生成する"""

import sys
from pathlib import Path

from http_retry import request_with_retry

import config

OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"


def synthesize(text: str, output_path: Path) -> Path:
    api_key = config.load_openai_key()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.OPENAI_TTS_MODEL,
        "voice": config.OPENAI_TTS_VOICE,
        "input": text,
        "instructions": config.TTS_INSTRUCTIONS,
        "response_format": "mp3",
    }

    resp = request_with_retry("POST", OPENAI_TTS_URL, headers=headers, json=payload, timeout=120)
    if resp.status_code != 200:
        sys.exit(f"エラー: OpenAI TTS APIエラー ({resp.status_code}): {resp.text[:300]}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(resp.content)
    return output_path
