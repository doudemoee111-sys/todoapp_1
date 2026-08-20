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

from http_retry import request_with_retry

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
    r = request_with_retry("POST", url, json=body, timeout=60)
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


# Only characters that are almost always clause/word boundaries when a caption
# is broken right AFTER them. Ambiguous kana (が/な/か/で/よ/ね…) are excluded
# because they are commonly verb/adjective inflections, not particles.
_JP_BREAK_AFTER = "をにへともは、。！？」』】）"


def _is_kanji(ch: str) -> bool:
    return "一" <= ch <= "鿿"


def _jp_wrap_point(u: str, max_len: int) -> int:
    """Pick a natural break index at or before max_len so a hard-wrapped caption
    doesn't split a word. Prefer breaking just after a safe particle/punctuation;
    else just before a kanji (a common word start); else fall back to max_len."""
    lo = max(4, max_len - 5)
    for i in range(max_len, lo - 1, -1):        # after a safe particle/punctuation
        if u[i - 1] in _JP_BREAK_AFTER:
            return i
    for i in range(max_len, lo - 1, -1):        # before a kanji (word boundary)
        if _is_kanji(u[i]) and not _is_kanji(u[i - 1]):
            return i
    return max_len


def _split_subtitle_units(text: str, max_len: int = 40, min_len: int = 12) -> list[str]:
    """Split narration into readable subtitle-sized units.

    One sentence per unit; long sentences are split at Japanese commas so a
    subtitle is never a wall of text, and tiny fragments are merged into the
    previous unit so each line stays on screen long enough to read.
    """
    sents = [s.strip() for s in re.split(r"(?<=[。！？\n])", text) if s.strip()]
    units: list[str] = []
    for s in sents:
        if len(s) <= max_len:
            units.append(s)
            continue
        cur = ""
        for p in re.split(r"(?<=[、，])", s):
            if cur and len(cur + p) > max_len:
                units.append(cur)
                cur = p
            else:
                cur += p
        if cur.strip():
            units.append(cur)
    # Hard-wrap any unit that STILL exceeds max_len (a long clause with no comma
    # to break on). Without this, a burned caption can run off the frame edge
    # because libass does not reliably wrap gapless CJK text. Break at a natural
    # Japanese boundary (after a particle, or before a kanji) when possible so we
    # don't cut in the middle of a word.
    capped: list[str] = []
    for u in units:
        while len(u) > max_len:
            cut = _jp_wrap_point(u, max_len)
            capped.append(u[:cut])
            u = u[cut:]
        if u.strip():
            capped.append(u)
    # Merge a tiny leftover fragment into the previous unit, but NEVER past
    # max_len (so merging can't recreate an over-long, overflowing caption).
    # Punctuation-only tails (a lone 。) always glue back so they never flash as
    # their own caption.
    _punct = "。、！？」』】）"
    merged: list[str] = []
    for u in capped:
        only_punct = u != "" and all(c in _punct for c in u)
        if merged and only_punct and len(merged[-1]) + len(u) <= max_len + 2:
            merged[-1] += u
        elif merged and len(u) < min_len and len(merged[-1]) + len(u) <= max_len:
            merged[-1] += u
        else:
            merged.append(u)
    return merged or [text.strip()]


def _synth_unit_bytes(text: str, api_key, sa_client, use_openai: bool, seg: Path) -> None:
    if use_openai:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        with client.audio.speech.with_streaming_response.create(
                model="tts-1", voice=OPENAI_TTS_VOICE, input=text) as resp:
            resp.stream_to_file(seg)
    elif api_key:
        seg.write_bytes(_google_synth_chunk_apikey(text, api_key))
    elif sa_client is not None:
        seg.write_bytes(_google_synth_chunk_sa(text, sa_client))
    else:
        raise RuntimeError("Google Cloud TTS の認証情報がありません（GOOGLE_TTS_API_KEY 等）。")


def synthesize_timed(text: str, out_path: str | Path, max_sub_len: int = 40):
    """Synthesize the narration one subtitle-unit at a time and measure each
    unit's REAL audio duration, so burned subtitles stay perfectly in sync with
    the voice (no proportional guessing). Returns (audio_path, segments) where
    segments = [(text, start_sec, end_sec), ...].

    max_sub_len caps how long a single subtitle unit may be. Use a smaller value
    for vertical shorts so captions fit the narrow frame in 1-2 lines.
    """
    out_path = Path(out_path)
    use_openai = (TTS_PROVIDER == "openai")
    api_key = os.environ.get("GOOGLE_TTS_API_KEY")
    sa_client = None
    if not use_openai and not api_key and os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        from google.cloud import texttospeech as tts
        sa_client = tts.TextToSpeechClient()

    min_len = 6 if max_sub_len <= 20 else 12
    units = _split_subtitle_units(text, max_len=max_sub_len, min_len=min_len)
    tmpdir = Path(tempfile.mkdtemp(prefix="tts_timed_"))
    seg_files: list[Path] = []
    segments: list[tuple[str, float, float]] = []
    t = 0.0
    for i, u in enumerate(units):
        seg = tmpdir / f"seg_{i:04d}.mp3"
        _synth_unit_bytes(u, api_key, sa_client, use_openai, seg)
        d = audio_duration(seg)
        segments.append((u.strip(), t, t + d))
        t += d
        seg_files.append(seg)
    _concat_audio(seg_files, out_path)
    return out_path, segments


def audio_duration(path: str | Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


if __name__ == "__main__":
    p = synthesize("これはテスト音声です。パイプラインの動作確認をしています。", "output/_tts_test.mp3")
    print("wrote", p, "duration", audio_duration(p), "s")
