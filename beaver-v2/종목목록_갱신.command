#!/bin/bash
# 공공데이터포털 KRX 상장종목정보를 즉시 받아 종목 자동완성 목록을 갱신한다.
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/pipeline" || exit 1
clear
echo "🦫 비버 종목목록 갱신 (KRX 전종목)"
echo "──────────────────────────────"

if [ ! -x .venv/bin/python ]; then
  echo "❌ 실행 환경(.venv)이 없어요. 프로젝트 환경을 먼저 준비해야 합니다."
  read -r -p "엔터를 누르면 닫혀요..."
  exit 1
fi

./.venv/bin/python sync_krx_listed.py
echo ""
read -r -p "확인했으면 엔터를 누르세요..."
