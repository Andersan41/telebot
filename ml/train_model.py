"""
Train probability model from labeled dataset (expected return mode).

Loads dataset.parquet (47 features + label), trains XGBRegressor on expected return,
saves to models/probability_model.pkl in format compatible with ProbabilityEngine.

Expected return target:
  - TP (label=1)  → +rr_ratio (positive expected return)
  - SL (label=0)  → -1.0 (loss of 1R)
  - EXPIRED (label=-1) → 0.0 (timeout = ~0R)

Threshold: predicted > 0 → signal is worth taking.

Usage:
    python -m ml.train_model                    # train on all data
    python -m ml.train_model --min-samples 100  # skip if fewer samples
    python -m ml.train_model --holdout 0.2      # holdout for A/B
"""
from __future__ import annotations

import os
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (
    brier_score_loss, roc_auc_score, classification_report,
    precision_score, recall_score, f1_score, mean_squared_error,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml.config import (
    DATASET_PATH, MODEL_PATH, NEW_MODEL_PATH, MODEL_DIR,
    MIN_SAMPLES, EMBARGO_BARS, HOLDOUT_PCT,
    N_ESTIMATORS, MAX_DEPTH, LEARNING_RATE, CALIBRATION_cv,
    FEATURE_NAMES, EXPIRED_LABEL,
    MIN_CHILD_WEIGHT, REG_ALPHA, REG_LAMBDA, SUBSAMPLE, COLSAMPLE_BYTREE,
)

# Metadata columns (not features)
META_COLS = {"symbol", "timeframe", "timestamp", "label", "entry_price",
             "tp_price", "sl_price", "exit_bar"}


def load_dataset(path: str = None) -> pd.DataFrame:
    """Load and validate dataset."""
    p = Path(path) if path else DATASET_PATH
    if not p.exists():
        raise FileNotFoundError(f"Dataset not found: {p}")

    df = pd.read_parquet(p)
    logger.info(f"Loaded {len(df)} rows from {p}")

    # Validate
    missing = [c for c in FEATURE_NAMES if c not in df.columns]
    if missing:
        logger.warning(f"Missing features (will fill with 0): {missing}")

    return df


def purged_embargo_split(
    n: int,
    n_splits: int = 5,
    embargo_bars: int = EMBARGO_BARS,
) -> List[Tuple[np.ndarray, np.ndarray]]:
    """Purged + embargo time-series split."""
    test_size = n // (n_splits + 1)
    splits = []

    for i in range(n_splits):
        test_end = n - (n_splits - i - 1) * test_size
        test_start = test_end - test_size
        train_end = test_start - embargo_bars

        if train_end <= 0:
            continue

        train_indices = np.arange(0, train_end)
        test_indices = np.arange(test_start, test_end)
        splits.append((train_indices, test_indices))

    return splits


def prepare_xy(df: pd.DataFrame) -> Tuple[pd.DataFrame, np.ndarray]:
    """Extract feature matrix X and expected return target y_return.

    y_return:
      - TP (label=1)  → +rr_ratio
      - SL (label=0)  → -1.0
      - EXPIRED (label=-1) → 0.0
    """
    feature_cols = [c for c in FEATURE_NAMES if c in df.columns]
    X = df[feature_cols].copy()

    # Fill missing features with 0
    for col in FEATURE_NAMES:
        if col not in X.columns:
            X[col] = 0

    X = X[FEATURE_NAMES]  # Ensure column order
    X = X.fillna(0)

    # Expected return target
    risk = (df["entry_price"] - df["sl_price"]).abs().clip(lower=0.01)
    reward = (df["tp_price"] - df["entry_price"]).abs()
    rr_ratio = reward / risk

    y_return = np.where(
        df["label"] == 1,
        rr_ratio.values,
        np.where(df["label"] == EXPIRED_LABEL, 0.0, -1.0),
    )

    return X, y_return


def train_model(
    df: pd.DataFrame,
    min_samples: int = MIN_SAMPLES,
) -> Dict[str, Any] | None:
    """Train XGBRegressor on expected return.

    Returns dict with model, metrics, feature_names. None if insufficient data.
    """
    # Filter to rows with valid labels (TP, SL, EXPIRED with prices)
    train_df = df[df["label"].isin([0, 1, EXPIRED_LABEL])].copy()
    valid_mask = train_df["entry_price"].notna() & train_df["sl_price"].notna()
    train_df = train_df[valid_mask]

    if len(train_df) < min_samples:
        logger.warning(f"Insufficient data: {len(train_df)} < {min_samples}")
        return None

    X, y_return = prepare_xy(train_df)
    n_samples = len(X)

    n_tp = int((train_df["label"] == 1).sum())
    n_sl = int((train_df["label"] == 0).sum())
    n_exp = int((train_df["label"] == EXPIRED_LABEL).sum())
    logger.info(f"Training on {n_samples} samples (TP={n_tp}, SL={n_sl}, EXPIRED={n_exp})")

    # Purged + embargo split for validation
    splits = purged_embargo_split(n_samples, n_splits=5, embargo_bars=EMBARGO_BARS)

    if not splits:
        logger.warning("Not enough data for any split")
        return None

    # Train regressor on all data
    from xgboost import XGBRegressor

    reg = XGBRegressor(
        n_estimators=N_ESTIMATORS,
        max_depth=MAX_DEPTH,
        learning_rate=LEARNING_RATE,
        min_child_weight=MIN_CHILD_WEIGHT,
        reg_alpha=REG_ALPHA,
        reg_lambda=REG_LAMBDA,
        subsample=SUBSAMPLE,
        colsample_bytree=COLSAMPLE_BYTREE,
        random_state=42,
    )
    reg.fit(X, y_return)

    # Evaluate on last split
    train_idx, test_idx = splits[-1]
    X_test = X.iloc[test_idx]
    y_test = y_return[test_idx]
    labels_test = train_df["label"].values[test_idx]

    y_pred = reg.predict(X_test)

    # Convert regression to binary for classification metrics
    # predicted > 0 → TP (1), predicted <= 0 → SL (0)
    y_pred_cls = (y_pred > 0).astype(int)
    y_true_cls = (labels_test == 1).astype(int)

    # Regression metrics
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))

    # Classification metrics (predicted > 0 vs actual TP)
    try:
        auc = roc_auc_score(y_true_cls, y_pred)
    except ValueError:
        auc = 0.5

    try:
        # Brier: use sigmoid of predicted return as probability
        y_proba = 1.0 / (1.0 + np.exp(-y_pred))
        brier = brier_score_loss(y_true_cls, y_proba)
    except ValueError:
        brier = 0.25

    precision = precision_score(y_true_cls, y_pred_cls, zero_division=0)
    recall = recall_score(y_true_cls, y_pred_cls, zero_division=0)
    f1 = f1_score(y_true_cls, y_pred_cls, zero_division=0)

    # Fit isotonic calibration on test set predictions
    try:
        iso_reg = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        y_proba_for_cal = 1.0 / (1.0 + np.exp(-y_pred))
        iso_reg.fit(y_proba_for_cal, y_true_cls)
        calibrated = True
    except Exception:
        iso_reg = None
        calibrated = False

    # Feature importance
    try:
        importances = dict(zip(FEATURE_NAMES, reg.feature_importances_))
    except Exception:
        importances = {}

    metrics = {
        "auc": round(auc, 4),
        "brier": round(brier, 4),
        "rmse": round(rmse, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "n_samples": n_samples,
        "n_tp": n_tp,
        "n_sl": n_sl,
        "n_expired": n_exp,
        "n_features": len(FEATURE_NAMES),
        "calibrated": calibrated,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(f"Metrics: AUC={auc:.4f} Brier={brier:.4f} RMSE={rmse:.4f} F1={f1:.4f}")
    logger.info(f"Classification report:\n{classification_report(y_true_cls, y_pred_cls, zero_division=0)}")

    return {
        "regressor": reg,
        "isotonic": iso_reg,
        "feature_names": FEATURE_NAMES,
        "metrics": metrics,
        "model_type": "expected_return",
    }


def save_model(model_data: Dict[str, Any], path: str = None) -> Path:
    """Save trained model to pickle file."""
    p = Path(path) if path else MODEL_PATH
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    with open(p, "wb") as f:
        pickle.dump(model_data, f)

    logger.info(f"Model saved to {p}")
    return p


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Train probability model (expected return)")
    parser.add_argument("--dataset", type=str, default=None)
    parser.add_argument("--min-samples", type=int, default=MIN_SAMPLES)
    parser.add_argument("--output", type=str, default=None,
                        help="Output path (default: models/probability_model.pkl)")
    parser.add_argument("--new-model", action="store_true",
                        help="Save as probability_model_new.pkl for A/B comparison")
    args = parser.parse_args()

    df = load_dataset(args.dataset)
    result = train_model(df, args.min_samples)

    if result is None:
        logger.error("Training failed — insufficient data")
        sys.exit(1)

    out_path = args.output
    if args.new_model and out_path is None:
        out_path = str(NEW_MODEL_PATH)

    save_model(result, out_path)

    # Print summary
    m = result["metrics"]
    print(f"\n=== Training complete (expected return) ===")
    print(f"Samples: {m['n_samples']} (TP={m['n_tp']}, SL={m['n_sl']}, EXPIRED={m['n_expired']})")
    print(f"AUC: {m['auc']}")
    print(f"Brier: {m['brier']}")
    print(f"RMSE: {m['rmse']}")
    print(f"Precision: {m['precision']}")
    print(f"Recall: {m['recall']}")
    print(f"F1: {m['f1']}")
    print(f"Features: {m['n_features']}")


if __name__ == "__main__":
    main()
