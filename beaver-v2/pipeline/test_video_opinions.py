"""수집 시점 다중 종목 의견 추출/조회/fallback 테스트."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analyze
import config
import stock_search


_RAW_EXTRACTION = {
    "opinions": [
        {
            "names": ["하이닉스", "SK하이닉스"],
            "stance": "긍정",
            "summary": "HBM 수요 덕에 실적 개선이 이어진다고 봤어요.",
            "evidence": "HBM 공급 계약 확대를 근거로 들었어요.",
            "speechType": "명시적 전망",
            "timeOrientation": "미래 전망",
            "confidence": "보통",
            "rationaleType": "실적",
            "opinionType": "현재 투자 의견",
            "evaluable": True,
        },
        {
            "names": ["삼전", "삼성전자"],
            "stance": "이상한값",
            "summary": "",
            "evidence": "",
        },
        {"names": [], "stance": "긍정", "summary": "이름 없으면 버려져야 해요."},
    ],
}


class AnalyzeVideoOpinionsTest(unittest.TestCase):
    def test_normalizes_entries_and_drops_invalid(self):
        with mock.patch.object(analyze, "_generate", return_value=json.dumps(_RAW_EXTRACTION, ensure_ascii=False)):
            entries = analyze.analyze_video_opinions("자막" * 100)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["stance"], "긍정")
        self.assertEqual(entries[0]["names"], ["하이닉스", "SK하이닉스"])
        # 잘못된 stance·빈 summary는 단순언급으로 강등
        self.assertEqual(entries[1]["stance"], "단순언급")


class VideoOpinionsCacheTest(unittest.TestCase):
    def _env(self, tmp):
        return mock.patch.object(config, "VIDEO_OPINIONS_CACHE_DIR", Path(tmp))

    def test_extract_uses_llm_once_then_cache(self):
        entries = [{"names": ["SK하이닉스"], "stance": "긍정", "summary": "s", "evidence": "e",
                    "mentioned": True, "speechType": "명시적 전망", "timeOrientation": "미래 전망",
                    "confidence": "보통", "rationaleType": "실적", "opinionType": "현재 투자 의견",
                    "evaluable": True}]
        with tempfile.TemporaryDirectory() as tmp, self._env(tmp), \
             mock.patch.object(config, "FORCE_ANALYSIS_REFRESH", False), \
             mock.patch.object(stock_search.remote_cache, "upload_file", return_value=True), \
             mock.patch.object(stock_search.remote_cache, "download_to_file", return_value=False), \
             mock.patch.object(analyze, "analyze_video_opinions", return_value=entries) as call:
            first = stock_search.extract_video_opinions("vid1", "자막 본문")
            second = stock_search.extract_video_opinions("vid1", "자막 본문")
        self.assertEqual(first, second)
        call.assert_called_once()

    def test_transcript_change_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as tmp, self._env(tmp), \
             mock.patch.object(config, "FORCE_ANALYSIS_REFRESH", False), \
             mock.patch.object(stock_search.remote_cache, "upload_file", return_value=True), \
             mock.patch.object(stock_search.remote_cache, "download_to_file", return_value=False), \
             mock.patch.object(analyze, "analyze_video_opinions", return_value=[]):
            stock_search.extract_video_opinions("vid1", "자막 A")
            self.assertIsNotNone(stock_search.read_video_opinions("vid1", "자막 A"))
            self.assertIsNone(stock_search.read_video_opinions("vid1", "자막 B"))


class ExtractedMatchTest(unittest.TestCase):
    def _video(self):
        return {"videoId": "vid1", "title": "제목", "_text": "자막"}

    def test_hit_by_alias(self):
        entries = [{"names": ["하이닉스", "SK하이닉스"], "stance": "긍정", "summary": "s",
                    "evidence": "e", "mentioned": True}]
        with mock.patch.object(stock_search, "read_video_opinions", return_value=entries):
            status, data = stock_search._extracted_opinion_match(self._video(), ["SK하이닉스", "sk하이닉스"])
        self.assertEqual(status, "hit")
        self.assertEqual(data["stance"], "긍정")
        self.assertNotIn("names", data)

    def test_none_when_stock_absent(self):
        entries = [{"names": ["삼성전자"], "stance": "긍정", "summary": "s", "evidence": "e"}]
        with mock.patch.object(stock_search, "read_video_opinions", return_value=entries):
            status, data = stock_search._extracted_opinion_match(self._video(), ["SK하이닉스"])
        self.assertEqual(status, "none")

    def test_miss_when_no_cache(self):
        with mock.patch.object(stock_search, "read_video_opinions", return_value=None):
            status, _ = stock_search._extracted_opinion_match(self._video(), ["SK하이닉스"])
        self.assertEqual(status, "miss")


class AnalyzeMatchIntegrationTest(unittest.TestCase):
    def test_extracted_hit_skips_llm(self):
        video = {"videoId": "vid1", "title": "SK하이닉스 분석", "_text": "SK하이닉스 이야기"}
        entries = [{"names": ["SK하이닉스"], "stance": "긍정", "summary": "s", "evidence": "e",
                    "mentioned": True}]
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(config, "STOCK_ANALYSIS_CACHE_DIR", Path(tmp)), \
             mock.patch.object(config, "FORCE_ANALYSIS_REFRESH", False), \
             mock.patch.object(stock_search.remote_cache, "upload_file", return_value=True), \
             mock.patch.object(stock_search.remote_cache, "download_to_file", return_value=False), \
             mock.patch.object(stock_search, "read_video_opinions", return_value=entries), \
             mock.patch.object(stock_search, "extract_context", return_value="SK하이닉스 문맥"), \
             mock.patch.object(stock_search, "source_time_sec", return_value=12), \
             mock.patch.object(analyze, "analyze_stock_opinion") as llm:
            data, cached = stock_search.analyze_match(video, "SK하이닉스")
        llm.assert_not_called()
        self.assertTrue(cached)
        self.assertEqual(data["stance"], "긍정")
        self.assertEqual(data["_analysisProvider"], "ingest")
        self.assertEqual(data["sourceTimeSec"], 12)

    def test_fallback_to_llm_when_cache_missing(self):
        video = {"videoId": "vid1", "title": "SK하이닉스 분석", "_text": "SK하이닉스 이야기"}
        llm_result = {"mentioned": True, "stance": "신중", "summary": "s", "evidence": "e"}
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(config, "STOCK_ANALYSIS_CACHE_DIR", Path(tmp)), \
             mock.patch.object(config, "FORCE_ANALYSIS_REFRESH", False), \
             mock.patch.object(stock_search.remote_cache, "upload_file", return_value=True), \
             mock.patch.object(stock_search.remote_cache, "download_to_file", return_value=False), \
             mock.patch.object(stock_search, "read_video_opinions", return_value=None), \
             mock.patch.object(stock_search, "extract_context", return_value="SK하이닉스 문맥"), \
             mock.patch.object(stock_search, "source_time_sec", return_value=None), \
             mock.patch.object(analyze, "analyze_stock_opinion", return_value=dict(llm_result)) as llm:
            data, cached = stock_search.analyze_match(video, "SK하이닉스")
        llm.assert_called_once()
        self.assertFalse(cached)
        self.assertEqual(data["stance"], "신중")


if __name__ == "__main__":
    unittest.main()
