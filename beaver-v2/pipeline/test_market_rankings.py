import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import market_rankings


class FakeJsonResponse:
    ok = True
    status_code = 200
    text = ""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class MarketRankingsTest(unittest.TestCase):
    def test_fetch_kr_sorts_by_market_cap_and_skips_preferred(self):
        def fake_get(url, timeout=30):
            if "basDt=" not in url:
                return FakeJsonResponse({"response": {"header": {"resultCode": "00"}, "body": {
                    "totalCount": 1,
                    "items": {"item": [{"basDt": "20260626", "srtnCd": "A005930",
                                        "mrktCtg": "KOSPI", "itmsNm": "삼성전자",
                                        "mrktTotAmt": "1000"}]}}}})
            return FakeJsonResponse({"response": {"header": {"resultCode": "00"}, "body": {
                "totalCount": 3,
                "items": {"item": [
                    {"basDt": "20260626", "srtnCd": "A005930", "mrktCtg": "KOSPI",
                     "itmsNm": "삼성전자", "mrktTotAmt": "1000"},
                    {"basDt": "20260626", "srtnCd": "A000660", "mrktCtg": "KOSPI",
                     "itmsNm": "SK하이닉스", "mrktTotAmt": "2000"},
                    {"basDt": "20260626", "srtnCd": "A005935", "mrktCtg": "KOSPI",
                     "itmsNm": "삼성전자우", "mrktTotAmt": "3000"},
                ]}}}})

        with mock.patch.object(config, "KRX_API_KEY", "dummy"), \
             mock.patch.object(market_rankings.requests, "get", side_effect=fake_get):
            payload = market_rankings.fetch_kr(limit=2)

        self.assertEqual(payload["baseDate"], "20260626")
        self.assertEqual([row["name"] for row in payload["rows"]], ["SK하이닉스", "삼성전자"])
        self.assertEqual(payload["rows"][0]["code"], "000660")

    def test_fetch_us_parses_nasdaq_screener_table(self):
        payload = {"data": {"table": {"rows": [
            {"symbol": "MSFT", "name": "Microsoft Corporation Common Stock", "marketCap": "3000.00"},
            {"symbol": "NVDA", "name": "NVIDIA Corporation Common Stock", "marketCap": "4000.00"},
            {"symbol": "ZERO", "name": "Zero Inc. Common Stock", "marketCap": "0.00"},
        ]}}}

        with mock.patch.object(market_rankings.requests, "get", return_value=FakeJsonResponse(payload)):
            result = market_rankings.fetch_us(limit=2)

        self.assertEqual([row["code"] for row in result["rows"]], ["NVDA", "MSFT"])
        self.assertEqual(result["rows"][0]["name"], "엔비디아")
        self.assertEqual(result["rows"][1]["name"], "마이크로소프트")

    def test_refresh_keeps_cached_market_when_fetch_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(config, "CACHE_DIR", Path(tmpdir)), \
             mock.patch.object(config, "MARKET_RANKINGS_REFRESH_HOURS", 0), \
             mock.patch.object(market_rankings.remote_cache, "download_to_file", return_value=False), \
             mock.patch.object(market_rankings.remote_cache, "upload_json", return_value=True):
            market_rankings.save_cache({
                "fetchedAt": "2026-06-29T00:00:00+09:00",
                "markets": {
                    "kr": {"rows": [{"name": "캐시국내"}], "source": "KRX", "error": ""},
                    "us": {"rows": [{"name": "캐시미국"}], "source": "NASDAQ", "error": ""},
                },
            })
            with mock.patch.object(market_rankings, "fetch_kr", side_effect=RuntimeError("kr fail")), \
                 mock.patch.object(market_rankings, "fetch_us", side_effect=RuntimeError("us fail")):
                refreshed = market_rankings.refresh(force=True)

        self.assertEqual(refreshed["markets"]["kr"]["rows"][0]["name"], "캐시국내")
        self.assertIn("kr fail", refreshed["markets"]["kr"]["error"])
        self.assertEqual(refreshed["markets"]["us"]["rows"][0]["name"], "캐시미국")

    def test_quotes_for_kr_prefers_naver_current_quote(self):
        naver_quote = {"005930": {"changeRateText": "-9.06%", "quoteSource": "NAVER"}}
        krx_quote = {"005930": {"changeRateText": "-5.84%", "quoteSource": "KRX"}}
        with mock.patch.object(market_rankings, "fetch_kr_quotes_naver", return_value=naver_quote), \
             mock.patch.object(market_rankings, "fetch_kr_quotes", return_value=krx_quote) as krx:
            quotes = market_rankings.quotes_for_rows("kr", [{"code": "005930"}])

        self.assertEqual(quotes["005930"]["changeRateText"], "-9.06%")
        self.assertEqual(quotes["005930"]["quoteSource"], "NAVER")
        krx.assert_not_called()


if __name__ == "__main__":
    unittest.main()
