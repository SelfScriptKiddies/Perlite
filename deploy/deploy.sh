#!/usr/bin/env bash
set -euo pipefail

# CONFIG
REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
BRANCH="main"
# Path to normalizer – from root repo
NORMALIZER="-m normalizer normalize"
VAULT_PATH="$REPO_DIR/storage"
LOG="$REPO_DIR/deploy/deploy.log"

# lock: only one deploy at a time
exec 9>"$REPO_DIR/deploy/deploy.lock"
flock 9

{
  echo "=== $(date -Is) deploy start ==="
  cd "$VAULT_PATH"
  git fetch origin
  git reset --hard "origin/${BRANCH}"
  git clean -fdx

  cd "$REPO_DIR"
  python3 -m normalizer normalize "$VAULT_PATH"

  echo "deploy ok"
  echo
} >>"$LOG" 2>&1
