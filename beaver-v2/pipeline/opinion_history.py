"""유튜버 종목 의견 히스토리 저장/조회.

검색/화면 연결부와 충돌을 줄이기 위해 P1 영속 저장 계약을 이 모듈에 모은다.
기본 저장소는 로컬 SQLite이며, 배포 환경에서는 Supabase REST upsert로 전환할 수 있다.
"""
import datetime
import hashlib
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlencode

import config

KST = datetime.timezone(datetime.timedelta(hours=9))
DEFAULT_PERIOD_DAYS = int(os.environ.get("OPINION_HISTORY_PERIOD_DAYS", "180"))
DEFAULT_TABLE = os.environ.get("SUPABASE_OPINION_HISTORY_TABLE", "youtuber_opinions")

SUPABASE_SCHEMA_SQL = """
create table if not exists public.youtuber_opinions (
  id text primary key,
  stock_name text not null,
  stock_code text not null default '',
  stock_key text not null,
  market text not null default '',
  channel_id text not null default '',
  channel_name text not null,
  channel_key text not null,
  video_id text not null,
  video_url text not null default '',
  video_title text not null default '',
  published_at timestamptz not null,
  analyzed_at timestamptz not null,
  stance text not null,
  summary text not null default '',
  evidence text not null default '',
  source_time_sec integer,
  views integer not null default 0,
  analysis_provider text not null default '',
  analysis_version text not null default '',
  context_hash text not null,
  unique (stock_key, channel_key, video_id, context_hash)
);

create index if not exists idx_youtuber_opinions_history
  on public.youtuber_opinions (stock_key, channel_key, published_at desc);
"""


def compact(text):
    return re.sub(r"[^0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ]", "", str(text or "")).lower()


def backend():
    return os.environ.get("OPINION_HISTORY_BACKEND", "sqlite").strip().lower()


def sqlite_path():
    configured = os.environ.get("OPINION_HISTORY_SQLITE_PATH", "").strip()
    if configured:
        return Path(configured)
    return config.CACHE_DIR / "opinion_history.sqlite3"


def stock_key(stock_name="", stock_code=""):
    code = str(stock_code or "").strip().upper()
    return code or compact(stock_name)


def channel_key(channel_id="", channel_name=""):
    channel_id = str(channel_id or "").strip()
    return channel_id or compact(channel_name)


def _now_iso():
    return datetime.datetime.now(KST).isoformat()


def _iso(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value or "")


def _record_id(record):
    basis = "|".join([
        record["stock_key"],
        record["channel_key"],
        record["video_id"],
        record["context_hash"],
    ])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def opinion_record(
        stock_name,
        video,
        result,
        context_hash,
        analysis_provider="",
        analysis_version="",
        stock_code="",
        market="",
        analyzed_at=None):
    """검색 결과에서 히스토리 저장 레코드를 만든다."""
    if not result or not result.get("mentioned"):
        return None
    stock_name = str(stock_name or "").strip()
    video = video or {}
    result = result or {}
    record = {
        "stock_name": stock_name,
        "stock_code": str(stock_code or "").strip(),
        "stock_key": stock_key(stock_name, stock_code),
        "market": str(market or "").strip(),
        "channel_id": str(video.get("channelId") or "").strip(),
        "channel_name": str(video.get("channel") or "").strip(),
        "video_id": str(video.get("videoId") or "").strip(),
        "video_url": str(video.get("url") or ""),
        "video_title": str(video.get("title") or ""),
        "published_at": _iso(video.get("publishedAt")),
        "analyzed_at": _iso(analyzed_at) if analyzed_at else _now_iso(),
        "stance": str(result.get("stance") or "단순언급"),
        "summary": str(result.get("summary") or ""),
        "evidence": str(result.get("evidence") or ""),
        "source_time_sec": result.get("sourceTimeSec"),
        "views": int(video.get("views") or 0),
        "analysis_provider": str(analysis_provider or ""),
        "analysis_version": str(analysis_version or ""),
        "context_hash": str(context_hash or "").strip(),
    }
    record["channel_key"] = channel_key(record["channel_id"], record["channel_name"])
    if not record["stock_key"] or not record["channel_key"] or not record["video_id"] or not record["context_hash"]:
        return None
    record["id"] = _record_id(record)
    return record


def ensure_sqlite_schema(db_path=None):
    path = Path(db_path or sqlite_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS youtuber_opinions (
                id TEXT PRIMARY KEY,
                stock_name TEXT NOT NULL,
                stock_code TEXT NOT NULL DEFAULT '',
                stock_key TEXT NOT NULL,
                market TEXT NOT NULL DEFAULT '',
                channel_id TEXT NOT NULL DEFAULT '',
                channel_name TEXT NOT NULL,
                channel_key TEXT NOT NULL,
                video_id TEXT NOT NULL,
                video_url TEXT NOT NULL DEFAULT '',
                video_title TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL,
                analyzed_at TEXT NOT NULL,
                stance TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                evidence TEXT NOT NULL DEFAULT '',
                source_time_sec INTEGER,
                views INTEGER NOT NULL DEFAULT 0,
                analysis_provider TEXT NOT NULL DEFAULT '',
                analysis_version TEXT NOT NULL DEFAULT '',
                context_hash TEXT NOT NULL,
                UNIQUE(stock_key, channel_key, video_id, context_hash)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_youtuber_opinions_history
            ON youtuber_opinions(stock_key, channel_key, published_at DESC)
        """)
    return path


def _save_sqlite(record, db_path=None):
    path = ensure_sqlite_schema(db_path)
    columns = [
        "id", "stock_name", "stock_code", "stock_key", "market",
        "channel_id", "channel_name", "channel_key",
        "video_id", "video_url", "video_title", "published_at", "analyzed_at",
        "stance", "summary", "evidence", "source_time_sec", "views",
        "analysis_provider", "analysis_version", "context_hash",
    ]
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(
        f"{column}=excluded.{column}"
        for column in columns
        if column not in {"id", "stock_key", "channel_key", "video_id", "context_hash"}
    )
    with sqlite3.connect(path) as conn:
        conn.execute(
            f"""
            INSERT INTO youtuber_opinions ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(stock_key, channel_key, video_id, context_hash)
            DO UPDATE SET {updates}
            """,
            [record.get(column) for column in columns],
        )
    return True


def _supabase_headers(content_type="application/json"):
    return {
        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": content_type,
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }


def _supabase_url(path, query=None):
    base = config.SUPABASE_URL.rstrip("/")
    suffix = f"/rest/v1/{path}"
    if query:
        suffix += "?" + query
    return base + suffix


def _save_supabase(record):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_ROLE_KEY:
        return False
    import requests

    query = "on_conflict=stock_key,channel_key,video_id,context_hash"
    response = requests.post(
        _supabase_url(DEFAULT_TABLE, query),
        headers=_supabase_headers(),
        json=record,
        timeout=20,
    )
    return response.status_code in (200, 201, 204)


def save_opinion(record, db_path=None, store=None, strict=False):
    """의견 레코드를 중복 없이 저장한다. 실패는 기본적으로 검색 흐름을 막지 않는다."""
    if not record:
        return False
    store = (store or backend()).lower()
    try:
        if store == "off":
            return False
        if store == "supabase":
            return _save_supabase(record)
        return _save_sqlite(record, db_path)
    except Exception:
        if strict:
            raise
        return False


def _cutoff_iso(period_days):
    period_days = DEFAULT_PERIOD_DAYS if period_days is None else int(period_days)
    return (datetime.datetime.now(KST) - datetime.timedelta(days=period_days)).isoformat()


def _query_sqlite(stock_name="", stock_code="", channel_id="", channel_name="", period_days=None, db_path=None, ascending=False):
    path = ensure_sqlite_schema(db_path)
    order = "ASC" if ascending else "DESC"
    skey = stock_key(stock_name, stock_code)
    ckey = channel_key(channel_id, channel_name)
    stock_name = str(stock_name or "").strip()
    channel_name = str(channel_name or "").strip()
    values = [
        skey,
        skey,
        stock_name,
        stock_name,
        ckey,
        ckey,
        channel_name,
        channel_name,
        _cutoff_iso(period_days),
    ]
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT *
            FROM youtuber_opinions
            WHERE (
                (? != '' AND stock_key = ?)
                OR (? != '' AND stock_name = ?)
              )
              AND (
                (? != '' AND channel_key = ?)
                OR (? != '' AND channel_name = ?)
              )
              AND published_at >= ?
            ORDER BY published_at {order}
            """,
            values,
        ).fetchall()
    return [dict(row) for row in rows]


def _query_supabase(stock_name="", stock_code="", channel_id="", channel_name="", period_days=None, ascending=False):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_ROLE_KEY:
        return []
    import requests

    skey = stock_key(stock_name, stock_code)
    ckey = channel_key(channel_id, channel_name)
    params = {
        "select": "*",
        "channel_key": f"eq.{ckey}",
        "published_at": f"gte.{_cutoff_iso(period_days)}",
        "order": f"published_at.{('asc' if ascending else 'desc')}",
    }
    response = requests.get(
        _supabase_url(DEFAULT_TABLE, urlencode(params, safe=".*,()")),
        headers=_supabase_headers(),
        timeout=20,
    )
    if not response.ok:
        return []
    stock_name = str(stock_name or "").strip()
    return [
        row for row in response.json()
        if (skey and row.get("stock_key") == skey) or (stock_name and row.get("stock_name") == stock_name)
    ]


def _history_rows(stock_name="", stock_code="", channel_id="", channel_name="", period_days=None, db_path=None, store=None, ascending=False):
    store = (store or backend()).lower()
    if store == "supabase":
        return _query_supabase(stock_name, stock_code, channel_id, channel_name, period_days, ascending)
    return _query_sqlite(stock_name, stock_code, channel_id, channel_name, period_days, db_path, ascending)


def _trend_label(stances):
    if not stances:
        return ""
    if len(stances) == 1:
        return "첫 기록이에요"
    latest = stances[-1]
    previous = next((stance for stance in reversed(stances[:-1]) if stance != latest), None)
    if previous:
        return f"{previous}에서 {latest}으로 변화"
    return f"{latest} 유지"


def history_summary(stock_name="", stock_code="", channel_id="", channel_name="", period_days=None, db_path=None, store=None):
    period_days = DEFAULT_PERIOD_DAYS if period_days is None else int(period_days)
    rows = _history_rows(
        stock_name=stock_name,
        stock_code=stock_code,
        channel_id=channel_id,
        channel_name=channel_name,
        period_days=period_days,
        db_path=db_path,
        store=store,
        ascending=True,
    )
    stances = [row.get("stance", "") for row in rows if row.get("stance")]
    return {
        "sameStockOpinionCount": len(rows),
        "periodDays": period_days,
        "latestTrend": _trend_label(stances),
        "stances": stances,
    }


def history_detail(stock_name="", stock_code="", channel_id="", channel_name="", period_days=None, db_path=None, store=None):
    period_days = DEFAULT_PERIOD_DAYS if period_days is None else int(period_days)
    rows = _history_rows(
        stock_name=stock_name,
        stock_code=stock_code,
        channel_id=channel_id,
        channel_name=channel_name,
        period_days=period_days,
        db_path=db_path,
        store=store,
        ascending=False,
    )
    opinions = [{
        "publishedAt": row.get("published_at", ""),
        "stance": row.get("stance", ""),
        "summary": row.get("summary", ""),
        "url": row.get("video_url", ""),
        "videoTitle": row.get("video_title", ""),
        "evidence": row.get("evidence", ""),
        "sourceTimeSec": row.get("source_time_sec"),
        "views": row.get("views", 0),
    } for row in rows]
    channel = rows[0] if rows else {}
    return {
        "stock": stock_name,
        "stockCode": stock_code,
        "channelId": channel_id or channel.get("channel_id", ""),
        "channelName": channel_name or channel.get("channel_name", ""),
        "periodDays": period_days,
        "opinions": opinions,
    }
