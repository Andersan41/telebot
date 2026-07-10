"""
tools/diagnose_zero_trades.py — Diagnose why ETH/TAO/HYPE produce 0 trades.

Usage:
    python -m tools.diagnose_zero_trades
"""
from __future__ import annotations
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
logger.disable("strategy.signal_engine")
logger.disable("indicators.engine")
logger.disable("strategy.pattern_engine")
logger.disable("risk.engine")
logger.disable("strategy.probability_engine")
logger.disable("strategy.trade_engine")

from data.exchange_client import exchange_client
from indicators.engine import IndicatorEngine
from market_structure.structure import analyze_structure, _classify_trend, _detect_trend_from_df
from liquidity.sweep import detect_sweeps
from liquidity.order_blocks import detect_order_blocks
from liquidity.fvg import detect_fvg
from liquidity.candle_quality import analyze_last_candle

SYMBOLS = ["BTC/USDT", "ETH/USDT", "TAO/USDT", "HYPE/USDT"]
TIMEFRAME = "4h"
DAYS = 120
WARMUP = 80


async def diagnose_symbol(symbol: str, candles: int):
    logger.info(f"\n{'='*60}")
    logger.info(f"  {symbol}")
    logger.info(f"{'='*60}")

    try:
        raw = await exchange_client.fetch_ohlcv_paginated(
            symbol, timeframe=TIMEFRAME, total_limit=candles, page_size=998,
        )
    except Exception as e:
        logger.error(f"  Fetch failed: {e}")
        return

    if raw is None or len(raw) < WARMUP + 20:
        logger.warning(f"  Not enough data: {len(raw) if raw is not None else 0}")
        return

    df = raw.copy()
    logger.info(f"  Candles: {len(df)}, range: {df.index[0]} → {df.index[-1]}")

    ind_engine = IndicatorEngine()
    trend_counts = {"bullish": 0, "bearish": 0, "ranging": 0}
    bos_counts = {"bullish": 0, "bearish": 0, "none": 0}
    sweep_counts = {"valid": 0, "invalid": 0, "none": 0}
    setup_counts = {"reversal": 0, "continuation": 0, "none": 0}
    rejection_counts = {}
    p_tp_values = []

    sample_window = 50
    scanned = 0

    for i in range(WARMUP, len(df)):
        window = df.iloc[:i + 1].copy()

        try:
            ind = ind_engine.calculate(window, symbol, TIMEFRAME)
        except Exception:
            continue

        if ind is None or ind.atr is None or ind.atr <= 0:
            continue

        # Structure analysis
        try:
            sweeps = detect_sweeps(window, lookback=50)
        except Exception:
            sweeps = []
        try:
            structure = analyze_structure(
                window, lookback=50, sweeps=sweeps,
                atr_value=ind.atr,
            )
        except Exception:
            structure = None

        if structure is None:
            continue

        scanned += 1

        # Track trend
        trend = structure.trend
        trend_counts[trend] = trend_counts.get(trend, 0) + 1

        # Track BOS
        if structure.last_bos is not None:
            bos_counts[structure.last_bos.type] = bos_counts.get(structure.last_bos.type, 0) + 1
        else:
            bos_counts["none"] += 1

        # Track sweeps
        valid_sw = [s for s in sweeps if s.is_valid] if sweeps else []
        if valid_sw:
            sweep_counts["valid"] += 1
        elif sweeps:
            sweep_counts["invalid"] += 1
        else:
            sweep_counts["none"] += 1

        # Track regime rejection
        if trend == "ranging":
            rejection_counts["ranging_market"] = rejection_counts.get("ranging_market", 0) + 1
        elif structure.last_bos is None:
            rejection_counts["no_BOS"] = rejection_counts.get("no_BOS", 0) + 1

        # Sample p_tp every 10 candles
        if scanned % 10 == 0 and trend != "ranging" and structure.last_bos is not None:
            try:
                from strategy.pattern_engine import pattern_engine
                from strategy.probability_engine import probability_engine
                from strategy.feature_builder import feature_builder

                order_blocks = detect_order_blocks(window, lookback=100)
                fvgs = detect_fvg(window, lookback=100)
                candle_quality = analyze_last_candle(window, atr_value=ind.atr)

                setup = pattern_engine.detect(
                    sweeps=sweeps, order_blocks=order_blocks,
                    structure=structure, fvgs=fvgs,
                    candle_quality=candle_quality,
                    current_price=float(ind.close), atr=ind.atr,
                )

                if setup.detected:
                    setup_counts[setup.setup_type] = setup_counts.get(setup.setup_type, 0) + 1
                else:
                    reason = setup.rejection_reason or "unknown"
                    rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            except Exception as e:
                rejection_counts[f"error: {e}"] = rejection_counts.get(f"error: {e}", 0) + 1

    logger.info(f"  Scanned candles: {scanned}")
    logger.info(f"\n  Trend distribution:")
    for t, c in sorted(trend_counts.items()):
        pct = c / scanned * 100 if scanned else 0
        logger.info(f"    {t:<12} {c:>5} ({pct:.1f}%)")

    logger.info(f"\n  BOS distribution:")
    for t, c in sorted(bos_counts.items()):
        pct = c / scanned * 100 if scanned else 0
        logger.info(f"    {t:<12} {c:>5} ({pct:.1f}%)")

    logger.info(f"\n  Sweep distribution:")
    for t, c in sorted(sweep_counts.items()):
        pct = c / scanned * 100 if scanned else 0
        logger.info(f"    {t:<12} {c:>5} ({pct:.1f}%)")

    logger.info(f"\n  Setup detection (sampled every 10 candles):")
    for t, c in sorted(setup_counts.items()):
        logger.info(f"    {t:<15} {c:>5}")

    logger.info(f"\n  Rejection reasons (sampled):")
    for reason, count in sorted(rejection_counts.items(), key=lambda x: -x[1]):
        logger.info(f"    {reason:<40} {count:>5}")


async def main():
    candles = DAYS * 24 + WARMUP + 50
    await exchange_client.connect()

    for symbol in SYMBOLS:
        await diagnose_symbol(symbol, candles)

    await exchange_client.close()


if __name__ == "__main__":
    asyncio.run(main())
