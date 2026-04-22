#!/usr/bin/env bash
# Reset the Muchlinski demo to its broken baseline.
# Deletes the local working dir and force-pushes main on the bot fork.
set -euo pipefail

TARGET="${REPRO_DEMO_TARGET:-/tmp/muchlinski-demo}"
BOT_OWNER="${GITHUB_BOT_OWNER:-}"
BOT_REPO="${GITHUB_BOT_REPO:-}"

echo "Resetting Muchlinski demo."

if [[ -d "$TARGET" ]]; then
  (
    cd "$TARGET"
    if [[ -n "$BOT_OWNER" && -n "$BOT_REPO" ]]; then
      # Close any open PRs the agent may have opened
      if command -v gh >/dev/null 2>&1; then
        gh pr list --repo "${BOT_OWNER}/${BOT_REPO}" --state open --json number -q '.[].number' \
          | xargs -I {} gh pr close --repo "${BOT_OWNER}/${BOT_REPO}" {} 2>/dev/null || true
      fi
      git push --force origin main 2>/dev/null || true
    fi
  )
fi

rm -rf "$TARGET"

# Re-run stage.sh to recreate baseline
"$(dirname "${BASH_SOURCE[0]}")/stage.sh"
