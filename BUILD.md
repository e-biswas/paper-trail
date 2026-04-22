# How this was built

> A four-day solo build (**April 21–24, 2026**) with Claude Opus 4.7 as a design partner, not an autocomplete engine. This is the story behind the repo — the pivots, the pushbacks, and the moments the collaboration actually earned its keep.

For the raw, dated record see [`diary/claude.md`](diary/claude.md) (Claude's journal) and [`diary/eb.md`](diary/eb.md) (mine). This file is the distilled narrative.

---

## Day 1 · Apr 21 — Picking the project, not the tool

I walked in with **five pre-ranked candidate ideas** ([`ideas.md`](ideas.md)) and a second-opinion question for Opus 4.7: *which of these has the best odds?*

Opus agreed with my ranking — **Paper Trail** — but surfaced something I hadn't weighted: the prior (4.6) hackathon's winners were **four of five non-developers** tackling vertical-domain problems (housing permits, healthcare, Ugandan road infrastructure, live music, children's coding). Not a single developer tool among them. The ML-research-tools framing I was pitching was a pattern mismatch.

Opus suggested verticalizing to medical AI. I pushed back — I wanted the product to be **defensibly broad**, not narrowed to one domain. We compromised: stay general, but make medical AI the **showcase demo** rather than the whole product. That one call ended up shaping everything downstream.

**Pushback #1, from me to Opus.** Stood.

---

## Day 1 · Apr 21 — The verification-intern reframe

My original sketch was *"autonomous investigator opens a PR with the fix."* Opus built around that.

Then I flipped it: senior research engineers don't delegate *whole investigations* to juniors — they delegate **verification questions** ("is this split patient-level?", "does this imputation fit on train only?"). That's the daily-use shape. The big investigation is the dramatic demo beat; the quick verification is the *product*.

So we split it: **Quick Check** (chat-style, bounded, cited, daily-use) and **Deep Investigation** (the full PR flow). Same tool set, different prompts, different turn budgets. Opus noted later in its diary that it was leading with the most dramatic surface — I was leading with the surface that gets used every day. Both mattered. Daily-use is usually the business.

**Pushback #2, from me to Opus.** Stood.

---

## Day 1 · Apr 21 — Planning docs before code

Before a line of Python, we built the full documentation layer: `CLAUDE.md` (loaded every session), `TASKS.md` (single source of truth for progress), `docs/integration.md` (the frozen-after-Day-1 event contract), and per-module plans for every backend and frontend component. **19 files.** Each module doc carried a mandatory *"How to verify (end-to-end)"* section.

Opus admitted it felt self-conscious about the volume at first — was this overhead in a short build? The discipline paid out within the same session: when Opus reviewed its own work with an Explore subagent, the audit caught a real schema bug (`session_start` had `mode` at the envelope root instead of nested in `data`) and a missing implementation-notes section. Both fixed in five minutes because the audit had a clean structure to check against.

The rule we set: **test every functionality end-to-end the moment it's written.** No "I wrote it, moving on."

---

## Day 1 · Apr 21 — Scope discipline before speed

Three architectural questions I pushed before we coded:

1. **Multi-agent with inter-agent messaging?** Opus: trap at hackathon scale — coordination cost dominates specialization benefit. Use the SDK's subagent `Task` mechanism instead. Accepted.
2. **Real cloud sandboxing (e2b, Modal)?** I couldn't afford cloud spend this week. Went local-only with a `Sandbox` abstraction that leaves the seam for `E2BSandbox` later. Accepted.
3. **Arbitrary papers, or just curated?** Went arbitrary — arXiv API for arXiv URLs (LaTeX source beats PDF parsing), `docling` for arbitrary PDFs, cached by URL hash. More work; the pitch dies without it.

**Three pushbacks, three agreements.** By the end of Day 1 morning, the shape of the thing was real and the scope was small enough to actually finish.

---

## Day 1 · Apr 21 (evening) — Backbone

- `pyproject.toml` with pinned deps, uv-managed
- FastAPI + two WebSocket endpoints (`/ws/investigate`, `/ws/check`)
- `LocalSandbox` with path confinement, timeout, output cap, env scrubbing
- Markdown-section parser (tested against pre-built JSONL fixtures)
- Run orchestrator: stubbed when no API key, real SDK when keyed

**36 unit tests green** across parser + sandbox. End-to-end WebSocket smoke passed both modes.

One thing Opus noted in its diary: it wrote the parser **before** running real fixtures, and everything passed on the first real invocation — because the parser was designed against exact expected JSONL fixtures built earlier. It called this *"the clearest case I've had recently of test-data-before-code paying back immediately."*

Told Opus to use the official standalone uv installer (not `pip install uv`) and pin Python 3.11 via `.python-version`. Reproducibility matters.

---

## Day 2 · Apr 22 — The agent works end-to-end

Dense day. Shipped:

- Real investigator + quick_check system prompts
- Three subagents (Paper Reader / Code Auditor / Experiment Runner)
- Paper ingester (arXiv API + docling + cache)
- GitHub MCP wiring
- Two full Deep Investigations that opened **real PRs** on the bot account

| Run | Duration | Cost | Confidence | Metric move |
|---|---|---|---|---|
| Muchlinski Deep | 134 s | $0.74 | 0.98 | LR AUC 0.81 → 0.70 (−0.11) |
| ISIC Deep | 142 s | $0.68 | 0.97 | AUC 0.72 → 0.65 (−0.06) |
| Muchlinski Quick Check ×3 | <22 s each | $0.23 total | — | — |

Total API spend on Day 2: **~$2**.

Three surprises worth recording:

**Parser chunk boundaries bit us.** The SDK streams agent output as multiple `TextBlock`s, and when two adjacent blocks happened to split mid-section header, the line-anchored regex stopped seeing `## Hypothesis`. One-line fix (inject a `\n` between blocks), but we wouldn't have caught it without a raw-text debug dump on a real run. Opus admitted the `REPRO_DEBUG_DUMP=/tmp/...` hook paid for itself within ten minutes of existing.

**`env` kwarg doesn't propagate through SDK `Bash`.** Subagent Experiment Runner kept hitting `ModuleNotFoundError: sklearn`. Opus tried a couple of rounds going through env before pivoting to rewrite the command string in Python before passing: `python src/eval.py` → `{abs_venv_python} src/eval.py`. Robust and explicit.

**False-alarm PAT scope escalation.** Before Day 2 proper, Opus flagged a GitHub PAT scope violation and asked me to regenerate. The regenerated token behaved identically because the `/user/repos` endpoint and `permissions` field on a public repo report the *user's* view, not the *token's*. The definitive check (attempting a write on a non-demo repo → 403) was the right methodology. Opus wrote it in its diary: *"I was wrong; I fixed the smoke script so I won't repeat the mistake."* Worth admitting.

The Muchlinski investigation converged on **the right compound root cause** (imputation-before-split + target column present during imputation) on the first real run, wrote the minimal fix, re-ran the eval, and dropped LR AUC the documented 11 points. The prompt took three rewrites to land — the section-block schema is load-bearing — but once it landed, the behavior was dependable.

---

## Day 2 · Apr 22 (afternoon) — Robustness probe on real papers

Before letting Opus move to the frontend, I asked: *find two arXiv papers + public repos you've never seen and stress-test the backend.* Opus picked (via an Explore subagent):

- **FED / DialoGPT dialog evaluation** — has a documented reproducibility issue on GitHub
- **TabM / Yandex Research** — ICLR 2025, zero open issues

All six Quick Checks produced cited verdicts. Zero crashes. On FED, the agent caught a real reproducibility risk: `microsoft/DialoGPT-large` pulled via `from_pretrained` with no revision pin → silent drift on upstream HuggingFace updates. That matches the documented "can't reproduce paper's numbers" issue. On TabM, the agent said `confirmed — no leakage` with file:line citations. It could have opportunistically claimed leakage to look smart. It didn't.

Then I raised the stakes: *pick a 2025 paper you don't know, resource-intensive enough that you can't run the eval.* Opus picked **GIDD** (arXiv 2512.10858, Dec 2025 — past its training cutoff), a 10B-param diffusion LM trained on 10²² FLOPs on TPU. Not locally runnable. The agent:

- Correctly separated the **JAX/TPU training path** from the **PyTorch inference path** — nuanced answer, not binary.
- Found the exact config knobs implementing the paper's main claim (`hybrid_mixing_scale` / `hybrid_mixing_shift` in `DiffusionConfig`).
- Flagged that **no per-size hyperparameter sweeps exist** — a legitimate gap between the paper's scaling-laws claim and the repo.

Cumulative robustness: **16 Quick Checks / 16 verdicts / 0 crashes / ~$1.65** across four unseen domains (dialog / tabular / diffusion LM / protein LM). On the protein-LM probe (ByProt), the agent made **the same structural finding** as on FED — unpinned pretrained weights → silent drift — across totally unrelated domains. That's the point I updated on: not pattern-matching keywords, actually auditing code.

---

## Day 3 · Apr 22 — The frontend, and one reframe

My original spec was a **three-pane dashboard** (Hypothesis Board / Tool Stream / Dossier side-by-side). Opus built something different: a **chat UI** with collapsible inline blocks per assistant turn. Each reply progressively reveals the agent's work; the final dossier + PR card sit at the end of the turn where they belong. Judges who've used ChatGPT will know what to do in five seconds.

Opus also skipped the full shadcn/ui CLI install in favor of hand-built Radix-primitive wrappers. Faster, fewer files, production bundle 503 KB (156 KB gzipped).

Backend additions landed first (the right call): `runs.py` persistence, `artifacts.py` builders (dossier / diff / events / paper), artifact endpoints, session endpoints, and conversational memory spliced into the user prompt on follow-up turns. Then the frontend. When the first assistant turn rendered, the second turn referencing *"given what you found earlier…"* worked on the first try.

---

## Day 3 · Apr 22 (evening) — PDF upload, Validator, a comp-bio probe

Two product beats I'd been sitting on:

1. **PDF upload through the UI.** Cloudflare-blocked bioRxiv fetches were burning agent cycles. I told Opus: *stop fighting curl user-agent tricks, just let me drop a PDF into the folder.* `POST /papers/upload` + "Attach PDF" pill landed in an hour. The comp-bio probe on ByProt ran against the local PDF path and produced the cross-domain structural finding mentioned above.
2. **Validator subagent.** Adversarial second pass on the agent's own Deep Investigation — 7 checks (hypothesis coverage, evidence quality, fix minimality, causal link, alternative explanations, uncertainty honesty, suggested follow-up), rolled up to `strong / acceptable / weak / unreliable`. Opus cautioned: *tune it fair-not-doomer, or it'll manufacture problems on clean runs.* Calibrated carefully. On a saved ByProt Deep run, the Validator surfaced 2 real warns (no metric delta produced; overlap not quantified) and proposed a concrete next experiment (MMseqs2 mapping CATH chains to UniRef50 clusters). Not boilerplate.

This was the night the product started feeling *done* rather than in-progress. The Validator specifically shifted the epistemic shape: from "here's what the agent found" to "here's what the agent found AND an independent audit of that reasoning."

---

## Day 4 · Apr 22 (morning) — The UX refinement wave

Woke up with a wishlist and a scope-freeze deadline (Apr 24 EOD). Full UX refinement pass: local run history with click-to-reopen + animated event replay, phase timings (paper_ingest → hypotheses → checks → verify → dossier → pr, monotone), guaranteed `session_end` on cancel/error/stream-exhaustion, Claude-Code-style composer (textarea grows upward, toolbar inside), pinned conversations, model selector across Opus 4.7 / Sonnet 4.6 / Haiku 4.5.

One interesting bug: the phase tracker's first pass re-opened `dossier` and `verify` when the agent interleaved events late in the run. Fix: make the tracker monotone — each phase can only open once; earlier-ranked events after a later phase are absorbed. Also moved the `hypotheses` trigger from the first `hypothesis` event to `claim_summary`, so the phase captures the real thinking time rather than just the streaming time.

Verified with a Haiku 4.5 Deep Investigation on Muchlinski: $0.12, 108 s, all five phases registered with sane durations (hypotheses 49.5 s — where the LLM actually thinks). Build green.

---

## Day 4 · Apr 22 (afternoon) — The unified repo attach (the last product call)

I sent Opus a screenshot of the config drawer — only a "Repo path" field showed, and I couldn't remember there used to be three. Diagnosis: not a bug, just mode-dependent visibility. But the deeper point landed: the whole story of this product is *"paste → PR"*. Asking users to clone, paste the path, and re-type the slug is the opposite of that promise.

Opus shipped `POST /repos/attach` — takes a GitHub URL, an `owner/repo` slug, or a local path; shallow-clones to `~/.cache/paper-trail/repos/<owner>__<repo>/` on first use; returns `{local_path, slug, default_branch, source, already_cloned}`. The three-field config drawer became **one Repo input with a status pill**. The demo flow is now *paste, ask, send*.

**Verified live:** pasted `e-biswas/reproforensics-muchlinski-demo` → cloned in ~3 s → Quick Check on the cached clone found the split bug at `src/prepare_data.py:15` in 11 s / $0.04. Second attach returned from cache instantly.

This was the last product-shape call of the week. Everything after was polish.

---

## Day 4 · Apr 22 (evening) — Submission polish

`docs/pitch.md` rewritten as a judge-facing doc with an evidence-for-generalization section. `README.md` rewritten to match the shipped surface (no more `stage.sh` step). PR body template in the investigator prompt tightened — reviewers now get TL;DR / metric deltas table / root cause / evidence with citations / fix / remaining uncertainty / validator footer, not raw section-header prose.

Final dry run (Opus 4.7 Quick Check on the cached Muchlinski clone): **9.3 s, $0.1425, refuted at 0.98 with 2 file:line citations**. No glitches. Surfaced one edge: the sidebar was labeling Deep runs with verdict summaries because the user's prompt was only ever stored client-side. Fixed — `user_prompt` now threads all the way through `chatStore → WS start → RunConfig.extras → meta.config → _first_user_text`.

---

## What actually worked in the collaboration

Reading back through both diaries, five patterns held:

1. **Pushback was bidirectional.** I pushed back three times on Day 1 (stay general; verification-intern reframe; arbitrary-paper support). Opus pushed back three times (vertical-demo pattern; no multi-agent; no cloud spend). Each pushback stood on its own merits. If the collaboration had been "human types, AI autocompletes," none of these would have surfaced.
2. **Docs-before-code caught real bugs.** The `session_start` schema mistake was caught by an Explore subagent auditing against the integration contract *before* any wire traffic ever ran. The audit had a clean target to check against because the contract existed.
3. **Test-data-before-code paid back immediately.** The parser, built against pre-authored JSONL fixtures, passed on first real invocation. The Muchlinski fixture was tuned until it showed a dramatic delta *before* the agent ever saw it — so "does the agent find the right bug?" had a ground-truth answer from minute one.
4. **The agent noticed cross-domain patterns I didn't prime.** Unpinned pretrained-weight drift was spotted on FED (DialoGPT) and ByProt (ESM2). Same structural risk, two totally unrelated domains. That was the moment I stopped thinking of the system as keyword-matching and started thinking of it as actually reading code.
5. **"Auto mode" worked because the scaffolding was already in place.** By the time I said "compact and next phase, auto mode" on Day 4 evening, CLAUDE.md had the rules, TASKS.md had the plan, and docs/integration.md had the contract. Opus wasn't making up what to do — it was executing against a shared structure.

---

## By the numbers

| | Value |
|---|---|
| Days of build | 2 active (Apr 21–22) |
| Total API spend | ~$4 through scope-freeze |
| Subagents | 4 (Paper Reader, Code Auditor, Experiment Runner, Validator) |
| Real papers probed | 6 (Muchlinski, ISIC, FED, TabM, GIDD, ByProt) |
| Quick Checks on unseen repos | 16, zero crashes, zero hallucinated bugs |
| Live PRs opened on bot account | 2 (Muchlinski, ISIC) |
| Evidence citations, programmatic audit | 22/22 files exist, 22/22 snippets locate |
| Final bundle size | 527 KB (162 KB gzip) |

---

## If you're reading this to learn how to build with Claude Code

The short version:

- **Plan before you code, even when the planning feels like overhead.** Four days is long enough to pay for 19 planning files.
- **Make the contract load-bearing.** `docs/integration.md` was frozen after Day 1 and survived untouched through every subsequent change.
- **Test data before code.** Pin a ground-truth target early; the agent has something to be measured against from minute one.
- **Push back both ways.** If the AI never tells you "I disagree" or "that's a trap," you're not collaborating — you're typing faster.
- **Let the AI read its own work.** Explore subagent audits caught schema bugs, missing sections, and a bad error-handling branch before any user ever saw them.

For the unedited record with the pushbacks and the uncertainty left in, start with [`diary/claude.md`](diary/claude.md) and [`diary/eb.md`](diary/eb.md).
