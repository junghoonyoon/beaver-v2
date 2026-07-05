import sqlite3
import tempfile
import unittest
from pathlib import Path

import opinion_history


class OpinionHistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "history.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, video_id, stance, published_at, context_hash, channel_id="UCa"):
        return opinion_history.opinion_record(
            "삼성전자",
            {
                "channel": "A 유튜버",
                "channelId": channel_id,
                "videoId": video_id,
                "title": f"{video_id} 제목",
                "publishedAt": published_at,
                "views": 100,
                "url": f"https://www.youtube.com/watch?v={video_id}",
            },
            {
                "mentioned": True,
                "stance": stance,
                "summary": f"{stance} 요약",
                "evidence": f"{stance} 근거",
                "sourceTimeSec": 15,
            },
            context_hash,
            analysis_provider="openrouter:test",
            analysis_version="stock-cache-v5",
            stock_code="005930",
            market="KOSPI",
        )

    def test_save_opinion_upserts_same_context_without_duplicate(self):
        first = self.record("v1", "긍정", "2026-06-01T10:00:00+09:00", "hash1")
        second = dict(first, views=500, summary="수정된 요약")

        self.assertTrue(opinion_history.save_opinion(first, db_path=self.db_path, store="sqlite"))
        self.assertTrue(opinion_history.save_opinion(second, db_path=self.db_path, store="sqlite"))

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT summary, views FROM youtuber_opinions").fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "수정된 요약")
        self.assertEqual(rows[0][1], 500)

    def test_history_summary_returns_chronological_stances_and_trend(self):
        opinion_history.save_opinion(
            self.record("v1", "긍정", "2026-06-01T10:00:00+09:00", "hash1"),
            db_path=self.db_path,
            store="sqlite",
        )
        opinion_history.save_opinion(
            self.record("v2", "신중", "2026-06-10T10:00:00+09:00", "hash2"),
            db_path=self.db_path,
            store="sqlite",
        )

        summary = opinion_history.history_summary(
            "삼성전자",
            stock_code="005930",
            channel_id="UCa",
            db_path=self.db_path,
            store="sqlite",
            period_days=365,
        )

        self.assertEqual(summary["sameStockOpinionCount"], 2)
        self.assertEqual(summary["stances"], ["긍정", "신중"])
        self.assertEqual(summary["latestTrend"], "긍정에서 신중으로 변화")

    def test_history_summary_can_query_code_saved_record_by_exact_stock_name(self):
        opinion_history.save_opinion(
            self.record("v1", "긍정", "2026-06-01T10:00:00+09:00", "hash1"),
            db_path=self.db_path,
            store="sqlite",
        )

        summary = opinion_history.history_summary(
            "삼성전자",
            channel_id="UCa",
            db_path=self.db_path,
            store="sqlite",
            period_days=365,
        )

        self.assertEqual(summary["sameStockOpinionCount"], 1)
        self.assertEqual(summary["latestTrend"], "첫 기록이에요")

    def test_history_detail_uses_channel_name_when_channel_id_is_missing(self):
        opinion_history.save_opinion(
            self.record("v1", "긍정", "2026-06-01T10:00:00+09:00", "hash1", channel_id=""),
            db_path=self.db_path,
            store="sqlite",
        )
        opinion_history.save_opinion(
            self.record("v2", "부정", "2026-06-11T10:00:00+09:00", "hash2", channel_id=""),
            db_path=self.db_path,
            store="sqlite",
        )

        detail = opinion_history.history_detail(
            "삼성전자",
            stock_code="005930",
            channel_name="A 유튜버",
            db_path=self.db_path,
            store="sqlite",
            period_days=365,
        )

        self.assertEqual(detail["channelName"], "A 유튜버")
        self.assertEqual([row["stance"] for row in detail["opinions"]], ["부정", "긍정"])
        self.assertEqual(detail["opinions"][0]["url"], "https://www.youtube.com/watch?v=v2")

    def test_opinion_record_skips_non_mentioned_result(self):
        record = opinion_history.opinion_record(
            "삼성전자",
            {"channel": "A", "videoId": "v1"},
            {"mentioned": False, "stance": "단순언급"},
            "hash",
        )

        self.assertIsNone(record)


if __name__ == "__main__":
    unittest.main()
