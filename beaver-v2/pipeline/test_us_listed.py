import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import us_listed


NASDAQ_TXT = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
INTC|Intel Corporation - Common Stock|Q|N|N|100|N|N
TEST|Test Company - Common Stock|Q|Y|N|100|N|N
File Creation Time: 0625202618:04|||||||
"""

OTHER_TXT = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
TSM|Taiwan Semiconductor Manufacturing Company Ltd. American Depositary Shares|N|TSM|N|100|N|TSM
File Creation Time: 0625202618:04|||||||
"""


class FakeResponse:
    ok = True
    status_code = 200

    def __init__(self, text):
        self.text = text


class UsListedTest(unittest.TestCase):
    def test_fetch_all_parses_nasdaq_and_other_listed(self):
        def fake_get(url, timeout=30):
            if "nasdaqlisted" in url:
                return FakeResponse(NASDAQ_TXT)
            return FakeResponse(OTHER_TXT)

        with mock.patch.object(us_listed.requests, "get", side_effect=fake_get):
            rows, base_date = us_listed.fetch_all()

        by_code = {row["code"]: row for row in rows}
        self.assertIn("INTC", by_code)
        self.assertIn("TSM", by_code)
        self.assertNotIn("TEST", by_code)
        self.assertEqual(by_code["INTC"]["name"], "Intel Corporation")
        self.assertEqual(by_code["INTC"]["market"], "NASDAQ")
        self.assertIn("인텔", by_code["INTC"]["aliases"])
        self.assertEqual(by_code["TSM"]["market"], "NYSE")
        self.assertIn("0625202618:04", base_date)

    def test_save_and_status(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(config, "CACHE_DIR", Path(tmpdir)), \
             mock.patch.object(config, "US_LISTED_JSON", Path(tmpdir) / "us_listed_stocks.json"):
            us_listed.save_cache([{"code": "INTC", "name": "Intel Corporation"}], base_date="today")
            payload = json.loads(config.US_LISTED_JSON.read_text(encoding="utf-8"))
            status = us_listed.cache_status()
        self.assertEqual(payload["baseDate"], "today")
        self.assertEqual(status["count"], 1)
        self.assertTrue(status["cached"])
        self.assertTrue(status["enabled"])


if __name__ == "__main__":
    unittest.main()
