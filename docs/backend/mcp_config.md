# Backend — GitHub MCP Configuration

## Purpose

Configure the official GitHub MCP server (`@modelcontextprotocol/server-github`) as a subprocess of the Claude Agent SDK, so the agent can open real pull requests at the end of a Deep Investigation.

## Status

`TODO` · last updated 2026-04-21

## Public interface

```python
# server/mcp_config.py
from claude_agent_sdk import McpStdioServerConfig

def build_mcp_servers() -> dict[str, McpStdioServerConfig]:
    """
    Returns the `mcp_servers` dict for ClaudeAgentOptions.
    The agent SDK spawns each server as a subprocess over stdio.
    """
```

Used by `server/agent.py`:

```python
options = ClaudeAgentOptions(
    ...,
    mcp_servers=build_mcp_servers(),
    allowed_tools=[..., "mcp__github__create_pull_request", "mcp__github__get_pull_request"],
)
```

## Implementation notes

### Config

```python
import os
from claude_agent_sdk import McpStdioServerConfig

def build_mcp_servers() -> dict[str, McpStdioServerConfig]:
    return {
        "github": McpStdioServerConfig(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": os.environ["GITHUB_TOKEN"]},
        ),
    }
```

Note: the env var name for the GitHub MCP server is `GITHUB_PERSONAL_ACCESS_TOKEN`, NOT `GITHUB_TOKEN`. We mirror our own `GITHUB_TOKEN` into it.

### Tool allowlist — what the agent is permitted to call

**INVARIANT: additive-only.** We do NOT expose every GitHub MCP tool. The GH
MCP server ships ~40 tools in total; our allowlist exposes only the additive
ones the investigator + PR-opener need. Destructive tools — `delete_file`,
`delete_branch`, `merge_pull_request`, `update_pull_request`, `close_*`,
`create_issue` — are never in the agent's tool schema, so the model cannot
invoke them regardless of token scope. This is defence layer #1 for the
fork-first PR flow (see below).

| Tool | Why |
|---|---|
| `mcp__github__create_pull_request` | The core artifact |
| `mcp__github__get_pull_request`    | Confirm PR state after creation |
| `mcp__github__get_repository`      | Read repo metadata (branch names, fork existence) |
| `mcp__github__create_branch`       | Push the fix branch |
| `mcp__github__create_or_update_file` | Commit each changed file |
| `mcp__github__get_file_contents`   | Read upstream file content when Read isn't enough |
| `mcp__github__push_files`          | Batch commit helper |
| `mcp__github__fork_repository`     | Fork-first flow: idempotent (returns existing fork if present) |

Auto-PR off path: when `RunConfig.auto_pr` is `False`, the investigator
runs with a **narrower** read-only subset (`get_repository`,
`get_file_contents`, `get_pull_request`) so it literally cannot commit or
open a PR. The user triggers PR opening out-of-band via
`POST /runs/{id}/push_pr`, which spawns a focused subagent with the full
allowlist restored for a single bounded run.

Explicitly NOT on the allowlist:
- Any `delete_*` / `merge_pull_request` / `update_pull_request` / `close_*`
  / `create_issue` / `add_comment` — anything that mutates state the demo
  doesn't need, or anything that could touch repos the bot doesn't own.

### PAT scope (minimum viable)

The bot's personal access token needs:

- `repo` (full) — required to push a branch and open a PR on a fork
- Nothing else

Fine-grained tokens also work. Scope restricted to the single demo repo.

### Repo flow for the PR

Agent operates inside `config.repo_path` (the staged local clone). The PR
step is MCP-driven — no `git push`. Two shapes, selected at prompt build
time by `_build_pr_directive` in `server/agent.py`:

**A. Bot-owned upstream (classic demo path).** When `repo_slug` owner ==
`GITHUB_BOT_OWNER`, the agent calls the tools directly against the
upstream:

1. `create_branch(owner=upstream, repo=upstream, branch=fix/..., from_branch=main)`
2. `create_or_update_file(owner=upstream, repo=upstream, branch=fix/..., path=…)` — once per file in `files_changed`
3. `create_pull_request(owner=upstream, repo=upstream, head="fix/...", base="main")`

**B. Fork-first (third-party upstream).** When `repo_slug` owner !=
`GITHUB_BOT_OWNER`, the agent's `Fork slug:` line carries the bot-owned
fork slug (`<bot-owner>/<repo>`):

1. `fork_repository(owner=upstream, repo=upstream)` — idempotent; returns the existing fork if present
2. `create_branch(owner=fork, repo=fork, branch=fix/..., from_branch=main)`
3. `create_or_update_file(owner=fork, repo=fork, branch=fix/..., path=…)` — once per file
4. `create_pull_request(owner=upstream, repo=upstream, head="<bot-owner>:fix/...", base="main")` — **cross-fork PR**; the `<bot-owner>:` prefix on `head` is what makes GitHub look at the fork's branch rather than the upstream's

Either shape: the MCP call returns `{url, number, title}`; agent echoes
`## PR opened:` with those fields; the server emits `pr_opened`.

### Bot account + demo fork plan

- Demo fork(s) live under `GITHUB_BOT_OWNER/GITHUB_BOT_REPO` configured in `.env`.
- For each demo fixture (Muchlinski, ISIC), we maintain a separate fork so demo PRs don't pollute each other.
- Before recording the final demo video, we run `git push --force` to reset the fork to the broken baseline, delete stale PRs, and re-run.

### Fallback if GitHub MCP fails

If PR creation fails (auth, rate limit, network), the agent should still emit `## Fix applied:` and `## Metric delta:` sections, then `## Aborted:` with `reason="pr_failed"`. The frontend renders a clear "PR could not be opened, here is the diff" panel and lets us screenshot / record anyway. No demo-breaking dependency on GitHub uptime.

## How to verify (end-to-end)

### Setup

1. Bot PAT in `.env` as `GITHUB_TOKEN`.
2. Empty demo fork at `<GITHUB_BOT_OWNER>/<GITHUB_BOT_REPO>` with `main` containing the broken Muchlinski fixture.

### Smoke test — MCP subprocess boots

```bash
uv run python -c "
from server.mcp_config import build_mcp_servers
import anyio
async def main():
    cfg = build_mcp_servers()
    print('OK' if 'github' in cfg else 'FAIL')
anyio.run(main)
"
```

Expect: `OK`.

### Live PR creation test

1. `uv run python -m server.agent --demo muchlinski`
2. Watch for `tool_call` with `name=mcp__github__create_pull_request`.
3. Watch for `tool_result` with output including a PR URL.
4. Watch for `pr_opened` envelope with `url` matching `https://github.com/.+/pull/\d+`.
5. Open the URL in a browser. Expect:
   - Title starts with `[RF] Fix: `
   - Body contains all 5 dossier sections
   - Diff changes `prepare_data.py` (or equivalent) with <50 LOC changed
   - No merge conflicts

### Expected failure modes

- **`npx` not found.** Node ≥ 20 must be installed. Add a preflight check to `env.py`.
- **Auth 401 from GitHub.** PAT expired / wrong scope. Regenerate.
- **"resource not accessible by integration".** Fine-grained token scoped to wrong repo. Widen scope or switch to full `repo`.
- **Rate limit.** Unlikely for demo volume, but bot account hits 5000/hr. If triggered during rehearsal, back off and retry.

## Known gaps / corner cases

- **MAJOR — missing `GITHUB_TOKEN` fails late with cryptic error.**
  `server/mcp_config.py:28-40` wraps the MCP server add in
  `if token:` with no warning path. When the token is unset, PR
  creation fails mid-run with "tool not found" rather than a clear
  startup error. Fix sketch: raise `ConfigError("GITHUB_TOKEN missing;
  PR creation will fail")` in `build_mcp_servers()` and have the
  server refuse to start in investigate mode.
- **MAJOR — PR creation failure after dossier is emitted leaves run
  ambiguous.** The investigator's prompt emits the dossier before the
  `create_pull_request` call; if the MCP call fails, the UI has a
  complete dossier but no PR link. Fix sketch: emit dossier with
  `pr_status: "pending"` and emit the definitive `pr_opened` (or
  synthesized `aborted reason=pr_failed`) immediately after the MCP
  round-trip.
- **MINOR — no MCP subprocess crash recovery.** If the `npx`
  server crashes mid-run, the SDK reports a tool error but doesn't
  restart it. Document as a hard failure mode; rely on preflight
  (`npx @modelcontextprotocol/server-github` reachable) instead of
  mid-run recovery.
- **MINOR — branch name collision on demo re-runs.** The agent picks
  `fix/reproducibility-<timestamp>`; within a rehearsal window the
  timestamps can collide at second resolution. Fix sketch: include a
  short random suffix, e.g. `-$(openssl rand -hex 2)`.

## Open questions / deferred

- GitHub App instead of PAT: would be cleaner and scope-limited, but MVP uses PAT. `DEFERRED`.
- Signed commits: `DEFERRED`.
- Automatic PR closure / reset after demo: post-hackathon.
