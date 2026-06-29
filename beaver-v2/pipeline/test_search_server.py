import unittest
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


if __name__ == "__main__":
    unittest.main()
