"""Full pipeline: prepare data, train RF + LR, report ROC-AUC as JSON."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
from prepare_data import prepare
from train import train_random_forest, train_logistic_regression

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "civilwar.csv"


def main() -> None:
    df = pd.read_csv(DATA_PATH)
    X_train, X_test, y_train, y_test = prepare(df)

    rf = train_random_forest(X_train, y_train)
    lr_model, scaler = train_logistic_regression(X_train, y_train)

    rf_auc = roc_auc_score(y_test, rf.predict_proba(X_test)[:, 1])
    lr_auc = roc_auc_score(y_test, lr_model.predict_proba(scaler.transform(X_test))[:, 1])

    payload = {
        "metric": "AUC",
        "rf": round(float(rf_auc), 4),
        "lr": round(float(lr_auc), 4),
        "context": "Muchlinski civil war onset",
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "prevalence_train": round(float(y_train.mean()), 4),
        "prevalence_test": round(float(y_test.mean()), 4),
    }
    print(f"METRIC_JSON: {json.dumps(payload)}")
    print(f"Random Forest AUC:       {rf_auc:.4f}")
    print(f"Logistic Regression AUC: {lr_auc:.4f}")


if __name__ == "__main__":
    main()
