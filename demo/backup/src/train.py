"""Training helpers: Random Forest classifier on ISIC features."""
from __future__ import annotations

from sklearn.ensemble import RandomForestClassifier

RANDOM_STATE = 42


def train_random_forest(X_train, y_train):
    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=12,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    return model
