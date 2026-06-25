#!/usr/bin/env python3
"""공공데이터포털 KRX 상장종목정보 캐시를 즉시 갱신한다."""
import sys

from runtime_settings import load_settings

load_settings()

import config  # noqa: E402
import krx_listed  # noqa: E402


def main():
    if not config.KRX_API_KEY:
        sys.exit("❌ 설정.txt에 공공데이터키를 입력해 주세요.")
    try:
        payload, changed = krx_listed.refresh(force=True)
    except Exception as exc:
        sys.exit(f"❌ KRX 상장종목정보 갱신 실패: {exc}")
    status = "갱신" if changed else "확인"
    print(f"✅ KRX 상장종목정보 {status}: {payload.get('count', 0)}개")
    print(f"   기준일자: {payload.get('baseDate') or '-'}")
    print(f"   저장 위치: {config.KRX_LISTED_JSON}")


if __name__ == "__main__":
    main()
