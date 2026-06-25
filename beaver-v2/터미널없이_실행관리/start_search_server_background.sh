#!/bin/bash
# 터미널 창 없이 종목 검색 서버를 백그라운드에서 실행한다.
set -u

MANAGER_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$MANAGER_DIR/.." && pwd)"
PIPELINE_DIR="$ROOT_DIR/pipeline"
LOG_DIR="$PIPELINE_DIR/cache"
LOG_FILE="$LOG_DIR/search_server.log"
PID_FILE="$LOG_DIR/search_server.pid"
URL="http://127.0.0.1:8765"

mkdir -p "$LOG_DIR"

if curl -sS --max-time 1 "$URL/api/status" >/dev/null 2>&1; then
  open "$URL"
  exit 0
fi

if [ ! -x "$PIPELINE_DIR/.venv/bin/python" ]; then
  osascript -e 'display dialog "실행 환경(.venv)이 없어요. 프로젝트 환경을 먼저 준비해야 합니다." buttons {"확인"} default button "확인"'
  exit 1
fi

if [ ! -f "$PIPELINE_DIR/cache/search_index.json" ]; then
  osascript -e 'display dialog "검색 인덱스가 아직 없어요. 먼저 종목검색실행.command를 한 번 실행해 주세요." buttons {"확인"} default button "확인"'
  exit 1
fi

cd "$PIPELINE_DIR" || exit 1
SEARCH_HOST=127.0.0.1 nohup "$PIPELINE_DIR/.venv/bin/python" search_server.py > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sS --max-time 1 "$URL/api/status" >/dev/null 2>&1; then
    open "$URL"
    exit 0
  fi
  sleep 0.5
done

open "$URL"
exit 0
