#!/usr/bin/env python3
"""최근 영상 자막을 모아 종목 검색 인덱스를 갱신한다."""
import sys

from runtime_settings import load_settings

load_settings()

import config  # noqa: E402
import stock_search  # noqa: E402


def main():
    if not config.YOUTUBE_API_KEY:
        sys.exit("❌ 설정.txt에 유튜브키를 입력해 주세요.")
    ready = [channel for channel in config.CHANNELS if channel.get("channelId")]
    if not ready:
        sys.exit("❌ 사용 가능한 채널 ID가 없어요.")
    print(f"최근 {config.SEARCH_LOOKBACK_DAYS}일 자막 인덱스를 갱신합니다.")
    print(f"채널 {len(ready)}곳 · 채널당 최대 {config.SEARCH_MAX_VIDEOS_PER_CHANNEL}개\n")
    stock_search.sync_index(ready)


if __name__ == "__main__":
    main()
