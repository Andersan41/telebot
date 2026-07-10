"""
scripts/compare_cores.py — Compare old vs simplified gate cores.

Runs both the old (32 gates) and simplified (17 gates) pipelines
on the same data and compares signal generation.

Usage:
    python scripts/compare_cores.py [--db data/signals.db] [--days 30]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import numpy as np


def load_resolved_signals(db_path: str, days: int = 30) -> list[dict]:
    """Load resolved signals for comparison."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rows = conn.execute("""
        SELECT s.symbol, s.timeframe, s.signal_type, s.close_price,
               s.created_at, o.pnl_pct, o.status
        FROM signal_outcomes o
        JOIN signals s ON o.signal_id = s.id
        WHERE o.status IN ('HIT_TP', 'HIT_SL')
          AND s.created_at > ?
        ORDER BY s.created_at ASC
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_decision_traces(db_path: str, days: int = 30) -> list[dict]:
    """Load decision traces to see what gates blocked."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rows = conn.execute("""
        SELECT * FROM decision_traces
        WHERE timestamp > ?
        ORDER BY timestamp ASC
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def analyze_gate_blockers(traces: list[dict]) -> dict:
    """Analyze which gates block the most signals."""
    gate_stats = {}
    for t in traces:
        if t.get("signal_generated"):
            continue
        blocked_reason = t.get("blocked_reason")
        final_stage = t.get("final_stage")
        if final_stage:
            if final_stage not in gate_stats:
                gate_stats[final_stage] = {"count": 0, "has_outcome": 0, "wins": 0}
            gate_stats[final_stage]["count"] += 1
            if t.get("outcome"):
                gate_stats[final_stage]["has_outcome"] += 1
                if t["outcome"] == "HIT_TP":
                    gate_stats[final_stage]["wins"] += 1

    return gate_stats


def simulate_simplified(gate_stats: dict, traces: list[dict]) -> dict:
    """Estimate what would happen with simplified core.

    Gates removed in simplified:
    - btc_global_trend
    - no_trade_zones (ATR, market_structure, tp_blocked, OI)
    - context_block
    - ema_spread
    - candle_close
    - min_score
    - news

    This estimates how many blocked signals would pass with simplified core.
    """
    removable_gates = {
        "btc_global_trend", "no_trade_zones", "context_block",
        "ema_spread", "candle_close", "min_score", "news",
    }

    would_pass = 0
    would_pass_wins = 0
    for t in traces:
        if t.get("signal_generated"):
            continue
        final_stage = t.get("final_stage")
        if final_stage in removable_gates:
            would_pass += 1
            if t.get("outcome") == "HIT_TP":
                would_pass_wins += 1

    return {
        "would_pass": would_pass,
        "would_pass_wins": would_pass_wins,
        "would_pass_wr": round(would_pass_wins / would_pass * 100, 1) if would_pass > 0 else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Compare old vs simplified gate cores")
    parser.add_argument("--db", default="data/signals.db")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    signals = load_resolved_signals(args.db, args.days)
    traces = load_decision_traces(args.db, args.days)

    print(f"Loaded {len(signals)} resolved signals, {len(traces)} decision traces (last {args.days} days)")

    if not signals:
        print("No resolved signals found.")
        sys.exit(0)

    # Current performance
    outcomes = [1 if s["status"] == "HIT_TP" else 0 for s in signals]
    pnls = [s["pnl_pct"] or 0 for s in signals]

    wins = sum(outcomes)
    n = len(outcomes)
    wr = wins / n * 100 if n > 0 else 0
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    pf = gp / gl if gl > 0 else float("inf")

    print(f"\n{'='*70}")
    print(f"GATE CORE COMPARISON")
    print(f"{'='*70}")

    print(f"\n  Current (old core): {n} signals, WR={wr:.1f}%, PF={pf:.2f}")

    # Gate analysis
    gate_stats = analyze_gate_blockers(traces)
    print(f"\n--- Gate Blockers (last {args.days} days) ---")
    print(f"  {'Gate':<25} {'Blocked':>8} {'Has Outcome':>12} {'WR':>8}")
    print(f"  {'-'*25} {'-'*8} {'-'*12} {'-'*8}")

    for gate, stats in sorted(gate_stats.items(), key=lambda x: -x[1]["count"]):
        gate_wr = round(stats["wins"] / stats["has_outcome"] * 100, 1) if stats["has_outcome"] > 0 else "N/A"
        removable = " *" if gate in {
            "btc_global_trend", "no_trade_zones", "context_block",
            "ema_spread", "candle_close", "min_score", "news",
        } else ""
        print(f"  {gate:<25} {stats['count']:>8} {stats['has_outcome']:>12} {gate_wr:>7}%{removable}")

    print(f"\n  * = removable in simplified core")

    # Simplified core estimate
    simplified = simulate_simplified(gate_stats, traces)
    print(f"\n--- Simplified Core Estimate ---")
    print(f"  Signals that would pass instead of being blocked: {simplified['would_pass']}")
    print(f"  Estimated WR of added signals: {simplified['would_pass_wr']:.1f}%")

    if simplified["would_pass"] > 0:
        new_n = n + simplified["would_pass"]
        new_wins = wins + simplified["would_pass_wins"]
        new_wr = new_wins / new_n * 100

        # Estimate new PnL (assuming similar avg PnL)
        avg_win_pnl = sum(p for p in pnls if p > 0) / max(wins, 1)
        avg_loss_pnl = sum(p for p in pnls if p < 0) / max(n - wins, 1)

        new_gp = gp + simplified["would_pass_wins"] * avg_win_pnl
        new_gl = gl + (simplified["would_pass"] - simplified["would_pass_wins"]) * abs(avg_loss_pnl)
        new_pf = new_gp / new_gl if new_gl > 0 else float("inf")

        print(f"\n  Projected with simplified core:")
        print(f"    Signals: {n} → {new_n} (+{simplified['would_pass']})")
        print(f"    WR:      {wr:.1f}% → {new_wr:.1f}% ({new_wr - wr:+.1f}%)")
        print(f"    PF:      {pf:.2f} → {new_pf:.2f} ({new_pf - pf:+.2f})")

        if new_wr > wr and new_pf >= pf:
            print(f"\n  [BETTER] Simplified core projected to improve both WR and PF")
        elif new_wr > wr:
            print(f"\n  [MIXED] WR improves but PF may decrease — investigate added signals")
        else:
            print(f"\n  [WORSE] Simplified core projected to degrade performance")
    else:
        print(f"\n  No signals would change with simplified core.")
        print(f"  The removed gates are not currently blocking any signals.")

    # Recommendations
    print(f"\n--- Recommendations ---")
    print(f"  1. Enable shadow mode: SHADOW_ENABLED=true, SHADOW_PRESET=simplified")
    print(f"  2. Run for 2-4 weeks to collect parallel data")
    print(f"  3. Use scripts/shadow_compare.py to compare actual results")
    print(f"  4. Only then decide whether to switch to simplified core")


if __name__ == "__main__":
    main()
