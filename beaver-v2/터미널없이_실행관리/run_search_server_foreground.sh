#!/bin/bash
# LaunchAgent가 실행하는 종목 검색 서버. 터미널 없이 백그라운드에서 foreground로 유지된다.
set -u

MANAGER_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$MANAGER_DIR/.." && pwd)"
PIPELINE_DIR="$ROOT_DIR/pipeline"
cd "$PIPELINE_DIR" || exit 1

if [ ! -x "$PIPELINE_DIR/.venv/bin/python" ]; then
  exit 1
fi

if [ ! -f "$PIPELINE_DIR/cache/search_index.json" ]; then
  exit 1
fi

SEARCH_HOST=127.0.0.1 "$PIPELINE_DIR/.venv/bin/python" search_server.py
