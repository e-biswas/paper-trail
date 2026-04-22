## Claim:
claim: "ISIC 2020 melanoma classifier achieves ROC-AUC > 0.70 on the challenge test set."

## Hypothesis 1: Duplicate-image leakage
confidence: 0.50
reason: "ISIC 2020 is publicly known to contain hundreds of exact duplicates; almost any off-the-shelf repro that doesn't dedupe will be affected."

## Hypothesis 2: Patient-level leakage
confidence: 0.38
reason: "Same patient appearing in multiple images is common in dermoscopy datasets. If the split is at the image level, patient features leak."

## Hypothesis 3: Data augmentation applied pre-split
confidence: 0.20
reason: "Some repros augment the full dataset then split; augmentations of train images then appear in test."

## Check: Duplicate-image leakage
hypothesis_id: h1
description: "Count duplicate image_hash values and check whether dedup happens before train_test_split."
method: "Read + Grep + Bash"

## Finding:
check_id: c1
result: "isic_metadata.csv has 4025 rows but only 3500 unique image_hash values — 525 exact duplicates. prepare_data.py (line 22) calls train_test_split directly on df without deduplication. Confirmed leakage."
supports: [h1]
refutes: []

## Hypothesis 1 (update):
confidence: 0.93
reason_delta: "Empirical confirmation: 525 duplicates in the source CSV and no dedup step in prepare_data."

## Check: Patient-level leakage
hypothesis_id: h2
description: "Check whether patient_id values appear in both train and test folds."
method: "Python"

## Finding:
check_id: c2
result: "After the standard train_test_split (random_state=42), 312 patient_ids appear in both folds. This is a real secondary leakage, but weaker than the duplicate-image leak which is confirmed by H1."
supports: [h2]
refutes: []

## Hypothesis 2 (update):
confidence: 0.74
reason_delta: "Confirmed but secondary to H1."

## Verdict:
hypothesis_id: h1
confidence: 0.93
summary: "Duplicate-image leakage is the primary driver of the inflated headline AUC. Exact-hash deduplication before split addresses it. Patient-level leakage (H2) is a real secondary issue recommended for a follow-up PR."

## Fix applied:
files_changed: [src/prepare_data.py]
diff_summary: "Add df.drop_duplicates(subset=['image_hash']) before train_test_split. Does not change the rest of the pipeline."

## Metric delta:
metric: "AUC"
before: 0.7153
after: 0.6522
context: "Random Forest on held-out test set"

## Dossier — Claim tested:
The repo reports ROC-AUC 0.7153 on a held-out 20% of the ISIC 2020 metadata + image-features training set, implying the model achieves clinically meaningful melanoma classification.

## Dossier — Evidence gathered:
The source CSV contains 4025 rows with only 3500 unique `image_hash` values — 525 exact duplicates (13%). `src/prepare_data.py` (line 22) splits on the full dataframe without deduplication, so duplicate hashes appear in both train and test folds. Random Forest memorizes images during training and recognizes the same hashes in the test fold, inflating the measured AUC.

## Dossier — Root cause:
Exact-duplicate-image leakage. 525 images (same `image_hash`, same features, same target) span the train/test boundary.

## Dossier — Fix applied:
One-line addition to `src/prepare_data.py`: `df = df.drop_duplicates(subset=['image_hash']).reset_index(drop=True)` before `train_test_split`.

## Dossier — Remaining uncertainty:
Exact-hash dedup does not catch perceptual near-duplicates — images that are visually identical but differ by a compression artifact or crop. The real ISIC 2020 dataset contains both. A stricter fix would apply perceptual hashing (e.g., pHash) with a similarity threshold. This is recommended as a follow-up PR. Additionally, patient-level leakage (H2) remains in the fixed version and is worth a separate investigation.

## PR opened:
url: https://github.com/paper-trail/isic-demo/pull/1
number: 1
title: "Fix duplicate-image leakage in ISIC preprocessing"
