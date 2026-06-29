#!/usr/bin/env python3
"""로컬 캐시를 Supabase Storage로 1회 업로드한다."""
from runtime_settings import load_settings

load_settings()

import config  # noqa: E402
import remote_cache  # noqa: E402


def main():
    if not remote_cache.enabled():
        raise SystemExit(
            "❌ Supabase 설정이 필요합니다. SUPABASE_URL, "
            "SUPABASE_SERVICE_ROLE_KEY, SUPABASE_STORAGE_BUCKET을 설정해 주세요."
        )

    uploaded = 0
    failed = 0
    if config.SEARCH_INDEX_JSON.exists():
        if remote_cache.upload_file("search_index.json", config.SEARCH_INDEX_JSON):
            uploaded += 1
            print("✅ search_index.json 업로드")
        else:
            failed += 1

    for path in sorted(config.TRANSCRIPT_CACHE_DIR.glob("*.json")):
        remote_path = f"transcripts/{path.name}"
        if remote_cache.upload_file(remote_path, path):
            uploaded += 1
        else:
            failed += 1
        if uploaded and uploaded % 50 == 0:
            print(f"  · {uploaded}개 업로드")

    for path in sorted(config.STOCK_ANALYSIS_CACHE_DIR.glob("*.json")):
        remote_path = f"stock_analysis/{path.name}"
        if remote_cache.upload_file(remote_path, path):
            uploaded += 1
        else:
            failed += 1
        if uploaded and uploaded % 50 == 0:
            print(f"  · {uploaded}개 업로드")

    print(f"\n완료: 업로드 {uploaded}개 · 실패 {failed}개")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
