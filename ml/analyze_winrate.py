"""Analyze winrate by feature groups to find improvement opportunities."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from ml.config import DATASET_PATH

df = pd.read_parquet(DATASET_PATH)
tp = df[df["label"] == 1]
sl = df[df["label"] == 0]
exp = df[df["label"] == -1]

print(f"=== Dataset: {len(df)} rows (TP={len(tp)}, SL={len(sl)}, EXPIRED={len(exp)})")
print()

# Key feature differences
features = [
    "structure_trend", "entry_armed", "rr_ratio", "has_bos", "dmi_diff",
    "mss_causality", "ema_spread_pct", "structure_bos_aligned", "atr_pct",
    "rsi", "volume_ratio", "components_count", "has_ob", "has_fvg", "has_sweep",
]
header = f"{'Feature':30s} {'TP mean':>10s} {'SL mean':>10s} {'Diff%':>8s}"
print(header)
print("-" * 62)
for f in features:
    if f in df.columns:
        t = tp[f].mean()
        s = sl[f].mean()
        diff = ((t - s) / max(abs(s), 0.001)) * 100
        print(f"{f:30s} {t:10.4f} {s:10.4f} {diff:+7.1f}%")

print()
print("=== Winrate by structure_trend ===")
for v in sorted(df["structure_trend"].unique()):
    sub = df[df["structure_trend"] == v]
    w = (sub["label"] == 1).sum() / max(len(sub), 1) * 100
    print(f"  trend={v:.1f}: n={len(sub):5d} winrate={w:.1f}%")

print()
print("=== Winrate by entry_armed ===")
for v in [0, 1]:
    sub = df[df["entry_armed"] == v]
    w = (sub["label"] == 1).sum() / max(len(sub), 1) * 100
    print(f"  armed={v}: n={len(sub):5d} winrate={w:.1f}%")

print()
print("=== Winrate by rr_ratio bins ===")
bins = [0, 1.0, 1.5, 2.0, 2.5, 3.0, 5.0, 100]
for i in range(len(bins) - 1):
    sub = df[(df["rr_ratio"] >= bins[i]) & (df["rr_ratio"] < bins[i + 1])]
    if len(sub) > 0:
        w = (sub["label"] == 1).sum() / len(sub) * 100
        print(f"  RR [{bins[i]:.1f}-{bins[i+1]:.1f}): n={len(sub):5d} winrate={w:.1f}%")

print()
print("=== Winrate by components_count ===")
for v in sorted(df["components_count"].unique()):
    sub = df[df["components_count"] == v]
    w = (sub["label"] == 1).sum() / max(len(sub), 1) * 100
    print(f"  components={int(v)}: n={len(sub):5d} winrate={w:.1f}%")

print()
print("=== Winrate by has_sweep ===")
for v in [0, 1]:
    sub = df[df["has_sweep"] == v]
    w = (sub["label"] == 1).sum() / max(len(sub), 1) * 100
    print(f"  sweep={v}: n={len(sub):5d} winrate={w:.1f}%")

print()
print("=== Winrate by has_ob ===")
for v in [0, 1]:
    sub = df[df["has_ob"] == v]
    w = (sub["label"] == 1).sum() / max(len(sub), 1) * 100
    print(f"  ob={v}: n={len(sub):5d} winrate={w:.1f}%")

print()
print("=== Winrate by has_fvg ===")
for v in [0, 1]:
    sub = df[df["has_fvg"] == v]
    w = (sub["label"] == 1).sum() / max(len(sub), 1) * 100
    print(f"  fvg={v}: n={len(sub):5d} winrate={w:.1f}%")

print()
print("=== Winrate by RSI zones ===")
rsi_bins = [(0, 30, "oversold"), (30, 50, "low"), (50, 70, "mid"), (70, 100, "overbought")]
for lo, hi, name in rsi_bins:
    sub = df[(df["rsi"] >= lo) & (df["rsi"] < hi)]
    if len(sub) > 0:
        w = (sub["label"] == 1).sum() / len(sub) * 100
        print(f"  RSI {name} [{lo}-{hi}]: n={len(sub):5d} winrate={w:.1f}%")

print()
print("=== Winrate by ADX zones ===")
adx_bins = [(0, 20, "weak"), (20, 40, "moderate"), (40, 100, "strong")]
for lo, hi, name in adx_bins:
    sub = df[(df["adx"] >= lo) & (df["adx"] < hi)]
    if len(sub) > 0:
        w = (sub["label"] == 1).sum() / len(sub) * 100
        print(f"  ADX {name} [{lo}-{hi}]: n={len(sub):5d} winrate={w:.1f}%")

print()
print("=== Winrate by volume_ratio zones ===")
vol_bins = [(0, 0.8, "low"), (0.8, 1.2, "normal"), (1.2, 2.0, "high"), (2.0, 100, "very_high")]
for lo, hi, name in vol_bins:
    sub = df[(df["volume_ratio"] >= lo) & (df["volume_ratio"] < hi)]
    if len(sub) > 0:
        w = (sub["label"] == 1).sum() / len(sub) * 100
        print(f"  Vol {name} [{lo:.1f}-{hi:.1f}]: n={len(sub):5d} winrate={w:.1f}%")

print()
print("=== Winrate by atr_pct (volatility) ===")
atr_bins = [(0, 0.01, "low_vol"), (0.01, 0.03, "normal"), (0.03, 0.06, "high"), (0.06, 100, "extreme")]
for lo, hi, name in atr_bins:
    sub = df[(df["atr_pct"] >= lo) & (df["atr_pct"] < hi)]
    if len(sub) > 0:
        w = (sub["label"] == 1).sum() / len(sub) * 100
        print(f"  ATR {name} [{lo:.3f}-{hi:.3f}]: n={len(sub):5d} winrate={w:.1f}%")

print()
print("=== Winrate by dmi_diff (trend strength) ===")
dmi_bins = [(-100, -0.1, "bearish"), (-0.1, 0.1, "neutral"), (0.1, 100, "bullish")]
for lo, hi, name in dmi_bins:
    sub = df[(df["dmi_diff"] >= lo) & (df["dmi_diff"] < hi)]
    if len(sub) > 0:
        w = (sub["label"] == 1).sum() / len(sub) * 100
        print(f"  DMI {name} [{lo:.1f}-{hi:.1f}]: n={len(sub):5d} winrate={w:.1f}%")

print()
print("=== Winrate by setup_type (is_reversal) ===")
for v in [0, 1]:
    sub = df[df["is_reversal"] == v]
    w = (sub["label"] == 1).sum() / max(len(sub), 1) * 100
    typ = "reversal" if v == 1 else "continuation"
    print(f"  {typ}: n={len(sub):5d} winrate={w:.1f}%")

print()
print("=== PREDICTED vs ACTUAL: threshold analysis ===")
# Use the model to see how different thresholds affect precision
from strategy.probability_engine import probability_engine
import json

# Get feature columns that exist
feature_cols = [c for c in df.columns if c not in ["label", "entry_price", "sl_price", "tp_price", "symbol", "timestamp"]]
X = df[feature_cols].fillna(0)

try:
    import pandas as pd
    preds = probability_engine.model.predict(X[probability_engine.feature_names])
    # Convert to P(TP) via isotonic
    proba_input = 1.0 / (1.0 + np.exp(-preds))
    if probability_engine.isotonic is not None:
        p_tp_values = probability_engine.isotonic.predict(proba_input)
    else:
        p_tp_values = proba_input

    df["pred_p_tp"] = p_tp_values
    df["pred_return"] = preds

    print(f"{'Threshold':>12s} {'Precision':>10s} {'Recall':>10s} {'Trades':>10s} {'Winrate':>10s}")
    print("-" * 55)
    for thresh in [0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8]:
        signals = df[df["pred_p_tp"] >= thresh]
        if len(signals) == 0:
            continue
        wins = (signals["label"] == 1).sum()
        losses = (signals["label"] == 0).sum()
        precision = wins / max(wins + losses, 1)
        recall = wins / max(len(tp), 1)
        winrate = wins / len(signals) * 100
        print(f"  p_tp>={thresh:.2f}  {precision:10.3f} {recall:10.3f} {len(signals):10d} {winrate:9.1f}%")

    print()
    print("=== PREDICTED expected_return threshold analysis ===")
    print(f"{'Threshold':>12s} {'Precision':>10s} {'Recall':>10s} {'Trades':>10s} {'Winrate':>10s}")
    print("-" * 55)
    for thresh in [-0.5, -0.2, 0.0, 0.1, 0.2, 0.3, 0.5, 0.8, 1.0, 1.5]:
        signals = df[df["pred_return"] >= thresh]
        if len(signals) == 0:
            continue
        wins = (signals["label"] == 1).sum()
        losses = (signals["label"] == 0).sum()
        precision = wins / max(wins + losses, 1)
        recall = wins / max(len(tp), 1)
        winrate = wins / len(signals) * 100
        print(f"  ret>={thresh:+.1f}    {precision:10.3f} {recall:10.3f} {len(signals):10d} {winrate:9.1f}%")

except Exception as e:
    print(f"Prediction analysis failed: {e}")
    import traceback; traceback.print_exc()
