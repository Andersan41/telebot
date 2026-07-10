"""
tools/experiment_mss.py — Run MSS parameter sweep experiments.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from data.exchange_client import exchange_client
from market_structure.diagnostic import diagnose_mss_funnel_full
import pandas_ta as ta


async def main():
    await exchange_client.connect()

    for symbol in ["BTC/USDT", "SOL/USDT"]:
        df = await exchange_client.fetch_ohlcv(symbol, "4h", limit=500)
        df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)
        atr_value = float(df["atr"].iloc[-1])

        print()
        print("=" * 60)
        print(symbol + " 4h  ATR=" + f"{atr_value:.2f}")
        print("=" * 60)

        # Test sweep windows
        print()
        print("--- SWEEP WINDOW TEST (disp >= 1.0, reclaim <= 2) ---")
        header = f"{'Window':>8} {'CHoCH':>6} {'w/sweep':>8} {'w/disp':>8} {'w/reclaim':>10} {'MSS':>6}"
        print(header)
        for window in [5, 10, 15]:
            stats = diagnose_mss_funnel_full(df, atr_value, lookback=400, max_causal_bars=window)
            row = f"{window:>8} {stats.choch_detected:>6} {stats.choch_with_sweep_in_window:>8} {stats.displacement_pass:>8} {stats.reclaim_pass:>10} {stats.mss_final:>6}"
            print(row)

        # Test displacement thresholds
        print()
        print("--- DISPLACEMENT THRESHOLD TEST (window=10, reclaim <= 2) ---")
        header = f"{'Thresh':>8} {'CHoCH':>6} {'w/sweep':>8} {'w/disp':>8} {'w/reclaim':>10} {'MSS':>6}"
        print(header)
        for thresh in [1.0, 0.9, 0.8, 0.7]:
            stats = diagnose_mss_funnel_full(df, atr_value, lookback=400, max_causal_bars=10)
            # Recount with custom threshold
            disp_count = sum(1 for d in stats.choch_details if d["displacement_atr"] >= thresh)
            mss_count = sum(
                1 for d in stats.choch_details
                if d["has_sweep"] and d["displacement_atr"] >= thresh and d["reclaim_bars"] <= 2
            )
            row = f"{thresh:>8.1f} {stats.choch_detected:>6} {stats.choch_with_sweep_in_window:>8} {disp_count:>8} {stats.reclaim_pass:>10} {mss_count:>6}"
            print(row)

        # Show near-misses
        print()
        print("--- NEAR MISSES (sweep=True, disp > 0.7) ---")
        stats = diagnose_mss_funnel_full(df, atr_value, lookback=400, max_causal_bars=10)
        near = [d for d in stats.choch_details if d["has_sweep"] and d["displacement_atr"] > 0.7]
        for d in near:
            print(f"  {d['type']:8s} idx={d['candle_index']:4d} bars={d['bars_since_sweep']:2d} disp={d['displacement_atr']:.3f} reclaim={d['reclaim_bars']}")


if __name__ == "__main__":
    asyncio.run(main())
