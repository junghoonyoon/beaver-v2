#!/usr/bin/env python3
"""Nasdaq Trader 공개 Symbol Directory로 미국 상장종목 캐시를 즉시 갱신한다."""
import sys

from runtime_settings import load_settings

load_settings()

import config  # noqa: E402
import us_listed  # noqa: E402


def main():
    try:
        payload, changed = us_listed.refresh(force=True)
    except Exception as exc:
        sys.exit(f"❌ 미국 상장종목정보 갱신 실패: {exc}")
    status = "갱신" if changed else "확인"
    print(f"✅ 미국 상장종목정보 {status}: {payload.get('count', 0)}개")
    print(f"   기준: {payload.get('baseDate') or '-'}")
    print(f"   저장 위치: {config.US_LISTED_JSON}")


if __name__ == "__main__":
    main()
