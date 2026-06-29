"""국내/미국 시가총액 상위 종목을 캐시한다."""
import datetime
import json
import re
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

import config
import remote_cache

KST = ZoneInfo("Asia/Seoul")
CACHE_PATH = config.CACHE_DIR / "market_rankings.json"
REMOTE_PATH = "market_rankings.json"
NASDAQ_SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks"

FALLBACK_KR = [
    ("삼성전자", "005930", "KOSPI"),
    ("SK하이닉스", "000660", "KOSPI"),
    ("LG에너지솔루션", "373220", "KOSPI"),
    ("삼성바이오로직스", "207940", "KOSPI"),
    ("현대차", "005380", "KOSPI"),
    ("기아", "000270", "KOSPI"),
    ("셀트리온", "068270", "KOSPI"),
    ("KB금융", "105560", "KOSPI"),
    ("NAVER", "035420", "KOSPI"),
    ("POSCO홀딩스", "005490", "KOSPI"),
]

FALLBACK_US = [
    ("엔비디아", "NVDA", "NASDAQ"),
    ("마이크로소프트", "MSFT", "NASDAQ"),
    ("애플", "AAPL", "NASDAQ"),
    ("아마존", "AMZN", "NASDAQ"),
    ("알파벳", "GOOGL", "NASDAQ"),
    ("메타", "META", "NASDAQ"),
    ("브로드컴", "AVGO", "NASDAQ"),
    ("테슬라", "TSLA", "NASDAQ"),
    ("버크셔해서웨이", "BRK/B", "NYSE"),
    ("일라이릴리", "LLY", "NYSE"),
]

US_DISPLAY_NAMES = {
    "AAPL": "애플",
    "MSFT": "마이크로소프트",
    "NVDA": "엔비디아",
    "AMZN": "아마존",
    "GOOGL": "알파벳",
    "GOOG": "알파벳",
    "META": "메타",
    "AVGO": "브로드컴",
    "TSLA": "테슬라",
    "BRK/B": "버크셔해서웨이",
    "BRK.A": "버크셔해서웨이",
    "BRK.B": "버크셔해서웨이",
    "LLY": "일라이릴리",
    "JPM": "JP모건",
    "WMT": "월마트",
    "TSM": "TSMC",
    "SPCX": "스페이스X",
    "MU": "마이크론",
    "AMD": "AMD",
    "ASML": "ASML",
    "V": "비자",
    "ORCL": "오라클",
    "MA": "마스터카드",
    "NFLX": "넷플릭스",
    "COST": "코스트코",
}


class MarketRankingError(RuntimeError):
    pass


def _now():
    return datetime.datetime.now(KST)


def _cache_path():
    return config.CACHE_DIR / "market_rankings.json"


def _compact_date(value):
    return str(value or "").replace("-", "").strip()


def _number(value):
    text = str(value or "").replace(",", "").replace("$", "").strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def _format_market_cap(value, currency):
    value = int(value or 0)
    if currency == "KRW":
        trillion = value / 1_000_000_000_000
        if trillion >= 1:
            return f"{trillion:.1f}조원"
        return f"{value / 100_000_000:.0f}억원"
    trillion = value / 1_000_000_000_000
    if trillion >= 1:
        return f"${trillion:.2f}T"
    return f"${value / 1_000_000_000:.0f}B"


def _fallback_rows(items, market, source):
    return [
        {
            "rank": idx,
            "name": name,
            "code": code,
            "market": exchange,
            "marketCap": None,
            "marketCapText": "",
            "currency": "KRW" if market == "kr" else "USD",
            "source": source,
        }
        for idx, (name, code, exchange) in enumerate(items, 1)
    ]


def _api_url(service_key, page_no, num_rows, bas_dt=None):
    params = {"pageNo": page_no, "numOfRows": num_rows, "resultType": "json"}
    if bas_dt:
        params["basDt"] = bas_dt
    tail = urlencode(params)
    if "%" in service_key:
        return f"{config.KRX_STOCK_PRICE_API_URL}?serviceKey={service_key}&{tail}"
    return f"{config.KRX_STOCK_PRICE_API_URL}?{urlencode({'serviceKey': service_key})}&{tail}"


def _krx_items_from_payload(payload):
    response = payload.get("response", {})
    header = response.get("header", {})
    code = str(header.get("resultCode", "00"))
    if code not in ("00", "0", ""):
        raise MarketRankingError(header.get("resultMsg") or f"KRX 오류 {code}")
    body = response.get("body", {})
    items = body.get("items", {})
    rows = items.get("item", []) if isinstance(items, dict) else []
    if isinstance(rows, dict):
        rows = [rows]
    total = int(body.get("totalCount") or len(rows))
    return rows, total


def _get_krx_payload(url, key):
    try:
        response = requests.get(url, timeout=30)
    except requests.RequestException as exc:
        raise MarketRankingError(f"KRX 시세정보 요청 실패: {exc.__class__.__name__}") from exc
    if not response.ok:
        detail = response.text[:200].replace(key, "[serviceKey]")
        raise MarketRankingError(f"KRX 시세정보 HTTP 오류 {response.status_code}: {detail}")
    try:
        return response.json()
    except ValueError as exc:
        raise MarketRankingError("KRX 시세정보 응답을 JSON으로 읽지 못했어요.") from exc


def _latest_kr_base_date(key):
    payload = _get_krx_payload(_api_url(key, 1, 1), key)
    rows, _ = _krx_items_from_payload(payload)
    for row in rows:
        bas = _compact_date(row.get("basDt"))
        if bas:
            return bas
    raise MarketRankingError("KRX 시세정보에서 기준일자를 찾지 못했어요.")


def _is_preferred_stock(name):
    return bool(re.search(r"우(?:B)?$", str(name or "")))


def fetch_kr(limit=10):
    key = (config.KRX_API_KEY or "").strip()
    if not key:
        raise MarketRankingError("공공데이터키가 비어 있어 국내 시총을 갱신할 수 없어요.")

    bas_dt = _latest_kr_base_date(key)
    rows = []
    page_no = 1
    num_rows = 1000
    while True:
        payload = _get_krx_payload(_api_url(key, page_no, num_rows, bas_dt=bas_dt), key)
        page_rows, total = _krx_items_from_payload(payload)
        for raw in page_rows:
            name = str(raw.get("itmsNm") or "").strip()
            code = str(raw.get("srtnCd") or "").strip()
            if code[:1].isalpha():
                code = code[1:]
            market = str(raw.get("mrktCtg") or "").strip()
            market_cap = _number(raw.get("mrktTotAmt"))
            if not name or not code or market not in ("KOSPI", "KOSDAQ") or not market_cap:
                continue
            if _is_preferred_stock(name):
                continue
            rows.append({
                "name": name,
                "code": code,
                "market": market,
                "marketCap": market_cap,
                "marketCapText": _format_market_cap(market_cap, "KRW"),
                "currency": "KRW",
                "source": "KRX",
            })
        if len(page_rows) < num_rows or len(rows) >= total:
            break
        page_no += 1
        if page_no > 50:
            break

    rows.sort(key=lambda row: row["marketCap"], reverse=True)
    top = rows[:limit]
    for idx, row in enumerate(top, 1):
        row["rank"] = idx
    return {"rows": top, "baseDate": bas_dt, "source": "KRX"}


def _nasdaq_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/market-activity/stocks/screener",
    }


def _clean_us_name(name):
    value = str(name or "").strip()
    value = re.sub(r"\s+Common Stock$", "", value, flags=re.I)
    value = re.sub(r"\s+Class [A-Z] Common Stock$", "", value, flags=re.I)
    value = re.sub(r"\s+Inc\.$", "", value, flags=re.I)
    return value.strip() or str(name or "").strip()


def _nasdaq_rows(payload):
    data = payload.get("data") or {}
    if data.get("table"):
        return data.get("table", {}).get("rows") or []
    return data.get("rows") or []


def fetch_us(limit=10):
    params = {
        "tableonly": "true",
        "limit": max(25, limit),
        "offset": 0,
        "sortby": "marketCap",
        "sortorder": "desc",
    }
    try:
        response = requests.get(NASDAQ_SCREENER_URL, params=params, headers=_nasdaq_headers(), timeout=30)
    except requests.RequestException as exc:
        raise MarketRankingError(f"Nasdaq 시총 요청 실패: {exc.__class__.__name__}") from exc
    if not response.ok:
        raise MarketRankingError(f"Nasdaq 시총 HTTP 오류 {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise MarketRankingError("Nasdaq 시총 응답을 JSON으로 읽지 못했어요.") from exc

    rows = []
    seen_names = set()
    for raw in _nasdaq_rows(payload):
        symbol = str(raw.get("symbol") or "").strip()
        market_cap = _number(raw.get("marketCap"))
        if not symbol or not market_cap:
            continue
        display = US_DISPLAY_NAMES.get(symbol) or _clean_us_name(raw.get("name"))
        name_key = display.lower()
        if name_key in seen_names:
            continue
        seen_names.add(name_key)
        rows.append({
            "name": display,
            "english": _clean_us_name(raw.get("name")),
            "code": symbol,
            "market": "US",
            "marketCap": market_cap,
            "marketCapText": _format_market_cap(market_cap, "USD"),
            "currency": "USD",
            "source": "NASDAQ",
        })
    rows.sort(key=lambda row: row["marketCap"], reverse=True)
    top = rows[:limit]
    for idx, row in enumerate(top, 1):
        row["rank"] = idx
    return {"rows": top, "baseDate": None, "source": "NASDAQ"}


def _default_payload():
    return {
        "fetchedAt": _now().isoformat(),
        "markets": {
            "kr": {"rows": _fallback_rows(FALLBACK_KR, "kr", "fallback"), "source": "fallback", "error": ""},
            "us": {"rows": _fallback_rows(FALLBACK_US, "us", "fallback"), "source": "fallback", "error": ""},
        },
    }


def load_cache():
    path = _cache_path()
    if not path.exists():
        remote_cache.download_to_file(REMOTE_PATH, path)
    if not path.exists():
        return _default_payload()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _default_payload()


def cache_is_fresh():
    payload = load_cache()
    fetched_at = payload.get("fetchedAt")
    if not fetched_at:
        return False
    try:
        age = _now() - datetime.datetime.fromisoformat(fetched_at).astimezone(KST)
    except ValueError:
        return False
    return age < datetime.timedelta(hours=config.MARKET_RANKINGS_REFRESH_HOURS)


def save_cache(payload):
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    remote_cache.upload_json(REMOTE_PATH, payload)
    return payload


def refresh(force=False):
    if not force and cache_is_fresh():
        return load_cache()

    previous = load_cache()
    payload = {"fetchedAt": _now().isoformat(), "markets": {}}
    for market, fetcher, fallback in (
        ("kr", fetch_kr, FALLBACK_KR),
        ("us", fetch_us, FALLBACK_US),
    ):
        try:
            payload["markets"][market] = fetcher(limit=10)
            payload["markets"][market]["error"] = ""
        except Exception as exc:
            cached = (previous.get("markets") or {}).get(market)
            if cached and cached.get("rows"):
                payload["markets"][market] = dict(cached)
                payload["markets"][market]["error"] = str(exc)[:200]
            else:
                payload["markets"][market] = {
                    "rows": _fallback_rows(fallback, market, "fallback"),
                    "source": "fallback",
                    "error": str(exc)[:200],
                }
    return save_cache(payload)


def rankings(force=False):
    return refresh(force=force)
