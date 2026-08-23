#!/usr/bin/env bash
# 毎日の素材生成をcronから叩くためのラッパー。
# cron は PATH が最小なので、node の絶対パスを NODE_BIN で指定してください。
set -euo pipefail

cd "$(dirname "$0")/.."
NODE_BIN="${NODE_BIN:-$(command -v node)}"
LOG_DIR="out/_logs"
mkdir -p "$LOG_DIR"
STAMP="$(TZ=Asia/Tokyo date +%F)"

{
  echo "===== $(TZ=Asia/Tokyo date '+%F %T %Z') ====="
  "$NODE_BIN" src/run.mjs "$STAMP"
} >> "$LOG_DIR/daily-$STAMP.log" 2>&1

echo "done: out/$STAMP/  (レビュー: out/$STAMP/REVIEW.md)"
