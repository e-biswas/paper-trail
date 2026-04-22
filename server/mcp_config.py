"""MCP server configuration for the conductor.

Exposes `build_mcp_servers()` — returns a mapping suitable for
`ClaudeAgentOptions.mcp_servers`. Currently ships the official GitHub MCP
server (`@modelcontextprotocol/server-github`) as the only entry, gated on
a `GITHUB_TOKEN` being present in the environment.

If the token is absent, we return an empty dict so the conductor still runs
(investigation + fix + dossier) but cannot open a PR.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)


def build_mcp_servers() -> dict[str, Any]:
    """Return the `mcp_servers` dict for ClaudeAgentOptions.

    Type is loose (`dict[str, Any]`) because the SDK accepts several server
    shapes (stdio / SSE / HTTP / in-SDK). We use stdio for `github`.
    """
    servers: dict[str, Any] = {}

    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        servers["github"] = {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {
                # The GH MCP server expects this exact env var name.
                "GITHUB_PERSONAL_ACCESS_TOKEN": token,
            },
        }
    else:
        log.info("GITHUB_TOKEN not set — GitHub MCP disabled; no PR creation.")

    return servers


# Tools we allow the conductor to call from the GitHub MCP server. A narrow
# allowlist so the agent can't accidentally close issues, delete branches, etc.
GITHUB_TOOL_ALLOWLIST: tuple[str, ...] = (
    "mcp__github__create_pull_request",
    "mcp__github__get_pull_request",
    "mcp__github__create_or_update_file",
    "mcp__github__create_branch",
    "mcp__github__get_file_contents",
    "mcp__github__push_files",
    "mcp__github__get_repository",
)
