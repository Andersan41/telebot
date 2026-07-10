"""
probability_model.py — Second-level Empirical Probability Model.

Pipeline:
  1. Leave-One-Feature-Out Analysis (per cluster)
  2. Time-Series Split evaluation (LR, RF, XGBoost)
  3. Calibration Curves
  4. Threshold-based filtering (WR, PF, Expectancy at various thresholds)

The model sits ON TOP of the signal engine — it doesn't replace it.
It takes a candidate signal and outputs P(TP) based on features.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import (
    roc_auc_score, precision_score, recall_score,
    classification_report, brier_score_loss, log_loss,
)
from sklearn.calibration import calibration_curve
import xgboost as xgb

REPORT_DIR = Path(__file__).resolve().parent.parent / "reports" / "analysis" / "v2"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 0. Load & prepare
# ---------------------------------------------------------------------------

def load_and_prepare() -> pd.DataFrame:
    csv = Path(__file__).resolve().parent.parent / "reports" / "dataset" / "features_combined.csv"
    df = pd.read_csv(csv)

    # Encode categoricals
    cat_cols = ["regime", "structure_trend", "ema_spread_trend", "direction"]
    for col in cat_cols:
        if col in df.columns:
            le = LabelEncoder()
            df[col] = le.fit_transform(df[col].astype(str))

    # Bool -> int
    for col in df.select_dtypes(include=["bool"]).columns:
        df[col] = df[col].astype(int)

    # Sort by time for time-series split
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
    df = df.sort_values("created_at").reset_index(drop=True)

    print(f"Loaded: {len(df)} rows, date range: {df['created_at'].min()} -> {df['created_at'].max()}")
    return df


def get_feature_cols(df: pd.DataFrame) -> list[str]:
    """All numeric features available at signal time (no leakage)."""
    exclude = {
        "signal_id", "symbol", "timeframe", "created_at", "source", "result",
        "win", "pnl_pct", "net_pnl_pct", "hours_in_trade", "sl_source",
        "entry_price", "exit_price",
        # Raw prices
        "close", "high", "low", "volume",
        "ema_fast", "ema_slow", "ema_trend", "ema_fast_prev", "ema_slow_prev",
        "rsi", "macd", "macd_signal", "macd_hist", "macd_hist_prev",
        "adx", "dmi_plus", "dmi_minus", "atr", "supertrend", "volume_sma",
        # Leakage
        "rr", "signal_score", "score_verdict",
    }

    # Include direction (encoded)
    feature_cols = []
    seen = set()
    for c in df.columns:
        if c in exclude or c in seen:
            continue
        if df[c].dtype in ["float64", "float32", "int64", "int32"]:
            if df[c].nunique() > 1:
                feature_cols.append(c)
                seen.add(c)
    return feature_cols


# ---------------------------------------------------------------------------
# 1. Leave-One-Feature-Out Analysis
# ---------------------------------------------------------------------------

def run_lofo(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    print("\n" + "=" * 70)
    print("1. LEAVE-ONE-FEATURE-OUT ANALYSIS (per cluster)")
    print("=" * 70)

    y = df["win"].astype(int).values
    X_full = df[feature_cols].copy()
    for col in X_full.columns:
        if X_full[col].isna().sum() > 0:
            X_full[col] = X_full[col].fillna(X_full[col].median())

    # Baseline: all features
    scaler = StandardScaler()
    X_scaled = pd.DataFrame(scaler.fit_transform(X_full), columns=feature_cols)

    tscv = TimeSeriesSplit(n_splits=5)
    baseline_aucs = []
    for train_idx, test_idx in tscv.split(X_scaled):
        X_tr, X_te = X_scaled.iloc[train_idx], X_scaled.iloc[test_idx]
        y_tr, y_te = y[train_idx], y[test_idx]
        lr = LogisticRegression(max_iter=1000, random_state=42)
        lr.fit(X_tr, y_tr)
        prob = lr.predict_proba(X_te)[:, 1]
        baseline_aucs.append(roc_auc_score(y_te, prob))
    baseline_auc = np.mean(baseline_aucs)
    print(f"\nBaseline AUC (all {len(feature_cols)} features): {baseline_auc:.4f}")

    # LOFO: remove each feature, retrain, measure delta
    lofo_results = []
    for feat in feature_cols:
        remaining = [c for c in feature_cols if c != feat]
        X_lofo = X_scaled[remaining]

        aucs = []
        for train_idx, test_idx in tscv.split(X_lofo):
            X_tr, X_te = X_lofo.iloc[train_idx], X_lofo.iloc[test_idx]
            y_tr, y_te = y[train_idx], y[test_idx]
            lr = LogisticRegression(max_iter=1000, random_state=42)
            lr.fit(X_tr, y_tr)
            prob = lr.predict_proba(X_te)[:, 1]
            aucs.append(roc_auc_score(y_te, prob))

        mean_auc = np.mean(aucs)
        delta = baseline_auc - mean_auc
        lofo_results.append({
            "feature": feat,
            "auc_without": mean_auc,
            "delta": delta,
            "important": delta > 0.005,  # removing it hurts AUC by >0.5pp
        })

    lofo_df = pd.DataFrame(lofo_results).sort_values("delta", ascending=False)

    print("\nLOFO Results (features sorted by importance):")
    print(f"{'Feature':30s} {'AUC w/o':>8s} {'Delta':>8s} {'Important':>10s}")
    print("-" * 60)
    for _, row in lofo_df.iterrows():
        imp = "YES" if row["important"] else ""
        print(f"{row['feature']:30s} {row['auc_without']:8.4f} {row['delta']:+8.4f} {imp:>10s}")

    # Cluster-level analysis
    print("\n--- Cluster-level LOFO ---")
    # Group features by cluster
    cluster_map = {
        "Cluster 7 (Trend)": ["dmi_strength", "adx_strength", "supertrend_strength",
                               "ema_spread_pct", "rsi_strength", "ema_spread_trend"],
        "Cluster 1 (RSI/MACD)": ["rsi_value", "macd_hist_normalized", "supertrend_direction",
                                   "ema_bullish_alignment", "ema_bearish_alignment"],
        "Cluster 4 (Crosses)": ["macd_bullish_cross", "macd_bearish_cross",
                                  "ema_bullish_cross", "ema_bearish_cross",
                                  "atr_percentile", "trend_is_strong"],
        "Cluster 5 (Structure)": ["structure_trend", "has_bos", "structure_breaks"],
        "Cluster 6 (Regime/Vol)": ["regime", "regime_confidence", "volume_ratio", "volume_above_avg"],
        "Cluster 3 (Sweep)": ["has_sweep", "sweep_strength"],
        "Cluster 2 (OB)": ["has_ob", "ob_valid"],
    }

    for cluster_name, members in cluster_map.items():
        present = [m for m in members if m in feature_cols]
        if len(present) < 2:
            continue
        cluster_lofo = lofo_df[lofo_df["feature"].isin(present)]
        best = cluster_lofo.iloc[0] if len(cluster_lofo) > 0 else None
        worst = cluster_lofo.iloc[-1] if len(cluster_lofo) > 0 else None
        if best is not None and worst is not None:
            print(f"  {cluster_name}:")
            print(f"    Most important:  {best['feature']} (delta={best['delta']:+.4f})")
            print(f"    Least important: {worst['feature']} (delta={worst['delta']:+.4f})")
            print(f"    Spread: {best['delta'] - worst['delta']:.4f}")

    lofo_df.to_csv(REPORT_DIR / "07_lofo_analysis.csv", index=False)
    return lofo_df


# ---------------------------------------------------------------------------
# 2. Time-Series Split Model Comparison
# ---------------------------------------------------------------------------

def run_time_series_models(df: pd.DataFrame, feature_cols: list[str]) -> dict:
    print("\n" + "=" * 70)
    print("2. TIME-SERIES SPLIT MODEL COMPARISON")
    print("=" * 70)

    y = df["win"].astype(int).values
    X_full = df[feature_cols].copy()
    for col in X_full.columns:
        if X_full[col].isna().sum() > 0:
            X_full[col] = X_full[col].fillna(X_full[col].median())

    scaler = StandardScaler()
    X_scaled = pd.DataFrame(scaler.fit_transform(X_full), columns=feature_cols)

    models = {
        "LogisticRegression": LogisticRegression(max_iter=1000, random_state=42),
        "RandomForest": RandomForestClassifier(
            n_estimators=200, max_depth=5, min_samples_leaf=20,
            random_state=42, n_jobs=-1,
        ),
        "XGBoost": xgb.XGBClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.1,
            random_state=42, eval_metric="logloss", use_label_encoder=False,
        ),
        "GradientBoosting": GradientBoostingClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.1,
            random_state=42,
        ),
    }

    tscv = TimeSeriesSplit(n_splits=5)
    results = {}

    for name, model in models.items():
        print(f"\n--- {name} ---")
        fold_aucs = []
        fold_precisions = []
        fold_recalls = []
        fold_brier = []
        all_y_true = []
        all_y_prob = []

        for fold, (train_idx, test_idx) in enumerate(tscv.split(X_scaled)):
            X_tr, X_te = X_scaled.iloc[train_idx], X_scaled.iloc[test_idx]
            y_tr, y_te = y[train_idx], y[test_idx]

            model.fit(X_tr, y_tr)
            prob = model.predict_proba(X_te)[:, 1]
            pred = (prob >= 0.5).astype(int)

            auc = roc_auc_score(y_te, prob)
            prec = precision_score(y_te, pred, zero_division=0)
            rec = recall_score(y_te, pred, zero_division=0)
            brier = brier_score_loss(y_te, prob)

            fold_aucs.append(auc)
            fold_precisions.append(prec)
            fold_recalls.append(rec)
            fold_brier.append(brier)
            all_y_true.extend(y_te)
            all_y_prob.extend(prob)

            print(f"  Fold {fold+1}: AUC={auc:.4f}  Prec={prec:.3f}  "
                  f"Rec={rec:.3f}  Brier={brier:.4f}")

        mean_auc = np.mean(fold_aucs)
        mean_prec = np.mean(fold_precisions)
        mean_rec = np.mean(fold_recalls)
        mean_brier = np.mean(fold_brier)

        print(f"  MEAN:    AUC={mean_auc:.4f}  Prec={mean_prec:.3f}  "
              f"Rec={mean_rec:.3f}  Brier={mean_brier:.4f}")

        results[name] = {
            "mean_auc": mean_auc,
            "mean_precision": mean_prec,
            "mean_recall": mean_rec,
            "mean_brier": mean_brier,
            "all_y_true": np.array(all_y_true),
            "all_y_prob": np.array(all_y_prob),
        }

    # Summary table
    print("\n--- Model Comparison Summary ---")
    print(f"{'Model':25s} {'AUC':>6s} {'Prec':>6s} {'Rec':>6s} {'Brier':>6s}")
    print("-" * 55)
    for name, r in sorted(results.items(), key=lambda x: -x[1]["mean_auc"]):
        print(f"{name:25s} {r['mean_auc']:6.4f} {r['mean_precision']:6.3f} "
              f"{r['mean_recall']:6.3f} {r['mean_brier']:6.4f}")

    return results


# ---------------------------------------------------------------------------
# 3. Calibration Curves
# ---------------------------------------------------------------------------

def run_calibration(df: pd.DataFrame, feature_cols: list[str], model_results: dict):
    print("\n" + "=" * 70)
    print("3. CALIBRATION ANALYSIS")
    print("=" * 70)

    for name, r in model_results.items():
        y_true = r["all_y_true"]
        y_prob = r["all_y_prob"]

        # Calibration curve
        prob_true, prob_pred = calibration_curve(y_true, y_prob, n_bins=10, strategy="uniform")

        print(f"\n--- {name} ---")
        print(f"{'Predicted':>10s} {'Actual':>10s} {'Count':>8s}")
        print("-" * 30)

        # Compute bin counts
        bins = np.linspace(0, 1, 11)
        for i in range(len(prob_true)):
            lo, hi = bins[i], bins[i + 1]
            count = np.sum((y_prob >= lo) & (y_prob < hi))
            print(f"{prob_pred[i]:10.3f} {prob_true[i]:10.3f} {count:8d}")

        # Expected Calibration Error
        bin_counts = np.histogram(y_prob, bins=bins)[0]
        bin_counts = bin_counts[bin_counts > 0]
        ece = np.sum(np.abs(prob_true - prob_pred) * bin_counts[:len(prob_true)]) / len(y_true)
        print(f"  ECE: {ece:.4f}")

        # Brier score
        brier = brier_score_loss(y_true, y_prob)
        print(f"  Brier: {brier:.4f}")

        # Save calibration data
        cal_df = pd.DataFrame({
            "predicted": prob_pred,
            "actual": prob_true,
            "bin_count": bin_counts[:len(prob_true)],
        })
        cal_df.to_csv(REPORT_DIR / f"08_calibration_{name}.csv", index=False)


# ---------------------------------------------------------------------------
# 4. Threshold-based filtering
# ---------------------------------------------------------------------------

def run_threshold_analysis(df: pd.DataFrame, feature_cols: list[str], model_results: dict):
    print("\n" + "=" * 70)
    print("4. THRESHOLD-BASED FILTERING ANALYSIS")
    print("=" * 70)

    # Use best model
    best_model_name = max(model_results, key=lambda k: model_results[k]["mean_auc"])
    print(f"\nUsing best model: {best_model_name}")

    y_true = model_results[best_model_name]["all_y_true"]
    y_prob = model_results[best_model_name]["all_y_prob"]

    # Also retrain best model on all data and get predictions per trade
    # For threshold analysis we need per-trade predictions, not aggregated
    # Let's retrain on all data and predict

    y = df["win"].astype(int).values
    X_full = df[feature_cols].copy()
    for col in X_full.columns:
        if X_full[col].isna().sum() > 0:
            X_full[col] = X_full[col].fillna(X_full[col].median())

    scaler = StandardScaler()
    X_scaled = pd.DataFrame(scaler.fit_transform(X_full), columns=feature_cols)

    # Train on first 80%, predict on last 20%
    split_idx = int(len(X_scaled) * 0.8)
    X_tr, X_te = X_scaled.iloc[:split_idx], X_scaled.iloc[split_idx:]
    y_tr, y_te = y[:split_idx], y[split_idx:]
    df_te = df.iloc[split_idx:].copy()

    models = {
        "LogisticRegression": LogisticRegression(max_iter=1000, random_state=42),
        "RandomForest": RandomForestClassifier(
            n_estimators=200, max_depth=5, min_samples_leaf=20,
            random_state=42, n_jobs=-1,
        ),
        "XGBoost": xgb.XGBClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.1,
            random_state=42, eval_metric="logloss", use_label_encoder=False,
        ),
    }

    thresholds = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]

    for model_name, model in models.items():
        print(f"\n--- {model_name} ---")
        model.fit(X_tr, y_tr)
        prob = model.predict_proba(X_te)[:, 1]
        df_te = df_te.copy()
        df_te["prob_tp"] = prob
        df_te["win"] = y_te

        print(f"{'Threshold':>10s} {'Trades':>7s} {'WR':>7s} {'PF':>6s} {'AvgPnL':>8s} {'Exp':>8s}")
        print("-" * 55)

        for thr in thresholds:
            subset = df_te[df_te["prob_tp"] >= thr]
            n = len(subset)
            if n < 5:
                continue

            wr = subset["win"].mean()
            wins = subset[subset["win"] == 1]["net_pnl_pct"]
            losses = subset[subset["win"] == 0]["net_pnl_pct"]
            gross_profit = wins.sum() if len(wins) > 0 else 0
            gross_loss = abs(losses.sum()) if len(losses) > 0 else 0.001
            pf = gross_profit / gross_loss
            avg_pnl = subset["net_pnl_pct"].mean()
            exp = avg_pnl  # expectancy = avg PnL per trade

            print(f"{thr:10.0%} {n:7d} {wr:6.1%} {pf:6.2f} {avg_pnl:+7.2f}% {exp:+7.2f}%")

        # Also show what happens below the threshold
        print(f"\nBelow threshold analysis (0.50):")
        below = df_te[df_te["prob_tp"] < 0.50]
        above = df_te[df_te["prob_tp"] >= 0.50]
        if len(below) > 5:
            print(f"  Below 0.50: {len(below)} trades, WR={below['win'].mean():.1%}, "
                  f"AvgPnL={below['net_pnl_pct'].mean():+.2f}%")
        if len(above) > 5:
            print(f"  Above 0.50: {len(above)} trades, WR={above['win'].mean():.1%}, "
                  f"AvgPnL={above['net_pnl_pct'].mean():+.2f}%")

    # --- Best regime-specific thresholds ---
    print("\n--- Regime-specific threshold analysis (XGBoost) ---")
    model = models["XGBoost"]
    prob = model.predict_proba(X_te)[:, 1]
    df_te = df.iloc[split_idx:].copy()
    df_te["prob_tp"] = prob
    df_te["win"] = y_te

    for regime in df_te["regime"].unique():
        regime_df = df_te[df_te["regime"] == regime]
        if len(regime_df) < 10:
            continue
        print(f"\n  Regime: {regime}")
        print(f"  {'Threshold':>10s} {'Trades':>7s} {'WR':>7s} {'AvgPnL':>8s}")
        print("  " + "-" * 38)
        for thr in [0.50, 0.60, 0.70]:
            subset = regime_df[regime_df["prob_tp"] >= thr]
            if len(subset) >= 3:
                print(f"  {thr:10.0%} {len(subset):7d} {subset['win'].mean():6.1%} "
                      f"{subset['net_pnl_pct'].mean():+7.2f}%")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

df_all = None
feature_cols = None


def main():
    global df_all, feature_cols

    df_all = load_and_prepare()
    feature_cols = get_feature_cols(df_all)

    print(f"\nFeature columns ({len(feature_cols)}): {feature_cols}")

    lofo_results = run_lofo(df_all, feature_cols)
    model_results = run_time_series_models(df_all, feature_cols)
    run_calibration(df_all, feature_cols, model_results)
    run_threshold_analysis(df_all, feature_cols, model_results)

    print("\n" + "=" * 70)
    print("ALL REPORTS SAVED TO:", REPORT_DIR)
    print("=" * 70)


if __name__ == "__main__":
    main()
