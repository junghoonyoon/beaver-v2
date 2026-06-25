import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import youtube


class TranscriptCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(config, "TRANSCRIPT_CACHE_DIR", self.root / "transcripts"),
            mock.patch.object(config, "MANUAL_TRANSCRIPT_DIR", self.root / "manual"),
            mock.patch.object(config, "TRANSCRIPT_REQUEST_DELAY_SECONDS", 0),
            mock.patch.object(config, "TRANSCRIPT_FAILURE_TTL_HOURS", 12),
            mock.patch.object(config, "FORCE_TRANSCRIPT_REFRESH", False),
            mock.patch.object(config, "SUPADATA_API_KEY", ""),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def test_success_is_reused_without_network(self):
        with mock.patch.object(youtube, "_innertube_transcript", return_value="자막 본문") as inner, \
             mock.patch.object(youtube, "_free_transcript", return_value=None):
            self.assertEqual(youtube.fetch_transcript("video1"), "자막 본문")
            self.assertEqual(youtube.fetch_transcript("video1"), "자막 본문")
        self.assertEqual(inner.call_count, 1)
        self.assertTrue(youtube.LAST_TRANSCRIPT_FROM_CACHE)

    def test_recent_failure_suppresses_repeated_requests(self):
        with mock.patch.object(youtube, "_innertube_transcript", return_value=None) as inner, \
             mock.patch.object(youtube, "_free_transcript", return_value=None):
            self.assertIsNone(youtube.fetch_transcript("video2"))
            self.assertIsNone(youtube.fetch_transcript("video2"))
        self.assertEqual(inner.call_count, 1)
        self.assertTrue(youtube.LAST_TRANSCRIPT_FROM_CACHE)

    def test_expired_failure_is_retried(self):
        cache_dir = config.TRANSCRIPT_CACHE_DIR
        cache_dir.mkdir(parents=True)
        old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=13)
        (cache_dir / "video3.json").write_text(json.dumps({
            "status": "failed", "source": "all", "fetchedAt": old.isoformat(), "error": "old",
        }), encoding="utf-8")
        with mock.patch.object(youtube, "_innertube_transcript", return_value="새 자막") as inner:
            self.assertEqual(youtube.fetch_transcript("video3"), "새 자막")
        inner.assert_called_once()

    def test_manual_transcript_precedes_network(self):
        config.MANUAL_TRANSCRIPT_DIR.mkdir(parents=True)
        (config.MANUAL_TRANSCRIPT_DIR / "video4.txt").write_text("직접 만든 자막", encoding="utf-8")
        with mock.patch.object(youtube, "_innertube_transcript") as inner:
            self.assertEqual(youtube.fetch_transcript("video4"), "직접 만든 자막")
        inner.assert_not_called()
        self.assertEqual(youtube.LAST_TRANSCRIPT_SOURCE, "manual")

    def test_upload_playlist_is_derived_without_api(self):
        with mock.patch.object(youtube, "_get") as api:
            self.assertEqual(youtube._uploads_playlist("UCabc"), "UUabc")
        api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
