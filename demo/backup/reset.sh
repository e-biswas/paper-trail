#!/usr/bin/env bash
# Reset the ISIC demo to its broken baseline.
set -euo pipefail

TARGET="${REPRO_DEMO_TARGET:-/tmp/isic-demo}"
BOT_OWNER="${GITHUB_BOT_OWNER:-}"
BOT_REPO="${GITHUB_BOT_REPO_ISIC:-${GITHUB_BOT_REPO:-}}"

echo "Resetting ISIC demo."

if [[ -d "$TARGET" ]]; then
  (
    cd "$TARGET"
    if [[ -n "$BOT_OWNER" && -n "$BOT_REPO" ]]; then
      if command -v gh >/dev/null 2>&1; then
        gh pr list --repo "${BOT_OWNER}/${BOT_REPO}" --state open --json number -q '.[].number' \
          | xargs -I {} gh pr close --repo "${BOT_OWNER}/${BOT_REPO}" {} 2>/dev/null || true
      fi
      git push --force origin main 2>/dev/null || true
    fi
  )
fi

rm -rf "$TARGET"
"$(dirname "${BASH_SOURCE[0]}")/stage.sh"
