#!/usr/bin/env bash
# 週次インサイトレポート生成（IG_USER_ID / IG_ACCESS_TOKEN が必要）
set -euo pipefail
cd "$(dirname "$0")/.."
NODE_BIN="${NODE_BIN:-$(command -v node)}"
mkdir -p out/_logs
"$NODE_BIN" src/steps/09-insights.mjs >> "out/_logs/weekly-$(TZ=Asia/Tokyo date +%F).log" 2>&1
echo "done: out/_reports/"
