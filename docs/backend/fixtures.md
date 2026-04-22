# Backend — Demo Fixtures

## Purpose

Pre-staged, pre-vetted repository fixtures that the agent investigates during demos. Each fixture is a small, runnable project with a known-documented reproducibility bug. These are the curated inputs our demo narrative depends on.

## Status

`TODO` · last updated 2026-04-21

## Fixtures

### Primary: Muchlinski 2016 — Civil War Prediction (imputation-before-split leakage)

- **Paper:** Muchlinski et al. 2016, "Comparing Random Forest with Logistic Regression for Predicting Class-Imbalanced Civil War Onset Data," *Political Analysis*.
- **Documented critique:** Kapoor & Narayanan, "Leakage and the Reproducibility Crisis in ML-based Science" (Princeton, 2023).
- **Location:** [`demo/primary/`](../../demo/primary/)
- **Dataset:** included in fixture (small, public — civil war onset panel).
- **Runtime:** full eval ≤ 2 min.
- **Bug:** imputation (Amelia II in the original R code; `IterativeImputer` in our Python port) is fit on the full dataset before train/test split. This leaks test-distribution information into training and inflates the Random Forest's relative advantage.
- **Fix:** move imputation into a `sklearn.pipeline.Pipeline` so it fits on train only.
- **Expected metric delta:** `RF AUC: 0.85 → 0.72`, `LR AUC: ~0.74 unchanged`. The paper's headline claim ("RF >> LR") evaporates.

### Backup: ISIC 2020 Melanoma Classification (duplicate-image leakage)

- **Challenge:** SIIM-ISIC 2020 Melanoma Classification (Kaggle).
- **Documented critique:** community GitHub issues and Nature Scientific Data follow-ups identifying 425+ exact-duplicate images between train folds, plus perceptual near-duplicates.
- **Location:** [`demo/backup/`](../../demo/backup/)
- **Dataset:** a small curated slice of the public ISIC 2020 images + metadata, chosen to surface the duplicates.
- **Runtime:** full eval ≤ 5 min.
- **Bug:** no dedup on image hashes before k-fold split.
- **Fix:** perceptual hash + dedup before split.
- **Expected metric delta:** AUC drops ~0.05 once duplicates are removed (less dramatic than Muchlinski, but medical-vertical story).

## Public interface

Each fixture is a self-contained directory with this layout:

```
demo/<fixture>/
├── README.md              ← what's broken, how to run, expected outputs
├── stage.sh               ← idempotent script: clones/builds/resets to broken state
├── reset.sh               ← rewinds the fixture after a demo run (undo any agent edits)
├── src/                   ← the broken code
├── data/                  ← small data sample
├── eval.py                ← the "official" eval script; prints a JSON line the agent can parse
└── .git/                  ← initialized so agent can branch/commit/push
```

### `stage.sh` responsibilities

1. Create the working dir (`/tmp/<fixture>-demo/`) if missing; else `rm -rf` it.
2. Copy `src/`, `data/`, `eval.py` into the working dir.
3. `cd` into the working dir; `git init -b main`; `git add -A`; `git commit -m "initial broken state"`.
4. Add the configured GitHub remote: `git remote add origin https://github.com/<BOT_OWNER>/<BOT_REPO>.git`.
5. Force-push main to reset the bot's fork.
6. Print the absolute path to stdout (this goes into the UI's prefilled `repo_path`).

### `eval.py` contract

Every fixture has an `eval.py` that the agent runs after applying a fix. It:

- Reads data from a known path.
- Trains/loads the model (small, fast, cheap).
- Writes a single line to stdout: `METRIC_JSON: {"metric": "ROC-AUC", "value": 0.72, "context": "RF", ...}`.
- Returns exit code 0 on success.

The investigator prompt tells the agent how to parse this line.

## Implementation notes

### Sizing for demo

Fixtures are deliberately small. The rule: **full eval must complete in under 2 minutes on a laptop.** We are not demoing training runs — we are demoing scientific debugging. If a fixture needs GPU, it's out.

### Keeping fixtures "believable"

The goal is to look like real ML repos. That means:
- Reasonable directory layout (`src/`, `data/`, `eval.py`), not one-file hacks.
- `README.md` inside the fixture that looks like a real repo's README (credits the original paper, describes the dataset, shows how to run).
- Realistic but minimal `requirements.txt`; all deps pinned.

### Preventing stale state between demo runs

After every full demo run the agent has added a branch, committed a fix, pushed, and opened a PR. Before re-running the demo:

```bash
cd demo/primary && ./reset.sh
```

Which: deletes local branches other than `main`, resets `main` to the initial commit, force-pushes to the fork, closes any open PRs via `gh pr list --state open | xargs gh pr close`.

### Dataset licensing

- Muchlinski data: publicly released with the paper and derivative replication repos. Safe to bundle.
- ISIC data: Kaggle competition data, CC-BY-NC. Only a very small sample bundled; `stage.sh` downloads the rest on demand from the public ISIC archive if needed.

### Why not use the original repos directly

The original Muchlinski repo is R; rewriting in Python keeps the agent's tool use consistent (no R interpreter needed). The original ISIC solutions are sprawling; we distill to a minimal classifier that surfaces the duplicate-image bug cleanly.

## How to verify (end-to-end)

### Per-fixture verification

For each of `primary` and `backup`:

1. **Staging idempotency:**
   ```bash
   demo/primary/stage.sh
   demo/primary/stage.sh   # second call
   ```
   Both succeed. Second call leaves state identical to first.

2. **Broken baseline runs:**
   ```bash
   cd /tmp/muchlinski-demo && python eval.py
   # prints: METRIC_JSON: {"metric": "ROC-AUC", "value": 0.85, "context": "RF", ...}
   ```

3. **Fix-by-hand verification:** apply the documented fix by hand, re-run `eval.py`, confirm the metric delta matches the expectation in the fixture's README. This is the ground truth the agent must reproduce.

4. **Reset works:**
   ```bash
   demo/primary/reset.sh
   # bot fork is back to broken state, no stray branches, no open PRs
   ```

5. **Agent reproduces the expected fix** — verified as part of the end-to-end test in [agent.md](agent.md).

### Cross-fixture checks

- The agent's workflow must not hard-code fixture-specific paths. Verify by running Deep Investigation on both fixtures with the same server binary.

## Open questions / deferred

- Tertiary fixture for the pitch (e.g., a temporal-leakage case): `DEFERRED`; scope-frozen after Day 4.
- Allow user-provided repos: `DEFERRED`; MVP is curated-only.
- Automated fixture CI (run `stage.sh` + `eval.py` nightly to detect rot): post-hackathon.
