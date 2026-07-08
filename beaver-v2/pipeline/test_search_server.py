import json
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import search_server
import stock_search


class SearchServerJobTest(unittest.TestCase):
    def tearDown(self):
        with search_server.JOBS_LOCK:
            search_server.JOBS.clear()
        with search_server.SEARCH_RESULT_CACHE_LOCK:
            search_server.SEARCH_RESULT_CACHE.clear()
        with search_server.WATCHLIST_REFRESH_LOCK:
            search_server.WATCHLIST_REFRESH_RATE_LIMIT.clear()
            search_server.WATCHLIST_REFRESH_RESPONSE_CACHE.clear()

    def test_fallback_finishing_first_does_not_complete_primary_job(self):
        video = {
            "videoId": "v1",
            "channel": "815머니톡",
            "title": "LG CNS 데이터센터 수혜",
            "publishedAt": "2026-06-27T20:00:27+09:00",
            "views": 1000,
            "url": "https://www.youtube.com/watch?v=v1",
            "_text": "LG CNS도 데이터센터 수혜를 봅니다.",
        }
        job_id = "job-lg-cns"
        result = stock_search.base_search_result("LG CNS", [video])
        result.update({
            "jobId": job_id,
            "done": False,
            "running": True,
            "fallbackRunning": True,
            "primaryDone": False,
            "currentChannel": "",
            "currentStatus": "검색을 시작했어요.",
        })
        with search_server.JOBS_LOCK:
            search_server.JOBS[job_id] = {
                "startedAt": 0,
                "result": result,
                "videoIds": {video["videoId"]},
            }

        with mock.patch("stock_search.fallback_videos", return_value=[]):
            search_server._run_fallback_job(job_id, "LG CNS", [video])

        snapshot = search_server._snapshot(job_id)
        self.assertFalse(snapshot["done"])
        self.assertTrue(snapshot["running"])
        self.assertFalse(snapshot["fallbackRunning"])
        self.assertEqual(snapshot["processedVideos"], 0)

        analysis = {
            "mentioned": True,
            "stance": "긍정",
            "summary": "LG CNS는 데이터센터 수혜가 기대됩니다.",
            "evidence": "데이터센터 수혜를 봅니다.",
            "sourceTimeSec": 0,
        }
        with mock.patch("stock_search.analyze_match", return_value=(analysis, False)):
            search_server._run_search_job(job_id, "LG CNS", [video], finalize=False)

        snapshot = search_server._snapshot(job_id)
        self.assertTrue(snapshot["done"])
        self.assertFalse(snapshot["running"])
        self.assertEqual(snapshot["processedVideos"], 1)
        self.assertEqual(len(snapshot["opinions"]), 1)

    def test_empty_primary_job_attaches_null_report_before_cache(self):
        job_id = "job-empty"
        result = stock_search.base_search_result("없는종목", [], {
            "mentionedVideoCount": 0,
            "candidateYoutuberCount": 0,
            "shownYoutuberCount": 0,
        })
        result.update({
            "jobId": job_id,
            "done": False,
            "running": True,
            "fallbackRunning": False,
            "primaryDone": False,
            "currentChannel": "",
            "currentStatus": "검색을 시작했어요.",
        })
        with search_server.JOBS_LOCK:
            search_server.JOBS[job_id] = {
                "startedAt": 0,
                "result": result,
                "videoIds": set(),
            }

        with mock.patch("stock_search.summary_report_for", return_value=None) as summary_report, \
                mock.patch("search_server._write_search_result_cache") as write_cache:
            search_server._run_search_job(job_id, "없는종목", [], finalize=True)

        snapshot = search_server._snapshot(job_id)
        summary_report.assert_called_once()
        self.assertIn("report", snapshot)
        self.assertIsNone(snapshot["report"])
        write_cache.assert_called_once()

    def test_completed_search_result_is_returned_from_cache(self):
        stock = {"name": "삼성전자", "code": "005930", "market": "KOSPI", "aliases": ["삼전"]}
        video = {
            "videoId": "v1",
            "channel": "테스트채널",
            "title": "삼성전자 실적 전망",
            "publishedAt": "2026-07-04T10:00:00+09:00",
            "views": 1234,
            "url": "https://www.youtube.com/watch?v=v1",
        }
        payload = stock_search.base_search_result("삼성전자", [video], {
            "mentionedVideoCount": 1,
            "candidateYoutuberCount": 1,
            "shownYoutuberCount": 1,
        })
        payload.update({
            "jobId": "job-first",
            "done": True,
            "running": False,
            "fallbackRunning": False,
            "primaryDone": True,
            "currentChannel": "",
            "currentStatus": "분석이 끝났어요.",
        })
        stock_search.add_opinion(payload, {
            "channel": "테스트채널",
            "title": "삼성전자 실적 전망",
            "publishedAt": "2026-07-04T10:00:00+09:00",
            "views": 1234,
            "url": "https://www.youtube.com/watch?v=v1",
            "stance": "긍정",
            "summary": "삼성전자 실적 개선을 긍정적으로 봅니다.",
            "evidence": "실적 전망을 근거로 들었습니다.",
            "reportable": True,
        })
        index = {
            "version": stock_search._SEARCH_INDEX_VERSION,
            "updatedAt": payload["indexUpdatedAt"],
            "videos": [video],
        }

        with tempfile.TemporaryDirectory() as tmpdir, \
                mock.patch.object(search_server, "SEARCH_RESULT_CACHE_DIR", Path(tmpdir)), \
                mock.patch("stock_search.stock_master", return_value=[stock]), \
                mock.patch("stock_search.load_index", return_value=index):
            search_server._write_search_result_cache("삼성전자", payload)
            with search_server.SEARCH_RESULT_CACHE_LOCK:
                search_server.SEARCH_RESULT_CACHE.clear()

            with mock.patch("stock_search.find_videos_with_stats") as find_videos:
                cached = search_server.start_search_job("삼성전자")

        find_videos.assert_not_called()
        self.assertTrue(cached["done"])
        self.assertFalse(cached["running"])
        self.assertTrue(cached["searchCacheHit"])
        self.assertTrue(cached["jobId"].startswith("cache-"))
        self.assertEqual(cached["opinions"][0]["summary"], "삼성전자 실적 개선을 긍정적으로 봅니다.")

    def test_popular_search_prewarm_interleaves_markets(self):
        payload = {
            "markets": {
                "kr": {"rows": [
                    {"rank": 1, "query": "삼성전자"},
                    {"rank": 2, "query": "SK하이닉스"},
                    {"rank": 3, "query": "현대차"},
                ]},
                "us": {"rows": [
                    {"rank": 1, "query": "엔비디아"},
                    {"rank": 2, "query": "테슬라"},
                ]},
            }
        }

        queries = search_server._popular_search_prewarm_queries(payload, 5)

        self.assertEqual(queries, ["삼성전자", "엔비디아", "SK하이닉스", "테슬라", "현대차"])

    def test_popular_search_prewarm_skips_fallback_needed_queries(self):
        video = {
            "videoId": "v1",
            "channel": "테스트채널",
            "title": "삼성전자 실적 전망",
            "publishedAt": "2026-07-04T10:00:00+09:00",
            "views": 1234,
            "url": "https://www.youtube.com/watch?v=v1",
        }
        payload = {
            "markets": {
                "kr": {"rows": [{"rank": 1, "query": "삼성전자"}]},
                "us": {"rows": [{"rank": 1, "query": "엔비디아"}]},
            }
        }
        result = stock_search.base_search_result("삼성전자", [video], {
            "mentionedVideoCount": 1,
            "candidateYoutuberCount": 1,
            "shownYoutuberCount": 1,
        })
        result["done"] = True

        with mock.patch("stock_search.load_index", return_value={
                "version": stock_search._SEARCH_INDEX_VERSION,
                "updatedAt": "2026-07-05T09:00:00+09:00",
                "videos": [video],
        }), \
                mock.patch("search_server._read_search_result_cache", return_value=None), \
                mock.patch("stock_search.find_videos_with_stats", side_effect=[([video], {}), ([], {})]), \
                mock.patch("stock_search.needs_search_fallback", side_effect=[False, True]), \
                mock.patch("stock_search.search_stock", return_value=result) as search_stock, \
                mock.patch("search_server._write_search_result_cache") as write_cache, \
                mock.patch.object(search_server.config, "SEARCH_RESULT_PREWARM_DELAY_SECONDS", 0):
            stats = search_server.warm_popular_search_result_cache(payload=payload, limit=2)

        search_stock.assert_called_once_with("삼성전자", include_fallback=False)
        write_cache.assert_called_once_with("삼성전자", result)
        self.assertEqual(stats["requested"], 2)
        self.assertEqual(stats["cached"], 1)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["errors"], 0)

    def test_watchlist_refresh_skips_fresh_items(self):
        with mock.patch("stock_search.load_index", return_value={
                "version": stock_search._SEARCH_INDEX_VERSION,
                "updatedAt": "2026-07-05T09:00:00+09:00",
                "videos": [{"videoId": "v1"}],
        }), mock.patch("stock_search.search_stock") as search_stock:
            payload = search_server.refresh_watchlist_items([{
                "key": "005930",
                "query": "삼성전자",
                "indexUpdatedAt": "2026-07-05T09:00:00+09:00",
            }])

        search_stock.assert_not_called()
        self.assertEqual(payload["results"][0]["status"], "fresh")
        self.assertEqual(payload["results"][0]["indexUpdatedAt"], "2026-07-05T09:00:00+09:00")

    def test_watchlist_refresh_uses_fast_search_without_fallback(self):
        video = {
            "videoId": "v1",
            "channel": "테스트채널",
            "title": "삼성전자 실적 전망",
            "publishedAt": "2026-07-04T10:00:00+09:00",
            "views": 1234,
            "url": "https://www.youtube.com/watch?v=v1",
        }
        result = stock_search.base_search_result("삼성전자", [video], {
            "mentionedVideoCount": 1,
            "candidateYoutuberCount": 1,
            "shownYoutuberCount": 1,
        })
        result["done"] = True

        with mock.patch("stock_search.load_index", return_value={
                "version": stock_search._SEARCH_INDEX_VERSION,
                "updatedAt": "2026-07-05T09:00:00+09:00",
                "videos": [video],
        }), \
                mock.patch("search_server._read_search_result_cache", return_value=None), \
                mock.patch("stock_search.search_stock", return_value=result) as search_stock, \
                mock.patch("search_server._write_search_result_cache") as write_cache:
            payload = search_server.refresh_watchlist_items([{
                "key": "005930",
                "query": "삼성전자",
                "indexUpdatedAt": "old-index",
            }])

        search_stock.assert_called_once_with("삼성전자", include_fallback=False)
        write_cache.assert_called_once_with("삼성전자", result)
        self.assertEqual(payload["results"][0]["status"], "done")
        self.assertEqual(payload["results"][0]["data"]["query"], "삼성전자")

    def test_watchlist_refresh_retries_with_fallback_after_fast_search_failure(self):
        result = {"query": "삼성전자", "done": True, "opinions": []}

        with mock.patch("stock_search.load_index", return_value={
                "version": stock_search._SEARCH_INDEX_VERSION,
                "updatedAt": "2026-07-05T09:00:00+09:00",
                "videos": [],
        }), \
                mock.patch("search_server._read_search_result_cache", return_value=None), \
                mock.patch("stock_search.search_stock", side_effect=[
                    RuntimeError("fast path failed"),
                    result,
                ]) as search_stock, \
                mock.patch("search_server._write_search_result_cache") as write_cache:
            payload = search_server.refresh_watchlist_items([{
                "key": "005930",
                "query": "삼성전자",
                "indexUpdatedAt": "old-index",
            }])

        self.assertEqual(search_stock.call_args_list, [
            mock.call("삼성전자", include_fallback=False),
            mock.call("삼성전자", include_fallback=True),
        ])
        write_cache.assert_called_once_with("삼성전자", result)
        self.assertEqual(payload["results"][0]["status"], "done")
        self.assertEqual(payload["results"][0]["data"]["query"], "삼성전자")

    def test_watchlist_refresh_rate_limit_blocks_excess_requests(self):
        with mock.patch.object(search_server.config, "WATCHLIST_REFRESH_RATE_LIMIT_WINDOW_SECONDS", 60), \
                mock.patch.object(search_server.config, "WATCHLIST_REFRESH_RATE_LIMIT_MAX", 2), \
                mock.patch("search_server.time.time", return_value=1000):
            self.assertEqual(search_server._allow_watchlist_refresh("1.2.3.4"), (True, 0))
            self.assertEqual(search_server._allow_watchlist_refresh("1.2.3.4"), (True, 0))
            allowed, retry_after = search_server._allow_watchlist_refresh("1.2.3.4")

        self.assertFalse(allowed)
        self.assertEqual(retry_after, 61)

    def test_watchlist_refresh_response_cache_reuses_identical_payload(self):
        payload = {"indexUpdatedAt": "idx", "results": [{"key": "005930", "status": "fresh"}]}
        items = [{"key": "005930", "query": "삼성전자", "indexUpdatedAt": "idx"}]
        signature = search_server._watchlist_refresh_signature(items, "idx")

        with mock.patch.object(search_server.config, "WATCHLIST_REFRESH_RESPONSE_CACHE_SECONDS", 30), \
                mock.patch("search_server.time.time", return_value=1000):
            search_server._remember_watchlist_response("1.2.3.4", signature, payload)
            cached = search_server._watchlist_cached_response("1.2.3.4", signature)

        self.assertTrue(cached["watchlistRefreshCacheHit"])
        self.assertEqual(cached["results"][0]["key"], "005930")


class SearchServerSeoTest(unittest.TestCase):
    def test_app_report_share_meta_uses_stock_report_title(self):
        stock = {"name": "현대차", "code": "005380", "market": "KOSPI", "aliases": ["현대자동차"]}
        with mock.patch("stock_search.stock_master", return_value=[stock]):
            base_html = """<!doctype html>
<html lang="ko">
<head>
  <title>지금사도될까요? | 주식 유튜브 의견 요약 리포트</title>
  <meta name="description" content="기본 설명">
  <meta property="og:title" content="기본 제목">
  <meta property="og:description" content="기본 OG 설명">
  <meta property="og:url" content="https://stockzip.kr/">
  <link rel="canonical" href="https://stockzip.kr/">
  <meta name="twitter:title" content="기본 트위터 제목">
  <meta name="twitter:description" content="기본 트위터 설명">
</head>
<body></body>
</html>"""
            meta = search_server._app_report_share_meta("현대자동차")
            html = search_server._replace_app_share_meta(base_html, meta)

        self.assertIn("<title>현대차 최근 2주 유튜버 의견 요약 리포트</title>", html)
        self.assertIn('property="og:title" content="현대차 최근 2주 유튜버 의견 요약 리포트"', html)
        self.assertIn('name="twitter:title" content="현대차 최근 2주 유튜버 의견 요약 리포트"', html)
        self.assertIn('property="og:url" content="https://stockzip.kr/?q=%ED%98%84%EB%8C%80%EC%B0%A8&amp;tab=report"', html)

    def test_stock_page_html_has_indexable_stock_content(self):
        stock = {"name": "삼성전자", "code": "005930", "market": "KOSPI", "aliases": ["삼전"]}
        video = {
            "videoId": "v1",
            "channel": "테스트채널",
            "title": "삼성전자 실적 전망",
            "publishedAt": "2026-07-04T10:00:00+09:00",
            "views": 1234,
            "url": "https://www.youtube.com/watch?v=v1",
            "searchText": stock_search.compact("삼성전자 실적 전망"),
            "titleSearchText": stock_search.compact("삼성전자 실적 전망"),
            "transcriptStatus": "ok",
        }
        with mock.patch("stock_search.stock_master", return_value=[stock]), \
                mock.patch("stock_search.load_index", return_value={
                    "version": stock_search._SEARCH_INDEX_VERSION,
                    "updatedAt": "2026-07-05T09:00:00+09:00",
                    "videos": [video],
                }), \
                mock.patch("config.CHANNELS", [{"name": "테스트채널", "channelId": "UC1"}]):
            html = search_server._stock_page_html(stock)

        self.assertIn("<title>삼성전자 최근 2주 유튜버 의견 요약 리포트</title>", html)
        self.assertIn('rel="canonical" href="https://stockzip.kr/stocks/005930"', html)
        self.assertIn('<meta name="robots" content="index,follow,max-image-preview:large">', html)
        self.assertIn('property="og:title" content="삼성전자 최근 2주 유튜버 의견 요약 리포트"', html)
        self.assertIn('property="og:image:alt" content="삼성전자 최근 2주 유튜버 의견 요약 리포트"', html)
        self.assertIn('href="https://stockzip.kr/?q=%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90&amp;tab=report"', html)
        self.assertIn('aria-label="breadcrumb"', html)
        self.assertIn("삼성전자 실적 전망", html)
        self.assertIn("최근 언급 영상", html)

        match = re.search(r'<script type="application/ld\+json">(.+?)</script>', html, re.S)
        self.assertIsNotNone(match)
        schema = json.loads(match.group(1))
        graph = schema["@graph"]
        self.assertTrue(any(item["@type"] == "BreadcrumbList" for item in graph))
        page = next(item for item in graph if item["@type"] == "WebPage")
        self.assertEqual(page["url"], "https://stockzip.kr/stocks/005930")
        self.assertEqual(page["mainEntity"]["name"], "삼성전자")
        self.assertEqual(page["dateModified"], "2026-07-04")

    def test_sitemap_xml_includes_stock_pages(self):
        with mock.patch("stock_search.indexable_stock_rows", return_value=[
                {"name": "삼성전자", "code": "005930", "market": "KOSPI", "slug": "005930"},
                {"name": "엔비디아", "code": "NVDA", "market": "NASDAQ", "slug": "NVDA"},
        ]), mock.patch("stock_search.load_index", return_value={
                "updatedAt": "2026-07-05T09:00:00+09:00",
        }):
            sitemap = search_server._sitemap_xml()

        root = ET.fromstring(sitemap)
        urls = {node.text for node in root.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc")}
        self.assertIn("https://stockzip.kr/", urls)
        self.assertIn("https://stockzip.kr/stocks/005930", urls)
        self.assertIn("https://stockzip.kr/stocks/NVDA", urls)


if __name__ == "__main__":
    unittest.main()
