#!/usr/bin/env python3
"""실행 전에 설정.txt와 필수 API 키가 준비됐는지 확인한다."""
import re
import sys
from pathlib import Path

SETTINGS = Path(__file__).resolve().parent.parent / "설정.txt"
PLACEHOLDER_PREFIXES = ("여기에_", "새_키_", "YOUR_")


def read_value(text, label):
    match = re.search(rf"^{label}\s*=\s*(.*?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def main():
    if not SETTINGS.exists():
        print("❌ 설정.txt가 없어요.")
        return 1

    text = SETTINGS.read_text(encoding="utf-8")
    missing = []
    for label in ("유튜브키",):
        value = read_value(text, label)
        if not value or value.startswith(PLACEHOLDER_PREFIXES):
            missing.append(label)
    provider = read_value(text, "분석방식").lower()
    if provider == "openrouter":
        value = read_value(text, "오픈라우터키")
        if not value or value.startswith(PLACEHOLDER_PREFIXES):
            missing.append("오픈라우터키")

    if missing:
        print("❌ 설정에 필요한 키가 비어 있어요: " + ", ".join(missing))
        print("   열리는 설정 파일에서 비어 있는 키를 입력하고 저장하세요.")
        print("   쓰지 않는 제공자의 키는 비워 둬도 됩니다.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
