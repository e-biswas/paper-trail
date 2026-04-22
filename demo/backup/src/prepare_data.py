"""
Data preparation for the ISIC 2020 melanoma classification reproduction.

Loads image metadata + handcrafted image features and produces train/test
splits for the classifier.

Reference: Rotemberg, V. et al. (2021). "A patient-centric dataset of images
and metadata for identifying melanomas using clinical context."
Scientific Data (Nature); accompanies the SIIM-ISIC 2020 Kaggle challenge.
"""
from __future__ import annotations

import pandas as pd
from sklearn.model_selection import train_test_split

TARGET = "target"
ID_COLS = ["image_name", "image_hash", "patient_id"]
CATEGORICAL = ["anatom_site_general_challenge"]
RANDOM_STATE = 42


def prepare(df: pd.DataFrame, test_size: float = 0.2):
    """Split metadata + image features into train/test.

    Returns (X_train, X_test, y_train, y_test).
    """
    df = df.copy()

    # One-hot encode the anatomical-site categorical.
    df = pd.get_dummies(df, columns=CATEGORICAL, drop_first=True)

    y = df[TARGET]
    X = df.drop(columns=[TARGET, *ID_COLS])

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=test_size,
        random_state=RANDOM_STATE,
        stratify=y,
    )
    return X_train, X_test, y_train, y_test
