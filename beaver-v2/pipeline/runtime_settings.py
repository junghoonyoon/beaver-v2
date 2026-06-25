"""설정.txt 값을 환경변수로 올리는 공통 도우미."""
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SETTINGS = HERE.parent / "설정.txt"
PLACEHOLDER_PREFIXES = ("여기에_", "새_키_", "YOUR_")
FIELDS = [
    ("제미나이키", "GEMINI_API_KEY"),
    ("유튜브키", "YOUTUBE_API_KEY"),
    ("자막키", "SUPADATA_API_KEY"),
    ("공공데이터키", "KRX_API_KEY"),
    ("KRX키", "KRX_API_KEY"),
    ("분석방식", "ANALYSIS_PROVIDER"),
    ("로컬모델", "OLLAMA_MODEL"),
    ("오픈라우터키", "OPENROUTER_API_KEY"),
    ("오픈라우터모델", "OPENROUTER_MODEL"),
    ("오픈라우터URL", "OPENROUTER_BASE_URL"),
    ("오픈라우터리퍼러", "OPENROUTER_REFERER"),
    ("검색분석수", "SEARCH_MAX_ANALYZED_VIDEOS"),
    ("검색후보수", "SEARCH_MAX_YOUTUBERS"),
    ("검색문맥길이", "SEARCH_CONTEXT_MAX_CHARS"),
]


def load_settings():
    if not SETTINGS.exists():
        return
    text = SETTINGS.read_text(encoding="utf-8")
    for label, env in FIELDS:
        match = re.search(rf"^{label}\s*=\s*(.*?)\s*$", text, re.MULTILINE)
        if not match:
            continue
        value = match.group(1).strip()
        if value and not value.startswith(PLACEHOLDER_PREFIXES):
            os.environ[env] = value
