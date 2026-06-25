"""YouTube 데이터 수집: 오늘 업로드 메타 + 자막."""
import datetime
import json
import time
from zoneinfo import ZoneInfo

import requests
from youtube_transcript_api import YouTubeTranscriptApi

import config

API = "https://www.googleapis.com/youtube/v3"
KST = ZoneInfo("Asia/Seoul")


class YouTubeAPIError(RuntimeError):
    def __init__(self, endpoint, status_code, reason=""):
        self.endpoint = endpoint
        self.status_code = status_code
        self.reason = reason
        message = f"YouTube API {endpoint} 오류 {status_code}"
        if reason:
            message += f": {reason}"
        super().__init__(message)


def _get(endpoint, **params):
    params["key"] = config.YOUTUBE_API_KEY
    r = requests.get(f"{API}/{endpoint}", params=params, timeout=20)
    if not r.ok:
        try:
            error = r.json().get("error", {})
            reason = error.get("message", "")
        except ValueError:
            reason = r.text[:120]
        # requests의 기본 예외에는 API 키가 포함된 전체 URL이 노출되므로 직접 정리한다.
        raise YouTubeAPIError(endpoint, r.status_code, reason)
    return r.json()


def _uploads_playlist(channel_id):
    # YouTube 채널의 업로드 재생목록은 UC 접두사를 UU로 바꾼 값이다.
    # 매 실행마다 channels.list를 호출하지 않아도 되어 채널당 1쿼터를 절약한다.
    if channel_id and channel_id.startswith("UC"):
        return "UU" + channel_id[2:]
    data = _get("channels", part="contentDetails", id=channel_id)
    items = data.get("items", [])
    if not items:
        return None
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def recent_uploads(channel, lookback_days=None, max_results=15):
    """채널이 최근 LOOKBACK_DAYS 일 안에 올린 영상들의 메타 리스트를 반환.

    각 항목: {channel, videoId, title, publishedAt, views, durationSec, url}
    """
    if not channel.get("channelId"):
        return []
    playlist = _uploads_playlist(channel["channelId"])
    if not playlist:
        return []

    days = config.LOOKBACK_DAYS if lookback_days is None else lookback_days
    since = datetime.datetime.now(KST).date() - datetime.timedelta(days=days - 1)
    recent = _get("playlistItems", part="contentDetails,snippet",
                  playlistId=playlist, maxResults=max_results)

    vids = []
    for it in recent.get("items", []):
        published = it["contentDetails"].get("videoPublishedAt")
        if not published:
            continue
        dt = datetime.datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(KST)
        if dt.date() < since:
            continue
        vids.append({"channel": channel["name"],
                     "videoId": it["contentDetails"]["videoId"],
                     "title": it["snippet"]["title"],
                     "publishedAt": dt})

    if not vids:
        return []

    # 통계(조회수)·길이 보강
    stats = _get("videos", part="statistics,contentDetails",
                 id=",".join(v["videoId"] for v in vids))
    by_id = {x["id"]: x for x in stats.get("items", [])}
    out = []
    for v in vids:
        s = by_id.get(v["videoId"], {})
        v["views"] = int(s.get("statistics", {}).get("viewCount", 0))
        v["durationSec"] = _iso_duration(s.get("contentDetails", {}).get("duration", "PT0S"))
        v["url"] = f"https://www.youtube.com/watch?v={v['videoId']}"
        out.append(v)
    return out


LAST_TRANSCRIPT_ERROR = None
LAST_TRANSCRIPT_SOURCE = None
LAST_TRANSCRIPT_FROM_CACHE = False
_LAST_UPSTREAM_REQUEST_AT = 0.0


def _cache_path(video_id):
    return config.TRANSCRIPT_CACHE_DIR / f"{video_id}.json"


def _read_cache(video_id):
    path = _cache_path(video_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_cache(video_id, payload):
    config.TRANSCRIPT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(video_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _cached_transcript(video_id):
    cached = _read_cache(video_id)
    if not cached:
        return False, None
    if cached.get("status") == "ok" and cached.get("text"):
        return True, cached["text"]
    if cached.get("status") != "failed":
        return False, None
    try:
        failed_at = datetime.datetime.fromisoformat(cached["fetchedAt"])
        age = datetime.datetime.now(datetime.timezone.utc) - failed_at
    except (KeyError, ValueError, TypeError):
        return False, None
    ttl = datetime.timedelta(hours=config.TRANSCRIPT_FAILURE_TTL_HOURS)
    return (True, None) if age < ttl else (False, None)


def _manual_transcript(video_id):
    """권한을 확보해 직접 만든 자막을 넣는 위치. 네트워크 요청 없이 우선 사용."""
    for suffix in (".txt", ".vtt", ".srt"):
        path = config.MANUAL_TRANSCRIPT_DIR / f"{video_id}{suffix}"
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    return None


def _pace_upstream():
    """비공식 자막 경로를 과도하게 호출하지 않도록 영상 간격을 둔다."""
    global _LAST_UPSTREAM_REQUEST_AT
    delay = max(0.0, config.TRANSCRIPT_REQUEST_DELAY_SECONDS)
    elapsed = time.monotonic() - _LAST_UPSTREAM_REQUEST_AT
    if elapsed < delay:
        time.sleep(delay - elapsed)
    _LAST_UPSTREAM_REQUEST_AT = time.monotonic()


def _supadata_transcript(video_id):
    """Supadata API로 자막 가져오기 (차단 우회 + 자막 없으면 AI 받아쓰기)."""
    global LAST_TRANSCRIPT_ERROR
    try:
        r = requests.get("https://api.supadata.ai/v1/transcript",
                         params={"url": f"https://www.youtube.com/watch?v={video_id}"},
                         headers={"x-api-key": config.SUPADATA_API_KEY}, timeout=90)
        if r.status_code != 200:
            LAST_TRANSCRIPT_ERROR = f"Supadata {r.status_code}: {r.text[:140]}"
            return None
        content = r.json().get("content")
        if isinstance(content, list):
            return " ".join(seg.get("text", "") for seg in content).strip() or None
        if isinstance(content, str):
            return content.strip() or None
        LAST_TRANSCRIPT_ERROR = "Supadata: 예상치 못한 응답 형식"
        return None
    except Exception as e:
        LAST_TRANSCRIPT_ERROR = f"Supadata 오류: {str(e)[:140]}"
        return None


def _free_transcript(video_id):
    """무료 youtube-transcript-api (0.x/1.x). 차단되면 실패."""
    global LAST_TRANSCRIPT_ERROR
    try:
        try:
            fetched = YouTubeTranscriptApi().fetch(video_id, languages=config.TRANSCRIPT_LANGS)
            return " ".join(s.text for s in fetched)
        except AttributeError:
            data = YouTubeTranscriptApi.get_transcript(video_id, languages=config.TRANSCRIPT_LANGS)
            return " ".join(x["text"] for x in data)
    except Exception as e:
        LAST_TRANSCRIPT_ERROR = f"{type(e).__name__}: {str(e)[:140]}"
        return None


# ── Defuddle 방식: 유튜브 내부 API(InnerTube)를 모바일 앱 클라이언트로 호출 (무료·차단에 강함) ──
_INNERTUBE_URL = "https://www.youtube.com/youtubei/v1/player?prettyPrint=false"
_IOS_CTX = {"client": {"clientName": "IOS", "clientVersion": "20.10.3"}}
_ANDROID_CTX = {"client": {"clientName": "ANDROID", "clientVersion": "20.10.38"}}
_ANDROID_UA = "com.google.android.youtube/20.10.38 (Linux; U; Android 14)"


def _innertube_caption_tracks(video_id):
    for ctx, ua in [(_IOS_CTX, None), (_ANDROID_CTX, _ANDROID_UA)]:
        try:
            headers = {"Content-Type": "application/json"}
            if ua:
                headers["User-Agent"] = ua
            r = requests.post(_INNERTUBE_URL, headers=headers, timeout=15,
                              json={"context": ctx, "videoId": video_id})
            if r.status_code != 200:
                continue
            tracks = (r.json().get("captions", {})
                      .get("playerCaptionsTracklistRenderer", {})
                      .get("captionTracks"))
            if tracks:
                return tracks
        except Exception:
            continue
    return None


def _pick_caption_track(tracks):
    def best(pred):
        m = [t for t in tracks if pred(t)]
        if not m:
            return None
        return next((t for t in m if t.get("kind") != "asr"), m[0])
    for lang in config.TRANSCRIPT_LANGS:
        t = best(lambda t, lg=lang: t.get("languageCode", "").lower().startswith(lg.lower()))
        if t:
            return t
    return best(lambda t: True)


def _parse_caption_xml(xml):
    import re
    import html
    parts = []
    for m in re.finditer(r"<p[^>]*>([\s\S]*?)</p>", xml):       # srv3: <p t=..><s>..</s></p>
        inner = m.group(1)
        ss = re.findall(r"<s[^>]*>([^<]*)</s>", inner)
        text = "".join(ss) if ss else re.sub(r"<[^>]+>", "", inner)
        text = html.unescape(text).replace("\n", " ").strip()
        if text:
            parts.append(text)
    if not parts:
        for m in re.finditer(r"<text[^>]*>([\s\S]*?)</text>", xml):  # 기본: <text start=..>..</text>
            text = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).replace("\n", " ").strip()
            if text:
                parts.append(text)
    return " ".join(parts).strip()


def _innertube_transcript(video_id):
    global LAST_TRANSCRIPT_ERROR
    try:
        tracks = _innertube_caption_tracks(video_id)
        if not tracks:
            LAST_TRANSCRIPT_ERROR = "InnerTube: 자막 트랙을 못 찾음"
            return None
        track = _pick_caption_track(tracks)
        url = (track or {}).get("baseUrl")
        if not url:
            return None
        xml = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15).text
        return _parse_caption_xml(xml) or None
    except Exception as e:
        LAST_TRANSCRIPT_ERROR = f"InnerTube 오류: {str(e)[:140]}"
        return None


def fetch_transcript(video_id, force=False):
    """영상 ID별 자막을 한 번만 수집한다.

    순서: 성공 캐시 → 수동 자막 → InnerTube → Supadata → 무료 라이브러리.
    성공 자막은 영구 캐시하고, 실패는 일정 시간 캐시해 반복 요청을 막는다.
    """
    global LAST_TRANSCRIPT_ERROR, LAST_TRANSCRIPT_SOURCE, LAST_TRANSCRIPT_FROM_CACHE
    LAST_TRANSCRIPT_ERROR = None
    LAST_TRANSCRIPT_SOURCE = None
    LAST_TRANSCRIPT_FROM_CACHE = False

    if not force and not config.FORCE_TRANSCRIPT_REFRESH:
        hit, text = _cached_transcript(video_id)
        if hit:
            cached = _read_cache(video_id) or {}
            LAST_TRANSCRIPT_SOURCE = cached.get("source", "cache")
            LAST_TRANSCRIPT_ERROR = cached.get("error")
            LAST_TRANSCRIPT_FROM_CACHE = True
            return text

    manual = _manual_transcript(video_id)
    if manual:
        source, text = "manual", manual
    else:
        source, text = None, None
        attempts = [("innertube", _innertube_transcript)]
        if config.SUPADATA_API_KEY:
            attempts.append(("supadata", _supadata_transcript))
        attempts.append(("youtube-transcript-api", _free_transcript))
        errors = []
        for candidate, loader in attempts:
            _pace_upstream()
            text = loader(video_id)
            if text:
                source = candidate
                break
            if LAST_TRANSCRIPT_ERROR:
                errors.append(f"{candidate}: {LAST_TRANSCRIPT_ERROR}")

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if text:
        _write_cache(video_id, {
            "status": "ok", "source": source, "fetchedAt": now, "text": text,
        })
        LAST_TRANSCRIPT_SOURCE = source
        LAST_TRANSCRIPT_ERROR = None
        return text

    error = " | ".join(errors) if "errors" in locals() and errors else (LAST_TRANSCRIPT_ERROR or "자막 없음")
    _write_cache(video_id, {
        "status": "failed", "source": "all", "fetchedAt": now, "error": error,
    })
    LAST_TRANSCRIPT_ERROR = error
    return None


def _iso_duration(iso):
    """PT1H2M3S -> 초."""
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s
