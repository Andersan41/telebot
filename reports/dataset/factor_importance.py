"""
factor_importance.py — Step 5: Basic Factor Importance Analysis
"""
import sys
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

# Load dataset
df = pd.read_parquet(OUT_DIR / "features_combined.parquet")
print(f"Dataset: {df.shape[0]} rows x {df.shape[1]} columns\n")

# ── 5.1 Correlation Matrix ──────────────────────────────────────────
print("=" * 70)
print("5.1 CORRELATION WITH WIN (numeric factors)")
print("=" * 70)

# Select numeric columns (exclude raw price data, keep factors)
factor_cols = [
    "ema_strength", "ema_spread_pct", "adx_value", "adx_strength",
    "supertrend_strength", "macd_hist_normalized", "rsi_value", "rsi_strength",
    "volume_ratio", "dmi_strength", "sweep_strength", "structure_breaks",
    "regime_confidence", "atr_percentile", "signal_score",
    "hours_in_trade", "rr",
]
# Add boolean columns (encoded as int)
bool_cols = [
    "ema_slope_ok", "has_bos", "has_sweep", "has_ob", "ob_valid",
    "ema_bullish_cross", "ema_bearish_cross", "ema_bullish_alignment",
    "ema_bearish_alignment", "macd_bullish_cross", "macd_bearish_cross",
    "volume_above_avg", "supertrend_bullish", "supertrend_bearish",
    "trend_is_strong",
]

available_factors = [c for c in factor_cols if c in df.columns]
available_bools = [c for c in bool_cols if c in df.columns]
all_numeric = available_factors + available_bools

# Add win as int
df["_win_int"] = df["win"].astype(int)
corr_with_win = df[all_numeric + ["_win_int"]].corr()["_win_int"].drop("_win_int").sort_values()

print("\nTop 10 POSITIVE correlations with win:")
for name, val in corr_with_win.tail(10).iloc[::-1].items():
    print(f"  {name:30s}  {val:+.4f}")

print("\nTop 10 NEGATIVE correlations with win:")
for name, val in corr_with_win.head(10).items():
    print(f"  {name:30s}  {val:+.4f}")

print(f"\nAll correlations with win:")
for name, val in corr_with_win.items():
    marker = " ***" if abs(val) > 0.1 else (" *" if abs(val) > 0.05 else "")
    print(f"  {name:30s}  {val:+.4f}{marker}")

# ── 5.2 WR by Categorical Factors ──────────────────────────────────
print("\n" + "=" * 70)
print("5.2 WIN RATE BY CATEGORICAL FACTORS")
print("=" * 70)

cat_factors = ["regime", "sl_source", "score_verdict", "direction",
               "structure_trend", "ema_spread_trend"]

for cat in cat_factors:
    if cat not in df.columns:
        continue
    print(f"\n--- {cat} ---")
    groups = df.groupby(cat).agg(
        N=("win", "count"),
        WR=("win", "mean"),
        avg_pnl=("pnl_pct", "mean"),
        avg_net_pnl=("net_pnl_pct", "mean"),
    ).sort_values("WR", ascending=False)
    groups["WR"] = (groups["WR"] * 100).round(1)
    groups["avg_pnl"] = groups["avg_pnl"].round(4)
    groups["avg_net_pnl"] = groups["avg_net_pnl"].round(4)
    print(groups.to_string())

# Bool factors WR
print(f"\n--- Boolean Factors WR ---")
for col in available_bools:
    if col in df.columns:
        g = df.groupby(col).agg(
            N=("win", "count"),
            WR=("win", "mean"),
            avg_pnl=("pnl_pct", "mean"),
        )
        g["WR"] = (g["WR"] * 100).round(1)
        g["avg_pnl"] = g["avg_pnl"].round(4)
        if len(g) == 2:
            print(f"\n  {col}:")
            print(g.to_string().replace("\n", "\n  "))

# ── 5.3 RandomForest Feature Importance ─────────────────────────────
print("\n" + "=" * 70)
print("5.3 RANDOM FOREST FEATURE IMPORTANCE")
print("=" * 70)

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import LabelEncoder

    # Prepare features
    rf_cols = available_factors + available_bools
    df_rf = df[rf_cols + ["win"]].dropna()
    print(f"\nRows for RF (dropna): {len(df_rf)}")

    X = df_rf[rf_cols].copy()
    y = df_rf["win"].astype(int)

    # Encode any remaining object columns
    for col in X.columns:
        if X[col].dtype == "object":
            le = LabelEncoder()
            X[col] = le.fit_transform(X[col].astype(str))

    rf = RandomForestClassifier(n_estimators=200, random_state=42, max_depth=10, min_samples_leaf=20)
    rf.fit(X, y)

    importances = pd.Series(rf.feature_importances_, index=rf_cols).sort_values(ascending=False)

    print(f"\nRF Accuracy: {rf.score(X, y)*100:.1f}%")
    print(f"\nFeature importances (sorted):")
    for name, imp in importances.items():
        bar = "#" * int(imp * 200)
        print(f"  {name:30s}  {imp:.4f}  {bar}")

except ImportError:
    print("\nscikit-learn not installed. Skipping RF analysis.")
    print("Install with: pip install scikit-learn")

# ── 5.4 Factor Correlation (Duplication) ───────────────────────────
print("\n" + "=" * 70)
print("5.4 FACTOR CORRELATION MATRIX (duplication check)")
print("=" * 70)

corr_matrix = df[available_factors].corr()

# Find pairs with high correlation
high_corr_pairs = []
for i in range(len(corr_matrix.columns)):
    for j in range(i + 1, len(corr_matrix.columns)):
        val = corr_matrix.iloc[i, j]
        if abs(val) > 0.5:
            high_corr_pairs.append((
                corr_matrix.columns[i],
                corr_matrix.columns[j],
                val
            ))

high_corr_pairs.sort(key=lambda x: abs(x[2]), reverse=True)

print("\nPairs with correlation > 0.5:")
for c1, c2, val in high_corr_pairs:
    marker = " *** DUPLICATE" if abs(val) > 0.8 else ""
    print(f"  {c1:30s} <-> {c2:30s}  {val:+.4f}{marker}")

# Top correlated pairs with win
print("\n\nFactor pairs with correlation > 0.8 (strong duplication):")
dup_candidates = [(c1, c2, v) for c1, c2, v in high_corr_pairs if abs(v) > 0.8]
if dup_candidates:
    for c1, c2, v in dup_candidates:
        print(f"  {c1} <-> {c2}: {v:+.4f}")
        # Suggest which to keep based on correlation with win
        corr1 = abs(corr_with_win.get(c1, 0))
        corr2 = abs(corr_with_win.get(c2, 0))
        keep = c1 if corr1 >= corr2 else c2
        drop = c2 if keep == c1 else c1
        print(f"    -> Keep '{keep}' (corr_with_win={corr1:.4f}), drop '{drop}' (corr_with_win={corr2:.4f})")
else:
    print("  None found!")

# Save factor importance report
report_path = OUT_DIR / "factor_importance.md"
with open(report_path, "w", encoding="utf-8") as f:
    f.write("# Factor Importance Analysis\n\n")
    f.write(f"**Dataset:** {df.shape[0]} rows x {df.shape[1]} columns\n")
    f.write(f"**Win rate:** {df['win'].mean()*100:.1f}%\n\n")

    f.write("## Correlation with Win\n\n")
    f.write("| Factor | Correlation | Significance |\n")
    f.write("|--------|------------|---------------|\n")
    for name, val in corr_with_win.items():
        sig = "***" if abs(val) > 0.1 else ("*" if abs(val) > 0.05 else "")
        f.write(f"| {name} | {val:+.4f} | {sig} |\n")

    f.write("\n## Win Rate by Category\n\n")
    for cat in cat_factors:
        if cat not in df.columns:
            continue
        f.write(f"### {cat}\n\n")
        groups = df.groupby(cat).agg(
            N=("win", "count"),
            WR=("win", "mean"),
            avg_pnl=("pnl_pct", "mean"),
        ).sort_values("WR", ascending=False)
        groups["WR"] = (groups["WR"] * 100).round(1)
        groups["avg_pnl"] = groups["avg_pnl"].round(4)
        f.write(groups.to_markdown() + "\n\n")

    f.write("## High Correlation Pairs (>0.5)\n\n")
    f.write("| Factor 1 | Factor 2 | Correlation |\n")
    f.write("|----------|----------|-------------|\n")
    for c1, c2, val in high_corr_pairs:
        f.write(f"| {c1} | {c2} | {val:+.4f} |\n")

print(f"\nSaved: {report_path}")
