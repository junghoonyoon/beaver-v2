#!/bin/bash
# 비버 검색 백그라운드 서비스를 해제한다.
PLIST_DST="$HOME/Library/LaunchAgents/com.beaver.stocksearch.plist"

clear
echo "🦫 비버 검색 백그라운드 서비스 해제"
echo "──────────────────────────────"

launchctl bootout "gui/$(id -u)" "$PLIST_DST" >/dev/null 2>&1 || true
rm -f "$PLIST_DST"

PIDS="$(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$PIDS" ]; then
  kill $PIDS >/dev/null 2>&1 || true
fi

echo ""
echo "✅ 해제 완료."
read -r -p "엔터를 누르면 닫혀요..."
