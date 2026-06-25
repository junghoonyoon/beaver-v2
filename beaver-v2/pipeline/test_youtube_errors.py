import unittest
import datetime
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

import config
import stock_search
import youtube


class FakeResponse:
    ok = False
    status_code = 404
    text = "not found"

    def json(self):
        return {"error": {"message": "playlist not found"}}


class YouTubeErrorTest(unittest.TestCase):
    def test_api_error_does_not_expose_key_url(self):
        with mock.patch.object(youtube.requests, "get", return_value=FakeResponse()):
            with self.assertRaises(youtube.YouTubeAPIError) as caught:
                youtube._get("playlistItems", playlistId="bad")
        message = str(caught.exception)
        self.assertIn("404", message)
        self.assertNotIn("key=", message)
        self.assertNotIn("googleapis.com", message)

    def test_bad_channel_does_not_stop_other_channels(self):
        channels = [
            {"name": "고장 채널", "type": "종목"},
            {"name": "정상 채널", "type": "종목"},
        ]
        video = {
            "channel": "정상 채널",
            "videoId": "ok",
            "title": "제목",
            "publishedAt": datetime.datetime(2026, 6, 24, 9, 0, 0),
            "views": 10,
            "durationSec": 60,
            "url": "https://example.com",
        }

        def recent(channel, **_kwargs):
            if channel["name"] == "고장 채널":
                raise youtube.YouTubeAPIError("playlistItems", 404, "not found")
            return [video.copy()]

        with mock.patch.object(youtube, "recent_uploads", side_effect=recent), \
             mock.patch.object(youtube, "fetch_transcript", return_value="자막"), \
             TemporaryDirectory() as tmpdir, \
             mock.patch.object(config, "CACHE_DIR", Path(tmpdir)), \
             mock.patch.object(config, "SEARCH_INDEX_JSON", Path(tmpdir) / "search_index.json"):
            payload = stock_search.sync_index(channels)
        rows = payload["videos"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["channel"], "정상 채널")


if __name__ == "__main__":
    unittest.main()
