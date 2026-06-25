#!/bin/bash
# KRX 상장종목정보 API 호출을 타임아웃·진행표시와 함께 진단한다. (멈추지 않음)
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/pipeline" || exit 1
clear
echo "🦫 KRX API 진단 (타임아웃 15초)"
echo "──────────────────────────────"

./.venv/bin/python - <<'PY'
import sys
from urllib.parse import urlencode
from runtime_settings import load_settings
load_settings()
import config
import requests

key = (config.KRX_API_KEY or "").strip()
print(f"키 확인: 길이 {len(key)} · 앞 6자리 {key[:6] or 'EMPTY'}", flush=True)
print(f"엔드포인트: {config.KRX_LISTED_API_URL}", flush=True)
tail = urlencode({"pageNo": 1, "numOfRows": 3, "resultType": "json"})

def try_call(label, url):
    print(f"\n[{label}] 요청 중... (최대 15초)", flush=True)
    try:
        r = requests.get(url, timeout=(15, 15))
        print(f"  → HTTP {r.status_code}", flush=True)
        body = r.text[:700].replace(key, "[KEY]")
        print("  → 응답:", body, flush=True)
    except Exception as e:
        print(f"  → 에러: {type(e).__name__}: {str(e)[:250]}", flush=True)

try_call("디코딩키(원본 그대로)", f"{config.KRX_LISTED_API_URL}?serviceKey={key}&{tail}")
try_call("인코딩키(URL 인코딩)", f"{config.KRX_LISTED_API_URL}?{urlencode({'serviceKey': key})}&{tail}")
print("\n진단 끝.", flush=True)
PY

echo ""
read -r -p "결과를 확인했으면 엔터를 누르세요..."
