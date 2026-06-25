"""Nasdaq Trader 공개 Symbol Directory로 미국 상장종목을 하루 1회 캐시한다."""
import datetime
import json
import re
import threading
from zoneinfo import ZoneInfo

import requests

import config

KST = ZoneInfo("Asia/Seoul")
_REFRESH_LOCK = threading.Lock()

US_KOREAN_ALIASES = {
    "AAPL": ["애플", "아이폰"],
    "MSFT": ["마이크로소프트", "MS", "Azure"],
    "NVDA": ["엔비디아", "젠슨황", "GPU"],
    "TSLA": ["테슬라", "일론머스크", "전기차"],
    "GOOG": ["구글", "알파벳"],
    "GOOGL": ["구글", "알파벳"],
    "META": ["메타", "페이스북", "인스타그램"],
    "AMZN": ["아마존", "AWS"],
    "NFLX": ["넷플릭스"],
    "AMD": ["AMD", "에이엠디"],
    "INTC": ["인텔", "Intel"],
    "MU": ["마이크론", "마이크론테크놀로지", "Micron"],
    "AVGO": ["브로드컴"],
    "QCOM": ["퀄컴"],
    "ARM": ["암홀딩스", "ARM"],
    "ORCL": ["오라클"],
    "CRM": ["세일즈포스"],
    "ADBE": ["어도비"],
    "PLTR": ["팔란티어", "Palantir"],
    "SMCI": ["슈퍼마이크로", "슈마컴"],
    "COIN": ["코인베이스"],
    "MSTR": ["마이크로스트래티지"],
    "BABA": ["알리바바"],
    "NIO": ["니오"],
    "XPEV": ["샤오펑"],
    "LI": ["리오토"],
    "PDD": ["핀둬둬", "테무"],
    "TSM": ["TSMC", "대만반도체"],
    "ASML": ["ASML", "에이에스엠엘"],
    "SNOW": ["스노우플레이크"],
    "SHOP": ["쇼피파이"],
    "UBER": ["우버"],
    "ABNB": ["에어비앤비"],
    "PYPL": ["페이팔"],
    "DIS": ["디즈니"],
    "NKE": ["나이키"],
    "SBUX": ["스타벅스"],
    "COST": ["코스트코"],
    "WMT": ["월마트"],
    "JPM": ["JP모건", "제이피모건"],
    "BRK.B": ["버크셔", "버크셔해서웨이"],
    "LLY": ["일라이릴리"],
    "NVO": ["노보노디스크"],
}

EXCHANGE_NAMES = {
    "Q": "NASDAQ",
    "N": "NYSE",
    "A": "NYSE American",
    "P": "NYSE Arca",
    "Z": "Cboe BZX",
    "V": "IEX",
}


class UsListedError(RuntimeError):
    pass


def _now():
    return datetime.datetime.now(KST)


def _is_today(value):
    if not value:
        return False
    try:
        return datetime.datetime.fromisoformat(value).astimezone(KST).date() == _now().date()
    except ValueError:
        return False


def _clean_security_name(value):
    name = str(value or "").strip()
    name = re.sub(r"\s+-\s+.*$", "", name)
    name = re.sub(r"\s+Common Stock$", "", name, flags=re.I)
    name = re.sub(r"\s+Class [A-Z] Common Stock$", "", name, flags=re.I)
    name = re.sub(r"\s+Ordinary Shares$", "", name, flags=re.I)
    name = re.sub(r"\s+American Depositary Shares?$", "", name, flags=re.I)
    return name.strip() or str(value or "").strip()


def _symbol_aliases(symbol, security_name):
    aliases = [symbol, security_name, *US_KOREAN_ALIASES.get(symbol, [])]
    if "." in symbol:
        aliases.append(symbol.replace(".", "-"))
    seen = set()
    out = []
    for alias in aliases:
        key = str(alias).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(alias)
    return out


def _request_text(url):
    try:
        response = requests.get(url, timeout=30)
    except requests.RequestException as exc:
        raise UsListedError(f"미국 종목정보 요청 실패: {exc.__class__.__name__}") from exc
    if not response.ok:
        raise UsListedError(f"미국 종목정보 HTTP 오류 {response.status_code}")
    return response.text


def _parse_pipe_file(text):
    lines = [line.rstrip("\n") for line in text.splitlines() if line.strip()]
    if not lines:
        return [], None
    header = lines[0].split("|")
    rows = []
    file_time = None
    for line in lines[1:]:
        if line.startswith("File Creation Time:"):
            file_time = line.split(":", 1)[1].split("|", 1)[0].strip()
            continue
        values = line.split("|")
        if len(values) != len(header):
            continue
        rows.append(dict(zip(header, values)))
    return rows, file_time


def _from_nasdaq_row(row):
    symbol = str(row.get("Symbol") or "").strip()
    name = _clean_security_name(row.get("Security Name"))
    if not symbol or not name or row.get("Test Issue") == "Y":
        return None
    return {
        "baseDate": "",
        "code": symbol,
        "isin": "",
        "market": "NASDAQ",
        "name": name,
        "english": name,
        "corpName": name,
        "aliases": _symbol_aliases(symbol, name),
        "etf": row.get("ETF") == "Y",
        "source": "NASDAQ_TRADER",
    }


def _from_other_row(row):
    symbol = str(row.get("ACT Symbol") or "").strip()
    name = _clean_security_name(row.get("Security Name"))
    if not symbol or not name or row.get("Test Issue") == "Y":
        return None
    exchange = EXCHANGE_NAMES.get(str(row.get("Exchange") or "").strip(), str(row.get("Exchange") or "").strip())
    return {
        "baseDate": "",
        "code": symbol,
        "isin": "",
        "market": exchange or "US",
        "name": name,
        "english": name,
        "corpName": name,
        "aliases": _symbol_aliases(symbol, name),
        "etf": row.get("ETF") == "Y",
        "source": "NASDAQ_TRADER",
    }


def load_cache():
    if not config.US_LISTED_JSON.exists():
        return {"fetchedAt": None, "stocks": []}
    try:
        return json.loads(config.US_LISTED_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"fetchedAt": None, "stocks": []}


def load_cached_stocks():
    return load_cache().get("stocks", [])


def cache_status():
    payload = load_cache()
    stocks = payload.get("stocks", [])
    return {
        "enabled": True,
        "cached": bool(stocks),
        "count": len(stocks),
        "baseDate": payload.get("baseDate"),
        "fetchedAt": payload.get("fetchedAt"),
        "freshToday": _is_today(payload.get("fetchedAt")),
    }


def cache_is_fresh():
    payload = load_cache()
    fetched_at = payload.get("fetchedAt")
    if not fetched_at:
        return False
    try:
        age = _now() - datetime.datetime.fromisoformat(fetched_at).astimezone(KST)
    except ValueError:
        return False
    return age < datetime.timedelta(hours=config.US_LISTED_REFRESH_HOURS)


def fetch_all():
    stocks = []
    seen = set()
    file_times = []

    nasdaq_rows, nasdaq_time = _parse_pipe_file(_request_text(config.NASDAQ_LISTED_URL))
    if nasdaq_time:
        file_times.append(nasdaq_time)
    for raw in nasdaq_rows:
        row = _from_nasdaq_row(raw)
        if not row or row["code"] in seen:
            continue
        seen.add(row["code"])
        stocks.append(row)

    other_rows, other_time = _parse_pipe_file(_request_text(config.OTHER_LISTED_URL))
    if other_time:
        file_times.append(other_time)
    for raw in other_rows:
        row = _from_other_row(raw)
        if not row or row["code"] in seen:
            continue
        seen.add(row["code"])
        stocks.append(row)

    stocks.sort(key=lambda row: (row.get("market", ""), row.get("code", "")))
    return stocks, " / ".join(file_times)


def save_cache(stocks, base_date=None):
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetchedAt": _now().isoformat(),
        "baseDate": base_date,
        "count": len(stocks),
        "stocks": stocks,
    }
    tmp = config.US_LISTED_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(config.US_LISTED_JSON)
    return payload


def refresh(force=False):
    with _REFRESH_LOCK:
        if not force and cache_is_fresh():
            return load_cache(), False
        stocks, base_date = fetch_all()
        return save_cache(stocks, base_date=base_date), True


def refresh_if_needed_async():
    if cache_is_fresh():
        return None

    def run():
        try:
            payload, changed = refresh(force=False)
            if changed:
                print(f"✅ 미국 상장종목정보 갱신: {payload.get('count', 0)}개")
        except Exception as exc:
            print(f"⚠️ 미국 상장종목정보 갱신 실패: {str(exc)[:160]}")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
