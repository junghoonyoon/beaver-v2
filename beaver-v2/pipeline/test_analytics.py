import datetime
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

    def test_dashboard_metrics_counts_core_funnel(self):
        self.write_event("page_view", "u1")
        self.write_event("session_start", "u1")
        self.write_event("search_submit", "u1", query="삼성전자")
        self.write_event("search_result", "u1", query="삼성전자", success=True, matchedVideos=2, opinionCount=1)
        self.write_event("stock_detail_view", "u1", query="삼성전자")
        self.write_event("video_click", "u1", query="삼성전자")
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
        self.assertEqual(by_key["video_click_rate"]["value"], "100.0%")
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
