"""
A/B compare current and new ML models.

Loads both models, runs on holdout data, compares metrics.
Optionally replaces production model if new one is better.

Usage:
    python -m ml.ab_compare              # compare only
    python -m ml.ab_compare --apply      # replace if better
"""
from __future__ import annotations

import os
import pickle
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.metrics import brier_score_loss, roc_auc_score

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml.config import (
    DATASET_PATH, MODEL_PATH, NEW_MODEL_PATH, MODEL_DIR,
    HOLDOUT_PCT, FEATURE_NAMES,
)


def load_model(path: Path) -> Optional[Dict[str, Any]]:
    """Load model from pickle. Returns None if not found."""
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


def get_holdout(df: pd.DataFrame, pct: float = HOLDOUT_PCT) -> pd.DataFrame:
    """Get last pct% of data as holdout set."""
    n = len(df)
    split_idx = int(n * (1 - pct))
    return df.iloc[split_idx:]


def evaluate_model(
    model_data: Dict[str, Any],
    X: pd.DataFrame,
    y_true: np.ndarray,
) -> Dict[str, float]:
    """Evaluate model on data. Returns metrics dict."""
    clf = model_data.get("classifier")
    if clf is None:
        return {}

    feature_names = model_data.get("feature_names", FEATURE_NAMES)
    X_aligned = X.reindex(columns=feature_names, fill_value=0)

    try:
        y_proba = clf.predict_proba(X_aligned)[:, 1]
    except Exception as e:
        logger.error(f"Prediction failed: {e}")
        return {}

    try:
        auc = roc_auc_score(y_true, y_proba)
    except ValueError:
        auc = 0.5

    try:
        brier = brier_score_loss(y_true, y_proba)
    except ValueError:
        brier = 0.25

    # Calibration error
    n_bins = 10
    bin_edges = np.linspace(0, 1, n_bins + 1)
    cal_error = 0.0
    for i in range(n_bins):
        mask = (y_proba >= bin_edges[i]) & (y_proba < bin_edges[i + 1])
        if mask.sum() > 0:
            bin_true = y_true[mask].mean()
            bin_pred = y_proba[mask].mean()
            cal_error += abs(bin_true - bin_pred) * mask.sum() / len(y_true)

    return {
        "auc": round(auc, 4),
        "brier": round(brier, 4),
        "calibration_error": round(cal_error, 4),
        "n_samples": len(y_true),
        "n_tp": int(y_true.sum()),
        "n_sl": int(len(y_true) - y_true.sum()),
    }


def compare_models(
    current: Dict[str, Any],
    new: Dict[str, Any],
    holdout_df: pd.DataFrame,
) -> Tuple[Dict, Dict, bool]:
    """Compare two models on holdout data.

    Returns (current_metrics, new_metrics, new_is_better).
    """
    meta_cols = {"symbol", "timeframe", "timestamp", "label", "entry_price",
                 "tp_price", "sl_price", "exit_bar"}
    feature_cols = [c for c in holdout_df.columns if c not in meta_cols]
    X = holdout_df[feature_cols].fillna(0)
    y = (holdout_df["label"] == 1).astype(int).values

    current_metrics = evaluate_model(current, X, y)
    new_metrics = evaluate_model(new, X, y)

    if not current_metrics or not new_metrics:
        return current_metrics, new_metrics, False

    # Decision criteria:
    # 1. AUC improvement > 0.01
    # 2. Brier improvement (lower is better)
    # 3. Calibration error improvement
    auc_better = new_metrics["auc"] > current_metrics["auc"] + 0.01
    brier_better = new_metrics["brier"] < current_metrics["brier"]
    cal_better = new_metrics["calibration_error"] < current_metrics["calibration_error"]

    is_better = auc_better and (brier_better or cal_better)

    return current_metrics, new_metrics, is_better


def apply_new_model() -> None:
    """Replace production model with new model."""
    if not NEW_MODEL_PATH.exists():
        logger.error(f"New model not found: {NEW_MODEL_PATH}")
        return

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # Backup current
    if MODEL_PATH.exists():
        backup = MODEL_PATH.with_suffix(f".bak_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.pkl")
        shutil.copy2(MODEL_PATH, backup)
        logger.info(f"Backup: {backup}")

    # Replace
    shutil.copy2(NEW_MODEL_PATH, MODEL_PATH)
    NEW_MODEL_PATH.unlink(missing_ok=True)
    logger.info(f"Production model updated: {MODEL_PATH}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="A/B compare ML models")
    parser.add_argument("--apply", action="store_true",
                        help="Replace production model if new is better")
    parser.add_argument("--dataset", type=str, default=None)
    args = parser.parse_args()

    current = load_model(MODEL_PATH)
    new = load_model(NEW_MODEL_PATH)

    if current is None and new is None:
        logger.error("No models found to compare")
        sys.exit(1)

    if current is None:
        logger.info("No current model — applying new model directly")
        if args.apply:
            apply_new_model()
        sys.exit(0)

    if new is None:
        logger.info("No new model found. Nothing to compare.")
        sys.exit(0)

    # Load dataset for holdout
    p = Path(args.dataset) if args.dataset else DATASET_PATH
    if not p.exists():
        logger.error(f"Dataset not found: {p}")
        sys.exit(1)

    df = pd.read_parquet(p)
    holdout = get_holdout(df)
    logger.info(f"Holdout: {len(holdout)} samples")

    current_m, new_m, is_better = compare_models(current, new, holdout)

    print("\n=== A/B Model Comparison ===")
    print(f"{'Metric':<20} {'Current':>10} {'New':>10} {'Better?':>10}")
    print("-" * 55)
    for key in ["auc", "brier", "calibration_error"]:
        c = current_m.get(key, "?")
        n = new_m.get(key, "?")
        if isinstance(c, float) and isinstance(n, float):
            if key == "brier" or key == "calibration_error":
                better = n < c
            else:
                better = n > c
            print(f"{key:<20} {c:>10.4f} {n:>10.4f} {'YES' if better else 'no':>10}")
        else:
            print(f"{key:<20} {c:>10} {n:>10}")

    print(f"\nSamples: current={current_m.get('n_samples', '?')}, new={new_m.get('n_samples', '?')}")
    print(f"Decision: {'NEW MODEL IS BETTER' if is_better else 'Keep current model'}")

    if is_better and args.apply:
        print("\nApplying new model...")
        apply_new_model()
    elif is_better and not args.apply:
        print("\nRun with --apply to replace production model.")
    else:
        print("\nKeeping current model.")


if __name__ == "__main__":
    main()
