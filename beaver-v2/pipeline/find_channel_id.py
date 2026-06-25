#!/usr/bin/env python3
"""핸들(@xxx) 또는 채널명으로 YouTube 채널 ID(UC...) 찾기.

YOUTUBE_API_KEY 필요. (YouTube가 닿는 환경 = 보통 내 PC 에서 실행)

사용:
  python find_channel_id.py @syukaworld
  python find_channel_id.py "슈카월드" "삼프로TV"
결과의 UC... 값을 config.CHANNELS 의 channelId 에 붙여넣으면 됨.
"""
import sys
import requests
import config

API = "https://www.googleapis.com/youtube/v3"


def resolve(q):
    key = config.YOUTUBE_API_KEY
    if q.startswith("@"):
        r = requests.get(f"{API}/channels",
                         params={"part": "id,snippet", "forHandle": q, "key": key},
                         timeout=15).json()
        items = r.get("items", [])
        if items:
            return [(items[0]["id"], items[0]["snippet"]["title"])]
    r = requests.get(f"{API}/search",
                     params={"part": "snippet", "q": q, "type": "channel",
                             "maxResults": 3, "key": key},
                     timeout=15).json()
    return [(it["snippet"]["channelId"], it["snippet"]["title"]) for it in r.get("items", [])]


if __name__ == "__main__":
    if not config.YOUTUBE_API_KEY:
        sys.exit("YOUTUBE_API_KEY 가 설정되지 않았습니다. (.env 또는 환경변수)")
    for q in sys.argv[1:]:
        print(f"\n[{q}]")
        for cid, title in resolve(q):
            print(f"  {cid}  ({title})")
