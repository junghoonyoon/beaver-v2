#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="${EXE_REPO_DIR:-$HOME/beaver-v2}"
BRANCH="${EXE_DEPLOY_BRANCH:-main}"
APP_DIR="$REPO_DIR/beaver-v2/pipeline"
BACKUP_ROOT="${EXE_DEPLOY_BACKUP_DIR:-$HOME/stockzip-deploy-backups}"
PID_FILE="${EXE_DEPLOY_PID_FILE:-$HOME/stockzip-search-server.pid}"
LOG_FILE="${EXE_DEPLOY_LOG_FILE:-$HOME/stockzip-search-server.log}"
PORT="${PORT:-8000}"
SEARCH_HOST="${SEARCH_HOST:-0.0.0.0}"
SEARCH_PUBLIC_BASE_URL="${SEARCH_PUBLIC_BASE_URL:-https://stockzip.kr}"

cd "$REPO_DIR"
git fetch origin "$BRANCH"

if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  stamp="$(date +%Y%m%d%H%M%S)"
  backup_dir="$BACKUP_ROOT/$stamp"
  mkdir -p "$backup_dir"
  git status --short > "$backup_dir/status.txt"
  git diff > "$backup_dir/worktree.diff" || true
  git diff --cached > "$backup_dir/staged.diff" || true
  git ls-files --others --exclude-standard > "$backup_dir/untracked-files.txt"
fi

git reset --hard "origin/$BRANCH"

cd "$APP_DIR"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install -r requirements.txt

if [ -f "$PID_FILE" ]; then
  old_pid="$(cat "$PID_FILE" || true)"
  if [ -n "${old_pid:-}" ] && kill -0 "$old_pid" 2>/dev/null; then
    kill "$old_pid" || true
    sleep 2
  fi
fi

if pgrep -f "$APP_DIR/.venv/bin/python search_server.py" >/dev/null 2>&1; then
  pkill -TERM -f "$APP_DIR/.venv/bin/python search_server.py" || true
  sleep 2
fi

nohup env \
  SEARCH_HOST="$SEARCH_HOST" \
  PORT="$PORT" \
  SEARCH_PUBLIC_BASE_URL="$SEARCH_PUBLIC_BASE_URL" \
  .venv/bin/python search_server.py > "$LOG_FILE" 2>&1 &
echo "$!" > "$PID_FILE"

sleep 5
curl -fsS "http://127.0.0.1:$PORT/api/status" >/tmp/stockzip-api-status.json
echo "Deployed origin/$BRANCH to EXE.dev on port $PORT."
