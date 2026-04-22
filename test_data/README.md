# Test Data

Test data for Paper Trail backend components. Every file here has a specific purpose; nothing is here for decoration.

## Layout

```
test_data/
├── parser/
│   ├── valid/              ← sample agent outputs the parser should handle
│   ├── invalid/            ← edge cases / malformed inputs the parser must reject gracefully
│   └── expected/           ← for each valid input, the JSONL of envelope events the parser should emit
├── replay/                 ← full envelope event streams (session_start → session_end) for UI dev + server smoke tests
├── papers/                 ← paper claim summaries that feed the agent as part of its Deep Investigation context
└── ground_truth/           ← expected outcomes per fixture (JSON) — used as acceptance criteria for end-to-end tests
```

## Files — what each one is for

### `parser/valid/`

Each file is a sample of what the agent would write as its turn-level output. The **markdown-section parser** in [`../docs/backend/agent.md`](../docs/backend/agent.md) should be able to consume these and emit the corresponding envelope events.

| File | Use |
|---|---|
| `complete_investigation.md` | Full happy-path Deep Investigation output covering every section type (claim, hypotheses, checks, findings, updates, verdict, fix, metric deltas, all 5 dossier sections, PR opened). Primary smoke test for the parser. |
| `with_hypothesis_updates.md` | ISIC-flavored investigation exercising the `hypothesis_update` event (confidence progression after a finding). |
| `quick_check_confirmed.md` | Quick Check returning `confirmed` — expected verdict for the ISIC "is dedup present?" question against a fixed fixture. |
| `quick_check_refuted.md` | Quick Check returning `refuted` — the canonical Muchlinski answer to "is imputation fit on train only?" |
| `quick_check_unclear.md` | Quick Check returning `unclear` — exercises the ambiguous-verdict path. |
| `aborted_investigation.md` | Deep Investigation that hits the turn cap without a confident verdict. Exercises the `aborted` event and the "no verdict reached" dossier state. |

### `parser/invalid/`

Edge cases. The parser must handle each of these without crashing; the exact behavior (skip / warn / abort) is specified per case in [`../docs/backend/agent.md`](../docs/backend/agent.md).

| File | Why |
|---|---|
| `missing_confidence.md` | Hypothesis block with no `confidence` field. Parser should skip with a warning. |
| `bare_prose.md` | Agent ignored the section schema and wrote pure prose. Parser should emit zero high-level events and not crash. |
| `malformed_section_name.md` | Typos and case variants in section headers. Parser must not coerce `## Hipothesis 1:` into a real hypothesis event. |
| `unclosed_section.md` | Stream truncated mid-section. Parser must not emit a half-parsed event. |

### `parser/expected/`

For each `valid/*.md` file that has a corresponding expected output, one `.jsonl` file listing the sequence of envelope events the parser should emit. `run_id`, `ts`, and `seq` are omitted — those are added by the server at emission time (see [`../docs/integration.md`](../docs/integration.md)).

### `replay/`

Full, realistic envelope streams (including `session_start`, `session_end`, `tool_call`, `tool_result`, `run_id`, `ts`, `seq`) — what the server would actually emit over the WebSocket for a complete run.

| File | Use |
|---|---|
| `muchlinski_success.jsonl` | Happy-path Deep Investigation on the primary fixture. 35 events, ends with `pr_opened` + `session_end(ok=true)`. |
| `isic_success.jsonl` | Happy-path Deep Investigation on the backup fixture. 28 events. |
| `quick_check_success.jsonl` | Canonical Quick Check run (refuted verdict). 7 events. |
| `investigation_aborted.jsonl` | Deep Investigation that hit the 30-turn cap without a confident verdict. Ends with `aborted` + `session_end(ok=false)`. |
| `investigation_errored.jsonl` | Error case — missing file, agent_exception, session ends without a verdict. |

Primary uses:
- **Frontend development** — drive the UI without a backend by feeding one of these into the reducer.
- **Backend smoke tests** — run the server's emitted stream against a golden fixture and diff (after stripping timestamps + seq).
- **Integration verification** — confirm every event type defined in [`../docs/integration.md`](../docs/integration.md) appears at least once across the replay set.

### `papers/`

Short summaries of the real papers our fixtures mimic, formatted as context the agent can ingest during a Deep Investigation. These are NOT the real paper PDFs — they're distilled claim summaries that capture the shape of the claim an agent needs to test.

| File | Covers |
|---|---|
| `muchlinski.md` | Muchlinski et al. 2016 civil-war-onset prediction paper. |
| `isic.md` | Rotemberg et al. 2021 / ISIC 2020 melanoma challenge dataset paper. |

### `ground_truth/`

Per-fixture acceptance criteria. Used to decide whether a Deep Investigation run succeeded. Each file includes:

- Headline metrics (broken state) and honest metrics (fixed state)
- The deterministic seed used
- Expected verdict: failure class, root-cause summary, minimum confidence
- Expected fix: files changed, rough diff size, shape of the fix
- List of acceptance checks an automated end-to-end test can assert

| File | Fixture |
|---|---|
| `muchlinski.json` | Primary fixture |
| `isic.json` | Backup fixture |

## How to use this test data

### Developing the markdown-section parser

```python
# Pseudocode for a parser unit test
for md_path in glob("test_data/parser/valid/*.md"):
    expected_path = Path("test_data/parser/expected") / (md_path.stem + ".jsonl")
    if not expected_path.exists():
        continue
    expected_events = [json.loads(line) for line in expected_path.open()]
    actual_events = list(parse_markdown(md_path.read_text()))
    assert_events_equivalent(actual_events, expected_events)
```

### Developing the frontend without a backend

Load any `replay/*.jsonl` into the reducer at 50 ms/event, verify each pane populates per [`../docs/integration.md`](../docs/integration.md#pane-routing-frontend-reducer-rules).

### Regenerating fixture datasets

```bash
python /Users/eb/Downloads/experiments/paper-trail/demo/primary/data/generate.py
python /Users/eb/Downloads/experiments/paper-trail/demo/backup/data/generate.py
```

Both seeded with `RANDOM_STATE=42`; re-runs produce identical CSVs.

## Status

| Component | Status | Last touched |
|---|---|---|
| Muchlinski fixture (`demo/primary`) | `DONE` — broken & fixed both verified end-to-end | 2026-04-22 |
| ISIC fixture (`demo/backup`) | `DONE` — broken & fixed both verified end-to-end | 2026-04-22 |
| Parser valid fixtures | `DONE` (6 files) | 2026-04-22 |
| Parser invalid fixtures | `DONE` (4 files) | 2026-04-22 |
| Parser expected outputs | `DONE` (6 files, all valid JSONL) | 2026-04-22 |
| Replay fixtures | `DONE` — 5 files, all valid JSONL | 2026-04-22 |
| Paper summaries | `DONE` | 2026-04-22 |
| Ground truth | `DONE` | 2026-04-22 |
