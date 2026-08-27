"""
backtest/run_breakout_event.py — Breakout-event backtest.

Detects genuine RANGE-BREAK events: a candle whose CLOSE pierces beyond the settled
range boundary in a direction. For each event it computes the Breakout Quality verdict
exactly as the live pipeline does (close beyond boundary + retention + displacement +
volume, vs settled range), then measures the FORWARD outcome.

This isolates the classifier's actual job — distinguishing a real breakout (price
continues) from an AMD fake-break (price reverts) — which the per-trade pipeline backtest
couldn't show (entries there are pullbacks, not breaks).

Forward outcome metrics (after the event at index i):
  - fwd_N  : aligned close-to-close return over the forward window (continues or reverts)
  - mfe    : max favorable excursion in the breakout direction (in the traded direction)
  - mae    : max adverse excursion in the opposite direction
  - sustained: retreat started below/above, i.e. reversed (non-)event for "real"/"fake"

Usage:
    python -m backtest.run_breakout_event --symbols BTC/USDT,ETH/USDT,SOL/USDT \\
        --timeframes 1h,4h,1d --days 180 --horizon 24
"""
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from data.exchange_client import exchange_client
from config.settings import config

CANDLES_PER_TF = {"1h": 24, "4h": 6, "1d": 1}
HORIZON = 12  # bars to look ahead (override via --horizon)


@dataclass
class BreakEvent:
    symbol: str
    timeframe: str
    idx: int
    direction: str
    boundary: float
    entry: float
    # breakout-quality verdict
    verdict: str
    score: float
    body_pct: float
    retention: int
    vol_ratio: float
    # forward outcome
    fwd_close: float = 0.0
    fwd_return_pct: float = 0.0
    mfe_pct: float = 0.0
    mae_pct: float = 0.0
    sustained: bool = False  # close stayed favourable at horizon


async def run_symbol(symbol: str, timeframe: str, candles: int) -> list[BreakEvent]:
    raw = None
    for attempt in range(3):
        try:
            raw = await exchange_client.fetch_ohlcv_paginated(symbol, timeframe,
                                                              total_limit=candles, page_size=998)
            break
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(5 * (attempt + 1))
    if raw is None or len(raw) < 120:
        return []

    df = raw.copy()
    high_arr = df["high"].to_numpy()
    low_arr = df["low"].to_numpy()
    close_arr = df["close"].to_numpy()
    vol_arr = df["volume"].to_numpy()
    n = len(df)

    events: list[BreakEvent] = []
    lookback = 40

    for i in range(lookback, n - 1):
        # settled range: max high / min low of the 40 bars BEFORE the event
        wh = high_arr[max(0, i - lookback):i]
        wl = low_arr[max(0, i - lookback):i]
        bh = float(wh.max())
        bl = float(wl.min())
        close = close_arr[i]

        buy = close > bh and bh > 0
        sell = close < bl and bl > 0
        if not (buy or sell):
            continue
        direction = "buy" if buy else "sell"
        boundary = bh if buy else bl

        # compute the official classifier verdict on a window ending at i
        df_win = df.iloc[: i + 1]
        atr = _approx_atr(df_win)
        try:
            from liquidity.breakout_quality import classify_breakout
            bq = classify_breakout(df_win, direction, atr=atr, oi_change_pct=None,
                                   lookback=lookback)
        except Exception:
            bq = None

        # forward window
        fwd = min(i + HORIZON, n - 1)
        fwd_close = close_arr[fwd]
        if direction == "buy":
            fwd_return = (fwd_close / close - 1) * 100
            mfe = (high_arr[i + 1:fwd + 1].max() / close - 1) * 100
            mae = (low_arr[i + 1:fwd + 1].min() / close - 1) * 100
            survived = fwd_close > boundary
        else:
            fwd_return = (1 - fwd_close / close) * 100
            mfe = (1 - low_arr[i + 1:fwd + 1].min() / close) * 100
            mae = (1 - high_arr[i + 1:fwd + 1].max() / close) * 100
            survived = fwd_close < boundary

        events.append(BreakEvent(
            symbol=symbol, timeframe=timeframe, idx=i, direction=direction,
            boundary=boundary, entry=close,
            verdict=bq.verdict if bq else "n/a",
            score=bq.score if bq else 0.0,
            body_pct=bq.body_pct if bq else 0.0,
            retention=bq.retention if bq else 0,
            vol_ratio=bq.volume_ratio if bq else 0.0,
            fwd_close=float(fwd_close), fwd_return_pct=float(fwd_return),
            mfe_pct=float(mfe), mae_pct=float(mae), sustained=bool(survived),
        ))

    return events


def _approx_atr(df: pd.DataFrame) -> float:
    try:
        c = df["close"]
        h = df["high"].tail(15)
        l = df["low"].tail(15)
        prev = c.shift(1).tail(15)
        tr = pd.concat([(h - l).abs(), (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
        return float(tr.mean()) if len(tr) else 0.0
    except Exception:
        return 0.0


def _grp(events: list[BreakEvent]):
    if not events:
        return dict(count=0, wr=0.0, avg_fwd=0.0, median_fwd=0.0, mfe=0.0, mae=0.0, survived=0.0)
    fwd = [e.fwd_return_pct for e in events]
    wr = sum(1 for f in fwd if f > 0) / len(fwd) * 100
    return dict(
        count=len(events),
        wr=round(wr, 1),
        avg_fwd=round(float(np.mean(fwd)), 3),
        median_fwd=round(float(np.median(fwd)), 3),
        mfe=round(float(np.mean([e.mfe_pct for e in events])), 2),
        mae=round(float(np.mean([e.mae_pct for e in events])), 2),
        survived=round(sum(1 for e in events if e.sustained) / len(events) * 100, 1),
    )


async def main():
    import argparse
    global HORIZON
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTC/USDT,ETH/USDT,SOL/USDT")
    ap.add_argument("--timeframes", default="1h,4h,1d")
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--horizon", type=int, default=HORIZON)
    args = ap.parse_args()
    HORIZON = args.horizon

    symbols = [s.strip() for s in args.symbols.split(",")]
    timeframes = [t.strip() for t in args.timeframes.split(",")]

    print(f"═══ BREAKOUT-EVENT backtest ═══")
    print(f"Symbols: {symbols} | TF: {timeframes} | Days: {args.days} | Horizon: {HORIZON} bars\n")

    await exchange_client.connect()

    all_events: list[BreakEvent] = []
    per_combo: dict[tuple[str, str], list[BreakEvent]] = {}

    for sym in symbols:
        for tf in timeframes:
            candles = args.days * CANDLES_PER_TF.get(tf, 24) + 200
            evts = await run_symbol(sym, tf, candles)
            per_combo[(sym, tf)] = evts
            all_events.extend(evts)
            g = _grp(evts)
            print(f"  {sym:>10} {tf}: {g['count']:>4} events | WR={g['wr']:>5.1f}% "
                  f"avgFwd={g['avg_fwd']:>+6.2f}% medFwd={g['median_fwd']:>+6.2f}% "
                  f"mfe={g['mfe']:>5.2f}% mae={g['mae']:>6.2f}% survived={g['survived']:>4.1f}%")
            await asyncio.sleep(2)

    print(f"\n═══ PER-TIMEFRAME (all symbols pooled) ═══")
    for tf in timeframes:
        evts = [e for e in all_events if e.timeframe == tf]
        g = _grp(evts)
        print(f"  {tf:>4}: {g['count']:>5} events | WR={g['wr']:>5.1f}% avgFwd={g['avg_fwd']:>+7.2f}% "
              f"medFwd={g['median_fwd']:>+7.2f}% mfe={g['mfe']:>5.2f}% mae={g['mae']:>6.2f}% survived={g['survived']:>4.1f}%")

    print(f"\n═══ VERDICT DISCRIMINATION (the key question) ═══")
    expected = ["real", "ambiguous", "fake"]
    for verdict in expected:
        evts = [e for e in all_events if e.verdict == verdict]
        g = _grp(evts)
        print(f"  {verdict:<12} {g['count']:>5} events | WR={g['wr']:>5.1f}% avgFwd={g['avg_fwd']:>+7.2f}% "
              f"medFwd={g['median_fwd']:>+7.2f}% mfe={g['mfe']:>5.2f}% mae={g['mae']:>6.2f}% survived={g['survived']:>4.1f}%")

    print(f"\n═══ SCORE BUCKETS ═══")
    for lo, hi in [(0, 25), (25, 45), (45, 55), (55, 101)]:
        evts = [e for e in all_events if lo <= e.score < hi]
        g = _grp(evts)
        print(f"  score {lo:>2}-{hi:<3} {g['count']:>5} events | WR={g['wr']:>5.1f}% "
              f"avgFwd={g['avg_fwd']:>+7.2f}% medFwd={g['median_fwd']:>+7.2f}% survived={g['survived']:>4.1f}%")

    print(f"\n═══ BODY PORTION ═══")
    for lo, hi in [(0, 0.3), (0.3, 0.5), (0.5, 0.8), (0.8, 1.01)]:
        evts = [e for e in all_events if lo <= e.body_pct < hi]
        g = _grp(evts)
        print(f"  body {lo:<4}..{hi:<4} {g['count']:>5} events | WR={g['wr']:>5.1f}% "
              f"avgFwd={g['avg_fwd']:>+7.2f}% medFwd={g['median_fwd']:>+7.2f}% survived={g['survived']:>4.1f}%")

    # gate simulation: restrict to "real" verdicts
    print(f"\n═══ GATE SIMULATION (only real verdicts) ═══")
    for min_score in [0, 25, 45, 55]:
        evts = [e for e in all_events if e.verdict == "real" and e.score >= min_score]
        g = _grp(evts)
        print(f"  real & score>={min_score:>3} : {g['count']:>5} events | WR={g['wr']:>5.1f}% "
              f"avgFwd={g['avg_fwd']:>+7.2f}% medFwd={g['median_fwd']:>+7.2f}%")

    await exchange_client.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())