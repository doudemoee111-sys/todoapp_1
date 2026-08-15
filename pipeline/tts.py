"""Text-to-speech with a pluggable provider.

Primary provider: Google Cloud Text-to-Speech (chosen by the user).
  - Auth mode A (simplest): env GOOGLE_TTS_API_KEY  -> REST v1 text:synthesize?key=...
  - Auth mode B: env GOOGLE_APPLICATION_CREDENTIALS -> service-account (google-cloud-texttospeech)
Fallback provider (smoke tests only): OpenAI TTS via env OPENAI_API_KEY, set TTS_PROVIDER=openai.

Google's request limit is 5000 bytes, so text is chunked on sentence boundaries
and the resulting audio segments are concatenated with ffmpeg.
"""
from __future__ import annotations
import base64
import os
import re
import subprocess
import tempfile
from pathlib import Path

import requests

from config import (TTS_PROVIDER, GOOGLE_TTS_VOICE, GOOGLE_TTS_SPEAKING_RATE,
                    OPENAI_TTS_VOICE)

_MAX_BYTES = 4500  # stay safely under Google's 5000-byte limit


def _split_sentences(text: str) -> list[str]:
    # Split on Japanese/period sentence enders, keeping chunks under the byte cap.
    parts = re.split(r"(?<=[。！？\n])", text)
    chunks, cur = [], ""
    for p in parts:
        if not p:
            continue
        if len((cur + p).encode("utf-8")) > _MAX_BYTES and cur:
            chunks.append(cur)
            cur = p
        else:
            cur += p
    if cur.strip():
        chunks.append(cur)
    return chunks or [text]


# ---- Google Cloud TTS -------------------------------------------------------
def _google_synth_chunk_apikey(text: str, api_key: str) -> bytes:
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"
    body = {
        "input": {"text": text},
        "voice": {"languageCode": "ja-JP", "name": GOOGLE_TTS_VOICE},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": GOOGLE_TTS_SPEAKING_RATE},
    }
    r = requests.post(url, json=body, timeout=60)
    r.raise_for_status()
    return base64.b64decode(r.json()["audioContent"])


def _google_synth_chunk_sa(text: str, client) -> bytes:
    from google.cloud import texttospeech as tts
    resp = client.synthesize_speech(
        input=tts.SynthesisInput(text=text),
        voice=tts.VoiceSelectionParams(language_code="ja-JP", name=GOOGLE_TTS_VOICE),
        audio_config=tts.AudioConfig(audio_encoding=tts.AudioEncoding.MP3,
                                     speaking_rate=GOOGLE_TTS_SPEAKING_RATE),
    )
    return resp.audio_content


def _synthesize_google(text: str, out_path: Path) -> Path:
    api_key = os.environ.get("GOOGLE_TTS_API_KEY")
    sa_client = None
    if not api_key:
        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            from google.cloud import texttospeech as tts
            sa_client = tts.TextToSpeechClient()
        else:
            raise RuntimeError(
                "Google Cloud TTS の認証情報がありません。GOOGLE_TTS_API_KEY か "
                "GOOGLE_APPLICATION_CREDENTIALS を設定してください（設定手順は README を参照）。"
            )
    chunks = _split_sentences(text)
    seg_files = []
    tmpdir = Path(tempfile.mkdtemp(prefix="tts_"))
    for i, ch in enumerate(chunks):
        audio = (_google_synth_chunk_apikey(ch, api_key) if api_key
                 else _google_synth_chunk_sa(ch, sa_client))
        seg = tmpdir / f"seg_{i:03d}.mp3"
        seg.write_bytes(audio)
        seg_files.append(seg)
    _concat_audio(seg_files, out_path)
    return out_path


# ---- OpenAI TTS (fallback) --------------------------------------------------
def _synthesize_openai(text: str, out_path: Path) -> Path:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    chunks = _split_sentences(text)
    tmpdir = Path(tempfile.mkdtemp(prefix="tts_"))
    seg_files = []
    for i, ch in enumerate(chunks):
        seg = tmpdir / f"seg_{i:03d}.mp3"
        with client.audio.speech.with_streaming_response.create(
            model="tts-1", voice=OPENAI_TTS_VOICE, input=ch,
        ) as resp:
            resp.stream_to_file(seg)
        seg_files.append(seg)
    _concat_audio(seg_files, out_path)
    return out_path


# ---- helpers ----------------------------------------------------------------
def _concat_audio(seg_files: list[Path], out_path: Path) -> None:
    if len(seg_files) == 1:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(seg_files[0]),
                        "-c", "copy", str(out_path)], check=True)
        return
    listfile = out_path.with_suffix(".txt")
    listfile.write_text("".join(f"file '{s}'\n" for s in seg_files))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listfile), "-c", "copy", str(out_path)], check=True)
    listfile.unlink(missing_ok=True)


def synthesize(text: str, out_path: str | Path) -> Path:
    out_path = Path(out_path)
    if TTS_PROVIDER == "openai":
        return _synthesize_openai(text, out_path)
    return _synthesize_google(text, out_path)


def audio_duration(path: str | Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


if __name__ == "__main__":
    p = synthesize("これはテスト音声です。パイプラインの動作確認をしています。", "output/_tts_test.mp3")
    print("wrote", p, "duration", audio_duration(p), "s")
