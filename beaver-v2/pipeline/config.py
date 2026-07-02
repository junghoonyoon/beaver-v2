"""파이프라인 설정. 채널 로스터·임계값·경로·API 키를 한곳에서 관리."""
import os
from pathlib import Path

# ── 경로 ──
PIPELINE_DIR = Path(__file__).resolve().parent
ROOT = PIPELINE_DIR.parent              # 프로젝트 루트 (비버 종목검색)
CACHE_DIR = PIPELINE_DIR / "cache"
TRANSCRIPT_CACHE_DIR = CACHE_DIR / "transcripts"
ANALYSIS_CACHE_DIR = CACHE_DIR / "analysis"
STOCK_ANALYSIS_CACHE_DIR = CACHE_DIR / "stock_analysis"
MANUAL_TRANSCRIPT_DIR = CACHE_DIR / "manual_transcripts"
SEARCH_INDEX_JSON = CACHE_DIR / "search_index.json"
KRX_LISTED_JSON = CACHE_DIR / "krx_listed_stocks.json"
US_LISTED_JSON = CACHE_DIR / "us_listed_stocks.json"
ANALYTICS_EVENTS_JSONL = CACHE_DIR / "analytics_events.jsonl"
SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "beaver-cache")
IS_RENDER = bool(os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"))
STARTUP_REFRESH_ENABLED = os.environ.get(
    "STARTUP_REFRESH_ENABLED",
    "0" if IS_RENDER else "1",
) == "1"
STARTUP_SEARCH_REFRESH_ENABLED = os.environ.get(
    "STARTUP_SEARCH_REFRESH_ENABLED",
    "1" if STARTUP_REFRESH_ENABLED else "0",
) == "1"
STARTUP_STOCK_REFRESH_ENABLED = os.environ.get("STARTUP_STOCK_REFRESH_ENABLED", "1") == "1"

# ── API 키 (환경변수에서) ──
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
SUPADATA_API_KEY = os.environ.get("SUPADATA_API_KEY", "")  # 무료 경로 실패 시 유료 fallback
KRX_API_KEY = os.environ.get("KRX_API_KEY", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_CACHE_ENABLED = os.environ.get("SUPABASE_CACHE_ENABLED", "1") == "1"
KRX_LISTED_API_URL = os.environ.get(
    "KRX_LISTED_API_URL",
    "https://apis.data.go.kr/1160100/service/GetKrxListedInfoService/getItemInfo",
)
KRX_STOCK_PRICE_API_URL = os.environ.get(
    "KRX_STOCK_PRICE_API_URL",
    "https://apis.data.go.kr/1160100/service/GetStockSecuritiesInfoService/getStockPriceInfo",
)
KRX_LISTED_REFRESH_HOURS = int(os.environ.get("KRX_LISTED_REFRESH_HOURS", "24"))
MARKET_RANKINGS_REFRESH_HOURS = int(os.environ.get("MARKET_RANKINGS_REFRESH_HOURS", "6"))
US_LISTED_REFRESH_HOURS = int(os.environ.get("US_LISTED_REFRESH_HOURS", "24"))
NASDAQ_LISTED_URL = os.environ.get(
    "NASDAQ_LISTED_URL",
    "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
)
OTHER_LISTED_URL = os.environ.get(
    "OTHER_LISTED_URL",
    "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
)
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
ANALYSIS_PROVIDER = os.environ.get("ANALYSIS_PROVIDER", "local-first")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash")
OPENROUTER_REFERER = os.environ.get("OPENROUTER_REFERER", "")
OPENROUTER_TITLE = os.environ.get("OPENROUTER_TITLE", "beaver-stock-search")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:14b")
OLLAMA_TIMEOUT_SECONDS = int(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "300"))
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "3"))  # 최근 며칠치 영상까지 볼지 (1=오늘만) ※정확도 점검용 임시 3
MAX_VIDEOS_PER_CHANNEL = int(os.environ.get("MAX_VIDEOS_PER_CHANNEL", "3"))  # 채널당 최대 영상 수
MAX_ANALYZED_VIDEOS = int(os.environ.get("MAX_ANALYZED_VIDEOS", "10"))  # 전체 후보 중 조회수 상위 N개만 분석
SEARCH_LOOKBACK_DAYS = int(os.environ.get("SEARCH_LOOKBACK_DAYS", "14"))
SEARCH_INDEX_REFRESH_HOURS = float(os.environ.get("SEARCH_INDEX_REFRESH_HOURS", "3"))
SEARCH_INDEX_AUTO_REFRESH_ENABLED = os.environ.get("SEARCH_INDEX_AUTO_REFRESH_ENABLED", "1") == "1"
SEARCH_MAX_VIDEOS_PER_CHANNEL = int(os.environ.get("SEARCH_MAX_VIDEOS_PER_CHANNEL", "15"))
SEARCH_MAX_YOUTUBERS = int(os.environ.get("SEARCH_MAX_YOUTUBERS", "15"))
SEARCH_MAX_ANALYZED_VIDEOS = int(os.environ.get("SEARCH_MAX_ANALYZED_VIDEOS", "15"))
SEARCH_FALLBACK_ENABLED = os.environ.get("SEARCH_FALLBACK_ENABLED", "1") == "1"
SEARCH_FALLBACK_MIN_RESULTS = int(os.environ.get("SEARCH_FALLBACK_MIN_RESULTS", "3"))
SEARCH_FALLBACK_RECENT_HOURS = int(os.environ.get("SEARCH_FALLBACK_RECENT_HOURS", "24"))
SEARCH_FALLBACK_MAX_RESULTS = int(os.environ.get("SEARCH_FALLBACK_MAX_RESULTS", "8"))
SEARCH_FALLBACK_MIN_VIEWS = int(os.environ.get("SEARCH_FALLBACK_MIN_VIEWS", "1000"))
SEARCH_FALLBACK_ORDER = os.environ.get("SEARCH_FALLBACK_ORDER", "relevance")
SEARCH_CONTEXT_WINDOW = int(os.environ.get("SEARCH_CONTEXT_WINDOW", "450"))
SEARCH_CONTEXT_MAX_CHARS = int(os.environ.get("SEARCH_CONTEXT_MAX_CHARS", "4000"))
SEARCH_CONTEXT_MAX_SPANS = int(os.environ.get("SEARCH_CONTEXT_MAX_SPANS", "4"))
TRANSCRIPT_FAILURE_TTL_HOURS = int(os.environ.get("TRANSCRIPT_FAILURE_TTL_HOURS", "12"))
TRANSCRIPT_TRANSIENT_FAILURE_TTL_HOURS = int(os.environ.get("TRANSCRIPT_TRANSIENT_FAILURE_TTL_HOURS", "2"))
TRANSCRIPT_REQUEST_DELAY_SECONDS = float(os.environ.get("TRANSCRIPT_REQUEST_DELAY_SECONDS", "1.0"))
FORCE_TRANSCRIPT_REFRESH = os.environ.get("FORCE_TRANSCRIPT_REFRESH", "") == "1"
FORCE_ANALYSIS_REFRESH = os.environ.get("FORCE_ANALYSIS_REFRESH", "") == "1"
POPULAR_PREWARM_ENABLED = os.environ.get("POPULAR_PREWARM_ENABLED", "1") == "1"
POPULAR_PREWARM_MARKET_LIMIT = int(os.environ.get("POPULAR_PREWARM_MARKET_LIMIT", "10"))

# ── 선정/표시 기준 ──
MIN_SUBSCRIBERS = 100_000   # 대상 채널 자격 (구독자)
MAX_CARDS = 10              # 분석한 조회수 상위 영상 노출 수
TRANSCRIPT_LANGS = ["ko", "ko-KR"]
VERDICTS = ["낙관", "신중", "경계"]

# ── 대상 채널 로스터 (= 분위기 측정 모집단) ──
# channelId 는 실제 YouTube 채널 ID(UC...)로 채워야 함. (mock 모드에선 불필요)
# tracked=True 인 채널이 '유튜버 입장 추적' 고정 로스터.
#
# lean : 성향 경향 — "강세" | "중립" | "신중" | "약세"
#        ※ '대략의 경향'. 시장 국면 따라 바뀌므로 최근 영상으로 검증·갱신할 것.
# type : 콘텐츠 유형 — "종목"(개별 종목 신호용) | "시황" | "거시" | "배분"
#        ※ '지금 사도 될까요?' 종목 카드 집계는 type="종목" 위주, 나머지는 '시장 분위기'용.
# 채널 성향은 최근 영상 기준으로 계속 보정해야 하는 보조 메타데이터.
def _channel(name, lean, kind, categories, channel_id="", tracked=False):
    return {
        "name": name,
        "channelId": channel_id,
        "lean": lean,
        "type": kind,
        "categories": categories,
        "tracked": tracked,
    }


CHANNELS = [
    _channel("삼프로TV", "중립", "시황", ["국내주식", "미국주식", "거시시황"], tracked=True),
    _channel("슈카월드", "신중", "거시", ["거시시황"], tracked=True),
    _channel("815머니톡", "강세", "시황", ["국내주식", "미국주식", "거시시황"], tracked=True),
    _channel("김작가 TV", "중립", "시황", ["국내주식", "미국주식", "거시시황"], tracked=True),
    _channel("박곰희TV", "중립", "배분", ["국내주식", "미국주식", "거시시황"], tracked=True),
    _channel("달란트투자", "강세", "종목", ["국내주식"]),
    _channel("상승효과TV", "중립", "시황", ["국내주식"], "UCINSVY-JDQraydXAdfMIbPg"),
    _channel("소수몽키", "중립", "종목", ["미국주식"]),
    _channel("미국주식으로 은퇴하기", "강세", "종목", ["미국주식", "반도체"]),
    _channel("김단테", "중립", "배분", ["미국주식", "거시시황"]),
    _channel("증시각도기TV", "강세", "종목", ["국내주식"]),
    _channel("한국경제TV뉴스", "중립", "시황", ["국내주식", "거시시황"]),
    _channel("와이스트릿", "중립", "시황", ["국내주식", "미국주식", "거시시황"]),
    _channel("홍춘욱의 경제강의노트", "중립", "거시", ["거시시황"]),
    _channel("김영익의 경제스쿨", "약세", "거시", ["거시시황"]),
    _channel("슈퍼개미 김정환", "강세", "종목", ["국내주식"]),
    _channel("메르의 투자노트", "중립", "종목", ["국내주식", "미국주식", "반도체", "2차전지", "조선방산"]),
    _channel("강환국 알고투자", "중립", "배분", ["국내주식", "미국주식", "거시시황"]),
    _channel("오건영의 경제읽기", "중립", "거시", ["거시시황"]),
    _channel("신과함께", "중립", "시황", ["국내주식", "거시시황"]),
    _channel("이브로TV", "강세", "종목", ["국내주식"]),
    _channel("주식하는 개미", "중립", "종목", ["국내주식"]),
    _channel("김준송TV", "신중", "거시", ["거시시황"]),
    _channel("후랭이TV", "중립", "배분", ["국내주식", "거시시황"]),
    _channel("머니인사이드", "중립", "시황", ["국내주식", "미국주식", "거시시황"]),
    _channel("경제읽어주는남자", "중립", "거시", ["거시시황"]),
    _channel("주코노미TV", "중립", "시황", ["국내주식"]),
    _channel("VIP TV", "신중", "종목", ["국내주식"]),
    _channel("홍진채", "신중", "종목", ["국내주식"]),
    _channel("김한진", "약세", "거시", ["거시시황"]),
    _channel("윤지호", "신중", "거시", ["거시시황", "국내주식"]),
    _channel("이선엽", "신중", "시황", ["국내주식", "거시시황"]),
    _channel("이효석", "중립", "거시", ["거시시황", "미국주식"]),

    # 종목형 보강: 국내·미국·섹터 특화 채널을 우선 수집 풀에 편입한다.
    _channel("전인구경제연구소", "중립", "종목", ["국내주식", "미국주식", "거시시황"]),
    _channel("냉철TV", "중립", "종목", ["국내주식"]),
    _channel("돈깡", "중립", "종목", ["국내주식"]),
    _channel("창원개미TV", "중립", "종목", ["국내주식"]),
    _channel("주식단테", "강세", "종목", ["국내주식"]),
    _channel("김종철프로증권", "중립", "종목", ["국내주식"]),
    _channel("부자아빠 주식학교", "강세", "종목", ["국내주식"]),
    _channel("이상로의 빨간주식", "강세", "종목", ["국내주식"]),
    _channel("주식초등학교", "중립", "종목", ["국내주식"]),
    _channel("이남우의 좋은주식연구소", "중립", "종목", ["국내주식", "미국주식"]),
    _channel("김현준 더퍼블릭자산운용", "중립", "종목", ["국내주식"]),
    _channel("염승환의 주식투자", "중립", "종목", ["국내주식"]),

    _channel("미주부", "중립", "종목", ["미국주식"]),
    _channel("미국주식 사관학교", "중립", "종목", ["미국주식"]),
    _channel("월가아재의 과학적 투자", "중립", "종목", ["미국주식", "거시시황"]),
    _channel("미국형님", "중립", "종목", ["미국주식"]),
    _channel("나스닥 사관학교", "중립", "종목", ["미국주식"]),
    _channel("더밀크", "중립", "종목", ["미국주식", "반도체", "거시시황"]),

    _channel("디일렉", "중립", "종목", ["반도체", "2차전지", "국내주식"]),
    _channel("테크월드뉴스", "중립", "종목", ["반도체", "국내주식"]),
    _channel("전자신문", "중립", "시황", ["반도체", "2차전지", "국내주식"]),
    _channel("IT의 신 이형수", "중립", "종목", ["반도체", "국내주식"]),
    _channel("박순혁TV", "강세", "종목", ["2차전지", "국내주식"]),
    _channel("선대인TV", "중립", "종목", ["2차전지", "국내주식", "거시시황"]),
    _channel("배터리 아저씨", "강세", "종목", ["2차전지", "국내주식"]),
    _channel("바이오스펙테이터", "중립", "종목", ["바이오", "국내주식"]),
    _channel("팜이데일리", "중립", "종목", ["바이오", "국내주식"]),
    _channel("히트뉴스", "중립", "시황", ["바이오", "국내주식"]),
    _channel("더구루", "중립", "종목", ["조선방산", "2차전지", "바이오", "국내주식", "미국주식"]),
    _channel("딜사이트", "중립", "종목", ["조선방산", "2차전지", "바이오", "국내주식"]),
    _channel("블로터", "중립", "시황", ["반도체", "2차전지", "바이오", "조선방산", "국내주식"]),
    _channel("국방TV", "중립", "시황", ["조선방산"]),
    _channel("비즈니스포스트", "중립", "시황", ["국내주식", "조선방산", "반도체", "2차전지"]),

    # 전체 시장 보강: 결과 표본이 적을 때 fallback 성격의 시황·뉴스 풀.
    _channel("토마토증권통", "중립", "종목", ["국내주식", "거시시황"]),
    _channel("매일경제TV", "중립", "시황", ["국내주식", "거시시황"]),
    _channel("MTN 머니투데이방송", "중립", "종목", ["국내주식", "거시시황"]),
    _channel("서울경제TV", "중립", "시황", ["국내주식", "거시시황"]),
    _channel("이데일리TV", "중립", "시황", ["국내주식", "거시시황"]),
    _channel("연합뉴스경제TV", "중립", "시황", ["국내주식", "거시시황"]),
    _channel("한국경제TV", "중립", "시황", ["국내주식", "거시시황"]),
    _channel("매경 월가월부", "중립", "시황", ["미국주식", "거시시황"]),
    _channel("어썸머니", "중립", "시황", ["국내주식", "미국주식", "거시시황"]),
    _channel("한경 글로벌마켓", "중립", "시황", ["미국주식", "거시시황"]),
    _channel("매경 자이앤트TV", "중립", "시황", ["국내주식", "미국주식", "거시시황"]),
    _channel("머니올라", "중립", "시황", ["국내주식", "거시시황"]),
    _channel("부꾸미", "중립", "시황", ["국내주식", "미국주식", "거시시황"]),
    _channel("리치고", "중립", "배분", ["국내주식", "거시시황"]),
    _channel("삼성증권 POP", "중립", "시황", ["국내주식", "미국주식", "거시시황"]),
]


# 로컬에서 resolve_pool.py 가 만든 channelId 매핑(channel_ids.json)이 있으면 채워넣는다.
# (config.py 본문을 건드리지 않고 ID만 외부에서 주입 → 깔끔하게 분리)
_IDS_FILE = PIPELINE_DIR / "channel_ids.json"
if _IDS_FILE.exists():
    import json as _json
    _ids = _json.loads(_IDS_FILE.read_text(encoding="utf-8"))
    for _c in CHANNELS:
        if not _c.get("channelId") and _c["name"] in _ids:
            _c["channelId"] = _ids[_c["name"]]


def tracked_roster():
    return [c for c in CHANNELS if c.get("tracked")]


def signal_pool():
    """종목 카드 집계용: 개별 종목을 다루는 채널(type='종목')만."""
    return [c for c in CHANNELS if c.get("type") == "종목"]


def selection_rule():
    return (f"구독자 {MIN_SUBSCRIBERS // 10000}만+ 주식 채널 {len(CHANNELS)}곳 · "
            f"최근 영상 중 조회수 상위 {MAX_ANALYZED_VIDEOS}개 분석")
