"""슈카월드 최신 영상의 자막 캐시·fallback 흐름을 확인한다.
Gemini를 안 쓰므로 요약 한도와 무관하게 '자막이 되는지'만 빠르게 확인한다.
"""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
SETTINGS = HERE.parent / "설정.txt"
CH = {"name": "슈카월드", "channelId": "UCsJ6RuBiTVWRX156FVbeaGg"}


def _load_key(label, env):
    if not SETTINGS.exists():
        return
    for line in SETTINGS.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith(label) and "=" in s:
            v = s.split("=", 1)[1].strip()
            if v and v != "여기에_붙여넣기":
                os.environ[env] = v


_load_key("유튜브키", "YOUTUBE_API_KEY")
_load_key("자막키", "SUPADATA_API_KEY")
os.environ.setdefault("GEMINI_API_KEY", "")

import youtube  # noqa: E402


def main():
    if not os.environ.get("YOUTUBE_API_KEY"):
        print("❌ 설정.txt 에 유튜브키가 없어요.")
        return
    print("슈카월드 최신 영상 찾는 중...")
    vids = youtube.recent_uploads(CH)
    if not vids:
        print("최근 3일 안에 올라온 영상이 없어요. (오늘/어제 업로드가 없을 수 있어요)")
        return
    v = vids[0]
    print(f"\n영상: {v['title']}\n{v['url']}\n")
    print("캐시 → InnerTube → Supadata → 무료 라이브러리 순서로 확인 중...")
    t = youtube.fetch_transcript(v["videoId"])
    if t:
        cached = " · 캐시 재사용" if youtube.LAST_TRANSCRIPT_FROM_CACHE else ""
        print(f"\n✅ 성공! 자막 {len(t):,}자 · 출처 {youtube.LAST_TRANSCRIPT_SOURCE}{cached}\n")
        print("─ 앞부분 미리보기 ──────────────")
        print(t[:600])
        print("────────────────────────────────")
    else:
        print(f"\n자막 수집 실패: {youtube.LAST_TRANSCRIPT_ERROR}")
        print("→ 실패 결과는 잠시 캐시되어 같은 영상을 바로 반복 요청하지 않아요.")


if __name__ == "__main__":
    main()
