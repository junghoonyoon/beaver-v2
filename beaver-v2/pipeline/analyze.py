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
_SPEECH_TYPE_ALIASES = {
    "명시적 전망": "명시적 전망",
    "조건부 전망": "조건부 전망",
    "사후 해석": "사후 해석",
    "뉴스 전달": "뉴스 전달",
    "서사 강조": "서사 강조",
    "투자 조언 회피": "투자 조언 회피",
    "단순언급": "뉴스 전달",
    "단순 언급": "뉴스 전달",
}
_TIME_ORIENTATION_ALIASES = {
    "미래 전망": "미래 전망",
    "현재 진단": "현재 진단",
    "과거 설명": "과거 설명",
}
_CONFIDENCE_ALIASES = {
    "강함": "강함",
    "보통": "보통",
    "약함": "약함",
}
_RATIONALE_TYPE_ALIASES = {
    "실적": "실적",
    "수급": "수급",
    "밸류": "밸류",
    "금리": "금리",
    "정책": "정책",
    "테마": "테마",
    "차트": "차트",
    "뉴스": "뉴스",
    "기타": "기타",
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
  "summary": "판단: 화자가 이 종목을 어떻게 보는지 결론만 1문장으로 압축",
  "evidence": "근거: 그 판단을 뒷받침한 자막 속 사건·수치·맥락을 1문장으로 설명",
  "speechType": "명시적 전망|조건부 전망|사후 해석|뉴스 전달|서사 강조|투자 조언 회피 중 하나",
  "timeOrientation": "미래 전망|현재 진단|과거 설명 중 하나",
  "confidence": "강함|보통|약함 중 하나",
  "rationaleType": "실적|수급|밸류|금리|정책|테마|차트|뉴스|기타 중 하나",
  "opinionType": "현재 투자 의견|조건부 투자 의견|보유/관망 의견|단기 수급 해석|과거 투자 사례|관련주/비교 맥락|시황/뉴스 전달|정보성 언급 중 하나",
  "evaluable": true
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
- opinionType:
  - 현재 투자 의견: 지금 이 종목의 매수·상승·하락·가치·보유 판단을 직접 말함.
  - 조건부 투자 의견: 실적·수급·가격 등 조건 확인 후 접근을 말함.
  - 보유/관망 의견: 보유·관망·추가 확인을 권함.
  - 단기 수급 해석: 이미 일어난 등락을 수급·청산·매물로 설명함.
  - 과거 투자 사례: 과거 매수·수익 경험이나 성공담이 중심임.
  - 관련주/비교 맥락: 다른 종목의 수혜·비교를 설명하기 위해 이 종목이 등장함.
  - 시황/뉴스 전달: 당일 등락·뉴스·시장 상황 전달이 중심임.
  - 정보성 언급: 기업 설명·지분 관계·나열 수준임.
- 현재 투자 의견, 조건부 투자 의견, 보유/관망 의견이 아니면 긍정·신중·부정으로 과도하게 분류하지 말고 단순언급을 우선하세요.
- 자막에 없는 내용을 추측하지 마세요.
- summary는 굵게 보이는 판단 문장입니다. evidence와 같은 표현을 반복하지 말고, 결론/전망/대응 방향만 20~45자 안팎으로 쓰세요.
- evidence는 회색 근거 문장입니다. summary를 다시 말하지 말고, 판단의 근거가 된 구체적 사건·수치·발언 맥락을 쓰세요.
- 숫자, 실적 발표, 시간외 등락, 리포트, 비교 대상 같은 근거 설명은 evidence에 남기세요.
- speechType:
  - 명시적 전망: 앞으로 오르거나 내린다는 방향을 비교적 분명히 말함.
  - 조건부 전망: "~하면", "확인되면", "수급이 붙으면"처럼 조건을 달아 판단함.
  - 사후 해석: 이미 오른/내린 뒤 그 이유를 설명함.
  - 뉴스 전달: 사실·뉴스·등락 전달이 중심임.
  - 서사 강조: 숫자보다 테마·스토리·큰 그림 설명이 중심임.
  - 투자 조언 회피: 양쪽 가능성을 열어두고 판단을 피함.
- timeOrientation은 발화의 중심 시점입니다. 미래를 말하면 미래 전망, 현재 상태를 말하면 현재 진단, 이미 일어난 일을 설명하면 과거 설명입니다.
- confidence는 단정 정도입니다. 강한 매수/매도·확신 표현은 강함, 조건·유보가 많으면 약함입니다.
- rationaleType은 판단 근거의 핵심 축 하나만 고르세요.
- evaluable은 사후 주가와 방향성을 비교할 수 있는 명시적/조건부 전망일 때만 true입니다. 사후 해석, 뉴스 전달, 단순언급은 false입니다.
- summary와 evidence는 자연스러운 한국어 존댓말로 작성하세요.

자막 문맥:
{context}
"""


_STOCK_REPORT_PROMPT = """다음은 최근 2주 동안 주식 유튜버들이 '{stock}'에 대해 낸 투자 의견 목록입니다.
이 의견들만 근거로 '{stock}' 요약 리포트를 아래 JSON으로만 답하세요.

의견 목록 (id / 채널 / 날짜 / 방향 / 판단 / 근거):
{opinions}

{{
  "headline": "지금 이 종목 판단을 쉼표 없이 완결된 한 문장으로 (20~45자, ~요)",
  "summary": "긍정과 관망이 각각 무엇을 근거로 삼는지 한 문장으로 종합 (40~90자)",
  "consensus": {{"text": "긍정·관망 양쪽이 공통으로 인정한 사실. 없으면 빈 문자열", "videoIds": ["…"]}},
  "bullCase": {{"text": "좋게 보는 쪽의 핵심 논리. 무엇을 근거로 긍정적으로 보는지", "videoIds": ["…"]}},
  "bearCase": {{"text": "관망·부정 쪽의 핵심 논리. 긍정 쪽과 무엇을 다르게 해석하는지가 드러나게", "videoIds": ["…"]}},
  "turningPoint": {{"text": "관망 의견이 긍정으로 바뀌기 위한 조건. 의견에 없으면 빈 문자열", "videoIds": ["…"]}},
  "checkpoints": [
    {{
      "event": "확인할 이벤트나 지표 이름 (예: 2분기 실적 발표)",
      "when": "확인 시점. 의견에 언급된 경우만 (예: 다음 주, 7월 말). 없으면 빈 문자열",
      "check": "무엇을 어떤 기준으로 확인해야 하는지 1문장",
      "interpretation": "확인 결과가 좋으면/나쁘면 어느 쪽 의견에 힘이 실리는지 1문장",
      "videoIds": ["…"]
    }}
  ]
}}

규칙:
- 위 JSON 구조를 그대로 지키세요. consensus, bullCase, bearCase, turningPoint는 절대 문자열이 아니라 반드시 {{"text": "...", "videoIds": ["..."]}} 객체여야 합니다.
- 최상위에는 videoIds 키를 만들지 마세요. 각 근거 id는 해당 section 객체나 checkpoint 안에만 넣으세요.
- 의견 목록에 실제로 나온 사실·수치·일정만 쓰세요. 목록에 없는 내용을 추측하거나 일반론을 만들지 마세요.
- 수치는 의견 목록의 표현을 그대로 쓰세요. 조/억/만 같은 단위를 합치거나 변환하지 마세요.
- headline은 반드시 20~45자 안에서 끝나는 완결 문장으로 쓰고, 길어서 중간에 끊길 문장은 만들지 마세요.
- summary는 40~90자의 한 문장으로 쓰고, bullCase/bearCase 내용을 길게 반복하지 마세요.
- bullCase와 bearCase는 의견 목록에 해당 방향 의견이 있으면 반드시 채우세요. 직접 권유 표현을 피하되 빈 문자열로 두지 마세요.
- checkpoints는 2~4개. "실적 확인하세요" 같은 막연한 항목 대신, 의견에 언급된 구체적 이벤트(실적 발표, 상장, 계약, 가격 지표 등)를 고르세요.
- when은 의견에 시점이 언급된 경우만 쓰고, 지어내지 마세요.
- videoIds에는 그 문장의 근거가 된 의견의 id만 넣으세요. 목록에 없는 id를 만들지 마세요.
- bullCase와 bearCase는 같은 사실을 반복하지 말고, 두 쪽 해석이 갈리는 지점이 대비되게 쓰세요.
- 특정 채널 이름을 문장 안에 쓰지 마세요.
- 모든 문장은 자연스러운 한국어 존댓말("~요", "~하세요")로 쓰세요.
- 매수·매도를 직접 권유하는 표현("사세요", "파세요", "매수를 권유", "추천", "사도 된다", "권했어요")은 쓰지 마세요. 대신 "긍정적으로 봤어요", "신중하게 봤어요"처럼 의견으로 표현하세요.
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


def _validate_stock_report_text(text):
    data = _extract_json(text)
    if not isinstance(data, dict):
        raise ValueError("요약 리포트 결과가 JSON 객체가 아니에요.")
    if not str(data.get("headline", "")).strip():
        raise ValueError("요약 리포트 헤드라인이 없어요.")
    checkpoints = data.get("checkpoints")
    if not isinstance(checkpoints, list) or not checkpoints:
        raise ValueError("체크포인트가 없어요.")
    bull = data.get("bullCase") or {}
    bear = data.get("bearCase") or {}
    if not str((bull if isinstance(bull, dict) else {}).get("text", "")).strip() and \
            not str((bear if isinstance(bear, dict) else {}).get("text", "")).strip():
        raise ValueError("긍정·관망 논리가 모두 비어 있어요.")


def _clip_text(value, limit=220):
    text = str(value or "").strip()
    return text[:limit]


def _report_section(raw, allowed_ids):
    section = raw if isinstance(raw, dict) else {}
    video_ids = [str(v).strip() for v in (section.get("videoIds") or []) if str(v).strip()]
    return {
        "text": _clip_text(section.get("text"), 360),
        "videoIds": [v for v in video_ids if v in allowed_ids][:4],
    }


def _normalize_stock_report(data, allowed_ids):
    allowed_ids = set(allowed_ids or [])
    checkpoints = []
    for raw in (data.get("checkpoints") or [])[:4]:
        if not isinstance(raw, dict):
            continue
        event = _clip_text(raw.get("event"), 60)
        check = _clip_text(raw.get("check"), 160)
        if not event or not check:
            continue
        video_ids = [str(v).strip() for v in (raw.get("videoIds") or []) if str(v).strip()]
        checkpoints.append({
            "event": event,
            "when": _clip_text(raw.get("when"), 40),
            "check": check,
            "interpretation": _clip_text(raw.get("interpretation"), 160),
            "videoIds": [v for v in video_ids if v in allowed_ids][:4],
        })
    if not checkpoints:
        raise ValueError("사용할 수 있는 체크포인트가 없어요.")
    return {
        "headline": _clip_text(data.get("headline"), 100),
        "summary": _clip_text(data.get("summary"), 140),
        "consensus": _report_section(data.get("consensus"), allowed_ids),
        "bullCase": _report_section(data.get("bullCase"), allowed_ids),
        "bearCase": _report_section(data.get("bearCase"), allowed_ids),
        "turningPoint": _report_section(data.get("turningPoint"), allowed_ids),
        "checkpoints": checkpoints,
    }


def _pick_allowed(value, aliases, default):
    value = str(value or "").strip()
    return aliases.get(value, default)


def _default_speech_type(stance, summary="", evidence=""):
    text = f"{summary} {evidence}"
    if stance == "단순언급":
        return "뉴스 전달"
    if any(word in text for word in ("이미", "때문에 올랐", "때문에 내렸", "하락한 이유", "상승한 이유")):
        return "사후 해석"
    if any(word in text for word in ("조건", "확인", "붙으면", "나오면", "돌파하면", "회복하면")):
        return "조건부 전망"
    return "명시적 전망"


def _default_time_orientation(speech_type):
    if speech_type == "사후 해석":
        return "과거 설명"
    if speech_type in ("뉴스 전달", "투자 조언 회피"):
        return "현재 진단"
    return "미래 전망"


def _bool_value(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "y"):
        return True
    if text in ("false", "0", "no", "n"):
        return False
    return default


def _normalize_stock_opinion(data):
    if not data.get("mentioned"):
        return {
            "mentioned": False,
            "stance": "단순언급",
            "summary": "",
            "evidence": "",
            "speechType": "뉴스 전달",
            "timeOrientation": "현재 진단",
            "confidence": "약함",
            "rationaleType": "기타",
            "evaluable": False,
        }
    stance = _STOCK_STANCE_ALIASES.get(str(data.get("stance", "")).strip(), data.get("stance"))
    summary = str(data.get("summary", "")).strip()
    evidence = str(data.get("evidence", "")).strip()
    default_speech = _default_speech_type(stance, summary, evidence)
    speech_type = _pick_allowed(data.get("speechType"), _SPEECH_TYPE_ALIASES, default_speech)
    time_orientation = _pick_allowed(
        data.get("timeOrientation"),
        _TIME_ORIENTATION_ALIASES,
        _default_time_orientation(speech_type),
    )
    default_confidence = "약함" if speech_type in ("조건부 전망", "투자 조언 회피", "뉴스 전달") else "보통"
    confidence = _pick_allowed(data.get("confidence"), _CONFIDENCE_ALIASES, default_confidence)
    rationale_type = _pick_allowed(data.get("rationaleType"), _RATIONALE_TYPE_ALIASES, "기타")
    default_evaluable = speech_type in ("명시적 전망", "조건부 전망") and stance in ("긍정", "부정")
    evaluable = _bool_value(data.get("evaluable"), default_evaluable) and default_evaluable
    return {
        "mentioned": True,
        "stance": stance,
        "summary": summary,
        "evidence": evidence,
        "speechType": speech_type,
        "timeOrientation": time_orientation,
        "confidence": confidence,
        "rationaleType": rationale_type,
        "opinionType": str(data.get("opinionType") or "").strip(),
        "evaluable": evaluable,
    }


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


def _report_opinion_line(opinion):
    published = str(opinion.get("publishedAt") or "")[:10]
    summary = str(opinion.get("summary") or "").strip()
    evidence = str(opinion.get("evidence") or "").strip()
    return (
        f"- id={opinion.get('videoId') or ''} / {opinion.get('channel') or '채널'} / {published} / "
        f"{opinion.get('stance') or ''} / 판단: {summary} / 근거: {evidence}"
    )


def analyze_stock_report(stock, opinions):
    """판단 가능한 의견 묶음 -> 쟁점·체크포인트 중심 요약 리포트."""
    rows = [op for op in (opinions or []) if str(op.get("summary") or "").strip()]
    if len(rows) < 2:
        raise ValueError("요약 리포트를 만들 의견이 부족해요.")
    allowed_ids = [str(op.get("videoId") or "").strip() for op in rows]
    allowed_ids = [v for v in allowed_ids if v]
    data = _extract_json(_generate(
        _STOCK_REPORT_PROMPT.format(
            stock=stock,
            opinions="\n".join(_report_opinion_line(op) for op in rows[:20]),
        ),
        validator=_validate_stock_report_text,
    ))
    return _normalize_stock_report(data, allowed_ids)


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
    return _normalize_stock_opinion(data)
