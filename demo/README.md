# Demo Fixtures

Curated repositories that ship in a deliberately-broken state, each with a known reproducibility bug. The Paper Trail agent investigates these during live demos and opens a PR with the fix.

Each fixture is a self-contained, runnable ML mini-project. Both fixtures have been verified end-to-end: the broken state produces the expected inflated metric, and the documented manual fix produces the honest metric.

## Fixtures

### Primary — Muchlinski Civil War Prediction

- **Location:** [`primary/`](primary/)
- **Paper:** Muchlinski et al. 2016 (*Political Analysis*)
- **Domain:** Tabular classification, panel data
- **Bug:** **Compound imputation leakage** — `KNNImputer` is fit on the full dataframe before `train_test_split`, AND the target column is still present in the dataframe at fit time. Both conditions leak test-side information (including labels) into the imputed values the model trains on.
- **Metric delta:** RF AUC 0.9562 → 0.9070 (−4.9), LR AUC 0.8091 → 0.6962 (−11.3)
- **Runtime:** ≤ 2 minutes end-to-end on a laptop
- **Read the fixture details:** [`primary/README.md`](primary/README.md)

### Backup — ISIC 2020 Melanoma Classification

- **Location:** [`backup/`](backup/)
- **Paper:** Rotemberg et al. 2021 (*Scientific Data*) / SIIM-ISIC 2020 Kaggle challenge
- **Domain:** Tabular-features proxy for medical imaging (metadata + handcrafted image statistics)
- **Bug:** **Duplicate-image leakage** — 525 duplicate rows (same `image_hash`, same features, same target) in the dataset; `prepare_data.py` splits without deduplication, so duplicates span train/test folds.
- **Metric delta:** RF AUC 0.7153 → 0.6522 (−6.3)
- **Runtime:** ≤ 1 minute
- **Read the fixture details:** [`backup/README.md`](backup/README.md)

## Fixture directory layout

Every fixture directory follows the same shape:

```
<fixture>/
├── README.md              ← paper claim, the bug, expected metrics, the fix
├── requirements.txt       ← sklearn, pandas, numpy
├── stage.sh               ← idempotent: copy to /tmp, git init, set remote
├── reset.sh               ← wipe /tmp + bot fork back to broken baseline
├── src/
│   ├── prepare_data.py    ← the bug lives here
│   ├── train.py           ← training helpers
│   └── eval.py            ← run the pipeline, emit METRIC_JSON line
└── data/
    ├── generate.py        ← deterministic generator (seeded RANDOM_STATE=42)
    └── <dataset>.csv      ← checked-in synthetic data
```

### The `METRIC_JSON:` contract

Every fixture's `eval.py` prints exactly one line to stdout beginning with `METRIC_JSON: ` followed by a JSON object containing at minimum `metric`, `context`, and one or more numeric metric values. This is what the agent parses to extract the before/after numbers it reports in the `metric_delta` envelope.

Primary example:

```
METRIC_JSON: {"metric": "AUC", "rf": 0.9562, "lr": 0.8091, "context": "Muchlinski civil war onset", "n_train": 2250, "n_test": 750, ...}
```

Backup example:

```
METRIC_JSON: {"metric": "AUC", "value": 0.7153, "context": "ISIC 2020 melanoma classification (RF on metadata+image features)", ...}
```

## Running a fixture by hand

```bash
# Stage the primary fixture (idempotent)
demo/primary/stage.sh
# -> prints /tmp/muchlinski-demo

# Run the broken eval
python /tmp/muchlinski-demo/src/eval.py
# -> METRIC_JSON: { ... }

# After a demo, reset (requires GITHUB_BOT_OWNER/BOT_REPO env for remote reset)
demo/primary/reset.sh
```

## End-to-end verification (the `How to verify` section that backs this doc)

For each fixture, running the following steps should produce the metrics documented in the fixture's README:

1. `./stage.sh` → new `/tmp/<fixture>-demo/` directory, git-initialized
2. `python src/eval.py` from inside that directory → `METRIC_JSON: {...}` matching the "broken" metrics
3. Apply the fix described in the fixture's README by hand → re-run `eval.py` → metrics match the "fixed" numbers

These have been run at fixture-creation time; see [../test_data/ground_truth/](../test_data/ground_truth/) for the exact numbers. Any drift (sklearn version bump, numpy random generator change, etc.) should be caught by re-running this procedure.

## Not in scope here

- Training actual neural networks on real images (too slow for a demo).
- Using the real ISIC 2020 dataset (licensing + size constraints).
- Patient-level leakage fix for ISIC (stretch, see [`backup/README.md`](backup/README.md)).
- Temporal-split leakage fix for Muchlinski (stretch, see [`primary/README.md`](primary/README.md)).
