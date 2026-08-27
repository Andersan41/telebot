"""
backtest/run_breakout_gate_ab.py — A/B of the Breakout Quality HARD GATE on the bot's own
signal-search logic.

Runs the same per-candle ICT pipeline as `run_breakout_quality.run_symbol` (Pattern →
HTF-bias → TradePlan → SL/TP), collecting every Executed trade together with its Breakout
Quality verdict/score computed exactly as the live Phase 1.41 does. Then it simulates the
HARD GATE ON vs OFF on that identical signal set:

    gate OFF : take every signal that survived the base pipeline
    gate ON  : take signals where verdict != "fake" AND score >= min_score
               (the exact rule in scheduler/scanner.py Phase 1.41)

It reports, per combo and pooled, whether enabling the gate changes PnL / WR / PF / avg
trade on the bot's own signals. This answers: "would the Breakout Quality hard gate help
or hurt this bot?" — without literally running scan_symbol_v2 (which touches the live DB,
Telegram callbacks and cross-cycle state, so it is not back-testable verbatim).

Usage:
    python -m backtest.run_breakout_gate_ab --symbols BTC/USDT,ETH/USDT,SOL/USDT \
        --timeframes 1h,4h,1d --days 180 [--min-score 45]
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

for _m in ["strategy.signal_engine", "indicators.engine", "strategy.pattern_engine",
           "risk.engine", "strategy.probability_engine", "strategy.trade_engine"]:
    logger.disable(_m)

import numpy as np

from data.exchange_client import exchange_client
from backtest.run_breakout_quality import run_symbol, Trade

CANDLES_PER_TF = {"1h": 24, "4h": 6, "1d": 1}


def stats(trades: list[Trade]):
    if not trades:
        return dict(count=0, wr=0.0, pf=0.0, avg_pnl=0.0, total_pnl=0.0)
    pnls = [t.net_pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    wr = len(wins) / len(trades) * 100
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 and abs(sum(losses)) > 0 else float("inf")
    return dict(count=len(trades), wr=round(wr, 1), pf=round(pf, 2),
                avg_pnl=round(float(np.mean(pnls)), 3), total_pnl=round(float(sum(pnls)), 2))


def fmt(s):
    return (f"{s['count']:>4} | WR={s['wr']:>5.1f}% | PF={s['pf']:>6.2f} | "
            f"avg={s['avg_pnl']:>+6.2f}% | tot={s['total_pnl']:>+8.2f}%")


def partition(all_trades: list[Trade], min_score: float):
    base = [t for t in all_trades]  # everything that survived the pipeline
    gated = [t for t in all_trades if t.bq_verdict != "fake" and t.bq_score >= min_score]
    dropped = [t for t in all_trades if t.bq_verdict == "fake" or t.bq_score < min_score]
    return base, gated, dropped


async def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTC/USDT,ETH/USDT,SOL/USDT")
    ap.add_argument("--timeframes", default="1h,4h,1d")
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--min-score", type=float, default=45.0)
    args = ap.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]
    timeframes = [t.strip() for t in args.timeframes.split(",")]

    print("═══ A/B: Breakout Quality HARD GATE on bot pipeline signals ═══")
    print(f"Symbols: {symbols} | TF: {timeframes} | Days: {args.days} | min_score: {args.min_score}\n")

    await exchange_client.connect()

    all_trades: list[Trade] = []
    per_combo: dict[tuple[str, str], list[Trade]] = {}

    for sym in symbols:
        for tf in timeframes:
            candles = args.days * CANDLES_PER_TF.get(tf, 24) + 220
            res = await run_symbol(sym, tf, candles)
            per_combo[(sym, tf)] = res["trades"]
            all_trades.extend(res["trades"])
            await asyncio.sleep(2)

    print(f"\n═══ BASE PIPELINE SIGNALS (no BQ gate) ═══")
    for (sym, tf), trades in per_combo.items():
        print(f"  {sym:>10} {tf}: {fmt(stats(trades))}")

    print(f"\n═══ A/B: gate OFF (ALL) vs gate ON (verdict!=fake & score>=min) ═══")
    print(f"\n  ── GLOBAL (all combos pooled) ──")
    base, gated, dropped = partition(all_trades, args.min_score)
    sb, sg, sd = stats(base), stats(gated), stats(dropped)
    print(f"  BASELINE (gate OFF) : {fmt(sb)}")
    print(f"  GATE ON (min={args.min_score:g}) : {fmt(sg)}")
    print(f"  BLOCKED by gate     : {fmt(sd)}")
    print(f"\n  ── PER COMBO ──")
    hdr = (f"{'Combo':<20} {'mode':<7} {'N':>4} {'WR%':>6} {'PF':>6} "
           f"{'AvgPnL%':>8} {'TotPnL%':>9}  Δtot")
    print(hdr)
    print("-" * len(hdr))
    for (sym, tf), trades in per_combo.items():
        _b, _g, _d = partition(trades, args.min_score)
        gb, gg = stats(_b), stats(_g)
        delta = (gg["total_pnl"] or 0.0) - (gb["total_pnl"] or 0.0)
        print(f"{sym+' '+tf:<20} {'off':<7} {fmt(gb)}")
        print(f"{'':<20} {'on ':<7} {fmt(gg)}   {delta:+.2f}pp")

    # how many "fake" ever appear in reality?
    fake_cnt = sum(1 for t in all_trades if t.bq_verdict == "fake")
    print(f"\n  (fake-verdict signals in sample: {fake_cnt})")

    await exchange_client.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())