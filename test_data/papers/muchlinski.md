# Muchlinski et al. 2016 — paper summary (for agent ingestion)

**Full citation:** Muchlinski, D., Siroky, D., He, J., & Kocher, M. (2016). *Comparing Random Forest with Logistic Regression for Predicting Class-Imbalanced Civil War Onset Data.* Political Analysis, 24(1), 87–103.

**Primary claim:**
> Random Forest (RF) substantially outperforms Logistic Regression (LR) at predicting civil war onset, in a setting with heavy class imbalance (onset prevalence ~1–3% per country-year observation). The authors report large ROC-AUC gaps (on the order of 10–20 points) favoring RF.

**Dataset:** Country-year panel data on civil war onsets, covering roughly 150 countries from 1960 to the early 2000s. Features include economic indicators (GDP per capita, GDP growth), demographic measures (ethnic fractionalization, population), political indicators (polity score, prior war history), and geographic descriptors (mountain terrain, neighboring conflicts).

**Methodology (as claimed):** Impute missing values, train RF and LR classifiers, evaluate on held-out test folds with stratified splits and balanced class weighting.

**Documented critique:**
Kapoor & Narayanan (2023, "Leakage and the Reproducibility Crisis in Machine-Learning-Based Science," *Patterns*) catalog Muchlinski 2016 as one of the canonical examples of data leakage in applied ML. When imputation is refitted on training data only, the reported RF-over-LR gap shrinks substantially.

**Relevance for this fixture:**
The demo recreates this claim in a small Python port with a deliberate data-preparation pipeline where (1) KNN imputation is fit on the entire dataframe before the train/test split, and (2) the target column remains in the dataframe at imputation time. Both conditions together inflate the baseline headline metric. A Paper Trail agent should identify and fix both aspects.

**Expected honest performance** (for comparison):
- Logistic Regression, test-set AUC: ~0.70
- Random Forest, test-set AUC: ~0.90

**Expected broken/headline performance:**
- Logistic Regression, test-set AUC: ~0.81 (inflated by ~11 points)
- Random Forest, test-set AUC: ~0.96 (inflated by ~5 points)
