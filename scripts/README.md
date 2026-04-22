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

## Related

- `demo/primary/stage.sh`, `demo/backup/stage.sh` — do the local
  staging work; this script just wraps them with the push step.
- `.env.example` — shows the env vars this script reads.
