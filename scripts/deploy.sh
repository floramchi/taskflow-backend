#!/usr/bin/env bash
# Deploys TaskFlow to a Linux VM that has Docker (with the compose plugin), rsync and SSH access.
# Usage: scripts/deploy.sh user@host [remote_dir]
#
# The remote directory must contain a .env file with at least JWT_SECRET. It is
# never overwritten by this script, so secrets stay on the server.
set -euo pipefail

HOST="${1:?usage: scripts/deploy.sh user@host [remote_dir]}"
REMOTE_DIR="${2:-/opt/taskflow}"

ssh "$HOST" "mkdir -p '$REMOTE_DIR'"

rsync -az --delete \
  --exclude .git --exclude .venv --exclude .env \
  --exclude __pycache__ --exclude .pytest_cache --exclude .ruff_cache \
  ./ "$HOST:$REMOTE_DIR/"

ssh "$HOST" "cd '$REMOTE_DIR' \
  && test -f .env || { echo 'Missing $REMOTE_DIR/.env (set JWT_SECRET)' >&2; exit 1; }"

# The api container applies migrations on start (alembic upgrade head).
ssh "$HOST" "cd '$REMOTE_DIR' && docker compose up -d --build"

# Give the API a moment to boot, then fail the deploy if it isn't healthy.
ssh "$HOST" "for i in \$(seq 1 20); do curl -fsS localhost:8000/health && exit 0; sleep 3; done; exit 1"
