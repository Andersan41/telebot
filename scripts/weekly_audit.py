"""
scripts/weekly_audit.py — Weekly performance audit with CUSUM drift detection.

The checklist says:
- "Don't give recommendations per week. Accumulate metric and look at it with CI."
- "For drift detection use something robust (e.g. CUSUM-like threshold on cumulative
  WR difference), not 'this week is worse than last'."

Usage:
    python scripts/weekly_audit.py [--db data/signals.db] [--window 7]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np


def load_signals(db_path: str) -> list[dict]:
    """Load all resolved signals with timestamps."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT s.created_at, s.symbol, s.signal_type, s.close_price,
               o.pnl_pct, o.status
        FROM signal_outcomes o
        JOIN signals s ON o.signal_id = s.id
        WHERE o.status IN ('HIT_TP', 'HIT_SL')
        ORDER BY s.created_at ASC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cusum_drift_detection(
    outcomes: list[int],
    threshold: float = 2.0,
    drift: float = 0.0,
) -> list[dict]:
    """CUSUM (Cumulative Sum) drift detection on binary outcomes.

    Detects sustained shifts in win rate by accumulating deviations
    from expected performance.

    Args:
        outcomes: list of 1 (win) or 0 (loss)
        threshold: CUSUM threshold for alarm
        drift: allowance for random variation (0 = detect any shift)

    Returns:
        List of alarm points with index and cumulative sum
    """
    n = len(outcomes)
    if n == 0:
        return []

    expected_wr = np.mean(outcomes)
    alarms = []

    # Upper CUSUM (detecting decrease in WR)
    s_upper = 0.0
    # Lower CUSUM (detecting increase in WR)
    s_lower = 0.0

    for i, outcome in enumerate(outcomes):
        deviation = outcome - expected_wr
        s_upper = max(0, s_upper + deviation - drift)
        s_lower = max(0, s_lower - deviation - drift)

        if s_upper > threshold:
            alarms.append({"index": i, "type": "DEGRADATION", "cusum": s_upper})
            s_upper = 0.0
        if s_lower > threshold:
            alarms.append({"index": i, "type": "IMPROVEMENT", "cusum": s_lower})
            s_lower = 0.0

    return alarms


def compute_rolling_metrics(
    outcomes: list[int], pnls: list[float], window: int = 7
) -> list[dict]:
    """Compute rolling window metrics."""
    n = len(outcomes)
    metrics = []

    for i in range(window, n + 1):
        window_outcomes = outcomes[i - window:i]
        window_pnls = pnls[i - window:i]

        wins = sum(window_outcomes)
        total = len(window_outcomes)
        wr = wins / total * 100 if total > 0 else 0

        gross_profit = sum(p for p in window_pnls if p > 0)
        gross_loss = abs(sum(p for p in window_pnls if p < 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        metrics.append({
            "window_end": i,
            "n_trades": total,
            "wins": wins,
            "wr": wr,
            "pf": pf,
            "total_pnl": sum(window_pnls),
            "avg_pnl": np.mean(window_pnls),
        })

    return metrics


def main():
    parser = argparse.ArgumentParser(description="Weekly audit with CUSUM drift detection")
    parser.add_argument("--db", default="data/signals.db")
    parser.add_argument("--window", type=int, default=7, help="Rolling window size (trades)")
    parser.add_argument("--cusum-threshold", type=float, default=2.0,
                        help="CUSUM alarm threshold")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    signals = load_signals(args.db)
    if not signals:
        print("No resolved signals found.")
        sys.exit(1)

    print(f"Loaded {len(signals)} resolved signals")

    outcomes = [1 if s["status"] == "HIT_TP" else 0 for s in signals]
    pnls = [s["pnl_pct"] or 0.0 for s in signals]

    # Overall stats
    total_wins = sum(outcomes)
    total_trades = len(outcomes)
    overall_wr = total_wins / total_trades * 100
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    overall_pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    print(f"\n{'='*70}")
    print(f"WEEKLY AUDIT REPORT")
    print(f"{'='*70}")
    print(f"\n  Overall: {total_trades} trades, WR={overall_wr:.1f}%, "
          f"PF={overall_pf:.2f}, TotalPnL={sum(pnls):+.2f}%")

    # Rolling metrics
    print(f"\n--- Rolling Window (last {args.window} trades) ---")
    rolling = compute_rolling_metrics(outcomes, pnls, args.window)

    if rolling:
        recent = rolling[-1]
        print(f"  Current window: {recent['n_trades']} trades, "
              f"WR={recent['wr']:.1f}%, PF={recent['pf']:.2f}, "
              f"PnL={recent['total_pnl']:+.2f}%")

        # Trend in rolling WR
        if len(rolling) >= 3:
            wr_values = [m["wr"] for m in rolling[-10:]]
            trend = "IMPROVING" if wr_values[-1] > wr_values[0] + 2 else \
                    "DEGRADING" if wr_values[-1] < wr_values[0] - 2 else "STABLE"
            print(f"  Trend (last {len(wr_values)} windows): {trend}")

    # CUSUM drift detection
    print(f"\n--- CUSUM Drift Detection (threshold={args.cusum_threshold}) ---")
    alarms = cusum_drift_detection(outcomes, threshold=args.cusum_threshold)

    if alarms:
        print(f"\n  DRIFT DETECTED:")
        for alarm in alarms:
            trade = signals[alarm["index"]]
            date = trade["created_at"][:10] if trade.get("created_at") else "unknown"
            print(f"    [{alarm['type']}] Trade #{alarm['index']+1} ({date}): "
                  f"CUSUM={alarm['cusum']:.2f}")
        print(f"\n  Recommendation: investigate recent performance. "
              f"Check if market regime changed.")
    else:
        print(f"  No drift detected. Performance is stable.")

    # Per-regime breakdown (if regime data available)
    print(f"\n--- Recent Performance (last 20 trades) ---")
    recent_20 = signals[-20:]
    recent_outcomes = [1 if s["status"] == "HIT_TP" else 0 for s in recent_20]
    recent_pnls = [s["pnl_pct"] or 0.0 for s in recent_20]

    if recent_20:
        r_wins = sum(recent_outcomes)
        r_total = len(recent_outcomes)
        r_wr = r_wins / r_total * 100
        r_gp = sum(p for p in recent_pnls if p > 0)
        r_gl = abs(sum(p for p in recent_pnls if p < 0))
        r_pf = r_gp / r_gl if r_gl > 0 else float("inf")

        print(f"  WR={r_wr:.1f}% (vs {overall_wr:.1f}% overall), "
              f"PF={r_pf:.2f} (vs {overall_pf:.2f} overall)")

        if abs(r_wr - overall_wr) > 5:
            direction = "WORSE" if r_wr < overall_wr else "BETTER"
            print(f"  WARNING: Recent WR is {abs(r_wr - overall_wr):.1f}% {direction} "
                  f"than overall. Check for regime change.")

    # Confidence interval on overall WR
    print(f"\n--- Confidence Interval ---")
    wr_values = [float(o) for o in outcomes]
    n_bootstrap = 1000
    boot_wrs = []
    rng = np.random.RandomState(42)
    for _ in range(n_bootstrap):
        sample = rng.choice(wr_values, size=len(wr_values), replace=True)
        boot_wrs.append(float(np.mean(sample)) * 100)

    ci_low = np.percentile(boot_wrs, 2.5)
    ci_high = np.percentile(boot_wrs, 97.5)
    print(f"  WR 95% CI: [{ci_low:.1f}%, {ci_high:.1f}%]")
    print(f"  If recent WR falls outside this CI, performance has shifted significantly.")


if __name__ == "__main__":
    main()
