"""
scripts/post_costs_analysis.py — Analyze edge after realistic costs.

The checklist says: "Add commission, slippage, funding. Recalculate expectancy
and PF after costs. Often this is the only thing needed to understand that
edge is imaginary."

Usage:
    python scripts/post_costs_analysis.py [--db data/signals.db]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np


def load_signals(db_path: str) -> list[dict]:
    """Load all resolved signals with PnL."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Check tables
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]

    signals = []
    if "signal_outcomes" in tables:
        rows = conn.execute("""
            SELECT s.symbol, s.signal_type, s.close_price, s.sl, s.tp,
                   s.created_at, o.close_price as exit_price, o.pnl_pct,
                   o.status, o.closed_at
            FROM signal_outcomes o
            JOIN signals s ON o.signal_id = s.id
            WHERE o.status IN ('HIT_TP', 'HIT_SL')
            ORDER BY s.created_at ASC
        """).fetchall()
        signals = [dict(r) for r in rows]

    conn.close()
    return signals


def compute_costs(
    entry_price: float,
    exit_price: float,
    signal_type: str,
    fee_pct: float = 0.05,
    slippage_pct: float = 0.05,
    funding_rate_8h: float = 0.0001,
    hold_hours: float = 8.0,
    is_perp: bool = True,
) -> dict:
    """Compute all costs for a round trip."""
    # Gross PnL
    if signal_type == "BUY":
        gross_pnl = (exit_price - entry_price) / entry_price * 100
    else:
        gross_pnl = (entry_price - exit_price) / entry_price * 100

    # Commission (both sides)
    commission = fee_pct * 2

    # Slippage (both sides)
    slippage = slippage_pct * 2

    # Funding (perpetuals only)
    funding = 0.0
    if is_perp:
        n_periods = hold_hours / 8.0
        funding = n_periods * funding_rate_8h * 100

    total_cost = commission + slippage + funding
    net_pnl = gross_pnl - total_cost

    return {
        "gross_pnl": gross_pnl,
        "commission": commission,
        "slippage": slippage,
        "funding": funding,
        "total_cost": total_cost,
        "net_pnl": net_pnl,
    }


def main():
    parser = argparse.ArgumentParser(description="Post-costs edge analysis")
    parser.add_argument("--db", default="data/signals.db")
    parser.add_argument("--fee-pct", type=float, default=0.05, help="Fee per side (%)")
    parser.add_argument("--slippage-pct", type=float, default=0.05, help="Slippage per side (%)")
    parser.add_argument("--funding-8h", type=float, default=0.0001, help="Funding rate per 8h")
    parser.add_argument("--hold-hours", type=float, default=8.0, help="Average hold time (hours)")
    parser.add_argument("--perp", action="store_true", default=True, help="Perpetual futures")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    signals = load_signals(args.db)
    if not signals:
        print("No resolved signals found.")
        sys.exit(1)

    print(f"Loaded {len(signals)} resolved signals\n")

    # Compute costs for each signal
    results = []
    for s in signals:
        if s["exit_price"] is None or s["close_price"] is None:
            continue
        costs = compute_costs(
            s["close_price"], s["exit_price"], s["signal_type"],
            fee_pct=args.fee_pct, slippage_pct=args.slippage_pct,
            funding_rate_8h=args.funding_8h, hold_hours=args.hold_hours,
            is_perp=args.perp,
        )
        results.append({**s, **costs})

    if not results:
        print("No valid signals with exit prices.")
        sys.exit(1)

    # Aggregate
    gross_pnls = [r["gross_pnl"] for r in results]
    net_pnls = [r["net_pnl"] for r in results]
    total_costs = [r["total_cost"] for r in results]

    wins_gross = sum(1 for p in gross_pnls if p > 0)
    losses_gross = sum(1 for p in gross_pnls if p < 0)
    wins_net = sum(1 for p in net_pnls if p > 0)
    losses_net = sum(1 for p in net_pnls if p < 0)

    gross_profit = sum(p for p in gross_pnls if p > 0)
    gross_loss = abs(sum(p for p in gross_pnls if p < 0))
    gross_pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    net_profit = sum(p for p in net_pnls if p > 0)
    net_loss = abs(sum(p for p in net_pnls if p < 0))
    net_pf = net_profit / net_loss if net_loss > 0 else float("inf")

    print("=" * 70)
    print("POST-COSTS EDGE ANALYSIS")
    print("=" * 70)

    print(f"\n  Costs applied:")
    print(f"    Commission:  {args.fee_pct}% per side ({args.fee_pct * 2}% round-trip)")
    print(f"    Slippage:    {args.slippage_pct}% per side ({args.slippage_pct * 2}% round-trip)")
    if args.perp:
        print(f"    Funding:     {args.funding_8h * 100:.4f}% per 8h (~{args.hold_hours:.0f}h hold)")
    print(f"    Total cost:  ~{np.mean(total_costs):.2f}% per trade")

    print(f"\n{'Metric':<25} {'GROSS':>15} {'NET (after costs)':>18}")
    print("-" * 60)
    print(f"{'Total signals':<25} {len(results):>15} {len(results):>18}")
    print(f"{'Wins':<25} {wins_gross:>15} {wins_net:>18}")
    print(f"{'Losses':<25} {losses_gross:>15} {losses_net:>18}")
    print(f"{'Win rate':<25} {wins_gross/len(results)*100:>14.1f}% {wins_net/len(results)*100:>17.1f}%")
    print(f"{'Profit factor':<25} {gross_pf:>15.2f} {net_pf:>18.2f}")
    print(f"{'Total PnL':<25} {sum(gross_pnls):>+14.2f}% {sum(net_pnls):>+17.2f}%")
    print(f"{'Avg PnL per trade':<25} {np.mean(gross_pnls):>+14.3f}% {np.mean(net_pnls):>+17.3f}%")
    print(f"{'Avg cost per trade':<25} {'':>15} {np.mean(total_costs):>17.3f}%")

    # Edge assessment
    print("\n" + "=" * 70)
    print("EDGE ASSESSMENT")
    print("=" * 70)

    if net_pf >= 1.5 and wins_net > losses_net:
        print("\n  [EDGE CONFIRMED] Strategy is profitable after costs.")
        print(f"  Net PF = {net_pf:.2f}, Net WR = {wins_net/len(results)*100:.1f}%")
    elif net_pf >= 1.0:
        print("\n  [MARGINAL] Strategy barely breaks even after costs.")
        print(f"  Net PF = {net_pf:.2f}. Edge is thin — may vanish with regime change.")
    else:
        print("\n  [NO EDGE] Strategy loses money after costs.")
        print(f"  Net PF = {net_pf:.2f}. The apparent edge was entirely cost-driven.")

    # Cost breakdown
    avg_commission = np.mean([r["commission"] for r in results])
    avg_slippage = np.mean([r["slippage"] for r in results])
    avg_funding = np.mean([r["funding"] for r in results])
    print(f"\n  Average cost breakdown per trade:")
    print(f"    Commission:  {avg_commission:.3f}%")
    print(f"    Slippage:    {avg_slippage:.3f}%")
    print(f"    Funding:     {avg_funding:.3f}%")

    # Breakeven analysis
    if gross_pf > 1.0:
        # How much cost can we tolerate?
        max_cost = np.mean(gross_pnls) - np.mean([p for p in gross_pnls if p < 0]) * -1
        print(f"\n  Breakeven: strategy can tolerate ~{np.mean(total_costs) + (gross_pf - 1) * 0.5:.3f}% "
              f"additional cost before edge disappears")


if __name__ == "__main__":
    main()
