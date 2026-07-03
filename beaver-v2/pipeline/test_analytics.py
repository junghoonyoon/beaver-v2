import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analytics
import config


class AnalyticsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.events_path = self.root / "analytics_events.jsonl"
        self.patches = [
            mock.patch.object(config, "CACHE_DIR", self.root),
            mock.patch.object(config, "ANALYTICS_EVENTS_JSONL", self.events_path),
            mock.patch("remote_cache.download_to_file", return_value=False),
            mock.patch("remote_cache.upload_file", return_value=True),
            mock.patch("remote_cache.download_bytes", return_value=None),
            mock.patch("remote_cache.upload_bytes", return_value=True),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def write_event(self, event_type, user_id, day_offset=0, **extra):
        now = datetime.datetime.now(analytics.KST) + datetime.timedelta(days=day_offset)
        payload = {
            "type": event_type,
            "timestamp": now.isoformat(),
            "userId": user_id,
            "sessionId": f"s-{user_id}-{day_offset}",
            "path": "/",
            **extra,
        }
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as file:
            import json
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def test_record_event_writes_jsonl(self):
        event = analytics.record_event({
            "type": "search_submit",
            "userId": "u1",
            "sessionId": "s1",
            "query": "삼성전자",
        })

        self.assertEqual(event["type"], "search_submit")
        self.assertTrue(self.events_path.exists())
        self.assertIn("삼성전자", self.events_path.read_text(encoding="utf-8"))

    def test_record_share_event_keeps_method(self):
        event = analytics.record_event({
            "type": "share_success",
            "userId": "u1",
            "sessionId": "s1",
            "query": "엔비디아",
            "method": "clipboard",
            "url": "https://stockzip.kr/?q=%EC%97%94%EB%B9%84%EB%94%94%EC%95%84",
        })

        saved = self.events_path.read_text(encoding="utf-8")
        self.assertEqual(event["type"], "share_success")
        self.assertEqual(event["method"], "clipboard")
        self.assertIn("share_success", saved)
        self.assertIn("clipboard", saved)

    def test_record_event_merges_larger_remote_file_before_upload(self):
        remote_rows = [
            {
                "type": "page_view",
                "timestamp": "2026-07-01T16:32:58+09:00",
                "userId": "remote-user-1",
                "sessionId": "s-remote-1",
                "path": "/",
            },
            {
                "type": "search_submit",
                "timestamp": "2026-07-01T16:33:10+09:00",
                "userId": "remote-user-2",
                "sessionId": "s-remote-2",
                "path": "/",
                "query": "삼성전자",
            },
        ]
        remote_body = "\n".join(json.dumps(row, ensure_ascii=False) for row in remote_rows).encode("utf-8") + b"\n"

        with mock.patch("remote_cache.download_bytes", return_value=remote_body), \
                mock.patch("remote_cache.upload_bytes", return_value=True) as upload:
            analytics.record_event({
                "type": "page_view",
                "userId": "new-user",
                "sessionId": "s-new",
            })

        saved = self.events_path.read_text(encoding="utf-8")
        self.assertIn("remote-user-1", saved)
        self.assertIn("remote-user-2", saved)
        self.assertIn("new-user", saved)
        self.assertEqual(len(saved.splitlines()), 3)
        self.assertGreaterEqual(upload.call_count, 2)
        self.assertEqual(upload.call_args_list[-1].args[0], analytics.REMOTE_PATH)

    def test_record_video_click_keeps_target_and_stance(self):
        event = analytics.record_event({
            "type": "video_click",
            "userId": "u1",
            "sessionId": "s1",
            "query": "마이크론",
            "clickTarget": "evidence_timestamp",
            "stance": "긍정",
            "label": "03:12부터 근거 확인",
            "url": "https://www.youtube.com/watch?v=abc&t=192s",
        })

        saved = self.events_path.read_text(encoding="utf-8")
        self.assertEqual(event["clickTarget"], "evidence_timestamp")
        self.assertEqual(event["stance"], "긍정")
        self.assertIn("03:12부터 근거 확인", saved)

    def test_record_search_result_keeps_market_mood_fields(self):
        event = analytics.record_event({
            "type": "search_result",
            "userId": "u1",
            "sessionId": "s1",
            "query": "삼성전자",
            "success": True,
            "marketMood": "관망 우세",
            "positiveCount": 1,
            "watchCount": 3,
            "riskCount": 0,
            "mentionOnlyCount": 2,
        })

        self.assertEqual(event["marketMood"], "관망 우세")
        self.assertEqual(event["watchCount"], 3)
        self.assertEqual(event["mentionOnlyCount"], 2)

    def test_dashboard_metrics_counts_core_funnel(self):
        self.write_event("page_view", "u1")
        self.write_event("session_start", "u1")
        self.write_event("search_submit", "u1", query="삼성전자")
        self.write_event("search_result", "u1", query="삼성전자", success=True, matchedVideos=2, opinionCount=1)
        self.write_event("stock_detail_view", "u1", query="삼성전자")
        self.write_event("video_click", "u1", query="삼성전자", clickTarget="evidence_timestamp", stance="긍정")
        self.write_event("video_click", "u1", query="삼성전자", clickTarget="source_cta", stance="긍정")
        self.write_event("video_click", "u1", query="삼성전자", clickTarget="channel_name", stance="긍정")
        self.write_event("session_end", "u1", durationMs=125000)
        self.write_event("page_view", "u2")
        self.write_event("search_submit", "u2", query="없는종목")
        self.write_event("search_result", "u2", query="없는종목", success=False)

        metrics = analytics.dashboard_metrics(days=7)
        by_key = {row["key"]: row for row in metrics["metrics"]}

        self.assertTrue(metrics["hasData"])
        self.assertIsNotNone(metrics["collection"]["firstEventAt"])
        self.assertEqual(by_key["dau"]["raw"], 2)
        self.assertEqual(by_key["total_searches"]["raw"], 2)
        self.assertEqual(by_key["stock_detail_views"]["raw"], 1)
        self.assertEqual(by_key["returning_users"]["raw"], 0)
        self.assertEqual(by_key["return_rate"]["value"], "0.0%")
        self.assertEqual(by_key["search_rate"]["value"], "100.0%")
        self.assertEqual(by_key["search_failure_rate"]["value"], "50.0%")
        self.assertEqual(by_key["video_click_rate"]["value"], "300.0%")
        self.assertEqual(by_key["video_click_user_rate"]["value"], "100.0%")
        self.assertEqual(by_key["evidence_timestamp_click_rate"]["value"], "100.0%")
        self.assertEqual(by_key["source_cta_click_rate"]["value"], "100.0%")
        self.assertEqual(by_key["channel_name_click_rate"]["value"], "100.0%")
        self.assertEqual(metrics["videoClickTargets"]["evidenceTimestamp"], 1)
        self.assertEqual(metrics["videoClickTargets"]["sourceCta"], 1)
        self.assertEqual(metrics["videoClickTargets"]["channelName"], 1)
        self.assertEqual(metrics["searchTerms"][0]["query"], "삼성전자")
        self.assertEqual(metrics["searchTerms"][0]["count"], 1)
        self.assertEqual(metrics["searchTerms"][0]["users"], 1)
        self.assertEqual(metrics["searchTerms"][0]["successRate"], 100.0)
        self.assertEqual(metrics["searchTerms"][1]["query"], "없는종목")
        self.assertEqual(metrics["searchTerms"][1]["failedCount"], 1)
        self.assertEqual(metrics["searchTerms"][1]["successRate"], 0.0)
        self.assertEqual(by_key["avg_session_time"]["value"], "2:05")

    def test_returning_users_matches_return_rate_definition(self):
        self.write_event("page_view", "u1", day_offset=-1, sessionId="s-u1-a")
        self.write_event("page_view", "u1", sessionId="s-u1-b")
        self.write_event("page_view", "u2")

        metrics = analytics.dashboard_metrics(days=7)
        by_key = {row["key"]: row for row in metrics["metrics"]}

        self.assertEqual(by_key["returning_users"]["raw"], 1)
        self.assertEqual(by_key["return_rate"]["value"], "50.0%")


if __name__ == "__main__":
    unittest.main()
