"""
analytics/feature_drift.py — Feature drift detection.

Compares optimal feature ranges from early trades vs recent trades.
Detects when market structure shifts cause features to behave differently.

Usage:
    python -m analytics.feature_drift [--db data/signals.db] [--split-ratio 0.5]
    python -m analytics.feature_drift --early-weeks 4 --late-weeks 4
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "signals.db"

DRIFT_FEATURES = [
    "adx", "rsi", "ema_spread_pct", "volume_ratio", "macd_hist",
    "atr_pct", "confidence", "rr_ratio",
    "tp_distance_pct", "sl_distance_pct",
    "btc_trend_strength", "context_score", "mtf_alignment_score",
    "ema_slope_3", "ema_slope_5",
]


def load_signals_with_features(db_path: str | Path) -> list[dict]:
    """Load signals with feature snapshots and outcomes."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    query = """
        SELECT
            s.created_at,
            dt.adx, dt.rsi, dt.ema_spread_pct, dt.volume_ratio,
            dt.macd_hist, dt.atr_pct, dt.confidence, dt.rr_ratio,
            dt.tp_distance_pct, dt.sl_distance_pct,
            dt.btc_trend_strength, dt.context_score, dt.mtf_alignment_score,
            dt.ema_slope_3, dt.ema_slope_5,
            dt.outcome, dt.pnl_pct, dt.direction
        FROM signals s
        JOIN decision_traces dt ON dt.signal_id = s.id
        WHERE dt.signal_generated = 1
          AND dt.outcome IN ('HIT_TP', 'HIT_SL')
        ORDER BY s.created_at
    """

    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def compute_feature_stats(trades: list[dict], features: list[str]) -> dict[str, dict]:
    """Compute median, IQR, P5-P95 for each feature in a trade set."""
    result = {}
    for f in features:
        vals = [t[f] for t in trades if t.get(f) is not None]
        if len(vals) < 5:
            continue
        sorted_vals = sorted(vals)
        n = len(sorted_vals)
        median = sorted_vals[n // 2]
        q1 = sorted_vals[int(n * 0.25)]
        q3 = sorted_vals[int(n * 0.75)]
        result[f] = {
            "count": n,
            "median": round(median, 4),
            "mean": round(sum(vals) / n, 4),
            "std": round((sum((v - sum(vals) / n) ** 2 for v in vals) / n) ** 0.5, 4),
            "p5": round(sorted_vals[int(n * 0.05)], 4),
            "p25": round(q1, 4),
            "p75": round(q3, 4),
            "p95": round(sorted_vals[int(n * 0.95)], 4),
            "iqr": round(q3 - q1, 4),
        }
    return result


def compute_winrate_by_range(
    trades: list[dict], feature: str, bins: int = 5
) -> list[dict]:
    """Compute WR for different ranges of a feature."""
    vals = [(t.get(feature), t.get("outcome") == "HIT_TP") for t in trades if t.get(feature) is not None]
    if len(vals) < 10:
        return []

    values = [v for v, _ in vals]
    lo, hi = min(values), max(values)
    bin_width = (hi - lo) / bins if hi > lo else 1

    result = []
    for i in range(bins):
        bin_lo = lo + i * bin_width
        bin_hi = lo + (i + 1) * bin_width
        bin_trades = [(v, w) for v, w in vals if bin_lo <= v < bin_hi or (i == bins - 1 and v == hi)]
        if len(bin_trades) < 3:
            continue
        wins = sum(1 for _, w in bin_trades if w)
        result.append({
            "range": f"[{bin_lo:.4f}, {bin_hi:.4f})",
            "count": len(bin_trades),
            "wr": round(wins / len(bin_trades) * 100, 1),
        })

    return result


def detect_feature_drift(
    early_stats: dict[str, dict],
    late_stats: dict[str, dict],
    threshold_pct: float = 10.0,
) -> list[dict]:
    """Detect significant shifts between early and late periods."""
    drifts = []

    for feature in set(early_stats.keys()) & set(late_stats.keys()):
        early = early_stats[feature]
        late = late_stats[feature]

        # Median shift as percentage of IQR
        median_shift = late["median"] - early["median"]
        iqr_avg = (early["iqr"] + late["iqr"]) / 2
        normalized_shift = abs(median_shift) / iqr_avg if iqr_avg > 0 else 0

        # IQR change
        iqr_change = (late["iqr"] - early["iqr"]) / early["iqr"] * 100 if early["iqr"] > 0 else 0

        # P5-P95 range shift
        p5_shift = late["p5"] - early["p5"]
        p95_shift = late["p95"] - early["p95"]

        if normalized_shift > threshold_pct / 100 or abs(iqr_change) > threshold_pct:
            severity = "HIGH" if normalized_shift > 0.3 or abs(iqr_change) > 30 else "MEDIUM" if normalized_shift > 0.15 or abs(iqr_change) > 15 else "LOW"

            drifts.append({
                "feature": feature,
                "severity": severity,
                "early_median": early["median"],
                "late_median": late["median"],
                "median_shift": round(median_shift, 4),
                "normalized_shift": round(normalized_shift, 3),
                "early_iqr": early["iqr"],
                "late_iqr": late["iqr"],
                "iqr_change_pct": round(iqr_change, 1),
                "early_p5_p95": f"[{early['p5']:.4f}, {early['p95']:.4f}]",
                "late_p5_p95": f"[{late['p5']:.4f}, {late['p95']:.4f}]",
                "early_n": early["count"],
                "late_n": late["count"],
            })

    drifts.sort(key=lambda x: x["normalized_shift"], reverse=True)
    return drifts


def print_feature_drift_report(
    early_stats: dict[str, dict],
    late_stats: dict[str, dict],
    drifts: list[dict],
) -> None:
    """Print feature drift report."""
    print("=" * 120)
    print("FEATURE DRIFT DETECTION")
    print("=" * 120)

    print(f"\n  Early period: {early_stats[list(early_stats.keys())[0]].get('count', 0)} signals")
    print(f"  Late period:  {late_stats[list(late_stats.keys())[0]].get('count', 0)} signals")

    # Comparison table
    print()
    print(f"  {'Feature':<22} {'Early Med':>10} {'Late Med':>10} {'Shift':>10} {'NormShift':>10} "
          f"{'Early IQR':>10} {'Late IQR':>10} {'IQR Δ%':>8} {'Severity':<8}")
    print(f"  {'-'*22} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*8} {'-'*8}")

    for feature in sorted(set(early_stats.keys()) | set(late_stats.keys())):
        early = early_stats.get(feature, {})
        late = late_stats.get(feature, {})
        if not early or not late:
            continue

        drift = next((d for d in drifts if d["feature"] == feature), None)
        severity = drift["severity"] if drift else ""
        shift = f"{drift['median_shift']:+.4f}" if drift else "—"
        norm = f"{drift['normalized_shift']:.3f}" if drift else "—"
        iqr_delta = f"{drift['iqr_change_pct']:+.1f}%" if drift else "—"

        print(f"  {feature:<22} {early['median']:>10.4f} {late['median']:>10.4f} "
              f"{shift:>10} {norm:>10} "
              f"{early['iqr']:>10.4f} {late['iqr']:>10.4f} {iqr_delta:>8} {severity:<8}")

    # Drift summary
    if drifts:
        print()
        print("=" * 120)
        print("DRIFTED FEATURES (sorted by severity)")
        print("=" * 120)
        for d in drifts:
            print(f"\n  {d['feature']} [{d['severity']}]")
            print(f"    Median: {d['early_median']:.4f} → {d['late_median']:.4f} (shift={d['median_shift']:+.4f})")
            print(f"    IQR:    {d['early_iqr']:.4f} → {d['late_iqr']:.4f} (Δ={d['iqr_change_pct']:+.1f}%)")
            print(f"    P5-P95: {d['early_p5_p95']} → {d['late_p5_p95']}")
    else:
        print("\n  No significant feature drift detected.")

    print()


def main():
    parser = argparse.ArgumentParser(description="Feature Drift Detection")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--split-ratio", type=float, default=0.5, help="Split point (0-1) for early/late")
    parser.add_argument("--threshold", type=float, default=10.0, help="Drift detection threshold %")
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    trades = load_signals_with_features(db_path)
    print(f"Loaded {len(trades)} signals with feature data")

    if len(trades) < 20:
        print("Need at least 20 signals for drift detection.")
        return

    # Split into early/late
    split_idx = int(len(trades) * args.split_ratio)
    early = trades[:split_idx]
    late = trades[split_idx:]

    early_stats = compute_feature_stats(early, DRIFT_FEATURES)
    late_stats = compute_feature_stats(late, DRIFT_FEATURES)
    drifts = detect_feature_drift(early_stats, late_stats, threshold_pct=args.threshold)

    print_feature_drift_report(early_stats, late_stats, drifts)

    if args.export:
        output = Path(__file__).resolve().parent.parent / "reports" / "feature_drift.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump({
                "early": early_stats,
                "late": late_stats,
                "drifts": drifts,
            }, f, indent=2, ensure_ascii=False)
        print(f"Exported to {output}")


if __name__ == "__main__":
    main()
