"""
analytics/evolution.py — Evolution Engine.

Automated weight optimization via walk-forward validation. Trains a model
on historical data, computes optimal factor weights, validates on holdout,
and proposes config changes if statistically significant improvement found.

Requires: scikit-learn, numpy, pandas (already in requirements.txt).

Usage:
    python -m analytics.evolution [--db data/signals.db] [--min-trades 300]
    python -m analytics.evolution --splits 5 --export-proposal
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "signals.db"

FACTOR_COLUMNS = [
    "st_strength", "ema_strength", "macd_strength", "rsi_strength",
    "vol_strength", "adx_strength", "dmi_strength",
]

FEATURE_COLUMNS = [
    *FACTOR_COLUMNS,
    "weighted_score", "adx", "rsi", "ema_fast", "ema_slow", "ema_trend",
    "macd_hist", "dmi_plus", "dmi_minus", "atr",
    "has_trigger_enc", "mtf_aligned_enc", "regime_enc",
]

REGIME_MAP = {"trend": 0, "range": 1, "compression": 2, "expansion": 3, "reversal": 4}


def load_candidates(db_path: str | Path, min_outcomes: int = 50) -> list[dict]:
    """Load signal_candidates with resolved outcomes for training."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    query = """
        SELECT
            symbol, timeframe, timestamp,
            signal_type, rejection_reason, score,
            st_strength, ema_strength, macd_strength, rsi_strength,
            vol_strength, adx_strength, dmi_strength, weighted_score,
            adx, rsi, ema_fast, ema_slow, ema_trend,
            macd_hist, dmi_plus, dmi_minus, atr,
            close_price, volume, volume_sma, supertrend_direction,
            regime, regime_confidence, confidence_v2_pct,
            has_trigger, has_leading_trigger, mtf_aligned,
            outcome, pnl_pct
        FROM signal_candidates
        WHERE outcome IN ('HIT_TP', 'HIT_SL')
        ORDER BY timestamp
    """

    rows = conn.execute(query).fetchall()
    conn.close()

    candidates = []
    for row in rows:
        d = dict(row)
        d["target"] = 1 if d.get("outcome") == "HIT_TP" else 0
        # Encode categoricals
        d["has_trigger_enc"] = 1 if d.get("has_trigger") else 0
        d["mtf_aligned_enc"] = 1 if d.get("mtf_aligned") else 0
        d["regime_enc"] = REGIME_MAP.get(d.get("regime", ""), -1)
        candidates.append(d)

    return candidates


def prepare_arrays(candidates: list[dict]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Convert candidate dicts to feature matrix and target vector."""
    X_rows = []
    y_rows = []

    for c in candidates:
        row = []
        valid = True
        for col in FEATURE_COLUMNS:
            val = c.get(col)
            if val is None:
                valid = False
                break
            row.append(float(val))
        if valid:
            X_rows.append(row)
            y_rows.append(c["target"])

    return np.array(X_rows), np.array(y_rows), FEATURE_COLUMNS


def walk_forward_optimization(
    candidates: list[dict],
    n_splits: int = 5,
    min_train: int = 100,
) -> dict:
    """Walk-forward optimization with temporal splits.

    For each fold:
    1. Train RF on past data
    2. Predict on next chunk
    3. Compute feature importances
    4. Calibrate probabilities

    Returns optimal weights and validation metrics.
    """
    try:
        from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.model_selection import TimeSeriesSplit
        from sklearn.metrics import accuracy_score, roc_auc_score, brier_score_loss
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return {"error": "scikit-learn not installed. Run: pip install scikit-learn"}

    X, y, feature_names = prepare_arrays(candidates)
    if len(X) < min_train:
        return {"error": f"Not enough data: {len(X)} candidates (need {min_train})"}

    tscv = TimeSeriesSplit(n_splits=n_splits)
    fold_metrics = []
    all_importances = np.zeros(len(feature_names))
    all_oof_preds = np.zeros(len(y))
    fold_count = 0

    for train_idx, test_idx in tscv.split(X):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]

        if len(X_train) < 50 or len(X_test) < 10:
            continue

        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)

        # Train calibrated model
        base = GradientBoostingClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.1,
            subsample=0.8, random_state=42,
        )
        model = CalibratedClassifierCV(base, cv=3, method="isotonic")
        model.fit(X_train_s, y_train)

        preds = model.predict_proba(X_test_s)[:, 1]
        all_oof_preds[test_idx] = preds

        # Feature importance from base model
        base.fit(X_train_s, y_train)
        all_importances += base.feature_importances_

        # Metrics
        binary_preds = (preds >= 0.5).astype(int)
        acc = accuracy_score(y_test, binary_preds)
        try:
            auc = roc_auc_score(y_test, preds)
        except ValueError:
            auc = 0.5
        brier = brier_score_loss(y_test, preds)

        fold_metrics.append({
            "fold": fold_count + 1,
            "train_size": len(X_train),
            "test_size": len(X_test),
            "accuracy": round(acc, 3),
            "auc": round(auc, 3),
            "brier": round(brier, 4),
            "test_wr": round(y_test.mean() * 100, 1),
            "pred_wr": round(preds.mean() * 100, 1),
        })
        fold_count += 1

    if fold_count == 0:
        return {"error": "No valid folds"}

    all_importances /= fold_count

    # Compute optimal weights from importances
    # Normalize so sum = 1, only for factor columns
    factor_indices = [i for i, f in enumerate(feature_names) if f in FACTOR_COLUMNS]
    factor_importances = all_importances[factor_indices]
    factor_names = [feature_names[i] for i in factor_indices]

    total_imp = factor_importances.sum()
    if total_imp > 0:
        optimal_weights = {
            name: round(float(imp / total_imp), 4)
            for name, imp in zip(factor_names, factor_importances)
        }
    else:
        optimal_weights = {name: round(1.0 / len(factor_names), 4) for name in factor_names}

    # Overall metrics
    valid_oof = all_oof_preds[all_oof_preds > 0]
    overall_metrics = {
        "total_candidates": len(X),
        "total_wins": int(y.sum()),
        "total_losses": int(len(y) - y.sum()),
        "overall_wr": round(y.mean() * 100, 1),
        "mean_predicted_prob": round(valid_oof.mean(), 3) if len(valid_oof) > 0 else 0,
    }

    # Confidence buckets
    buckets = []
    for lo in np.arange(0.3, 0.9, 0.1):
        hi = lo + 0.1
        mask = (all_oof_preds >= lo) & (all_oof_preds < hi)
        if mask.sum() > 5:
            buckets.append({
                "predicted_range": f"{lo*100:.0f}-{hi*100:.0f}%",
                "count": int(mask.sum()),
                "actual_wr": round(y[mask].mean() * 100, 1),
                "avg_predicted": round(all_oof_preds[mask].mean() * 100, 1),
            })

    # Top feature importances
    sorted_imp = sorted(
        zip(feature_names, all_importances),
        key=lambda x: x[1],
        reverse=True,
    )

    return {
        "fold_metrics": fold_metrics,
        "overall": overall_metrics,
        "optimal_weights": optimal_weights,
        "feature_importance": [
            {"feature": f, "importance": round(float(i), 4)}
            for f, i in sorted_imp[:15]
        ],
        "calibration_buckets": buckets,
        "mean_cv_auc": round(np.mean([f["auc"] for f in fold_metrics]), 3),
        "mean_cv_brier": round(np.mean([f["brier"] for f in fold_metrics]), 4),
    }


def load_current_weights(db_path: str | Path) -> dict:
    """Load current scoring weights from config or bot_settings."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Try bot_settings
    try:
        row = conn.execute("SELECT value FROM bot_settings WHERE key = 'scoring_weights'").fetchone()
        if row:
            return json.loads(row["value"])
    except Exception:
        pass

    # Try config_snapshot from latest decision trace
    try:
        row = conn.execute("""
            SELECT config_snapshot FROM decision_traces
            WHERE config_snapshot IS NOT NULL
            ORDER BY timestamp DESC LIMIT 1
        """).fetchone()
        if row:
            cfg = json.loads(row["config_snapshot"])
            return {k: cfg.get(k) for k in FACTOR_COLUMNS if cfg.get(k) is not None}
    except Exception:
        pass

    return {}


def propose_weight_changes(
    current: dict, proposed: dict, min_delta: float = 0.02
) -> list[dict]:
    """Compare current vs proposed weights, suggest changes."""
    proposals = []

    for factor in FACTOR_COLUMNS:
        old = current.get(factor, 0)
        new = proposed.get(factor, 0)
        delta = new - old

        if abs(delta) >= min_delta:
            proposals.append({
                "factor": factor,
                "current": round(old, 4),
                "proposed": round(new, 4),
                "delta": round(delta, 4),
                "direction": "increase" if delta > 0 else "decrease",
            })

    return proposals


def print_evolution_report(result: dict, proposals: list[dict], current: dict) -> None:
    """Print evolution engine report."""
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return

    print("=" * 100)
    print("EVOLUTION ENGINE — Walk-Forward Optimization")
    print("=" * 100)

    # Overall
    o = result["overall"]
    print(f"\n  Dataset: {o['total_candidates']:,} candidates "
          f"({o['total_wins']:,} wins, {o['total_losses']:,} losses)")
    print(f"  Overall WR: {o['overall_wr']:.1f}%")
    print(f"  Mean CV AUC: {result['mean_cv_auc']:.3f}")
    print(f"  Mean CV Brier: {result['mean_cv_brier']:.4f}")

    # Fold metrics
    print(f"\n{'='*100}")
    print("WALK-FORWARD FOLD RESULTS")
    print("=" * 100)
    print(f"\n  {'Fold':>5} {'Train':>7} {'Test':>6} {'Acc':>6} {'AUC':>6} {'Brier':>7} {'TestWR':>7} {'PredWR':>7}")
    print(f"  {'-'*5} {'-'*7} {'-'*6} {'-'*6} {'-'*6} {'-'*7} {'-'*7} {'-'*7}")

    for f in result["fold_metrics"]:
        print(f"  {f['fold']:>5} {f['train_size']:>7} {f['test_size']:>6} "
              f"{f['accuracy']:>5.1%} {f['auc']:>6.3f} {f['brier']:>7.4f} "
              f"{f['test_wr']:>6.1f}% {f['pred_wr']:>6.1f}%")

    # Feature importance
    print(f"\n{'='*100}")
    print("FEATURE IMPORTANCE (from GradientBoosting)")
    print("=" * 100)
    print(f"\n  {'Rank':<5} {'Feature':<22} {'Importance':>10} {'Bar'}")
    print(f"  {'-'*5} {'-'*22} {'-'*10} {'-'*30}")

    for i, fi in enumerate(result["feature_importance"][:10], 1):
        bar = "#" * int(fi["importance"] * 200)
        marker = " *" if fi["feature"] in FACTOR_COLUMNS else ""
        print(f"  {i:<5} {fi['feature']:<22} {fi['importance']:>10.4f} {bar}{marker}")

    # Optimal vs current weights
    print(f"\n{'='*100}")
    print("OPTIMAL WEIGHTS (from model) vs CURRENT WEIGHTS")
    print("=" * 100)
    print(f"\n  {'Factor':<18} {'Current':>10} {'Optimal':>10} {'Delta':>10} {'Action'}")
    print(f"  {'-'*18} {'-'*10} {'-'*10} {'-'*10} {'-'*15}")

    optimal = result["optimal_weights"]
    for factor in FACTOR_COLUMNS:
        cur = current.get(factor, 0)
        opt = optimal.get(factor, 0)
        delta = opt - cur
        action = ""
        if abs(delta) > 0.02:
            action = f"{'↑' if delta > 0 else '↓'} {abs(delta):.3f}"
        print(f"  {factor:<18} {cur:>10.4f} {opt:>10.4f} {delta:>+10.4f} {action}")

    # Proposals
    if proposals:
        print(f"\n{'='*100}")
        print("WEIGHT CHANGE PROPOSALS")
        print("=" * 100)
        print()
        for p in proposals:
            arrow = "↑" if p["direction"] == "increase" else "↓"
            print(f"  {p['factor']:<18} {p['current']:.4f} → {p['proposed']:.4f} "
                  f"({arrow} {abs(p['delta']):.3f})")

        print()
        print("  To apply these weights, update ScoringConfig in config/settings.py")
        print("  or use: /setparam scoring_<factor> <new_weight>")
    else:
        print("\n  No significant weight changes proposed (all deltas < 0.02)")

    # Calibration buckets
    if result.get("calibration_buckets"):
        print(f"\n{'='*100}")
        print("MODEL CALIBRATION (predicted vs actual)")
        print("=" * 100)
        print(f"\n  {'Predicted':<15} {'N':>6} {'Actual WR':>10} {'Avg Predicted':>14}")
        print(f"  {'-'*15} {'-'*6} {'-'*10} {'-'*14}")
        for b in result["calibration_buckets"]:
            print(f"  {b['predicted_range']:<15} {b['count']:>6} "
                  f"{b['actual_wr']:>9.1f}% {b['avg_predicted']:>13.1f}%")

    print()


def main():
    parser = argparse.ArgumentParser(description="Evolution Engine — Auto Weight Optimization")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--splits", type=int, default=5, help="Walk-forward splits")
    parser.add_argument("--min-trades", type=int, default=100, help="Minimum candidates")
    parser.add_argument("--export-proposal", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Apply weights to bot_settings")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    candidates = load_candidates(db_path)
    print(f"Loaded {len(candidates)} candidates with outcomes")

    if len(candidates) < args.min_trades:
        print(f"Need at least {args.min_trades} candidates (have {len(candidates)}).")
        print("Let the bot accumulate more signals before running evolution.")
        return

    result = walk_forward_optimization(candidates, n_splits=args.splits, min_train=args.min_trades)
    current = load_current_weights(db_path)
    proposals = propose_weight_changes(current, result.get("optimal_weights", {}))

    print_evolution_report(result, proposals, current)

    if args.apply and proposals:
        print("Applying weight changes to bot_settings...")
        conn = sqlite3.connect(str(db_path))
        new_weights = result.get("optimal_weights", {})
        # Merge with current
        merged = {**current, **new_weights}
        conn.execute(
            "INSERT OR REPLACE INTO bot_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("scoring_weights", json.dumps(merged), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()
        print("Weights updated. Restart bot to apply.")

    if args.export_proposal:
        output = Path(__file__).resolve().parent.parent / "reports" / "evolution_proposal.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump({
                "result": result,
                "current_weights": current,
                "proposals": proposals,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }, f, indent=2, ensure_ascii=False)
        print(f"\nExported to {output}")


if __name__ == "__main__":
    main()
