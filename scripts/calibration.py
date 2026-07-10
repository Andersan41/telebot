"""
scripts/calibration.py — Probability calibration analysis for signal candidates.

Reads walk_forward.py predictions (or runs its own RF calibration) and produces
reliability diagrams, ECE, and calibration metrics.

Usage:
    python scripts/calibration.py [--db data/signals.db] [--splits 5]
    python scripts/calibration.py --from-json scripts/wf_results.json
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler

# Reuse features from walk_forward
sys.path.insert(0, str(Path(__file__).parent))
from walk_forward import FEATURES, REGIME_MAP, load_candidates


def expected_calibration_error(probs: np.ndarray, actuals: np.ndarray, n_bins: int = 10) -> float:
    """Compute Expected Calibration Error (ECE)."""
    bin_edges = np.linspace(0.5, 1.0, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        mask = (probs >= lo) & (probs < hi)
        if i == n_bins - 1:
            mask = (probs >= lo) & (probs <= hi)
        count = mask.sum()
        if count == 0:
            continue
        mean_pred = probs[mask].mean()
        actual_wr = actuals[mask].mean()
        ece += count / len(probs) * abs(mean_pred - actual_wr)
    return float(ece)


def max_calibration_error(probs: np.ndarray, actuals: np.ndarray, n_bins: int = 10) -> float:
    """Compute Max Calibration Error (MCE)."""
    bin_edges = np.linspace(0.5, 1.0, n_bins + 1)
    mce = 0.0
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        mask = (probs >= lo) & (probs < hi)
        if i == n_bins - 1:
            mask = (probs >= lo) & (probs <= hi)
        count = mask.sum()
        if count == 0:
            continue
        mean_pred = probs[mask].mean()
        actual_wr = actuals[mask].mean()
        mce = max(mce, abs(mean_pred - actual_wr))
    return float(mce)


def overconfidence_ratio(probs: np.ndarray, actuals: np.ndarray) -> float:
    """Fraction of predictions where model is overconfident (predicted > actual by >5pp)."""
    overconfident = 0
    n_bins = 10
    bin_edges = np.linspace(0.5, 1.0, n_bins + 1)
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        mask = (probs >= lo) & (probs < hi)
        if i == n_bins - 1:
            mask = (probs >= lo) & (probs <= hi)
        count = mask.sum()
        if count == 0:
            continue
        mean_pred = probs[mask].mean()
        actual_wr = actuals[mask].mean()
        if mean_pred - actual_wr > 0.05:
            overconfident += count
    return overconfident / len(probs) if len(probs) > 0 else 0.0


def run_calibration_pipeline(df: pd.DataFrame, n_splits: int = 5) -> dict:
    """Run calibration pipeline with RF + isotonic on TimeSeriesSplit."""
    X = df[FEATURES].values
    y = df["target"].values
    timestamps = pd.to_datetime(df["timestamp"]).values

    tscv = TimeSeriesSplit(n_splits=n_splits)

    all_probs = []
    all_true = []
    fold_metrics = []

    for fold_num, (train_idx, test_idx) in enumerate(tscv.split(X), 1):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]

        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)

        rf = RandomForestClassifier(
            n_estimators=200, max_depth=5,
            class_weight="balanced", random_state=42, n_jobs=-1,
        )
        rf.fit(X_train_s, y_train)

        calibrated = CalibratedClassifierCV(rf, method="isotonic", cv=3)
        calibrated.fit(X_train_s, y_train)

        probs = calibrated.predict_proba(X_test_s)[:, 1]
        all_probs.extend(probs)
        all_true.extend(y_test)

        # Per-fold calibration
        ece = expected_calibration_error(probs, np.array(y_test))
        fold_metrics.append({
            "fold": fold_num,
            "ece": ece,
            "n_samples": len(test_idx),
        })

    all_probs = np.array(all_probs)
    all_true = np.array(all_true)

    # Overall calibration metrics
    ece = expected_calibration_error(all_probs, all_true)
    mce = max_calibration_error(all_probs, all_true)
    overconf = overconfidence_ratio(all_probs, all_true)

    # Calibration curve data (for plotting)
    fraction_of_positives, mean_predicted_value = calibration_curve(
        all_true, all_probs, n_bins=10, strategy="uniform",
    )

    # Per-regime calibration
    regime_cal = {}
    for regime in df["regime"].dropna().unique():
        mask = df["regime"] == regime
        if mask.sum() < 10:
            continue
        r_probs = all_probs[mask.values[:len(all_probs)]]
        r_true = all_true[mask.values[:len(all_probs)]]
        if len(np.unique(r_true)) > 1:
            regime_cal[regime] = {
                "ece": expected_calibration_error(r_probs, r_true),
                "win_rate": float(r_true.mean()),
                "mean_predicted": float(r_probs.mean()),
                "n": int(mask.sum()),
            }

    return {
        "overall": {
            "ece": float(ece),
            "mce": float(mce),
            "overconfidence_ratio": float(overconf),
            "total_samples": len(all_true),
            "win_rate": float(all_true.mean()),
            "mean_predicted_prob": float(all_probs.mean()),
        },
        "folds": fold_metrics,
        "calibration_curve": {
            "fraction_of_positives": fraction_of_positives.tolist(),
            "mean_predicted_value": mean_predicted_value.tolist(),
        },
        "regime_calibration": regime_cal,
        "predictions": {
            "probs": all_probs.tolist(),
            "actuals": all_true.tolist(),
        },
    }


def print_calibration_report(results: dict):
    """Print formatted calibration report."""
    o = results["overall"]
    print("\n=== Probability Calibration Report ===\n")
    print(f"Total samples:       {o['total_samples']}")
    print(f"Actual win rate:     {o['win_rate']:.1%}")
    print(f"Mean predicted prob: {o['mean_predicted_prob']:.1%}")
    print(f"\nCalibration Metrics:")
    print(f"  ECE (Expected Cal. Error):   {o['ece']:.4f}")
    print(f"  MCE (Max Cal. Error):        {o['mce']:.4f}")
    print(f"  Overconfidence ratio:        {o['overconfidence_ratio']:.1%}")

    # Interpretation
    if o['ece'] < 0.05:
        print("\n  -> Well calibrated (ECE < 5%)")
    elif o['ece'] < 0.10:
        print("\n  -> Moderately calibrated (ECE 5-10%)")
    else:
        print("\n  -> Poorly calibrated (ECE > 10%) — model over/under-estimates probability")

    if o['overconfidence_ratio'] > 0.3:
        print("  -> High overconfidence: model often predicts higher probability than actual")

    # Calibration curve
    print("\nCalibration Curve:")
    print(f"  {'Predicted':>10} {'Actual':>10} {'Count':>8}")
    print("  " + "-" * 32)
    fp = results["calibration_curve"]["fraction_of_positives"]
    mpv = results["calibration_curve"]["mean_predicted_value"]
    # Estimate counts from predictions
    probs = np.array(results["predictions"]["probs"])
    for pred, actual in zip(mpv, fp):
        mask = np.abs(probs - pred) < 0.03
        count = mask.sum()
        print(f"  {pred:>10.1%} {actual:>10.1%} {count:>8}")

    # Per-regime calibration
    if results.get("regime_calibration"):
        print("\nPer-Regime Calibration:")
        print(f"  {'Regime':>14} {'ECE':>8} {'WinRate':>10} {'Pred Prob':>10} {'N':>6}")
        print("  " + "-" * 52)
        for regime, data in results["regime_calibration"].items():
            print(f"  {regime:>14} {data['ece']:>8.4f} {data['win_rate']:>10.1%} "
                  f"{data['mean_predicted']:>10.1%} {data['n']:>6}")

    # Per-fold
    print("\nPer-Fold ECE:")
    for f in results["folds"]:
        print(f"  Fold {f['fold']}: ECE={f['ece']:.4f} (n={f['n_samples']})")


def main():
    parser = argparse.ArgumentParser(description="Probability calibration analysis")
    parser.add_argument("--db", default="data/signals.db", help="SQLite database path")
    parser.add_argument("--splits", type=int, default=5, help="Number of time series splits")
    parser.add_argument("--min-outcomes", type=int, default=50, help="Minimum resolved outcomes")
    parser.add_argument("--from-json", default=None, help="Load predictions from walk_forward JSON")
    parser.add_argument("--output", default=None, help="Save results to JSON file")
    args = parser.parse_args()

    if args.from_json:
        with open(args.from_json) as f:
            results = json.load(f)
        print(f"Loaded predictions from {args.from_json}")
    else:
        if not os.path.exists(args.db):
            print(f"Database not found: {args.db}")
            sys.exit(1)

        print(f"Loading candidates from {args.db}...")
        df = load_candidates(args.db, args.min_outcomes)
        print(f"Loaded {len(df)} resolved outcomes")

        if len(df) < args.min_outcomes:
            print(f"Not enough data (need {args.min_outcomes}). Exiting.")
            sys.exit(1)

        print(f"Running calibration pipeline ({args.splits} splits)...")
        results = run_calibration_pipeline(df, args.splits)

    print_calibration_report(results)

    if args.output:
        output = {k: v for k, v in results.items() if k != "predictions"}
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
