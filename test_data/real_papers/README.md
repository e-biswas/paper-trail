# Real-world robustness probes

Unscripted paper + repo pairs we use to stress-test the agent beyond our curated fixtures. Each subdirectory is one target.

These are the receipts — full paper markdown, paper metadata, the exact Quick Check questions we asked, and the agent's verdicts with evidence — for the probes referenced in [../../TASKS.md](../../TASKS.md) and [../../diary/claude.md](../../diary/claude.md).

## Layout

```
real_papers/
├── fed/        # easy: documented repro issue (NLP/dialog eval)
├── tabm/       # clean: ICLR 2025 tabular ML, expected no-find
├── gidd/       # hard: Dec 2025 post-cutoff diffusion-LM paper
└── byprot/     # domain shift: protein language models + data leakage
```

Each subdirectory contains:

| File | What it holds |
|---|---|
| `paper_meta.json` | Title, authors, arXiv ID, section count, ingester duration |
| `paper_full.md` | The paper body after docling + our section parser |
| `questions.txt` | The Quick Check prompts we sent, one per blank-line-separated entry |
| `run_summary.json` | Structured record of every Quick Check: verdict, confidence, evidence list, notes, tool-call count, duration, cost |

## How to re-run

```bash
# FED + TabM (~$0.47)
uv run python tests/robustness_real_papers.py

# GIDD (~$0.60)
uv run python tests/robustness_gidd.py
```

Paper ingestion is cached (`~/.cache/paper-trail/papers/`), so only the Quick Checks cost API credits on re-runs.

## The three targets

### `fed/` — easy baseline (documented repro issue)

- **Paper:** Mehri & Eskenazi 2020, *"Unsupervised Evaluation of Interactive Dialog with DialoGPT."* arXiv 2006.12719.
- **Repo:** [Shikib/fed](https://github.com/Shikib/fed) — 2 .py files.
- **Expected signal:** the repo has [issue #3](https://github.com/Shikib/fed/issues/3) where users can't reproduce the paper's turn-level FED scores. We want the agent to find the mechanism.
- **Agent found:** `microsoft/DialoGPT-large` pulled via `from_pretrained` with no revision pin — upstream HF updates silently drift results. This matches the documented issue. The agent connected the dots without being told to look for it.

### `tabm/` — clean baseline

- **Paper:** Gorishniy et al. 2024/2025, *"TabM: Advancing Tabular Deep Learning with Parameter-Efficient Ensembling."* ICLR 2025, arXiv 2410.24210.
- **Repo:** [yandex-research/tabm](https://github.com/yandex-research/tabm) — 15 .py files, zero open issues.
- **Expected signal:** honest "no obvious leakage" verdicts. This exists to catch over-reaching / hallucinated-bug behavior.
- **Agent found:** preprocessing fit on train only (confirmed with file:line), validation-set-based hyperparameter selection (not test). No false positives.

### `gidd/` — hard stress case (Dec 2025, post-training-cutoff, TPU-scale)

- **Paper:** von Rütte et al. *"Scaling Behavior of Discrete Diffusion Language Models."* arXiv 2512.10858, submitted 11 Dec 2025.
- **Repo:** [dvruette/gidd-easydel](https://github.com/dvruette/gidd-easydel) — 33 .py files, 16 notebooks, ~30 MB.
- **Why it's hard:** post the agent's training cutoff, domain (discrete diffusion LMs) we never designed for, trained at 10B parameters / 10²² FLOPs on TPU — not locally runnable.
- **Agent found:** 5 precise, evidence-backed verdicts. Correctly identified the PyTorch inference fallback path (`modeling_gidd_hf.py`) separate from the JAX training path; spotted that no per-size hyperparameter sweeps exist; confirmed the `hybrid_mixing_scale`/`hybrid_mixing_shift` config parameters that implement the paper's noise-interpolation claim.

### `byprot/` — domain shift (comp-bio: protein LM data leakage)

- **Paper:** Hermann et al. 2024, *"Beware of Data Leakage from Protein LLM Pretraining."* bioRxiv 10.1101/2024.07.23.604678 · PMLR vol. 261. PDF had to be downloaded manually (bioRxiv is Cloudflare-protected and our auto-ingester gets blocked); then parsed by docling into 36K chars of markdown. This is exactly the use case the `POST /papers/upload` endpoint / UI "Attach PDF" button exists for.
- **Repo:** [BytedProtein/ByProt](https://github.com/BytedProtein/ByProt) — 74 .py files, 2.7 MB; ICML 2023 LM-Design official code integrating ESM2 for inverse folding.
- **Why it's different:** protein language models — a new domain. The paper's central finding is data leakage via **sequence similarity** (the same protein sequences appearing across UniRef50 pretraining and downstream evaluation). That's the biology analog of our canonical tabular leakage classes.
- **Agent found:** 5/5 verdicts. Four `refuted`: the repo trusts upstream split files as-is, with no UniRef50-overlap filtering, no in-repo MMseqs2/CD-HIT clustering, no tests warning about train-test overlap. Also spotted that ESM weights are fetched via `esm.pretrained.load_model_and_alphabet_hub` from an **unpinned** Facebook hub URL — the same structural class of reproducibility risk the agent flagged on FED (upstream model → silent drift). Cross-domain pattern recognition, without being told to look for it.

## Results snapshot

(Numbers from the most recent runs. Full per-question detail is in each target's `run_summary.json`.)

| Target | Questions | Verdicts | Crashes | Cost |
|---|---:|---:|---:|---:|
| fed | 3 | 3 | 0 | ≈$0.18 |
| tabm | 3 | 3 | 0 | ≈$0.29 |
| gidd | 5 | 5 | 0 | ≈$0.60 |
| byprot | 5 | 5 | 0 | ≈$0.58 |
| **Total** | **16** | **16** | **0** | **≈$1.65** |

## Interpreting the verdicts

- `confirmed` / `refuted` / `unclear` are the three allowed verdict labels. `unclear` means the agent could not definitively answer from static inspection — this is a **feature** (Quick Check is bounded at ≤8 tool calls; "I don't know" is a valid terminal state).
- `evidence` entries cite `file:line` with a one-line snippet. Where the agent cites a line, it actually read the file.
- `confidence` is a self-reported float 0–1.

## How to validate an artifact yourself (5 concrete checks)

For each probe in this directory, here's how you can independently sanity-check the agent's output — no re-run needed.

**1. Do the evidence citations point at real code?**

Open the target's `run_summary.json`, pick any check, and look at `checks[i].evidence`. Each entry has `file` and `line`. Go to the cloned repo and read that file:

```bash
# For byprot:
less +42 /tmp/real-byprot/src/byprot/datamodules/datasets/data_utils.py
# Confirm line 42 really is the code the notes reference.
```

If a cited line is outside the file or empty, the agent hallucinated and the run should be retried.

**2. Does the verdict match the reasoning in `notes`?**

The `notes` field is a one-sentence summary. Read it, then re-read the evidence snippets. Does the verdict logically follow? e.g. if the notes say "the imputer is fit on the full dataframe before the split," then `refuted` for a question phrased as *"is imputation fit on train only?"* is the right call; `confirmed` would be wrong.

**3. Does the dossier match the emitted envelopes?**

Open the run's `events.jsonl` (download via the UI or `GET /runs/{id}/events.jsonl`). Every `dossier_section` envelope has a `section` key matching one of the five canonical names. Compare to the dossier you see in the UI — they should be identical markdown. Any drift means the renderer is out of sync with the persisted log (a bug in the frontend, not the agent).

**4. Does the PR diff match `fix_applied`?**

For Deep Investigation runs that produced a `pr_opened` envelope: open the PR URL, look at the diff, confirm the files modified match `files_changed` in the run summary, and the change matches what `fix_applied.diff_summary` describes. You can also download `diff.patch` from the UI to compare locally.

**5. Does the paper context match what the agent reasoned about?**

For probes that include `paper_full.md`, skim it (or ask the LLM to summarize specific sections for you). The agent's `claim_summary` envelope should faithfully reflect the paper's actual claim. For `byprot/`, where we only have sections extracted by docling, skim `paper_full.md` and verify the abstract and headline claim about UniRef50 leakage are there.

**Re-runs aren't deterministic.** LLM outputs vary slightly across calls. Expect small phrasing drift between runs (e.g., "full dataframe" vs "entire dataframe"), but the verdict label + cited files should be stable. If you re-run a probe (`uv run python tests/robustness_*.py`) and get a verdict flip, that's signal — investigate.

## What is NOT tested here

- Deep Investigation on external repos. We deliberately never run that path against code we don't own — the agent would apply `Edit`s and potentially push a PR. Read-only Quick Check only.
- Whether any verdict is objectively "correct" — we assess plausibility + faithfulness-to-code, not ground truth. For ground-truth checks on fixtures, see [`test_data/ground_truth/`](../ground_truth/).
- LLM-call determinism. Small phrasing drift is expected on re-run.
