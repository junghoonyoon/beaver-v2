#!/usr/bin/env python3
"""종목 검색 화면과 로컬 검색 API를 제공한다."""
import base64
import datetime
import gzip
import hashlib
import html
import http.client
import json
import mimetypes
import os
import re
import struct
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from runtime_settings import load_settings

load_settings()

import config  # noqa: E402
import krx_listed  # noqa: E402
import analytics  # noqa: E402
import market_rankings  # noqa: E402
import stock_search  # noqa: E402
import us_listed  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
APP_HTML = ROOT / "앱화면" / "stock-search.html"
APP_ASSETS = ROOT / "앱화면" / "assets"
DASHBOARD_HTML = ROOT / "앱화면" / "mvp-dashboard.html"
ROBOTS_TXT = ROOT / "앱화면" / "robots.txt"
SITEMAP_XML = ROOT / "앱화면" / "sitemap.xml"
GOOGLE_VERIFICATION_HTML = ROOT / "앱화면" / "google661da6d73ff97f8e.html"
HOST = os.environ.get("SEARCH_HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
PORT = int(os.environ.get("SEARCH_PORT") or os.environ.get("PORT") or "8765")
PUBLIC_HOST = os.environ.get("SEARCH_PUBLIC_HOST", HOST)
PUBLIC_BASE_URL = os.environ.get("SEARCH_PUBLIC_BASE_URL", "https://stockzip.kr").rstrip("/")
QUOTE_WS_INTERVAL_SECONDS = max(3, int(os.environ.get("QUOTE_WS_INTERVAL_SECONDS", "10")))
JOBS = {}
JOBS_LOCK = threading.Lock()
MAX_JOBS = 20
SEARCH_RESULT_CACHE = {}
SEARCH_RESULT_CACHE_LOCK = threading.Lock()
SEARCH_RESULT_CACHE_DIR = config.CACHE_DIR / "search_results"
SEARCH_RESULT_CACHE_VERSION = 2
SEARCH_RESULT_CACHE_TTL_SECONDS = max(60, int(os.environ.get("SEARCH_RESULT_CACHE_TTL_SECONDS", "3600")))
SEARCH_RESULT_CACHE_MAX_ITEMS = max(10, int(os.environ.get("SEARCH_RESULT_CACHE_MAX_ITEMS", "200")))
SEARCH_REFRESH_STATE = {
    "running": False,
    "lastStartedAt": None,
    "lastFinishedAt": None,
    "lastError": "",
}
SEARCH_REFRESH_LOCK = threading.Lock()
POPULAR_PREWARM_STATE = {
    "running": False,
    "lastStartedAt": None,
    "lastFinishedAt": None,
    "lastIndexUpdatedAt": None,
    "lastError": "",
    "lastStats": None,
}
POPULAR_PREWARM_LOCK = threading.Lock()
SEARCH_RESULT_PREWARM_STATE = {
    "running": False,
    "lastStartedAt": None,
    "lastFinishedAt": None,
    "lastIndexUpdatedAt": None,
    "lastError": "",
    "lastStats": None,
}
SEARCH_RESULT_PREWARM_LOCK = threading.Lock()
WATCHLIST_REFRESH_RATE_LIMIT = {}
WATCHLIST_REFRESH_RESPONSE_CACHE = {}
WATCHLIST_REFRESH_LOCK = threading.Lock()


class SearchServer(ThreadingHTTPServer):
    allow_reuse_address = True


def _ready_channels():
    return [channel for channel in config.CHANNELS if channel.get("channelId")]


def _index_age_seconds(index):
    updated_at = index.get("updatedAt")
    if not updated_at:
        return None
    try:
        updated = datetime.datetime.fromisoformat(updated_at)
    except (TypeError, ValueError):
        return None
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=stock_search.KST)
    return max(0, (datetime.datetime.now(stock_search.KST) - updated).total_seconds())


def _is_search_index_stale(index):
    if not index.get("videos"):
        return True
    if index.get("version") != stock_search._SEARCH_INDEX_VERSION:
        return True
    if index.get("lookbackDays") != config.SEARCH_LOOKBACK_DAYS:
        return True
    if index.get("maxVideosPerChannel") != config.SEARCH_MAX_VIDEOS_PER_CHANNEL:
        return True
    age = _index_age_seconds(index)
    if age is None:
        return True
    return age >= config.SEARCH_INDEX_REFRESH_HOURS * 3600


def search_refresh_status(index=None):
    index = index or stock_search.load_index()
    age = _index_age_seconds(index)
    with SEARCH_REFRESH_LOCK:
        state = dict(SEARCH_REFRESH_STATE)
    state.update({
        "enabled": config.SEARCH_INDEX_AUTO_REFRESH_ENABLED,
        "refreshHours": config.SEARCH_INDEX_REFRESH_HOURS,
        "ageSeconds": age,
        "stale": _is_search_index_stale(index),
    })
    return state


def popular_prewarm_status():
    with POPULAR_PREWARM_LOCK:
        state = dict(POPULAR_PREWARM_STATE)
    state.update({
        "enabled": config.POPULAR_PREWARM_ENABLED,
        "marketLimit": config.POPULAR_PREWARM_MARKET_LIMIT,
    })
    return state


def search_result_prewarm_status():
    with SEARCH_RESULT_PREWARM_LOCK:
        state = dict(SEARCH_RESULT_PREWARM_STATE)
    state.update({
        "enabled": config.SEARCH_RESULT_PREWARM_ENABLED,
        "limit": config.SEARCH_RESULT_PREWARM_LIMIT,
    })
    return state


def _public_url(path):
    return f"{PUBLIC_BASE_URL}/{str(path or '').lstrip('/')}"


def _escape(value):
    return html.escape(str(value or ""), quote=True)


def _report_period_label():
    return "최근 2주" if config.SEARCH_LOOKBACK_DAYS == 14 else f"최근 {config.SEARCH_LOOKBACK_DAYS}일"


def _app_report_share_meta(query):
    identity = stock_search.stock_identity(query)
    name = identity.get("name") or str(query or "").strip()
    if not name:
        return None
    title = f"{name} {_report_period_label()} 유튜버 의견 요약 리포트"
    description = f"{name} {_report_period_label()} 영상 속 의견을 모아 30초 리포트로 요약해 드려요. 근거 영상은 필요한 부분만 골라 보세요."
    url = _public_url(f"/?q={quote(name)}&tab=report")
    return {
        "title": title,
        "description": description,
        "url": url,
    }


def _replace_head_attr(html_text, selector, value):
    pattern = rf'(<meta {selector} content=")[^"]*(">)'
    return re.sub(pattern, rf'\1{_escape(value)}\2', html_text, count=1)


def _replace_app_share_meta(html_text, meta):
    if not meta:
        return html_text
    html_text = re.sub(r"<title>.*?</title>", f"<title>{_escape(meta['title'])}</title>", html_text, count=1, flags=re.S)
    html_text = re.sub(r'(<link rel="canonical" href=")[^"]*(">)', rf'\1{_escape(meta["url"])}\2', html_text, count=1)
    html_text = _replace_head_attr(html_text, 'name="description"', meta["description"])
    html_text = _replace_head_attr(html_text, 'property="og:title"', meta["title"])
    html_text = _replace_head_attr(html_text, 'property="og:description"', meta["description"])
    html_text = _replace_head_attr(html_text, 'property="og:url"', meta["url"])
    html_text = _replace_head_attr(html_text, 'name="twitter:title"', meta["title"])
    html_text = _replace_head_attr(html_text, 'name="twitter:description"', meta["description"])
    return html_text


def _format_date(value):
    if not value:
        return ""
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return str(value)[:10]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=stock_search.KST)
    return parsed.astimezone(stock_search.KST).strftime("%Y-%m-%d")


def _stock_url(stock):
    slug = stock_search.stock_slug(stock)
    return _public_url(f"/stocks/{quote(slug, safe='')}")


def _stock_page_payload(stock):
    query = stock_search.stock_display_name(stock)
    videos, stats = stock_search.find_videos_with_stats(
        query,
        max_youtubers=config.SEARCH_MAX_YOUTUBERS,
        include_fallback=False,
    )
    latest = max((video.get("publishedAt", "") for video in videos), default="")
    return {
        "stock": stock,
        "name": query,
        "code": str(stock.get("code") or "").strip().upper(),
        "market": str(stock.get("market") or "").strip(),
        "videos": videos,
        "stats": stats,
        "latestPublishedAt": latest,
        "indexUpdatedAt": stock_search.load_index().get("updatedAt"),
    }


def _stock_page_html(stock):
    payload = _stock_page_payload(stock)
    name = payload["name"]
    code = payload["code"]
    market = payload["market"]
    code_label = f"{market} {code}".strip()
    period_label = _report_period_label()
    title = f"{name} {period_label} 유튜버 의견 요약 리포트"
    description = (
        f"{name}({code}) {period_label} 영상 속 의견을 모아 30초 리포트로 요약해 드려요. "
        "근거 영상은 필요한 부분만 골라 보세요."
        if code else
        f"{name} {period_label} 영상 속 의견을 모아 30초 리포트로 요약해 드려요. 근거 영상은 필요한 부분만 골라 보세요."
    )
    canonical = _stock_url(stock)
    app_url = _public_url(f"/?q={quote(name)}&tab=report")
    latest = _format_date(payload["latestPublishedAt"]) or _format_date(payload["indexUpdatedAt"])
    videos = payload["videos"][:8]
    stats = payload["stats"]
    image_url = _public_url("/assets/og-image.png")
    video_items = "\n".join(
        f"""          <li>
            <a href="{_escape(video.get('url'))}" rel="nofollow noopener" target="_blank">{_escape(video.get('title'))}</a>
            <span>{_escape(video.get('channel'))} · {_escape(_format_date(video.get('publishedAt')))} · 조회 {_escape(video.get('views') or 0)}</span>
          </li>"""
        for video in videos
    )
    if not video_items:
        video_items = """          <li>
            <span>현재 검색 인덱스에서 확인된 최근 언급 영상이 아직 없습니다.</span>
          </li>"""
    web_page_schema = {
        "@type": "WebPage",
        "@id": f"{canonical}#webpage",
        "name": title,
        "url": canonical,
        "description": description,
        "inLanguage": "ko-KR",
        "isPartOf": {
            "@id": _public_url("/#website"),
        },
        "breadcrumb": {
            "@id": f"{canonical}#breadcrumb",
        },
        "primaryImageOfPage": {
            "@type": "ImageObject",
            "url": image_url,
            "width": 1200,
            "height": 630,
        },
        "mainEntity": {
            "@type": "Thing",
            "name": name,
            "identifier": code,
        },
    }
    if latest:
        web_page_schema["dateModified"] = latest
    json_ld = json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": _public_url("/#organization"),
                "name": "지금사도될까요?",
                "url": _public_url("/"),
                "logo": image_url,
            },
            {
                "@type": "WebSite",
                "@id": _public_url("/#website"),
                "name": "지금사도될까요?",
                "url": _public_url("/"),
                "inLanguage": "ko-KR",
                "publisher": {
                    "@id": _public_url("/#organization"),
                },
            },
            {
                "@type": "BreadcrumbList",
                "@id": f"{canonical}#breadcrumb",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": 1,
                        "name": "홈",
                        "item": _public_url("/"),
                    },
                    {
                        "@type": "ListItem",
                        "position": 2,
                        "name": name,
                        "item": canonical,
                    },
                ],
            },
            web_page_schema,
        ],
    }, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="index,follow,max-image-preview:large">
  <meta name="theme-color" content="#ffffff">
  <title>{_escape(title)}</title>
  <meta name="description" content="{_escape(description)}">
  <link rel="canonical" href="{_escape(canonical)}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="지금사도될까요?">
  <meta property="og:title" content="{_escape(title)}">
  <meta property="og:description" content="{_escape(description)}">
  <meta property="og:url" content="{_escape(canonical)}">
  <meta property="og:image" content="{_escape(image_url)}">
  <meta property="og:image:secure_url" content="{_escape(image_url)}">
  <meta property="og:image:type" content="image/png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:alt" content="{_escape(title)}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{_escape(title)}">
  <meta name="twitter:description" content="{_escape(description)}">
  <meta name="twitter:image" content="{_escape(image_url)}">
  <meta name="twitter:image:alt" content="{_escape(title)}">
  <script type="application/ld+json">{json_ld}</script>
  <style>
    :root {{ color-scheme:light; --ink:#1d1d1f; --body:#555b64; --line:#e5e7eb; --blue:#0071e3; --canvas:#f7f8fa; }}
    * {{ box-sizing:border-box }}
    body {{ margin:0; color:var(--ink); background:#fff; font-family:Inter,-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif; }}
    main {{ width:min(760px,calc(100% - 32px)); margin:0 auto; padding:44px 0 72px; }}
    .brand {{ display:inline-flex; align-items:center; gap:10px; color:var(--ink); text-decoration:none; font-weight:850; }}
    .mark {{ display:inline-flex; align-items:center; justify-content:center; width:28px; height:28px; border-radius:50%; background:var(--ink); color:#fff; }}
    .breadcrumb {{ display:flex; flex-wrap:wrap; gap:7px; margin-top:34px; color:#7a8088; font-size:13px; font-weight:650; }}
    .breadcrumb a {{ color:inherit; text-decoration:none; }}
    .breadcrumb a:hover {{ color:var(--blue); }}
    .eyebrow {{ margin:46px 0 12px; color:var(--blue); font-size:14px; font-weight:800; }}
    h1 {{ margin:0; font-size:clamp(34px,7vw,58px); line-height:1.05; letter-spacing:0; }}
    .lead {{ margin:18px 0 0; color:var(--body); font-size:18px; line-height:1.7; word-break:keep-all; }}
    .actions {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:28px; }}
    .button {{ display:inline-flex; align-items:center; justify-content:center; min-height:44px; border-radius:999px; padding:0 18px; background:var(--blue); color:#fff; text-decoration:none; font-weight:780; }}
    .button.secondary {{ background:#eef2f7; color:#222831; }}
    .stats {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin-top:34px; }}
    .stat {{ padding:16px; border:1px solid var(--line); border-radius:8px; background:#fff; }}
    .stat b {{ display:block; font-size:26px; line-height:1; }}
    .stat span {{ display:block; margin-top:8px; color:var(--body); font-size:13px; font-weight:650; }}
    section {{ margin-top:42px; }}
    h2 {{ margin:0 0 14px; font-size:22px; line-height:1.3; }}
    .summary {{ padding:18px; border-radius:8px; background:var(--canvas); color:#353b44; line-height:1.75; word-break:keep-all; }}
    ul {{ margin:0; padding:0; list-style:none; border-top:1px solid var(--line); }}
    li {{ padding:16px 0; border-bottom:1px solid var(--line); }}
    li a {{ display:block; color:var(--ink); text-decoration:none; font-weight:760; line-height:1.45; }}
    li a:hover {{ color:var(--blue); }}
    li span {{ display:block; margin-top:7px; color:var(--body); font-size:13px; line-height:1.5; }}
    .notice {{ margin-top:36px; color:#7a8088; font-size:13px; line-height:1.7; }}
    @media (max-width:640px) {{ main {{ padding-top:28px; }} .stats {{ grid-template-columns:1fr; }} .lead {{ font-size:16px; }} }}
  </style>
</head>
<body>
  <main>
    <a class="brand" href="{_escape(_public_url('/'))}"><span class="mark">?</span><span>지금사도될까요?</span></a>
    <nav class="breadcrumb" aria-label="breadcrumb">
      <a href="{_escape(_public_url('/'))}">홈</a>
      <span aria-hidden="true">/</span>
      <span>{_escape(name)}</span>
    </nav>
    <p class="eyebrow">{_escape(code_label or '종목')} 유튜브 의견 리포트</p>
    <h1>{_escape(name)}<br>지금 사도 될까요?</h1>
    <p class="lead">{_escape(description)} 차트와 가격만 보기 전에, 최근 영상에서 어떤 기대와 우려가 반복됐는지 먼저 훑어볼 수 있습니다.</p>
    <div class="actions">
      <a class="button" href="{_escape(app_url)}">앱에서 실시간 리포트 보기</a>
      <a class="button secondary" href="{_escape(_public_url('/'))}">다른 종목 검색</a>
    </div>
    <div class="stats" aria-label="최근 유튜브 언급 통계">
      <div class="stat"><b>{_escape(stats.get('mentionedVideoCount', 0))}</b><span>최근 언급 영상</span></div>
      <div class="stat"><b>{_escape(stats.get('candidateYoutuberCount', 0))}</b><span>언급 유튜버</span></div>
      <div class="stat"><b>{_escape(latest or '-')}</b><span>최근 확인일</span></div>
    </div>
    <section>
      <h2>{_escape(name)} 요약</h2>
      <p class="summary">최근 {config.SEARCH_LOOKBACK_DAYS}일 검색 인덱스 기준으로 {_escape(name)} 관련 유튜브 언급을 모았습니다. 자세한 긍정·관망·주의 판단과 근거 문장은 앱 리포트에서 최신 상태로 확인할 수 있습니다.</p>
    </section>
    <section>
      <h2>최근 관련 영상</h2>
      <ul>
{video_items}
      </ul>
    </section>
    <p class="notice">이 페이지는 검색엔진이 종목별 리포트를 발견할 수 있도록 만든 색인용 문서입니다. 유튜버의 공개 영상 의견을 요약한 참고 자료이며 투자 권유가 아닙니다.</p>
  </main>
</body>
</html>"""


def _sitemap_lastmod():
    updated_at = stock_search.load_index().get("updatedAt")
    return _format_date(updated_at) or datetime.datetime.now(stock_search.KST).strftime("%Y-%m-%d")


def _sitemap_xml():
    lastmod = _sitemap_lastmod()
    urls = [("/", "1.0")]
    urls.extend((f"/stocks/{quote(row['slug'], safe='')}", "0.8") for row in stock_search.indexable_stock_rows())
    items = "\n".join(
        f"""  <url>
    <loc>{_escape(_public_url(path))}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>daily</changefreq>
    <priority>{priority}</priority>
  </url>"""
        for path, priority in urls
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{items}
</urlset>
"""


def prewarm_popular_async(reason=""):
    """첫 화면 인기주식/등락률 payload를 백그라운드에서 미리 계산한다."""
    if not config.POPULAR_PREWARM_ENABLED:
        return False
    index = stock_search.load_index()
    if not index.get("videos"):
        return False
    index_updated_at = index.get("updatedAt")
    with POPULAR_PREWARM_LOCK:
        if POPULAR_PREWARM_STATE["running"]:
            return False
        if (
                POPULAR_PREWARM_STATE.get("lastStats") is not None and
                POPULAR_PREWARM_STATE.get("lastIndexUpdatedAt") == index_updated_at):
            return False
        POPULAR_PREWARM_STATE.update({
            "running": True,
            "lastStartedAt": datetime.datetime.now(stock_search.KST).isoformat(),
            "lastError": "",
        })

    def worker():
        try:
            why = f" ({reason})" if reason else ""
            print(f"인기주식 홈 캐시를 백그라운드에서 예열합니다{why}.")
            stats = stock_search.warm_popular_stocks_cache(limit=config.POPULAR_PREWARM_MARKET_LIMIT)
            with POPULAR_PREWARM_LOCK:
                POPULAR_PREWARM_STATE["lastStats"] = stats
                POPULAR_PREWARM_STATE["lastIndexUpdatedAt"] = index_updated_at
            print(
                "✅ 인기주식 홈 캐시 예열 완료: "
                f"종목 {stats['rows']}개"
            )
        except Exception as exc:
            with POPULAR_PREWARM_LOCK:
                POPULAR_PREWARM_STATE["lastError"] = str(exc)[:200]
            print(f"⚠️ 인기주식 홈 캐시 예열 실패: {exc}")
        finally:
            with POPULAR_PREWARM_LOCK:
                POPULAR_PREWARM_STATE["running"] = False
                POPULAR_PREWARM_STATE["lastFinishedAt"] = datetime.datetime.now(stock_search.KST).isoformat()
            prewarm_popular_search_results_async(reason=reason or "popular-prewarm")

    threading.Thread(target=worker, daemon=True).start()
    return True


def _popular_search_prewarm_queries(payload, limit):
    markets = payload.get("markets") or {}
    rows_by_market = {
        key: sorted(market.get("rows") or [], key=lambda row: int(row.get("rank") or 9999))
        for key, market in markets.items()
    }
    queries = []
    seen = set()
    max_rows = max((len(rows) for rows in rows_by_market.values()), default=0)
    for idx in range(max_rows):
        for market_key in ("kr", "us"):
            rows = rows_by_market.get(market_key) or []
            if idx >= len(rows):
                continue
            row = rows[idx]
            query = str(row.get("query") or row.get("name") or row.get("code") or "").strip()
            key = stock_search.compact(query)
            if not key or key in seen:
                continue
            seen.add(key)
            queries.append(query)
            if len(queries) >= limit:
                return queries
    return queries


def warm_popular_search_result_cache(payload=None, limit=None):
    """인기종목의 최종 검색 결과를 홈 요청과 분리해서 미리 만든다."""
    index = stock_search.load_index()
    if not index.get("videos"):
        return {"requested": 0, "cached": 0, "skipped": 0, "errors": 0, "indexUpdatedAt": index.get("updatedAt")}
    limit = max(0, int(limit if limit is not None else config.SEARCH_RESULT_PREWARM_LIMIT))
    if not limit:
        return {"requested": 0, "cached": 0, "skipped": 0, "errors": 0, "indexUpdatedAt": index.get("updatedAt")}
    payload = payload or stock_search.popular_stocks(
        limit=max(limit, config.SEARCH_RESULT_PREWARM_LIMIT),
        use_saved=True,
        refresh_quotes=False,
    )
    queries = _popular_search_prewarm_queries(payload, limit)
    stats = {
        "requested": len(queries),
        "cached": 0,
        "skipped": 0,
        "errors": 0,
        "indexUpdatedAt": index.get("updatedAt"),
    }
    for query in queries:
        try:
            cache_key = _search_result_cache_key(query, index.get("updatedAt"))
            if _read_search_result_cache(cache_key):
                stats["cached"] += 1
                continue
            videos, _ = stock_search.find_videos_with_stats(query, include_fallback=False)
            if stock_search.needs_search_fallback(videos):
                stats["skipped"] += 1
                continue
            result = stock_search.search_stock(query, include_fallback=False)
            _write_search_result_cache(query, result)
            stats["cached"] += 1
            delay = max(0, float(config.SEARCH_RESULT_PREWARM_DELAY_SECONDS))
            if delay:
                time.sleep(delay)
        except Exception as exc:
            stats["errors"] += 1
            print(f"⚠️ 인기종목 검색 결과 캐시 예열 실패({query}): {str(exc)[:160]}")
    return stats


def prewarm_popular_search_results_async(reason="", payload=None):
    """인기종목 검색 결과 캐시를 백그라운드에서 예열한다."""
    if not config.SEARCH_RESULT_PREWARM_ENABLED:
        return False
    index = stock_search.load_index()
    if not index.get("videos"):
        return False
    index_updated_at = index.get("updatedAt")
    with SEARCH_RESULT_PREWARM_LOCK:
        if SEARCH_RESULT_PREWARM_STATE["running"]:
            return False
        if (
                SEARCH_RESULT_PREWARM_STATE.get("lastStats") is not None and
                SEARCH_RESULT_PREWARM_STATE.get("lastIndexUpdatedAt") == index_updated_at):
            return False
        SEARCH_RESULT_PREWARM_STATE.update({
            "running": True,
            "lastStartedAt": datetime.datetime.now(stock_search.KST).isoformat(),
            "lastError": "",
        })

    def worker():
        try:
            why = f" ({reason})" if reason else ""
            print(f"인기종목 검색 결과 캐시를 백그라운드에서 예열합니다{why}.")
            stats = warm_popular_search_result_cache(payload=payload)
            with SEARCH_RESULT_PREWARM_LOCK:
                SEARCH_RESULT_PREWARM_STATE["lastStats"] = stats
                SEARCH_RESULT_PREWARM_STATE["lastIndexUpdatedAt"] = index_updated_at
            print(
                "✅ 인기종목 검색 결과 캐시 예열 완료: "
                f"{stats['cached']}개 저장 · {stats['skipped']}개 건너뜀 · 오류 {stats['errors']}개"
            )
        except Exception as exc:
            with SEARCH_RESULT_PREWARM_LOCK:
                SEARCH_RESULT_PREWARM_STATE["lastError"] = str(exc)[:200]
            print(f"⚠️ 인기종목 검색 결과 캐시 예열 실패: {exc}")
        finally:
            with SEARCH_RESULT_PREWARM_LOCK:
                SEARCH_RESULT_PREWARM_STATE["running"] = False
                SEARCH_RESULT_PREWARM_STATE["lastFinishedAt"] = datetime.datetime.now(stock_search.KST).isoformat()

    threading.Thread(target=worker, daemon=True).start()
    return True


def refresh_search_index_async(force=False, reason=""):
    """오래된 검색 인덱스를 서버는 살려둔 채 백그라운드에서 갱신한다."""
    if not force and not config.SEARCH_INDEX_AUTO_REFRESH_ENABLED:
        return False
    index = stock_search.load_index()
    if not force and not _is_search_index_stale(index):
        return False
    if not config.YOUTUBE_API_KEY:
        print("⚠️ 유튜브키가 없어 검색 인덱스를 백그라운드 갱신하지 못해요.")
        return False
    ready = _ready_channels()
    if not ready:
        print("⚠️ 사용 가능한 채널 ID가 없어 검색 인덱스를 갱신하지 못해요.")
        return False

    with SEARCH_REFRESH_LOCK:
        if SEARCH_REFRESH_STATE["running"]:
            return False
        SEARCH_REFRESH_STATE.update({
            "running": True,
            "lastStartedAt": datetime.datetime.now(stock_search.KST).isoformat(),
            "lastError": "",
        })

    def worker():
        refreshed = False
        try:
            why = f" ({reason})" if reason else ""
            print(f"검색 인덱스를 백그라운드에서 갱신합니다{why}.")
            stock_search.sync_index(ready)
            refreshed = True
        except Exception as exc:
            with SEARCH_REFRESH_LOCK:
                SEARCH_REFRESH_STATE["lastError"] = str(exc)[:200]
            print(f"⚠️ 검색 인덱스 백그라운드 갱신 실패: {exc}")
        finally:
            with SEARCH_REFRESH_LOCK:
                SEARCH_REFRESH_STATE["running"] = False
                SEARCH_REFRESH_STATE["lastFinishedAt"] = datetime.datetime.now(stock_search.KST).isoformat()
            if refreshed:
                if not prewarm_popular_async(reason="index-refresh"):
                    prewarm_popular_search_results_async(reason="index-refresh")

    threading.Thread(target=worker, daemon=True).start()
    return True


def _snapshot(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return None
        # JSON 왕복으로 브라우저에 줄 수 있는 안전한 복사본을 만든다.
        payload = json.loads(json.dumps(job["result"], ensure_ascii=False))
    _sort_snapshot_opinions(payload)
    return payload


def _json_copy(payload):
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _search_fingerprint(payload):
    """무거운 내용(의견·리포트)이 바뀌었는지만 감지하는 지문. 진행 카운터는 제외."""
    report = payload.get("report") or {}
    raw = ":".join([
        str(len(payload.get("opinions") or [])),
        str(payload.get("analyzedVideos") or 0),
        str(report.get("generatedAt") or ("1" if report else "")),
        "1" if payload.get("done") else "0",
        "1" if payload.get("fallbackRunning") else "0",
        str(len(payload.get("errors") or [])),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


_PROGRESS_LIGHT_FIELDS = (
    "jobId", "done", "running", "fallbackRunning", "primaryDone",
    "currentChannel", "currentStatus", "processedVideos", "analyzedVideos", "totalVideos",
)


def _watchlist_refresh_signature(items, index_updated_at=""):
    normalized = []
    for raw in (items or [])[:20]:
        item = raw if isinstance(raw, dict) else {}
        query = str(item.get("query") or item.get("label") or item.get("code") or "").strip()
        normalized.append({
            "key": str(item.get("key") or "").strip(),
            "query": stock_search.compact(query),
            "label": stock_search.compact(item.get("label") or ""),
            "code": str(item.get("code") or "").strip().upper(),
            "pending": bool(item.get("pending")),
            "indexUpdatedAt": str(item.get("indexUpdatedAt") or ""),
        })
    raw = json.dumps({
        "indexUpdatedAt": index_updated_at or "",
        "items": normalized,
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _client_key(headers, client_address):
    forwarded = headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    return (client_address or ("unknown",))[0] or "unknown"


def _watchlist_cached_response(client_key, signature):
    now = time.time()
    ttl = max(0, config.WATCHLIST_REFRESH_RESPONSE_CACHE_SECONDS)
    if not ttl:
        return None
    cache_key = (client_key, signature)
    with WATCHLIST_REFRESH_LOCK:
        record = WATCHLIST_REFRESH_RESPONSE_CACHE.get(cache_key)
        if not record:
            return None
        if now - float(record.get("createdAt") or 0) > ttl:
            WATCHLIST_REFRESH_RESPONSE_CACHE.pop(cache_key, None)
            return None
        payload = _json_copy(record["payload"])
    payload["watchlistRefreshCacheHit"] = True
    return payload


def _remember_watchlist_response(client_key, signature, payload):
    ttl = max(0, config.WATCHLIST_REFRESH_RESPONSE_CACHE_SECONDS)
    if not ttl:
        return
    now = time.time()
    cache_key = (client_key, signature)
    with WATCHLIST_REFRESH_LOCK:
        WATCHLIST_REFRESH_RESPONSE_CACHE[cache_key] = {
            "createdAt": now,
            "payload": _json_copy(payload),
        }
        expired = [
            key for key, record in WATCHLIST_REFRESH_RESPONSE_CACHE.items()
            if now - float(record.get("createdAt") or 0) > ttl
        ]
        for key in expired:
            WATCHLIST_REFRESH_RESPONSE_CACHE.pop(key, None)


def _allow_watchlist_refresh(client_key):
    now = time.time()
    window = max(1, config.WATCHLIST_REFRESH_RATE_LIMIT_WINDOW_SECONDS)
    limit = max(1, config.WATCHLIST_REFRESH_RATE_LIMIT_MAX)
    with WATCHLIST_REFRESH_LOCK:
        hits = [
            timestamp for timestamp in WATCHLIST_REFRESH_RATE_LIMIT.get(client_key, [])
            if now - timestamp < window
        ]
        if len(hits) >= limit:
            retry_after = max(1, int(window - (now - hits[0])) + 1)
            WATCHLIST_REFRESH_RATE_LIMIT[client_key] = hits
            return False, retry_after
        hits.append(now)
        WATCHLIST_REFRESH_RATE_LIMIT[client_key] = hits
    return True, 0


def _search_result_cache_identity(query):
    identity = stock_search.stock_identity(query)
    name = identity.get("name") or query.strip()
    return {
        "name": stock_search.compact(name),
        "code": str(identity.get("code") or "").strip().upper(),
        "market": str(identity.get("market") or "").strip().upper(),
    }


def _search_result_cache_key(query, index_updated_at):
    identity = _search_result_cache_identity(query)
    raw = json.dumps({
        "version": SEARCH_RESULT_CACHE_VERSION,
        "stock": identity,
        "indexUpdatedAt": index_updated_at or "",
        "lookbackDays": config.SEARCH_LOOKBACK_DAYS,
        "maxVideosPerChannel": config.SEARCH_MAX_VIDEOS_PER_CHANNEL,
        "maxYoutubers": config.SEARCH_MAX_YOUTUBERS,
        "maxAnalyzedVideos": config.SEARCH_MAX_ANALYZED_VIDEOS,
        "fallbackEnabled": config.SEARCH_FALLBACK_ENABLED,
        "fallbackMinResults": config.SEARCH_FALLBACK_MIN_RESULTS,
        "stockCacheVersion": getattr(stock_search, "_STOCK_CACHE_VERSION", 0),
        "reportCacheVersion": getattr(stock_search, "_REPORT_CACHE_VERSION", 0),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _search_result_cache_path(cache_key):
    return SEARCH_RESULT_CACHE_DIR / f"{cache_key}.json"


def _is_search_result_cache_fresh(record):
    try:
        created_at = float(record.get("createdAt") or 0)
    except (TypeError, ValueError):
        return False
    return time.time() - created_at <= SEARCH_RESULT_CACHE_TTL_SECONDS


def _cached_search_result_payload(payload, cache_key):
    cached = _json_copy(payload)
    cached.update({
        "jobId": f"cache-{cache_key[:12]}",
        "done": True,
        "running": False,
        "fallbackRunning": False,
        "primaryDone": True,
        "currentChannel": "",
        "currentStatus": "캐시된 결과를 바로 보여드려요.",
        "searchCacheHit": True,
    })
    _sort_snapshot_opinions(cached)
    return cached


def _read_search_result_cache(cache_key):
    if config.FORCE_ANALYSIS_REFRESH:
        return None
    with SEARCH_RESULT_CACHE_LOCK:
        record = SEARCH_RESULT_CACHE.get(cache_key)
        if record and _is_search_result_cache_fresh(record):
            return _cached_search_result_payload(record["payload"], cache_key)
        if record:
            SEARCH_RESULT_CACHE.pop(cache_key, None)

    path = _search_result_cache_path(cache_key)
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
            record.get("version") != SEARCH_RESULT_CACHE_VERSION or
            record.get("cacheKey") != cache_key or
            not _is_search_result_cache_fresh(record)):
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict) or not payload.get("done"):
        return None
    with SEARCH_RESULT_CACHE_LOCK:
        SEARCH_RESULT_CACHE[cache_key] = {
            "createdAt": record.get("createdAt"),
            "payload": payload,
        }
        _trim_search_result_cache_locked()
    return _cached_search_result_payload(payload, cache_key)


def _trim_search_result_cache_locked():
    if len(SEARCH_RESULT_CACHE) <= SEARCH_RESULT_CACHE_MAX_ITEMS:
        return
    old_keys = sorted(
        SEARCH_RESULT_CACHE,
        key=lambda key: float(SEARCH_RESULT_CACHE[key].get("createdAt") or 0),
    )[:len(SEARCH_RESULT_CACHE) - SEARCH_RESULT_CACHE_MAX_ITEMS]
    for old_key in old_keys:
        SEARCH_RESULT_CACHE.pop(old_key, None)


def _write_search_result_cache(query, payload):
    if config.FORCE_ANALYSIS_REFRESH or not payload or not payload.get("done"):
        return
    if payload.get("errors") and not payload.get("opinions"):
        return
    cache_key = _search_result_cache_key(query, payload.get("indexUpdatedAt"))
    cached = _json_copy(payload)
    cached.update({
        "jobId": "",
        "done": True,
        "running": False,
        "fallbackRunning": False,
        "primaryDone": True,
        "currentChannel": "",
        "currentStatus": "분석이 끝났어요.",
        "searchCacheHit": False,
    })
    cached.pop("searchCacheStoredAt", None)
    record = {
        "version": SEARCH_RESULT_CACHE_VERSION,
        "cacheKey": cache_key,
        "createdAt": time.time(),
        "payload": cached,
    }
    with SEARCH_RESULT_CACHE_LOCK:
        SEARCH_RESULT_CACHE[cache_key] = {
            "createdAt": record["createdAt"],
            "payload": cached,
        }
        _trim_search_result_cache_locked()
    try:
        SEARCH_RESULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _search_result_cache_path(cache_key).with_suffix(f".{time.monotonic_ns()}.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_search_result_cache_path(cache_key))
    except OSError:
        pass


def _store_search_result_from_job(job_id, query):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        result = job.get("result")
        if not result or not result.get("done") or result.get("running"):
            return
        payload = _json_copy(result)
    _sort_snapshot_opinions(payload)
    _write_search_result_cache(query, payload)


def _sort_snapshot_opinions(payload):
    """진행 중 응답도 최종 응답과 같은 순서로 보여준다."""
    opinions = payload.get("opinions") or []
    for idx, opinion in enumerate(opinions):
        opinion.setdefault("_order", idx)
    opinions.sort(key=stock_search.opinion_sort_key)
    for opinion in opinions:
        opinion.pop("_order", None)


def _trim_jobs():
    if len(JOBS) <= MAX_JOBS:
        return
    old_ids = sorted(JOBS, key=lambda key: JOBS[key].get("startedAt", 0))[:len(JOBS) - MAX_JOBS]
    for old_id in old_ids:
        JOBS.pop(old_id, None)


def _attach_search_report(job_id, will_finalize):
    """검색이 끝나는 시점에 한 번만 쟁점·체크포인트 요약 리포트를 붙인다."""
    if not will_finalize:
        return
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job or job.get("reportDone"):
            return
        job["reportDone"] = True
        result = job["result"]
        result["currentStatus"] = "핵심 쟁점과 체크포인트를 정리하는 중이에요."
        snapshot = _json_copy(result)
    stock_search.sort_opinions(snapshot)
    report = None
    try:
        report = stock_search.summary_report_for(snapshot)
    except Exception as exc:
        print(f"⚠️ 요약 리포트 생성 실패: {str(exc)[:200]}")
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job:
            job["result"]["report"] = report


def _run_search_job(job_id, query, videos, finalize=True):
    with JOBS_LOCK:
        result = JOBS[job_id]["result"]
        result["currentStatus"] = "관련 영상을 고르는 중이에요."

    if not videos:
        with JOBS_LOCK:
            result = JOBS[job_id]["result"]
            result["primaryDone"] = True
            if finalize and not result.get("fallbackRunning"):
                result["done"] = True
                result["running"] = False
            result["currentStatus"] = "최근 영상에서 이 종목 언급을 찾지 못했어요."
        _attach_search_report(job_id, finalize and not result.get("fallbackRunning"))
        _store_search_result_from_job(job_id, query)
        return

    for video in videos:
        with JOBS_LOCK:
            result = JOBS[job_id]["result"]
            generate = result["analyzedVideos"] < config.SEARCH_MAX_ANALYZED_VIDEOS
            result["currentChannel"] = video["channel"]
            result["currentStatus"] = (
                f"{video['channel']} 의견을 분석 중이에요."
                if generate else f"{video['channel']} 캐시를 확인 중이에요."
            )

        try:
            if generate:
                opinion_result, cached = stock_search.analyze_match(video, query)
            else:
                opinion_result, cached = stock_search.cached_match(video, query)
                if not cached:
                    with JOBS_LOCK:
                        JOBS[job_id]["result"]["processedVideos"] += 1
                    continue
            opinion = stock_search.opinion_from_analysis(query, video, opinion_result, cached)
            with JOBS_LOCK:
                result = JOBS[job_id]["result"]
                if generate:
                    result["analyzedVideos"] += 1
                stock_search.add_opinion(result, opinion)
                result["processedVideos"] += 1
        except Exception as exc:
            with JOBS_LOCK:
                result = JOBS[job_id]["result"]
                result["errors"].append(f"{video['channel']}: {str(exc)[:120]}")
                result["processedVideos"] += 1

    with JOBS_LOCK:
        will_finalize = finalize or not JOBS.get(job_id, {}).get("result", {}).get("fallbackRunning")
    _attach_search_report(job_id, will_finalize)
    with JOBS_LOCK:
        result = JOBS[job_id]["result"]
        result["primaryDone"] = True
        if finalize or not result.get("fallbackRunning"):
            result["done"] = True
            result["running"] = False
        result["currentChannel"] = ""
        result["currentStatus"] = "분석이 끝났어요." if result["done"] else "최신 영상을 보강 중이에요."
    _store_search_result_from_job(job_id, query)


def _run_fallback_job(job_id, query, existing_videos):
    try:
        videos = stock_search.fallback_videos(query, existing_videos)
        with JOBS_LOCK:
            result = JOBS[job_id]["result"]
            seen = JOBS[job_id].setdefault("videoIds", {row["videoId"] for row in existing_videos})
            fresh = [row for row in videos if row["videoId"] not in seen]
            for row in fresh:
                seen.add(row["videoId"])
            result["matchedVideos"] += len(fresh)
            result["mentionedVideoCount"] = result["matchedVideos"]
            result["candidateYoutuberCount"] = len({row["channel"] for row in existing_videos + fresh})
            result["shownYoutuberCount"] = min(result["candidateYoutuberCount"], config.SEARCH_MAX_YOUTUBERS)
            result["analysisLimit"] = max(1, min(result["matchedVideos"], config.SEARCH_MAX_ANALYZED_VIDEOS))
            result["currentStatus"] = "최신 영상 보강 결과를 확인 중이에요." if fresh else result.get("currentStatus", "")
        if fresh:
            _run_search_job(job_id, query, fresh, finalize=False)
    except Exception as exc:
        with JOBS_LOCK:
            result = JOBS.get(job_id, {}).get("result")
            if result is not None:
                result["errors"].append(f"최신 영상 보강: {str(exc)[:120]}")
    finally:
        with JOBS_LOCK:
            primary_done = bool(JOBS.get(job_id, {}).get("result", {}).get("primaryDone"))
        _attach_search_report(job_id, primary_done)
        with JOBS_LOCK:
            result = JOBS.get(job_id, {}).get("result")
            if result is not None:
                result["fallbackRunning"] = False
                if result.get("primaryDone"):
                    result["done"] = True
                    result["running"] = False
                result["currentChannel"] = ""
                result["currentStatus"] = (
                    "분석이 끝났어요."
                    if result.get("done")
                    else "기본 후보 의견을 분석 중이에요."
                )
        _store_search_result_from_job(job_id, query)


def _wait_for_first_search_update(job_id, timeout_seconds=1.0):
    """첫 응답이 빈 화면으로 깜빡이지 않도록 짧게만 진행 상황을 기다린다."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with JOBS_LOCK:
            result = JOBS.get(job_id, {}).get("result")
            if not result:
                return
            if (
                    result.get("opinions") or
                    result.get("processedVideos") or
                    (result.get("done") and result.get("primaryDone"))):
                return
        time.sleep(0.05)


def start_search_job(query):
    index = stock_search.load_index()
    cache_key = _search_result_cache_key(query, index.get("updatedAt"))
    cached = _read_search_result_cache(cache_key)
    if cached:
        return cached

    videos, stats = stock_search.find_videos_with_stats(query, include_fallback=False)
    fallback_running = stock_search.needs_search_fallback(videos)
    job_id = uuid.uuid4().hex[:12]
    result = stock_search.base_search_result(query, videos, stats)
    result.update({
        "jobId": job_id,
        "done": False,
        "running": True,
        "fallbackRunning": fallback_running,
        "primaryDone": False,
        "currentChannel": "",
        "currentStatus": "검색을 시작했어요.",
    })
    with JOBS_LOCK:
        JOBS[job_id] = {
            "startedAt": time.time(),
            "result": result,
            "videoIds": {row["videoId"] for row in videos},
        }
        _trim_jobs()
    thread = threading.Thread(target=_run_search_job, args=(job_id, query, videos, not fallback_running), daemon=True)
    thread.start()
    if fallback_running:
        fallback_thread = threading.Thread(target=_run_fallback_job, args=(job_id, query, videos), daemon=True)
        fallback_thread.start()
    _wait_for_first_search_update(job_id)
    return _snapshot(job_id)


def refresh_watchlist_items(items):
    index = stock_search.load_index()
    index_updated_at = index.get("updatedAt") or ""
    results = []
    for raw in (items or [])[:20]:
        item = raw if isinstance(raw, dict) else {}
        key = str(item.get("key") or "").strip()
        query = str(item.get("query") or item.get("label") or item.get("code") or "").strip()
        if len(query) < 2:
            results.append({
                "key": key,
                "query": query,
                "status": "failed",
                "error": "검색어가 부족해요.",
            })
            continue
        if (
                not item.get("pending") and
                str(item.get("indexUpdatedAt") or "") == index_updated_at):
            results.append({
                "key": key,
                "query": query,
                "status": "fresh",
                "indexUpdatedAt": index_updated_at,
            })
            continue
        try:
            cache_key = _search_result_cache_key(query, index_updated_at)
            cached = _read_search_result_cache(cache_key)
            if cached:
                results.append({
                    "key": key,
                    "query": query,
                    "status": "cached",
                    "data": cached,
                    "indexUpdatedAt": index_updated_at,
                })
                continue
            try:
                result = stock_search.search_stock(query, include_fallback=False)
            except Exception:
                # 관심종목 새로고침은 평소엔 빠른 경로를 우선 쓰고,
                # 그 경로에서 실패한 종목만 fallback 검색까지 허용한다.
                result = stock_search.search_stock(query, include_fallback=True)
            _write_search_result_cache(query, result)
            results.append({
                "key": key,
                "query": query,
                "status": "done",
                "data": result,
                "indexUpdatedAt": result.get("indexUpdatedAt") or index_updated_at,
            })
        except Exception as exc:
            results.append({
                "key": key,
                "query": query,
                "status": "failed",
                "error": str(exc)[:200],
            })
    return {
        "indexUpdatedAt": index_updated_at,
        "results": results,
    }


def _websocket_accept_key(key):
    raw = (key.strip() + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
    return base64.b64encode(hashlib.sha1(raw).digest()).decode("ascii")


def _websocket_frame(payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    length = len(body)
    header = bytearray([0x81])
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))
    return bytes(header) + body


def _quote_signature(quote):
    if not quote:
        return None
    return (
        quote.get("price"),
        quote.get("priceText"),
        quote.get("change"),
        quote.get("changeRate"),
        quote.get("changeRateText"),
        quote.get("changeDirection"),
        quote.get("priceBaseDate"),
        quote.get("quoteSource"),
        quote.get("quoteDelayText"),
    )


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"[검색 서버] {fmt % args}")

    def _accepts_gzip(self):
        return "gzip" in (self.headers.get("Accept-Encoding") or "").lower()

    def _send_body(self, body, content_type, status=200, cache="no-store", cors=False,
                   headers=None, head_only=False, use_etag=False):
        """모든 응답의 공통 출구. gzip 압축 + ETag 304로 발신 트래픽을 줄인다."""
        etag = None
        if use_etag and status == 200:
            etag = f'"{hashlib.md5(body).hexdigest()}"'
            if (self.headers.get("If-None-Match") or "").strip() == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", cache)
                self.send_header("Vary", "Accept-Encoding")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        encoded = body
        gzipped = False
        if not head_only and len(body) >= 512 and self._accepts_gzip():
            candidate = gzip.compress(body, 6)
            if len(candidate) < len(body):
                encoded = candidate
                gzipped = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", cache)
        self.send_header("Vary", "Accept-Encoding")
        if gzipped:
            self.send_header("Content-Encoding", "gzip")
        if etag:
            self.send_header("ETag", etag)
        if cors:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        for name, value in (headers or {}).items():
            self.send_header(name, str(value))
        self.end_headers()
        if not head_only:
            self.wfile.write(encoded)

    def _json(self, payload, status=200, cors=False, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_body(body, "application/json; charset=utf-8", status=status, cors=cors, headers=headers)

    def _text(self, text, content_type="text/plain; charset=utf-8", status=200, head_only=False, cache="no-store"):
        self._send_body(
            text.encode("utf-8"), content_type, status=status, cache=cache,
            head_only=head_only, use_etag=cache != "no-store",
        )

    def _file(self, path, cache="no-store"):
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        content_type = f"{mime}; charset=utf-8" if mime.startswith("text/") else mime
        self._send_body(body, content_type, cache=cache, use_etag=cache != "no-store")

    def _html(self, parsed=None):
        if not APP_HTML.exists() or not APP_HTML.is_file():
            self.send_error(404)
            return
        html = APP_HTML.read_text(encoding="utf-8")
        if parsed:
            params = parse_qs(parsed.query)
            if (params.get("tab") or [""])[0] == "report":
                html = _replace_app_share_meta(html, _app_report_share_meta((params.get("q") or [""])[0]))
        try:
            payload = stock_search.popular_stocks(refresh_quotes=False)
            payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
            snippet = f"<script>window.__INITIAL_POPULAR_STOCKS__={payload_json};</script>"
            html = html.replace("</head>", f"{snippet}\n</head>", 1)
        except Exception as exc:
            print(f"[검색 서버] 초기 인기주식 주입 실패: {exc}")
        body = html.encode("utf-8")
        self._send_body(body, "text/html; charset=utf-8", cache="public, max-age=60", use_etag=True)

    def _file_head(self, path):
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8" if mime.startswith("text/") else mime)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_HEAD(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/stock-search.html"):
            self._file_head(APP_HTML)
            return
        if parsed.path.startswith("/stocks/"):
            stock = stock_search.stock_by_slug(unquote(parsed.path.removeprefix("/stocks/")))
            if not stock:
                self.send_error(404)
                return
            self._text(_stock_page_html(stock), "text/html; charset=utf-8", head_only=True)
            return
        if parsed.path == "/robots.txt":
            self._file_head(ROBOTS_TXT)
            return
        if parsed.path == "/sitemap.xml":
            self._text(_sitemap_xml(), "application/xml; charset=utf-8", head_only=True)
            return
        if parsed.path == "/google661da6d73ff97f8e.html":
            self._file_head(GOOGLE_VERIFICATION_HTML)
            return
        if parsed.path.startswith("/assets/"):
            path = (APP_ASSETS / parsed.path.removeprefix("/assets/")).resolve()
            if APP_ASSETS.resolve() in path.parents:
                self._file_head(path)
                return
        if parsed.path == "/mvp-dashboard.html":
            self._file_head(DASHBOARD_HTML)
            return
        self.send_error(404)

    def do_OPTIONS(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/api/analytics/event", "/api/dashboard/metrics"):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "86400")
            self.end_headers()
            return
        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/analytics/event":
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 8192)
                body = self.rfile.read(length).decode("utf-8") if length else "{}"
                payload = json.loads(body or "{}")
                analytics.record_event(payload)
                self._json({"ok": True}, cors=True)
            except Exception as exc:
                self._json({"ok": False, "error": str(exc)[:200]}, 400, cors=True)
            return
        if parsed.path == "/api/watchlist/refresh":
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 65536)
                body = self.rfile.read(length).decode("utf-8") if length else "{}"
                payload = json.loads(body or "{}")
                items = payload.get("items") if isinstance(payload, dict) else []
                client_key = _client_key(self.headers, self.client_address)
                index_updated_at = stock_search.load_index().get("updatedAt") or ""
                signature = _watchlist_refresh_signature(items, index_updated_at)
                cached = _watchlist_cached_response(client_key, signature)
                if cached:
                    self._json(cached)
                    return
                allowed, retry_after = _allow_watchlist_refresh(client_key)
                if not allowed:
                    self._json({
                        "error": f"방금 확인했어요. {retry_after}초 뒤에 다시 시도해 주세요.",
                        "retryAfter": retry_after,
                    }, 429, headers={"Retry-After": retry_after})
                    return
                response = refresh_watchlist_items(items)
                _remember_watchlist_response(client_key, signature, response)
                self._json(response)
            except Exception as exc:
                self._json({"error": str(exc)[:200]}, 400)
            return
        self.send_error(404)

    def _popular_stock_quotes_ws(self, parsed):
        if self.headers.get("Upgrade", "").lower() != "websocket":
            self.send_error(400, "WebSocket upgrade required")
            return
        key = self.headers.get("Sec-WebSocket-Key", "")
        if not key:
            self.send_error(400, "Missing Sec-WebSocket-Key")
            return
        params = parse_qs(parsed.query)
        market = params.get("market", [""])[0]
        codes = []
        for value in params.get("codes", []):
            codes.extend(part for part in value.split(",") if part.strip())
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", _websocket_accept_key(key))
        self.end_headers()

        previous = {}
        while True:
            payload = stock_search.popular_stock_quotes(market, codes)
            quotes = payload.get("quotes") or {}
            changed_quotes = {
                code: quote
                for code, quote in quotes.items()
                if _quote_signature(quote) != previous.get(code)
            }
            previous.update({code: _quote_signature(quote) for code, quote in changed_quotes.items()})
            payload["type"] = "quotes" if changed_quotes else "heartbeat"
            payload["quotes"] = changed_quotes
            self.wfile.write(_websocket_frame(payload))
            self.wfile.flush()
            time.sleep(QUOTE_WS_INTERVAL_SECONDS)

    def _proxy_maesu(self):
        upstream_path = self.path[len("/maesu"):] or "/"
        connection = http.client.HTTPConnection("127.0.0.1", 8001, timeout=120)
        try:
            connection.request("GET", upstream_path)
            response = connection.getresponse()
            body = response.read()
            content_type = response.getheader("Content-Type") or "application/json; charset=utf-8"
            self._send_body(body, content_type, status=response.status, cors=True)
        except (OSError, TimeoutError) as exc:
            self._json({"error": f"가격 추정 API를 연결하지 못했어요: {exc}"}, 503, cors=True)
        finally:
            connection.close()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/maesu" or parsed.path.startswith("/maesu/"):
            self._proxy_maesu()
            return
        if parsed.path == "/ws/popular-stock-quotes":
            try:
                self._popular_stock_quotes_ws(parsed)
            except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
                pass
            except Exception as exc:
                print(f"[검색 서버] 실시간 시세 스트림 오류: {exc}")
            return
        if parsed.path == "/api/dashboard/metrics":
            try:
                days = parse_qs(parsed.query).get("days", ["7"])[0]
                self._json(analytics.dashboard_metrics(days=days), cors=True)
            except Exception as exc:
                self._json({"error": str(exc)}, 500, cors=True)
            return
        if parsed.path == "/api/status":
            index = stock_search.load_index()
            refresh_search_index_async(reason="status")
            provider = config.ANALYSIS_PROVIDER.lower()
            model = config.OPENROUTER_MODEL if provider == "openrouter" else config.OLLAMA_MODEL
            self._json({
                "ready": bool(index.get("videos")),
                "indexVersion": index.get("version"),
                "videoCount": len(index.get("videos", [])),
                "updatedAt": index.get("updatedAt"),
                "lookbackDays": index.get("lookbackDays", config.SEARCH_LOOKBACK_DAYS),
                "maxVideosPerChannel": index.get("maxVideosPerChannel"),
                "analysisProvider": provider,
                "model": model,
                "searchRefresh": search_refresh_status(index),
                "popularPrewarm": popular_prewarm_status(),
                "searchResultPrewarm": search_result_prewarm_status(),
                "stockMaster": krx_listed.cache_status(),
                "usStockMaster": us_listed.cache_status(),
            })
            return
        if parsed.path == "/api/stocks/status":
            self._json({
                "krx": krx_listed.cache_status(),
                "us": us_listed.cache_status(),
            })
            return
        if parsed.path == "/api/us-stocks/status":
            self._json(us_listed.cache_status())
            return
        if parsed.path == "/api/chips":
            query = parse_qs(parsed.query).get("q", [""])[0].strip()
            if query:
                self._json({
                    "label": "함께 언급된 종목",
                    "chips": stock_search.related_chips(query),
                })
            else:
                self._json({
                    "label": "최근 많이 언급된 종목",
                    "chips": stock_search.popular_chips(),
                })
            return
        if parsed.path == "/api/popular-stocks":
            try:
                self._json(stock_search.popular_stocks(refresh_quotes=False))
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return
        if parsed.path == "/api/popular-stock-quotes":
            params = parse_qs(parsed.query)
            market = params.get("market", [""])[0]
            codes = []
            for value in params.get("codes", []):
                codes.extend(part for part in value.split(",") if part.strip())
            try:
                self._json(stock_search.popular_stock_quotes(market, codes))
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return
        if parsed.path == "/api/youtuber-history":
            params = parse_qs(parsed.query)
            query = params.get("stock", [""])[0].strip()
            channel_id = params.get("channelId", [""])[0].strip()
            channel_name = params.get("channelName", [""])[0].strip()
            period_days = params.get("periodDays", [""])[0].strip()
            if not query or not (channel_id or channel_name):
                self._json({"error": "stock과 channelId 또는 channelName이 필요해요."}, 400)
                return
            try:
                self._json(stock_search.youtuber_history_detail(
                    query,
                    channel_id=channel_id,
                    channel_name=channel_name,
                    period_days=int(period_days) if period_days else None,
                ))
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return
        if parsed.path == "/api/market-rankings":
            try:
                force = parse_qs(parsed.query).get("force", [""])[0] in ("1", "true", "yes")
                self._json(market_rankings.rankings(force=force))
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return
        if parsed.path == "/api/search":
            query = parse_qs(parsed.query).get("q", [""])[0].strip()
            if len(query) < 2:
                self._json({"error": "종목명을 두 글자 이상 입력해 주세요."}, 400)
                return
            try:
                refresh_search_index_async(reason="search")
                self._json(stock_search.search_stock(query))
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return
        if parsed.path == "/api/search/start":
            query = parse_qs(parsed.query).get("q", [""])[0].strip()
            if len(query) < 2:
                self._json({"error": "종목명을 두 글자 이상 입력해 주세요."}, 400)
                return
            try:
                refresh_search_index_async(reason="search/start")
                self._json(start_search_job(query))
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return
        if parsed.path == "/api/search/progress":
            params = parse_qs(parsed.query)
            job_id = params.get("id", [""])[0].strip()
            client_fp = params.get("fp", [""])[0].strip()
            payload = _snapshot(job_id)
            if not payload:
                self._json({"error": "검색 작업을 찾지 못했어요."}, 404)
                return
            fp = _search_fingerprint(payload)
            payload["fp"] = fp
            if client_fp and client_fp == fp and not payload.get("done"):
                # 의견·리포트가 그대로면 상태 필드만 얇게 보낸다 (대역폭 절약).
                light = {key: payload.get(key) for key in _PROGRESS_LIGHT_FIELDS}
                light.update({"unchanged": True, "fp": fp})
                self._json(light)
                return
            self._json(payload)
            return
        if parsed.path == "/api/suggest":
            query = parse_qs(parsed.query).get("q", [""])[0].strip()
            if not query:
                self._json({"suggestions": []})
                return
            self._json({"suggestions": stock_search.suggest_stocks(query)})
            return
        if parsed.path in ("/", "/stock-search.html"):
            self._html(parsed)
            return
        if parsed.path.startswith("/stocks/"):
            stock = stock_search.stock_by_slug(unquote(parsed.path.removeprefix("/stocks/")))
            if not stock:
                self.send_error(404)
                return
            self._text(_stock_page_html(stock), "text/html; charset=utf-8", cache="public, max-age=300")
            return
        if parsed.path == "/robots.txt":
            self._file(ROBOTS_TXT, cache="public, max-age=3600")
            return
        if parsed.path == "/sitemap.xml":
            self._text(_sitemap_xml(), "application/xml; charset=utf-8", cache="public, max-age=3600")
            return
        if parsed.path == "/google661da6d73ff97f8e.html":
            self._file(GOOGLE_VERIFICATION_HTML, cache="public, max-age=3600")
            return
        if parsed.path.startswith("/assets/"):
            path = (APP_ASSETS / parsed.path.removeprefix("/assets/")).resolve()
            if APP_ASSETS.resolve() in path.parents:
                self._file(path, cache="public, max-age=86400")
                return
        if parsed.path == "/mvp-dashboard.html":
            self._file(DASHBOARD_HTML)
            return
        self.send_error(404)


def main():
    index = stock_search.load_index()
    if not index.get("videos"):
        print("⚠️ 검색 인덱스가 없어 빈 상태로 서버를 먼저 시작합니다.")
    elif _is_search_index_stale(index):
        print("⚠️ 검색 인덱스가 오래되어 기존 데이터로 서버를 먼저 시작합니다.")
    if config.STARTUP_SEARCH_REFRESH_ENABLED:
        refresh_search_index_async(reason="startup")
    if not prewarm_popular_async(reason="startup"):
        prewarm_popular_search_results_async(reason="startup")
    if config.STARTUP_STOCK_REFRESH_ENABLED:
        krx_listed.refresh_if_needed_async()
        us_listed.refresh_if_needed_async()
    else:
        print("시작 시 자동 종목정보 갱신은 꺼져 있어요. seed 캐시를 사용합니다.")
    if not config.STARTUP_SEARCH_REFRESH_ENABLED:
        print("시작 시 자동 검색 인덱스 갱신은 꺼져 있어요. seed 캐시를 사용합니다.")
    try:
        server = SearchServer((HOST, PORT), Handler)
    except OSError as exc:
        print(f"❌ 검색 서버를 시작하지 못했어요: {exc}")
        print(f"   이미 실행 중이라면 http://{PUBLIC_HOST}:{PORT} 를 열어보세요.")
        return 1
    if HOST == "0.0.0.0":
        print(f"✅ 종목 검색 서버")
        print(f"   맥에서 보기: http://127.0.0.1:{PORT}")
        print(f"   휴대폰에서 보기: http://{PUBLIC_HOST}:{PORT}")
        print("   ※ 맥과 휴대폰이 같은 와이파이에 있어야 합니다.")
    else:
        print(f"✅ 종목 검색 서버: http://{HOST}:{PORT}")
    print("   이 창을 닫으면 검색 서비스도 종료됩니다.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
