"""
analytics/drift_report.py — Weekly drift report.

Tracks factor performance, regime WR, and signal quality over rolling
time windows. Detects when a factor/regime that used to work stops working.

Usage:
    python -m analytics.drift_report [--db data/signals.db] [--weeks 8]
    python -m analytics.drift_report --window 14d
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "signals.db"

DRIFT_FACTORS = [
    "adx", "rsi", "ema_spread_pct", "volume_ratio", "macd_hist",
    "atr_pct", "confidence", "rr_ratio",
    "tp_distance_pct", "sl_distance_pct",
    "btc_trend_strength", "context_score", "mtf_alignment_score",
]


def load_weekly_trades(db_path: str | Path, weeks: int = 8) -> list[dict]:
    """Load trades from the last N weeks."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    cutoff = datetime.now(timezone.utc) - timedelta(weeks=weeks)

    query = """
        SELECT
            s.id, s.symbol, s.signal_type, s.close_price,
            s.created_at,
            o.status, o.pnl_pct, o.closed_at,
            dt.adx, dt.rsi, dt.ema_spread_pct, dt.volume_ratio,
            dt.macd_hist, dt.atr_pct, dt.confidence, dt.rr_ratio,
            dt.tp_distance_pct, dt.sl_distance_pct,
            dt.btc_trend_strength, dt.context_score, dt.mtf_alignment_score,
            dt.regime, dt.strategy_version
        FROM signals s
        JOIN signal_outcomes o ON s.id = o.signal_id
        LEFT JOIN decision_traces dt ON dt.signal_id = s.id
        WHERE o.status IN ('HIT_TP', 'HIT_SL')
          AND s.created_at >= ?
        ORDER BY s.created_at
    """

    rows = conn.execute(query, [cutoff.isoformat()]).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_week_label(dt_str: str | None) -> str:
    """Convert timestamp to ISO week label: '2024-W25'."""
    if not dt_str:
        return "unknown"
    try:
        if isinstance(dt_str, str):
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        else:
            dt = dt_str
        iso_cal = dt.isocalendar()
        return f"{iso_cal[0]}-W{iso_cal[1]:02d}"
    except (ValueError, TypeError):
        return "unknown"


def compute_weekly_factor_drift(
    trades: list[dict], factors: list[str]
) -> dict[str, list[dict]]:
    """Per factor, per week: WR, avg value, trade count."""
    weekly: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "total": 0, "values": [], "pnls": []}))

    for t in trades:
        week = get_week_label(t.get("created_at"))
        for f in factors:
            val = t.get(f)
            if val is None:
                continue
            weekly[f][week]["total"] += 1
            weekly[f][week]["values"].append(val)
            weekly[f][week]["pnls"].append(t.get("pnl_pct", 0))
            if t.get("status") == "HIT_TP":
                weekly[f][week]["wins"] += 1

    result: dict[str, list[dict]] = {}
    for factor, weeks in weekly.items():
        week_list = []
        for week_label in sorted(weeks.keys()):
            d = weeks[week_label]
            n = d["total"]
            wr = d["wins"] / n * 100 if n > 0 else 0
            avg_val = sum(d["values"]) / len(d["values"]) if d["values"] else 0
            avg_pnl = sum(d["pnls"]) / len(d["pnls"]) if d["pnls"] else 0

            sorted_vals = sorted(d["values"])
            p5 = sorted_vals[int(len(sorted_vals) * 0.05)] if sorted_vals else 0
            p95 = sorted_vals[int(len(sorted_vals) * 0.95)] if sorted_vals else 0

            week_list.append({
                "week": week_label,
                "trades": n,
                "wr": round(wr, 1),
                "avg_value": round(avg_val, 4),
                "p5": round(p5, 4),
                "p95": round(p95, 4),
                "avg_pnl": round(avg_pnl, 3),
            })
        result[factor] = week_list

    return result


def compute_weekly_regime_drift(trades: list[dict]) -> dict[str, list[dict]]:
    """Per regime, per week: WR, count."""
    weekly: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "total": 0}))

    for t in trades:
        week = get_week_label(t.get("created_at"))
        regime = t.get("regime") or "unknown"
        weekly[regime][week]["total"] += 1
        if t.get("status") == "HIT_TP":
            weekly[regime][week]["wins"] += 1

    result: dict[str, list[dict]] = {}
    for regime, weeks in weekly.items():
        week_list = []
        for week_label in sorted(weeks.keys()):
            d = weeks[week_label]
            n = d["total"]
            wr = d["wins"] / n * 100 if n > 0 else 0
            week_list.append({
                "week": week_label,
                "trades": n,
                "wr": round(wr, 1),
            })
        result[regime] = week_list

    return result


def detect_drift(weekly_data: list[dict], min_weeks: int = 3) -> dict | None:
    """Detect if a factor's performance is drifting.

    Compares first half vs second half of available weeks.
    Returns drift info if significant change detected.
    """
    if len(weekly_data) < min_weeks:
        return None

    mid = len(weekly_data) // 2
    first_half = weekly_data[:mid]
    second_half = weekly_data[mid:]

    # Filter to weeks with enough trades
    first_valid = [w for w in first_half if w["trades"] >= 3]
    second_valid = [w for w in second_half if w["trades"] >= 3]

    if not first_valid or not second_valid:
        return None

    first_wr = sum(w["wr"] * w["trades"] for w in first_valid) / sum(w["trades"] for w in first_valid)
    second_wr = sum(w["wr"] * w["trades"] for w in second_valid) / sum(w["trades"] for w in second_valid)

    first_avg_val = sum(w["avg_value"] * w["trades"] for w in first_valid) / sum(w["trades"] for w in first_valid)
    second_avg_val = sum(w["avg_value"] * w["trades"] for w in second_valid) / sum(w["trades"] for w in second_valid)

    wr_delta = second_wr - first_wr
    val_delta = second_avg_val - first_avg_val

    if abs(wr_delta) < 2.0:
        return None

    direction = "DEGRADED" if wr_delta < -2 else "IMPROVED"

    return {
        "direction": direction,
        "first_wr": round(first_wr, 1),
        "second_wr": round(second_wr, 1),
        "wr_delta": round(wr_delta, 1),
        "first_avg_value": round(first_avg_val, 4),
        "second_avg_value": round(second_avg_val, 4),
        "val_delta": round(val_delta, 4),
    }


def print_drift_report(
    factor_drift: dict[str, list[dict]],
    regime_drift: dict[str, list[dict]],
) -> None:
    """Print the drift report."""
    print("=" * 100)
    print("WEEKLY DRIFT REPORT")
    print("=" * 100)

    # Factor drift
    print()
    print("FACTOR DRIFT (weighted WR by week)")
    print()

    for factor, weeks in factor_drift.items():
        if len(weeks) < 2:
            continue

        drift = detect_drift(weeks)
        marker = ""
        if drift:
            marker = f" ← {drift['direction']} (ΔWR={drift['wr_delta']:+.1f}%)"

        print(f"  {factor}{marker}")
        print(f"  {'Week':<10} {'N':>4} {'WR':>7} {'AvgVal':>10} {'P5':>10} {'P95':>10} {'AvgPnL':>9}")
        print(f"  {'-'*10} {'-'*4} {'-'*7} {'-'*10} {'-'*10} {'-'*10} {'-'*9}")

        for w in weeks:
            print(f"  {w['week']:<10} {w['trades']:>4} {w['wr']:>6.1f}% "
                  f"{w['avg_value']:>10.4f} {w['p5']:>10.4f} {w['p95']:>10.4f} "
                  f"{w['avg_pnl']:>+8.3f}%")
        print()

    # Regime drift
    print("=" * 100)
    print("REGIME DRIFT (WR by week)")
    print()

    for regime, weeks in regime_drift.items():
        if len(weeks) < 2:
            continue

        drift = detect_drift(weeks)
        marker = ""
        if drift:
            marker = f" ← {drift['direction']} (ΔWR={drift['wr_delta']:+.1f}%)"

        print(f"  {regime}{marker}")
        print(f"  {'Week':<10} {'N':>4} {'WR':>7}")
        print(f"  {'-'*10} {'-'*4} {'-'*7}")

        for w in weeks:
            bar = "#" * int(w["wr"] / 2)
            print(f"  {w['week']:<10} {w['trades']:>4} {w['wr']:>6.1f}% {bar}")
        print()

    # Summary of drifters
    print("=" * 100)
    print("DRIFT DETECTION SUMMARY")
    print()

    drifters = []
    for factor, weeks in factor_drift.items():
        drift = detect_drift(weeks)
        if drift:
            drifters.append((factor, drift))

    drifters.sort(key=lambda x: abs(x[1]["wr_delta"]), reverse=True)

    if drifters:
        for factor, d in drifters:
            print(f"  {factor:<25} {d['direction']:<12} "
                  f"WR: {d['first_wr']:.1f}% → {d['second_wr']:.1f}% (Δ={d['wr_delta']:+.1f}%)  "
                  f"Value: {d['first_avg_value']:.4f} → {d['second_avg_value']:.4f}")
    else:
        print("  No significant drift detected.")

    print()


def main():
    parser = argparse.ArgumentParser(description="Weekly Drift Report")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--weeks", type=int, default=8)
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    trades = load_weekly_trades(db_path, weeks=args.weeks)
    print(f"Loaded {len(trades)} trades from last {args.weeks} weeks")

    if not trades:
        print("No trades found for the specified period.")
        return

    factor_drift = compute_weekly_factor_drift(trades, DRIFT_FACTORS)
    regime_drift = compute_weekly_regime_drift(trades)

    print_drift_report(factor_drift, regime_drift)

    if args.export:
        output = Path(__file__).resolve().parent.parent / "reports" / "drift_report.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump({
                "factor_drift": factor_drift,
                "regime_drift": regime_drift,
            }, f, indent=2, ensure_ascii=False)
        print(f"Exported to {output}")


if __name__ == "__main__":
    main()
