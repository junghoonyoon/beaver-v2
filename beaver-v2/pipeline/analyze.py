"""설정한 LLM 제공자로 자막을 분석한다."""
import hashlib
import json
import re
import time

import requests

import config

_client = None
# 모델 이름은 시기에 따라 바뀌므로, 설정값부터 순서대로 시도하고 되는 걸 캐시한다.
_CANDIDATES = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-flash-latest"]
_working = None
_CACHE_VERSION = 4
LAST_GENERATION_PROVIDER = None
_STOCK_STANCE_ALIASES = {
    "긍정": "긍정",
    "신중": "신중",
    "중립": "신중",
    "관망": "신중",
    "부정": "부정",
    "단순언급": "단순언급",
    "단순 언급": "단순언급",
}


def _client_lazy():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _is_transient(msg):
    msg = msg.lower()
    return any(s in msg for s in ("503", "unavailable", "429", "resource_exhausted", "overloaded", "high demand"))


def _generate_gemini(prompt):
    global _working
    if not config.GEMINI_API_KEY:
        raise RuntimeError("Gemini API 키가 없어요.")
    client = _client_lazy()
    order = []
    for n in [_working, config.GEMINI_MODEL] + _CANDIDATES:
        if n and n not in order:
            order.append(n)

    last = None
    for name in order:
        for attempt in range(4):  # 일시적 오류(503/429)면 점점 길게 기다리며 재시도
            try:
                resp = client.models.generate_content(model=name, contents=prompt)
                _working = name
                return resp.text
            except Exception as e:
                last = e
                if _is_transient(str(e)) and attempt < 3:
                    time.sleep(3 * (2 ** attempt))  # 3 → 6 → 12초
                    continue
                break  # 다른 종류 오류거나 재시도 소진 → 다음 모델로
    raise last


def _generate_ollama(prompt):
    """Ollama의 JSON 모드로 로컬 분석한다."""
    response = requests.post(
        f"{config.OLLAMA_URL.rstrip('/')}/api/chat",
        json={
            "model": config.OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": 0},
        },
        timeout=config.OLLAMA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    body = response.json()
    text = (body.get("message") or {}).get("content", "")
    if not text.strip():
        raise RuntimeError("Ollama가 빈 응답을 반환했어요.")
    # 다음 단계에서 JSON 구조를 검증할 수 있도록 여기서도 파싱 가능 여부를 확인한다.
    _extract_json(text)
    return text


def _generate_openrouter(prompt):
    """OpenRouter의 OpenAI 호환 Chat Completions API로 분석한다."""
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError("OpenRouter API 키가 없어요.")
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": config.OPENROUTER_TITLE,
    }
    if config.OPENROUTER_REFERER:
        headers["HTTP-Referer"] = config.OPENROUTER_REFERER

    response = requests.post(
        f"{config.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions",
        headers=headers,
        json={
            "model": config.OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        timeout=config.OLLAMA_TIMEOUT_SECONDS,
    )
    if response.status_code == 402:
        raise RuntimeError("OpenRouter 크레딧이 부족하거나 결제가 활성화되지 않았어요.")
    if response.status_code in (401, 403):
        raise RuntimeError("OpenRouter API 키 권한을 확인해 주세요.")
    response.raise_for_status()
    body = response.json()
    choices = body.get("choices") or []
    text = ((choices[0] if choices else {}).get("message") or {}).get("content", "")
    if not text.strip():
        raise RuntimeError("OpenRouter가 빈 응답을 반환했어요.")
    _extract_json(text)
    return text


def _generate(prompt, validator=None):
    """설정한 제공자 순서로 생성하고 실제 사용한 제공자를 기록한다."""
    global LAST_GENERATION_PROVIDER
    provider = config.ANALYSIS_PROVIDER.lower()
    errors = []

    if provider in ("local-first", "ollama"):
        try:
            text = _generate_ollama(prompt)
            if validator:
                validator(text)
            LAST_GENERATION_PROVIDER = f"ollama:{config.OLLAMA_MODEL}"
            return text
        except Exception as e:
            errors.append(f"Ollama: {str(e)[:180]}")
            if provider == "ollama":
                raise RuntimeError(errors[-1]) from e

    if provider in ("local-first", "gemini"):
        try:
            text = _generate_gemini(prompt)
            if validator:
                validator(text)
            LAST_GENERATION_PROVIDER = f"gemini:{_working or config.GEMINI_MODEL}"
            return text
        except Exception as e:
            errors.append(f"Gemini: {str(e)[:180]}")

    if provider == "openrouter":
        try:
            text = _generate_openrouter(prompt)
            if validator:
                validator(text)
            LAST_GENERATION_PROVIDER = f"openrouter:{config.OPENROUTER_MODEL}"
            return text
        except Exception as e:
            errors.append(f"OpenRouter: {str(e)[:180]}")

    LAST_GENERATION_PROVIDER = None
    raise RuntimeError(" / ".join(errors) or f"지원하지 않는 분석 방식: {provider}")


_ANALYZE_PROMPT = """다음은 한국 주식 유튜브 영상의 자막입니다. 내용을 분석해 아래 JSON으로만 답하세요.

{{
  "coreLines": ["…", "…", "…"],
  "verdict": "낙관|신중|경계 중 하나",
  "stockOpinions": [
    {{
      "name": "종목명",
      "stance": "긍정|중립|부정|단순언급 중 하나",
      "reason": "그 종목에 대한 화자의 판단 근거 한 문장"
    }}
  ],
  "beaverLine": "…"
}}

규칙:
- coreLines: 영상이 말한 핵심 사실 3줄. 객관적으로, 존댓말 "~요"로.
- verdict: 화자의 시장 입장을 분류. 상승/매수 우위면 "낙관", 관망/중립이면 "신중", 하락/리스크 경고 우위면 "경계".
- stockOpinions: 종목별 의견 최대 4개. 영상 전체 분위기를 종목 의견으로 복사하지 마세요.
  - 긍정: 해당 종목의 매수·상승·실적 개선을 명시적으로 주장
  - 중립: 관망·확인 필요·보유 또는 조건부 접근을 명시
  - 부정: 매도·하락·고평가·리스크 회피를 명시
  - 단순언급: 비교·뉴스·시장 설명에 이름만 등장하고 방향 판단은 없음
  - reason: 자막에서 확인되는 근거만 쓰고 추측하지 마세요.
- beaverLine: 차분한 핵심 판단 한 문장(약 25~40자, "~요"). "비버는" 같은 시그니처는 붙이지 마세요.

자막:
{transcript}
"""

_INSIGHTS_PROMPT = """오늘 분석한 한국 주식 유튜브 영상들의 요약입니다. 전체를 종합해 투자자에게 도움이 될 '오늘의 인사이트' 3줄을 뽑으세요.
합의(다수 의견)·핵심 종목·공통 대응전략 관점이면 좋습니다. JSON 배열로만 답하세요: ["…","…","…"]

요약들:
{summaries}
"""

_STOCK_OPINION_PROMPT = """다음은 주식 유튜브 자막 중 '{stock}' 관련 문맥입니다.
화자가 이 종목에 대해 실제로 어떤 의견을 냈는지 아래 JSON으로만 답하세요.

{{
  "mentioned": true,
  "stance": "긍정|신중|부정|단순언급 중 하나",
  "summary": "화자의 종목 의견을 1문장으로 요약",
  "evidence": "그 판단의 근거를 자막 내용에 근거해 1문장으로 요약"
}}

규칙:
- '{stock}' 또는 별칭({aliases})이 실제 종목·기업 의미로 언급되지 않았다면 mentioned=false로 답하세요.
- 시장 전체 분위기를 종목 의견으로 복사하지 마세요.
- 긍정·신중·부정은 화자가 '{stock}' 자체의 실적·주가·가치·매매 대응을 직접 평가한 경우에만 선택하세요.
- 다른 기업을 설명하기 위한 비교 대상, 시가총액 비교, 지수 구성종목 나열, 당일 등락 전달만 있으면 단순언급입니다.
- '{stock}'이 하락했다는 사실만 전달하고 향후 전망이나 대응 의견이 없으면 단순언급입니다.
- 긍정: 매수·상승·실적 개선·성장 기대를 명시적으로 말함.
- 신중: 관망·보유·조건부 접근·추가 확인 필요를 말함.
- 부정: 매도·하락·고평가·실적 악화·회피를 명시적으로 말함.
- 단순언급: 이름은 나왔지만 방향성 있는 판단이 없음.
- 자막에 없는 내용을 추측하지 마세요.
- summary와 evidence는 자연스러운 한국어 존댓말로 작성하세요.

자막 문맥:
{context}
"""


def _extract_json(text):
    text = (text or "").strip()
    m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    return json.loads(m.group(1) if m else text)


def _validate_analysis_text(text):
    data = _extract_json(text)
    if not isinstance(data, dict):
        raise ValueError("분석 결과가 JSON 객체가 아니에요.")
    if data.get("verdict") not in config.VERDICTS:
        raise ValueError("시장 판정이 없거나 잘못됐어요.")
    if not isinstance(data.get("coreLines"), list) or not data["coreLines"]:
        raise ValueError("핵심 요약이 없어요.")
    if not isinstance(data.get("stockOpinions", []), list):
        raise ValueError("종목 의견 형식이 잘못됐어요.")
    if not str(data.get("beaverLine", "")).strip():
        raise ValueError("한 줄 요약이 없어요.")


def _validate_insights_text(text):
    data = _extract_json(text)
    if not isinstance(data, list) or not data:
        raise ValueError("인사이트 결과가 JSON 배열이 아니에요.")


def _validate_stock_opinion_text(text):
    data = _extract_json(text)
    if not isinstance(data, dict) or not isinstance(data.get("mentioned"), bool):
        raise ValueError("종목 의견 결과 형식이 잘못됐어요.")
    if data.get("mentioned"):
        if _STOCK_STANCE_ALIASES.get(str(data.get("stance", "")).strip()) not in ("긍정", "신중", "부정", "단순언급"):
            raise ValueError("종목 의견 방향이 잘못됐어요.")
        if not str(data.get("summary", "")).strip():
            raise ValueError("종목 의견 요약이 없어요.")


def analyze_video(transcript):
    """자막 1건 -> 시장 판정과 종목별 의견."""
    data = _extract_json(_generate(
        _ANALYZE_PROMPT.format(transcript=transcript[:12000]),
        validator=_validate_analysis_text,
    ))
    if data.get("verdict") not in config.VERDICTS:
        data["verdict"] = "신중"
    data["coreLines"] = (data.get("coreLines") or [])[:3]
    opinions = []
    for raw in (data.get("stockOpinions") or [])[:4]:
        name = str(raw.get("name", "")).strip()
        stance = raw.get("stance")
        reason = str(raw.get("reason", "")).strip()
        if not name or stance not in ("긍정", "중립", "부정", "단순언급"):
            continue
        opinions.append({"name": name, "stance": stance, "reason": reason})
    data["stockOpinions"] = opinions
    # 기존 영상 카드와의 호환용. 종목 신호 집계는 stockOpinions만 사용한다.
    data["stocks"] = [o["name"] for o in opinions]
    return data


def analyze_video_cached(video_id, transcript, force=False):
    """같은 영상·같은 자막은 로컬·Gemini 어디에도 다시 보내지 않는다."""
    global LAST_GENERATION_PROVIDER
    config.ANALYSIS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = config.ANALYSIS_CACHE_DIR / f"{video_id}.json"
    digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    if path.exists() and not force and not config.FORCE_ANALYSIS_REFRESH:
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("version") == _CACHE_VERSION and cached.get("transcriptHash") == digest:
                LAST_GENERATION_PROVIDER = cached.get("provider", "cache")
                return cached["data"], True
        except (OSError, ValueError, KeyError):
            pass

    LAST_GENERATION_PROVIDER = None
    data = analyze_video(transcript)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "version": _CACHE_VERSION,
        "transcriptHash": digest,
        "provider": LAST_GENERATION_PROVIDER,
        "data": data,
    }, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return data, False


def make_insights(analyzed):
    """분석된 영상 전체 -> 인사이트 3줄."""
    summaries = "\n".join(
        f"- [{a['verdict']}] {a['channel']}: {a['beaverLine']}" for a in analyzed)
    return _extract_json(_generate(
        _INSIGHTS_PROMPT.format(summaries=summaries),
        validator=_validate_insights_text,
    ))[:3]


def analyze_stock_opinion(stock, aliases, context):
    """검색한 특정 종목에 대한 의견만 집중 분석한다."""
    data = _extract_json(_generate(
        _STOCK_OPINION_PROMPT.format(
            stock=stock,
            aliases=", ".join(aliases),
            context=context[:config.SEARCH_CONTEXT_MAX_CHARS],
        ),
        validator=_validate_stock_opinion_text,
    ))
    if not data.get("mentioned"):
        return {"mentioned": False, "stance": "단순언급", "summary": "", "evidence": ""}
    stance = _STOCK_STANCE_ALIASES.get(str(data.get("stance", "")).strip(), data.get("stance"))
    return {
        "mentioned": True,
        "stance": stance,
        "summary": str(data.get("summary", "")).strip(),
        "evidence": str(data.get("evidence", "")).strip(),
    }
