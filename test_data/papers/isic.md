# ISIC 2020 — paper summary (for agent ingestion)

**Full citation:** Rotemberg, V., Kurtansky, N., Betz-Stablein, B., Caffery, L., Chousakos, E., Codella, N., Combalia, M., Dusza, S., Guitera, P., Gutman, D., Halpern, A., Helba, B., Kittler, H., Kose, K., Langer, S., Lioprys, K., Malvehy, J., Musthaq, S., Nanda, J., Reiter, O., Shih, G., Stratigos, A., Tschandl, P., Weber, J., & Soyer, H. P. (2021). *A patient-centric dataset of images and metadata for identifying melanomas using clinical context.* Scientific Data (Nature), 8(34).

**Primary claim (and challenge):**
The 2020 SIIM-ISIC Melanoma Classification Kaggle challenge released 33,126 dermoscopy images + patient metadata, with a held-out test set. Top submissions report ROC-AUC > 0.95, and many downstream papers that fine-tune on this data report test-set ROC-AUC in the 0.70–0.90 range depending on architecture and features used.

**Dataset:** Dermoscopic images of skin lesions (melanoma vs benign) with associated metadata: patient ID, age, sex, anatomical site, image name, and image hash. Prevalence is 1.8% melanoma in the public training split.

**Documented critique:**
- At least **425 exact-duplicate images** are documented in the public ISIC 2020 training set (same image appearing twice with different names; community-reported via GitHub issues on the challenge repository).
- Additional perceptual near-duplicates (same lesion imaged from slightly different angles or with different compression) push the effective duplicate rate higher.
- Patient-level overlap also exists: many patients contribute multiple images, and without patient-level splits the same patient's lesions can appear in both train and test folds.

**Relevance for this fixture:**
The demo recreates a minimal metadata-plus-image-features classifier using a synthetic schema that mirrors the real ISIC 2020 metadata layout. The dataset ships with 15% injected exact duplicates (by `image_hash`). The baseline `prepare_data.py` splits directly without deduplication. A Paper Trail agent should detect the duplicate hashes and patch the pipeline to `drop_duplicates(subset=["image_hash"])` before the split.

**Expected honest performance:**
- Random Forest, test-set AUC after dedup: ~0.65

**Expected broken/headline performance:**
- Random Forest, test-set AUC before dedup: ~0.72 (inflated by duplicate memorization)
