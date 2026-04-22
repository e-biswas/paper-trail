"""Environment + credential verification.

Non-destructive checks for:

1. `.env` loads cleanly via `server.env.load_env()`.
2. `ANTHROPIC_API_KEY` is shaped like a real key (does NOT call the API — the
   SDK smoke in `tests/smoke_sdk.py` already covered that).
3. `GITHUB_TOKEN` authenticates and identifies a real user.
4. The token CAN see the two demo repos (`GITHUB_BOT_OWNER`/`GITHUB_BOT_REPO`
   and the optional ISIC repo).
5. The token has WRITE permission on those repos (contents + pull requests).
6. The token CANNOT see anything else — fine-grained scoping worked.

Prints compact PASS/FAIL summary at the end. Exits non-zero on hard failures.
Secrets are never printed (prefixes only).
"""
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass

import httpx

from server.env import load_env


GH_API = "https://api.github.com"


def _redact(value: str, keep: int = 10) -> str:
    if not value:
        return "<empty>"
    return f"{value[:keep]}…({len(value)} chars)"


def _print(label: str, value: object) -> None:
    print(f"  {label:32s} {value}")


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


async def _gh_get(client: httpx.AsyncClient, path: str, token: str) -> httpx.Response:
    return await client.get(
        f"{GH_API}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "paper-trail-smoke",
        },
    )


async def main() -> int:
    # ── 1. Load env ──────────────────────────────────────────────────────
    try:
        load_env()
    except Exception as exc:
        print(f"FAIL: env.load_env() raised: {exc}")
        return 1

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    gh_token = os.environ.get("GITHUB_TOKEN", "")
    gh_owner = os.environ.get("GITHUB_BOT_OWNER", "")
    gh_repo = os.environ.get("GITHUB_BOT_REPO", "")
    gh_repo_isic = os.environ.get("GITHUB_BOT_REPO_ISIC", "")

    print("── .env loaded ──")
    _print("ANTHROPIC_API_KEY", _redact(anthropic_key, 7))
    _print("GITHUB_TOKEN", _redact(gh_token, 15))
    _print("GITHUB_BOT_OWNER", gh_owner or "<empty>")
    _print("GITHUB_BOT_REPO", gh_repo or "<empty>")
    _print("GITHUB_BOT_REPO_ISIC", gh_repo_isic or "<empty>")
    print()

    results: list[CheckResult] = []

    # ── 2. Anthropic key shape ───────────────────────────────────────────
    if anthropic_key.startswith("sk-ant-") and len(anthropic_key) > 50:
        results.append(CheckResult("ANTHROPIC_API_KEY shape", True, "starts with sk-ant- and is long enough"))
    else:
        results.append(
            CheckResult("ANTHROPIC_API_KEY shape", False, f"unexpected prefix/length: {_redact(anthropic_key)}")
        )

    # ── 3. GitHub — token identity ───────────────────────────────────────
    async with httpx.AsyncClient(timeout=10.0) as client:
        if not gh_token:
            results.append(CheckResult("GITHUB_TOKEN present", False, "empty"))
        else:
            r = await _gh_get(client, "/user", gh_token)
            if r.status_code == 200:
                user = r.json()
                login = user.get("login")
                results.append(CheckResult("GITHUB_TOKEN authenticates", True, f"login={login}"))
                if login != gh_owner:
                    results.append(CheckResult(
                        "token owner matches GITHUB_BOT_OWNER",
                        False,
                        f"token belongs to {login!r}, but GITHUB_BOT_OWNER={gh_owner!r} — PR creation will target the wrong account",
                    ))
                else:
                    results.append(CheckResult("token owner matches GITHUB_BOT_OWNER", True, login))
            else:
                results.append(CheckResult(
                    "GITHUB_TOKEN authenticates",
                    False,
                    f"HTTP {r.status_code}: {r.text[:200]}",
                ))

        # ── 4. Repo visibility + write permission ─────────────────────────
        for label, repo in [("primary", gh_repo), ("isic", gh_repo_isic)]:
            if not repo:
                continue
            r = await _gh_get(client, f"/repos/{gh_owner}/{repo}", gh_token)
            if r.status_code == 404:
                results.append(CheckResult(
                    f"{label} repo visible ({gh_owner}/{repo})",
                    False,
                    "404 — repo doesn't exist or token isn't scoped to it",
                ))
                continue
            if r.status_code != 200:
                results.append(CheckResult(
                    f"{label} repo visible ({gh_owner}/{repo})",
                    False,
                    f"HTTP {r.status_code}: {r.text[:200]}",
                ))
                continue

            data = r.json()
            results.append(CheckResult(
                f"{label} repo visible ({gh_owner}/{repo})",
                True,
                f"visibility={data.get('visibility')} default_branch={data.get('default_branch')}",
            ))
            perms = data.get("permissions") or {}
            can_push = bool(perms.get("push") or perms.get("admin"))
            results.append(CheckResult(
                f"{label} repo write permission",
                can_push,
                f"permissions={perms}",
            ))

        # ── 5. Scope isolation — attempt a WRITE on a non-demo repo ───────
        #
        # Methodology note: `/user/repos` returns repos the *user* owns, not
        # repos the *token* is scoped to, so that listing is misleading for
        # fine-grained PATs. Similarly `GET /repos/{owner}/{repo}` succeeds
        # on any public repo regardless of scope, and its `permissions` field
        # reports the USER's permissions, not the token's effective scope.
        #
        # The only definitive check is: attempt a write that requires the
        # `contents:write` permission. A correctly-scoped token returns 403
        # on non-demo repos; a broadly-scoped token returns 422/201.
        non_demo_probes = ["coursera-web-development", "e-biswas.github.io", "masters_thesis"]
        leak_found = False
        probe_details = []
        for probe in non_demo_probes:
            pr = await client.post(
                f"{GH_API}/repos/{gh_owner}/{probe}/git/refs",
                headers={
                    "Authorization": f"Bearer {gh_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "paper-trail-smoke",
                },
                json={"ref": "refs/heads/scope-probe-do-not-use", "sha": "0" * 40},
            )
            probe_details.append(f"{probe}={pr.status_code}")
            if pr.status_code not in (403, 404):
                leak_found = True

        if leak_found:
            results.append(CheckResult(
                "token scope blocks writes to non-demo repos",
                False,
                f"unexpected write-probe results: {', '.join(probe_details)} (want 403 or 404)",
            ))
        else:
            results.append(CheckResult(
                "token scope blocks writes to non-demo repos",
                True,
                f"write probes all blocked ({', '.join(probe_details)})",
            ))

        # ── 6. Rate limit headroom ────────────────────────────────────────
        r = await _gh_get(client, "/rate_limit", gh_token)
        if r.status_code == 200:
            core = r.json().get("resources", {}).get("core", {})
            remaining = core.get("remaining", 0)
            limit = core.get("limit", 0)
            results.append(CheckResult(
                "rate limit",
                remaining > 100,
                f"{remaining}/{limit} remaining",
            ))

    # ── Verdict ──────────────────────────────────────────────────────────
    print("── Checks ──")
    for r in results:
        icon = "✓" if r.ok else "✗"
        print(f"  {icon} {r.name:45s} {r.detail}")

    hard_fails = [r for r in results if not r.ok]
    print()
    if not hard_fails:
        print("ALL CHECKS PASSED. Ready for Day 2 auto mode.")
        return 0
    print(f"FAIL: {len(hard_fails)} check(s) failed. Fix before proceeding.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
