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

### `preflight.sh` (planned — TASKS D5.X-preflight)

A one-command sanity check you run before a rehearsal or the live
demo. Fails fast if any precondition is wrong, so you find out now
rather than 30 seconds into the run on stage.

**Why this exists.** Paper Trail has a long list of external
preconditions: env vars filled in, a GitHub PAT with the right scope,
ports 8080 and 5173 free, enough disk on `/tmp`, a Python env and
Node toolchain that actually work, network reachability to GitHub
and arXiv, and two fixtures that must stage cleanly. Any one of
these can silently fail and turn a 3-minute demo into a 30-minute
debug session. The preflight bundles all the checks into one script.

**What it checks, in order:**

1. **Env vars present.** `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`,
   `GITHUB_BOT_OWNER`, `GITHUB_BOT_REPO`, `GITHUB_BOT_REPO_ISIC` —
   each must be set and non-empty.
2. **GitHub PAT scope.** `gh auth status` reports the `repo` scope
   (needed to push branches and open PRs on the bot-owned repo).
3. **Ports free.** `lsof -i :8080 -i :5173` returns nothing.
4. **Disk space.** At least 2 GB free on the `/tmp` filesystem.
5. **Toolchain versions.** `python --version` ≥ 3.11,
   `node --version` ≥ 20, `npm --version` works, `uv --version`
   works, `gh --version` works.
6. **Dependencies installed.** `uv sync --frozen --check` returns
   clean; `npm --prefix web ci --dry-run` returns clean.
7. **Network reachability.** `curl -sfI https://github.com` and
   `curl -sfI https://arxiv.org/abs/1603.05629` both return 200
   within 5 s.
8. **Fixture stageability.** `demo/primary/stage.sh` and
   `demo/backup/stage.sh` both run to completion against a
   throwaway `/tmp/paper-trail-preflight-*` target.
9. **Prompts load.** Python import of `server.agent` and
   `server.prompts` succeeds (catches syntax / missing-file
   regressions early).

**Output.** One line per check, `✓` or `✗` prefix. Non-zero exit on
first failure so CI can gate on it. Prints a summary at the end with
elapsed time.

**When to run it.**

- Before every rehearsal.
- Immediately before the live demo (5 minutes out).
- After pulling changes on a fresh machine.
- On any new machine, before even running `init_demo_repos.sh`.

**When NOT to run it.** During an active run — it starts its own
fixture-stage probe which collides with the /tmp state the running
agent depends on.

## Related

- `demo/primary/stage.sh`, `demo/backup/stage.sh` — do the local
  staging work; `init_demo_repos.sh` wraps them with the push step,
  `preflight.sh` wraps them in a dry-run probe.
- `.env.example` — shows the env vars these scripts read.
