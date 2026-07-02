#!/usr/bin/env python3
"""종목 검색 화면과 로컬 검색 API를 제공한다."""
import datetime
import json
import mimetypes
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
JOBS = {}
JOBS_LOCK = threading.Lock()
MAX_JOBS = 20
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
                prewarm_popular_async(reason="index-refresh")

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
            opinion = stock_search.opinion_from_result(video, opinion_result, cached)
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
        result = JOBS[job_id]["result"]
        result["primaryDone"] = True
        if finalize or not result.get("fallbackRunning"):
            result["done"] = True
            result["running"] = False
        result["currentChannel"] = ""
        result["currentStatus"] = "분석이 끝났어요." if result["done"] else "최신 영상을 보강 중이에요."


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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[검색 서버] {fmt % args}")

    def _json(self, payload, status=200, cors=False):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cors:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path):
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8" if mime.startswith("text/") else mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

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
        if parsed.path == "/robots.txt":
            self._file_head(ROBOTS_TXT)
            return
        if parsed.path == "/sitemap.xml":
            self._file_head(SITEMAP_XML)
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
        self.send_error(404)

    def do_GET(self):
        parsed = urlparse(self.path)
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
                self._json(stock_search.popular_stocks())
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
            job_id = parse_qs(parsed.query).get("id", [""])[0].strip()
            payload = _snapshot(job_id)
            if not payload:
                self._json({"error": "검색 작업을 찾지 못했어요."}, 404)
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
            self._file(APP_HTML)
            return
        if parsed.path == "/robots.txt":
            self._file(ROBOTS_TXT)
            return
        if parsed.path == "/sitemap.xml":
            self._file(SITEMAP_XML)
            return
        if parsed.path == "/google661da6d73ff97f8e.html":
            self._file(GOOGLE_VERIFICATION_HTML)
            return
        if parsed.path.startswith("/assets/"):
            path = (APP_ASSETS / parsed.path.removeprefix("/assets/")).resolve()
            if APP_ASSETS.resolve() in path.parents:
                self._file(path)
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
    prewarm_popular_async(reason="startup")
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
