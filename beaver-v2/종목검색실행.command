#!/bin/bash
# 최근 자막을 갱신한 뒤 종목 검색 웹앱을 실행한다.
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/pipeline" || exit 1
clear
echo "🦫 비버 종목 검색"
echo "──────────────────────────────"

if [ ! -x .venv/bin/python ]; then
  echo "❌ 실행 환경(.venv)이 없어요. 프로젝트 환경을 먼저 준비해야 합니다."
  read -r -p "엔터를 누르면 닫혀요..."
  exit 1
fi

if ! ./.venv/bin/python check_settings.py; then
  open -t "$ROOT/설정.txt"
  read -r -p "유튜브키를 입력하고 저장한 뒤 다시 실행하세요. 엔터를 누르면 닫혀요..."
  exit 1
fi

if ! ./.venv/bin/python check_local_ai.py; then
  read -r -p "엔터를 누르면 닫혀요..."
  exit 1
fi

echo ""
echo "최근 영상 자막을 갱신할게요. 처음에는 시간이 조금 걸릴 수 있어요."
echo "이미 받은 자막은 캐시를 재사용합니다."
echo ""
if ! ./.venv/bin/python sync_search_index.py; then
  echo "❌ 검색 데이터 준비에 실패했어요."
  read -r -p "엔터를 누르면 닫혀요..."
  exit 1
fi

echo ""
echo "검색 화면을 여는 중이에요..."
APP_NAME="stockzip"
APP_URL="https://stockzip.localhost"
echo "앞으로는 포트 번호 대신 아래 주소를 쓰면 됩니다:"
echo "  $APP_URL"
echo "처음 실행이면 macOS 권한 확인이 뜰 수 있어요."
echo ""

if ! command -v npx >/dev/null 2>&1; then
  echo "❌ npx를 찾지 못했어요. Node.js 24 이상을 설치한 뒤 다시 실행하세요."
  read -r -p "엔터를 누르면 닫혀요..."
  exit 1
fi

(
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    URL="$(npx -y portless get "$APP_NAME" 2>/dev/null || true)"
    if [ -n "$URL" ]; then
      open "$URL"
      exit 0
    fi
    sleep 0.5
  done
  open "$APP_URL"
) &
SEARCH_HOST=127.0.0.1 npx -y portless "$APP_NAME" -- ./.venv/bin/python search_server.py
