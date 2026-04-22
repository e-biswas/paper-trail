#!/usr/bin/env bash
# Stage the ISIC backup demo into /tmp/isic-demo and init a git repo.
# Idempotent: wipes and recreates the target on every invocation.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${REPRO_DEMO_TARGET:-/tmp/isic-demo}"
BOT_OWNER="${GITHUB_BOT_OWNER:-}"
BOT_REPO="${GITHUB_BOT_REPO_ISIC:-${GITHUB_BOT_REPO:-}}"

echo "Staging ISIC backup fixture -> $TARGET"

rm -rf "$TARGET"
mkdir -p "$TARGET"
cp -r "$SRC_DIR/src" "$TARGET/"
cp -r "$SRC_DIR/data" "$TARGET/"
cp "$SRC_DIR/requirements.txt" "$TARGET/"
cp "$SRC_DIR/README.md" "$TARGET/"

cd "$TARGET"
git init -q -b main
git add -A
git -c user.email=bot@paper-trail.local \
    -c user.name='Paper Trail Bot' \
    commit -q -m "Initial broken state (ISIC 2020 melanoma reproduction)"

if [[ -n "$BOT_OWNER" && -n "$BOT_REPO" ]]; then
  git remote remove origin 2>/dev/null || true
  git remote add origin "https://github.com/${BOT_OWNER}/${BOT_REPO}.git"
  echo "Remote 'origin' set to github.com/${BOT_OWNER}/${BOT_REPO}"
else
  echo "NOTE: GITHUB_BOT_OWNER / GITHUB_BOT_REPO unset; skipping remote setup." >&2
fi

echo "$TARGET"
