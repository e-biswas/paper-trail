# Backend — System Prompts

## Purpose

Three prompt files that define the agent's behavior. The prompts are the **product's brain** — they encode what "investigation" means here, the failure taxonomy the agent draws hypotheses from, and the exact markdown structure the server parser depends on.

## Status

`TODO` · last updated 2026-04-21

## Files

| File | Purpose | Used by |
|---|---|---|
| `server/prompts/investigator.md` | Deep Investigation operating manual | `/ws/investigate` |
| `server/prompts/quick_check.md` | Quick Check operating manual | `/ws/check` |
| `server/prompts/failure_classes.md` | Shared failure taxonomy with grep signatures | Referenced by both prompts via include/concat |

## Public interface

Prompts are plain markdown loaded at request time:

```python
# server/agent.py
def load_prompt(mode: Mode) -> str:
    base = (PROMPTS_DIR / f"{'investigator' if mode=='investigate' else 'quick_check'}.md").read_text()
    taxonomy = (PROMPTS_DIR / "failure_classes.md").read_text()
    return base.replace("{{FAILURE_CLASSES}}", taxonomy)
```

The `{{FAILURE_CLASSES}}` token lets us update the taxonomy in one place.

## Implementation notes

### Prompt loading and substitution

- Prompts are plain markdown files loaded at request time — no build-step templating.
- `{{FAILURE_CLASSES}}` is the only substitution token; we do not add Jinja or any templating framework.
- Prompts are read fresh on every run (no caching) so edits during development apply immediately — avoid reloads during a live demo.
- `PROMPTS_DIR = Path(__file__).parent / "prompts"` in `server/agent.py`.

### Versioning and iteration

- Keep the prompts under version control; hand-edit them. Do not generate them.
- When making significant edits, log the prompt's byte length + first 100 chars in the server startup log so we can verify which version is live.

### Header exactness

The markdown-section parser in [agent.md](agent.md) keys on the exact strings `## Hypothesis N:`, `## Check:`, `## Finding:`, `## Verdict:`, `## Fix applied:`, `## Metric delta:`, `## Dossier — <section>:`. **The prompts are the contract that makes the parser work.** If you change a header here, change it in the parser in the same commit. Incorrect headers in the prompt will silently cause the parser to miss sections — manifests as a dead Hypothesis Board or an empty Dossier pane.

### Claim summary vs dossier

Note the separation: `## Claim:` (near the top of an investigator run) emits a **`claim_summary`** event, routed to the Dossier pane's header. The five dossier sections (`## Dossier — Claim tested:`, etc.) are written later, after the fix has been applied, and emit **`dossier_section`** events. Same claim, referenced twice — once as a concise summary, once inside the final audit report.

---

## `investigator.md` — design spec

The prompt instructs Claude to be a **"reproducibility investigator"**: rigorous, hypothesis-driven, evidence-seeking, honest about uncertainty. It enforces a strict output structure so the server parser can route sections to UI panes.

### Required output sections, in order

```
## Claim:
claim: "RF beats LR for civil-war onset prediction (Muchlinski et al. 2016)."

## Hypothesis 1: Imputation-before-split leakage
confidence: 0.55
reason: "Common in older R workflows; Muchlinski used Amelia II which can impute the full panel before split."

## Hypothesis 2: ...
...

## Check: Imputation-before-split leakage
hypothesis_id: h1
description: "Read prepare_data.R and find where imputation is fit."
method: "Grep for 'amelia' / 'impute'; read fit call site; confirm it runs over full df before split."

## Finding:
check_id: c1
result: "Line 47 of prepare_data.R fits Amelia on the full panel before train/test split. Confirms leakage."
supports: [h1]
refutes: []

## Hypothesis 1 (update):
confidence: 0.95
reason_delta: "Confirmed by direct inspection of prepare_data.R:47."

## Verdict:
hypothesis_id: h1
confidence: 0.95
summary: "Imputation is fit on the full panel before train/test split, leaking test-distribution information into training."

## Fix applied:
files_changed: [prepare_data.py]
diff_summary: "Move Amelia-equivalent imputation into a sklearn Pipeline with fit on train-only; apply transform to test."

## Metric delta:
metric: "AUC"
before: 0.85
after: 0.72
baseline: 0.74  # logistic regression
context: "RandomForest; Muchlinski conflict onset dataset; 5-fold CV."

## Dossier — Claim tested:
<markdown paragraph>

## Dossier — Evidence gathered:
<markdown paragraph>

## Dossier — Root cause:
<markdown paragraph>

## Dossier — Fix applied:
<markdown paragraph>

## Dossier — Remaining uncertainty:
<markdown paragraph>
```

Then the agent calls `mcp__github__create_pull_request` with title, branch, body (= concatenated dossier sections), returning a URL.

### Behavioral rules the prompt enforces

1. Before generating any hypothesis, read the repo structure (`Glob`/`Read`) and the paper abstract (via provided summary or `WebFetch`).
2. Generate **3–5 hypotheses**, drawn from `{{FAILURE_CLASSES}}`. Assign confidences that sum ≤ 1.5 (they can be non-exclusive).
3. For each of the **top 2** hypotheses, design and execute **one** small discriminating check. Prefer `Read` + `Grep` over `Bash` (cheaper, faster).
4. Update confidences explicitly via `## Hypothesis N (update):` blocks after each finding.
5. Declare `## Verdict:` only when one hypothesis exceeds 0.85 confidence.
6. When writing the fix, make the **smallest** change that fixes the bug. Avoid cleanup, refactors, or drive-by improvements.
7. Re-run the eval after the fix. If the metric doesn't move or moves in the wrong direction, do NOT declare success — emit `## Aborted:` instead.
8. In `## Dossier — Remaining uncertainty:`, list anything the agent assumed, approximated, or could not verify. Judges value honesty here.

### Tool allowlist behavior

- Use `Read` / `Glob` / `Grep` freely for inspection.
- Use `Bash` only for: `git diff` / `git status` / `git add` / `git commit` / `git push` / running the repo's own eval script.
- Use `Edit` for code fixes. Never use `Write` to clobber files.
- Use `WebFetch` to fetch the paper's abstract/intro if a URL is provided.

### Anti-patterns the prompt forbids

- No training runs. If the repo has a `train.py` that takes >60s, do NOT run it. Use the fixture's pre-staged eval script instead.
- No speculation without evidence. Confidence must be grounded in tool output.
- No sprawling fixes. One hypothesis → one minimal fix.

---

## `quick_check.md` — design spec

Much shorter. Tells Claude:

> You are verifying ONE assumption about the repo in front of you. The question is below. Run the minimum number of tool calls to answer it. Do not investigate unrelated issues. Output exactly one `## Verdict:` block in the schema shown, then stop.

### Required output

```
## Verdict:
verdict: confirmed | refuted | unclear
confidence: 0.0–1.0
evidence:
  - file: path/to/file.py
    line: 47
    snippet: "code excerpt"
notes: "one-line summary"
```

Rules:
- At most 3 tool calls.
- If the answer is genuinely ambiguous (e.g., the repo has two conflicting implementations), verdict is `unclear` with both cited in `evidence`.
- Never open a PR in Quick Check mode.
- Never modify files in Quick Check mode. Remove `Edit`/`Write` from allowed tools for this mode.

---

## `failure_classes.md` — design spec

A structured reference document Claude draws hypotheses from. Each entry:

```
### {NAME}

**Symptom:** <how it manifests in a run>
**Common in:** <domains/datasets where this tends to appear>
**Code signatures to grep for:**
- `pattern1`
- `pattern2`
**Discriminating check:** <one small check that confirms or refutes>
**Canonical fix:** <the minimal code change>
```

### MVP failure classes

1. **Imputation-before-split leakage** (PRIMARY DEMO)
   - Signatures: `SimpleImputer().fit(X)` outside a `Pipeline`; `Amelia(data=full_df)` before `train/test` split; `mean()` / `std()` computed on full dataset before split.
   - Check: inspect the first `.fit()` call on imputer/scaler and trace whether it sees test rows.
   - Fix: move into `sklearn.pipeline.Pipeline([...])`; `fit_transform` on train; `transform` on test.

2. **Patient-/entity-level split bug**
   - Signatures: `train_test_split(X, y)` without `groups=` when a patient/ID column exists; `GroupShuffleSplit` absent.
   - Check: check whether any ID value appears in both splits.
   - Fix: `GroupShuffleSplit(n_splits=1, groups=df['patient_id'])`.

3. **Duplicate-row / duplicate-image leakage**
   - Signatures: no `drop_duplicates()` on raw data; no perceptual-hash dedup for images.
   - Check: count exact duplicates between train and test.
   - Fix: dedupe before split.

4. **Temporal leakage**
   - Signatures: features derived from `groupby.transform` using future values; `.shift(-k)` on features; `train_test_split` on time-series without a time cutoff.
   - Check: verify every test-row feature is derivable from data with timestamp ≤ prediction time.
   - Fix: strict time-based split + backward-only feature windows.

5. **(Stretch) Subgroup blind spot**
   - Signatures: single scalar metric reported; no `pd.crosstab` of error rates by demographic.
   - Check: slice metrics by each categorical demographic column; flag any >10% drop from the aggregate.
   - Fix: add a subgroup eval section to the eval script.

---

## How to verify (end-to-end)

### Unit-ish smoke

1. Load each prompt with `load_prompt("investigate")` and `load_prompt("check")`.
2. Assert the rendered investigator prompt contains all five failure-class names.
3. Assert the quick-check prompt contains the exact `## Verdict:` schema.

### Full path

1. Run the Muchlinski end-to-end test from [agent.md](agent.md). Expect the agent to:
   - List at least 3 hypotheses, with "Imputation-before-split leakage" as rank 1.
   - Run a `Read` on `prepare_data.*` within the first 3 turns.
   - Issue a `## Verdict:` with `hypothesis_id: h1` and confidence ≥ 0.85.
   - Write a minimal fix that moves imputation into a `Pipeline`.
   - Report a `metric_delta` with `after < before`.
2. Run a Quick Check with "Is imputation fit on train only?" against the same fixture. Expect `verdict: refuted`, confidence ≥ 0.8, with at least one evidence entry pointing at the fit call site.

### Expected failure modes

- **Agent emits free-form prose instead of `## Section:`.** Prompt is not strict enough — add an explicit "use ONLY these section headers, no others" instruction.
- **Agent opens a PR too early.** Prompt must require `metric_delta` with `after != before` before PR creation.
- **Quick Check runs >8 turns.** Quick Check prompt needs a "stop after verdict" instruction reinforced; `max_turns=8` still protects us.

## Open questions / deferred

- Should `failure_classes.md` be dynamically extended based on repo signals (e.g., presence of `image` directory → expand dermatology-specific checks)? `DEFERRED`; MVP is static.
- Few-shot examples inside the prompt: would improve first-turn quality but cost tokens. Try adding one example of a completed investigation if Day 2 output quality is weak.
- Prompt versioning: tag prompts with `version:` frontmatter so we can A/B test. `DEFERRED`.
