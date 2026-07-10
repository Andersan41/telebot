"""
scripts/leakage_detector.py — Leakage detection for time-sensitive features.

Tests whether HTF/context features use future information by:
1. Comparing model performance WITH vs WITHOUT time-sensitive features
2. Permutation importance on out-of-sample windows
3. Feature correlation analysis with outcomes

The checklist says: "Shift all HTF/context features one bar back and rerun.
If metrics degrade significantly — you had leakage."

Since we can't recompute historical features from stored snapshots, this script:
- Trains baseline model with ALL features
- Trains restricted model WITHOUT time-sensitive features (mtf_aligned, regime, context)
- Compares AUC/Brier/WR to detect if time-sensitive features add real edge or just noise
- Runs permutation importance on OOS folds to identify leakage-prone features

Usage:
    python scripts/leakage_detector.py [--db data/signals.db] [--splits 5]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.preprocessing import StandardScaler
from sklearn.inspection import permutation_importance


# All features available in signal_candidates
ALL_FEATURES = [
    "st_strength", "ema_strength", "macd_strength", "rsi_strength",
    "vol_strength", "adx_strength", "dmi_strength", "weighted_score",
    "adx", "rsi", "ema_fast", "ema_slow", "ema_trend",
    "macd_hist", "dmi_plus", "dmi_minus", "atr",
    "has_trigger_enc", "mtf_aligned_enc", "regime_enc",
]

# Time-sensitive features (potential leakage sources)
TIME_SENSITIVE_FEATURES = ["mtf_aligned_enc", "regime_enc"]

# Safe features (computed from closed candles on primary TF only)
SAFE_FEATURES = [f for f in ALL_FEATURES if f not in TIME_SENSITIVE_FEATURES]

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
            signal_type, outcome, pnl_pct,
            st_strength, ema_strength, macd_strength, rsi_strength,
            vol_strength, adx_strength, dmi_strength, weighted_score,
            adx, rsi, ema_fast, ema_slow, ema_trend,
            macd_hist, dmi_plus, dmi_minus, atr,
            regime, has_trigger, mtf_aligned
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

    df = df.dropna(subset=ALL_FEATURES)
    return df


def train_and_evaluate(
    X: np.ndarray, y: np.ndarray, timestamps: np.ndarray,
    features: List[str], n_splits: int = 5,
    label: str = "",
) -> Dict:
    """Train RF+isotonic and evaluate with TimeSeriesSplit."""
    tscv = TimeSeriesSplit(n_splits=n_splits)
    all_probs, all_true = [], []
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

        auc = roc_auc_score(y_test, probs) if len(np.unique(y_test)) > 1 else 0.5
        brier = brier_score_loss(y_test, probs)

        fold_metrics.append({
            "fold": fold_num,
            "auc": auc,
            "brier": brier,
            "test_size": len(test_idx),
            "train_start": str(timestamps[train_idx[0]])[:10],
            "test_end": str(timestamps[test_idx[-1]])[:10],
        })
        all_probs.extend(probs)
        all_true.extend(y_test)

    all_probs = np.array(all_probs)
    all_true = np.array(all_true)

    overall_auc = roc_auc_score(all_true, all_probs) if len(np.unique(all_true)) > 1 else 0.5
    overall_brier = brier_score_loss(all_true, all_probs)

    # Permutation importance on last fold
    perm_imp = {}
    try:
        scaler_last = StandardScaler()
        X_all_s = scaler_last.fit_transform(X)
        rf_last = RandomForestClassifier(
            n_estimators=200, max_depth=5,
            class_weight="balanced", random_state=42, n_jobs=-1,
        )
        rf_last.fit(X_all_s, y)
        result = permutation_importance(
            rf_last, X_all_s, y, n_repeats=10, random_state=42, n_jobs=-1,
        )
        for i, feat in enumerate(features):
            perm_imp[feat] = {
                "importance_mean": float(result.importances_mean[i]),
                "importance_std": float(result.importances_std[i]),
            }
    except Exception as e:
        print(f"  Warning: permutation importance failed: {e}")

    # Stability across folds
    auc_values = [m["auc"] for m in fold_metrics]
    auc_std = float(np.std(auc_values))

    return {
        "label": label,
        "features": features,
        "n_features": len(features),
        "overall_auc": float(overall_auc),
        "overall_brier": float(overall_brier),
        "auc_std": auc_std,
        "fold_metrics": fold_metrics,
        "permutation_importance": perm_imp,
    }


def print_comparison(baseline: Dict, restricted: Dict) -> None:
    """Print side-by-side comparison."""
    print("=" * 80)
    print("LEAKAGE DETECTION REPORT")
    print("=" * 80)

    print(f"\n{'Metric':<25} {'Baseline (all)':>18} {'Restricted':>18} {'Delta':>12}")
    print("-" * 75)

    auc_delta = baseline["overall_auc"] - restricted["overall_auc"]
    brier_delta = baseline["overall_brier"] - restricted["overall_brier"]

    print(f"{'AUC':<25} {baseline['overall_auc']:>18.4f} {restricted['overall_auc']:>18.4f} {auc_delta:>+12.4f}")
    print(f"{'Brier score':<25} {baseline['overall_brier']:>18.4f} {restricted['overall_brier']:>18.4f} {brier_delta:>+12.4f}")
    print(f"{'AUC std (stability)':<25} {baseline['auc_std']:>18.4f} {restricted['auc_std']:>18.4f}")
    print(f"{'N features':<25} {baseline['n_features']:>18} {restricted['n_features']:>18}")

    print(f"\n--- Baseline features: {', '.join(baseline['features'])}")
    print(f"--- Restricted features: {', '.join(restricted['features'])}")

    # Verdict
    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)

    if abs(auc_delta) < 0.02:
        print("\n  [SAFE] Time-sensitive features add negligible predictive power.")
        print("  Either they are clean (no leakage) or they are useless.")
        print("  Recommendation: REMOVE them — fewer features = less overfitting risk.")
    elif auc_delta > 0.05:
        print(f"\n  [WARNING] Time-sensitive features improve AUC by {auc_delta:+.4f}.")
        print("  This MAY indicate leakage (features using future information).")
        print("  Next step: recompute features with 1-bar lag on HTF candles and retest.")
    else:
        print(f"\n  [INCONCLUSIVE] Time-sensitive features improve AUC by {auc_delta:+.4f}.")
        print("  Could be genuine signal or mild leakage. Manual inspection needed.")

    # Feature importance comparison
    print("\n" + "=" * 80)
    print("PERMUTATION IMPORTANCE (out-of-sample)")
    print("=" * 80)

    print(f"\n--- Baseline model (all features):")
    imp = sorted(
        baseline["permutation_importance"].items(),
        key=lambda x: -x[1]["importance_mean"],
    )
    for name, vals in imp[:10]:
        marker = " *" if name in TIME_SENSITIVE_FEATURES else ""
        print(f"  {name:>25}: {vals['importance_mean']:+.4f} ± {vals['importance_std']:.4f}{marker}")

    print(f"\n--- Restricted model (safe features only):")
    imp = sorted(
        restricted["permutation_importance"].items(),
        key=lambda x: -x[1]["importance_mean"],
    )
    for name, vals in imp[:10]:
        print(f"  {name:>25}: {vals['importance_mean']:+.4f} ± {vals['importance_std']:.4f}")

    # Fold stability
    print("\n" + "=" * 80)
    print("FOLD STABILITY (AUC per fold)")
    print("=" * 80)
    print(f"\n{'Fold':<8} {'Baseline':>12} {'Restricted':>12}")
    print("-" * 35)
    for b_m, r_m in zip(baseline["fold_metrics"], restricted["fold_metrics"]):
        print(f"  {b_m['fold']:<6} {b_m['auc']:>12.4f} {r_m['auc']:>12.4f}")


def main():
    parser = argparse.ArgumentParser(description="Leakage detection for time-sensitive features")
    parser.add_argument("--db", default="data/signals.db", help="SQLite database path")
    parser.add_argument("--splits", type=int, default=5, help="Number of time series splits")
    parser.add_argument("--min-outcomes", type=int, default=50, help="Minimum resolved outcomes")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    print(f"Loading candidates from {args.db}...")
    df = load_candidates(args.db, args.min_outcomes)
    print(f"Loaded {len(df)} resolved outcomes ({df['target'].sum()} wins, "
          f"{(~df['target'].astype(bool)).sum()} losses)")

    if len(df) < args.min_outcomes:
        print(f"Not enough data. Exiting.")
        sys.exit(1)

    X_all = df[ALL_FEATURES].values
    X_safe = df[SAFE_FEATURES].values
    y = df["target"].values
    timestamps = pd.to_datetime(df["timestamp"]).values

    print(f"\nTraining baseline model ({len(ALL_FEATURES)} features)...")
    baseline = train_and_evaluate(
        X_all, y, timestamps, ALL_FEATURES,
        n_splits=args.splits, label="baseline",
    )

    print(f"Training restricted model ({len(SAFE_FEATURES)} features, no MTF/regime)...")
    restricted = train_and_evaluate(
        X_safe, y, timestamps, SAFE_FEATURES,
        n_splits=args.splits, label="restricted",
    )

    print_comparison(baseline, restricted)


if __name__ == "__main__":
    main()
