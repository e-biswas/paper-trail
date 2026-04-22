# Validity defense — how we back the agent's claims

Intended for judges and any technical reviewer asking *"why should I believe the output?"*

Paper Trail is a **static-inspection agent with evidence anchors**. It does not claim to certify a paper reproduces — it produces a dossier of evidence, which the user (or a human reviewer) validates. Our validity story has **seven layers**; each is independently checkable.

---

## 1. Ground-truth fixtures

We hand-built two fixtures where we **know the answer** because we wrote the bug:

| Fixture | Bug | Expected metric delta |
|---|---|---|
| `demo/primary/` (Muchlinski) | Compound: imputation-before-split + target-column-in-imputer | RF AUC 0.9562 → 0.9070 (−0.05), LR 0.8091 → 0.6962 (−0.11) |
| `demo/backup/` (ISIC) | Duplicate-image leakage (525 exact-hash duplicates cross train/test) | AUC 0.7153 → 0.6522 (−0.06) |

Before/after numbers are reproducible in <2 minutes each on a laptop: see `demo/primary/data/generate.py` + `demo/primary/src/eval.py` (seed 42). Acceptance criteria are pinned in `test_data/ground_truth/*.json`.

**Deep Investigation runs are scored against these acceptance criteria.** The Muchlinski run hit 0.98 verdict confidence and produced the correct metric delta on the first real SDK call. Receipts: `tests/smoke_muchlinski_e2e.py` and the live PRs at [muchlinski #1](https://github.com/e-biswas/reproforensics-muchlinski-demo/pull/1), [isic #1](https://github.com/e-biswas/reproforensics-isic-demo/pull/1).

## 2. The PR is the primary artifact

Each Deep Investigation opens a **real** pull request on the bot's fork. Judges can:
- Click the URL → land on a public GitHub PR
- Read the diff → see exactly what the agent changed
- Read the PR body → the 5-section dossier with file:line evidence
- Compare the `diff.patch` downloaded from the UI against the PR diff

The PR is non-deniable. If the agent hallucinated, the code wouldn't apply or the metric wouldn't move. Both Muchlinski and ISIC PRs are live as of 2026-04-22.

## 3. Real-world robustness set (4 domains, 16 Quick Checks, 0 crashes)

| Probe | Domain | Questions | Crashes | Cost | Artifacts |
|---|---|---:|---:|---:|---|
| fed | NLP dialog evaluation | 3 | 0 | ≈$0.18 | `test_data/real_papers/fed/` |
| tabm | tabular ML, clean | 3 | 0 | ≈$0.29 | `test_data/real_papers/tabm/` |
| gidd | diffusion LMs (Dec-2025, post-cutoff) | 5 | 0 | ≈$0.60 | `test_data/real_papers/gidd/` |
| byprot | protein LMs (comp-bio) | 5 | 0 | ≈$0.58 | `test_data/real_papers/byprot/` |

**Each probe saved `paper_full.md`, `paper_meta.json`, `questions.txt`, `run_summary.json`** — so anyone can open them and walk through what the agent did. Re-runs are free on the paper side (on-disk cache) and ~$0.50–0.60 on the check side.

## 4. Programmatic self-audit of evidence

`tests/audit_byprot_run.py` is a script that walks the ByProt run's `run_summary.json`, and for each cited evidence entry:

1. Confirms the cited **file exists** in the cloned repo.
2. Locates the **snippet** inside that file, within a ±5-line tolerance of the cited line.
3. Classifies each match as **strict** (contiguous, near-cited-line), **relaxed** (fragments on adjacent lines), or **partial** (agent collapsed 3+ source lines with `...` markers — inspects as faithful).
4. Checks the verdict label is semantically consistent with the `notes` field (refuted ↔ contains negation, confirmed ↔ contains affirmation, unclear ↔ contains hedging).

**Result on the ByProt run:**

- 22 of 22 cited files exist. Zero hallucinated paths.
- 22 of 22 snippets locate at the correct position (17 strict, 4 relaxed pair-matches for multi-line statements, 1 partial for a 3-line `Struct2SeqDataset(...)` call).
- 5 of 5 verdict/notes pairs semantically consistent.

**Run it yourself:**

```bash
uv run python tests/audit_byprot_run.py
```

Takes <1 second. No API calls.

## 5. Negative controls — does the agent hallucinate bugs?

On **TabM** (a clean ICLR 2025 paper with zero open issues), the agent was asked three questions where the *right* answer is "nothing is wrong":

1. *Is the train/test split leak-free?* → `confirmed` (0.90), cites the `QuantileTransformer.fit(X_train)` call in `datasets.py`.
2. *Group-aware splits?* → `unclear` (0.50), explicitly notes the repo uses TabReD's precomputed splits and doesn't re-split itself.
3. *Test-set contamination via selection?* → `refuted` (0.90), cites that hyperparameter tuning optimizes on val, not test.

No false positives. No "we found leakage!" to look clever. The agent returned `unclear` when it was unclear. That's the behavior that lets judges trust a `confirmed` or `refuted` elsewhere.

## 6. Validator subagent — on-demand peer review

Every Deep Investigation can be audited by a **Validator subagent** — a fresh Opus 4.7 call with a narrow "fair but rigorous peer reviewer" prompt. Triggered from the UI button at the bottom of an investigation turn (also available via `POST /runs/{id}/validate`), it produces a structured report:

| Check | What it asks |
|---|---|
| `hypothesis_coverage` | Did the investigator consider the obvious failure classes? |
| `evidence_quality` | Are findings code-backed or inferred? |
| `fix_minimality` | Is the diff the smallest change, or is there scope creep? |
| `causal_link` | Does the metric delta plausibly follow from the root cause? |
| `alternative_explanations` | Could something else explain the observed behavior? |
| `uncertainty_honesty` | Is "Remaining uncertainty" substantive or padding? |
| `suggested_followup` | What's the single most valuable thing the investigator didn't run? |

Each check returns `pass` / `warn` / `fail` with a one-sentence, citation-bearing note. The rollup verdict is `strong` / `acceptable` / `weak` / `unreliable`, mapped mechanically from the marks (not vibes). The full report lands:
- **In the UI** — as the last block of the assistant's chat message, color-coded per mark.
- **In the PR body** — appended to `dossier.md`, so any reader of the GitHub PR sees the self-critique alongside the fix.
- **In `run_summary.json`** — persisted for later inspection.

**Why this matters for validity:** a single agent that declares itself correct is unconvincing. A different agent-pass, with a different prompt and different constraints, that cross-checks and surfaces `warn`s or `fail`s — that's closer to how researchers actually review each other's work. On the ByProt run (no metric delta, task mismatch with paper), the validator correctly surfaced 2 `warn`s: one on causal link (no quantitative verification), one on alternative explanations (overlap not quantified). It didn't rubber-stamp.

**Cost:** ~$0.04–0.08 per audit, ~10–15 s wall-clock. Cached after the first call.

## 7. Cross-domain pattern recognition (emergent, not prompted)

On two unrelated repos the agent independently flagged the **same structural bug class** without being told to:

- **FED (NLP dialog eval):** `microsoft/DialoGPT-large` fetched via `from_pretrained` with no revision pin → upstream updates silently drift results.
- **ByProt (protein LMs):** ESM2 weights fetched via `esm.pretrained.load_model_and_alphabet_hub` from an unpinned Facebook hub URL → same mechanism.

Our prompts don't contain the word "unpinned" or any of this specific vocabulary — the agent identified the pattern from first principles in both domains. This is evidence the system generalizes structural reasoning, not keyword pattern-matching.

---

## What we do NOT claim

Judges who press us should get these as straight answers:

- **We don't certify a paper reproduces.** We audit the repo and report evidence. The final call is human.
- **We don't guarantee verdicts are correct** — only that they're grounded in the code we read. A `confirmed` verdict based on real file:line citations can still be semantically wrong if the code does something subtle the agent missed. That's why we ship evidence, not conclusions.
- **We don't detect every failure class.** Our taxonomy lives in `server/prompts/failure_classes.md` and covers 6 common ML-reproducibility patterns. A subtle bug outside the taxonomy may be missed (and should show as `unclear` with a hedged note, not a false `refuted`).
- **We don't guarantee bit-deterministic output.** LLM calls drift slightly across runs. Verdict *labels* should be stable; phrasing will wander.

---

## How a reviewer can reproduce any of this in ~10 minutes

1. Boot everything: `./dev.sh`
2. Open http://127.0.0.1:5173
3. Drop the Muchlinski paper URL + local repo path + `e-biswas/reproforensics-muchlinski-demo` slug into the Deep Investigation form. Hit send. Watch the live PR open.
4. Compare the resulting PR to [muchlinski #1](https://github.com/e-biswas/reproforensics-muchlinski-demo/pull/1). Same diff, same dossier structure.
5. Run `uv run python tests/audit_byprot_run.py` to verify the external-repo probe's evidence is real.
6. Download the dossier / diff / events.jsonl from the UI for any past run and diff them against their sibling in `test_data/real_papers/*/`.

If any of these steps produces a different outcome than documented here, that's the scenario we need to see — and the one we'd want to ship a fix for before the submission deadline.
