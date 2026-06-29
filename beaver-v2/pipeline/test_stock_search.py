import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import stock_search


class StockSearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(config, "CACHE_DIR", self.root),
            mock.patch.object(config, "TRANSCRIPT_CACHE_DIR", self.root / "transcripts"),
            mock.patch.object(config, "STOCK_ANALYSIS_CACHE_DIR", self.root / "stock_analysis"),
            mock.patch.object(config, "SEARCH_INDEX_JSON", self.root / "search_index.json"),
            mock.patch.object(config, "KRX_LISTED_JSON", self.root / "krx_listed_stocks.json"),
            mock.patch.object(config, "US_LISTED_JSON", self.root / "us_listed_stocks.json"),
            mock.patch.object(config, "SEARCH_MAX_YOUTUBERS", 10),
            mock.patch.object(config, "SEARCH_MAX_ANALYZED_VIDEOS", 2),
            mock.patch.object(config, "SEARCH_CONTEXT_WINDOW", 450),
            mock.patch.object(config, "SEARCH_CONTEXT_MAX_CHARS", 4000),
            mock.patch.object(config, "SEARCH_CONTEXT_MAX_SPANS", 4),
            mock.patch.object(config, "FORCE_ANALYSIS_REFRESH", False),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def write_transcript(self, video_id, text):
        config.TRANSCRIPT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (config.TRANSCRIPT_CACHE_DIR / f"{video_id}.json").write_text(json.dumps({
            "status": "ok", "text": text,
        }, ensure_ascii=False), encoding="utf-8")

    def write_index(self, videos):
        config.SEARCH_INDEX_JSON.write_text(json.dumps({
            "updatedAt": "2026-06-24T00:00:00+09:00",
            "videos": videos,
        }, ensure_ascii=False), encoding="utf-8")

    def write_krx_stocks(self, stocks):
        config.KRX_LISTED_JSON.write_text(json.dumps({
            "fetchedAt": "2026-06-24T00:00:00+09:00",
            "baseDate": "20260624",
            "stocks": stocks,
        }, ensure_ascii=False), encoding="utf-8")

    def write_us_stocks(self, stocks):
        config.US_LISTED_JSON.write_text(json.dumps({
            "fetchedAt": "2026-06-24T00:00:00+09:00",
            "baseDate": "sample",
            "stocks": stocks,
        }, ensure_ascii=False), encoding="utf-8")

    def test_known_aliases_find_spaced_name(self):
        aliases = stock_search.query_aliases("SK하이닉스")
        self.assertIn("하이닉스", aliases)
        self.assertGreater(stock_search.match_count("오늘 SK 하이닉스를 봅니다", aliases), 0)

    def test_suggest_stocks_returns_samsung_group_candidates(self):
        names = [row["name"] for row in stock_search.suggest_stocks("삼성")]
        self.assertGreaterEqual(len(names), 4)
        self.assertIn("삼성전자", names)
        self.assertIn("삼성SDS", names)
        self.assertIn("삼성전기", names)
        self.assertIn("삼성카드", names)

    def test_suggest_stocks_returns_ls_group_candidates(self):
        names = [row["name"] for row in stock_search.suggest_stocks("LS")]
        self.assertIn("LS", names)
        self.assertIn("LS ELECTRIC", names)
        self.assertIn("LS에코에너지", names)
        self.assertIn("LS마린솔루션", names)
        self.assertEqual(stock_search.suggest_stocks("LS일렉")[0]["name"], "LS ELECTRIC")

    def test_suggest_stocks_uses_krx_cache_when_available(self):
        self.write_krx_stocks([
            {"baseDate": "20260624", "code": "123450", "isin": "KR7123450000", "market": "KOSDAQ",
             "name": "비버전자", "corpName": "비버전자 주식회사", "aliases": ["비버전자 주식회사"], "source": "KRX"},
        ])
        first = stock_search.suggest_stocks("비버")[0]
        self.assertEqual(first["name"], "비버전자")
        self.assertEqual(first["code"], "123450")
        self.assertEqual(first["isin"], "KR7123450000")
        self.assertEqual(first["source"], "KRX")

    def test_suggest_stocks_uses_us_cache_and_korean_aliases(self):
        self.write_us_stocks([
            {"code": "INTC", "market": "NASDAQ", "name": "Intel Corporation", "english": "Intel Corporation",
             "corpName": "Intel Corporation", "aliases": ["INTC", "Intel Corporation", "인텔", "Intel"], "source": "NASDAQ_TRADER"},
            {"code": "NVDA", "market": "NASDAQ", "name": "NVIDIA Corporation", "english": "NVIDIA Corporation",
             "corpName": "NVIDIA Corporation", "aliases": ["NVDA", "NVIDIA Corporation", "엔비디아", "NVIDIA"], "source": "NASDAQ_TRADER"},
        ])
        first = stock_search.suggest_stocks("인텔")[0]
        self.assertEqual(first["name"], "인텔")
        self.assertEqual(first["code"], "INTC")
        self.assertEqual(first["market"], "NASDAQ")
        self.assertEqual(first["source"], "NASDAQ_TRADER")
        self.assertIn("Intel Corporation", first["aliases"])

        nvidia = stock_search.suggest_stocks("nvidia")[0]
        self.assertEqual(nvidia["name"], "엔비디아")
        self.assertEqual(nvidia["code"], "NVDA")
        self.assertIn("NVIDIA Corporation", nvidia["aliases"])

    def test_suggest_stocks_uses_name_prefix_only(self):
        names = [row["name"] for row in stock_search.suggest_stocks("나")]
        self.assertGreaterEqual(len(names), 5)
        self.assertTrue(all(name.startswith("나") for name in names))

    def test_suggest_stocks_can_match_name_contains_as_lower_priority(self):
        names = [row["name"] for row in stock_search.suggest_stocks("성전")]
        self.assertIn("삼성전자", names)
        self.assertIn("삼성전기", names)

    def test_suggest_stocks_scores_like_brokerage_search(self):
        self.assertEqual(stock_search.suggest_stocks("삼전")[0]["name"], "삼성전자")
        self.assertEqual(stock_search.suggest_stocks("ㅅㅈ")[0]["name"], "삼성전자")
        self.assertEqual(stock_search.suggest_stocks("0059")[0]["name"], "삼성전자")
        self.assertEqual(stock_search.suggest_stocks("nvidia")[0]["name"], "엔비디아")
        self.assertEqual(stock_search.suggest_stocks("갤럭시")[0]["name"], "삼성전자")

    def test_find_videos_keeps_one_representative_per_channel(self):
        videos = [
            {"videoId": "a", "channel": "A", "title": "하이닉스 전망", "publishedAt": "2026-06-24",
             "views": 10, "url": "a"},
            {"videoId": "b", "channel": "A", "title": "시장 전망", "publishedAt": "2026-06-23",
             "views": 20, "url": "b"},
            {"videoId": "c", "channel": "B", "title": "반도체", "publishedAt": "2026-06-22",
             "views": 30, "url": "c"},
        ]
        self.write_transcript("a", "하이닉스 실적이 좋습니다")
        self.write_transcript("b", "하이닉스는 신중합니다")
        self.write_transcript("c", "SK 하이닉스 상승을 봅니다")
        self.write_index(videos)
        found = stock_search.find_videos("SK하이닉스")
        self.assertEqual(len(found), 2)
        self.assertEqual({row["channel"] for row in found}, {"A", "B"})
        self.assertEqual(next(row for row in found if row["channel"] == "A")["videoId"], "a")

    def test_stock_analysis_is_cached(self):
        video = {"videoId": "v1", "_text": "삼성전자 실적 개선을 긍정적으로 봅니다."}
        result = {"mentioned": True, "stance": "긍정", "summary": "긍정적이에요.", "evidence": "실적 개선을 봤어요."}
        with mock.patch("analyze.analyze_stock_opinion", return_value=result) as analyze_call:
            first, first_cached = stock_search.analyze_match(video, "삼성전자")
            second, second_cached = stock_search.analyze_match(video, "삼성전자")
        self.assertEqual(first, second)
        self.assertFalse(first_cached)
        self.assertTrue(second_cached)
        analyze_call.assert_called_once()

    def test_analyze_match_falls_back_to_title_when_transcript_is_missing(self):
        video = {
            "videoId": "v1",
            "_text": "",
            "title": "현대차 주가 빠진 진짜 이유",
        }

        result, cached = stock_search.analyze_match(video, "현대차")

        self.assertFalse(cached)
        self.assertTrue(result["mentioned"])
        self.assertEqual(result["stance"], "단순언급")

    def test_search_stock_only_generates_for_fast_limit_but_uses_extra_cache(self):
        videos = [
            {"videoId": "a", "channel": "A", "title": "삼성전자", "publishedAt": "2026-06-24",
             "views": 30, "url": "a"},
            {"videoId": "b", "channel": "B", "title": "삼성전자", "publishedAt": "2026-06-23",
             "views": 20, "url": "b"},
            {"videoId": "c", "channel": "C", "title": "삼성전자", "publishedAt": "2026-06-22",
             "views": 10, "url": "c"},
        ]
        for row in videos:
            self.write_transcript(row["videoId"], "삼성전자 실적 개선을 긍정적으로 봅니다.")
        self.write_index(videos)

        cached_video = dict(videos[2], _text="삼성전자 실적 개선을 긍정적으로 봅니다.", matchCount=1, titleMatch=True)
        cached_result = {"mentioned": True, "stance": "신중", "summary": "캐시 의견이에요.", "evidence": "캐시 근거예요."}
        with mock.patch("analyze.analyze_stock_opinion", return_value=cached_result):
            stock_search.analyze_match(cached_video, "삼성전자")

        fresh_result = {"mentioned": True, "stance": "긍정", "summary": "새 의견이에요.", "evidence": "새 근거예요."}
        with mock.patch("analyze.analyze_stock_opinion", return_value=fresh_result) as analyze_call:
            data = stock_search.search_stock("삼성전자")

        self.assertEqual(data["matchedVideos"], 3)
        self.assertEqual(data["analyzedVideos"], 2)
        self.assertEqual(len(data["opinions"]), 3)
        self.assertEqual(analyze_call.call_count, 2)

    def test_sort_opinions_prioritizes_latest_upload(self):
        data = {"opinions": [], "counts": {"긍정": 0, "신중": 0, "부정": 0, "단순언급": 0}}
        stock_search.add_opinion(data, {
            "stance": "단순언급", "channel": "A", "publishedAt": "2026-06-26T15:00:00+09:00", "views": 1,
        })
        stock_search.add_opinion(data, {
            "stance": "긍정", "channel": "B", "publishedAt": "2026-06-25T20:00:37+09:00", "views": 116403,
        })
        stock_search.add_opinion(data, {
            "stance": "부정", "channel": "C", "publishedAt": "2026-06-26T14:51:15+09:00", "views": 167,
        })

        stock_search.sort_opinions(data)

        self.assertEqual([row["channel"] for row in data["opinions"]], ["A", "C", "B"])
        self.assertNotIn("_order", data["opinions"][0])


if __name__ == "__main__":
    unittest.main()
