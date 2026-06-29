"""종목 검색 인덱스 생성과 주문형 종목 의견 분석."""
import datetime
import hashlib
import json
import re
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import config
import krx_listed
import remote_cache
import us_listed

KST = ZoneInfo("Asia/Seoul")
_STOCK_CACHE_VERSION = 5
_SEARCH_INDEX_VERSION = 2
_REMOTE_INDEX_CHECK_INTERVAL_SECONDS = 60
_REMOTE_INDEX_CHECKED_AT = 0
CHOSEONG = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
INITIAL_CHARS = set(CHOSEONG)

KNOWN_ALIASES = {
    "삼성전자": ["삼성전자", "삼전"],
    "삼성SDS": ["삼성SDS", "삼성에스디에스"],
    "삼성전기": ["삼성전기"],
    "삼성SDI": ["삼성SDI", "삼성에스디아이"],
    "삼성바이오로직스": ["삼성바이오로직스", "삼바"],
    "삼성물산": ["삼성물산"],
    "삼성생명": ["삼성생명"],
    "삼성화재": ["삼성화재"],
    "삼성중공업": ["삼성중공업"],
    "삼성증권": ["삼성증권"],
    "삼성카드": ["삼성카드"],
    "삼성E&A": ["삼성E&A", "삼성엔지니어링", "삼성이앤에이"],
    "LS": ["LS", "엘에스"],
    "LS ELECTRIC": ["LS ELECTRIC", "LS일렉트릭", "LS 일렉트릭", "엘에스일렉트릭"],
    "LS에코에너지": ["LS에코에너지", "LS 에코에너지", "엘에스에코에너지"],
    "LS마린솔루션": ["LS마린솔루션", "LS 마린솔루션", "엘에스마린솔루션"],
    "LS네트웍스": ["LS네트웍스", "LS 네트웍스", "엘에스네트웍스"],
    "LS머트리얼즈": ["LS머트리얼즈", "LS 머트리얼즈", "엘에스머트리얼즈"],
    "SK하이닉스": ["SK하이닉스", "SK 하이닉스", "하이닉스"],
    "SK이노베이션": ["SK이노베이션", "SK 이노베이션"],
    "SK텔레콤": ["SK텔레콤", "SK 텔레콤"],
    "SK스퀘어": ["SK스퀘어", "SK 스퀘어"],
    "네이버": ["네이버", "NAVER"],
    "카카오": ["카카오", "KAKAO"],
    "카카오뱅크": ["카카오뱅크"],
    "카카오페이": ["카카오페이"],
    "엔비디아": ["엔비디아", "NVIDIA"],
    "마이크론": ["마이크론", "마이크론테크놀로지", "Micron"],
    "Intel Corporation": ["인텔", "Intel", "INTC"],
    "Advanced Micro Devices": ["AMD", "에이엠디"],
    "Palantir Technologies Inc.": ["팔란티어", "Palantir", "PLTR"],
    "Meta Platforms Inc.": ["메타", "페이스북", "인스타그램", "META"],
    "Amazon.com Inc.": ["아마존", "AWS", "AMZN"],
    "Netflix Inc.": ["넷플릭스", "NFLX"],
    "테슬라": ["테슬라", "TESLA"],
    "애플": ["애플", "APPLE"],
    "마이크로소프트": ["마이크로소프트", "Microsoft", "MSFT"],
    "구글": ["구글", "알파벳", "Google", "Alphabet"],
    "현대차": ["현대차", "현대자동차"],
    "기아": ["기아", "기아차"],
    "LG전자": ["LG전자", "엘지전자"],
    "LG에너지솔루션": ["LG에너지솔루션", "엘지에너지솔루션", "LG엔솔", "엘지엔솔"],
    "LG화학": ["LG화학", "엘지화학"],
    "한화에어로스페이스": ["한화에어로스페이스", "한화에어로"],
    "나노신소재": ["나노신소재"],
    "나노팀": ["나노팀"],
    "나무가": ["나무가"],
    "나스미디어": ["나스미디어"],
    "나이스정보통신": ["나이스정보통신", "NICE정보통신"],
    "나이스디앤비": ["나이스디앤비", "NICE디앤비"],
    "나우IB": ["나우IB", "나우아이비"],
    "나라엠앤디": ["나라엠앤디"],
    "나라셀라": ["나라셀라"],
    "나인테크": ["나인테크"],
}

FALLBACK_STOCK_MASTER = [
    {"name": "삼성전자", "code": "005930", "market": "KOSPI", "english": "Samsung Electronics", "aliases": ["삼전"], "keywords": ["갤럭시", "Galaxy", "반도체", "메모리"]},
    {"name": "삼성전자우", "code": "005935", "market": "KOSPI", "aliases": ["삼전우"]},
    {"name": "삼성SDS", "code": "018260", "market": "KOSPI", "aliases": ["삼성에스디에스"]},
    {"name": "삼성전기", "code": "009150", "market": "KOSPI", "aliases": []},
    {"name": "삼성SDI", "code": "006400", "market": "KOSPI", "aliases": ["삼성에스디아이"]},
    {"name": "삼성바이오로직스", "code": "207940", "market": "KOSPI", "aliases": ["삼바"]},
    {"name": "삼성물산", "code": "028260", "market": "KOSPI", "aliases": []},
    {"name": "삼성생명", "code": "032830", "market": "KOSPI", "aliases": []},
    {"name": "삼성화재", "code": "000810", "market": "KOSPI", "aliases": []},
    {"name": "삼성중공업", "code": "010140", "market": "KOSPI", "aliases": []},
    {"name": "삼성증권", "code": "016360", "market": "KOSPI", "aliases": []},
    {"name": "삼성카드", "code": "029780", "market": "KOSPI", "english": "Samsung Card", "aliases": []},
    {"name": "삼성E&A", "code": "028050", "market": "KOSPI", "english": "Samsung E&A", "aliases": ["삼성엔지니어링", "삼성이앤에이"]},
    {"name": "LS", "code": "006260", "market": "KOSPI", "english": "LS", "aliases": ["엘에스"]},
    {"name": "LS ELECTRIC", "code": "010120", "market": "KOSPI", "english": "LS ELECTRIC", "aliases": ["LS일렉트릭", "LS 일렉트릭", "엘에스일렉트릭"], "keywords": ["전력기기", "전력설비", "변압기"]},
    {"name": "LS에코에너지", "code": "229640", "market": "KOSPI", "english": "LS Eco Energy", "aliases": ["LS 에코에너지", "엘에스에코에너지"], "keywords": ["전선"]},
    {"name": "LS마린솔루션", "code": "060370", "market": "KOSDAQ", "english": "LS Marine Solution", "aliases": ["LS 마린솔루션", "엘에스마린솔루션"], "keywords": ["해저케이블"]},
    {"name": "LS네트웍스", "code": "000680", "market": "KOSPI", "english": "LS Networks", "aliases": ["LS 네트웍스", "엘에스네트웍스"]},
    {"name": "LS머트리얼즈", "code": "417200", "market": "KOSDAQ", "english": "LS Materials", "aliases": ["LS 머트리얼즈", "엘에스머트리얼즈"], "keywords": ["2차전지"]},
    {"name": "SK하이닉스", "code": "000660", "market": "KOSPI", "english": "SK hynix", "aliases": ["SK 하이닉스", "하이닉스"], "keywords": ["HBM", "메모리", "반도체"]},
    {"name": "SK이노베이션", "code": "096770", "market": "KOSPI", "aliases": ["SK 이노베이션"]},
    {"name": "SK텔레콤", "code": "017670", "market": "KOSPI", "aliases": ["SK 텔레콤"]},
    {"name": "SK스퀘어", "code": "402340", "market": "KOSPI", "aliases": ["SK 스퀘어"]},
    {"name": "SK바이오사이언스", "code": "302440", "market": "KOSPI", "aliases": []},
    {"name": "현대차", "code": "005380", "market": "KOSPI", "english": "Hyundai Motor", "aliases": ["현대자동차"], "keywords": ["제네시스", "Genesis", "자동차"]},
    {"name": "현대모비스", "code": "012330", "market": "KOSPI", "aliases": []},
    {"name": "현대글로비스", "code": "086280", "market": "KOSPI", "aliases": []},
    {"name": "기아", "code": "000270", "market": "KOSPI", "english": "Kia", "aliases": ["기아차"], "keywords": ["자동차"]},
    {"name": "NAVER", "code": "035420", "market": "KOSPI", "english": "NAVER", "aliases": ["네이버"], "keywords": ["라인", "웹툰", "클라우드"]},
    {"name": "카카오", "code": "035720", "market": "KOSPI", "english": "Kakao", "aliases": [], "keywords": ["카톡", "카카오톡", "모빌리티"]},
    {"name": "카카오뱅크", "code": "323410", "market": "KOSPI", "aliases": []},
    {"name": "카카오페이", "code": "377300", "market": "KOSPI", "aliases": []},
    {"name": "LG전자", "code": "066570", "market": "KOSPI", "english": "LG Electronics", "aliases": ["엘지전자"], "keywords": ["가전", "전장"]},
    {"name": "LG에너지솔루션", "code": "373220", "market": "KOSPI", "english": "LG Energy Solution", "aliases": ["LG엔솔", "엘지엔솔"], "keywords": ["배터리", "2차전지"]},
    {"name": "LG화학", "code": "051910", "market": "KOSPI", "english": "LG Chem", "aliases": ["엘지화학"], "keywords": ["화학", "배터리"]},
    {"name": "POSCO홀딩스", "code": "005490", "market": "KOSPI", "aliases": ["포스코홀딩스", "포스코"]},
    {"name": "셀트리온", "code": "068270", "market": "KOSPI", "aliases": []},
    {"name": "나노신소재", "code": "121600", "market": "KOSDAQ", "aliases": []},
    {"name": "나노팀", "code": "417010", "market": "KOSDAQ", "aliases": []},
    {"name": "나무가", "code": "190510", "market": "KOSDAQ", "aliases": []},
    {"name": "나스미디어", "code": "089600", "market": "KOSDAQ", "aliases": []},
    {"name": "나이스정보통신", "code": "036800", "market": "KOSDAQ", "aliases": ["NICE정보통신"]},
    {"name": "나이스디앤비", "code": "130580", "market": "KOSDAQ", "aliases": ["NICE디앤비"]},
    {"name": "나우IB", "code": "293580", "market": "KOSDAQ", "aliases": ["나우아이비"]},
    {"name": "나라엠앤디", "code": "051490", "market": "KOSDAQ", "aliases": []},
    {"name": "나라셀라", "code": "405920", "market": "KOSDAQ", "aliases": []},
    {"name": "나인테크", "code": "267320", "market": "KOSDAQ", "aliases": []},
    {"name": "HLB", "code": "028300", "market": "KOSDAQ", "aliases": ["에이치엘비"]},
    {"name": "에코프로", "code": "086520", "market": "KOSDAQ", "aliases": []},
    {"name": "에코프로비엠", "code": "247540", "market": "KOSDAQ", "aliases": []},
    {"name": "알테오젠", "code": "196170", "market": "KOSDAQ", "aliases": []},
    {"name": "엔비디아", "code": "NVDA", "market": "NASDAQ", "english": "NVIDIA", "aliases": ["NVIDIA"], "keywords": ["GPU", "AI", "젠슨황"]},
    {"name": "테슬라", "code": "TSLA", "market": "NASDAQ", "english": "Tesla", "aliases": ["TESLA"], "keywords": ["전기차", "일론머스크"]},
    {"name": "애플", "code": "AAPL", "market": "NASDAQ", "english": "Apple", "aliases": ["APPLE"], "keywords": ["아이폰", "iPhone"]},
    {"name": "마이크로소프트", "code": "MSFT", "market": "NASDAQ", "english": "Microsoft", "aliases": ["Microsoft"], "keywords": ["MS", "Azure", "오픈AI"]},
    {"name": "알파벳", "code": "GOOGL", "market": "NASDAQ", "english": "Alphabet", "aliases": ["구글", "Google"], "keywords": ["유튜브", "YouTube", "검색"]},
    {"name": "마이크론", "code": "MU", "market": "NASDAQ", "english": "Micron", "aliases": ["마이크론테크놀로지", "Micron"], "keywords": ["메모리", "반도체", "DRAM"]},
    {"name": "Intel Corporation", "code": "INTC", "market": "NASDAQ", "english": "Intel Corporation", "aliases": ["인텔", "Intel"], "keywords": ["CPU", "반도체"]},
    {"name": "Advanced Micro Devices", "code": "AMD", "market": "NASDAQ", "english": "Advanced Micro Devices", "aliases": ["AMD", "에이엠디"], "keywords": ["CPU", "GPU", "반도체"]},
    {"name": "Palantir Technologies Inc.", "code": "PLTR", "market": "NASDAQ", "english": "Palantir Technologies Inc.", "aliases": ["팔란티어", "Palantir"], "keywords": ["AI", "데이터"]},
    {"name": "Meta Platforms Inc.", "code": "META", "market": "NASDAQ", "english": "Meta Platforms Inc.", "aliases": ["메타", "페이스북", "인스타그램"], "keywords": ["SNS", "AI"]},
    {"name": "Amazon.com Inc.", "code": "AMZN", "market": "NASDAQ", "english": "Amazon.com Inc.", "aliases": ["아마존", "AWS"], "keywords": ["클라우드", "이커머스"]},
    {"name": "Netflix Inc.", "code": "NFLX", "market": "NASDAQ", "english": "Netflix Inc.", "aliases": ["넷플릭스"], "keywords": ["OTT", "스트리밍"]},
]


def stock_master():
    """KRX·미국 캐시가 있으면 전체 종목을 우선 사용하고, 보강 목록을 합친다."""
    cache_key = (
        id(krx_listed.load_cached_stocks),
        id(us_listed.load_cached_stocks),
        config.KRX_LISTED_JSON.stat().st_mtime if config.KRX_LISTED_JSON.exists() else None,
        config.US_LISTED_JSON.stat().st_mtime if config.US_LISTED_JSON.exists() else None,
    )
    cached_key = getattr(stock_master, "_cached_key", None)
    cached = getattr(stock_master, "_cached", None)
    if cached_key == cache_key and cached is not None:
        return cached
    rows = []
    seen_codes = set()
    for stock in krx_listed.load_cached_stocks():
        code = compact(stock.get("code", ""))
        if code:
            seen_codes.add(code)
        rows.append(stock)
    for stock in us_listed.load_cached_stocks():
        code = compact(stock.get("code", ""))
        if code and code in seen_codes:
            continue
        if code:
            seen_codes.add(code)
        rows.append(stock)
    for stock in FALLBACK_STOCK_MASTER:
        code = compact(stock.get("code", ""))
        if code and code in seen_codes:
            continue
        rows.append(stock)
    stock_master._cached_key = cache_key
    stock_master._cached = rows
    return rows


def compact(text):
    return re.sub(r"[^0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ]", "", str(text)).lower()


def initials(text):
    result = []
    for ch in str(text):
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            result.append(CHOSEONG[(code - 0xAC00) // 588])
        elif ch in INITIAL_CHARS:
            result.append(ch)
        elif ch.isascii() and ch.isalnum():
            result.append(ch.lower())
    return "".join(result)


def is_initial_query(value):
    value = compact(value)
    return bool(value) and all(ch in INITIAL_CHARS for ch in value)


def _has_hangul(value):
    return bool(re.search(r"[가-힣]", str(value or "")))


def _display_name(stock):
    """미국 주요 종목은 공식 영문명 대신 앱 사용자에게 익숙한 한국어 이름을 보여준다."""
    code = str(stock.get("code") or "").strip().upper()
    for alias in us_listed.US_KOREAN_ALIASES.get(code, []):
        if _has_hangul(alias):
            return alias
    return stock.get("name", "")


def _stock_aliases(stock):
    aliases = [
        _display_name(stock),
        stock["name"],
        stock.get("code", ""),
        stock.get("isin", ""),
        stock.get("corpName", ""),
        stock.get("english", ""),
        *(stock.get("aliases") or []),
    ]
    aliases.extend(KNOWN_ALIASES.get(stock["name"], []))
    seen = set()
    out = []
    for alias in aliases:
        key = compact(alias)
        if key and key not in seen:
            seen.add(key)
            out.append(alias)
    return out


def _search_terms(stock):
    return {
        "name": [stock["name"]],
        "initial": [initials(stock["name"])],
        "code": [stock.get("code", ""), stock.get("isin", "")],
        "english": [stock.get("english", "")],
        "alias": [stock.get("corpName", ""), *(stock.get("aliases") or []), *KNOWN_ALIASES.get(stock["name"], [])],
        "keyword": stock.get("keywords", []),
    }


def _score_term(q, term, base_exact, base_prefix, base_contains):
    key = compact(term)
    if not key:
        return None
    if key == q:
        return base_exact
    if key.startswith(q):
        return base_prefix
    if q in key:
        return base_contains
    return None


def _suggestion_score(stock, query):
    q = compact(query)
    if not q:
        return None
    terms = _search_terms(stock)
    candidates = []

    for term in terms["name"]:
        score = _score_term(q, term, 0, 10, 70)
        if score is not None:
            candidates.append((score, "종목명", term))

    if is_initial_query(q):
        for term in terms["initial"]:
            score = _score_term(q, term, 20, 20, 85)
            if score is not None:
                candidates.append((score, "초성", term))

    for term in terms["code"]:
        score = _score_term(q, term, 1, 30, 95)
        if score is not None:
            candidates.append((score, "종목코드", term))

    for term in terms["english"]:
        score = _score_term(q, term, 2, 40, 90)
        if score is not None:
            candidates.append((score, "영문명", term))

    for term in terms["alias"]:
        score = _score_term(q, term, 3, 50, 100)
        if score is not None:
            candidates.append((score, "별칭", term))

    for term in terms["keyword"]:
        score = _score_term(q, term, 4, 60, 110)
        if score is not None:
            candidates.append((score, "키워드", term))

    return min(candidates, default=None, key=lambda item: item[0])


def suggest_stocks(query, limit=None):
    """토스증권처럼 여러 신호를 점수화해 자동완성 후보를 반환한다."""
    query = query.strip()
    if not compact(query):
        return []
    rows = []
    for order, stock in enumerate(stock_master()):
        matched = _suggestion_score(stock, query)
        if not matched:
            continue
        score, match_type, matched_text = matched
        aliases = _stock_aliases(stock)
        rows.append((score, order, {
            "name": _display_name(stock),
            "code": stock.get("code", ""),
            "market": stock.get("market", ""),
            "isin": stock.get("isin", ""),
            "baseDate": stock.get("baseDate", ""),
            "corpName": stock.get("corpName", ""),
            "source": stock.get("source", "local"),
            "english": stock.get("english", ""),
            "aliases": aliases,
            "matchType": match_type,
            "matched": matched_text,
            "score": score,
        }))
    rows.sort(key=lambda row: (row[0], row[1]))
    results = [row[2] for row in rows]
    return results if limit is None else results[:limit]


def query_aliases(query):
    query = query.strip()
    if not query:
        return []
    query_key = compact(query)
    aliases = [query]
    for stock in stock_master():
        stock_aliases = _stock_aliases(stock)
        if query_key in {compact(name) for name in stock_aliases}:
            aliases = stock_aliases
            break
    for canonical, known in KNOWN_ALIASES.items():
        all_names = [canonical, *known]
        if query_key in {compact(name) for name in all_names}:
            aliases = all_names
            break
    if query_key.startswith("sk") and len(query_key) > 4:
        aliases.append(query_key[2:])
    seen = set()
    out = []
    for alias in aliases:
        key = compact(alias)
        if key and key not in seen:
            seen.add(key)
            out.append(alias)
    return out


def _chip_candidate_stocks():
    """칩은 검색 성공률이 높은 주요 종목 풀에서 고른다."""
    rows = []
    seen = set()
    known_keys = {compact(name) for name in KNOWN_ALIASES}
    for stock in stock_master():
        names = [stock.get("name", ""), *_stock_aliases(stock), *stock.get("keywords", [])]
        if stock in FALLBACK_STOCK_MASTER or any(compact(name) in known_keys for name in names):
            key = compact(stock.get("code") or stock.get("name"))
            if key and key not in seen:
                seen.add(key)
                rows.append(stock)
    return rows


def _chip_row(stock, score=0):
    return {
        "name": _display_name(stock),
        "code": stock.get("code", ""),
        "market": stock.get("market", ""),
        "score": round(score, 3),
    }


def _unique_chip_rows(rows, limit):
    out = []
    seen = set()
    for row in rows:
        key = compact(row.get("name") or row.get("code"))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _video_mentions_stock(video, stock):
    aliases = _stock_aliases(stock)
    title = video.get("title", "")
    text = transcript_text(video["videoId"])
    title_count = match_count(title, aliases)
    text_count = match_count(text, aliases)
    return title_count, text_count


def popular_chips(limit=8):
    """검색 전 노출: 최근 많이 언급된 종목."""
    cache_key = (
        config.SEARCH_INDEX_JSON.stat().st_mtime if config.SEARCH_INDEX_JSON.exists() else None,
        limit,
    )
    cached_key = getattr(popular_chips, "_cached_key", None)
    cached = getattr(popular_chips, "_cached", None)
    if cached_key == cache_key and cached is not None:
        return cached

    scores = []
    videos = load_index().get("videos", [])
    for stock in _chip_candidate_stocks():
        channels = set()
        title_hits = 0
        text_hits = 0
        views = 0
        latest = ""
        for video in videos:
            title_count, text_count = _video_mentions_stock(video, stock)
            if not title_count and not text_count:
                continue
            channels.add(video.get("channel", ""))
            title_hits += title_count
            text_hits += text_count
            views += int(video.get("views") or 0)
            latest = max(latest, video.get("publishedAt", ""))
        if not channels:
            continue
        score = len(channels) * 10 + title_hits * 4 + min(text_hits, 12) + min(views / 100000, 8)
        scores.append((score, latest, stock.get("name", ""), stock))

    ranked = sorted(scores, key=lambda row: (row[0], row[1], row[2], row[3].get("code", "")), reverse=True)
    rows = _unique_chip_rows([_chip_row(stock, score) for score, _, _, stock in ranked], limit)
    popular_chips._cached_key = cache_key
    popular_chips._cached = rows
    return rows


def related_chips(query, limit=8):
    """검색 후 노출: 같은 영상에서 함께 언급된 종목."""
    query_key = compact(query)
    query_names = {compact(name) for name in query_aliases(query)}
    videos = find_videos(query, max_youtubers=config.SEARCH_MAX_YOUTUBERS)
    scores = []
    for stock in _chip_candidate_stocks():
        stock_names = {compact(name) for name in _stock_aliases(stock)}
        if query_key in stock_names or query_names & stock_names:
            continue
        channels = set()
        title_hits = 0
        text_hits = 0
        views = 0
        latest = ""
        for video in videos:
            title_count, text_count = _video_mentions_stock(video, stock)
            if not title_count and not text_count:
                continue
            channels.add(video.get("channel", ""))
            title_hits += title_count
            text_hits += text_count
            views += int(video.get("views") or 0)
            latest = max(latest, video.get("publishedAt", ""))
        if not channels:
            continue
        score = len(channels) * 10 + title_hits * 4 + min(text_hits, 12) + min(views / 100000, 8)
        scores.append((score, latest, stock.get("name", ""), stock))
    ranked = sorted(scores, key=lambda row: (row[0], row[1], row[2], row[3].get("code", "")), reverse=True)
    rows = _unique_chip_rows([_chip_row(stock, score) for score, _, _, stock in ranked], limit)
    return rows or popular_chips(limit)


def transcript_text(video_id):
    path = config.TRANSCRIPT_CACHE_DIR / f"{video_id}.json"
    if not path.exists():
        remote_cache.download_to_file(f"transcripts/{video_id}.json", path)
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return data.get("text", "") if data.get("status") == "ok" else ""


def transcript_segments(video_id):
    """자막 문장별 시작 시간을 반환한다. 기존 캐시에 없으면 한 번 보강한다."""
    path = config.TRANSCRIPT_CACHE_DIR / f"{video_id}.json"
    if not path.exists():
        remote_cache.download_to_file(f"transcripts/{video_id}.json", path)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    if data.get("status") == "ok" and data.get("segments"):
        return data.get("segments", [])
    if data.get("status") != "ok" or not data.get("text"):
        return []

    try:
        import youtube
        youtube.fetch_transcript(video_id, force=True)
        refreshed = json.loads(path.read_text(encoding="utf-8"))
        if refreshed.get("status") == "ok":
            return refreshed.get("segments", [])
        if data.get("status") == "ok" and data.get("text"):
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return []
    except Exception:
        if data.get("status") == "ok" and data.get("text"):
            try:
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
        return []


def match_count(text, aliases):
    normalized = compact(text)
    return sum(normalized.count(compact(alias)) for alias in aliases)


def extract_context(text, aliases, window=None, max_chars=None, max_spans=None):
    """검색어 주변 문맥을 여러 구간 모아 긴 자막 전체 전송을 피한다."""
    window = config.SEARCH_CONTEXT_WINDOW if window is None else window
    max_chars = config.SEARCH_CONTEXT_MAX_CHARS if max_chars is None else max_chars
    max_spans = config.SEARCH_CONTEXT_MAX_SPANS if max_spans is None else max_spans
    lowered = text.lower()
    spans = []
    for alias in aliases:
        needle = alias.lower().strip()
        if not needle:
            continue
        start = 0
        while len(spans) < max_spans:
            at = lowered.find(needle, start)
            if at < 0:
                break
            spans.append((max(0, at - window), min(len(text), at + len(needle) + window)))
            start = at + len(needle)
    if not spans:
        # 띄어쓰기 차이로만 매칭된 경우 문맥 위치를 찾기 어려우므로 제한된 전체 자막 사용.
        return text[:max_chars]
    spans.sort()
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return "\n\n[…중략…]\n\n".join(text[s:e] for s, e in merged)[:max_chars]


def load_index():
    _sync_remote_index_if_needed()
    if not config.SEARCH_INDEX_JSON.exists():
        return {"updatedAt": None, "videos": []}
    try:
        return json.loads(config.SEARCH_INDEX_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"updatedAt": None, "videos": []}


def _sync_remote_index_if_needed(force=False):
    global _REMOTE_INDEX_CHECKED_AT
    now = time.monotonic()
    if not force and now - _REMOTE_INDEX_CHECKED_AT < _REMOTE_INDEX_CHECK_INTERVAL_SECONDS:
        return
    _REMOTE_INDEX_CHECKED_AT = now
    remote_index = remote_cache.download_json("search_index.json")
    if remote_index:
        local_index = None
        if config.SEARCH_INDEX_JSON.exists():
            try:
                local_index = json.loads(config.SEARCH_INDEX_JSON.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                local_index = None
        if _remote_index_is_newer(remote_index, local_index):
            config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = config.SEARCH_INDEX_JSON.with_suffix(".tmp")
            tmp.write_text(json.dumps(remote_index, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(config.SEARCH_INDEX_JSON)


def _remote_index_is_newer(remote_index, local_index):
    if not local_index:
        return True
    remote_updated = remote_index.get("updatedAt")
    local_updated = local_index.get("updatedAt")
    if not local_updated:
        return True
    if not remote_updated:
        return False
    return remote_updated > local_updated


def save_index(videos):
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _SEARCH_INDEX_VERSION,
        "updatedAt": datetime.datetime.now(KST).isoformat(),
        "lookbackDays": config.SEARCH_LOOKBACK_DAYS,
        "maxVideosPerChannel": config.SEARCH_MAX_VIDEOS_PER_CHANNEL,
        "videos": videos,
    }
    tmp = config.SEARCH_INDEX_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(config.SEARCH_INDEX_JSON)
    remote_cache.upload_json("search_index.json", payload)
    return payload


def sync_index(channels):
    """최근 영상 자막을 캐시하고 검색 가능한 메타데이터 인덱스를 만든다."""
    import youtube

    videos = []
    failed_channels = []
    for channel in channels:
        try:
            recent = youtube.recent_uploads(
                channel,
                lookback_days=config.SEARCH_LOOKBACK_DAYS,
                max_results=max(15, config.SEARCH_MAX_VIDEOS_PER_CHANNEL),
            )[:config.SEARCH_MAX_VIDEOS_PER_CHANNEL]
        except Exception as exc:
            failed_channels.append(channel["name"])
            print(f"  ⚠️ {channel['name']}: {str(exc)[:100]}")
            continue
        print(f"  · {channel['name']}: 후보 {len(recent)}개")
        for video in recent:
            text = youtube.fetch_transcript(video["videoId"])
            if not text:
                print(f"      자막 없음 · {video['title'][:36]}")
            videos.append({
                "videoId": video["videoId"],
                "channel": video["channel"],
                "channelType": channel.get("type"),
                "title": video["title"],
                "publishedAt": video["publishedAt"].isoformat(),
                "views": video["views"],
                "durationSec": video["durationSec"],
                "url": video["url"],
                "transcriptChars": len(text or ""),
                "transcriptStatus": "ok" if text else "missing",
                "transcriptError": "" if text else (youtube.LAST_TRANSCRIPT_ERROR or ""),
            })
    videos.sort(key=lambda row: (row["publishedAt"], row.get("transcriptStatus") == "ok"), reverse=True)
    payload = save_index(videos)
    with_transcript = sum(1 for row in videos if row.get("transcriptStatus") == "ok")
    print(f"\n✅ 검색 인덱스 생성: 영상 {len(videos)}개 · 자막 {with_transcript}개 · 최근 {config.SEARCH_LOOKBACK_DAYS}일")
    if failed_channels:
        print("   건너뛴 채널:", ", ".join(failed_channels))
    return payload


def _index_video_row(video, text="", channel_type=None, fallback=False):
    return {
        "videoId": video["videoId"],
        "channel": video["channel"],
        "channelType": channel_type,
        "title": video["title"],
        "publishedAt": video["publishedAt"].isoformat() if hasattr(video["publishedAt"], "isoformat") else video["publishedAt"],
        "views": video.get("views", 0),
        "durationSec": video.get("durationSec", 0),
        "url": video.get("url") or f"https://www.youtube.com/watch?v={video['videoId']}",
        "transcriptChars": len(text or ""),
        "transcriptStatus": "ok" if text else "missing",
        "transcriptError": "",
        "fallback": fallback,
    }


def _video_match_row(video, aliases):
    text = transcript_text(video["videoId"])
    count = match_count(text, aliases)
    title_count = match_count(video.get("title", ""), aliases)
    if count <= 0 and title_count <= 0:
        return None
    row = dict(video)
    row["_text"] = text
    row["matchCount"] = count
    row["titleMatch"] = bool(title_count)
    row["hasTranscriptText"] = bool(text.strip())
    return row


def _latest_published_at(rows):
    latest = None
    for row in rows:
        try:
            published = datetime.datetime.fromisoformat(row.get("publishedAt", ""))
        except (TypeError, ValueError):
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=KST)
        latest = published if latest is None or published > latest else latest
    return latest


def _needs_search_fallback(matches):
    if not config.SEARCH_FALLBACK_ENABLED or not config.YOUTUBE_API_KEY:
        return False
    title_matches = [row for row in matches if row.get("titleMatch")]
    if len(title_matches) < config.SEARCH_FALLBACK_MIN_RESULTS:
        return True
    latest = _latest_published_at(title_matches)
    if latest is None:
        return True
    age = datetime.datetime.now(KST) - latest.astimezone(KST)
    return age >= datetime.timedelta(hours=config.SEARCH_FALLBACK_RECENT_HOURS)


def _fallback_search_matches(query, aliases, existing_ids):
    import youtube

    channel_type_by_id = {row.get("channelId"): row.get("type") for row in config.CHANNELS if row.get("channelId")}
    out = []
    try:
        videos = youtube.search_videos(
            query,
            lookback_days=config.SEARCH_LOOKBACK_DAYS,
            max_results=config.SEARCH_FALLBACK_MAX_RESULTS,
            order=config.SEARCH_FALLBACK_ORDER,
        )
    except Exception as exc:
        print(f"  ⚠️ YouTube 검색 보강 실패: {str(exc)[:100]}")
        return []
    for video in videos:
        if video["videoId"] in existing_ids:
            continue
        if int(video.get("views") or 0) < config.SEARCH_FALLBACK_MIN_VIEWS:
            continue
        text = youtube.fetch_transcript(video["videoId"])
        if not text:
            continue
        row = _index_video_row(
            video,
            text=text,
            channel_type=channel_type_by_id.get(video.get("channelId")),
            fallback=True,
        )
        match = _video_match_row(row, aliases)
        if match:
            out.append(match)
            existing_ids.add(video["videoId"])
    return out


def find_videos(query, max_youtubers=None):
    aliases = query_aliases(query)
    if not aliases:
        return []
    matches = []
    for video in load_index().get("videos", []):
        row = _video_match_row(video, aliases)
        if row:
            matches.append(row)
    if _needs_search_fallback(matches):
        existing_ids = {row["videoId"] for row in matches}
        matches.extend(_fallback_search_matches(query, aliases, existing_ids))
    matches.sort(
        key=lambda row: (
            row.get("hasTranscriptText", False),
            row["titleMatch"],
            row["matchCount"],
            row["publishedAt"],
            row["views"],
        ),
        reverse=True,
    )
    # 결과는 유튜버별 대표 영상 1개만 사용한다.
    limit = max_youtubers or config.SEARCH_MAX_YOUTUBERS
    best = {}
    for row in matches:
        best.setdefault(row["channel"], row)
        if len(best) >= limit:
            break
    return list(best.values())


def _stock_cache_path(video_id, query):
    digest = hashlib.sha256(compact(query).encode("utf-8")).hexdigest()[:16]
    return config.STOCK_ANALYSIS_CACHE_DIR / f"{video_id}-{digest}.json"


def _analysis_inputs(video, query):
    aliases = query_aliases(query)
    context = extract_context(video["_text"], aliases)
    context_hash = hashlib.sha256(context.encode("utf-8")).hexdigest()
    path = _stock_cache_path(video["videoId"], query)
    return aliases, context, context_hash, path


def _evidence_terms(evidence):
    terms = []
    for term in re.findall(r"[0-9A-Za-z가-힣]{2,}", evidence or ""):
        key = compact(term)
        if len(key) >= 2 and key not in {"있습니다", "것으로", "통해", "대한", "또한", "예상됩니다"}:
            terms.append(key)
    return set(terms)


def source_time_sec(video_id, aliases, evidence):
    segments = transcript_segments(video_id)
    if not segments:
        return None
    alias_keys = [compact(alias) for alias in aliases if compact(alias)]
    terms = _evidence_terms(evidence)
    best = None
    for order, segment in enumerate(segments):
        text = segment.get("text", "")
        key = compact(text)
        if not key or not any(alias in key for alias in alias_keys):
            continue
        overlap = sum(1 for term in terms if term in key)
        score = overlap * 10 + min(len(key), 80) / 80
        try:
            start_sec = float(segment.get("startSec"))
        except (TypeError, ValueError):
            continue
        candidate = (score, -order, start_sec)
        if best is None or candidate > best:
            best = candidate
    return round(best[2]) if best else None


def cached_match(video, query):
    """AI 호출 없이 기존 종목 분석 캐시만 읽는다."""
    _, _, context_hash, path = _analysis_inputs(video, query)
    return _read_cached_analysis(path, context_hash)


def _read_cached_analysis(path, context_hash):
    if path.exists() and not config.FORCE_ANALYSIS_REFRESH:
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if (cached.get("version") == _STOCK_CACHE_VERSION and
                    cached.get("contextHash") == context_hash):
                return cached["data"], True
        except (OSError, ValueError, KeyError):
            pass
    return None, False


def analyze_match(video, query):
    import analyze

    aliases, context, context_hash, path = _analysis_inputs(video, query)
    if not context.strip() and match_count(video.get("title", ""), aliases):
        return {
            "mentioned": False,
            "stance": "단순언급",
            "summary": "",
            "evidence": "",
            "sourceTimeSec": None,
        }, False
    cached_data, cached = _read_cached_analysis(path, context_hash)
    if cached:
        return cached_data, True

    data = analyze.analyze_stock_opinion(query, aliases, context)
    data["sourceTimeSec"] = source_time_sec(video["videoId"], aliases, data.get("evidence", ""))
    config.STOCK_ANALYSIS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "version": _STOCK_CACHE_VERSION,
        "contextHash": context_hash,
        "provider": analyze.LAST_GENERATION_PROVIDER,
        "data": data,
    }, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return data, False


def base_search_result(query, videos):
    analysis_limit = max(1, min(len(videos), config.SEARCH_MAX_ANALYZED_VIDEOS))
    return {
        "query": query.strip(),
        "aliases": query_aliases(query),
        "matchedVideos": len(videos),
        "processedVideos": 0,
        "analyzedVideos": 0,
        "analysisLimit": analysis_limit,
        "opinions": [],
        "counts": {"긍정": 0, "신중": 0, "부정": 0, "단순언급": 0},
        "errors": [],
        "indexUpdatedAt": load_index().get("updatedAt"),
    }


def opinion_from_result(video, result, cached):
    if not result.get("mentioned"):
        return None
    return {
        "channel": video["channel"],
        "title": video["title"],
        "publishedAt": video["publishedAt"],
        "views": video["views"],
        "url": video["url"],
        "stance": result["stance"],
        "summary": result["summary"],
        "evidence": result["evidence"],
        "sourceTimeSec": result.get("sourceTimeSec"),
        "cached": cached,
    }


def add_opinion(search_result, opinion):
    if not opinion:
        return
    opinion["_order"] = len(search_result["opinions"])
    search_result["opinions"].append(opinion)
    search_result["counts"][opinion["stance"]] += 1


def _published_sort_value(opinion):
    value = opinion.get("publishedAt") or ""
    try:
        return datetime.datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return 0


def opinion_sort_key(opinion):
    """업로드 최신순을 우선하고, 같은 시간일 때만 판단 의견을 먼저 둔다."""
    mention_rank = 1 if opinion.get("stance") == "단순언급" else 0
    return (-_published_sort_value(opinion), mention_rank, -int(opinion.get("views") or 0), opinion.get("_order", 0))


def sort_opinions(search_result):
    """업로드 최신순을 우선하고, 같은 시간일 때만 판단 의견을 먼저 둔다."""
    search_result["opinions"].sort(
        key=opinion_sort_key
    )
    for opinion in search_result["opinions"]:
        opinion.pop("_order", None)


def search_stock(query):
    videos = find_videos(query)
    search_result = base_search_result(query, videos)
    analysis_limit = search_result["analysisLimit"]

    for idx, video in enumerate(videos):
        try:
            if idx < analysis_limit:
                result, cached = analyze_match(video, query)
                search_result["analyzedVideos"] += 1
            else:
                # 빠른 검색을 위해 상위 N개만 새로 분석한다.
                # 다만 이미 캐시된 추가 유튜버 의견은 공짜로 같이 보여준다.
                result, cached = cached_match(video, query)
                if not cached:
                    search_result["processedVideos"] += 1
                    continue
        except Exception as exc:
            search_result["errors"].append(f"{video['channel']}: {str(exc)[:120]}")
            search_result["processedVideos"] += 1
            continue
        add_opinion(search_result, opinion_from_result(video, result, cached))
        search_result["processedVideos"] += 1
    sort_opinions(search_result)
    search_result["done"] = True
    return search_result
