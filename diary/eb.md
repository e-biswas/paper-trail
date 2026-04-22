# Developer's Diary

Running log of decisions made during the build. Seeded by Claude from the conversation; the developer (handle: `eb`) annotates as entries are added.

If something here doesn't match what you remember, edit it — this is your journal.

---

## 2026-04-21 — Joined the hackathon

Got accepted to the Built-with-Opus-4.7 Claude Code hackathon (Apr 21–26). I had five candidate project ideas pre-written in [`ideas.md`](../ideas.md), with my own ranking memo at the top. Wanted a second opinion from Claude before committing.

## 2026-04-21 — Picked the project

Claude agreed with my ranking — **Paper Trail** was the strongest of the five. Claude also flagged something I hadn't weighted: past winners of this hackathon were almost all vertical-domain tools (housing permits, healthcare, Uganda road infrastructure, music, education), not developer/ML-research tools. Suggested I verticalize by scoping to medical AI papers.

I chose to stay general but use medical AI as the showcase demo. Reason: I want the product to be defensibly broad (ML research in general), and the demo to be specific enough to land. Verticalizing the product would be a different pitch.

## 2026-04-21 — The verification-intern framing

I reframed the product from "one-shot autonomous investigator" to "verification intern." The core insight: research labs already have a workflow for this — senior engineers delegate verification questions to PhD students all day. Claude's Deep Investigation flow is one half of the story; the other half is a fast Quick Check mode for ad-hoc questions.

This made the pitch noticeably stronger. Deep Investigation is a one-shot demo beat; Quick Check is what the product actually is in someone's workflow.

## 2026-04-21 — Documentation first

Insisted on a full docs layer before any code. Root-level README + CLAUDE.md + TASKS.md. `docs/integration.md` as the event contract between backend and frontend. Per-module plans under `docs/backend/` and `docs/frontend/`. Every module doc has a mandatory "How to verify (end-to-end)" section.

The rule: test every functionality end-to-end the moment it's written. No "I wrote it, moving on." Produce test data, execute, verify actual vs expected. If off, fix before continuing.

## 2026-04-21 — Synthetic fixture iteration

Needed demo datasets that (a) were runnable in under 2 minutes on a laptop, (b) showed a dramatic metric delta when the bug was fixed. Went through several iterations on the Muchlinski fixture — first attempts had RF ≈ LR in both broken and fixed states (bug was real but not dramatic). Landed on a compound leakage bug + linear DGP + MNAR missingness that gives RF 0.9562 → 0.9070 and LR 0.8091 → 0.6962. The 11-point LR drop is the demo moment.

ISIC backup fixture came together faster: synthetic metadata with injected duplicates, AUC 0.7153 → 0.6522 after dedup.

Both fixtures verified end-to-end (broken + manual-fix) before moving on.

## 2026-04-21 — Pre-implementation scope refinement

Pushed Claude on a few things before we started coding:

1. Should the system be multi-agent? Claude warned this is a trap at hackathon scale and recommended SDK subagents instead. I agreed.
2. Should we run code in a real sandbox? Yes, but I can't afford cloud services this week. We're going local-only, with a `Sandbox` interface that leaves room for `E2BSandbox` later.
3. Should judges be able to paste any paper? Yes — Quick Check will work on anything, Deep Investigation is "best-effort with honest confidence" on non-curated inputs. arXiv API for arXiv URLs, docling for arbitrary PDFs.

## 2026-04-21 — Starting the diary

Asked for this journal so future Claude Code users can see what the actual build looked like — including the iteration, the pushbacks, the places where either of us was uncertain. Keeping it concise. Updating as we go.

## 2026-04-21 — Day 1 done

Backend structural backbone is live: uv-managed Python project, FastAPI app with two WebSocket endpoints, a proper `LocalSandbox` with path confinement + timeout + output cap + env scrubbing, a markdown-section parser, and a run orchestrator wired to the Claude Agent SDK (stub fallback when no API key is present so we can develop the frontend without burning credits).

36 unit tests passing across parser and sandbox. End-to-end WebSocket smoke test passing — both modes round-trip 5 envelopes with monotone sequencing; bad configs surface proper `error` envelopes.

Told Claude to use best-practice tooling and guarantee reproducibility. Landed on: official `uv` standalone installer (not `pip install uv`), `pyproject.toml` with pinned major versions, `.python-version` so any clean checkout pulls Python 3.11 via uv, `.gitignore` scrubbed for secrets and caches.

Deferred to Day 2 (with a note in TASKS.md): paper ingester, subagents, real system prompts, and the `include_partial_messages=True` SDK streaming check that needs a live API key.

## 2026-04-22 — Day 2 done: full agent pipeline, two live PRs

Put Claude on auto mode for Day 2. Started the day with only a skeleton; ended with a fully-working Paper Trail agent that:

- Ingests any arXiv paper or PDF (via `arxiv` + `docling`, cached on disk)
- Drives a conductor agent with a taxonomy-aware investigator prompt
- Delegates to three specialized subagents (paper reader, code auditor, experiment runner)
- Parses the conductor's output live into structured envelope events
- Opens a real GitHub PR at the end of a successful Deep Investigation

Two real PRs are now live on my bot repos, with full 5-section scientific dossiers in the PR bodies:

- [reproforensics-muchlinski-demo/pull/1](https://github.com/e-biswas/reproforensics-muchlinski-demo/pull/1)
- [reproforensics-isic-demo/pull/1](https://github.com/e-biswas/reproforensics-isic-demo/pull/1)

Numbers:

| Run | Duration | Cost | Verdict conf | Metric move |
|---|---|---|---|---|
| Muchlinski Deep | 134 s | $0.74 | 0.98 | LR AUC 0.81 → 0.70 (−0.11) |
| Muchlinski Quick Check ×3 | <22 s each | $0.23 total | — | — |
| ISIC Deep | 142 s | $0.68 | 0.97 | AUC 0.72 → 0.65 (−0.06) |

Day-2 total API spend: ≈$2. Per-run caps held at $5.

One thing I'd call out for other Claude Code users reading the diary: the discipline of building the test data **before** the agent paid off enormously. Every subagent had a concrete fixture to be measured against from minute one — the "does it find the right bug?" question had a ground-truth answer the whole time. No hand-waving.

Also the pushbacks from Claude during scope refinement (no multi-agent, no cloud spend, subagents via SDK `Task` instead of a message bus) were the right call. Kept the surface small enough to actually finish.

Frontend + demo polish tomorrow.

## 2026-04-22 — Real-world robustness probe before the frontend

Before touching the frontend, asked Claude to find two new arXiv papers + public repos it had never seen and stress-test the backend. Picked pair (via an Explore subagent):

1. **FED / DialoGPT dialog evaluation** (arXiv 2006.12719) — has a documented reproducibility issue on GitHub.
2. **TabM / Yandex Research** (arXiv 2410.24210) — ICLR 2025, zero open issues.

Both papers ingested cleanly (FED: 47K chars / 24 sections; TabM: 221K chars / 66 sections; docling was slow on TabM but the cache now makes repeat ingests instant).

Ran 3 Quick Checks on each repo. All 6 produced cited verdicts, no crashes, reasonable turn counts (1–5 tool calls per check), $0.52 total. The standout: on the FED repo, the agent spotted that `microsoft/DialoGPT-large` is pulled via `from_pretrained` with no revision pin — which is the actual mechanism behind the documented "can't reproduce" issue. It found that without being told to look for it.

On TabM it correctly said *"no leakage, preprocessing fits on train only"* with file:line citations. No hallucinated bugs to look clever.

Safety note: I deliberately did NOT run Deep Investigation on external repos — only Quick Check in read-only mode. Never want the agent editing someone else's code during testing.

Feeling confident moving to the frontend now. The backend works on unscripted inputs.

## 2026-04-22 — One more: the hard 2025 paper

Before letting Claude move on, I asked for one more target — something recent enough Claude doesn't know, resource-intensive enough that we can't actually reproduce it. Claude picked **GIDD — Scaling Behavior of Discrete Diffusion Language Models** (arXiv 2512.10858, Dec 2025), which trains a 10B-param diffusion LM at 10²² FLOPs on TPU. Not locally runnable.

Paper ingested (101K chars, 27 sections, 20s). Repo cloned — 33 .py + 16 .ipynb, 30MB. I was braced for the notebook-heavy layout to choke the agent's Read tool. It didn't.

5 Quick Checks, 5 verdicts, $0.60. Highlights:

- Correctly distinguished the **JAX/TPU training path** from the **PyTorch inference path** (modeling_gidd_hf.py). Not a binary "runnable / not runnable" answer — a nuanced one.
- Found the **exact config knobs** implementing the paper's main claim (`hybrid_mixing_scale` / `hybrid_mixing_shift` in `DiffusionConfig`). Parameter names I would have had to dig to know.
- Flagged that **no per-size hyperparameter sweeps exist** in the repo, even though the paper's scaling laws claim holds across 7 sizes. That's a legitimate reproducibility gap.

I asked Claude to save all the test data in detail so I can check it myself. Everything's at `test_data/real_papers/{fed,tabm,gidd}/` with the full paper markdown, the questions, and structured JSON summaries of every verdict + evidence list. Idempotent re-runs (paper cache is free, only Quick Checks cost API).

Cumulative robustness spend: ~$1.07 across 11 Quick Checks on 3 unseen targets. Zero crashes, zero hallucinated bugs. I'm calling the backend done.

## 2026-04-22 — Frontend done

Asked Claude to go for the frontend with creative license but ChatGPT-style minimalism. Also wanted it to think about how to show each agent's activity, let users save artifacts from the sandbox, and treat each chat turn as potentially producing a PR. Before building, Claude paused and walked me through the implications — especially that "chat turns share context" would mean real backend work (run persistence + session state + prompt splicing). Glad it checked; that would've bitten us later.

Backend additions landed first (right call):
- `server/runs.py` — every run persisted as a JSONL event log + meta.json
- `server/artifacts.py` — builders for dossier, diff, events, paper
- Artifact endpoints (`/runs/{id}/dossier.md` etc.)
- Session + usage endpoints
- Conversational memory spliced into the user prompt on follow-up turns

Then the frontend:
- Vite + React + TypeScript + Tailwind + Radix primitives (Claude skipped the shadcn CLI install in favor of hand-built wrappers — cleaner, fewer files)
- Chat shell: left sidebar for history + current-session runs, main thread, bottom input row with a `[Quick Check / Deep Investigation]` dropdown
- Assistant messages render collapsible inline blocks: paper claim preview → Hypothesis Board (animated confidence bars, status-colored borders, gold glow on verdict) → Tool Stream (expandable input/output per call) → Metric Delta (big numbers with Δ chips) → 5-section Dossier accordion → PR card with external-link animation
- Artifact download row on every run: dossier.md, diff.patch, events.jsonl, paper.md
- Cost meter per-run + sidebar showing session total + all-time total
- Empty-state with example prompts so judges know what to type

Tested end-to-end: TypeScript builds clean, production bundle 503 KB (156 KB gzipped), Vite proxy routes `/ws` + REST to backend correctly, a Quick Check driven through the proxy produced all expected envelopes and the artifact endpoints returned correct data. `./dev.sh` boots both servers with one command.

It looks good. Dark mode by default, Inter + JetBrains Mono, status colors discipline, motion only where it pays. Not perfect — I'll inspect more tomorrow and nitpick — but the first render is already presentable.

## 2026-04-22 — PDF upload + a comp-bio probe

Pushed Claude on two things: first, stop wasting cycles fighting Cloudflare — if a PDF is blocked, tell me and I'll drop it in the folder myself; second, we obviously need a way to attach a PDF through the UI for these cases. Also asked Claude to remember that my machine is a 16 GB M5 MacBook so it doesn't propose local fine-tuning or anything heavy.

Claude saved the machine specs to memory, added a `POST /papers/upload` backend endpoint, and a matching "Attach PDF" pill in the frontend's advanced config. Tested the upload both directions — happy path returns a local path that feeds the ingester, bad file types rejected with clean errors.

Then the new domain probe — comp-bio. Paper: Hermann et al. 2024 *"Beware of Data Leakage from Protein LLM Pretraining"* on bioRxiv (and in PMLR). bioRxiv is behind Cloudflare and blocked our fetcher; I downloaded the PDF into `test_data/real_papers/byprot/` and Claude ran the ingester against the local path. docling parsed it to 36 K chars in 8 seconds. Then 5 Quick Checks against BytedProtein/ByProt, a 74-file LM-Design repo integrating ESM2.

5/5 verdicts. $0.58. Best finding: on a protein-LM repo the agent has never seen, in a domain it has never been designed for, it flagged that ESM weights are fetched from an **unpinned** Facebook hub URL — the same structural reproducibility risk it caught on the FED dialog repo (unpinned `microsoft/DialoGPT-large`). Different field, same underlying pattern. That's the kind of cross-domain reasoning I wanted to see.

Also got a real validity-review guide added to `test_data/real_papers/README.md` — five concrete self-checks I can run to audit any of the saved probes without re-invoking the agent. Useful for the submission review and for anyone else trying to kick the tires on this system.

## 2026-04-22 — Added a Validator subagent

Thought researchers would really appreciate an adversarial second pass on the agent's own output — someone asking "did you actually back your claim?", "is this fix minimal?", "could something else explain the metric change?". Claude agreed and added a caveat: tune it to be fair, not a doomer, or it'll manufacture problems on clean repos.

Result: a 4th subagent (Validator) that runs on demand via a button after a Deep Investigation completes. 7 checks with pass/warn/fail marks, rolled up into a strong/acceptable/weak/unreliable verdict. Shows in the UI as a color-coded card and also appends to the PR body so anyone reading the GitHub PR sees the self-critique.

Cost: ~$0.04 per audit, 14 seconds. Cached after first call.

Tested it on a saved Deep run — the validator surfaced 2 real warns (no metric delta was produced, overlap not quantified) and proposed a specific next experiment (MMseqs2 mapping CATH chains to UniRef50 clusters). Concrete and actionable, not boilerplate.

This feels like the kind of feature researchers will actually notice. "The agent audits itself and shows you where the reasoning is weak" is a much stronger pitch than "the agent is always right."

## 2026-04-22 (morning) — UX refinement pass

Got the Validator subagent landed and then laid out a whole refinement wishlist: (1) runs saved locally + shown in a real history panel + clickable to reopen, (2) time metrics per phase, (3) "always completes" guarantee, (4) more live progress cues, (5) Claude-Code-style input box with the mode chip inside the box, (6) pin conversations, (7) model selector for Opus / Sonnet / Haiku. Asked Claude to summarize what's left and picked the recommended option on each clarifying question (animated replay; all three models; inline timings footer; backend-persisted pin). Auto mode from there.

End result after one evening: backend now has `/sessions`, `/sessions/{id}/pin`, `/sessions/{id}/title`; runs carry the chosen `model` through to `ClaudeAgentOptions`; phase events fire six-deep (paper_ingest → hypotheses → checks → verify → dossier → pr) and never re-open; every code path emits a terminal `session_end`. Frontend has the new composer (mine now feels a lot like Claude Code's box — grows upward, toolbar inside), a proper left-panel history grouped pinned-first, and clicking a past session replays its events through the reducer with a stagger so the hypothesis board / tool stream / dossier reconstruct visibly. The live phase pulses when running; timings strip renders as chips once done.

Verified with a Haiku 4.5 Deep Investigation on Muchlinski: $0.12, 108 s, all five phases registered with sane durations (hypotheses 49.5 s being the dominant term — that's where the LLM actually thinks). Meta.json now includes phase_timings so the sidebar summary has everything it needs in one fetch.

Remaining pre-submission: demo video, pitch polish, one dry run under timer. Scope freeze is Apr 24 EOD — plenty of runway.

## 2026-04-22 (afternoon) — Unified repo attach

Pointed at a screenshot where the config drawer looked like it had lost two fields. Turned out those only appear in Deep Investigation mode (Quick Check doesn't need paper URL or PR target). But the right move fell out of that: the three-field flow was hostile to the core demo — "paste a paper + a repo, get a PR". Asked Claude to make attaching a repo feel as light as the rest of the flow.

Claude shipped `POST /repos/attach` — takes a GitHub URL, `owner/repo` slug, or local path and figures out the rest (shallow-clones to a cache dir, derives slug + default branch). Frontend: one "Repo" input with an Attach button and a green-check status pill. The old two-field form is gone. Also removed the duplicate Attach-PDF button from the drawer since the `+` icon in the composer toolbar already covers that.

Verified with `e-biswas/reproforensics-muchlinski-demo`: first Attach clones in ~3s, second returns from cache instantly. Quick Check on the cached clone found the split in 11s / $0.04. The demo is now properly "paste, ask, done" — no manual cloning, no slug typing.

## 2026-04-22 (evening) — Day 4: pitch + polish

Told Claude "next phase, auto mode" after the unified repo attach landed. Came back with a fully rewritten pitch.md and README that match the current shipped state (validator, attach, phase timeline, model selector, 16-check robustness probe, 22/22 evidence audit). The PR body template in the investigator prompt got a proper shape (TL;DR, metric deltas table, etc.) — that's a judge-visible artifact so worth the polish.

Dry run with Opus on the cached Muchlinski clone: 9.3s / $0.14, correct refuted verdict with citations. Clean. One thing surfaced: old Deep Investigation runs had the verdict text as the sidebar title because the user's prompt wasn't persisted server-side. Claude threaded a `user_prompt` field through the whole stack and fixed it.

Left for me: record the 4-act demo video, final dry run after the cut, submit to Cerebral Valley.
