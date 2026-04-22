# Paper Trail (Reproducibility Forensics)

> **A verification intern for research engineers.** Paste a paper + a GitHub repo. Ask a quick verification question — *"does this split respect patient boundaries?"* — or launch a full investigation — *"why doesn't this paper reproduce?"*. Get back evidence-backed answers, and when the fix is clear, a real GitHub PR with a scientific audit dossier and an independent peer-review pass.

Built for the **"Built with Opus 4.7" Claude Code hackathon** (Cerebral Valley, Apr 21–26, 2026).

---

## Why this exists

A huge amount of ML research breaks at the same point: a paper claim exists, the public repo is incomplete or drifted, and nobody can quickly tell whether the gap is in the code, the data, the config, or the paper's prose. Time and GPU hours die there, and the scientific record loses credibility.

**Paper Trail** is a Claude Code agent that does what senior research engineers usually delegate to PhD students: read the paper, read the repo, form ranked hypotheses about why the numbers don't match, design and run small discriminating checks, and — when the root cause is clear — write the minimal fix and produce a reviewable audit trail.

---

## Two modes, one composer

### Deep Investigation

Paste a paper URL + a repo (GitHub URL, `owner/repo` slug, or local path — the backend auto-clones). The chat shows four live blocks:

- **Hypothesis Board** — ranked candidate failure causes with animated confidence bars
- **Tool Stream** — every file read, grep, script run, and diff check as it happens
- **Metric Delta** — before/after from the re-run eval with Δ chip
- **Dossier** — evidence report in five fixed sections (*Claim tested · Evidence gathered · Root cause · Fix applied · Remaining uncertainty*)

Above the footer, a **phase timeline** shows where the wall-clock time went (*paper ingest · hypotheses · checks · verify · dossier · pr*). When the agent converges, it writes the fix, re-runs the eval, and opens a real GitHub PR. The PR body is the dossier.

### Quick Check

A bounded agent pass (≤8 turns, ≤60 s, ≤$1). Type a question, get a **`confirmed` / `refuted` / `unclear`** verdict with file:line citations. Three prefilled suggestion chips cover the most common research-engineer questions; free text supported.

### Validator — second-opinion pass

After any Deep Investigation, click **"Run validator"**. A fresh Opus 4.7 agent grades the run on 7 checks (hypothesis coverage, evidence quality, fix minimality, causal link, alternative explanations, uncertainty honesty, suggested follow-up) and produces an overall `strong / acceptable / weak / unreliable`. The report shows up in the UI, is persisted with the run, and ships in the PR body.

---

## Demo

Curated demo repos are live on the bot account — no pre-cloning required:

- **`e-biswas/reproforensics-muchlinski-demo`** — Muchlinski 2016 "Random Forest vs Logistic Regression for Civil War Prediction." Classic imputation-before-split leakage. When fixed, RF AUC drops 0.9562 → 0.9070 and LR drops 0.8091 → 0.6962 — the paper's central claim (*RF ≫ LR*) evaporates.
- **`e-biswas/reproforensics-isic-demo`** — ISIC 2020 Melanoma Classification with 525 duplicate images crossing train/test. AUC 0.7153 → 0.6522 after dedup.

Two real PRs already live on those repos (see [muchlinski #1](https://github.com/e-biswas/reproforensics-muchlinski-demo/pull/1) and [isic #1](https://github.com/e-biswas/reproforensics-isic-demo/pull/1)) from past Deep Investigation runs.

---

## Stack

- **Agent core:** [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview) (Python). Model selector exposes Opus 4.7 (default), Sonnet 4.6, Haiku 4.5.
- **Specialized subagents:** Paper Reader, Code Auditor, Experiment Runner, Validator
- **GitHub PR creation:** [`@modelcontextprotocol/server-github`](https://github.com/modelcontextprotocol/servers) via MCP
- **Backend:** FastAPI + WebSocket streaming + shallow-clone repo cache
- **Frontend:** React + Vite + TypeScript + Tailwind
- **Python package manager:** [`uv`](https://docs.astral.sh/uv/)

---

## Quickstart

```bash
# 1) Dependencies
uv sync
npm --prefix web install

# 2) Environment
cp .env.example .env
# fill: ANTHROPIC_API_KEY, GITHUB_TOKEN, GITHUB_BOT_OWNER, GITHUB_BOT_REPO

# 3) Run (starts FastAPI on :8080 and Vite on :5173)
./dev.sh

# 4) Open http://localhost:5173
```

In the composer:

1. Click the sliders icon → paste `e-biswas/reproforensics-muchlinski-demo` into the Repo field → Attach.
2. Switch mode to Deep Investigation.
3. Type: *"Investigate why this paper's RF > LR claim doesn't reproduce."*
4. Watch the Hypothesis Board, Tool Stream, and Dossier fill in.
5. Click the PR card when it appears.
6. Click **Run validator** to get the second-opinion audit.

For Quick Check: same setup, just keep the mode chip on Quick Check and type a targeted question like *"Is imputation fit only on training data?"*.

---

## Project documentation

| If you want to... | Read |
|---|---|
| Hear the story of how this was built with Opus 4.7 | [BUILD.md](BUILD.md) |
| Understand the project and rules | [CLAUDE.md](CLAUDE.md) |
| See what's done / in progress | [TASKS.md](TASKS.md) |
| Understand the backend ↔ frontend wire format | [docs/integration.md](docs/integration.md) |
| See the submission narrative and roadmap | [docs/pitch.md](docs/pitch.md) |
| Read the judge-facing validity defense (7 layers) | [docs/validity.md](docs/validity.md) |
| Dig into backend modules | [docs/backend/README.md](docs/backend/README.md) |
| Dig into frontend modules | [docs/frontend/README.md](docs/frontend/README.md) |
| Build journals | [diary/claude.md](diary/claude.md), [diary/eb.md](diary/eb.md) |

---

## What's in the repo

```
paper-trail/
├── server/           # Python: FastAPI app, agent orchestrator, subagents, MCP config
├── web/              # React + Vite dashboard
├── demo/             # Staged primary (Muchlinski) + backup (ISIC) fixtures
├── test_data/        # Real-paper probes (FED/TabM/GIDD/ByProt), parser + ground-truth fixtures
├── tests/            # Smoke tests + programmatic evidence audit
└── docs/             # Integration contract, pitch, validity defense, module plans
```

---

## Future vision (not in MVP)

The hackathon MVP is deliberately small — 6 failure classes, two curated demos, two modes. Beyond the week:

- **CI for scientific claims.** A GitHub App that audits reproducibility on every commit.
- **Heavy-compute Deep Investigation.** MVP runs small cheap checks; full product orchestrates multi-GPU replication on Modal / Coreweave.
- **Organization-wide verification intern.** Quick Check across a lab's entire repo fleet.
- **Benchmark integrity surface.** Continuous audit of the top-cited public ML repos; published reproducibility grade per paper.
- **Per-domain Claude skill packs.** Medical imaging, NLP, RL — each with its own curated failure taxonomy.

See [docs/pitch.md](docs/pitch.md) for the full roadmap.

---

## License

TBD. Code and dossiers produced during the hackathon are shared with Anthropic and Cerebral Valley for judging purposes.
