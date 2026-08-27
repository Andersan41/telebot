"""
backtest/run_breakout_quality.py — New ICT pipeline backtest collecting Breakout Quality verdicts.

Runs the real scan pipeline per candle (Pattern → HTF → TradePlan → Probability → Risk),
records each executed trade's Breakout Quality verdict/score, and reports stats broken
down by verdict so we can see whether the AMD-sweep classifier separates winners/losers.

Usage:
    python -m backtest.run_breakout_quality --symbols BTC/USDT,ETH/USDT,SOL/USDT \\
        --timeframes 1h,4h,1d --days 180
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

for _m in ["strategy.signal_engine", "indicators.engine", "strategy.pattern_engine",
           "risk.engine", "strategy.probability_engine", "strategy.trade_engine"]:
    logger.disable(_m)

import numpy as np
import pandas as pd

from data.exchange_client import exchange_client
from indicators.engine import IndicatorEngine, IndicatorValues
from strategy.pattern_engine import pattern_engine
from liquidity.sweep import detect_sweeps
from liquidity.order_blocks import detect_order_blocks
from liquidity.fvg import detect_fvg
from liquidity.candle_quality import analyze_last_candle
from liquidity.breakout_quality import classify_breakout
from market_structure.structure import analyze_structure, calc_premium_discount_score
from market_structure.htf_bias import get_htf_bias, HTFBias, extract_structure_dict
from config.settings import config

COMMISSION_PCT = 0.06
SLIPPAGE_PCT = 0.02
MAX_TRADE_DURATION_BARS = 96
CANDLES_PER_TF = {"1h": 24, "4h": 6, "1d": 1}


@dataclass
class Trade:
    symbol: str
    timeframe: str
    direction: str
    entry_price: float
    entry_index: int
    entry_timestamp: str
    sl: float
    tp: float
    exit_price: float = 0.0
    exit_index: int = 0
    exit_reason: str = ""
    pnl_pct: float = 0.0
    net_pnl_pct: float = 0.0
    setup_type: str = ""
    regime: str = ""
    # breakout quality
    bq_verdict: str = "n/a"
    bq_score: float = 0.0
    bq_body_pct: float = 0.0
    bq_retention: int = 0
    bq_vol_ratio: float = 0.0


def simulate_trade(direction, entry_price, sl, tp, df, entry_idx, symbol, timeframe,
                   setup_type="", regime="", bq=None) -> Trade:
    trade = Trade(
        symbol=symbol, timeframe=timeframe, direction=direction,
        entry_price=entry_price, entry_index=entry_idx,
        entry_timestamp=str(df.index[entry_idx]), sl=sl, tp=tp,
        setup_type=setup_type, regime=regime,
    )
    if bq is not None:
        trade.bq_verdict = bq.verdict
        trade.bq_score = bq.score
        trade.bq_body_pct = bq.body_pct
        trade.bq_retention = bq.retention
        trade.bq_vol_ratio = bq.volume_ratio

    for i in range(entry_idx + 1, min(entry_idx + MAX_TRADE_DURATION_BARS + 1, len(df))):
        high, low = float(df["high"].iloc[i]), float(df["low"].iloc[i])
        if direction == "BUY":
            if low <= sl:
                trade.exit_price, trade.exit_index, trade.exit_reason = sl, i, "sl"
                break
            elif high >= tp:
                trade.exit_price, trade.exit_index, trade.exit_reason = tp, i, "tp"
                break
        else:
            if high >= sl:
                trade.exit_price, trade.exit_index, trade.exit_reason = sl, i, "sl"
                break
            elif low <= tp:
                trade.exit_price, trade.exit_index, trade.exit_reason = tp, i, "tp"
                break

    if not trade.exit_price:
        last_idx = min(entry_idx + MAX_TRADE_DURATION_BARS, len(df) - 1)
        trade.exit_price = float(df["close"].iloc[last_idx])
        trade.exit_index, trade.exit_reason = last_idx, "timeout"

    if direction == "BUY":
        trade.pnl_pct = (trade.exit_price / entry_price - 1) * 100
    else:
        trade.pnl_pct = (1 - trade.exit_price / entry_price) * 100
    trade.net_pnl_pct = trade.pnl_pct - (COMMISSION_PCT * 2 + SLIPPAGE_PCT * 2)
    return trade


async def run_symbol(symbol, timeframe, candles):
    result = {"symbol": symbol, "timeframe": timeframe, "trades": [], "rejections": {}}
    raw = None
    for attempt in range(3):
        try:
            raw = await exchange_client.fetch_ohlcv_paginated(symbol, timeframe,
                                                              total_limit=candles, page_size=998)
            break
        except Exception as e:
            logger.warning(f"  fetch attempt {attempt+1}/3 failed {symbol}: {e}")
            if attempt < 2:
                await asyncio.sleep(5 * (attempt + 1))
    if raw is None or len(raw) < 120:
        logger.warning(f"Not enough data {symbol} {timeframe}: {len(raw) if raw is not None else 0}")
        return result

    df = raw.copy()

    # pre-fetch HTF for HTF gate
    htf_data = {}
    for htf in ["1w", "1d", "4h"]:
        try:
            htf_df = await exchange_client.fetch_ohlcv(symbol, htf, limit=50)
            if htf_df is not None and len(htf_df) >= 20:
                htf_data[htf] = htf_df
        except Exception:
            pass

    ind_engine = IndicatorEngine()
    cooldown = 0
    warmup = 80

    for i in range(warmup, len(df)):
        if cooldown > 0:
            cooldown -= 1
            continue
        window = df.iloc[: i + 1].copy()

        try:
            ind = ind_engine.calculate(window, symbol, timeframe)
        except Exception:
            continue
        if ind is None or not ind.atr or ind.atr <= 0:
            continue

        current_price = float(ind.close)

        try:
            sweeps = detect_sweeps(window, lookback=50)
        except Exception:
            sweeps = []
        try:
            order_blocks = detect_order_blocks(window, lookback=100)
        except Exception:
            order_blocks = []
        try:
            fvgs = detect_fvg(window, lookback=100)
        except Exception:
            fvgs = []
        try:
            candle_quality = analyze_last_candle(window, atr_value=ind.atr)
        except Exception:
            candle_quality = None

        _disp_atr = 0.0
        _reclaim = 0
        if candle_quality and ind.atr and ind.atr > 0:
            _disp_atr = getattr(candle_quality, 'body_atr_ratio', 0.0) or 0.0
        valid_sw = [s for s in sweeps if s.is_valid] if sweeps else []
        if valid_sw:
            _reclaim = valid_sw[0].reclaim_candles
        try:
            structure = analyze_structure(window, lookback=50, sweeps=sweeps,
                                          displacement_atr=_disp_atr, reclaim_bars=_reclaim,
                                          atr_value=ind.atr if ind.atr else 0.0)
        except Exception:
            structure = None

        setup = pattern_engine.detect(sweeps=sweeps, order_blocks=order_blocks,
                                      structure=structure, fvgs=fvgs, candle_quality=candle_quality,
                                      current_price=current_price, atr=ind.atr)
        if not setup.detected:
            continue

        # ── HTF bias gate (mimic scanner) ──
        try:
            _struct_1d = extract_structure_dict(structure) if structure else None
            htf_bias = get_htf_bias(df_1d=htf_data.get("1d"), df_4h=htf_data.get("4h"),
                                    structure_1d=_struct_1d, structure_4h=None)
            if htf_bias != HTFBias.NEUTRAL:
                dm = {"buy": HTFBias.BULLISH, "sell": HTFBias.BEARISH}
                if dm.get(setup.direction) != htf_bias:
                    result["rejections"]["htf_bias"] = result["rejections"].get("htf_bias", 0) + 1
                    continue
        except Exception:
            pass

        # ── Trade plan ──
        try:
            from strategy.trade_engine import trade_engine
            plan = trade_engine.build_trade_plan(ind=ind, direction=setup.direction,
                                                 structure=structure, order_blocks=order_blocks,
                                                 sweeps=sweeps, fvgs=fvgs, df=window,
                                                 timeframe=timeframe)
            sl, tp = plan.sl, plan.tp
        except Exception:
            result["rejections"]["trade_plan"] = result["rejections"].get("trade_plan", 0) + 1
            continue
        if sl is None or tp is None:
            result["rejections"]["sl_tp"] = result["rejections"].get("sl_tp", 0) + 1
            continue

        # ── Breakout Quality: compile a verdict against the settled window ──
        bq = None
        if config.breakout_quality_enabled:
            try:
                bq = classify_breakout(window, setup.direction,
                                       atr=ind.atr if ind.atr else 0.0,
                                       oi_change_pct=None,
                                       lookback=config.breakout_quality_lookback)
            except Exception:
                bq = None

        trade = simulate_trade(direction=setup.direction.upper(), entry_price=current_price,
                               sl=sl, tp=tp, df=df, entry_idx=i, symbol=symbol, timeframe=timeframe,
                               setup_type=setup.setup_type or "unknown",
                               regime=structure.trend if structure else "unknown", bq=bq)
        result["trades"].append(trade)
        cooldown = 3

    return result


def _grp(trades):
    if not trades:
        return dict(count=0, wr=0.0, pf=0.0, avg_pnl=0.0, total_pnl=0.0, avg_dur=0.0)
    pnls = [t.net_pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    wr = len(wins) / len(trades) * 100
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else float("inf")
    return dict(count=len(trades), wr=round(wr, 1), pf=round(pf, 2),
                avg_pnl=round(float(np.mean(pnls)), 3), total_pnl=round(float(sum(pnls)), 2),
                avg_dur=round(float(np.mean([t.exit_index - t.entry_index for t in trades])), 1))


async def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTC/USDT,ETH/USDT,SOL/USDT")
    ap.add_argument("--timeframes", default="1h,4h,1d")
    ap.add_argument("--days", type=int, default=180)
    args = ap.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]
    timeframes = [t.strip() for t in args.timeframes.split(",")]

    logger.info("═══ Backtest: new pipeline + Breakout Quality ═══")
    logger.info(f"Symbols: {symbols} | Timeframes: {timeframes} | Days: {args.days}\n")

    await exchange_client.connect()

    all_trades = []
    combos = []
    for sym in symbols:
        for tf in timeframes:
            candles = args.days * CANDLES_PER_TF.get(tf, 24) + 100 + 120
            logger.info(f"── {sym} {tf} (~{candles} candles) ──")
            t0 = time.time()
            res = await run_symbol(sym, tf, candles)
            el = time.time() - t0
            g = _grp(res["trades"])
            combos.append((f"{sym} {tf}", g))
            all_trades.extend(res["trades"])
            logger.info(f"    {len(res['trades'])} trades | WR={g['wr']}% PF={g['pf']} "
                        f"PnL={g['total_pnl']:+.2f}% ({el:.0f}s)")
            await asyncio.sleep(2)

    logger.info("\n═══ PER-COMBO ═══")
    hdr = f"{'Combo':<22} {'N':>4} {'WR%':>6} {'PF':>6} {'AvgPnL%':>8} {'TotPnL%':>8} {'Dur':>5}"
    logger.info(hdr)
    logger.info("-" * len(hdr))
    for name, g in combos:
        logger.info(f"{name:<22} {g['count']:>4} {g['wr']:>5.1f}% {g['pf']:>6.2f} "
                    f"{g['avg_pnl']:>+7.2f}% {g['total_pnl']:>+8.2f}% {g['avg_dur']:>5}")

    logger.info("\n  ═══ BREAKOUT QUALITY VERDICT BREAKDOWN (all combos) ═══")
    for verdict in ["real", "ambiguous", "fake", "n/a"]:
        trades = [t for t in all_trades if t.bq_verdict == verdict]
        g = _grp(trades)
        logger.info(f"  {verdict:<10} {g['count']:>4} trades | WR={g['wr']:>5.1f}% PF={g['pf']:>6.2f} "
                    f"PnL={g['total_pnl']:>+8.2f}% avg={g['avg_pnl']:>+7.2f}%")

    # score buckets
    logger.info("\n  ═══ BREAKOUT QUALITY SCORE BUCKETS ═══")
    for lo, hi, label in [(0, 25, "0-25 (weak)"), (25, 45, "25-45"), (45, 55, "45-55"), (55, 100, "55+ (real)")]:
        trades = [t for t in all_trades if lo <= t.bq_score < hi]
        g = _grp(trades)
        logger.info(f"  score {label:<12} {g['count']:>4} trades | WR={g['wr']:>5.1f}% PF={g['pf']:>6.2f} "
                    f"PnL={g['total_pnl']:>+8.2f}%")

    # per setup type × verdict
    logger.info("\n  ═══ SETUP TYPE × VERDICT ═══")
    for stype in ["reversal", "continuation"]:
        for verdict in ["real", "ambiguous", "fake"]:
            trades = [t for t in all_trades if t.setup_type == stype and t.bq_verdict == verdict]
            g = _grp(trades)
            logger.info(f"  {stype:<12} {verdict:<10} {g['count']:>4} trades | WR={g['wr']:>5.1f}% "
                        f"PF={g['pf']:>6.2f} PnL={g['total_pnl']:>+8.2f}%")

    # Hard-gate simulation: what would filtering out fake/weak do?
    logger.info("\n  ═══ GATE SIMULATION (block fake + score<min) ═══")
    for min_score in [0, 25, 45, 55]:
        allowed = [t for t in all_trades if t.bq_verdict != "fake" and t.bq_score >= min_score]
        g = _grp(allowed)
        logger.info(f"  allow score>={min_score:>3} & !fake : {g['count']:>4} trades | "
                    f"WR={g['wr']:>5.1f}% PF={g['pf']:>6.2f} PnL={g['total_pnl']:>+8.2f}%")

    await exchange_client.close()
    logger.info("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())