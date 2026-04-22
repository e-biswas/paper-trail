"""
Generate a synthetic ISIC-2020-style dermoscopy dataset.

Mirrors the ISIC 2020 Challenge metadata schema (one row per image) with
handcrafted image-statistic features instead of pixel data — small and fast
enough to run in a laptop-grade demo, but realistic enough to surface the
known duplicate-image leakage bug.

Bug structure: 15% of the dataset consists of exact duplicates
(same image_hash + same features + same target, but different image_id),
simulating the 400+ documented duplicates in the real ISIC 2020 train set.

Deterministic: seeded with RANDOM_STATE.
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

RANDOM_STATE = 42
N_UNIQUE = 3500
DUP_RATE = 0.15  # fraction of rows that are duplicates of other rows
N_PATIENTS = 1800

ANATOM_SITES = ["torso", "upper_extremity", "lower_extremity", "head_neck", "palms_soles", "oral_genital"]


def _sample_image_features(rng: np.random.Generator, benign: bool) -> dict:
    # Weak class separation: features overlap substantially between classes.
    # Clean-data ROC-AUC sits around 0.70; the duplicate leakage drives it up
    # dramatically by letting RF memorize images it sees during training
    # and recognize again in the test fold.
    shift = 0.0 if benign else 0.45
    return {
        "mean_intensity": float(np.clip(rng.normal(130 - 10 * shift, 35), 0, 255)),
        "std_intensity": float(np.clip(rng.normal(20 + 5 * shift, 15), 0, 80)),
        "skewness": float(rng.normal(-0.1 + 0.15 * shift, 1.2)),
        "kurtosis": float(rng.normal(2.8 + 0.2 * shift, 1.5)),
        "red_mean": float(np.clip(rng.normal(150 - 8 * shift, 40), 0, 255)),
        "green_mean": float(np.clip(rng.normal(110 - 6 * shift, 35), 0, 255)),
        "blue_mean": float(np.clip(rng.normal(95 - 4 * shift, 30), 0, 255)),
        "edge_density": float(np.clip(rng.normal(0.12 + 0.03 * shift, 0.10), 0, 1)),
        "symmetry_score": float(np.clip(rng.normal(0.78 - 0.10 * shift, 0.18), 0, 1)),
        "size_pixels": int(rng.integers(40_000, 400_000)) + (int(rng.exponential(30_000)) if not benign else 0),
    }


def generate() -> pd.DataFrame:
    rng = np.random.default_rng(RANDOM_STATE)

    unique_rows = []
    for i in range(N_UNIQUE):
        melanoma = 1 if rng.random() < 0.12 else 0
        features = _sample_image_features(rng, benign=(melanoma == 0))
        patient = int(rng.integers(1, N_PATIENTS + 1))
        age = int(np.clip(rng.normal(58, 18), 15, 95))
        sex = int(rng.integers(0, 2))  # 0=F, 1=M
        site = rng.integers(0, len(ANATOM_SITES))
        image_hash = f"hash_{i:06d}_{int(rng.integers(10_000, 99_999))}"

        unique_rows.append({
            "image_name": f"ISIC_{i:07d}",
            "image_hash": image_hash,
            "patient_id": f"IP_{patient:05d}",
            "age_approx": age,
            "sex": sex,
            "anatom_site_general_challenge": ANATOM_SITES[site],
            **features,
            "target": melanoma,
        })

    df_unique = pd.DataFrame(unique_rows)

    # Inject duplicates: pick DUP_RATE * N_UNIQUE rows and copy them with a new
    # image_name but identical hash + features + target. These represent
    # ISIC-style exact duplicates the original challenge team documented.
    n_dups = int(DUP_RATE * N_UNIQUE)
    dup_sources = df_unique.sample(n=n_dups, random_state=RANDOM_STATE).reset_index(drop=True)
    dups = dup_sources.copy()
    dups["image_name"] = [f"ISIC_DUP_{i:07d}" for i in range(n_dups)]

    df = pd.concat([df_unique, dups], ignore_index=True)
    df = df.sample(frac=1.0, random_state=RANDOM_STATE).reset_index(drop=True)
    return df


def main() -> None:
    df = generate()
    out = Path(__file__).parent / "isic_metadata.csv"
    df.to_csv(out, index=False)
    n_hashes = df["image_hash"].nunique()
    print(f"Wrote {len(df)} rows ({n_hashes} unique hashes; {len(df)-n_hashes} duplicates) to {out}.")
    print(f"Melanoma prevalence: {df['target'].mean():.4f}")


if __name__ == "__main__":
    main()
