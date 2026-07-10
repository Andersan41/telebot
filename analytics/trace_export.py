"""
analytics/trace_export.py — Full DecisionTrace export for 300-1000+ completed trades.

Joins decision_traces ↔ signal_candidates ↔ signal_outcomes into a single
flat dataset. Every row = one pipeline pass with full gate results, feature
snapshot, and outcome.

Usage:
    python -m analytics.trace_export [--db data/signals.db] [--output reports/trace_export.csv]
    python -m analytics.trace_export --format json
    python -m analytics.trace_export --signal-only  # only signal_generated=True
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "signals.db"

GATE_COLUMNS = [
    "gate_cooldown", "gate_portfolio_risk", "gate_btc_global_trend",
    "gate_indicators", "gate_confirm_tf", "gate_signal_engine",
    "gate_distance_filter", "gate_tp_path", "gate_mtf_alignment",
    "gate_btc_correlation", "gate_eth_correlation", "gate_volatility",
    "gate_context_timeout", "gate_context_block", "gate_context_min_verdict",
    "gate_news", "gate_sl_distance", "gate_rr_guard", "gate_no_trade_zones",
    "gate_dynamic_risk", "gate_confidence_v2", "gate_dedup",
    "gate_compression_block",
]

FEATURE_COLUMNS = [
    "adx", "rsi", "ema_short", "ema_long", "ema_spread_pct",
    "macd_hist", "supertrend_direction", "volume_ratio",
    "dmi_strength", "ema_strength",
    "signal_score", "confidence",
    "regime", "direction",
    "sl_source", "tp_distance_pct", "sl_distance_pct", "rr_ratio",
    "has_bos", "has_sweep", "has_ob", "ob_distance_pct",
    "context_score", "btc_trend_strength", "mtf_alignment_score",
    "atr_pct", "ema_slope_3", "ema_slope_5",
    "nearest_support_pct", "nearest_resistance_pct", "regime_confidence",
]

METADATA_COLUMNS = [
    "id", "symbol", "timeframe", "timestamp",
    "final_stage", "blocked_reason", "signal_generated",
    "signal_type", "score", "close_price", "sl", "tp",
    "strategy_version", "config_snapshot",
    "signal_id", "candidate_id",
    "outcome", "pnl_pct",
    "gate_path",
]

ALL_COLUMNS = METADATA_COLUMNS + GATE_COLUMNS + FEATURE_COLUMNS


def load_traces(
    db_path: str | Path,
    signal_only: bool = False,
    symbol: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Load decision traces with optional filters.

    Args:
        db_path: Path to SQLite database.
        signal_only: If True, only rows where signal_generated=True.
        symbol: Filter by symbol.
        since: ISO timestamp — only rows after this time.

    Returns:
        List of dicts, one per trace row.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    conditions = []
    params: list[Any] = []

    if signal_only:
        conditions.append("signal_generated = 1")
    if symbol:
        conditions.append("symbol = ?")
        params.append(symbol)
    if since:
        conditions.append("timestamp >= ?")
        params.append(since)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT * FROM decision_traces {where} ORDER BY timestamp"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [dict(row) for row in rows]


def export_csv(traces: list[dict], output: str | Path) -> None:
    """Export traces to CSV."""
    if not traces:
        print("No traces to export.")
        return

    # Filter columns to those that exist in the data
    available = [c for c in ALL_COLUMNS if c in traces[0]]

    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=available, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(traces)

    print(f"Exported {len(traces)} traces to {output}")


def export_json(traces: list[dict], output: str | Path) -> None:
    """Export traces to JSON."""
    with open(output, "w", encoding="utf-8") as f:
        json.dump(traces, f, indent=2, ensure_ascii=False, default=str)
    print(f"Exported {len(traces)} traces to {output}")


def print_summary(traces: list[dict]) -> None:
    """Print summary statistics of the export."""
    if not traces:
        print("No traces found.")
        return

    total = len(traces)
    signals = sum(1 for t in traces if t.get("signal_generated"))
    wins = sum(1 for t in traces if t.get("outcome") == "HIT_TP")
    losses = sum(1 for t in traces if t.get("outcome") == "HIT_SL")
    closed = wins + losses

    symbols = set(t.get("symbol", "") for t in traces)
    versions = set(t.get("strategy_version", "unknown") for t in traces if t.get("strategy_version"))
    timeframes = set(t.get("timeframe", "") for t in traces)

    # Gate pass rates
    gate_stats: dict[str, dict] = {}
    for col in GATE_COLUMNS:
        entered = sum(1 for t in traces if t.get(col) is not None)
        passed = sum(1 for t in traces if t.get(col) is True)
        if entered > 0:
            gate_stats[col] = {"entered": entered, "passed": passed, "rate": passed / entered * 100}

    # Feature ranges for signals
    signal_traces = [t for t in traces if t.get("signal_generated")]
    feature_ranges: dict[str, dict] = {}
    for col in FEATURE_COLUMNS:
        values = [t[col] for t in signal_traces if t.get(col) is not None]
        if values:
            sorted_vals = sorted(values)
            n = len(sorted_vals)
            feature_ranges[col] = {
                "min": sorted_vals[0],
                "max": sorted_vals[-1],
                "median": sorted_vals[n // 2],
                "p5": sorted_vals[max(0, int(n * 0.05))],
                "p95": sorted_vals[min(n - 1, int(n * 0.95))],
            }

    # Final stage distribution
    final_stages: dict[str, int] = {}
    for t in traces:
        stage = t.get("final_stage") or "unknown"
        final_stages[stage] = final_stages.get(stage, 0) + 1

    print("=" * 80)
    print("DECISION TRACE EXPORT SUMMARY")
    print("=" * 80)
    print(f"\n  Total traces:        {total:,}")
    print(f"  Signals generated:   {signals:,} ({signals / total * 100:.1f}%)")
    print(f"  Completed trades:    {closed} (TP={wins}, SL={losses})")
    if closed > 0:
        print(f"  Win Rate:            {wins / closed * 100:.1f}%")
    print(f"  Symbols:             {', '.join(sorted(symbols))}")
    print(f"  Timeframes:          {', '.join(sorted(timeframes))}")
    print(f"  Strategy versions:   {', '.join(sorted(versions)) if versions else 'N/A'}")

    print(f"\n{'='*80}")
    print("GATE PASS RATES (from full candidate pool)")
    print("=" * 80)
    print(f"\n  {'Gate':<30} {'Entered':>8} {'Passed':>8} {'Rate':>8}")
    print(f"  {'-'*30} {'-'*8} {'-'*8} {'-'*8}")
    for gate, stats in sorted(gate_stats.items(), key=lambda x: x[1]["entered"], reverse=True):
        print(f"  {gate:<30} {stats['entered']:>8,} {stats['passed']:>8,} {stats['rate']:>7.1f}%")

    print(f"\n{'='*80}")
    print("FINAL STAGE DISTRIBUTION")
    print("=" * 80)
    for stage, count in sorted(final_stages.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        print(f"  {stage:<35} {count:>8,} ({pct:>5.1f}%)")

    if feature_ranges:
        print(f"\n{'='*80}")
        print("SIGNAL FEATURE RANGES (min / P5 / median / P95 / max)")
        print("=" * 80)
        print(f"\n  {'Feature':<25} {'Min':>8} {'P5':>8} {'Median':>8} {'P95':>8} {'Max':>8}")
        print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
        for col, rng in feature_ranges.items():
            print(f"  {col:<25} {rng['min']:>8.2f} {rng['p5']:>8.2f} "
                  f"{rng['median']:>8.2f} {rng['p95']:>8.2f} {rng['max']:>8.2f}")


def main():
    parser = argparse.ArgumentParser(description="Export DecisionTrace data")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite database path")
    parser.add_argument("--output", "-o", default=None, help="Output file path")
    parser.add_argument("--format", choices=["csv", "json"], default="csv")
    parser.add_argument("--signal-only", action="store_true", help="Only signal_generated=True")
    parser.add_argument("--symbol", default=None, help="Filter by symbol")
    parser.add_argument("--since", default=None, help="ISO timestamp filter")
    parser.add_argument("--summary-only", action="store_true", help="Print summary only")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    traces = load_traces(db_path, signal_only=args.signal_only, symbol=args.symbol, since=args.since)
    print(f"Loaded {len(traces)} traces from {db_path}")

    if args.summary_only:
        print_summary(traces)
        return

    print_summary(traces)

    if args.output:
        output = Path(args.output)
    else:
        suffix = "json" if args.format == "json" else "csv"
        output = Path(__file__).resolve().parent.parent / "reports" / f"trace_export.{suffix}"

    output.parent.mkdir(parents=True, exist_ok=True)

    if args.format == "json":
        export_json(traces, output)
    else:
        export_csv(traces, output)


if __name__ == "__main__":
    main()
