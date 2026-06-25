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

# ── API 키 (환경변수에서) ──
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
SUPADATA_API_KEY = os.environ.get("SUPADATA_API_KEY", "")  # 무료 경로 실패 시 유료 fallback
KRX_API_KEY = os.environ.get("KRX_API_KEY", "")
KRX_LISTED_API_URL = os.environ.get(
    "KRX_LISTED_API_URL",
    "https://apis.data.go.kr/1160100/service/GetKrxListedInfoService/getItemInfo",
)
KRX_LISTED_REFRESH_HOURS = int(os.environ.get("KRX_LISTED_REFRESH_HOURS", "24"))
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
SEARCH_MAX_VIDEOS_PER_CHANNEL = int(os.environ.get("SEARCH_MAX_VIDEOS_PER_CHANNEL", "5"))
SEARCH_MAX_YOUTUBERS = int(os.environ.get("SEARCH_MAX_YOUTUBERS", "10"))
SEARCH_MAX_ANALYZED_VIDEOS = int(os.environ.get("SEARCH_MAX_ANALYZED_VIDEOS", "5"))
SEARCH_CONTEXT_WINDOW = int(os.environ.get("SEARCH_CONTEXT_WINDOW", "450"))
SEARCH_CONTEXT_MAX_CHARS = int(os.environ.get("SEARCH_CONTEXT_MAX_CHARS", "4000"))
SEARCH_CONTEXT_MAX_SPANS = int(os.environ.get("SEARCH_CONTEXT_MAX_SPANS", "4"))
TRANSCRIPT_FAILURE_TTL_HOURS = int(os.environ.get("TRANSCRIPT_FAILURE_TTL_HOURS", "12"))
TRANSCRIPT_REQUEST_DELAY_SECONDS = float(os.environ.get("TRANSCRIPT_REQUEST_DELAY_SECONDS", "1.0"))
FORCE_TRANSCRIPT_REFRESH = os.environ.get("FORCE_TRANSCRIPT_REFRESH", "") == "1"
FORCE_ANALYSIS_REFRESH = os.environ.get("FORCE_ANALYSIS_REFRESH", "") == "1"

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
CHANNELS = [
    {"name": "삼프로TV",              "channelId": "", "lean": "중립", "type": "시황", "tracked": True},
    {"name": "슈카월드",              "channelId": "", "lean": "신중", "type": "거시", "tracked": True},
    {"name": "815머니톡",             "channelId": "", "lean": "강세", "type": "시황", "tracked": True},
    {"name": "김작가 TV",             "channelId": "", "lean": "중립", "type": "시황", "tracked": True},
    {"name": "박곰희TV",              "channelId": "", "lean": "중립", "type": "배분", "tracked": True},
    {"name": "달란트투자",            "channelId": "", "lean": "강세", "type": "종목"},
    {"name": "상승효과TV",            "channelId": "UCINSVY-JDQraydXAdfMIbPg", "lean": "중립", "type": "시황"},  # @sng_tv · '시장을 꿰뚫는 주식 투자의 기술' 저자
    {"name": "소수몽키",              "channelId": "", "lean": "중립", "type": "종목"},
    {"name": "미국주식으로 은퇴하기",   "channelId": "", "lean": "강세", "type": "종목"},
    {"name": "김단테",                "channelId": "", "lean": "중립", "type": "배분"},
    {"name": "증시각도기TV",          "channelId": "", "lean": "강세", "type": "종목"},  # 염승환 (개인 채널 '염승환의 주식투자'와 동일 인물 → 중복 제거)
    {"name": "한국경제TV뉴스",         "channelId": "", "lean": "중립", "type": "시황"},
    {"name": "와이스트릿",            "channelId": "", "lean": "중립", "type": "시황"},
    {"name": "홍춘욱의 경제강의노트",   "channelId": "", "lean": "중립", "type": "거시"},
    {"name": "김영익의 경제스쿨",      "channelId": "", "lean": "약세", "type": "거시"},
    {"name": "슈퍼개미 김정환",        "channelId": "", "lean": "강세", "type": "종목"},
    {"name": "메르의 투자노트",        "channelId": "", "lean": "중립", "type": "종목"},
    {"name": "강환국 알고투자",        "channelId": "", "lean": "중립", "type": "배분"},
    {"name": "오건영의 경제읽기",      "channelId": "", "lean": "중립", "type": "거시"},
    {"name": "신과함께",              "channelId": "", "lean": "중립", "type": "시황"},
    {"name": "이브로TV",              "channelId": "", "lean": "강세", "type": "종목"},
    {"name": "주식하는 개미",          "channelId": "", "lean": "중립", "type": "종목"},
    {"name": "김준송TV",              "channelId": "", "lean": "신중", "type": "거시"},
    {"name": "정채진 투자노트",        "channelId": "", "lean": "중립", "type": "종목"},
    {"name": "이타인클럽",            "channelId": "", "lean": "중립", "type": "종목"},
    {"name": "후랭이TV",              "channelId": "", "lean": "중립", "type": "배분"},  # 부동산·재테크 비중 큼 — 주식 신호용으론 약함
    {"name": "머니인사이드",          "channelId": "", "lean": "중립", "type": "시황"},
    {"name": "경제읽어주는남자",       "channelId": "", "lean": "중립", "type": "거시"},
    {"name": "주코노미TV",            "channelId": "", "lean": "중립", "type": "시황"},
    # ── 균형 보강 (신중·약세 쪽 — 가치투자 운용사·전직 애널리스트) ──
    {"name": "VIP TV",                "channelId": "", "lean": "신중", "type": "종목"},  # 최준철·김민국, VIP자산운용 (가치투자, 밸류 보수)
    {"name": "홍진채",                "channelId": "", "lean": "신중", "type": "종목"},  # 라쿤자산운용 (가치투자)
    {"name": "김한진",                "channelId": "", "lean": "약세", "type": "거시"},  # 삼프로TV 이코노미스트
    {"name": "윤지호",                "channelId": "", "lean": "신중", "type": "거시"},  # 전 이베스트 리서치센터장
    {"name": "이선엽",                "channelId": "", "lean": "신중", "type": "시황"},  # AFW파트너스, 전 신한 투자전략팀장
    {"name": "이효석",                "channelId": "", "lean": "중립", "type": "거시"},  # HS아카데미, 전 SK증권
    # {"name": "사경인",              "channelId": "", "lean": "신중", "type": "종목"},  # 회계·재무제표 리스크 관점 — 최근 활동 검증 후 활성화
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
