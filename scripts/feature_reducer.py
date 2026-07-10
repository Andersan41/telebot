"""
scripts/feature_reducer.py — Feature reduction via correlation clustering.

The checklist says:
- "Group correlated features and keep one representative per cluster"
- "Rule: >=50-100 trades per feature. At 1138 trades → max ~10-15 features"
- "Evaluate importance via permutation importance on OOS windows, not SHAP on train"

Usage:
    python scripts/feature_reducer.py [--db data/signals.db] [--max-features 12]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Set

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler
from sklearn.inspection import permutation_importance
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform


ALL_FEATURES = [
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
            st_strength, ema_strength, macd_strength, rsi_strength,
            vol_strength, adx_strength, dmi_strength, weighted_score,
            adx, rsi, ema_fast, ema_slow, ema_trend,
            macd_hist, dmi_plus, dmi_minus, atr,
            regime, has_trigger, mtf_aligned,
            outcome, pnl_pct, timestamp
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


def cluster_features(
    df: pd.DataFrame, features: List[str], threshold: float = 0.7
) -> Dict[str, List[str]]:
    """Cluster features by correlation and select representatives.

    Uses hierarchical clustering on absolute correlation matrix.
    Features with |corr| > threshold are grouped together.
    The representative is the feature with highest permutation importance.
    """
    corr = df[features].corr().abs()
    # Convert correlation to distance
    dist = 1 - corr
    np.fill_diagonal(dist.values, 0)

    # Ensure symmetric
    dist_sym = (dist + dist.T) / 2

    # Hierarchical clustering
    condensed = squareform(dist_sym.values, checks=False)
    Z = linkage(condensed, method="average")

    # Cut at threshold
    labels = fcluster(Z, t=1 - threshold, criterion="distance")

    clusters: Dict[int, List[str]] = {}
    for feat, label in zip(features, labels):
        clusters.setdefault(label, []).append(feat)

    return {f"cluster_{k}": v for k, v in clusters.items()}


def select_representatives(
    df: pd.DataFrame, clusters: Dict[str, List[str]], y: np.ndarray
) -> List[str]:
    """Select the best representative from each cluster using permutation importance."""
    representatives = []

    X = df[list(set(f for cl in clusters.values() for f in cl))].values
    scaler = StandardScaler()
    X_s = scaler.fit_transform(X)

    rf = RandomForestClassifier(n_estimators=100, max_depth=5, class_weight="balanced",
                                random_state=42, n_jobs=-1)
    rf.fit(X_s, y)

    all_feats = [f for cl in clusters.values() for f in cl]
    result = permutation_importance(rf, X_s, y, n_repeats=5, random_state=42, n_jobs=-1)
    imp_map = {f: result.importances_mean[i] for i, f in enumerate(all_feats)}

    for cluster_name, feats in clusters.items():
        best = max(feats, key=lambda f: imp_map.get(f, 0))
        representatives.append(best)

    return representatives


def evaluate_feature_set(
    df: pd.DataFrame, features: List[str], y: np.ndarray,
    timestamps: np.ndarray, n_splits: int = 5,
) -> Dict:
    """Evaluate a feature set with walk-forward."""
    X = df[features].values
    tscv = TimeSeriesSplit(n_splits=n_splits)
    all_probs, all_true = [], []

    for train_idx, test_idx in tscv.split(X):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]

        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)

        rf = RandomForestClassifier(n_estimators=200, max_depth=5,
                                    class_weight="balanced", random_state=42, n_jobs=-1)
        rf.fit(X_train_s, y_train)

        calibrated = CalibratedClassifierCV(rf, method="isotonic", cv=3)
        calibrated.fit(X_train_s, y_train)
        probs = calibrated.predict_proba(X_test_s)[:, 1]

        all_probs.extend(probs)
        all_true.extend(y_test)

    all_probs = np.array(all_probs)
    all_true = np.array(all_true)

    auc = roc_auc_score(all_true, all_probs) if len(np.unique(all_true)) > 1 else 0.5

    return {
        "features": features,
        "n_features": len(features),
        "auc": float(auc),
        "n_samples": len(all_true),
    }


def main():
    parser = argparse.ArgumentParser(description="Feature reduction via correlation clustering")
    parser.add_argument("--db", default="data/signals.db")
    parser.add_argument("--max-features", type=int, default=12,
                        help="Max features to keep (rule: 50-100 trades per feature)")
    parser.add_argument("--corr-threshold", type=float, default=0.7,
                        help="Correlation threshold for clustering")
    parser.add_argument("--min-outcomes", type=int, default=50)
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    print(f"Loading candidates from {args.db}...")
    df = load_candidates(args.db, args.min_outcomes)
    print(f"Loaded {len(df)} resolved outcomes")
    print(f"Rule: {len(df)} trades / 100 = max {len(df) // 100} features recommended")

    y = df["target"].values
    timestamps = pd.to_datetime(df["timestamp"]).values

    # Step 1: Correlation matrix
    print(f"\n--- Correlation Analysis ---")
    corr = df[ALL_FEATURES].corr()
    high_corr_pairs = []
    for i, f1 in enumerate(ALL_FEATURES):
        for j, f2 in enumerate(ALL_FEATURES):
            if i < j and abs(corr.loc[f1, f2]) > 0.7:
                high_corr_pairs.append((f1, f2, corr.loc[f1, f2]))

    if high_corr_pairs:
        print(f"\n  High correlation pairs (|r| > 0.7):")
        for f1, f2, r in sorted(high_corr_pairs, key=lambda x: -abs(x[2])):
            print(f"    {f1:>25} ↔ {f2:<25} r={r:+.3f}")
    else:
        print("  No highly correlated pairs found.")

    # Step 2: Cluster
    print(f"\n--- Feature Clustering (threshold={args.corr_threshold}) ---")
    clusters = cluster_features(df, ALL_FEATURES, args.corr_threshold)
    for name, feats in clusters.items():
        print(f"  {name}: {', '.join(feats)}")

    # Step 3: Select representatives
    print(f"\n--- Selecting Representatives ---")
    representatives = select_representatives(df, clusters, y)
    print(f"  Selected: {', '.join(representatives)}")

    # Step 4: Evaluate reduced set
    print(f"\n--- Evaluating Feature Sets ---")
    baseline = evaluate_feature_set(df, ALL_FEATURES, y, timestamps)
    reduced = evaluate_feature_set(df, representatives, y, timestamps)

    print(f"\n  {'Set':<20} {'N Features':>12} {'AUC':>10}")
    print(f"  {'-'*20} {'-'*12} {'-'*10}")
    print(f"  {'All features':<20} {baseline['n_features']:>12} {baseline['auc']:>10.4f}")
    print(f"  {'Reduced':<20} {reduced['n_features']:>12} {reduced['auc']:>10.4f}")

    auc_delta = reduced["auc"] - baseline["auc"]
    if abs(auc_delta) < 0.02:
        print(f"\n  [GOOD] Reduced set matches baseline (ΔAUC={auc_delta:+.4f})")
        print(f"  Recommendation: use {len(representatives)} features for simpler model")
    elif auc_delta < -0.05:
        print(f"\n  [WARNING] Reduced set degrades AUC by {auc_delta:+.4f}")
        print(f"  Consider increasing max-features or lowering correlation threshold")
    else:
        print(f"\n  [OK] Reduced set slightly improves AUC ({auc_delta:+.4f})")

    # Step 5: Try further reduction if over max_features
    if len(representatives) > args.max_features:
        print(f"\n--- Further Reduction to {args.max_features} features ---")
        # Use permutation importance to rank and keep top N
        X = df[representatives].values
        scaler = StandardScaler()
        X_s = scaler.fit_transform(X)
        rf = RandomForestClassifier(n_estimators=100, max_depth=5, class_weight="balanced",
                                    random_state=42, n_jobs=-1)
        rf.fit(X_s, y)
        result = permutation_importance(rf, X_s, y, n_repeats=5, random_state=42, n_jobs=-1)
        imp = sorted(zip(representatives, result.importances_mean), key=lambda x: -x[1])
        top_features = [f for f, _ in imp[:args.max_features]]
        print(f"  Top {args.max_features}: {', '.join(top_features)}")

        final = evaluate_feature_set(df, top_features, y, timestamps)
        print(f"  AUC with {args.max_features} features: {final['auc']:.4f}")
        representatives = top_features

    print(f"\n--- Final Feature Set ({len(representatives)} features) ---")
    for f in representatives:
        print(f"  - {f}")


if __name__ == "__main__":
    main()
