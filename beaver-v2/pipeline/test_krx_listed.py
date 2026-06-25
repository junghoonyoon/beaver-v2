import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import krx_listed


class FakeResponse:
    ok = True
    status_code = 200

    def json(self):
        return {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": {
                    "totalCount": 1,
                    "items": {
                        "item": [{
                            "basDt": "20260624",
                            "srtnCd": "005930",
                            "isinCd": "KR7005930003",
                            "mrktCtg": "KOSPI",
                            "itmsNm": "삼성전자",
                            "corpNm": "삼성전자 주식회사",
                        }]
                    },
                },
            }
        }


class KrxListedTest(unittest.TestCase):
    def test_fetch_all_normalizes_public_data_rows(self):
        with mock.patch.object(krx_listed.requests, "get", return_value=FakeResponse()):
            rows = krx_listed.fetch_all(service_key="dummy")
        self.assertEqual(rows[0]["baseDate"], "20260624")
        self.assertEqual(rows[0]["code"], "005930")
        self.assertEqual(rows[0]["isin"], "KR7005930003")
        self.assertEqual(rows[0]["market"], "KOSPI")
        self.assertEqual(rows[0]["name"], "삼성전자")
        self.assertEqual(rows[0]["corpName"], "삼성전자 주식회사")

    def test_fetch_all_pins_latest_basdt_and_terminates(self):
        """basDt 없이 부르면 406만 건이 와 무한 루프에 빠진다.
        최신 영업일을 고정하고 그 날짜로만 받아 종료되는지 검증한다."""
        calls = []

        class R:
            ok = True
            status_code = 200

            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

        def fake_get(url, *args, **kwargs):
            calls.append(url)
            if "basDt=" not in url:
                # 기준일자 탐색용 1건 조회 (전체 누적 totalCount는 거대)
                return R({"response": {"header": {"resultCode": "00"}, "body": {
                    "totalCount": 4067580,
                    "items": {"item": [{"basDt": "20260623", "srtnCd": "A005930",
                                        "isinCd": "KR7005930003", "mrktCtg": "KOSPI",
                                        "itmsNm": "삼성전자", "corpNm": "삼성전자 주식회사"}]}}}})
            # basDt 고정 시: 해당 영업일 종목만 (작은 totalCount)
            return R({"response": {"header": {"resultCode": "00"}, "body": {
                "totalCount": 2,
                "items": {"item": [
                    {"basDt": "20260623", "srtnCd": "A005930", "isinCd": "KR7005930003",
                     "mrktCtg": "KOSPI", "itmsNm": "삼성전자", "corpNm": "삼성전자 주식회사"},
                    {"basDt": "20260623", "srtnCd": "A000660", "isinCd": "KR7000660001",
                     "mrktCtg": "KOSPI", "itmsNm": "SK하이닉스", "corpNm": "에스케이하이닉스"},
                ]}}}})

        with mock.patch.object(krx_listed.requests, "get", side_effect=fake_get):
            rows = krx_listed.fetch_all(service_key="dummy")

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["code"], "000660")  # 'A' 접두 제거 + 정렬
        self.assertTrue(any("basDt=20260623" in u for u in calls))
        self.assertLessEqual(len(calls), 5)  # 무한 루프가 아님

    def test_save_and_status(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(config, "CACHE_DIR", Path(tmpdir)), \
             mock.patch.object(config, "KRX_LISTED_JSON", Path(tmpdir) / "krx_listed_stocks.json"), \
             mock.patch.object(config, "KRX_API_KEY", "dummy"):
            krx_listed.save_cache([{"baseDate": "20260624", "code": "005930", "name": "삼성전자"}])
            payload = json.loads(config.KRX_LISTED_JSON.read_text(encoding="utf-8"))
            status = krx_listed.cache_status()
        self.assertEqual(payload["baseDate"], "20260624")
        self.assertEqual(status["count"], 1)
        self.assertTrue(status["cached"])
        self.assertTrue(status["enabled"])


if __name__ == "__main__":
    unittest.main()
