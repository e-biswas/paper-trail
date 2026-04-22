"""
Generate a synthetic civil-war-onset panel dataset.

Mirrors the structure of Muchlinski et al. (2016): country-year observations
with missing values, civil war onset as a rare binary outcome (~3% prevalence).
The feature set, missingness pattern, and noisy causal structure are designed
so that iterative imputation fit on the full dataframe (before train/test split)
leaks meaningful information — letting Random Forest exploit non-linear patterns
in imputed values that are unavailable to a properly-fit train-only imputer.

Deterministic: seeded with RANDOM_STATE. Re-run to regenerate civilwar.csv.
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

RANDOM_STATE = 42
N_COUNTRIES = 150
YEARS = range(1960, 2020)
TARGET_PREVALENCE_MIN = 0.02
TARGET_PREVALENCE_MAX = 0.12
MISSING_RATE = 0.20
N_ROWS = 3000

NUMERIC_WITH_MISSING = [
    "gdp_per_capita",
    "gdp_growth_rate",
    "population_log",
    "ethnic_frac",
    "oil_exports_pct",
    "polity_score",
    "years_since_war",
    "arms_imports",
    "infant_mortality",
    "primary_education_ratio",
]


def generate() -> pd.DataFrame:
    rng = np.random.default_rng(RANDOM_STATE)
    rows = []

    for country in range(1, N_COUNTRIES + 1):
        dev = rng.normal(0, 1)
        institutional = rng.normal(0, 1)
        ethnic_heterogeneity = rng.beta(2, 5)

        for year in YEARS:
            gdp_pc = np.exp(8.0 + dev + 0.02 * (year - 1990) + rng.normal(0, 0.3))
            gdp_growth = 0.02 + 0.01 * dev + rng.normal(0, 0.04)
            population_log = np.log(1e6 * np.exp(1.5 + 0.5 * dev)) + rng.normal(0, 0.1)
            prior_war = 1 if rng.random() < 0.08 else 0
            neighbor_war = 1 if rng.random() < 0.12 else 0
            ethnic_frac = float(np.clip(ethnic_heterogeneity + rng.normal(0, 0.05), 0, 1))
            mountain_terrain = float(rng.uniform(0, 1))
            oil_exports_pct = float(rng.exponential(0.1)) if rng.random() < 0.4 else 0.0
            polity_score = float(np.clip(2 * institutional + rng.normal(0, 3), -10, 10))
            years_since_war = int(rng.integers(0, 30))
            arms_imports = float(rng.exponential(100))
            infant_mortality = float(np.exp(4.0 - dev + rng.normal(0, 0.3)))
            primary_edu_ratio = float(np.clip(0.6 + 0.2 * dev + rng.normal(0, 0.1), 0, 1))

            # Deliberately LINEAR DGP: logistic regression is Bayes-optimal
            # here. Random Forest has nothing to gain over LR on clean data.
            # The only way RF can beat LR is by exploiting imputation leakage
            # — which is the bug we want the agent to find.
            logit = (
                -3.2
                + 1.6 * prior_war
                + 1.1 * neighbor_war
                - 8.0 * gdp_growth
                + 1.8 * ethnic_frac
                + 0.7 * mountain_terrain
                + 0.8 * oil_exports_pct
                - 0.08 * polity_score
                + 0.002 * infant_mortality
                - 0.7 * primary_edu_ratio
                - 0.02 * years_since_war
                + rng.normal(0, 0.35)
            )
            p = 1.0 / (1.0 + np.exp(-logit))
            onset = 1 if rng.random() < p else 0

            rows.append({
                "country_id": country,
                "year": year,
                "gdp_per_capita": gdp_pc,
                "gdp_growth_rate": gdp_growth,
                "population_log": population_log,
                "prior_war": prior_war,
                "ethnic_frac": ethnic_frac,
                "mountain_terrain": mountain_terrain,
                "oil_exports_pct": oil_exports_pct,
                "polity_score": polity_score,
                "neighbor_war": neighbor_war,
                "years_since_war": years_since_war,
                "arms_imports": arms_imports,
                "infant_mortality": infant_mortality,
                "primary_education_ratio": primary_edu_ratio,
                "civil_war_onset": onset,
            })

    df = pd.DataFrame(rows)
    df = df.sample(n=N_ROWS, random_state=RANDOM_STATE).reset_index(drop=True)

    # MNAR missingness: conflict-affected rows (onset=1) have substantially
    # higher missingness, because data collection in conflict zones is disrupted.
    # This is what makes full-dataset imputation genuinely leaky: the imputer
    # sees that missing-pattern correlates with onset and uses that signal.
    onset_mask = df["civil_war_onset"] == 1
    for col in NUMERIC_WITH_MISSING:
        rates = np.where(onset_mask, MISSING_RATE * 3.5, MISSING_RATE * 0.6)
        miss = rng.random(len(df)) < rates
        df.loc[miss, col] = np.nan

    return df


def main() -> None:
    df = generate()
    prevalence = df["civil_war_onset"].mean()
    if not (TARGET_PREVALENCE_MIN <= prevalence <= TARGET_PREVALENCE_MAX):
        raise SystemExit(f"Prevalence {prevalence:.4f} out of target band; regen seed or constants.")

    out_path = Path(__file__).parent / "civilwar.csv"
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} rows to {out_path}. Prevalence: {prevalence:.4f}")


if __name__ == "__main__":
    main()
