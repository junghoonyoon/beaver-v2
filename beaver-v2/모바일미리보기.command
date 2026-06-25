#!/bin/bash
# 같은 와이파이의 휴대폰에서 종목 검색 프로토타입을 볼 수 있게 실행한다.
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/pipeline" || exit 1
clear
echo "📱 비버 모바일 미리보기"
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

IFACE="$(route get default 2>/dev/null | awk '/interface:/ {print $2; exit}')"
IP=""
if [ -n "$IFACE" ]; then
  IP="$(ipconfig getifaddr "$IFACE" 2>/dev/null)"
fi
if [ -z "$IP" ]; then
  IP="$(ipconfig getifaddr en0 2>/dev/null)"
fi
if [ -z "$IP" ]; then
  IP="$(ipconfig getifaddr en1 2>/dev/null)"
fi

if [ -z "$IP" ]; then
  echo "❌ 맥의 와이파이 IP를 찾지 못했어요."
  echo "   시스템 설정 > Wi-Fi에서 IP 주소를 확인한 뒤 알려주세요."
  read -r -p "엔터를 누르면 닫혀요..."
  exit 1
fi

echo ""
echo "최근 영상 자막을 갱신할게요. 이미 받은 자막은 캐시를 재사용합니다."
echo ""
if ! ./.venv/bin/python sync_search_index.py; then
  echo "❌ 검색 데이터 준비에 실패했어요."
  read -r -p "엔터를 누르면 닫혀요..."
  exit 1
fi

echo ""
echo "휴대폰에서 아래 주소를 열어보세요:"
echo ""
echo "  http://$IP:8765"
echo ""
echo "조건: 맥과 휴대폰이 같은 와이파이에 연결되어 있어야 해요."
echo "맥에서 확인할 주소: http://127.0.0.1:8765"
echo ""
(sleep 1; open "http://127.0.0.1:8765") &
SEARCH_HOST=0.0.0.0 SEARCH_PUBLIC_HOST="$IP" ./.venv/bin/python search_server.py
