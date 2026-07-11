#!/usr/bin/env bash
# Sync python/ from the pi-mono monorepo into this standalone repo.
set -euo pipefail

MONOREPO_ROOT="${MONOREPO_ROOT:-$(cd "$(dirname "$0")/../../pi-mono" && pwd)}"
PY_REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -d "$MONOREPO_ROOT/python/src" ]]; then
  echo "Monorepo python tree not found at: $MONOREPO_ROOT/python" >&2
  exit 1
fi

rsync -av \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.mypy_cache' \
  --exclude '.ruff_cache' \
  --exclude '*.html' \
  --exclude 'import.jsonl' \
  --exclude '.git' \
  --exclude 'pi_mono_python.egg-info' \
  "$MONOREPO_ROOT/python/" \
  "$PY_REPO_ROOT/"

echo "Synced from $MONOREPO_ROOT/python -> $PY_REPO_ROOT"
echo "Review changes, then: git add -A && git commit && git push"
