import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analyze
import config


class AnalysisCacheTest(unittest.TestCase):
    def test_same_transcript_is_analyzed_once(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(config, "ANALYSIS_CACHE_DIR", Path(tmp)), \
             mock.patch.object(config, "FORCE_ANALYSIS_REFRESH", False), \
             mock.patch.object(analyze, "analyze_video", return_value={"verdict": "신중"}) as call:
            first, first_cached = analyze.analyze_video_cached("video1", "같은 자막")
            second, second_cached = analyze.analyze_video_cached("video1", "같은 자막")
        self.assertEqual(first, second)
        self.assertFalse(first_cached)
        self.assertTrue(second_cached)
        call.assert_called_once()

    def test_changed_transcript_invalidates_analysis(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(config, "ANALYSIS_CACHE_DIR", Path(tmp)), \
             mock.patch.object(config, "FORCE_ANALYSIS_REFRESH", False), \
             mock.patch.object(analyze, "analyze_video", side_effect=[
                 {"verdict": "신중"}, {"verdict": "낙관"},
             ]) as call:
            analyze.analyze_video_cached("video2", "이전 자막")
            result, cached = analyze.analyze_video_cached("video2", "수정된 자막")
        self.assertEqual(result["verdict"], "낙관")
        self.assertFalse(cached)
        self.assertEqual(call.call_count, 2)


if __name__ == "__main__":
    unittest.main()
