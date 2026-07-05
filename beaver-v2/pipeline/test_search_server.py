import json
import re
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

import search_server
import stock_search


class SearchServerJobTest(unittest.TestCase):
    def tearDown(self):
        with search_server.JOBS_LOCK:
            search_server.JOBS.clear()

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


class SearchServerSeoTest(unittest.TestCase):
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

        self.assertIn("<title>삼성전자 유튜브 의견 리포트 | 지금사도될까요?</title>", html)
        self.assertIn('rel="canonical" href="https://stockzip.kr/stocks/005930"', html)
        self.assertIn('<meta name="robots" content="index,follow,max-image-preview:large">', html)
        self.assertIn('property="og:image:alt" content="삼성전자 유튜브 의견 리포트"', html)
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
