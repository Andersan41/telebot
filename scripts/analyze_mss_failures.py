"""Analyze MSS failures with CORRECT ATR (like scanner does)."""
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
from market_structure.structure import analyze_structure, classify_choch


def calc_atr(df, period=14):
    """Calculate ATR like the indicators engine."""
    if len(df) < period + 1:
        return None
    atr_series = ta.atr(df["high"], df["low"], df["close"], length=period)
    if atr_series is None or atr_series.empty:
        return None
    val = atr_series.iloc[-1]
    return float(val) if val == val else None  # NaN check


async def analyze(symbol: str, timeframe: str, candles: int = 500):
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
    mss_fail_reasons = Counter()
    displacement_values = []

    lookback = min(80, len(df) - 1)

    for i in range(lookback, len(df)):
        window = df.iloc[: i + 1]
        current_price = float(df["close"].iloc[i])

        try:
            atr_val = calc_atr(window)
            if atr_val is None or atr_val <= 0:
                continue

            sweeps = detect_sweeps(window, lookback=50)
            obs = detect_order_blocks(window, lookback=100)
            fvgs = detect_fvg(window, lookback=100)
            cq = analyze_last_candle(window)

            # Calculate displacement like scanner does
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

            if structure.last_choch is not None:
                choch_count += 1

                if structure.last_mss is not None:
                    mss_count += 1
                else:
                    choch = structure.last_choch
                    reasons = []
                    if not choch.has_sweep_reference:
                        reasons.append("no_sweep_in_window")
                    if choch.displacement_score < 1.0:
                        reasons.append(f"displacement={choch.displacement_score:.2f}")
                        displacement_values.append(choch.displacement_score)
                    if choch.reclaim_bars > 2:
                        reasons.append(f"reclaim={choch.reclaim_bars}")
                    for r in reasons:
                        mss_fail_reasons[r] += 1

        except Exception:
            pass

    print(f"\n{'='*60}")
    print(f"{symbol} {timeframe} | {total} bars")
    print(f"{'='*60}")
    print(f"  CHoCHs found: {choch_count} ({choch_count/total*100:.1f}%)")
    print(f"  MSS classified: {mss_count} ({mss_count/total*100:.1f}%)")
    print(f"  CHoCH without MSS: {choch_count - mss_count}")
    print(f"\n  MSS failure reasons:")
    for reason, count in mss_fail_reasons.most_common():
        print(f"    {count:>4}  {reason}")

    if displacement_values:
        avg = sum(displacement_values) / len(displacement_values)
        print(f"\n  Displacement distribution (n={len(displacement_values)}):")
        for thresh in [0.3, 0.5, 0.75, 0.9, 1.0]:
            cnt = sum(1 for d in displacement_values if d < thresh)
            print(f"    < {thresh} ATR: {cnt} ({cnt/len(displacement_values)*100:.0f}%)")
        print(f"    Average: {avg:.2f} ATR")
    print()


async def main():
    for sym in ["BTC/USDT", "ETH/USDT"]:
        await analyze(sym, "1h", 500)


if __name__ == "__main__":
    asyncio.run(main())
