#!/usr/bin/env bash
# Paper Trail preflight — one-command sanity check before a rehearsal or
# the live demo. Fails fast if any precondition is wrong, so you find out
# now rather than 30 seconds into the run on stage.
#
# See scripts/README.md for the full check list + rationale. Usage:
#
#   ./scripts/preflight.sh          # run all checks
#   PREFLIGHT_SKIP_NETWORK=1 ./scripts/preflight.sh   # skip remote hits
#   PREFLIGHT_SKIP_STAGE=1   ./scripts/preflight.sh   # skip fixture stage probe
#
# Exit status: 0 if everything passed, 1 on the first failure.
set -uo pipefail

cd "$(dirname "$(dirname "${BASH_SOURCE[0]}")")"    # repo root

# ── Colours (no-op on non-TTY) ───────────────────────────────────────────────
if [[ -t 1 ]]; then
  GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; DIM='\033[2m'; RESET='\033[0m'
else
  GREEN=''; RED=''; YELLOW=''; DIM=''; RESET=''
fi

_fail_count=0
_warn_count=0
_pass_count=0
_start_sec=$(date +%s)

_pass() { printf "  ${GREEN}✓${RESET} %s\n" "$1"; _pass_count=$((_pass_count + 1)); }
_warn() { printf "  ${YELLOW}!${RESET} %s\n" "$1"; _warn_count=$((_warn_count + 1)); }
_fail() { printf "  ${RED}✗${RESET} %s\n" "$1"; _fail_count=$((_fail_count + 1)); return 1; }
_info() { printf "  ${DIM}·${RESET} %s\n" "$1"; }

_section() {
  printf "\n${DIM}── %s ──${RESET}\n" "$1"
}

_exit_if_failed() {
  if (( _fail_count > 0 )); then
    printf "\n${RED}FAIL${RESET} — stopping at first failure. Fix and re-run.\n" >&2
    exit 1
  fi
}

# ── 1. Env vars ──────────────────────────────────────────────────────────────
_section "env vars"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  _pass ".env loaded"
else
  _fail ".env not found — copy .env.example to .env and fill in secrets"
  _exit_if_failed
fi

_required_vars=(ANTHROPIC_API_KEY GITHUB_TOKEN GITHUB_BOT_OWNER GITHUB_BOT_REPO)
for v in "${_required_vars[@]}"; do
  if [[ -z "${!v:-}" ]]; then
    _fail "$v is not set"
  elif [[ "${!v}" == "sk-ant-..." || "${!v}" == "ghp_..." || "${!v}" == "paper-trail" && "$v" == "GITHUB_BOT_OWNER" ]]; then
    _warn "$v looks like the .env.example placeholder — update it"
  else
    _pass "$v is set"
  fi
done

# Soft-required: backup fixture repo. If unset, init_demo_repos.sh falls
# back to the primary — fine for the demo but worth calling out.
if [[ -z "${GITHUB_BOT_REPO_ISIC:-}" ]]; then
  _warn "GITHUB_BOT_REPO_ISIC unset — backup fixture will reuse GITHUB_BOT_REPO"
fi
_exit_if_failed

# ── 2. GitHub PAT scope ──────────────────────────────────────────────────────
# Paper Trail uses the GitHub MCP server (npx @modelcontextprotocol/server-github)
# for PR creation, not the `gh` CLI, so `gh` is OPTIONAL — we validate the
# token directly against api.github.com when it's missing.
_section "GitHub PAT scope"

_probe_token_scopes() {
  local hdrs
  if hdrs=$(curl --max-time 5 -sS -I \
             -H "Authorization: token ${GITHUB_TOKEN}" \
             https://api.github.com/user 2>/dev/null); then
    if grep -qi '^HTTP/.* 200' <<<"$hdrs"; then
      local scopes
      scopes=$(grep -i '^x-oauth-scopes:' <<<"$hdrs" | head -1 | tr -d '\r')
      if grep -qiE 'repo(,|$|\s)' <<<"$scopes"; then
        _pass "GitHub API reports 'repo' scope on GITHUB_TOKEN"
      elif [[ -z "$scopes" ]]; then
        # Fine-grained tokens return no x-oauth-scopes header; fall back to
        # checking whether the bot repo is reachable for write.
        _warn "no x-oauth-scopes header (likely a fine-grained token)"
      else
        _warn "GITHUB_TOKEN present but lacks classic 'repo' scope (${scopes})"
      fi
    else
      _fail "api.github.com rejected GITHUB_TOKEN (got: $(head -1 <<<"$hdrs"))"
    fi
  else
    if [[ -n "${PREFLIGHT_SKIP_NETWORK:-}" ]]; then
      _info "PREFLIGHT_SKIP_NETWORK set — skipping token probe"
    else
      _fail "could not reach api.github.com to validate GITHUB_TOKEN"
    fi
  fi
}

if command -v gh >/dev/null 2>&1; then
  if _scopes=$(GITHUB_TOKEN="$GITHUB_TOKEN" gh auth status 2>&1); then
    if grep -qiE 'token scopes:.*\brepo\b' <<<"$_scopes" || grep -qiE 'scopes.*\brepo\b' <<<"$_scopes"; then
      _pass "gh reports 'repo' scope on active token"
    else
      _warn "gh auth status did not explicitly list 'repo' scope; fine-grained tokens may still work"
    fi
  else
    _probe_token_scopes
  fi
else
  _info "gh CLI not installed — Paper Trail uses the GitHub MCP server, not gh"
  _probe_token_scopes
fi
_exit_if_failed

# ── 3. Ports free ────────────────────────────────────────────────────────────
_section "ports free"

_check_port() {
  local port="$1"
  if lsof -i ":$port" >/dev/null 2>&1; then
    _fail "port $port is in use"
    _info "run: lsof -i :$port"
  else
    _pass "port $port is free"
  fi
}
_check_port 8080
_check_port 5173
_exit_if_failed

# ── 4. Disk space ────────────────────────────────────────────────────────────
_section "disk space"

# macOS df reports in 1K blocks by default; -g asks for GiB, but use -Ph for portability.
if _tmp_free=$(df -Pk /tmp | awk 'NR==2 {print $4}'); then
  _tmp_free_gb=$(( _tmp_free / 1024 / 1024 ))
  if (( _tmp_free_gb >= 2 )); then
    _pass "/tmp has ${_tmp_free_gb} GB free (need ≥ 2 GB)"
  else
    _fail "/tmp has only ${_tmp_free_gb} GB free (need ≥ 2 GB)"
  fi
fi
_exit_if_failed

# ── 5. Toolchain versions ────────────────────────────────────────────────────
_section "toolchain versions"

# Python ≥ 3.11
if command -v python >/dev/null 2>&1; then
  if python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    _pass "python $(python -c 'import sys; print(".".join(map(str, sys.version_info[:3])))') (≥ 3.11)"
  else
    _fail "python is < 3.11 ($(python --version 2>&1))"
  fi
else
  _fail "python not on PATH"
fi

# Node ≥ 20
if command -v node >/dev/null 2>&1; then
  _node_major=$(node -p 'process.versions.node.split(".")[0]')
  if (( _node_major >= 20 )); then
    _pass "node $(node --version) (≥ 20)"
  else
    _fail "node is < 20 ($(node --version))"
  fi
else
  _fail "node not on PATH"
fi

# npm present
if command -v npm >/dev/null 2>&1; then
  _pass "npm $(npm --version)"
else
  _fail "npm not on PATH"
fi

# uv present
if command -v uv >/dev/null 2>&1; then
  _pass "uv $(uv --version 2>&1 | head -1)"
else
  _fail "uv not on PATH (install: curl -LsSf https://astral.sh/uv/install.sh | sh)"
fi

# gh present (duplicated from section 2 but harmless; aggregates cleanly)
if command -v gh >/dev/null 2>&1; then
  _pass "gh $(gh --version 2>&1 | head -1)"
fi
_exit_if_failed

# ── 6. Dependencies installed ────────────────────────────────────────────────
_section "dependencies installed"

if uv sync --frozen >/dev/null 2>&1; then
  _pass "uv sync --frozen clean"
else
  if uv sync >/dev/null 2>&1; then
    _warn "uv.lock needed updating — consider committing the new uv.lock"
  else
    _fail "uv sync failed; check pyproject.toml"
  fi
fi

if [[ -d web/node_modules ]]; then
  _pass "web/node_modules present"
else
  _warn "web/node_modules missing — run: npm --prefix web ci"
fi
_exit_if_failed

# ── 7. Network reachability ─────────────────────────────────────────────────
_section "network reachability"

if [[ -n "${PREFLIGHT_SKIP_NETWORK:-}" ]]; then
  _info "PREFLIGHT_SKIP_NETWORK set — skipping HTTP probes"
else
  _probe() {
    local url="$1"
    local label="$2"
    local code
    code=$(curl --max-time 5 -sSI -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
    # Treat any HTTP response (2xx / 3xx / 4xx) as "reachable" — the server is
    # up. 4xx on a HEAD probe is common for API roots that only accept POST.
    # 000 means the request didn't even get a response (DNS / TLS / timeout).
    if [[ "$code" == "000" || "$code" == "5"* ]]; then
      _fail "${label} unreachable (http_code=${code})"
    else
      _pass "${label} reachable (http_code=${code})"
    fi
  }
  _probe "https://github.com" "github.com"
  _probe "https://arxiv.org/abs/1603.05629" "arxiv.org (ResNet paper)"
  _probe "https://api.anthropic.com/v1/messages" "api.anthropic.com"
fi
_exit_if_failed

# ── 8. Fixture stageability ──────────────────────────────────────────────────
_section "fixture stageability"

if [[ -n "${PREFLIGHT_SKIP_STAGE:-}" ]]; then
  _info "PREFLIGHT_SKIP_STAGE set — skipping dry-run of stage.sh"
else
  _stage_probe() {
    local fixture_dir="$1"
    local fixture_name
    fixture_name=$(basename "$fixture_dir")
    local probe_dir
    probe_dir="/tmp/paper-trail-preflight-${fixture_name}-$$"
    rm -rf "$probe_dir"
    if REPRO_DEMO_TARGET="$probe_dir" \
       GITHUB_BOT_OWNER="${GITHUB_BOT_OWNER}" \
       GITHUB_BOT_REPO="${GITHUB_BOT_REPO}" \
       GITHUB_BOT_REPO_ISIC="${GITHUB_BOT_REPO_ISIC:-${GITHUB_BOT_REPO}}" \
       "$fixture_dir/stage.sh" >/dev/null 2>&1; then
      _pass "${fixture_dir}/stage.sh ran clean"
      rm -rf "$probe_dir"
    else
      _fail "${fixture_dir}/stage.sh failed (${probe_dir} left for inspection)"
    fi
  }
  _stage_probe demo/primary
  _stage_probe demo/backup
fi
_exit_if_failed

# ── 9. Prompts load ──────────────────────────────────────────────────────────
_section "prompts load"

if uv run python -c "
from server.agent import _build_investigator_system_prompt, _build_quick_check_system_prompt
from server.subagents.base import load_subagent_prompt
assert _build_investigator_system_prompt().strip()
assert _build_quick_check_system_prompt().strip()
for name in ('code_auditor', 'experiment_runner', 'paper_reader', 'validator',
            'patch_generator', 'metric_extractor'):
    assert load_subagent_prompt(name).strip(), name
print('ok')
" >/dev/null 2>&1; then
  _pass "conductor + 6 subagent prompts importable"
else
  _fail "prompt import failed — run: uv run python -c 'import server.agent'"
fi
_exit_if_failed

# ── Summary ──────────────────────────────────────────────────────────────────
_elapsed=$(( $(date +%s) - _start_sec ))
printf "\n"
if (( _fail_count == 0 )); then
  printf "${GREEN}PREFLIGHT GREEN${RESET} — %d checks passed, %d warnings in %ds\n" \
    "$_pass_count" "$_warn_count" "$_elapsed"
  exit 0
else
  printf "${RED}PREFLIGHT RED${RESET} — %d failed, %d warnings, %d passed in %ds\n" \
    "$_fail_count" "$_warn_count" "$_pass_count" "$_elapsed" >&2
  exit 1
fi
