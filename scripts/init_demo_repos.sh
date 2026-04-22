#!/usr/bin/env bash
# Initialize the GitHub demo repos with the broken-baseline state.
#
# For each demo fixture: run its `stage.sh` to materialize `/tmp/<fixture>-demo`
# with a git repo pointing at the configured remote, then force-push `main` to
# overwrite whatever's there (including closing prior PRs on next run via
# reset.sh).
#
# Idempotent — safe to run multiple times. Reads credentials from .env.
set -euo pipefail

cd "$(dirname "$(dirname "${BASH_SOURCE[0]}")")"    # repo root

# ── Load .env ────────────────────────────────────────────────────────────────
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

for required in GITHUB_TOKEN GITHUB_BOT_OWNER; do
  if [[ -z "${!required:-}" ]]; then
    echo "FAIL: $required not set in .env" >&2
    exit 1
  fi
done

primary_repo="${GITHUB_BOT_REPO:-}"
backup_repo="${GITHUB_BOT_REPO_ISIC:-${GITHUB_BOT_REPO:-}}"

_push_fixture() {
  local fixture_dir="$1"
  local repo_name="$2"
  local target_dir="$3"

  if [[ -z "$repo_name" ]]; then
    echo "skip: no repo configured for $fixture_dir" >&2
    return
  fi

  echo "── Initializing $fixture_dir → $GITHUB_BOT_OWNER/$repo_name ──"

  REPRO_DEMO_TARGET="$target_dir" GITHUB_BOT_OWNER="$GITHUB_BOT_OWNER" \
    GITHUB_BOT_REPO="$repo_name" GITHUB_BOT_REPO_ISIC="$repo_name" \
    "$fixture_dir/stage.sh" > /dev/null

  (
    cd "$target_dir"
    # Swap origin URL to the token-embedded form for this push only.
    git remote set-url origin "https://${GITHUB_TOKEN}@github.com/${GITHUB_BOT_OWNER}/${repo_name}.git"
    if ! git push --force origin main; then
      echo "FAIL: git push to $GITHUB_BOT_OWNER/$repo_name failed" >&2
      return 1
    fi
    # Scrub the token back out so the local repo's .git/config doesn't keep it.
    git remote set-url origin "https://github.com/${GITHUB_BOT_OWNER}/${repo_name}.git"
  )

  echo "   pushed main to $GITHUB_BOT_OWNER/$repo_name"
}

_push_fixture demo/primary "$primary_repo" "/tmp/muchlinski-demo"
_push_fixture demo/backup  "$backup_repo"  "/tmp/isic-demo"

echo "all demo repos initialized."
