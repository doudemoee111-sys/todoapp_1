"""Check every credential this pipeline needs, and say exactly what is wrong.

    python3 doctor.py

Motivation: "are my environment variables right?" is not answerable by reading
them. A value can be present, well-formed, and still belong to the wrong
project or the wrong channel — which is precisely the failure that took a
production channel down. So this does not inspect the values; it *uses* them,
one cheap read-only call per service, and reports what actually happened.

Secrets are never printed. Each value is shown as a short fingerprint —
`sha256(value)[:8]` — which is safe to paste anywhere and lets two
environments be compared: the sleep channel and the existing channel MUST show
different fingerprints for the YouTube triple, and identical ones for
OPENAI_API_KEY / STABILITY_API_KEY.

Every call here is free or costs a single quota unit, so it is safe to run as
often as you like.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import unicodedata

OK, NG, WARN, SKIP = "OK", "NG", "WARN", "--"

# (env var, required, expected prefix/suffix, what it is for)
SPEC = [
    ("YOUTUBE_CLIENT_ID",     True,  ".apps.googleusercontent.com", "YouTube 投稿（OAuth）"),
    ("YOUTUBE_CLIENT_SECRET", True,  "GOCSPX-",                     "YouTube 投稿（OAuth）"),
    ("YOUTUBE_REFRESH_TOKEN", True,  "1//",                         "YouTube 投稿（OAuth）"),
    ("GOOGLE_TTS_API_KEY",    True,  "AIza",                        "ナレーション音声"),
    ("OPENAI_API_KEY",        True,  "sk-",                         "台本生成"),
    ("STABILITY_API_KEY",     True,  "sk-",                         "画像・サムネ生成"),
    ("EXPECTED_CHANNEL_ID",   False, "UC",                          "投稿先チャンネルの固定"),
    ("AMBIENT_SECONDS",       False, None,                          "L2 の尺"),
]


OPTIONAL_NOTE = {
    "EXPECTED_CHANNEL_ID": "未設定でも動きますが、取り違えを防ぐため強く推奨します",
    "AMBIENT_SECONDS": "未設定なら既定の 10800（3時間）が使われます",
}


def _w(s: str) -> int:
    """Display width: CJK characters occupy two columns in a terminal."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


SECRET_VARS = [name for name, *_ in SPEC if name.endswith(("_KEY", "_SECRET", "_TOKEN", "_ID"))]


def scrub(text: str) -> str:
    """Redact any configured secret that made it into a message.

    Library exceptions quote the request they failed on, and a request can
    carry a credential. Rather than audit every call site forever, everything
    printed passes through here — a value that is in the environment can never
    reach the terminal.
    """
    out = str(text)
    for name in SECRET_VARS:
        value = os.environ.get(name, "").strip()
        if len(value) < 8:
            continue
        out = out.replace(value, f"<{name}>")
        # Truncated echoes ("...key=AIzaFAK") need prefix matching too.
        for cut in range(len(value) - 1, 7, -1):
            if value[:cut] in out:
                out = out.replace(value[:cut], f"<{name}:一部>")
                break
    return out


class Report:
    """Prints each result as it happens, so it sits under its own heading."""

    MARK = {OK: "  OK  ", NG: " FAIL ", WARN: " WARN ", SKIP: " ---- "}
    COL = 26

    def __init__(self) -> None:
        self.failed = 0
        self.warned = 0

    def add(self, status: str, name: str, detail: str) -> None:
        if status == NG:
            self.failed += 1
        elif status == WARN:
            self.warned += 1
        pad = " " * max(1, self.COL - _w(name))
        print(f"  [{self.MARK[status]}] {name}{pad}{scrub(detail)}")

    def section(self, title: str) -> None:
        print(f"\n{title}")


# ---- 1. presence and shape --------------------------------------------------
def check_shape(rep: Report) -> dict:
    rep.section("== 1. 環境変数が設定されているか ==")
    found = {}
    for name, required, marker, purpose in SPEC:
        raw = os.environ.get(name, "")
        value = raw.strip()
        if not value:
            note = OPTIONAL_NOTE.get(name, "")
            rep.add(NG if required else WARN, name,
                    f"未設定 — {purpose}" + (f"。{note}" if note else ""))
            continue
        found[name] = value
        note = f"設定あり  fp={fingerprint(value)}  ({len(value)}文字)"
        if raw != value:
            rep.add(WARN, name, note + "  ⚠ 前後に空白か改行が入っています。貼り直してください")
            continue
        if marker and not (value.startswith(marker) or value.endswith(marker)):
            rep.add(WARN, name, note + f"  ⚠ 通常は「{marker}」を含む形式です。別の値を貼っていないか確認")
            continue
        rep.add(OK, name, note)

    if "AMBIENT_SECONDS" in found:
        try:
            sec = int(found["AMBIENT_SECONDS"])
            if not (60 <= sec <= 43200):
                rep.add(WARN, "AMBIENT_SECONDS", f"{sec}秒 — 想定外の値です（3時間なら 10800）")
        except ValueError:
            rep.add(NG, "AMBIENT_SECONDS", "数値ではありません")
    return found


# ---- 2. the services actually answer ----------------------------------------
def check_youtube(rep: Report) -> None:
    rep.section("== 2. YouTube：3点が揃っていて、どのチャンネルに投稿されるか ==")
    missing = [k for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
               if not os.environ.get(k, "").strip()]
    if missing:
        rep.add(SKIP, "YouTube 認証", f"{', '.join(missing)} が未設定のため未確認")
        return
    try:
        from youtube_upload import current_channel
        ch = current_channel()
    except Exception as e:  # noqa: BLE001
        msg = str(e).replace("\n", " ")[:200]
        hint = ""
        if "No module named" in msg:
            rep.add(NG, "YouTube 認証",
                    f"依存パッケージが未導入です（{msg}） → `bash pipeline/setup.sh` を実行")
            return
        if "unauthorized_client" in msg:
            hint = " → CLIENT_ID/SECRET と REFRESH_TOKEN が別クライアント由来です"
        elif "invalid_grant" in msg:
            hint = " → 同意画面が「テスト中」でトークンが失効した可能性（本番公開して再発行）"
        elif "invalid_client" in msg:
            hint = " → CLIENT_ID か SECRET が誤りです"
        rep.add(NG, "YouTube 認証", f"失敗: {msg}{hint}")
        return

    rep.add(OK, "YouTube 認証", f"成功 — 投稿先「{ch['title']}」")
    rep.add(OK, "  channelId", ch["id"])

    # Which genres are pinned to this channel in config.py? That answers the
    # question the environment cannot: *what is this environment for*.
    try:
        from config import GENRES
        bound = [k for k, g in GENRES.items() if g.get("channel_id") == ch["id"]]
        declared = [k for k, g in GENRES.items() if g.get("channel_id")]
    except Exception:  # noqa: BLE001
        bound, declared = [], []
    if bound:
        rep.add(OK, "  この環境の用途", f"config.py のジャンル {', '.join(bound)} 専用の環境です")
    elif declared:
        rep.add(WARN, "  この環境の用途",
                f"config.py で channel_id を宣言しているジャンル（{', '.join(declared)}）とは"
                f"別のチャンネルです。それらをこの環境で実行すると投稿前に中断します")

    expected = os.environ.get("EXPECTED_CHANNEL_ID", "").strip()
    if not expected:
        if bound:
            rep.add(OK, "  チャンネル固定",
                    "config.py 側で固定済み — 環境変数は無くても取り違えは止まります")
        else:
            rep.add(WARN, "  チャンネル固定",
                    "未設定 — 上の channelId を EXPECTED_CHANNEL_ID に入れると取り違えを防げます")
    elif expected == ch["id"]:
        rep.add(OK, "  チャンネル固定", "一致 — 別チャンネルの資格情報が入ったら投稿前に中断します")
    else:
        rep.add(NG, "  チャンネル固定",
                f"不一致！ 想定 {expected} / 実際 {ch['id']} — このまま投稿すると別チャンネルに出ます")


def _get(url: str, **kw):
    import requests
    return requests.get(url, timeout=20, **kw)


def check_google_tts(rep: Report) -> None:
    rep.section("== 3. Google TTS：キーが有効で、使う音声が存在するか ==")
    key = os.environ.get("GOOGLE_TTS_API_KEY", "").strip()
    if not key:
        rep.add(SKIP, "Google TTS", "GOOGLE_TTS_API_KEY 未設定のため未確認")
        return
    try:
        import config
        want = config.GOOGLE_TTS_VOICE
        # Key goes in a header, never the query string: a failed request
        # echoes its URL in the exception text, and that text gets printed.
        r = _get("https://texttospeech.googleapis.com/v1/voices",
                 params={"languageCode": "ja-JP"},
                 headers={"X-Goog-Api-Key": key})
    except Exception as e:  # noqa: BLE001
        rep.add(NG, "Google TTS", f"接続できません（ネットワーク許可を確認）: {str(e)[:140]}")
        return
    if r.status_code == 400 and "API key not valid" in r.text:
        rep.add(NG, "Google TTS", "キーが無効です — GOOGLE_TTS_API_KEY を貼り直してください")
        return
    if r.status_code == 403:
        rep.add(NG, "Google TTS",
                "403 — キーが Cloud Text-to-Speech API に対して無効です。"
                "APIの有効化、キーの API 制限、請求先アカウントの紐付けを確認")
        return
    if r.status_code != 200:
        rep.add(NG, "Google TTS", f"HTTP {r.status_code}: {r.text[:120]}")
        return
    names = {v.get("name") for v in r.json().get("voices", [])}
    if want in names:
        rep.add(OK, "Google TTS", f"有効 — 音声 {want} を確認（日本語 {len(names)} 種）")
    else:
        rep.add(NG, "Google TTS",
                f"キーは有効ですが、設定中の音声 {want} が一覧にありません。GOOGLE_TTS_VOICE を確認")


def check_openai(rep: Report) -> None:
    rep.section("== 4. OpenAI：キーが有効で、使うモデルが引けるか ==")
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        rep.add(SKIP, "OpenAI", "OPENAI_API_KEY 未設定のため未確認")
        return
    try:
        import config
        model = config.SCRIPT_MODEL
        r = _get(f"https://api.openai.com/v1/models/{model}",
                 headers={"Authorization": f"Bearer {key}"})
    except Exception as e:  # noqa: BLE001
        rep.add(NG, "OpenAI", f"接続できません（ネットワーク許可を確認）: {str(e)[:140]}")
        return
    if r.status_code == 401:
        rep.add(NG, "OpenAI", "401 — キーが無効か失効しています")
    elif r.status_code == 404:
        rep.add(NG, "OpenAI", f"キーは有効ですが、モデル {model} を使えません（SCRIPT_MODEL を確認）")
    elif r.status_code == 200:
        rep.add(OK, "OpenAI", f"有効 — モデル {model} を確認")
    else:
        rep.add(NG, "OpenAI", f"HTTP {r.status_code}: {r.text[:120]}")


def check_stability(rep: Report) -> None:
    rep.section("== 5. Stability：キーが有効で、残高があるか ==")
    key = os.environ.get("STABILITY_API_KEY", "").strip()
    if not key:
        rep.add(SKIP, "Stability", "STABILITY_API_KEY 未設定のため未確認")
        return
    try:
        r = _get("https://api.stability.ai/v1/user/balance",
                 headers={"Authorization": f"Bearer {key}"})
    except Exception as e:  # noqa: BLE001
        rep.add(NG, "Stability", f"接続できません（ネットワーク許可を確認）: {str(e)[:140]}")
        return
    if r.status_code == 401:
        rep.add(NG, "Stability", "401 — キーが無効です")
        return
    if r.status_code != 200:
        rep.add(NG, "Stability", f"HTTP {r.status_code}: {r.text[:120]}")
        return
    credits = r.json().get("credits", 0)
    # L1 one video = 30 images ~= 90 credits.
    videos = int(credits // 90)
    if credits < 90:
        rep.add(NG, "Stability", f"残高 {credits:.1f} クレジット — 1本ぶんに足りません（要チャージ）")
    elif videos < 5:
        rep.add(WARN, "Stability", f"残高 {credits:.1f} クレジット — 解説動画あと約 {videos} 本ぶん")
    else:
        rep.add(OK, "Stability", f"有効 — 残高 {credits:.1f} クレジット（解説動画 約 {videos} 本ぶん）")


# ---- 6. local tooling -------------------------------------------------------
def check_tools(rep: Report) -> None:
    rep.section("== 6. ローカルツール ==")
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        if path:
            rep.add(OK, tool, "PATH にあります")
        else:
            rep.add(NG, tool, "見つかりません → `bash pipeline/setup.sh` を実行")
    try:
        out = subprocess.run(["fc-list", ":lang=ja"], capture_output=True, text=True, timeout=15)
        n = len([l for l in out.stdout.splitlines() if l.strip()])
        if n:
            rep.add(OK, "日本語フォント", f"{n} 件（字幕の焼き込みに必要）")
        else:
            rep.add(NG, "日本語フォント", "見つかりません → `bash pipeline/setup.sh` を実行")
    except Exception:  # noqa: BLE001
        rep.add(WARN, "日本語フォント", "fc-list が無く確認できませんでした")


def main() -> int:
    print("\n" + "=" * 72)
    print(" 環境チェック — 値は一切表示しません（fp は照合用の指紋です）")
    print("=" * 72 + "\n")

    rep = Report()
    _ = check_shape(rep)
    check_youtube(rep)
    check_google_tts(rep)
    check_openai(rep)
    check_stability(rep)
    check_tools(rep)
    print()

    if rep.failed:
        print(f"✗ {rep.failed} 件の問題があります。上の FAIL を解消してから投稿に進んでください。\n")
        return 1
    print("✓ 必須項目はすべて通りました。この環境で投稿できます。"
          + (f"（WARN {rep.warned} 件は確認推奨）" if rep.warned else "") + "\n")
    print("補足: fp（指紋）を別環境のものと見比べると、取り違えが分かります。")
    print("  ・YOUTUBE_CLIENT_ID / SECRET / REFRESH_TOKEN … 2つの環境で fp が【違う】のが正しい")
    print("  ・OPENAI_API_KEY / STABILITY_API_KEY        … 2つの環境で fp が【同じ】でも問題ない\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
