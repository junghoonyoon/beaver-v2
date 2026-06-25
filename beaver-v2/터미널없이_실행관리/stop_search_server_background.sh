#!/bin/bash
# 백그라운드 종목 검색 서버를 종료한다.
set -u

MANAGER_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$MANAGER_DIR/.." && pwd)"
PIPELINE_DIR="$ROOT_DIR/pipeline"
PID_FILE="$PIPELINE_DIR/cache/search_server.pid"

if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$PID" ]; then
    kill "$PID" >/dev/null 2>&1 || true
  fi
  rm -f "$PID_FILE"
fi

PIDS="$(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$PIDS" ]; then
  kill $PIDS >/dev/null 2>&1 || true
fi

osascript -e 'display notification "종목 검색 서버를 종료했어요." with title "비버 검색"' >/dev/null 2>&1 || true
