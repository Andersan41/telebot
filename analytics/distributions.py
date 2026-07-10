"""
analytics/distributions.py — Factor distribution analysis.

Shows distributions (median, P5, P95, IQR) for all features, split by
TP vs SL — enabling automatic range calibration from real data.

Usage:
    python -m analytics.distributions [--db data/signals.db]
    python -m analytics.distributions --factor adx
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "signals.db"

DISTRIBUTION_FACTORS = [
    "adx", "rsi", "ema_spread_pct", "volume_ratio", "macd_hist",
    "atr_pct", "confidence", "rr_ratio",
    "tp_distance_pct", "sl_distance_pct",
    "signal_score", "btc_trend_strength", "context_score",
    "mtf_alignment_score", "ema_slope_3", "ema_slope_5",
    "nearest_support_pct", "nearest_resistance_pct",
]


def load_signal_features(db_path: str | Path) -> list[dict]:
    """Load feature snapshots from decision_traces for generated signals with outcomes."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    query = """
        SELECT
            dt.adx, dt.rsi, dt.ema_spread_pct, dt.volume_ratio,
            dt.macd_hist, dt.atr_pct, dt.confidence, dt.rr_ratio,
            dt.tp_distance_pct, dt.sl_distance_pct,
            dt.signal_score, dt.btc_trend_strength, dt.context_score,
            dt.mtf_alignment_score, dt.ema_slope_3, dt.ema_slope_5,
            dt.nearest_support_pct, dt.nearest_resistance_pct,
            dt.direction, dt.regime,
            dt.outcome, dt.pnl_pct
        FROM decision_traces dt
        WHERE dt.signal_generated = 1
          AND dt.outcome IN ('HIT_TP', 'HIT_SL')
    """

    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def compute_distribution(values: list[float]) -> dict:
    """Compute descriptive statistics for a list of values."""
    if not values:
        return {}

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    return {
        "count": n,
        "min": round(sorted_vals[0], 4),
        "max": round(sorted_vals[-1], 4),
        "median": round(sorted_vals[n // 2], 4),
        "mean": round(sum(sorted_vals) / n, 4),
        "p5": round(sorted_vals[max(0, int(n * 0.05))], 4),
        "p25": round(sorted_vals[max(0, int(n * 0.25))], 4),
        "p75": round(sorted_vals[min(n - 1, int(n * 0.75))], 4),
        "p95": round(sorted_vals[min(n - 1, int(n * 0.95))], 4),
        "iqr": round(
            sorted_vals[min(n - 1, int(n * 0.75))] - sorted_vals[max(0, int(n * 0.25))],
            4,
        ),
    }


def compute_factor_distributions(
    trades: list[dict], factors: list[str]
) -> dict[str, dict]:
    """Compute overall, TP, and SL distributions for each factor."""
    result = {}

    for factor in factors:
        all_vals = [t[factor] for t in trades if t.get(factor) is not None]
        tp_vals = [t[factor] for t in trades if t.get(factor) is not None and t.get("outcome") == "HIT_TP"]
        sl_vals = [t[factor] for t in trades if t.get(factor) is not None and t.get("outcome") == "HIT_SL"]

        result[factor] = {
            "overall": compute_distribution(all_vals),
            "tp": compute_distribution(tp_vals),
            "sl": compute_distribution(sl_vals),
            "separation": None,
        }

        # Compute separation: how well TP and SL distributions separate
        if tp_vals and sl_vals:
            tp_median = sorted(tp_vals)[len(tp_vals) // 2]
            sl_median = sorted(sl_vals)[len(sl_vals) // 2]
            overall_std = (sum((v - sum(all_vals) / len(all_vals)) ** 2 for v in all_vals) / len(all_vals)) ** 0.5
            if overall_std > 0:
                separation = abs(tp_median - sl_median) / overall_std
                result[factor]["separation"] = round(separation, 3)

    return result


def compute_by_direction(
    trades: list[dict], factors: list[str]
) -> dict[str, dict[str, dict]]:
    """Compute distributions split by BUY vs SELL."""
    result = {}
    for direction in ["BUY", "SELL"]:
        subset = [t for t in trades if t.get("direction") == direction]
        if not subset:
            continue
        result[direction] = compute_factor_distributions(subset, factors)
    return result


def compute_by_regime(
    trades: list[dict], factors: list[str]
) -> dict[str, dict[str, dict]]:
    """Compute distributions split by regime."""
    regimes: dict[str, list[dict]] = {}
    for t in trades:
        r = t.get("regime") or "unknown"
        regimes.setdefault(r, []).append(t)

    result = {}
    for regime, subset in regimes.items():
        if len(subset) >= 5:
            result[regime] = compute_factor_distributions(subset, factors)
    return result


def print_distribution_table(dists: dict[str, dict]) -> None:
    """Print distribution table for all factors."""
    print("=" * 120)
    print("FACTOR DISTRIBUTIONS (TP vs SL)")
    print("=" * 120)
    print()
    print(f"  {'Factor':<25} {'N':>5} │ {'TP Median':>10} {'TP P5':>10} {'TP P95':>10} │ "
          f"{'SL Median':>10} {'SL P5':>10} {'SL P95':>10} │ {'Sep':>6}")
    print(f"  {'-'*25} {'-'*5} │ {'-'*10} {'-'*10} {'-'*10} │ "
          f"{'-'*10} {'-'*10} {'-'*10} │ {'-'*6}")

    for factor, d in sorted(dists.items()):
        tp = d.get("tp", {})
        sl = d.get("sl", {})
        sep = d.get("separation")

        tp_med = f"{tp.get('median', 0):.4f}" if tp else "N/A"
        tp_p5 = f"{tp.get('p5', 0):.4f}" if tp else "N/A"
        tp_p95 = f"{tp.get('p95', 0):.4f}" if tp else "N/A"
        sl_med = f"{sl.get('median', 0):.4f}" if sl else "N/A"
        sl_p5 = f"{sl.get('p5', 0):.4f}" if sl else "N/A"
        sl_p95 = f"{sl.get('p95', 0):.4f}" if sl else "N/A"
        sep_str = f"{sep:.3f}" if sep is not None else "N/A"
        n = d.get("overall", {}).get("count", 0)

        marker = " ★" if sep is not None and sep > 0.3 else ""
        print(f"  {factor:<25} {n:>5} │ {tp_med:>10} {tp_p5:>10} {tp_p95:>10} │ "
              f"{sl_med:>10} {sl_p5:>10} {sl_p95:>10} │ {sep_str:>6}{marker}")

    print()
    print("  Sep = Separation score (|TP_median - SL_median| / std). Higher = better discriminator.")
    print("  ★ = Separation > 0.3 (potentially useful as a gate)")


def print_percentile_ranges(dists: dict[str, dict]) -> None:
    """Print recommended ranges from percentiles."""
    print()
    print("=" * 120)
    print("RECOMMENDED RANGES (from TP trade percentiles)")
    print("=" * 120)
    print()
    print(f"  {'Factor':<25} {'TP P25-P75 (IQR)':>25} {'TP P5-P95':>25} {'Current useful range':>25}")
    print(f"  {'-'*25} {'-'*25} {'-'*25} {'-'*25}")

    for factor, d in sorted(dists.items()):
        tp = d.get("tp", {})
        if not tp or tp.get("count", 0) < 5:
            continue

        iqr_lo = tp.get("p25", 0)
        iqr_hi = tp.get("p75", 0)
        p5 = tp.get("p5", 0)
        p95 = tp.get("p95", 0)

        print(f"  {factor:<25} [{iqr_lo:>9.4f}, {iqr_hi:>9.4f}]  "
              f"[{p5:>9.4f}, {p95:>9.4f}]  "
              f"[{p5:.4f}, {p95:.4f}]")


def print_by_direction(dir_dists: dict[str, dict[str, dict]]) -> None:
    """Print BUY vs SELL comparison."""
    print()
    print("=" * 120)
    print("BUY vs SELL DISTRIBUTIONS")
    print("=" * 120)

    for direction in ["BUY", "SELL"]:
        if direction not in dir_dists:
            continue
        print(f"\n  {direction}:")
        print(f"  {'Factor':<25} {'TP Median':>10} {'SL Median':>10} {'Δ':>10} {'Sep':>6}")
        print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*10} {'-'*6}")

        for factor, d in sorted(dir_dists[direction].items()):
            tp = d.get("tp", {})
            sl = d.get("sl", {})
            sep = d.get("separation")

            tp_med = tp.get("median", 0) if tp else 0
            sl_med = sl.get("median", 0) if sl else 0
            delta = tp_med - sl_med
            sep_str = f"{sep:.3f}" if sep is not None else "N/A"

            print(f"  {factor:<25} {tp_med:>10.4f} {sl_med:>10.4f} {delta:>+10.4f} {sep_str:>6}")


def main():
    parser = argparse.ArgumentParser(description="Factor Distribution Analysis")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--factor", default=None, help="Show detailed distribution for one factor")
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    trades = load_signal_features(db_path)
    print(f"Loaded {len(trades)} completed signals with feature data")

    if not trades:
        print("No signals with outcome data found.")
        return

    dists = compute_factor_distributions(trades, DISTRIBUTION_FACTORS)
    dir_dists = compute_by_direction(trades, DISTRIBUTION_FACTORS)

    print_distribution_table(dists)
    print_percentile_ranges(dists)
    print_by_direction(dir_dists)

    if args.factor:
        if args.factor in dists:
            d = dists[args.factor]
            print(f"\n{'='*80}")
            print(f"DETAILED: {args.factor}")
            print("=" * 80)
            for group in ["overall", "tp", "sl"]:
                g = d.get(group, {})
                if g:
                    print(f"\n  {group.upper()}:")
                    for k, v in g.items():
                        print(f"    {k:<15} {v}")
        else:
            print(f"Factor '{args.factor}' not found.")

    if args.export:
        output = Path(__file__).resolve().parent.parent / "reports" / "distributions.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump(dists, f, indent=2, ensure_ascii=False)
        print(f"\nExported to {output}")


if __name__ == "__main__":
    main()
