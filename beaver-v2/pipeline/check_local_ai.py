#!/usr/bin/env python3
"""local-first/ollama 모드에서 Ollama 서버와 모델 준비 상태를 확인한다."""
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "설정.txt"


def setting(label, default):
    if not SETTINGS.exists():
        return default
    text = SETTINGS.read_text(encoding="utf-8")
    match = re.search(rf"^{label}\s*=\s*(.*?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match and match.group(1).strip() else default


def main():
    provider = setting("분석방식", "local-first").lower()
    model = setting("로컬모델", "qwen3:14b")
    if provider in ("gemini", "openrouter"):
        return 0
    try:
        response = requests.get("http://127.0.0.1:11434/api/tags", timeout=3)
        response.raise_for_status()
        names = {m.get("name") for m in response.json().get("models", [])}
    except Exception:
        print("❌ 로컬 AI(Ollama)가 실행되고 있지 않아요.")
        print("   먼저 '로컬AI_준비.command'를 더블클릭하세요.")
        return 1
    if model not in names:
        print(f"❌ 로컬 모델 '{model}'이 아직 없어요.")
        print("   먼저 '로컬AI_준비.command'를 더블클릭하세요.")
        return 1
    print(f"✅ 로컬 AI 준비 확인: {model}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
