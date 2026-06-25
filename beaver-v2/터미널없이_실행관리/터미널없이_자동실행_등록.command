#!/bin/bash
# 종목 검색 서버를 macOS 백그라운드 서비스로 등록한다. 한 번 등록하면 터미널 없이 브라우저만 열면 된다.
MANAGER_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$MANAGER_DIR/.." && pwd)"
PLIST_SRC="$MANAGER_DIR/com.beaver.stocksearch.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.beaver.stocksearch.plist"
SERVICE="gui/$(id -u)/com.beaver.stocksearch"

clear
echo "🦫 비버 검색 백그라운드 서비스 등록"
echo "──────────────────────────────"

if [ ! -x "$ROOT/pipeline/.venv/bin/python" ]; then
  echo "❌ 실행 환경(.venv)이 없어요. 프로젝트 환경을 먼저 준비해야 합니다."
  read -r -p "엔터를 누르면 닫혀요..."
  exit 1
fi

if [ ! -f "$ROOT/pipeline/cache/search_index.json" ]; then
  echo "❌ 검색 인덱스가 아직 없어요."
  echo "   먼저 종목검색실행.command를 한 번 실행해 주세요."
  read -r -p "엔터를 누르면 닫혀요..."
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
launchctl bootout "gui/$(id -u)" "$PLIST_DST" >/dev/null 2>&1 || true
cp "$PLIST_SRC" "$PLIST_DST"
chmod 644 "$PLIST_DST"

if launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"; then
  launchctl kickstart -k "$SERVICE" >/dev/null 2>&1 || true
  echo ""
  echo "✅ 등록 완료!"
  echo "이제 터미널 없이 아래 주소만 열면 됩니다:"
  echo ""
  echo "  http://127.0.0.1:8765"
  echo ""
  echo "브라우저 즐겨찾기에 추가해두면 편해요."
  open "http://127.0.0.1:8765"
else
  echo "❌ 등록에 실패했어요."
fi

read -r -p "엔터를 누르면 닫혀요..."
