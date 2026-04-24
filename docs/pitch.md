# Paper Trail — a verification intern for scientific code

*Built with Claude Opus 4.7 for Cerebral Valley's hackathon. April 21–24, 2026.*

---

## The moment

A 2016 civil-war-prediction paper says Random Forest significantly beats Logistic Regression on imbalanced panel data.

We pointed Paper Trail at the public repo and asked, *"Why doesn't this paper reproduce?"*

134 seconds later: five ranked hypotheses, the root cause traced to imputation fit on the full dataframe before the train/test split, the fix written, the eval re-run. **LR AUC dropped 11 points. The paper's central claim vanished.** The agent opened a GitHub PR with the diff and a five-section scientific dossier. An independent second Opus pass graded it `acceptable` with two honest warnings.

One paper. One question. One reproducible diff. [PR #1](https://github.com/e-biswas/reproforensics-muchlinski-demo/pull/1).

This is what Paper Trail does.

---

## The problem

Machine-learning research breaks at the same point over and over. A paper claims something. The public repo is close but drifted — preprocessing differs, the split is wrong, a metric is misused, a hidden default matters. Nobody can tell in under a day whether the gap is in the code, the data, the config, or the paper's prose. Engineering time, GPU hours, and scientific trust die there.

<!--
  Optional: if you want to add 2–3 sentences on why this problem matters to
  *you* specifically (a bug that cost you a thesis chapter, a team you watched
  lose weeks, etc.), the best home for that paragraph is right here — between
  the general problem statement above and the "PhD delegation" metaphor below.
  Keep it in your own voice; the rest of the pitch is deliberately impersonal
  so a personal line lands harder. If nothing honest fits, skip it — forced
  authenticity reads worse than none.
-->

Research labs handle this today by delegating grunt work to PhD students:

> *"Is the imputation fit on train only?"*
> *"Is this split patient-level or image-level?"*
> *"Do any rows appear in both train and test?"*

Senior engineers spend their time formulating the question. Juniors spend theirs grepping code for the answer. The result is the most expensive grep in science.

**We rebuilt that delegation loop as a Claude Code agent.**

---

## What Paper Trail is

One chat UI. One composer at the bottom, in the style Claude Code users already know. Paste a repo. Pick a mode. Send.

**Quick Check — the daily-use verification intern.** ≤15 turns, ≤60 seconds, ≤$1. Type a question, get a `confirmed` / `refuted` / `unclear` verdict with file:line evidence. This is what researchers reach for *instead of* bothering a teammate.

**Deep Investigation — the scientific debugger.** A full agent loop: generate ranked hypotheses → run discriminating checks via tool use → converge on a root cause → write the minimal fix → re-run the eval → open a real GitHub PR whose body *is* the audit dossier. Every step streams into the UI as it happens. The agent shows its work.

**Validator — a built-in peer-review pass.** One click spawns a separate Opus 4.7 agent with a narrow peer-review prompt. Seven checks — hypothesis coverage, evidence quality, fix minimality, causal link, alternative explanations, uncertainty honesty, suggested follow-up. Each returns `pass` / `warn` / `fail` with a citation-bearing note. The rollup is mechanically mapped, not model-picked. A single agent calling itself correct is unconvincing. A second agent audit is closer to how researchers actually review each other's work.

---

## Demo narrative (4 acts, ~4 min)

### Act 1 — Setup (20 s)

*"I'm a research engineer. My team cited Muchlinski 2016 on civil-war prediction. Numbers don't match. Let me load it."*

Paste `e-biswas/reproforensics-muchlinski-demo`. Status pill: *✓ cloned · branch: main*. Zero manual setup.

### Act 2 — Quick Check warmup (30 s)

Mode: Quick Check. *"Is the imputation fit on the full dataset or just on training?"*

Two tool calls. ~12 seconds. $0.08.

> **REFUTED** · 0.94
> Imputer.fit() runs on the full dataframe at `src/prepare_data.py:47`, before the split at line 63. This is data leakage.

### Act 3 — Deep Investigation (2 min)

Mode: Deep Investigation. *"Investigate the full repo."*

- **Hypothesis Board** fills within 20 s: five ranked candidates drawn from the failure taxonomy. Imputation-before-split leads at 0.55.
- **Tool Stream** streams real file reads, greps for `fit(`, scans the eval script. Live. Every call visible.
- A finding confirms the leakage; `h1` confidence jumps to 0.95.
- **Phase timeline:** *paper 0.02 s · hypotheses 49 s · checks 20 s · verify 30 s · dossier 29 ms*.
- Agent writes the fix (moves imputation into an sklearn `Pipeline`). Re-runs the eval.
- **Metric delta:** RF AUC 0.9562 → 0.9070 (−0.0492). LR 0.8091 → 0.6962 (**−0.1129**). The paper's central claim that RF beats LR evaporates.
- Dossier fills section by section. *Remaining uncertainty* honestly flags one preprocessing detail the agent couldn't verify from the paper's prose.

### Act 4 — The artifact + the audit (30 s)

A **PR card** appears. Click it. Judges see a real pull request on the bot's fork: 34 lines changed, one file, a reviewable scientific dossier as the PR body. Shareable. Mergeable.

Back in the UI: **Run validator**. Ten seconds later, a peer-review block renders below the PR card. Overall `acceptable`. Seven checks with citation-bearing notes. *"Causal link — warn — metric delta plausible but no bootstrap CI reported."* The validator didn't rubber-stamp.

### Act 5 (optional, 30 s) — Generalization

*"And medical AI too — ISIC 2020 melanoma. Same agent, different bug class: 525 duplicate images cross train/test. AUC 0.7153 → 0.6522 after dedup."* [PR #1](https://github.com/e-biswas/reproforensics-isic-demo/pull/1).

---

## Evidence beyond the demos

Judges, reach for any of these. No demo-day special staging.

### Two real GitHub PRs

Clickable. Diffs apply cleanly.
- [reproforensics-muchlinski-demo #1](https://github.com/e-biswas/reproforensics-muchlinski-demo/pull/1)
- [reproforensics-isic-demo #1](https://github.com/e-biswas/reproforensics-isic-demo/pull/1)

### 16 Quick Checks across 4 unseen real papers, zero crashes

| Probe | Domain | Qs | Cost | Notable finding |
|---|---|---:|---:|---|
| FED | NLP dialog eval | 3 | $0.18 | Flagged `DialoGPT-large` loaded from unpinned `from_pretrained` hub URL |
| TabM | tabular ML (ICLR 2025, clean) | 3 | $0.29 | Correctly reported *no* leakage with evidence — didn't reach for a bug to look smart |
| GIDD | diffusion LMs (arXiv 2512, post-training-cutoff) | 5 | $0.60 | Correctly distinguished JAX training from PyTorch inference; found exact config knobs for paper's central claim |
| ByProt | protein LMs (comp-bio) | 5 | $0.58 | Flagged ESM weights loaded from unpinned Facebook hub URL — **same structural bug class as FED, completely different domain** |

The last row is the memorable one. *The agent independently identified the same structural risk — unpinned pretrained weights → silent drift — on two unrelated repos without being told to look for it.* The word "unpinned" appears nowhere in our prompts. That's evidence the system generalizes structural reasoning, not keyword matching.

### Programmatic evidence audit

`tests/audit_byprot_run.py` walks every cited evidence entry in a saved run and verifies the cited file exists, locates the snippet within ±5 lines, and checks the verdict label is consistent with the notes. Result on ByProt: **22 / 22 cited files exist. 22 / 22 snippets located. 5 / 5 verdict↔notes pairs consistent. Zero hallucinations.** Runs in under a second, no API calls. Judges can run it themselves.

### Negative controls

TabM is a clean ICLR 2025 paper. We asked three questions and the agent gave three honest answers: one `refuted` (flagging that no bug was found, with citations), one `confirmed` of the clean behavior, one `unclear` hedge. **Zero false alarms.** That's the behavior that lets judges trust a `confirmed` or a `refuted` elsewhere.

### Ground-truth fixtures

Acceptance criteria pinned in `test_data/ground_truth/*.json`. Before/after numbers reproducible on a laptop in under two minutes.

### Consistency benchmark — 30 runs, reproducible from the repo

We ran the agent **3 times** on each of 2 unseen recent papers (`tabm`, ICLR 2025; `gidd`, arXiv Dec 2025) across Quick Check + a professor-style Deep Investigation — 30 runs, $13.49 total, zero crashes. Findings:

- Quick Check verdict agreement **78–80 %** across repeats; Fleiss' κ 0.29–0.44 (fair-to-moderate agreement *beyond chance*).
- Deep Investigation conclusion agreement **100 %** on both papers — 3/3 runs unanimously classified `no_actionable_bug`, the correct answer in both cases.
- Independent Opus Validator graded the Deep runs `strong` (tabm) / `acceptable` (gidd) with **67–86 %** of 7 quality checks passing.
- On the clean baseline (tabm), the agent **did not hallucinate a bug** across 3 independent Deep runs given a professor-style prompt pushing on 4 specific axes.

Full methodology, per-question tables, and honest caveats in [`benchmark/README.md`](../benchmark/README.md) + [`benchmark/results/FINDINGS.md`](../benchmark/results/FINDINGS.md). Raw per-run dossiers + validator scores under `benchmark/runs/` for anyone who wants to audit a single datapoint.

Full details in [`docs/validity.md`](validity.md).

---

## What we don't claim (yet)

We'd rather be trusted than oversold, so:

- **It doesn't run the paper's full training.** Not locally, not in this hackathon. Paper Trail runs small discriminating checks — enough to find the bug, not enough to *replicate the entire paper's compute budget*. The heavy-compute version is roadmap.
- **It needs a reviewable code surface.** Closed-source repos, Jupyter-notebook-only research, or binary-blob pipelines don't work yet. Static Python + a runnable eval script is the sweet spot.
- **Quick Check generalizes; Deep Investigation is best on supported failure classes.** Six are covered with taxonomy-grade confidence: imputation-before-split, target-leakage-via-imputer, patient-level splits, duplicate rows, temporal leakage, unpinned pretrained weights. Novel failure modes *can* be found — but without prior taxonomy the agent leans more exploratory.
- **The Validator reduces over-confidence; it doesn't eliminate it.** We tuned it fair-not-doomer. It catches rubber-stamping but isn't a formal proof of correctness.
- **It's one contributor's four days.** A real product would deserve a team, real integration tests against novel failure classes, and a compliance review. This is a working prototype that passes a 7-layer validity defense — not a shipped enterprise product.

---

## Where this goes next

The MVP is deliberately small — six failure classes, two curated demos, four subagents. The roadmap is the ambitious part.

### CI for scientific claims

A GitHub App that installs on any ML repo. Every commit to `main` triggers a reproducibility audit. Regressions block merge. Audit dossiers post as check-runs. *Lint for scientific integrity.*

### Heavy-compute Deep Investigation

MVP runs tiny checks in under two minutes. The full product orchestrates multi-GPU replication on Modal / Lambda / Coreweave to verify paper claims *at scale* — running the paper's actual eval on the claimed dataset and reporting the verdict with bootstrapped confidence intervals.

### Organization-wide verification intern

Quick Check across an entire lab's or company's repo fleet. *"Scan every repo in our org for patient-level leakage. Audit every repo for test-set contamination against our new benchmark."* Compliance-grade auditing for AI organizations.

### Benchmark integrity surface

A continuous audit of the top-cited public ML benchmarks and their reference implementations. Published reproducibility grade per paper — browseable by anyone. *A Wikipedia-for-claims.*

### Per-domain skill packs

Medical imaging, NLP, RL, time-series, fairness, protein modeling — each with a curated failure taxonomy authored by domain experts, shipped as Claude skill/subagent packs. Plug in when you work in that domain.

---

## Open by default — how to help

Paper Trail is **open source from day one**. The agent prompts are in the repo, the failure taxonomy is in the repo, the validator is in the repo, the evidence audit is in the repo. Clone it, run it on your repo, tell us when it's wrong.

The ways this gets better fastest:

- **Add a failure class.** If you know a reproducibility bug pattern our taxonomy doesn't cover (e.g. *batch-norm state leaked across folds*, *tokenizer version drift*, *random-seed API deprecation*), a pull request to `server/prompts/failure_classes.md` with one grep signature + one discriminating check is everything we need.
- **Add a domain probe.** Run Paper Trail on a paper/repo from your field. Drop the results into `test_data/real_papers/<your-domain>/`. Even a single probe doubles our domain coverage.
- **Write a negative control.** Clean repos where the agent *should* say "nothing is wrong" are more valuable than catching bugs. False-positive rate is the reviewer-trust metric.
- **Translate a domain-expert voice into a skill pack.** If you run a medical-imaging lab, a fairness-audit team, a benchmarks group — your failure taxonomy is gold.

---

## Talk to us

We know you're out there: AI-safety orgs, reproducibility groups at Princeton / Stanford / Allen / EleutherAI, compute providers watching GPU hours die to *"my baseline regressed,"* regulated-AI startups who need audit logs for FDA or EU AI Act compliance, journal publishers who want reproducibility signals attached to submissions.

The ambition is **CI for scientific claims**, and it deserves real investment — money, integrations, hiring around it, or all three.

If any of that resonates, the repo is the conversation starter. Open an issue labeled `let's-talk` and we'll route it fast. Anthropic teams — DM us; we'd love to see where this fits inside the Claude Code + skills ecosystem.

This hackathon entry is the seed. The tree is a year of work. **We're interested in both.**

---

## What we built

- Python backend on Claude Agent SDK + FastAPI + WebSockets, live-streaming envelopes.
- React + Vite + TypeScript + Tailwind chat UI with phase timeline, animated event replay, pinned sessions, model selector.
- Two agent modes (Quick Check / Deep Investigation), four specialized subagents (Paper Reader, Code Auditor, Experiment Runner, Validator), one shared tool set.
- One-field repo attach: GitHub URL / slug / local path → auto-cloned + slug-resolved in ≤3 seconds.
- Persisted run store with event logs + artifact builders (`dossier.md`, `diff.patch`, `events.jsonl`, `paper.md`).
- Two curated fixtures (Muchlinski + ISIC) with pre-documented bugs and ground-truth acceptance criteria.
- Four unseen-paper domain probes (FED / TabM / GIDD / ByProt) totaling 16 Quick Checks at $1.65.
- Two real GitHub PRs opened end-to-end.
- 22 / 22 programmatic evidence audit pass, 7-layer validity defense document.
- A rebuilt build-story README ([`BUILD.md`](../BUILD.md)) sourced from two human + AI daily journals.

All solo, in four days, using the hackathon's own product — Claude Code — to build it.

---

## Credits and references

- Kapoor, S. & Narayanan, A. (2023). *Leakage and the Reproducibility Crisis in Machine-Learning-Based Science.* Patterns. — Source of the failure taxonomy.
- Muchlinski, D. et al. (2016). *Comparing Random Forest with Logistic Regression for Predicting Class-Imbalanced Civil War Onset Data.* Political Analysis. — Primary demo fixture.
- SIIM-ISIC 2020 Melanoma Classification Challenge. — Backup demo fixture.
- Hermann et al. (2024). *Beware of Data Leakage from Protein LLM Pretraining.* bioRxiv. — Comp-bio domain probe.
- Anthropic Claude Opus 4.7 / Sonnet 4.6 / Haiku 4.5 and the Claude Agent SDK.
- Cerebral Valley Built-with-Opus-4.7 hackathon for the week.
