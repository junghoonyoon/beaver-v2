import datetime
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
            mock.patch.object(config, "SEARCH_FALLBACK_ENABLED", False),
            mock.patch.object(config, "FORCE_ANALYSIS_REFRESH", False),
            mock.patch("remote_cache.download_json", return_value=None),
            mock.patch("remote_cache.upload_json", return_value=True),
            mock.patch("remote_cache.download_to_file", return_value=False),
            mock.patch("remote_cache.upload_file", return_value=True),
        ]
        for patch in self.patches:
            patch.start()
        stock_search.clear_popular_stocks_cache()

    def tearDown(self):
        stock_search.clear_popular_stocks_cache()
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

    def test_channel_pool_has_launch_scale_and_categories(self):
        categories = {cat for channel in config.CHANNELS for cat in channel.get("categories", [])}

        self.assertGreaterEqual(len(config.CHANNELS), 80)
        self.assertGreaterEqual(len(config.signal_pool()), 40)
        self.assertGreaterEqual(len([c for c in config.CHANNELS if c.get("channelId")]), 70)
        self.assertGreaterEqual(len([c for c in config.signal_pool() if c.get("channelId")]), 40)
        self.assertTrue({
            "국내주식", "미국주식", "반도체", "2차전지", "바이오", "조선방산", "거시시황",
        }.issubset(categories))

    def test_short_us_ticker_does_not_match_inside_english_words(self):
        self.write_us_stocks([
            {"code": "LLY", "market": "NYSE", "name": "Eli Lilly and Company", "english": "Eli Lilly and Company",
             "corpName": "Eli Lilly and Company", "aliases": ["LLY", "Eli Lilly and Company", "일라이릴리"], "source": "NASDAQ"},
        ])
        aliases = stock_search.query_aliases("일라이릴리")
        self.assertIn("LLY", aliases)
        self.assertEqual(stock_search.match_count("Never really not justice.", aliases), 0)
        self.assertGreater(stock_search.match_count("LLY earnings look strong.", aliases), 0)

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

    def test_lg_cns_aliases_match_krx_name(self):
        self.write_krx_stocks([
            {"baseDate": "20260624", "code": "064400", "isin": "KR7064400005", "market": "KOSPI",
             "name": "LG씨엔에스", "corpName": "(주)엘지씨엔에스", "aliases": ["(주)엘지씨엔에스"], "source": "KRX"},
        ])
        first = stock_search.suggest_stocks("LG CNS")[0]
        self.assertEqual(first["name"], "LG씨엔에스")
        self.assertEqual(first["code"], "064400")
        self.assertIn("LG CNS", stock_search.query_aliases("LG CNS"))
        self.assertIn("엘지씨엔에스", stock_search.query_aliases("lg cns"))
        self.assertGreater(stock_search.match_count("LG CNS도 데이터센터 수혜를 봅니다.", stock_search.query_aliases("LG CNS")), 0)

    def test_popular_stocks_returns_market_groups_from_mentions(self):
        videos = [
            {"videoId": "kr1", "channel": "A", "title": "삼성전자 전망", "publishedAt": "2026-06-24T10:00:00+09:00",
             "views": 10000, "url": "kr1"},
            {"videoId": "kr2", "channel": "B", "title": "반도체", "publishedAt": "2026-06-25T10:00:00+09:00",
             "views": 20000, "url": "kr2"},
            {"videoId": "us1", "channel": "C", "title": "엔비디아 AI", "publishedAt": "2026-06-25T11:00:00+09:00",
             "views": 30000, "url": "us1"},
        ]
        self.write_transcript("kr1", "삼성전자 실적 개선")
        self.write_transcript("kr2", "삼성전자는 HBM 기대감이 있습니다")
        self.write_transcript("us1", "엔비디아 GPU 수요가 좋습니다")
        self.write_index(videos)

        with mock.patch("market_rankings.quotes_for_rows", return_value={}):
            payload = stock_search.popular_stocks(limit=5)

        self.assertEqual(payload["title"], "인기주식 TOP 10")
        self.assertIn("유튜브 언급 기준", payload["basis"])
        self.assertEqual(payload["markets"]["kr"]["rows"][0]["name"], "삼성전자")
        self.assertEqual(payload["markets"]["kr"]["rows"][0]["videoCount"], 2)
        self.assertEqual(payload["markets"]["kr"]["rows"][0]["rawChannelCount"], 2)
        self.assertNotIn("opinionCount", payload["markets"]["kr"]["rows"][0])
        self.assertEqual(payload["markets"]["us"]["rows"][0]["name"], "엔비디아")
        self.assertEqual(payload["markets"]["us"]["rows"][0]["videoCount"], 1)
        self.assertEqual(payload["markets"]["us"]["rows"][0]["rawChannelCount"], 1)

    def test_popular_stocks_sort_by_raw_channel_count_first(self):
        videos = [
            {"videoId": "nv1", "channel": "A", "title": "엔비디아", "publishedAt": "2026-06-25T10:00:00+09:00",
             "views": 500000, "url": "nv1"},
            {"videoId": "nv2", "channel": "A", "title": "엔비디아", "publishedAt": "2026-06-25T11:00:00+09:00",
             "views": 500000, "url": "nv2"},
            {"videoId": "mu1", "channel": "B", "title": "마이크론", "publishedAt": "2026-06-25T12:00:00+09:00",
             "views": 1000, "url": "mu1"},
            {"videoId": "mu2", "channel": "C", "title": "마이크론", "publishedAt": "2026-06-25T13:00:00+09:00",
             "views": 1000, "url": "mu2"},
        ]
        for row in videos:
            self.write_transcript(row["videoId"], row["title"])
        self.write_index(videos)

        with mock.patch("market_rankings.quotes_for_rows", return_value={}):
            payload = stock_search.popular_stocks(limit=2)

        rows = payload["markets"]["us"]["rows"]
        self.assertEqual(rows[0]["name"], "마이크론")
        self.assertEqual(rows[0]["rawChannelCount"], 2)
        self.assertEqual(rows[1]["name"], "엔비디아")
        self.assertEqual(rows[1]["rawChannelCount"], 1)

    def test_popular_stocks_uses_us_alias_candidates_from_cache(self):
        self.write_us_stocks([
            {"code": "AVGO", "market": "NASDAQ", "name": "Broadcom Inc.", "english": "Broadcom Inc.",
             "corpName": "Broadcom Inc.", "aliases": ["AVGO", "Broadcom Inc.", "브로드컴"], "source": "NASDAQ_TRADER"},
        ])
        videos = [
            {"videoId": "avgo1", "channel": "A", "title": "브로드컴 AI 반도체", "publishedAt": "2026-06-25T10:00:00+09:00",
             "views": 10000, "url": "avgo1"},
        ]
        self.write_transcript("avgo1", "브로드컴은 AI 반도체 수요가 좋습니다.")
        self.write_index(videos)

        with mock.patch("market_rankings.quotes_for_rows", return_value={}):
            payload = stock_search.popular_stocks(limit=5)

        rows = payload["markets"]["us"]["rows"]
        self.assertEqual(rows[0]["name"], "브로드컴")
        self.assertEqual(rows[0]["code"], "AVGO")
        self.assertEqual(rows[0]["rawChannelCount"], 1)

    def test_warm_popular_stocks_cache_saves_home_payload(self):
        videos = [
            {"videoId": "kr1", "channel": "A", "title": "삼성전자 전망", "publishedAt": "2026-06-24",
             "views": 10000, "url": "kr1"},
            {"videoId": "kr2", "channel": "B", "title": "삼성전자 투자", "publishedAt": "2026-06-25",
             "views": 20000, "url": "kr2"},
        ]
        for row in videos:
            self.write_transcript(row["videoId"], "삼성전자 실적 개선을 긍정적으로 봅니다.")
        self.write_index(videos)

        with mock.patch("market_rankings.quotes_for_rows", return_value={}), \
                mock.patch("remote_cache.upload_file"):
            stats = stock_search.warm_popular_stocks_cache(limit=1)
            stock_search.clear_popular_stocks_cache()
            payload = stock_search.popular_stocks(limit=1)

        self.assertTrue(stats["saved"])
        self.assertEqual(stats["rows"], 1)
        self.assertEqual(payload["markets"]["kr"]["rows"][0]["rawChannelCount"], 2)

    def test_popular_stocks_refreshes_missing_cached_quotes(self):
        self.write_index([])
        cached = {
            "version": stock_search._POPULAR_STOCKS_CACHE_VERSION,
            "limit": 1,
            "indexUpdatedAt": "2026-07-03T09:00:00+09:00",
            "payload": {
                "title": "인기주식 TOP 10",
                "basis": "최근 14일 유튜브 언급 기준",
                "updatedAt": "2026-07-03T09:00:00+09:00",
                "quoteUpdatedAt": "2026-07-03T09:00:00+09:00",
                "markets": {
                    "us": {"rows": [{
                        "name": "마이크론",
                        "code": "MU",
                        "rawChannelCount": 42,
                        "changeRateText": "",
                    }]},
                },
            },
        }
        stock_search._popular_stocks_cache_path().write_text(json.dumps(cached), encoding="utf-8")

        with mock.patch("market_rankings.quotes_for_rows", return_value={
            "MU": {"changeRateText": "-3.35%", "quoteSource": "NASDAQ"}
        }):
            payload = stock_search.popular_stocks(limit=1)

        row = payload["markets"]["us"]["rows"][0]
        self.assertEqual(row["changeRateText"], "-3.35%")
        self.assertEqual(row["quoteSource"], "NASDAQ")

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

    def test_find_videos_uses_index_search_text_without_loading_all_transcripts(self):
        videos = [
            {"videoId": "a", "channel": "A", "title": "시장 전망", "publishedAt": "2026-06-24",
             "views": 10, "url": "a", "searchText": stock_search.compact("하이닉스 실적 개선"),
             "titleSearchText": stock_search.compact("시장 전망"), "transcriptStatus": "ok"},
            {"videoId": "b", "channel": "B", "title": "반도체", "publishedAt": "2026-06-23",
             "views": 20, "url": "b", "searchText": stock_search.compact("삼성전자 실적 개선"),
             "titleSearchText": stock_search.compact("반도체"), "transcriptStatus": "ok"},
        ]
        self.write_index(videos)

        with mock.patch("stock_search.transcript_text", side_effect=AssertionError("should not read transcripts")):
            found, stats = stock_search.find_videos_with_stats("SK하이닉스")

        self.assertEqual([row["videoId"] for row in found], ["a"])
        self.assertEqual(stats["mentionedVideoCount"], 1)
        self.assertEqual(stats["candidateYoutuberCount"], 1)

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

    def test_market_mood_uses_conservative_bias_adjustment(self):
        cases = [
            ({"긍정": 5, "신중": 1, "부정": 0, "단순언급": 2}, "긍정적 분위기"),
            ({"긍정": 4, "신중": 4, "부정": 0, "단순언급": 1}, "조건부 긍정"),
            ({"긍정": 3, "신중": 7, "부정": 1, "단순언급": 4}, "관망 우세"),
            ({"긍정": 2, "신중": 2, "부정": 2, "단순언급": 0}, "주의 필요"),
            ({"긍정": 1, "신중": 0, "부정": 0, "단순언급": 8}, "판단 보류"),
            ({"긍정": 3, "신중": 1, "부정": 3, "단순언급": 0}, "주의 필요"),
        ]

        for counts, label in cases:
            with self.subTest(counts=counts):
                mood = stock_search.market_mood(counts)
                self.assertEqual(mood["label"], label)
                self.assertEqual(set(mood), {"label", "summary", "biasNotice", "judgedCount", "mentionOnlyCount", "scoreRatio"})

    def test_add_opinion_updates_market_mood_without_base_result(self):
        data = stock_search.base_search_result("삼성전자", [])

        for stance in ("긍정", "신중", "신중", "단순언급"):
            stock_search.add_opinion(data, {
                "stance": stance,
                "channel": "A",
                "publishedAt": "2026-06-24",
                "views": 1,
            })

        self.assertEqual(data["marketMood"]["label"], "관망 우세")
        self.assertEqual(set(data["marketMood"]), {"label", "summary", "biasNotice", "judgedCount", "mentionOnlyCount", "scoreRatio"})

    def test_analyze_match_ignores_title_only_when_transcript_is_missing(self):
        video = {
            "videoId": "v1",
            "_text": "",
            "title": "현대차 주가 빠진 진짜 이유",
        }

        result, cached = stock_search.analyze_match(video, "현대차")

        self.assertFalse(cached)
        self.assertFalse(result["mentioned"])
        self.assertEqual(result["stance"], "단순언급")

    def test_market_mood_ignores_mention_only_and_labels_small_samples(self):
        mood = stock_search.market_mood({"긍정": 1, "신중": 1, "부정": 0, "단순언급": 5})

        self.assertEqual(mood["label"], "판단 보류")
        self.assertIsNone(mood["biasNotice"])
        self.assertEqual(set(mood), {"label", "summary", "biasNotice", "judgedCount", "mentionOnlyCount", "scoreRatio"})

    def test_market_mood_labels_representative_cases(self):
        self.assertEqual(stock_search.market_mood({"긍정": 4, "신중": 1, "부정": 0})["label"], "긍정적 분위기")
        self.assertEqual(stock_search.market_mood({"긍정": 3, "신중": 2, "부정": 0})["label"], "조건부 긍정")
        self.assertEqual(stock_search.market_mood({"긍정": 1, "신중": 3, "부정": 0})["label"], "관망 우세")
        self.assertEqual(stock_search.market_mood({"긍정": 1, "신중": 1, "부정": 2})["label"], "주의 필요")
        self.assertEqual(stock_search.market_mood({"긍정": 2, "신중": 2, "부정": 1})["label"], "의견 갈림")

    def test_add_opinion_updates_market_mood(self):
        data = {"opinions": [], "counts": {"긍정": 0, "신중": 0, "부정": 0, "단순언급": 0}}
        for idx, stance in enumerate(["긍정", "긍정", "신중"], 1):
            stock_search.add_opinion(data, {
                "stance": stance, "channel": f"C{idx}", "publishedAt": "2026-06-26T15:00:00+09:00", "views": 1,
            })

        self.assertEqual(data["marketMood"]["label"], "긍정적 분위기")

    def test_find_videos_uses_youtube_fallback_when_results_are_stale(self):
        videos = [
            {"videoId": "old", "channel": "A", "title": "현대차 전망", "publishedAt": "2026-06-20T10:00:00+09:00",
             "views": 30, "url": "old"},
        ]
        self.write_transcript("old", "현대차 실적 개선")
        self.write_index(videos)
        fallback = [{
            "videoId": "new",
            "channel": "B",
            "channelId": "UCb",
            "title": "현대차 3시간 전 새 분석",
            "publishedAt": datetime.datetime(2026, 6, 29, 12, 0, 0, tzinfo=stock_search.KST),
            "views": 100,
            "durationSec": 100,
            "url": "new",
        }]

        with mock.patch.object(config, "SEARCH_FALLBACK_ENABLED", True), \
                mock.patch.object(config, "YOUTUBE_API_KEY", "key"), \
                mock.patch.object(config, "SEARCH_FALLBACK_RECENT_HOURS", 24), \
                mock.patch.object(config, "SEARCH_FALLBACK_MAX_RESULTS", 5), \
                mock.patch.object(config, "SEARCH_FALLBACK_MIN_VIEWS", 0), \
                mock.patch.object(config, "SEARCH_FALLBACK_ORDER", "relevance"), \
                mock.patch("youtube.search_videos", return_value=fallback), \
                mock.patch("youtube.fetch_transcript", return_value="현대차 새 의견"):
            found = stock_search.find_videos("현대차")

        self.assertEqual({row["videoId"] for row in found}, {"old", "new"})

    def test_find_videos_skips_title_only_fallback_without_transcript(self):
        videos = [
            {"videoId": "old", "channel": "A", "title": "삼성전자 전망", "publishedAt": "2026-06-20T10:00:00+09:00",
             "views": 30, "url": "old"},
        ]
        self.write_transcript("old", "삼성전자 실적 개선")
        self.write_index(videos)
        fallback = [{
            "videoId": "new",
            "channel": "B",
            "channelId": "UCb",
            "title": "삼성전자 방금 나온 새 분석",
            "publishedAt": datetime.datetime(2026, 6, 29, 12, 0, 0, tzinfo=stock_search.KST),
            "views": 100,
            "durationSec": 100,
            "url": "new",
        }]

        with mock.patch.object(config, "SEARCH_FALLBACK_ENABLED", True), \
                mock.patch.object(config, "YOUTUBE_API_KEY", "key"), \
                mock.patch.object(config, "SEARCH_FALLBACK_RECENT_HOURS", 24), \
                mock.patch.object(config, "SEARCH_FALLBACK_MAX_RESULTS", 5), \
                mock.patch.object(config, "SEARCH_FALLBACK_MIN_VIEWS", 0), \
                mock.patch.object(config, "SEARCH_FALLBACK_ORDER", "relevance"), \
                mock.patch("youtube.search_videos", return_value=fallback), \
                mock.patch("youtube.fetch_transcript", return_value=None):
            found = stock_search.find_videos("삼성전자")

        self.assertEqual([row["videoId"] for row in found], ["old"])

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
