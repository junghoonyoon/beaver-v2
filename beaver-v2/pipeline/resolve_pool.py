#!/usr/bin/env python3
"""config.CHANNELS 의 채널명을 YouTube로 조회해 channelId 를 channel_ids.json 에 저장.

※ 유튜브가 닿는 환경(= 보통 사용자 맥)에서 한 번만 실행하면 됩니다.
   설정.txt 의 유튜브키를 읽습니다.

사용:
  cd pipeline
  python3 resolve_pool.py            # ID 없는 채널 전부 조회
  python3 resolve_pool.py --force    # 이미 있는 것도 다시 조회

결과(channel_ids.json)는 config.py 가 자동으로 읽어 채널ID를 채웁니다.
이름 검색은 가끔 엉뚱한 채널을 고를 수 있으니, 출력된 (제목)을 확인하고
틀린 건 channel_ids.json 을 직접 고치세요.
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SETTINGS = HERE.parent / "설정.txt"
OUT = HERE / "channel_ids.json"


def load_youtube_key():
    if os.environ.get("YOUTUBE_API_KEY"):
        return
    if SETTINGS.exists():
        m = re.search(r"유튜브키\s*=\s*(\S+)", SETTINGS.read_text(encoding="utf-8"))
        if m:
            os.environ["YOUTUBE_API_KEY"] = m.group(1)


def main():
    force = "--force" in sys.argv
    load_youtube_key()

    import config
    import find_channel_id

    if not config.YOUTUBE_API_KEY:
        sys.exit("❌ 유튜브키를 못 찾았어요. 설정.txt 의 '유튜브키 =' 줄을 확인하세요.")

    ids = {}
    if OUT.exists():
        ids = json.loads(OUT.read_text(encoding="utf-8"))

    todo = [c for c in config.CHANNELS
            if force or (c["name"] not in ids and not c.get("channelId"))]
    print(f"조회 대상 {len(todo)}곳 (이미 확보 {len(ids)}곳)\n")

    for c in todo:
        name = c["name"]
        try:
            res = find_channel_id.resolve(name)
        except Exception as e:
            print(f"  ⚠️ {name}: 조회 오류 {type(e).__name__}: {str(e)[:80]}")
            continue
        if not res:
            print(f"  ❓ {name}: 결과 없음 (이름을 @핸들로 바꿔보세요)")
            continue
        cid, title = res[0]
        ids[name] = cid
        a, b = name.replace(" ", ""), title.replace(" ", "")
        flag = "" if (a in b or b in a) else "  ← 제목 다름, 확인!"
        print(f"  · {name:14s} → {cid}  ({title}){flag}")

    OUT.write_text(json.dumps(ids, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ channel_ids.json 저장 ({len(ids)}곳). config.py 가 자동으로 읽어요.")
    print("   '← 제목 다름' 표시된 건 channel_ids.json 에서 직접 고치세요.")


if __name__ == "__main__":
    main()
