"""
scripts/virtual_outcomes.py — Track virtual outcomes for rejected candidates.

The checklist says:
- "Log feature snapshot and 'virtual outcome' for rejected candidates too
  (what would have happened if you took the trade)"
- "Periodically take rejected signals with small capital to collect data
  outside blind spots"

This script simulates outcomes for candidates that were blocked by gates,
using the same SL/TP calculation logic. This enables true counterfactual
analysis (Step 5).

Usage:
    python scripts/virtual_outcomes.py [--db data/signals.db] [--days 30]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import numpy as np


def load_rejected_candidates(db_path: str, days: int = 30) -> list[dict]:
    """Load rejected candidates that have price data for virtual outcome tracking.

    Candidates are "rejected" if they passed signal_engine but were blocked
    by a downstream gate (blocked_gate is not null).
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rows = conn.execute("""
        SELECT id, symbol, timeframe, timestamp, signal_type,
               close_price, sl, tp, blocked_gate, outcome, pnl_pct,
               st_strength, ema_strength, macd_strength, rsi_strength,
               vol_strength, adx_strength, dmi_strength, weighted_score,
               regime, mtf_aligned, has_trigger
        FROM signal_candidates
        WHERE blocked_gate IS NOT NULL
          AND blocked_gate != 'signal_engine'
          AND blocked_gate != 'indicators'
          AND close_price IS NOT NULL
          AND sl IS NOT NULL
          AND tp IS NOT NULL
          AND timestamp > ?
        ORDER BY timestamp DESC
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def simulate_outcome(
    signal_type: str,
    entry_price: float,
    sl: float,
    tp: float,
    high_prices: list[float],
    low_prices: list[float],
) -> dict:
    """Simulate what would have happened if the trade was taken.

    Uses high/low prices to check if SL or TP was hit first.
    """
    if signal_type == "BUY":
        for i, (high, low) in enumerate(zip(high_prices, low_prices)):
            if low <= sl:
                return {"outcome": "HIT_SL", "bars_to_exit": i + 1}
            if high >= tp:
                return {"outcome": "HIT_TP", "bars_to_exit": i + 1}
    else:  # SELL
        for i, (high, low) in enumerate(zip(high_prices, low_prices)):
            if high >= sl:
                return {"outcome": "HIT_SL", "bars_to_exit": i + 1}
            if low <= tp:
                return {"outcome": "HIT_TP", "bars_to_exit": i + 1}

    return {"outcome": "OPEN", "bars_to_exit": None}


def main():
    parser = argparse.ArgumentParser(description="Virtual outcome tracking for rejected candidates")
    parser.add_argument("--db", default="data/signals.db")
    parser.add_argument("--days", type=int, default=30, help="Look back N days")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be tracked")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    candidates = load_rejected_candidates(args.db, args.days)
    print(f"Found {len(candidates)} rejected candidates (last {args.days} days)")

    if not candidates:
        print("No rejected candidates found with SL/TP data.")
        sys.exit(0)

    # Group by gate
    by_gate = {}
    for c in candidates:
        gate = c["blocked_gate"]
        if gate not in by_gate:
            by_gate[gate] = []
        by_gate[gate].append(c)

    print(f"\n--- Rejected Candidates by Gate ---")
    for gate, cands in sorted(by_gate.items(), key=lambda x: -len(x[1])):
        print(f"  {gate:<25} {len(cands):>5} candidates")

    # Stats on rejected candidates
    print(f"\n--- Candidate Stats ---")
    all_scores = [c["weighted_score"] or 0 for c in candidates]
    all_regimes = [c["regime"] or "unknown" for c in candidates]
    all_mtf = [c["mtf_aligned"] or False for c in candidates]

    print(f"  Avg weighted_score: {np.mean(all_scores):.2f}")
    print(f"  Regimes: {dict(zip(*np.unique(all_regimes, return_counts=True)))}")
    print(f"  MTF aligned: {sum(all_mtf)}/{len(all_mtf)} ({sum(all_mtf)/len(all_mtf)*100:.0f}%)")

    # Virtual outcome tracking
    print(f"\n--- Virtual Outcome Analysis ---")
    print(f"  NOTE: To compute virtual outcomes, you need historical OHLCV data")
    print(f"  for each candidate's symbol/timeframe after the signal time.")
    print(f"  This requires fetching exchange data for each rejected candidate.")

    # Estimate potential edge
    passed_scores = [c["weighted_score"] or 0 for c in candidates
                     if c.get("outcome") == "HIT_TP"]
    failed_scores = [c["weighted_score"] or 0 for c in candidates
                     if c.get("outcome") == "HIT_SL"]

    if passed_scores and failed_scores:
        print(f"\n  If these candidates had been taken:")
        print(f"  Passed (TP) avg score: {np.mean(passed_scores):.2f}")
        print(f"  Failed (SL) avg score: {np.mean(failed_scores):.2f}")
        print(f"  Score gap: {np.mean(passed_scores) - np.mean(failed_scores):+.2f}")
    else:
        print(f"\n  No outcome data available for rejected candidates.")
        print(f"  Run this script after collecting virtual outcomes.")

    # Recommendations
    print(f"\n--- Recommendations ---")
    print(f"  1. Enable virtual outcome tracking in the scanner to log outcomes")
    print(f"     for candidates blocked by downstream gates (not signal_engine)")
    print(f"  2. Periodically (5-10% of capital) take rejected candidates to")
    print(f"     collect real data outside the strategy's blind spots")
    print(f"  3. Use the data for true counterfactual analysis in Step 5")


if __name__ == "__main__":
    main()
