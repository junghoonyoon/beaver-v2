"""MVP 운영 지표 이벤트 수집과 대시보드 집계를 담당한다."""
import datetime
import json
import threading
from collections import defaultdict

import config
import remote_cache

KST = datetime.timezone(datetime.timedelta(hours=9))
REMOTE_PATH = "analytics/events.jsonl"
_LOCK = threading.Lock()
_MAX_FIELD_LENGTH = 300

EVENT_TYPES = {
    "page_view",
    "session_start",
    "session_end",
    "search_submit",
    "search_result",
    "stock_detail_view",
    "video_click",
    "share_click",
    "share_success",
    "market_mood_view",
    "market_mood_notice_view",
    "stance_filter_click",
}


def _now():
    return datetime.datetime.now(KST)


def _event_path():
    return config.ANALYTICS_EVENTS_JSONL


def _sync_remote_if_needed():
    path = _event_path()
    if path.exists():
        return
    remote_cache.download_to_file(REMOTE_PATH, path)


def _event_line(event):
    return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def _event_key(line):
    try:
        event = json.loads(line)
    except ValueError:
        return ("raw", line)
    return (
        event.get("timestamp"),
        event.get("type"),
        event.get("userId"),
        event.get("sessionId"),
        event.get("path"),
        event.get("query"),
        event.get("stockCode"),
        event.get("label"),
        event.get("url"),
        event.get("clickTarget"),
    )


def _jsonl_lines(body):
    if not body:
        return []
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="ignore")
    return [line for line in str(body).splitlines() if line.strip()]


def _local_event_lines(path):
    if not path.exists():
        return []
    return _jsonl_lines(path.read_text(encoding="utf-8"))


def _merge_event_lines(*groups):
    merged = []
    seen = set()
    for lines in groups:
        for line in lines:
            key = _event_key(line)
            if key in seen:
                continue
            seen.add(key)
            merged.append(line)
    return merged


def _write_event_lines(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(lines)
    if body:
        body += "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)


def _backup_remote_events(remote_body):
    if not remote_body:
        return
    stamp = _now().strftime("%Y%m%d-%H%M%S")
    remote_cache.upload_bytes(
        f"analytics/backups/events-{stamp}.jsonl",
        remote_body,
        "application/x-ndjson; charset=utf-8",
    )


def _append_event_safely(path, event):
    local_lines = _local_event_lines(path)
    remote_body = remote_cache.download_bytes(REMOTE_PATH)
    remote_lines = _jsonl_lines(remote_body)
    if remote_lines and len(local_lines) < len(remote_lines):
        _backup_remote_events(remote_body)
        print(
            "  ⚠️ analytics 원격 이벤트가 로컬보다 큽니다. "
            f"remote={len(remote_lines)} local={len(local_lines)} 병합 후 업로드합니다."
        )
    merged = _merge_event_lines(remote_lines, local_lines, [_event_line(event)])
    _write_event_lines(path, merged)
    remote_cache.upload_bytes(
        REMOTE_PATH,
        path.read_bytes(),
        "application/x-ndjson; charset=utf-8",
    )


def _short(value, limit=_MAX_FIELD_LENGTH):
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _safe_bool(value):
    return bool(value) if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes")


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def _date_key(dt):
    return dt.astimezone(KST).date().isoformat()


def _pct(numerator, denominator):
    if not denominator:
        return 0.0
    return round(numerator / denominator * 100, 1)


def _duration_text(milliseconds):
    if not milliseconds:
        return "0:00"
    seconds = max(0, round(milliseconds / 1000))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _metric(key, label, value, sub, raw=0, unit="number"):
    return {
        "key": key,
        "label": label,
        "value": value,
        "sub": sub,
        "raw": raw,
        "unit": unit,
    }


def _clean_event(payload):
    event_type = _short(payload.get("type"), 60)
    if event_type not in EVENT_TYPES:
        raise ValueError("지원하지 않는 이벤트입니다.")
    return {
        "type": event_type,
        "timestamp": _now().isoformat(),
        "userId": _short(payload.get("userId"), 80),
        "sessionId": _short(payload.get("sessionId"), 80),
        "path": _short(payload.get("path"), 200),
        "query": _short(payload.get("query"), 100),
        "stockCode": _short(payload.get("stockCode"), 40),
        "success": _safe_bool(payload.get("success")),
        "matchedVideos": _safe_int(payload.get("matchedVideos")),
        "opinionCount": _safe_int(payload.get("opinionCount")),
        "marketMood": _short(payload.get("marketMood") or payload.get("marketMoodLabel"), 80),
        "positiveCount": _safe_int(payload.get("positiveCount")),
        "watchCount": _safe_int(payload.get("watchCount")),
        "riskCount": _safe_int(payload.get("riskCount")),
        "mentionOnlyCount": _safe_int(payload.get("mentionOnlyCount", payload.get("infoMentionCount"))),
        "durationMs": _safe_int(payload.get("durationMs")),
        "url": _short(payload.get("url"), 300),
        "method": _short(payload.get("method"), 40),
        "label": _short(payload.get("label"), 120),
        "clickTarget": _short(payload.get("clickTarget"), 60),
        "stance": _short(payload.get("stance"), 40),
        "error": _short(payload.get("error"), 200),
    }


def record_event(payload):
    event = _clean_event(payload or {})
    if not event["userId"]:
        event["userId"] = event["sessionId"] or "anonymous"
    path = _event_path()
    with _LOCK:
        _append_event_safely(path, event)
    return event


def load_events():
    with _LOCK:
        _sync_remote_if_needed()
        path = _event_path()
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            ts = _parse_time(event.get("timestamp"))
            if not ts:
                continue
            event["_time"] = ts
            event["_date"] = _date_key(ts)
            rows.append(event)
        return rows


def _first_seen_by_user(events):
    first_seen = {}
    for event in events:
        user_id = event.get("userId")
        if not user_id or event.get("type") != "page_view":
            continue
        current = first_seen.get(user_id)
        if current is None or event["_time"] < current:
            first_seen[user_id] = event["_time"]
    return first_seen


def _users_for(events, event_type):
    return {event.get("userId") for event in events if event.get("type") == event_type and event.get("userId")}


def _daily_search_rates(period_events, days):
    by_date = {day: {"visitors": set(), "searchers": set()} for day in days}
    for event in period_events:
        row = by_date.get(event["_date"])
        if not row:
            continue
        if event.get("type") == "page_view":
            row["visitors"].add(event.get("userId"))
        if event.get("type") == "search_submit":
            row["searchers"].add(event.get("userId"))
    return [
        {
            "date": day,
            "rate": _pct(len(row["searchers"]), len(row["visitors"])),
        }
        for day, row in by_date.items()
    ]


def _retention_rate(first_seen, page_views, cohort_date, after_days):
    cohort_users = {user for user, first in first_seen.items() if first.date() == cohort_date}
    if not cohort_users:
        return None
    target = (cohort_date + datetime.timedelta(days=after_days)).isoformat()
    retained = {
        event.get("userId")
        for event in page_views
        if event.get("userId") in cohort_users and event["_date"] == target
    }
    return _pct(len(retained), len(cohort_users))


def _retention_cohorts(first_seen, page_views, today):
    starts = [today - datetime.timedelta(days=14), today - datetime.timedelta(days=7), today]
    rows = []
    for start in starts:
        row = {"date": start.isoformat()}
        for day in (1, 3, 7, 14):
            row[f"d{day}"] = _retention_rate(first_seen, page_views, start, day)
        rows.append(row)
    return rows


def _search_terms(searches, search_results):
    rows = defaultdict(lambda: {
        "query": "",
        "count": 0,
        "users": set(),
        "resultCount": 0,
        "failedCount": 0,
        "lastSearchedAt": None,
    })
    for event in searches:
        query = (event.get("query") or event.get("stockCode") or "").strip() or "(빈 검색어)"
        row = rows[query]
        row["query"] = query
        row["count"] += 1
        if event.get("userId"):
            row["users"].add(event.get("userId"))
        if row["lastSearchedAt"] is None or event["_time"] > row["lastSearchedAt"]:
            row["lastSearchedAt"] = event["_time"]
    for event in search_results:
        query = (event.get("query") or event.get("stockCode") or "").strip() or "(빈 검색어)"
        row = rows[query]
        row["query"] = query
        row["resultCount"] += 1
        if not event.get("success"):
            row["failedCount"] += 1
    return [
        {
            "query": row["query"],
            "count": row["count"],
            "users": len(row["users"]),
            "failedCount": row["failedCount"],
            "successRate": _pct(row["resultCount"] - row["failedCount"], row["resultCount"]) if row["resultCount"] else None,
            "lastSearchedAt": row["lastSearchedAt"].isoformat() if row["lastSearchedAt"] else None,
        }
        for row in sorted(rows.values(), key=lambda item: (-item["count"], item["query"]))[:20]
        if row["count"] > 0
    ]


def dashboard_metrics(days=7):
    days = max(1, min(int(days or 7), 31))
    now = _now()
    today = now.date()
    start = today - datetime.timedelta(days=days - 1)
    day_keys = [(start + datetime.timedelta(days=idx)).isoformat() for idx in range(days)]
    events = load_events()
    first_event_at = min((event["_time"] for event in events), default=None)
    period_events = [event for event in events if start <= event["_time"].date() <= today]
    today_events = [event for event in events if event["_time"].date() == today]
    page_views = [event for event in events if event.get("type") == "page_view"]
    period_page_views = [event for event in period_events if event.get("type") == "page_view"]
    today_page_views = [event for event in today_events if event.get("type") == "page_view"]
    first_seen = _first_seen_by_user(events)

    visitors = _users_for(period_events, "page_view")
    today_visitors = _users_for(today_events, "page_view")
    searchers = _users_for(period_events, "search_submit")
    detail_users = _users_for(period_events, "stock_detail_view")
    video_users = _users_for(period_events, "video_click")
    new_users = {user for user in visitors if first_seen.get(user) and start <= first_seen[user].date() <= today}

    searches = [event for event in period_events if event.get("type") == "search_submit"]
    search_results = [event for event in period_events if event.get("type") == "search_result"]
    failed_searches = [event for event in search_results if not event.get("success")]
    details = [event for event in period_events if event.get("type") == "stock_detail_view"]
    video_clicks = [event for event in period_events if event.get("type") == "video_click"]
    video_clicks_by_target = defaultdict(list)
    for event in video_clicks:
        video_clicks_by_target[event.get("clickTarget") or "unknown"].append(event)
    session_ends = [
        event for event in period_events
        if event.get("type") == "session_end" and _safe_int(event.get("durationMs")) > 0
    ]
    average_duration = round(
        sum(_safe_int(event.get("durationMs")) for event in session_ends) / len(session_ends)
    ) if session_ends else 0

    user_queries = defaultdict(set)
    for event in searches:
        user_queries[event.get("userId")].add((event.get("stockCode") or event.get("query") or "").strip())
    distinct_search_counts = [len({item for item in items if item}) for items in user_queries.values()]
    avg_search_stocks = round(sum(distinct_search_counts) / len(distinct_search_counts), 1) if distinct_search_counts else 0

    visits_by_user = defaultdict(set)
    sessions_by_user = defaultdict(set)
    for event in period_page_views:
        visits_by_user[event.get("userId")].add(event["_date"])
        if event.get("sessionId"):
            sessions_by_user[event.get("userId")].add(event.get("sessionId"))
    repeat_users = {
        user for user in visitors
        if len(visits_by_user[user]) >= 2 or len(sessions_by_user[user]) >= 2
    }
    returning_users = repeat_users

    d7_cohort_date = today - datetime.timedelta(days=7)
    d7_retention = _retention_rate(first_seen, page_views, d7_cohort_date, 7) or 0.0

    metrics = [
        _metric("dau", "오늘 방문자", f"{len(today_visitors):,}", "오늘 1회 이상 방문", len(today_visitors)),
        _metric("new_users", "첫 방문자", f"{len(new_users):,}", f"최근 {days}일 첫 방문", len(new_users)),
        _metric("returning_users", "재방문자", f"{len(returning_users):,}", f"최근 {days}일 2회 이상 방문", len(returning_users)),
        _metric("search_rate", "검색 실행률", f"{_pct(len(searchers), len(visitors)):.1f}%", "방문 → 검색 전환", _pct(len(searchers), len(visitors)), "percent"),
        _metric("total_searches", "검색 수", f"{len(searches):,}", f"최근 {days}일 검색 요청 합계", len(searches)),
        _metric("avg_search_stocks", "평균 검색 종목", f"{avg_search_stocks:.1f}", "검색한 사람이 찾은 종목 수", avg_search_stocks),
        _metric("search_failure_rate", "검색 실패율", f"{_pct(len(failed_searches), len(search_results)):.1f}%", "결과 없음·분석 실패 포함", _pct(len(failed_searches), len(search_results)), "percent"),
        _metric("stock_detail_views", "결과 확인 수", f"{len(details):,}", "검색 결과를 확인한 횟수", len(details)),
        _metric("video_click_rate", "상세→영상 클릭률", f"{_pct(len(video_clicks), len(details)):.1f}%", "영상 클릭 / 결과 확인 수", _pct(len(video_clicks), len(details)), "percent"),
        _metric("video_click_user_rate", "상세 조회자 중 영상 클릭률", f"{_pct(len(video_users), len(detail_users)):.1f}%", "영상 클릭 사용자 / 상세 조회자", _pct(len(video_users), len(detail_users)), "percent"),
        _metric("evidence_timestamp_click_rate", "근거 타임스탬프 클릭률", f"{_pct(len(video_clicks_by_target['evidence_timestamp']), len(details)):.1f}%", "근거 타임스탬프 클릭 / 결과 확인 수", _pct(len(video_clicks_by_target["evidence_timestamp"]), len(details)), "percent"),
        _metric("source_cta_click_rate", "하단 CTA 클릭률", f"{_pct(len(video_clicks_by_target['source_cta']), len(details)):.1f}%", "하단 근거 CTA 클릭 / 결과 확인 수", _pct(len(video_clicks_by_target["source_cta"]), len(details)), "percent"),
        _metric("channel_name_click_rate", "채널명 클릭률", f"{_pct(len(video_clicks_by_target['channel_name']), len(details)):.1f}%", "채널명 클릭 / 결과 확인 수", _pct(len(video_clicks_by_target["channel_name"]), len(details)), "percent"),
        _metric("avg_session_time", "평균 세션 시간", _duration_text(average_duration), "방문 시작부터 이탈까지 평균", average_duration, "duration"),
        _metric("d7_retention", "7일 뒤 재방문율", f"{d7_retention:.1f}%", "첫 방문 7일 후 재방문", d7_retention, "percent"),
        _metric("return_rate", "재방문율", f"{_pct(len(repeat_users), len(visitors)):.1f}%", f"최근 {days}일 2회 이상 방문", _pct(len(repeat_users), len(visitors)), "percent"),
    ]

    return {
        "source": "actual",
        "sourceLabel": "운영 데이터",
        "generatedAt": now.isoformat(),
        "hasData": bool(events),
        "eventCount": len(events),
        "collection": {
            "firstEventAt": first_event_at.isoformat() if first_event_at else None,
        },
        "period": {
            "days": days,
            "start": start.isoformat(),
            "end": today.isoformat(),
        },
        "metrics": metrics,
        "funnel": {
            "visitors": len(visitors),
            "searchUsers": len(searchers),
            "detailUsers": len(detail_users),
            "videoClickUsers": len(video_users),
            "searchRate": _pct(len(searchers), len(visitors)),
            "detailRate": _pct(len(detail_users), len(visitors)),
            "videoClickRate": _pct(len(video_users), len(visitors)),
        },
        "videoClickTargets": {
            "channelName": len(video_clicks_by_target["channel_name"]),
            "evidenceTimestamp": len(video_clicks_by_target["evidence_timestamp"]),
            "sourceCta": len(video_clicks_by_target["source_cta"]),
            "unknown": len(video_clicks_by_target["unknown"]),
        },
        "searchTerms": _search_terms(searches, search_results),
        "trend": _daily_search_rates(period_events, day_keys),
        "cohorts": _retention_cohorts(first_seen, page_views, today),
    }
