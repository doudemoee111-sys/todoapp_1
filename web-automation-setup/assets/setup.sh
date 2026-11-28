#!/usr/bin/env bash
# =============================================================================
# クラウド環境セットアップスクリプト（Claude Code Routines の Setup script 欄に設定）
# 役割: 動画合成に必要な ffmpeg・日本語フォント・Python ライブラリを毎回用意する。
#       初回は導入に時間がかかるが、以降はキャッシュされる。
# 対象OS: Debian / Ubuntu 系（Claude Code のクラウド実行環境）
# =============================================================================
set -euo pipefail

echo "[setup] apt パッケージを導入します（ffmpeg・日本語Boldフォント）..."
# sudo が使える環境ではそのまま、使えない環境は sudo を外して実行してください。
apt-get update -y
apt-get install -y --no-install-recommends \
  ffmpeg \
  fonts-noto-cjk \
  fontconfig
fc-cache -f >/dev/null 2>&1 || true

# 導入される日本語Boldフォントの標準パス（config.py の FONT_PATH に使う）:
#   /usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc
echo "[setup] 日本語フォントの確認:"
fc-list 2>/dev/null | grep -i "NotoSansCJK" || echo "  (NotoSansCJK が見つからない場合は fonts-noto-cjk の導入を確認してください)"

echo "[setup] Python ライブラリを導入します..."
python3 -m pip install --upgrade pip
# パイプラインが requirements.txt を持っている場合はそちらを優先
if [ -f requirements.txt ]; then
  python3 -m pip install -r requirements.txt
else
  # 引き継ぎ書に記載の依存関係（requirements.txt が無い場合のフォールバック）
  python3 -m pip install \
    moviepy \
    pillow \
    numpy \
    requests \
    google-auth \
    google-auth-oauthlib \
    google-auth-httplib2 \
    google-api-python-client \
    anthropic \
    openai
fi

echo "[setup] 完了しました。"
