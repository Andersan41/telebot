"""
scripts/shadow_compare.py — Compare shadow/paper version against live version.

The checklist says: "Compare on identical market conditions. This is the only
honest way if you don't have enough volume for control mode."

Usage:
    python scripts/shadow_compare.py [--db data/signals.db]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np


def load_live_signals(db_path: str) -> list[dict]:
    """Load live signals with outcomes."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT s.symbol, s.timeframe, s.signal_type, s.close_price,
               s.created_at, o.pnl_pct, o.status
        FROM signal_outcomes o
        JOIN signals s ON o.signal_id = s.id
        WHERE o.status IN ('HIT_TP', 'HIT_SL')
        ORDER BY s.created_at ASC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_shadow_signals(db_path: str) -> list[dict]:
    """Load shadow signals (if stored in shadow_decisions table)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Check if shadow table exists
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='shadow_decisions'"
    )
    if cur.fetchone() is None:
        conn.close()
        return []

    rows = conn.execute("""
        SELECT * FROM shadow_decisions ORDER BY timestamp ASC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def compute_stats(signals: list[dict]) -> dict:
    """Compute basic stats for a set of signals."""
    if not signals:
        return {"n": 0, "wr": 0, "pf": 0, "total_pnl": 0}

    outcomes = [1 if s.get("status") == "HIT_TP" or s.get("outcome") == "HIT_TP" else 0
                for s in signals]
    pnls = [s.get("pnl_pct", 0) or 0 for s in signals]

    wins = sum(outcomes)
    n = len(outcomes)
    wr = wins / n * 100 if n > 0 else 0

    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    return {
        "n": n,
        "wins": wins,
        "losses": n - wins,
        "wr": round(wr, 1),
        "pf": round(pf, 2),
        "total_pnl": round(sum(pnls), 2),
        "avg_pnl": round(np.mean(pnls), 3) if pnls else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Shadow vs Live comparison")
    parser.add_argument("--db", default="data/signals.db")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    live = load_live_signals(args.db)
    shadow = load_shadow_signals(args.db)

    if not shadow:
        print("No shadow signals found.")
        print("Enable shadow mode with SHADOW_ENABLED=true in .env")
        print("and let the bot run to collect shadow decisions.")
        sys.exit(0)

    print(f"Loaded {len(live)} live signals, {len(shadow)} shadow signals\n")

    live_stats = compute_stats(live)
    shadow_stats = compute_stats(shadow)

    print("=" * 60)
    print("SHADOW vs LIVE COMPARISON")
    print("=" * 60)

    print(f"\n{'Metric':<20} {'Live':>12} {'Shadow':>12} {'Delta':>12}")
    print("-" * 58)

    for metric in ["n", "wr", "pf", "total_pnl", "avg_pnl"]:
        live_val = live_stats[metric]
        shadow_val = shadow_stats[metric]
        delta = shadow_val - live_val

        if metric in ("wr", "total_pnl", "avg_pnl"):
            fmt = f"{live_val:>11.1f}% {shadow_val:>11.1f}% {delta:>+11.1f}%" if metric == "wr" else \
                  f"{live_val:>11.2f} {shadow_val:>11.2f} {delta:>+11.2f}"
        elif metric == "pf":
            fmt = f"{live_val:>12.2f} {shadow_val:>12.2f} {delta:>+12.2f}"
        else:
            fmt = f"{live_val:>12} {shadow_val:>12} {delta:>+12}"

        print(f"  {metric:<18} {fmt}")

    # Verdict
    print("\n" + "=" * 60)
    print("VERDICT")
    print("=" * 60)

    wr_diff = shadow_stats["wr"] - live_stats["wr"]
    pf_diff = shadow_stats["pf"] - live_stats["pf"]

    if wr_diff > 2 and pf_diff >= 0:
        print("\n  [SHADOW BETTER] Shadow version outperforms live.")
        print(f"  WR difference: {wr_diff:+.1f}%, PF difference: {pf_diff:+.2f}")
        print("  Recommendation: consider switching to shadow version.")
    elif wr_diff < -2 or pf_diff < -0.2:
        print("\n  [SHADOW WORSE] Shadow version underperforms live.")
        print(f"  WR difference: {wr_diff:+.1f}%, PF difference: {pf_diff:+.2f}")
        print("  Recommendation: keep current live version.")
    else:
        print("\n  [SIMILAR] Shadow and live performance are comparable.")
        print(f"  WR difference: {wr_diff:+.1f}%, PF difference: {pf_diff:+.2f}")
        print("  Recommendation: collect more data before deciding.")

    # Per-symbol breakdown
    if len(shadow) > 10:
        print(f"\n--- Per-Symbol Breakdown ---")
        live_by_symbol = {}
        for s in live:
            sym = s["symbol"]
            if sym not in live_by_symbol:
                live_by_symbol[sym] = []
            live_by_symbol[sym].append(s)

        shadow_by_symbol = {}
        for s in shadow:
            sym = s.get("symbol", "unknown")
            if sym not in shadow_by_symbol:
                shadow_by_symbol[sym] = []
            shadow_by_symbol[sym].append(s)

        all_symbols = set(list(live_by_symbol.keys()) + list(shadow_by_symbol.keys()))
        print(f"\n  {'Symbol':<15} {'Live WR':>10} {'Shadow WR':>12} {'Live N':>8} {'Shadow N':>10}")
        print(f"  {'-'*15} {'-'*10} {'-'*12} {'-'*8} {'-'*10}")

        for sym in sorted(all_symbols):
            live_s = compute_stats(live_by_symbol.get(sym, []))
            shadow_s = compute_stats(shadow_by_symbol.get(sym, []))
            print(f"  {sym:<15} {live_s['wr']:>9.1f}% {shadow_s['wr']:>11.1f}% "
                  f"{live_s['n']:>8} {shadow_s['n']:>10}")


if __name__ == "__main__":
    main()
