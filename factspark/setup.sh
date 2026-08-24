#!/usr/bin/env bash
# =============================================================================
# クラウド(Claude Code Routines)環境セットアップスクリプト
# 方針: 途中で失敗しても止めず(set -e は使わない)、最後に必ず診断を出して exit 0。
#       これにより Claude セッションは必ず起動でき、何が足りないかを自分で報告できる。
# ffmpeg は pip の imageio-ffmpeg で導入(apt/root 不要)。moviepy はこれを自動利用する。
# 日本語フォントは apt の fonts-noto-cjk を試す(使えなければ診断に出す)。
# =============================================================================
echo "[setup] === start ==="
echo "[setup] whoami=$(whoami)  sudo=$(command -v sudo || echo none)"

# --- Python 依存 (PyPI が許可されている必要あり) ---
python3 -m pip install --upgrade pip 2>&1 | tail -1 || echo "[setup][warn] pip upgrade failed"
python3 -m pip install -r requirements.txt 2>&1 | tail -3 || echo "[setup][warn] requirements install failed"
# ffmpeg 本体を pip で(システムに無くてもこれで動く)
python3 -m pip install imageio-ffmpeg 2>&1 | tail -1 || echo "[setup][warn] imageio-ffmpeg install failed"
# cffi を明示導入。これが無いと cryptography の Rust バインディングが PanicException を
# 出し、google.auth の import ごと失敗する(YouTube認証不能)。環境により pip が
# externally-managed のため --break-system-packages も試す。
python3 -m pip install --upgrade cffi 2>&1 | tail -1 \
  || python3 -m pip install --upgrade --break-system-packages cffi 2>&1 | tail -1 \
  || echo "[setup][warn] cffi install failed"

# --- 日本語Boldフォント (apt が使えれば導入。失敗しても続行) ---
if command -v apt-get >/dev/null 2>&1; then
  # Noto CJK に加え、フォールバックの IPAゴシックも導入する。sekai 等で Noto の導入が
  # 失敗しても、config.py の候補リストが IPAゴシックを拾って字幕を焼けるようにする。
  ( sudo apt-get update -y && sudo apt-get install -y --no-install-recommends fonts-noto-cjk fonts-ipafont-gothic fontconfig ) 2>&1 | tail -2 \
    || ( apt-get update -y && apt-get install -y --no-install-recommends fonts-noto-cjk fonts-ipafont-gothic fontconfig ) 2>&1 | tail -2 \
    || echo "[setup][warn] apt でのフォント導入に失敗(ネットワークのパッケージ既定リスト許可 or root 権限を確認)"
  command -v fc-cache >/dev/null 2>&1 && fc-cache -f >/dev/null 2>&1 || true
fi

# --- 診断(ここが最重要: 何が使えるかを必ず出す) ---
echo "[setup][diag] python : $(python3 --version 2>&1)"
echo "[setup][diag] sys ffmpeg : $(command -v ffmpeg || echo none)"
python3 - <<'PY' 2>&1 || true
try:
    import imageio_ffmpeg
    print("[setup][diag] imageio-ffmpeg :", imageio_ffmpeg.get_ffmpeg_exe())
except Exception as e:
    print("[setup][diag] imageio-ffmpeg : ERR", e)
for m in ("cffi", "moviepy", "PIL", "numpy", "requests", "googleapiclient", "google_auth_oauthlib", "google.auth", "google.auth.transport.requests"):
    try:
        __import__(m); print(f"[setup][diag] import {m}: OK")
    except Exception as e:
        print(f"[setup][diag] import {m}: ERR {e}")
# 実際に採用される字幕フォントのパスを表示(存在するものが選ばれる)
try:
    import sys; sys.path.insert(0, "generator")
    import config, os
    print(f"[setup][diag] FONT_PATH -> {config.FONT_PATH} exists={os.path.exists(str(config.FONT_PATH))}")
except Exception as e:
    print(f"[setup][diag] FONT_PATH : ERR {e}")
PY
echo "[setup][diag] JP fonts:"; fc-list 2>/dev/null | grep -iE "CJK|Noto Sans JP|IPA" | head -3 || echo "  (日本語フォント未検出)"
echo "[setup] === done (exit 0) ==="
exit 0
