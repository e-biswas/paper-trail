# Paper Trail — Consistency Benchmark

A self-imposed scientific validation of the Paper Trail agent. We ask: given
the same paper, the same repo, and the same question, does the agent produce
a consistent answer across independent runs? If the agent is going to help
audit *other* people's reproducibility, its own output had better be
reproducible.

This benchmark exercises **the core system only** — no web UI, no GitHub PR
side-effects — so the numbers reflect the model + prompts + tooling chain in
isolation. `auto_pr=false` on every run.

---

## What this measures

For every `(paper, mode, question)` triple we run the agent **N=3 times** and
compare the outputs. We care about three independent quality signals:

1. **Agreement** — do the repeats reach the same *decision*?
   - Quick Check: same verdict label (`confirmed` / `refuted` / `unclear`)?
   - Deep Investigation: same top-confidence hypothesis name?
2. **Evidence grounding** — do the repeats cite the same *code*?
   - Quick Check: Jaccard on `(file, line)` citations.
   - Deep Investigation: Jaccard on `files_changed` from the fix.
3. **Independent review quality** — does the second-opinion Validator agree?
   - Deep only — the Validator subagent grades the investigation on seven
     axes (hypothesis coverage, evidence quality, fix minimality, causal
     link, alternatives considered, uncertainty honesty, follow-up).

Plus scalar dispersion on cost, wall-clock duration, and tool-call count —
predictability signals for anyone planning to budget around this agent.

---

## Targets

Two recent papers with full Quick Check coverage already in
`test_data/real_papers/`. Both are **not owned** by the bot account — the
agent is reading cold code the authors shipped publicly.

| Target | Year | Domain | Why it's here |
|---|---|---|---|
| `tabm` | ICLR 2025 | Tabular deep learning | **Clean baseline.** No documented bug. Tests whether the agent hallucinates a problem when there isn't one. |
| `gidd` | arXiv Dec 2025 | Discrete diffusion LMs | **Hardest stress case.** Post-training-cutoff, TPU-scale 10B-parameter training, a domain the agent wasn't designed for. |

Paper PDFs / arXiv sources, cached markdown, existing Quick Check
questions, and prior-run results for these targets live under
[`../test_data/real_papers/`](../test_data/real_papers/).

## Prompts

For each target we ask:

- **Quick Check** — the existing questions in
  [`../test_data/real_papers/<target>/questions.txt`](../test_data/real_papers/),
  imported verbatim into
  [`questions/<target>.json`](questions/). These are grounded, falsifiable,
  single-verdict questions written earlier as robustness probes.
- **Deep Investigation** — one new *professor-style* prompt per paper,
  crafted for this benchmark. Neutral and non-leading (no "find the bug"
  framing), but specific enough that an honest repo audit has to engage
  with a mechanism, not a vibe. See the `deep_investigation.prompt` field
  in each `questions/<target>.json`.

The professor prompts are threaded into the agent via a newly-exposed
`user_prompt` → "Operator brief" splice in `server/agent.py` (additive,
backward-compatible; previously unused on the Deep path).

---

## Layout

```
benchmark/
├── README.md                          ← you are here
├── questions/
│   ├── gidd.json                      ← 5 Quick Checks + 1 Deep prompt
│   └── tabm.json                      ← 3 Quick Checks + 1 Deep prompt
├── scripts/
│   ├── run_benchmark.py               ← repeats every question N times; resumable
│   ├── validate_runs.py               ← Validator subagent over every Deep run
│   ├── analyze_consistency.py         ← produces results/consistency.json
│   └── make_report.py                 ← renders results/SUMMARY.md
├── runs/
│   └── <paper>/<mode>/<q_id>/repeat_<k>/
│       ├── events.jsonl               ← raw envelope stream (authoritative)
│       ├── run_meta.json              ← compact summary (verdict, cost, …)
│       ├── dossier.md                 ← Deep-only: rendered 5-section dossier
│       └── validity_report.json       ← Deep-only: Validator payload + cost
└── results/
    ├── consistency.json               ← computed metrics per group & aggregate
    └── SUMMARY.md                     ← human-readable report (tables only)
```

---

## Metric definitions

All metrics are computed in
[`scripts/analyze_consistency.py`](scripts/analyze_consistency.py).

### Quick Check

| Metric | Definition |
|---|---|
| **Verdict agreement** | Fraction of repeats whose verdict label equals the modal label for that question. 1.0 = unanimous; 0.33 = three different answers (with N=3). |
| **Fleiss' κ** | Chance-corrected agreement on verdict labels across all Quick Check questions of a paper, pooling N raters per item. κ > 0.6 is substantial; κ > 0.8 is near-perfect agreement beyond chance. |
| **Evidence file Jaccard** | Mean pairwise Jaccard on the set of cited `file` paths across repeats. Measures "did the agent look at the same code?" |
| **Evidence line Jaccard** | Same, but on `(file, line)` tuples. Stricter — rewards citing the exact same line. |
| **Confidence mean / sd** | Self-reported confidence (0-1) across repeats. Large SD = the agent is uncertain about its own certainty. |
| **Cost / duration / tool-calls mean & sd** | Predictability signals. Low SD = cheap to plan around. |

### Deep Investigation

| Metric | Definition |
|---|---|
| **Top-hypothesis agreement** | Fraction of repeats whose highest-confidence verdict points at the same hypothesis *name* (normalized lowercase). Measures "did the agent converge on the same mechanism?" |
| **Fix-files Jaccard** | Mean pairwise Jaccard on `files_changed` across repeats. Only meaningful when a fix is applied. |
| **Metric-Δ recorded fraction** | Fraction of repeats that emitted any `metric_delta`. A `tabm`-style clean paper should be near 0; a buggy paper should be near 1. |
| **Metric-Δ magnitude mean / sd** | Mean and sample SD of `|after - before|` for the first metric delta. Unit-free indicator of how much the fix moved the needle. |
| **Dossier completeness fraction** | Fraction of repeats that emitted all five canonical sections (*claim_tested, evidence_gathered, root_cause, fix_applied, remaining_uncertainty*). |
| **Validator overall mode** | Most-common `overall` label from the Validator subagent across repeats (`strong` / `acceptable` / `weak` / `unreliable`). |
| **Validator pass fraction** | Mean (#pass / 7) across repeats — independent second-opinion quality signal. |

### Why we didn't add

- **Bootstrap CIs.** With N=3 repeats per cell, bootstrap CIs on a mean or
  Jaccard are noisier than the point estimate itself. Reported κ and
  Jaccard are already robust enough for the scale we can afford.
- **Cohen's h / φ coefficients.** Useful only for 2×2 contingency tables;
  our verdict space is 3-way.
- **Ground-truth accuracy.** These two papers don't have universally agreed
  ground truth for "is this reproducible or not." The canonical-ground-truth
  fixtures (Muchlinski, ISIC) live under `test_data/ground_truth/` and are
  graded separately. Here we measure **consistency**, not correctness.

---

## How to reproduce

```bash
# 1. Configure API key (same one used by the server)
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env

# 2. Run the benchmark (3 repeats × 2 papers × (QCs + 1 Deep each))
uv run python benchmark/scripts/run_benchmark.py          # ≈ $15-20, ≈ 25 min

# 3. Validator subagent on every Deep run
uv run python benchmark/scripts/validate_runs.py          # ≈ $1

# 4. Compute metrics + render report
uv run python benchmark/scripts/analyze_consistency.py
uv run python benchmark/scripts/make_report.py

# Open the report
open benchmark/results/SUMMARY.md
```

Flags:

- `--smoke` — tabm only, 1 repeat (≈$3). Validates the pipeline without
  committing to a full budget.
- `--paper gidd` / `--paper tabm` — restrict to one paper.
- `--mode check` / `--mode investigate` — restrict to one mode.
- `--dry-run` — list scheduled tasks without any API calls.
- `--force` — re-run already-completed tasks (overwrites artifacts).

### Budget guard

`run_benchmark.py` enforces a `TOTAL_BUDGET_USD = 45.0` hard cap, computed by
summing persisted `run_meta.json:cost_usd` across all runs on every new task.
If the next task would push total spend above the cap, the runner stops
gracefully.

### Resumability

Every run's artifacts live in a dedicated directory. A task is considered
done when `reached_session_end=true` is persisted in `run_meta.json`. Re-
invocations skip done tasks by default. Interrupted or crashed runs are
retried.

### Isolation

- Quick Check repeats share one read-only clone of the target repo (tools
  are `Read`, `Grep`, `Glob` only — no mutation possible).
- Deep Investigation repeats each get a fresh shallow clone
  (`/tmp/bench-<paper>-deep-<repeat_idx>`) so applied fixes from one run
  can't contaminate the starting state of another. `git diff` post-run
  within each clone surfaces the agent's edits for the Validator.

---

## Results

See [`results/SUMMARY.md`](results/SUMMARY.md) for the per-group tables and
headline aggregates. The full machine-readable payload — every metric in the
schema — is in [`results/consistency.json`](results/consistency.json).

Once results are in, a short interpretation lives in
[`results/FINDINGS.md`](results/FINDINGS.md) (written by hand, not auto-
generated).

---

## Caveats & honest limitations

- **N=3 repeats per cell.** Enough to *detect* gross inconsistency but
  not enough to estimate fine-grained variance. 5 repeats would be better;
  10 would be ideal. We chose 3 under a finite API-credit budget.
- **LLM outputs are non-deterministic.** Even at temperature 0 the Claude
  API admits small variation across calls. Phrasing drift in `notes` or
  `evidence[].snippet` is expected and doesn't count against consistency;
  the metrics above focus on *decision-relevant* fields that should be
  stable.
- **Validator is itself a Claude call.** The second opinion isn't
  independent in the hardest sense (same model family, same provider). It
  is independent of the investigator's conversation and prompts, which is
  the non-trivial discipline. We treat validator scores as a quality
  co-signal, not ground truth.
- **Two papers is a small sample.** This is a consistency audit, not a
  generalization claim. For broader-generalization evidence see the
  robustness probes in `test_data/real_papers/`, covering four papers
  (fed, tabm, gidd, byprot) with single-pass Quick Check coverage.
- **`auto_pr=False` everywhere.** We never open a pull request during the
  benchmark — we don't own these repos and won't spam the authors. The
  agent still *applies* the fix locally on Deep runs, so the metric delta
  (where applicable) reflects a real eval re-run.
- **Cost caps are real.** The `max_budget_usd=2.50` cap per Deep run will
  occasionally truncate a run before the agent reaches a verdict. These
  show up as `stop_reason` ∈ {`turn_cap`, `budget_cap`} and are included
  in consistency as honest failure modes, not excluded.

---

## What the scientific community should walk away with

If the aggregates say:

- Verdict agreement ≥ 0.8 on Quick Check → the agent's single-verdict
  answers are stable enough to quote.
- Fleiss' κ ≥ 0.6 on Quick Check verdicts → that stability is beyond
  chance-level.
- Evidence Jaccard ≥ 0.7 → the agent's citations point at the same code
  locations across runs — so when it says *"line 47 of `prepare_data.py`"*
  you can trust that the next run will point there too.
- Top-hypothesis agreement ≥ 0.67 on Deep → the investigation converges
  on the same mechanism.
- Validator pass fraction ≥ 0.6 on Deep → an independent grader agrees
  the reasoning holds up.

If any of these fall below their thresholds, the report says so openly and
the raw artifacts in `runs/` are available to audit why.
