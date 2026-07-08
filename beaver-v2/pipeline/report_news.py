"""체크포인트 관련 뉴스를 구글 뉴스 RSS에서 가져와 리포트에 붙인다.

- 국내 뉴스: 한국어 검색어로 그대로 노출
- 해외 뉴스: 영어 검색어로 찾고 제목만 한국어로 번역, 링크는 원문
- API 키가 필요 없고, 실패해도 리포트는 그대로 나간다.
"""
import hashlib
import json
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

import config

NEWS_CACHE_DIR = config.CACHE_DIR / "report_news"
NEWS_CACHE_TTL_SECONDS = 6 * 3600
MAX_ITEMS_PER_CHECKPOINT = 3
_PER_QUERY_LIMIT = 2
_RSS_TIMEOUT_SECONDS = 8


def _rss_url(query, lang):
    if lang == "en":
        return f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
    return f"https://news.google.com/rss/search?q={quote(query)}&hl=ko&gl=KR&ceid=KR:ko"


def parse_rss_items(xml_text, lang, limit=_PER_QUERY_LIMIT):
    """구글 뉴스 RSS XML -> [{title, link, source, lang}]"""
    items = []
    root = ET.fromstring(xml_text)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source = (item.findtext("source") or "").strip()
        if not title or not link.startswith(("http://", "https://")):
            continue
        # 구글 뉴스 제목은 "제목 - 언론사" 형태라 언론사 꼬리를 떼어낸다.
        if source and title.endswith(f"- {source}"):
            title = title[: -len(source) - 1].rstrip(" -").strip()
        items.append({"title": title, "link": link, "source": source, "lang": lang})
        if len(items) >= limit:
            break
    return items


def _cache_path(query, lang):
    digest = hashlib.sha256(f"{lang}:{query}".encode("utf-8")).hexdigest()[:24]
    return NEWS_CACHE_DIR / f"{digest}.json"


def _fetch_news(query, lang, limit=_PER_QUERY_LIMIT):
    path = _cache_path(query, lang)
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(cached.get("fetchedAt") or 0) <= NEWS_CACHE_TTL_SECONDS:
            return (cached.get("items") or [])[:limit]
    except (OSError, ValueError, TypeError):
        pass
    response = requests.get(
        _rss_url(query, lang),
        timeout=_RSS_TIMEOUT_SECONDS,
        headers={"User-Agent": "Mozilla/5.0 (beaver-news)"},
    )
    response.raise_for_status()
    items = parse_rss_items(response.text, lang, limit)
    NEWS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{time.monotonic_ns()}.tmp")
    tmp.write_text(json.dumps({"fetchedAt": time.time(), "items": items}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return items


_QUERY_STOPWORDS = {
    "관련", "여부", "전망", "확인", "소식", "이슈", "뉴스", "및", "등",
    "the", "a", "an", "of", "and", "for", "to", "on", "in",
}


def _relevant(title, query):
    """검색어의 핵심 단어가 제목에 충분히 들어있는 기사만 남긴다 (범용 시황 기사 제거)."""
    import re
    haystack = title.lower()
    tokens = [
        w for w in re.split(r"[\s,·'\"]+", query.lower())
        if len(w) >= 2 and w not in _QUERY_STOPWORDS
    ]
    if not tokens:
        return True
    hits = sum(1 for w in tokens if w in haystack)
    return hits >= max(1, len(tokens) // 2)


def attach_checkpoint_news(report):
    """체크포인트마다 newsKeywords 기반 관련 뉴스를 붙인다. 실패는 항목 단위로 조용히 넘어간다."""
    import analyze

    checkpoints = (report or {}).get("checkpoints") or []
    pending = []  # 번역 대기 중인 해외 뉴스
    for checkpoint in checkpoints:
        keywords = checkpoint.get("newsKeywords") or {}
        found = []
        for lang in ("ko", "en"):
            raw = keywords.get(lang)
            queries = [raw] if isinstance(raw, str) else (raw or [])
            for query in queries:
                query = str(query or "").strip()
                if not query:
                    continue
                try:
                    found.extend(
                        item for item in _fetch_news(query, lang)
                        if _relevant(item["title"], query)
                    )
                except Exception:
                    continue
        seen = set()
        rows = []
        for item in found:
            key = item["title"].lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append(item)
        checkpoint["news"] = rows[:MAX_ITEMS_PER_CHECKPOINT]
        pending.extend(item for item in checkpoint["news"] if item["lang"] == "en")

    if pending:
        try:
            translated = analyze.translate_news_titles([item["title"] for item in pending])
            for item, ko_title in zip(pending, translated):
                if str(ko_title or "").strip():
                    item["titleKo"] = str(ko_title).strip()
        except Exception:
            pass  # 번역 실패 시 영어 제목 그대로 노출
    return report
