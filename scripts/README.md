# scripts/

One-off helper scripts for setting up Paper Trail's demo environment. These
are not part of the agent's runtime — they're developer utilities you run
by hand before a demo (or once when bootstrapping a new machine).

## What's in here

### `init_demo_repos.sh`

Publishes the "broken baseline" code for each demo fixture to a GitHub repo
that the agent is allowed to open PRs against.

**Why this exists.** During the demo the agent investigates a paper's
public repo, finds the bug, fixes it, and opens a pull request. For that
to work on stage we need a real GitHub repo — owned by a bot account —
that already contains the buggy code. That way the agent's fix becomes
a visible, clickable PR on a real repo URL, not a toy local commit.

**What it does, step by step:**

1. Reads `GITHUB_TOKEN` and `GITHUB_BOT_OWNER` (and the per-fixture repo
   names) from `.env`.
2. For each demo fixture under `demo/` (currently `primary/` = Muchlinski
   civil-war, `backup/` = ISIC melanoma):
   - Runs the fixture's own `stage.sh` to materialize the broken code
     at `/tmp/<fixture>-demo/` as a git repo.
   - Temporarily embeds the token into the remote URL, force-pushes
     `main` to the bot-owned GitHub repo, then scrubs the token back
     out of the local config.

**Safe to re-run.** The force-push is intentional — it resets the bot
repo to a clean broken state so the next demo run starts from a known
baseline, even if the previous run merged a fix. Idempotent by design.

**When to run it.**

- Once per new machine, after you've filled in `.env`.
- Before a rehearsal or the live demo, to reset the bot repo back to
  the broken baseline.
- After you change a fixture's code and want the GitHub repo to match.

**When NOT to run it.** Never during a live run. It force-pushes, which
would clobber any in-progress PR the agent is working against.

### `preflight.sh`

A one-command sanity check you run before a rehearsal or the live
demo. Fails fast at the first broken precondition, so you find out
now rather than 30 seconds into the run on stage.

**Why this exists.** Paper Trail has a long list of external
preconditions: env vars filled in, a GitHub PAT, ports 8080 and 5173
free, enough disk on `/tmp`, a working Python env and Node
toolchain, network reachability to GitHub / arXiv / Anthropic, and
two fixtures that must stage cleanly. Any one of these can silently
fail and turn a 3-minute demo into a 30-minute debug session. The
preflight bundles all the checks into one script.

**How to run it.**

```bash
./scripts/preflight.sh                          # full run, ~2–5 s on a warm cache
PREFLIGHT_SKIP_NETWORK=1 ./scripts/preflight.sh # skip HTTP probes (offline rehearsal)
PREFLIGHT_SKIP_STAGE=1   ./scripts/preflight.sh # skip fixture stage probe (fast iteration)
```

Exit status is `0` on full green, `1` on the first failure. Output
is one `✓` / `✗` / `!` / `·` line per check plus a one-line summary
with elapsed seconds. Runs from the repo root; `cd` isn't needed —
the script detects its own location.

**What it checks, in order:**

1. **Env vars present.** `.env` loads; `ANTHROPIC_API_KEY`,
   `GITHUB_TOKEN`, `GITHUB_BOT_OWNER`, `GITHUB_BOT_REPO` all set and
   non-empty (and not the `.env.example` placeholder strings).
   `GITHUB_BOT_REPO_ISIC` is soft-required — a warning, not a fail.
2. **GitHub PAT scope.** Paper Trail uses the GitHub MCP server (via
   `npx`), not the `gh` CLI, so `gh` is optional. If `gh` is present
   the script uses `gh auth status`; otherwise it probes
   `api.github.com/user` with the token. Fine-grained tokens
   (no `x-oauth-scopes` header) surface as a warning, not a fail.
3. **Ports free.** `lsof -i :8080` and `lsof -i :5173` both empty.
4. **Disk space.** At least 2 GB free on the `/tmp` filesystem.
5. **Toolchain versions.** Python ≥ 3.11, Node ≥ 20, `npm`, `uv`,
   and `gh` (if installed) all resolvable.
6. **Dependencies installed.** `uv sync --frozen` runs clean;
   `web/node_modules` is present (warning if not — run `npm ci`).
7. **Network reachability.** HEAD probes to `github.com`,
   `arxiv.org/abs/1603.05629`, and `api.anthropic.com/v1/messages`
   within a 5 s timeout. Any `2xx` / `3xx` / `4xx` counts as
   reachable; `5xx` or no-response fails. Skip with
   `PREFLIGHT_SKIP_NETWORK=1`.
8. **Fixture stageability.** `demo/primary/stage.sh` and
   `demo/backup/stage.sh` both run to completion against throwaway
   `/tmp/paper-trail-preflight-*` targets that are removed on
   success. Skip with `PREFLIGHT_SKIP_STAGE=1`.
9. **Prompts load.** `uv run python -c` imports the investigator +
   quick-check prompts and all six subagent prompts (`code_auditor`,
   `experiment_runner`, `paper_reader`, `validator`,
   `patch_generator`, `metric_extractor`). Catches syntax or
   missing-file regressions before a live run.

**When to run it.**

- Before every rehearsal.
- Immediately before the live demo (5 minutes out).
- After pulling changes on a fresh machine.
- On any new machine, before even running `init_demo_repos.sh`.

**When NOT to run it.** During an active run — the fixture-stage
probe collides with the `/tmp/*-demo` state the running agent
depends on. Use `PREFLIGHT_SKIP_STAGE=1` if you need the rest of the
checks while a run is in flight.

## Related

- `demo/primary/stage.sh`, `demo/backup/stage.sh` — do the local
  staging work; `init_demo_repos.sh` wraps them with the push step,
  `preflight.sh` wraps them in a dry-run probe.
- `.env.example` — shows the env vars these scripts read.
- `tests/smoke_abort_e2e.py` + `tests/smoke_new_subagents.py` — the
  backend smoke tests preflight's prompt-load check guards against
  regressing.
