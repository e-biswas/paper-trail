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

We do NOT expose every GitHub MCP tool. The agent should not open issues, close PRs, or touch unrelated repos. Allowlist:

| Tool | Why |
|---|---|
| `mcp__github__create_pull_request` | The core artifact |
| `mcp__github__get_pull_request` | Confirm PR state after creation |
| `mcp__github__get_repository` | Read repo metadata if needed |

Explicitly NOT on the allowlist:
- Any `delete_*` / `merge_pull_request` / `create_issue` / anything that mutates state the demo doesn't need.

### PAT scope (minimum viable)

The bot's personal access token needs:

- `repo` (full) — required to push a branch and open a PR on a fork
- Nothing else

Fine-grained tokens also work. Scope restricted to the single demo repo.

### Repo flow for the PR

1. Agent operates inside `config.repo_path` (already a git repo; the fixture's `stage.sh` ran `git init` + committed the broken state).
2. Agent uses `Bash` to: `git checkout -b fix/reproducibility-<timestamp>`, `git add`, `git commit -m "..."`, `git push`.
3. Agent calls `mcp__github__create_pull_request(base="main", head="fix/...", title="...", body="<dossier markdown>")`.
4. The MCP tool returns `{url, number, title}`. Agent echoes a `## PR opened:` section; server emits `pr_opened`.

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

## Open questions / deferred

- GitHub App instead of PAT: would be cleaner and scope-limited, but MVP uses PAT. `DEFERRED`.
- Signed commits: `DEFERRED`.
- Automatic PR closure / reset after demo: post-hackathon.
