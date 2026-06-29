"""Supabase Storage 기반 영속 캐시.

Render의 로컬 파일은 재배포/재시작 때 사라질 수 있으므로, 자막과 검색 인덱스는
가능하면 Supabase Storage에도 저장해 로컬/배포 환경이 같은 캐시를 공유한다.
"""
import json
import mimetypes
from pathlib import Path
from urllib.parse import quote

import requests

import config


def enabled():
    return bool(
        config.SUPABASE_CACHE_ENABLED
        and config.SUPABASE_URL
        and config.SUPABASE_SERVICE_ROLE_KEY
        and config.SUPABASE_STORAGE_BUCKET
    )


def _headers(content_type=None):
    headers = {
        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _object_url(remote_path):
    base = config.SUPABASE_URL.rstrip("/")
    bucket = quote(config.SUPABASE_STORAGE_BUCKET, safe="")
    path = "/".join(quote(part, safe="") for part in str(remote_path).split("/"))
    return f"{base}/storage/v1/object/{bucket}/{path}"


def download_bytes(remote_path):
    if not enabled():
        return None
    try:
        response = requests.get(_object_url(remote_path), headers=_headers(), timeout=30)
    except requests.RequestException as exc:
        print(f"  ⚠️ Supabase 캐시 다운로드 실패({remote_path}): {str(exc)[:120]}")
        return None
    if response.status_code == 404 or (response.status_code == 400 and "not_found" in response.text):
        return None
    if not response.ok:
        print(f"  ⚠️ Supabase 캐시 다운로드 실패({remote_path}): {response.status_code} {response.text[:120]}")
        return None
    return response.content


def download_json(remote_path):
    body = download_bytes(remote_path)
    if body is None:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        print(f"  ⚠️ Supabase 캐시 JSON 파싱 실패({remote_path}): {str(exc)[:120]}")
        return None


def download_to_file(remote_path, local_path, overwrite=False):
    local_path = Path(local_path)
    if local_path.exists() and not overwrite:
        return True
    body = download_bytes(remote_path)
    if body is None:
        return False
    local_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = local_path.with_suffix(local_path.suffix + ".tmp")
    tmp.write_bytes(body)
    tmp.replace(local_path)
    return True


def upload_bytes(remote_path, body, content_type="application/octet-stream"):
    if not enabled():
        return False
    headers = _headers(content_type)
    headers["x-upsert"] = "true"
    try:
        response = requests.post(_object_url(remote_path), headers=headers, data=body, timeout=60)
    except requests.RequestException as exc:
        print(f"  ⚠️ Supabase 캐시 업로드 실패({remote_path}): {str(exc)[:120]}")
        return False
    if not response.ok:
        print(f"  ⚠️ Supabase 캐시 업로드 실패({remote_path}): {response.status_code} {response.text[:120]}")
        return False
    return True


def upload_json(remote_path, payload):
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return upload_bytes(remote_path, body, "application/json; charset=utf-8")


def upload_file(remote_path, local_path):
    local_path = Path(local_path)
    if not local_path.exists() or not local_path.is_file():
        return False
    content_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
    return upload_bytes(remote_path, local_path.read_bytes(), content_type)
