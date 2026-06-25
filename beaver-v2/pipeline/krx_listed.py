"""공공데이터포털 KRX 상장종목정보를 하루 1회 캐시한다."""
import datetime
import json
import threading
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

import config

KST = ZoneInfo("Asia/Seoul")
_REFRESH_LOCK = threading.Lock()


class KrxListedError(RuntimeError):
    pass


def _now():
    return datetime.datetime.now(KST)


def _compact_date(value):
    return str(value or "").replace("-", "").strip()


def _is_today(value):
    if not value:
        return False
    try:
        return datetime.datetime.fromisoformat(value).astimezone(KST).date() == _now().date()
    except ValueError:
        return False


def _api_url(service_key, page_no, num_rows, bas_dt=None):
    """공공데이터 키는 인코딩키/디코딩키가 섞여 들어오므로 이중 인코딩을 피한다."""
    params = {
        "pageNo": page_no,
        "numOfRows": num_rows,
        "resultType": "json",
    }
    if bas_dt:
        params["basDt"] = bas_dt
    tail = urlencode(params)
    if "%" in service_key:
        return f"{config.KRX_LISTED_API_URL}?serviceKey={service_key}&{tail}"
    return f"{config.KRX_LISTED_API_URL}?{urlencode({'serviceKey': service_key})}&{tail}"


def _items_from_payload(payload):
    response = payload.get("response", {})
    header = response.get("header", {})
    result_code = str(header.get("resultCode", "00"))
    if result_code not in ("00", "0", ""):
        raise KrxListedError(header.get("resultMsg") or f"공공데이터 오류 {result_code}")

    body = response.get("body", {})
    items = body.get("items", {})
    rows = items.get("item", []) if isinstance(items, dict) else []
    if isinstance(rows, dict):
        rows = [rows]
    total = int(body.get("totalCount") or len(rows))
    return rows, total


def _normalize_row(row):
    name = str(row.get("itmsNm") or "").strip()
    code = str(row.get("srtnCd") or "").strip()
    if code[:1].isalpha():  # 공공데이터 단축코드는 'A005930' 형태 → 6자리 코드로 정규화
        code = code[1:]
    if not name or not code:
        return None
    corp_name = str(row.get("corpNm") or "").strip()
    aliases = []
    if corp_name and corp_name != name:
        aliases.append(corp_name)
    return {
        "baseDate": _compact_date(row.get("basDt")),
        "code": code,
        "isin": str(row.get("isinCd") or "").strip(),
        "market": str(row.get("mrktCtg") or "").strip(),
        "name": name,
        "corpName": corp_name,
        "aliases": aliases,
        "source": "KRX",
    }


def load_cache():
    if not config.KRX_LISTED_JSON.exists():
        return {"fetchedAt": None, "baseDate": None, "stocks": []}
    try:
        return json.loads(config.KRX_LISTED_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"fetchedAt": None, "baseDate": None, "stocks": []}


def load_cached_stocks():
    return load_cache().get("stocks", [])


def cache_status():
    payload = load_cache()
    stocks = payload.get("stocks", [])
    return {
        "enabled": bool(config.KRX_API_KEY),
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
    return age < datetime.timedelta(hours=config.KRX_LISTED_REFRESH_HOURS)


def _get_payload(url, key):
    try:
        response = requests.get(url, timeout=30)
    except requests.RequestException as exc:
        reason = exc.__class__.__name__
        raise KrxListedError(f"KRX 상장종목정보 요청 실패: {reason}") from exc
    if not response.ok:
        detail = response.text[:300].replace(key, "[serviceKey]")
        raise KrxListedError(f"KRX 상장종목정보 HTTP 오류 {response.status_code}: {detail}")
    try:
        return response.json()
    except ValueError as exc:
        raise KrxListedError("KRX 상장종목정보 응답을 JSON으로 읽지 못했어요.") from exc


def _latest_base_date(key):
    """basDt 없이 호출하면 수년치 일별 누적(수백만 건)이 와 무한 루프에 빠진다.
    최신 1건만 조회해 가장 최근 영업일(basDt)을 얻은 뒤, 그 날짜로만 전종목을 받는다."""
    payload = _get_payload(_api_url(key, 1, 1), key)
    rows, _ = _items_from_payload(payload)
    for raw in rows:
        bas = _compact_date(raw.get("basDt"))
        if bas:
            return bas
    raise KrxListedError("KRX 응답에서 기준일자(basDt)를 찾지 못했어요.")


def fetch_all(service_key=None, num_rows=1000):
    """KRX 상장종목 전체를 공공데이터포털에서 받아온다. (최신 영업일 1일치만)"""
    key = (service_key or config.KRX_API_KEY or "").strip()
    if not key:
        raise KrxListedError("공공데이터키가 비어 있어 KRX 종목정보를 갱신할 수 없어요.")

    bas_dt = _latest_base_date(key)
    page_no = 1
    total = None
    rows = []
    seen = set()
    while True:
        payload = _get_payload(_api_url(key, page_no, num_rows, bas_dt=bas_dt), key)

        page_rows, total = _items_from_payload(payload)
        if not page_rows:
            break
        for raw in page_rows:
            row = _normalize_row(raw)
            if not row:
                continue
            key_tuple = (row["code"], row["isin"])
            if key_tuple in seen:
                continue
            seen.add(key_tuple)
            rows.append(row)
        if total is not None and len(rows) >= total:
            break
        if len(page_rows) < num_rows:
            break
        page_no += 1
        if page_no > 50:  # 안전장치: 한 영업일 상장종목이 5만 개를 넘을 수 없음
            break

    rows.sort(key=lambda row: (row.get("market", ""), row.get("name", ""), row.get("code", "")))
    return rows


def save_cache(stocks):
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    base_dates = [row.get("baseDate") for row in stocks if row.get("baseDate")]
    payload = {
        "fetchedAt": _now().isoformat(),
        "baseDate": max(base_dates) if base_dates else None,
        "count": len(stocks),
        "stocks": stocks,
    }
    tmp = config.KRX_LISTED_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(config.KRX_LISTED_JSON)
    return payload


def refresh(force=False):
    """필요할 때만 KRX 종목 마스터를 갱신한다."""
    with _REFRESH_LOCK:
        if not force and cache_is_fresh():
            return load_cache(), False
        stocks = fetch_all()
        return save_cache(stocks), True


def refresh_if_needed_async():
    """서버 시작을 막지 않도록 백그라운드에서 하루 1회 갱신한다."""
    if not config.KRX_API_KEY or cache_is_fresh():
        return None

    def run():
        try:
            payload, changed = refresh(force=False)
            if changed:
                print(f"✅ KRX 상장종목정보 갱신: {payload.get('count', 0)}개 · 기준일 {payload.get('baseDate') or '-'}")
        except Exception as exc:
            print(f"⚠️ KRX 상장종목정보 갱신 실패: {str(exc)[:160]}")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
