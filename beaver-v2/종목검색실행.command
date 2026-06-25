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
(sleep 1; open "http://127.0.0.1:8765") &
./.venv/bin/python search_server.py
