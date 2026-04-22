## Failure-class taxonomy

A ranked catalogue of reproducibility failures the investigator looks for first. Each entry lists the symptom, where it tends to appear, concrete code signatures the investigator should grep for, the smallest check that discriminates it, and the canonical minimal fix.

Drawn from Kapoor & Narayanan (2023) *"Leakage and the Reproducibility Crisis in Machine-Learning-Based Science"* and from the Princeton replication database.

---

### 1. Imputation-before-split leakage

- **Symptom:** held-out test metric is inflated — often by a few to many AUC points — and the gap shrinks or vanishes when the eval is re-run with a proper train-only imputer.
- **Common in:** tabular medical / social-science ML; any repo that uses `IterativeImputer`, `KNNImputer`, `SimpleImputer`, or R packages like `mice` / `Amelia`.
- **Code signatures to grep for:**
  - `KNNImputer` / `SimpleImputer` / `IterativeImputer` called with `.fit_transform(` on a dataframe BEFORE any `train_test_split` / `GroupShuffleSplit` / `KFold` call on the same dataframe.
  - Assignment patterns like `df_imputed = imputer.fit_transform(df)` followed later by `train_test_split(df_imputed, ...)`.
  - `df.drop(columns=[...])` that does NOT remove the target column before imputation — if the target is present at imputation time, KNN/Iterative imputers can use target-adjacent patterns to fill values, directly leaking labels.
- **Discriminating check:** open the data-prep file, locate the first `.fit(` / `.fit_transform(` call on the imputer, and verify it runs on a view of the data that excludes the test rows AND the target column.
- **Canonical minimal fix:** split first, fit the imputer on train only, apply `.transform()` to test. Drop the target column before imputing.

### 2. Patient- / entity-level split bug

- **Symptom:** paper reports patient-level AUC; repo reports image-level AUC; the two are silently different because the split shuffles by row instead of by entity.
- **Common in:** medical imaging (CheXpert, ISIC, MIMIC), multi-visit clinical records, any dataset with a grouping column (`patient_id`, `subject`, `study_id`).
- **Code signatures to grep for:**
  - `train_test_split(X, y, ...)` with no `groups=` argument when the dataframe has a column named `patient_id` / `subject_id` / `study_id` / `case_id`.
  - `KFold` used instead of `GroupKFold` / `StratifiedGroupKFold` on data with a grouping column.
- **Discriminating check:** after the split is performed, intersect the set of group ids in train and test. A non-empty intersection confirms the bug.
- **Canonical minimal fix:** swap to `GroupShuffleSplit` / `GroupKFold` keyed on the ID column. For images: dedupe by patient first, then split.

### 3. Duplicate-row / duplicate-image leakage

- **Symptom:** model AUC appears higher than any other published work on the same data; honest re-run is several points lower.
- **Common in:** Kaggle-era image challenges (ISIC 2020 had ~425 documented duplicates), panel datasets where the same row appears under two ids, scraped corpora with template duplicates.
- **Code signatures to grep for:**
  - Pipelines that call `train_test_split` without `.drop_duplicates(subset=<hash_col>)` earlier.
  - Dataset loaders that don't compute a perceptual or exact hash on images.
  - CSVs where the number of rows exceeds the number of distinct values in an id column (e.g. `image_hash`).
- **Discriminating check:** count duplicates — `df['image_hash'].nunique() < len(df)` or the equivalent for rows — and check whether any dedup happens before the split.
- **Canonical minimal fix:** `df = df.drop_duplicates(subset=['<hash_col>']).reset_index(drop=True)` BEFORE the split.

### 4. Temporal leakage

- **Symptom:** model "predicts" events with high accuracy, but features encode information that was only observable after the prediction time.
- **Common in:** sepsis / ICU / credit-default / churn prediction; any time-series task with a cutoff time.
- **Code signatures to grep for:**
  - Feature construction using `groupby.transform(...)`, rolling windows with `center=True`, or `.shift(-k)` (negative shift — reads the future).
  - `train_test_split` applied to a time-sorted panel without a time cutoff.
- **Discriminating check:** inspect the feature-engineering functions for any pandas operation that reads forward in time. Confirm the split is strict time-based if one is claimed.
- **Canonical minimal fix:** add a time cutoff to the split (`train: ts < cutoff`, `test: ts >= cutoff`). Replace forward-looking features with backward-only windows.

### 5. Metric implementation mismatch

- **Symptom:** the reported number is high because the metric as implemented is not what its name suggests.
- **Common in:** Heavily imbalanced tasks where accuracy is reported instead of AUPRC or PPV; multi-class tasks using `average="micro"` on macro-weighted targets; ranking metrics computed at the wrong K.
- **Code signatures to grep for:**
  - Hand-rolled metric functions that don't match their `sklearn.metrics.*` namesake.
  - `accuracy_score` applied to a ~5% prevalence target.
  - `roc_auc_score(..., average="micro")` when the paper reports a macro-averaged or per-class AUC.
- **Discriminating check:** re-run the eval with the canonical `sklearn.metrics.*` function alongside the repo's metric and compare.
- **Canonical minimal fix:** replace the custom metric with the standard implementation. If the paper explicitly asked for the custom version, note it in the dossier instead of changing code.

### 6. (Stretch) Subgroup blind spot

- **Symptom:** the aggregate metric looks good; the per-subgroup metric reveals a large failure on one slice (demographics, site, device).
- **Common in:** medical imaging repos that don't slice by race/sex/age; any deployed classifier with heterogeneous users.
- **Code signatures to grep for:**
  - Eval scripts that report a single scalar with no subgroup breakdown.
  - Data loaders that drop demographic columns "to avoid leakage" (separate issue).
- **Discriminating check:** compute the metric per subgroup; flag any subgroup where performance falls >10 points below the aggregate.
- **Canonical minimal fix:** add a subgroup-slice evaluation to the eval script. Do not change the model. Report the slice in the dossier.

---

## Notes for the investigator

- These classes frequently **co-occur**. A repo with imputation-before-split AND a missing patient split is common. Generate hypotheses for all relevant classes; let the checks discriminate.
- When confidences tie, prefer the class with the **strongest grep signature** in the repo. If the taxonomy says "grep for `fit_transform` on a full df" and you find one, rank that hypothesis first.
- If you find evidence for a failure class NOT in this taxonomy (e.g., random-seed instability, hyperparameter drift, library-version mismatch), document it in `## Dossier — Remaining uncertainty:` but do NOT invent a new failure-class name — stay disciplined.
