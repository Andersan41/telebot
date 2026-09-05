"""Quick Pattern Engine rejection rate measurement on historical data."""
import asyncio
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.exchange_client import exchange_client
from strategy.pattern_engine import pattern_engine
from liquidity.sweep import detect_sweeps
from liquidity.order_blocks import detect_order_blocks
from liquidity.fvg import detect_fvg
from liquidity.candle_quality import analyze_last_candle
from market_structure.structure import analyze_structure


async def measure(symbol: str, timeframe: str, candles: int = 500):
    await exchange_client.connect()
    try:
        df = await exchange_client.fetch_ohlcv_paginated(
            symbol, timeframe, total_limit=candles, page_size=998
        )
    finally:
        await exchange_client.close()

    import pandas_ta as ta
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)

    rejections = Counter()
    total = 0
    lookback = min(80, len(df) - 1)

    # Tracking detected signal characteristics
    detected_count = 0
    has_displacement_count = 0
    has_ob_count = 0
    has_fvg_count = 0
    has_bos_count = 0
    has_sweep_count = 0
    has_mss_count = 0
    reversal_count = 0
    continuation_count = 0
    confirmation_rej = 0

    for i in range(lookback, len(df)):
        window = df.iloc[: i + 1]
        current_price = float(df["close"].iloc[i])
        atr_val = float(df["atr"].iloc[i]) if not (df["atr"].iloc[i] is None or str(df["atr"].iloc[i]) == "nan") else 0.0

        try:
            sweeps = detect_sweeps(window, lookback=50)
            obs = detect_order_blocks(window, lookback=100)
            fvgs = detect_fvg(window, lookback=100)
            cq = analyze_last_candle(window, atr_value=atr_val if atr_val > 0 else None)
            structure = analyze_structure(window, lookback=50, sweeps=sweeps, atr_value=atr_val)

            setup = pattern_engine.detect(
                sweeps=sweeps,
                order_blocks=obs,
                structure=structure,
                fvgs=fvgs,
                candle_quality=cq,
                current_price=current_price,
                atr=atr_val,
            )

            total += 1
            if not setup.detected:
                rejections[setup.rejection_reason or "unknown"] += 1
            else:
                detected_count += 1
                has_displacement_count += 1 if setup.has_displacement else 0
                has_ob_count += 1 if setup.has_ob else 0
                has_fvg_count += 1 if setup.has_fvg else 0
                has_bos_count += 1 if setup.has_bos else 0
                has_sweep_count += 1 if setup.has_sweep else 0
                has_mss_count += 1 if setup.has_mss else 0
                if setup.setup_type == "reversal":
                    reversal_count += 1
                elif setup.setup_type == "continuation":
                    continuation_count += 1
                if setup.confirmation_score < 2:
                    confirmation_rej += 1
        except Exception as e:
            rejections[f"error: {e}"] += 1
            total += 1

    detected = total - sum(rejections.values())
    print(f"\n{'='*60}")
    print(f"{symbol} {timeframe} | {total} bars | lookback={lookback}")
    print(f"{'='*60}")
    print(f"  DETECTED: {detected} ({detected/total*100:.1f}%)")
    print(f"  REJECTED: {sum(rejections.values())} ({sum(rejections.values())/total*100:.1f}%)")
    print(f"\n  Rejection breakdown:")
    for reason, count in rejections.most_common():
        pct = count / total * 100
        print(f"    {count:>4} ({pct:>5.1f}%)  {reason}")

    if detected_count > 0:
        print(f"\n  Detected signal characteristics:")
        print(f"    has_displacement: {has_displacement_count}/{detected_count} ({has_displacement_count/detected_count*100:.1f}%)")
        print(f"    has_ob:          {has_ob_count}/{detected_count} ({has_ob_count/detected_count*100:.1f}%)")
        print(f"    has_fvg:         {has_fvg_count}/{detected_count} ({has_fvg_count/detected_count*100:.1f}%)")
        print(f"    has_bos:         {has_bos_count}/{detected_count} ({has_bos_count/detected_count*100:.1f}%)")
        print(f"    has_sweep:       {has_sweep_count}/{detected_count} ({has_sweep_count/detected_count*100:.1f}%)")
        print(f"    has_mss:         {has_mss_count}/{detected_count} ({has_mss_count/detected_count*100:.1f}%)")
        print(f"    reversal:        {reversal_count}/{detected_count} ({reversal_count/detected_count*100:.1f}%)")
        print(f"    continuation:    {continuation_count}/{detected_count} ({continuation_count/detected_count*100:.1f}%)")
        print(f"    conf_score < 2:  {confirmation_rej}/{detected_count} ({confirmation_rej/detected_count*100:.1f}%)")
    print()


async def main():
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT"]
    timeframe = "1h"
    candles = 500

    for sym in symbols:
        await measure(sym, timeframe, candles)


if __name__ == "__main__":
    asyncio.run(main())
