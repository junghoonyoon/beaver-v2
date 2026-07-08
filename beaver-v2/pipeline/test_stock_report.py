"""종목 요약 리포트(쟁점·체크포인트) 생성/캐시/정규화 테스트."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analyze
import config
import stock_search


def _opinion(video_id, stance, summary="판단 문장", evidence="근거 문장", **extra):
    row = {
        "videoId": video_id,
        "channel": f"채널{video_id}",
        "publishedAt": "2026-07-01T09:00:00+09:00",
        "stance": stance,
        "summary": summary,
        "evidence": evidence,
        "reportable": True,
    }
    row.update(extra)
    return row


_RAW_REPORT = {
    "headline": "실적 기대는 크지만 선반영 확인이 먼저예요",
    "summary": "긍정은 실적 개선을, 관망은 주가 선반영을 근거로 봤어요.",
    "consensus": {"text": "실적 개선 방향 자체에는 양쪽이 동의했어요.", "videoIds": ["v1", "v2"]},
    "bullCase": {"text": "박스권 하단이라 가격 메리트가 있다고 봤어요.", "videoIds": ["v1"]},
    "bearCase": {"text": "호재가 선반영돼 실적 확인 후에도 늦지 않다고 봤어요.", "videoIds": ["v2"]},
    "turningPoint": {"text": "실적 발표에서 시장 예상치를 넘으면 관망이 풀려요.", "videoIds": ["v2"]},
    "checkpoints": [
        {
            "event": "2분기 실적 발표",
            "when": "다음 주",
            "check": "영업이익이 시장 예상치를 넘는지 확인하세요.",
            "interpretation": "넘으면 긍정 쪽, 못 넘으면 관망 쪽 의견에 힘이 실려요.",
            "videoIds": ["v1", "없는아이디"],
        },
        {"event": "", "when": "", "check": "이벤트 이름이 없어 버려져야 해요.", "videoIds": []},
    ],
}


class NormalizeStockReportTest(unittest.TestCase):
    def test_normalize_keeps_valid_checkpoints_and_filters_video_ids(self):
        report = analyze._normalize_stock_report(json.loads(json.dumps(_RAW_REPORT)), ["v1", "v2"])
        self.assertEqual(report["headline"], _RAW_REPORT["headline"])
        self.assertEqual(len(report["checkpoints"]), 1)
        self.assertEqual(report["checkpoints"][0]["videoIds"], ["v1"])
        self.assertEqual(report["consensus"]["videoIds"], ["v1", "v2"])

    def test_normalize_hides_empty_text_markers(self):
        raw = json.loads(json.dumps(_RAW_REPORT))
        raw["consensus"] = {"text": "빈 문자열", "videoIds": ["v1"]}
        raw["turningPoint"] = {"text": "[빈 문자열]", "videoIds": ["v2"]}
        raw["checkpoints"][0]["when"] = "빈 문자열"
        raw["checkpoints"][0]["interpretation"] = "없음"

        report = analyze._normalize_stock_report(raw, ["v1", "v2"])

        self.assertEqual(report["consensus"]["text"], "")
        self.assertEqual(report["turningPoint"]["text"], "")
        self.assertEqual(report["checkpoints"][0]["when"], "")
        self.assertEqual(report["checkpoints"][0]["interpretation"], "")

    def test_normalize_reframes_narrow_component_checkpoint(self):
        raw = json.loads(json.dumps(_RAW_REPORT))
        raw["checkpoints"][0].update({
            "event": "애플의 중국 창신 메모리 반도체 칩 사용 여부",
            "timing": "진행중",
            "outcome": {
                "label": "중립",
                "text": "DDR5 제조 원가가 높아 가격 메리트가 크지 않고 글로벌 제품 탑재가 어려워요.",
            },
            "check": "중국 메모리 도입이 글로벌 제품 탑재와 마진 개선으로 이어지는지 확인하세요.",
        })

        report = analyze._normalize_stock_report(raw, ["v1", "v2"])

        self.assertEqual(report["checkpoints"][0]["event"], "메모리 비용과 공급망 리스크")

    def test_normalize_reframes_product_feature_as_monetization_checkpoint(self):
        raw = json.loads(json.dumps(_RAW_REPORT))
        raw["checkpoints"][0].update({
            "event": "AI 부동산 플랫폼 고도화 및 AI 부동산 탐색 기능 탑재",
            "timing": "예정",
            "when": "하반기 예정",
            "check": "네이버 페이가 AI와 디지털 트윈 기술을 결합한 부동산 플랫폼으로 진화하는지 확인해야 해요.",
            "interpretation": "성공적으로 고도화되고 기능이 탑재된다면 신사업 성장 동력에 긍정적인 영향을 줄 거예요.",
        })

        report = analyze._normalize_stock_report(raw, ["v1", "v2"])
        checkpoint = report["checkpoints"][0]

        self.assertEqual(checkpoint["event"], "신사업 수익화와 이익 기여도")
        self.assertIn("거래액", checkpoint["check"])
        self.assertIn("영업이익률", checkpoint["check"])
        self.assertIn("수익화", checkpoint["interpretation"])

    def test_normalize_clips_report_sections_at_sentence_boundary(self):
        raw = json.loads(json.dumps(_RAW_REPORT))
        raw["bullCase"]["text"] = "실적 개선과 저평가 매력이 이어지고 있어요. " * 20

        report = analyze._normalize_stock_report(raw, ["v1", "v2"])

        self.assertLessEqual(len(report["bullCase"]["text"]), 360)
        self.assertTrue(report["bullCase"]["text"].endswith("요."))

    def test_normalize_fails_without_usable_checkpoints(self):
        broken = json.loads(json.dumps(_RAW_REPORT))
        broken["checkpoints"] = [{"event": "", "check": ""}]
        with self.assertRaises(ValueError):
            analyze._normalize_stock_report(broken, ["v1"])

    def test_validator_rejects_report_without_cases(self):
        broken = json.loads(json.dumps(_RAW_REPORT))
        broken["bullCase"] = {"text": ""}
        broken["bearCase"] = {"text": ""}
        with self.assertRaises(ValueError):
            analyze._validate_stock_report_text(json.dumps(broken, ensure_ascii=False))

    def test_validator_accepts_valid_report(self):
        analyze._validate_stock_report_text(json.dumps(_RAW_REPORT, ensure_ascii=False))


class ReportOpinionsTest(unittest.TestCase):
    def test_filters_mentions_and_unreportable(self):
        result = {"opinions": [
            _opinion("v1", "긍정"),
            _opinion("v2", "신중"),
            _opinion("v3", "단순언급"),
            _opinion("v4", "긍정", reportable=False),
            _opinion("v5", "부정", summary=""),
            _opinion("", "긍정"),
        ]}
        rows = stock_search.report_opinions(result)
        self.assertEqual([row["videoId"] for row in rows], ["v1", "v2"])


class SummaryReportCacheTest(unittest.TestCase):
    def _result(self):
        return {
            "query": "SK하이닉스",
            "rawQuery": "SK하이닉스",
            "opinions": [_opinion("v1", "긍정"), _opinion("v2", "신중")],
        }

    def test_same_opinions_generate_once(self):
        normalized = analyze._normalize_stock_report(json.loads(json.dumps(_RAW_REPORT)), ["v1", "v2"])
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(config, "STOCK_REPORT_CACHE_DIR", Path(tmp)), \
             mock.patch.object(config, "FORCE_ANALYSIS_REFRESH", False), \
             mock.patch.object(stock_search.remote_cache, "upload_file", return_value=True), \
             mock.patch.object(analyze, "analyze_stock_report", return_value=dict(normalized)) as call:
            first = stock_search.summary_report_for(self._result())
            second = stock_search.summary_report_for(self._result())
        self.assertEqual(first["headline"], second["headline"])
        call.assert_called_once()

    def test_changed_opinions_invalidate_cache(self):
        normalized = analyze._normalize_stock_report(json.loads(json.dumps(_RAW_REPORT)), ["v1", "v2"])
        changed = self._result()
        changed["opinions"][0]["summary"] = "다른 판단"
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(config, "STOCK_REPORT_CACHE_DIR", Path(tmp)), \
             mock.patch.object(config, "FORCE_ANALYSIS_REFRESH", False), \
             mock.patch.object(stock_search.remote_cache, "upload_file", return_value=True), \
             mock.patch.object(analyze, "analyze_stock_report", return_value=dict(normalized)) as call:
            stock_search.summary_report_for(self._result())
            stock_search.summary_report_for(changed)
        self.assertEqual(call.call_count, 2)

    def test_not_enough_opinions_returns_none(self):
        result = {"query": "테스트", "rawQuery": "테스트", "opinions": [_opinion("v1", "긍정")]}
        with mock.patch.object(analyze, "analyze_stock_report") as call:
            self.assertIsNone(stock_search.summary_report_for(result))
        call.assert_not_called()

    def test_attach_swallows_generation_errors(self):
        result = self._result()
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(config, "STOCK_REPORT_CACHE_DIR", Path(tmp)), \
             mock.patch.object(config, "FORCE_ANALYSIS_REFRESH", False), \
             mock.patch.object(analyze, "analyze_stock_report", side_effect=RuntimeError("LLM 실패")):
            stock_search.attach_summary_report(result)
        self.assertIsNone(result["report"])


if __name__ == "__main__":
    unittest.main()
