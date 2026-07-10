"""
scripts/walk_forward.py — Walk-forward validation with purged+embargo splits.

Improvements over basic TimeSeriesSplit:
- Purged split: gap between train/test to prevent triple-barrier label leakage
- Embargo: configurable embargo period >= max holding period
- Anchored walk-forward: stability analysis across windows
- Permutation importance on OOS (not train-set importance)

Usage:
    python scripts/walk_forward.py [--db data/signals.db] [--splits 5] [--embargo-bars 10]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Iterator, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss
from sklearn.preprocessing import StandardScaler
from sklearn.inspection import permutation_importance


FEATURES = [
    "st_strength", "ema_strength", "macd_strength", "rsi_strength",
    "vol_strength", "adx_strength", "dmi_strength", "weighted_score",
    "adx", "rsi", "ema_fast", "ema_slow", "ema_trend",
    "macd_hist", "dmi_plus", "dmi_minus", "atr",
    "has_trigger_enc", "mtf_aligned_enc", "regime_enc",
]

REGIME_MAP = {"trend": 0, "range": 1, "compression": 2, "expansion": 3, "reversal": 4}


def load_candidates(db_path: str, min_outcomes: int = 50) -> pd.DataFrame:
    """Load candidates with resolved outcomes."""
    conn = sqlite3.connect(db_path)

    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='signal_candidates'"
    )
    if cur.fetchone() is None:
        conn.close()
        print("Table 'signal_candidates' does not exist.")
        sys.exit(1)

    query = """
        SELECT
            symbol, timeframe, timestamp,
            signal_type, rejection_reason, score,
            st_strength, ema_strength, macd_strength, rsi_strength,
            vol_strength, adx_strength, dmi_strength, weighted_score,
            adx, rsi, ema_fast, ema_slow, ema_trend,
            macd_hist, dmi_plus, dmi_minus, atr,
            close_price, regime, has_trigger, mtf_aligned,
            outcome, pnl_pct
        FROM signal_candidates
        WHERE outcome IN ('HIT_TP', 'HIT_SL')
          AND st_strength IS NOT NULL
        ORDER BY timestamp ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if len(df) < min_outcomes:
        print(f"WARNING: Only {len(df)} resolved outcomes (min={min_outcomes}).")

    df["target"] = (df["outcome"] == "HIT_TP").astype(int)
    df["regime_enc"] = df["regime"].map(REGIME_MAP).fillna(-1).astype(float)
    df["has_trigger_enc"] = df["has_trigger"].fillna(0).astype(int)
    df["mtf_aligned_enc"] = df["mtf_aligned"].fillna(0).astype(int)
    df = df.dropna(subset=FEATURES)

    return df


def purged_embargo_split(
    timestamps: np.ndarray,
    n_splits: int = 5,
    embargo_bars: int = 10,
) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
    """Generate purged + embargoed time series splits.

    Between train and test: a gap of `embargo_bars` samples is excluded.
    This prevents leakage from triple-barrier labels that span across the boundary.

    Args:
        timestamps: sorted array of timestamps (datetime64)
        n_splits: number of splits
        embargo_bars: number of bars to skip between train end and test start

    Yields:
        (train_idx, test_idx) arrays
    """
    n = len(timestamps)
    # Each fold tests on approximately n / (n_splits + 1) samples
    test_size = n // (n_splits + 1)

    for i in range(n_splits):
        test_end = n - (n_splits - i) * test_size
        test_start = test_end - test_size
        train_end = test_start - embargo_bars

        if train_end <= 0:
            continue

        train_idx = np.arange(0, train_end)
        test_idx = np.arange(test_start, test_end)

        if len(train_idx) > 0 and len(test_idx) > 0:
            yield train_idx, test_idx


def compute_fold_metrics(
    y_true: np.ndarray, probs: np.ndarray,
    train_idx: np.ndarray, test_idx: np.ndarray,
    timestamps: np.ndarray, fold_num: int,
) -> dict:
    """Compute metrics for a single fold."""
    auc = roc_auc_score(y_true, probs) if len(np.unique(y_true)) > 1 else 0.5
    brier = brier_score_loss(y_true, probs)
    ll = log_loss(y_true, probs) if len(np.unique(y_true)) > 1 else float("nan")

    return {
        "fold": fold_num,
        "train_size": len(train_idx),
        "test_size": len(test_idx),
        "train_start": str(timestamps[train_idx[0]])[:10],
        "train_end": str(timestamps[train_idx[-1]])[:10],
        "test_start": str(timestamps[test_idx[0]])[:10],
        "test_end": str(timestamps[test_idx[-1]])[:10],
        "win_rate_train": float(y_true[train_idx].mean()) if len(train_idx) > 0 else 0,
        "win_rate_test": float(y_true[test_idx].mean()) if len(test_idx) > 0 else 0,
        "auc": float(auc),
        "brier": float(brier),
        "log_loss": float(ll),
        "n_samples": len(test_idx),
    }


def run_walk_forward(
    df: pd.DataFrame,
    n_splits: int = 5,
    embargo_bars: int = 10,
    n_estimators: int = 200,
    max_depth: int = 5,
) -> dict:
    """Run walk-forward with purged+embargo splits."""
    X = df[FEATURES].values
    y = df["target"].values
    timestamps = pd.to_datetime(df["timestamp"]).values

    all_probs = []
    all_true = []
    all_fold_metrics = []

    for fold_num, (train_idx, test_idx) in enumerate(
        purged_embargo_split(timestamps, n_splits, embargo_bars), 1
    ):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]

        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)

        rf = RandomForestClassifier(
            n_estimators=n_estimators, max_depth=max_depth,
            class_weight="balanced", random_state=42, n_jobs=-1,
        )
        rf.fit(X_train_s, y_train)

        calibrated = CalibratedClassifierCV(rf, method="isotonic", cv=3)
        calibrated.fit(X_train_s, y_train)
        probs = calibrated.predict_proba(X_test_s)[:, 1]

        metrics = compute_fold_metrics(y, probs, train_idx, test_idx, timestamps, fold_num)
        all_fold_metrics.append(metrics)
        all_probs.extend(probs)
        all_true.extend(y_test)

        print(f"Fold {fold_num}: AUC={metrics['auc']:.3f} Brier={metrics['brier']:.4f} "
              f"train={len(train_idx)} test={len(test_idx)} "
              f"[{metrics['train_start']}→{metrics['train_end']} | "
              f"{metrics['test_start']}→{metrics['test_end']}]")

    all_probs = np.array(all_probs)
    all_true = np.array(all_true)

    overall_auc = roc_auc_score(all_true, all_probs) if len(np.unique(all_true)) > 1 else 0.5
    overall_brier = brier_score_loss(all_true, all_probs)

    # Permutation importance on last fold
    perm_imp = {}
    try:
        last_train_idx, last_test_idx = list(
            purged_embargo_split(timestamps, n_splits, embargo_bars)
        )[-1]
        scaler_last = StandardScaler()
        X_last_train_s = scaler_last.fit_transform(X[last_train_idx])
        X_last_test_s = scaler_last.transform(X[last_test_idx])

        rf_last = RandomForestClassifier(
            n_estimators=n_estimators, max_depth=max_depth,
            class_weight="balanced", random_state=42, n_jobs=-1,
        )
        rf_last.fit(X_last_train_s, y[last_train_idx])

        result = permutation_importance(
            rf_last, X_last_test_s, y[last_test_idx],
            n_repeats=10, random_state=42, n_jobs=-1,
        )
        for i, feat in enumerate(FEATURES):
            perm_imp[feat] = {
                "importance_mean": float(result.importances_mean[i]),
                "importance_std": float(result.importances_std[i]),
            }
    except Exception as e:
        print(f"  Warning: permutation importance failed: {e}")

    return {
        "folds": all_fold_metrics,
        "overall": {
            "auc": float(overall_auc),
            "brier": float(overall_brier),
            "total_samples": len(all_true),
            "win_rate": float(all_true.mean()),
            "n_folds": len(all_fold_metrics),
        },
        "permutation_importance": perm_imp,
        "predictions": {
            "probs": all_probs.tolist(),
            "actuals": all_true.tolist(),
        },
    }


def analyze_stability(fold_metrics: list[dict]) -> dict:
    """Analyze stability of metrics across folds.

    The checklist says: "Look at stability between windows, not average metric.
    A strategy with PF 1.4 in 6/8 windows is more interesting than PF 3.0 in 2 and 0.7 in 6."
    """
    auc_values = [m["auc"] for m in fold_metrics]
    brier_values = [m["brier"] for m in fold_metrics]

    auc_mean = float(np.mean(auc_values))
    auc_std = float(np.std(auc_values))
    auc_cv = auc_std / auc_mean if auc_mean > 0 else float("inf")

    # Count "good" folds (AUC > 0.5 = better than random)
    good_folds = sum(1 for a in auc_values if a > 0.5)
    total_folds = len(auc_values)

    # Consistency: fraction of folds where AUC > 0.5
    consistency = good_folds / total_folds if total_folds > 0 else 0

    return {
        "auc_mean": auc_mean,
        "auc_std": auc_std,
        "auc_cv": auc_cv,
        "auc_min": float(np.min(auc_values)),
        "auc_max": float(np.max(auc_values)),
        "good_folds": good_folds,
        "total_folds": total_folds,
        "consistency": consistency,
        "auc_values": [float(v) for v in auc_values],
        "verdict": (
            "STABLE" if consistency >= 0.8 and auc_cv < 0.15
            else "ACCEPTABLE" if consistency >= 0.6
            else "UNSTABLE"
        ),
    }


def print_calibration_table(probs: np.ndarray, actuals: np.ndarray, n_buckets: int = 10):
    """Print calibration table."""
    bins = np.linspace(0.5, 1.0, n_buckets + 1)
    print("\n--- Calibration Table ---")
    print(f"{'Bucket':>12} {'Count':>6} {'Mean Pred':>10} {'Actual WR':>10} {'Gap':>8}")
    print("-" * 50)

    for i in range(n_buckets):
        lo, hi = bins[i], bins[i + 1]
        mask = (probs >= lo) & (probs < hi)
        if i == n_buckets - 1:
            mask = (probs >= lo) & (probs <= hi)
        count = mask.sum()
        if count == 0:
            continue
        mean_pred = probs[mask].mean()
        actual_wr = actuals[mask].mean()
        print(f"  {lo:.0%}-{hi:.0%}  {count:>6} {mean_pred:>10.1%} {actual_wr:>10.1%} "
              f"{mean_pred - actual_wr:>+8.1%}")


def main():
    parser = argparse.ArgumentParser(
        description="Walk-forward validation with purged+embargo splits"
    )
    parser.add_argument("--db", default="data/signals.db", help="SQLite database path")
    parser.add_argument("--splits", type=int, default=5, help="Number of splits")
    parser.add_argument("--embargo-bars", type=int, default=10,
                        help="Embargo bars between train/test (>= max holding period)")
    parser.add_argument("--min-outcomes", type=int, default=50)
    parser.add_argument("--estimators", type=int, default=200)
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    print(f"Loading candidates from {args.db}...")
    df = load_candidates(args.db, args.min_outcomes)
    print(f"Loaded {len(df)} resolved outcomes ({df['target'].sum()} wins, "
          f"{(~df['target'].astype(bool)).sum()} losses)")

    if len(df) < args.min_outcomes:
        print(f"Not enough data (need {args.min_outcomes}). Exiting.")
        sys.exit(1)

    print(f"\nRunning purged+embargo walk-forward "
          f"({args.splits} splits, embargo={args.embargo_bars} bars)...")
    results = run_walk_forward(
        df, args.splits, args.embargo_bars, args.estimators, args.max_depth,
    )

    # Stability analysis
    stability = analyze_stability(results["folds"])
    results["stability"] = stability

    # Calibration table
    probs = np.array(results["predictions"]["probs"])
    actuals = np.array(results["predictions"]["actuals"])
    print_calibration_table(probs, actuals)

    # Summary
    o = results["overall"]
    print(f"\n--- Overall ---")
    print(f"AUC:          {o['auc']:.3f}")
    print(f"Brier score:  {o['brier']:.4f}")
    print(f"Win rate:     {o['win_rate']:.1%}")
    print(f"Total samples: {o['total_samples']}")

    # Stability
    print(f"\n--- Stability Analysis ---")
    print(f"Verdict:      {stability['verdict']}")
    print(f"AUC mean±std: {stability['auc_mean']:.3f} ± {stability['auc_std']:.3f}")
    print(f"AUC range:    [{stability['auc_min']:.3f}, {stability['auc_max']:.3f}]")
    print(f"Consistency:  {stability['good_folds']}/{stability['total_folds']} "
          f"folds with AUC > 0.5 ({stability['consistency']:.0%})")

    if stability["verdict"] == "UNSTABLE":
        print("\n  WARNING: Model is UNSTABLE across folds.")
        print("  This means the edge is not consistent — likely overfitting.")
        print("  Consider: fewer features, simpler model, or more data.")

    # Permutation importance
    if results.get("permutation_importance"):
        print(f"\n--- Permutation Importance (OOS, last fold) ---")
        imp = sorted(
            results["permutation_importance"].items(),
            key=lambda x: -x[1]["importance_mean"],
        )
        for name, vals in imp[:10]:
            print(f"  {name:>25}: {vals['importance_mean']:+.4f} ± {vals['importance_std']:.4f}")

    if args.output:
        output = {k: v for k, v in results.items() if k != "predictions"}
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
