#!/bin/bash
# 사용자가 직접 실행해 Ollama와 Qwen3 14B를 준비하는 도우미.
clear
echo "🦫 비버 로컬 AI 준비"
echo "──────────────────────────────"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama가 아직 설치되지 않았어요."
  echo "지금 설치 페이지를 열게요. 설치를 마친 뒤 이 파일을 다시 실행하세요."
  open "https://ollama.com/download"
  read -r -p "엔터를 누르면 닫혀요..."
  exit 1
fi

if ! curl -sS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "Ollama를 시작하는 중이에요..."
  open -a Ollama
  sleep 3
fi

echo ""
echo "Qwen3 14B 모델을 준비할게요. 처음 한 번은 약 9GB를 내려받아요."
echo "이미 받아둔 경우에는 바로 끝납니다."
echo ""
if ! ollama pull qwen3:14b; then
  echo ""
  echo "❌ 모델 준비에 실패했어요. Ollama 앱이 실행 중인지 확인해 주세요."
  read -r -p "엔터를 누르면 닫혀요..."
  exit 1
fi

echo ""
echo "✅ 준비됐어요. 이제 '종목검색실행.command'를 실행하세요."
read -r -p "엔터를 누르면 닫혀요..."
