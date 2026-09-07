"""Analyze MSS failures across multiple symbols to check ATR scaling."""
import asyncio
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas_ta as ta
from data.exchange_client import exchange_client
from liquidity.sweep import detect_sweeps
from liquidity.order_blocks import detect_order_blocks
from liquidity.fvg import detect_fvg
from liquidity.candle_quality import analyze_last_candle
from market_structure.structure import analyze_structure


def calc_atr(df, period=14):
    if len(df) < period + 1:
        return None
    atr_series = ta.atr(df["high"], df["low"], df["close"], length=period)
    if atr_series is None or atr_series.empty:
        return None
    val = atr_series.iloc[-1]
    return float(val) if val == val else None


async def analyze(symbol: str, timeframe: str, candles: int = 500, exchange_client=None):
    await exchange_client.connect()
    try:
        df = await exchange_client.fetch_ohlcv_paginated(
            symbol, timeframe, total_limit=candles, page_size=998
        )
    finally:
        await exchange_client.close()

    total = 0
    choch_count = 0
    mss_count = 0
    displacements = []
    atr_pct_values = []

    lookback = min(80, len(df) - 1)

    for i in range(lookback, len(df)):
        window = df.iloc[: i + 1]
        current_price = float(df["close"].iloc[i])

        try:
            atr_val = calc_atr(window)
            if atr_val is None or atr_val <= 0:
                continue

            atr_pct = (atr_val / current_price) * 100

            sweeps = detect_sweeps(window, lookback=50)
            obs = detect_order_blocks(window, lookback=100)
            fvgs = detect_fvg(window, lookback=100)
            cq = analyze_last_candle(window)

            _disp_atr = 0.0
            if cq and hasattr(cq, 'body_atr_ratio'):
                _disp_atr = cq.body_atr_ratio if cq.body_atr_ratio else 0.0

            _reclaim = 0
            if sweeps:
                _valid_sw = [s for s in sweeps if s.is_valid]
                if _valid_sw:
                    _reclaim = _valid_sw[0].reclaim_candles

            structure = analyze_structure(
                window, lookback=50,
                sweeps=sweeps,
                displacement_atr=_disp_atr,
                reclaim_bars=_reclaim,
                atr_value=atr_val,
            )

            total += 1
            atr_pct_values.append(atr_pct)

            if structure.last_choch is not None:
                choch_count += 1
                if structure.last_mss is not None:
                    mss_count += 1
                else:
                    choch = structure.last_choch
                    displacements.append(choch.displacement_score)

        except Exception:
            pass

    avg_atr = sum(atr_pct_values) / len(atr_pct_values) if atr_pct_values else 0

    print(f"\n{'='*50}")
    print(f"{symbol}")
    print(f"{'='*50}")
    print(f"  Avg ATR%: {avg_atr:.2f}%")
    print(f"  CHoCHs: {choch_count}/{total} ({choch_count/total*100:.0f}%)")
    print(f"  MSS: {mss_count} ({mss_count/total*100:.0f}%)")
    print(f"  CHoCH without MSS: {len(displacements)}")

    if displacements:
        for thresh in [0.3, 0.5, 0.75, 1.0]:
            cnt = sum(1 for d in displacements if d < thresh)
            print(f"    disp < {thresh}: {cnt}/{len(displacements)} ({cnt/len(displacements)*100:.0f}%)")
        avg_d = sum(displacements) / len(displacements)
        print(f"    Avg displacement: {avg_d:.2f} ATR")


async def main():
    from data.exchange_client import exchange_client as ec

    symbols = [
        "BTC/USDT",   # large cap, low ATR%
        "ETH/USDT",   # large cap
        "SOL/USDT",   # mid cap, higher ATR%
        "DOGE/USDT",  # memecoin, high ATR%
        "ARB/USDT",   # L2, mid volatility
        "PEPE/USDT",  # micro cap, very high ATR%
    ]

    for sym in symbols:
        try:
            await analyze(sym, "1h", 500, ec)
        except Exception as e:
            print(f"\n{sym}: ERROR - {e}")


if __name__ == "__main__":
    asyncio.run(main())
