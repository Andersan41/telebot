"""
tools/diagnose_mss.py — Run MSS funnel diagnostics on live data.

Usage:
    python -m tools.diagnose_mss BTC/USDT 4h
    python -m tools.diagnose_mss SOL/USDT 1h --full
"""
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    if len(sys.argv) < 3:
        print("Usage: python -m tools.diagnose_mss <symbol> <timeframe> [--full]")
        print("Example: python -m tools.diagnose_mss BTC/USDT 4h")
        sys.exit(1)

    symbol = sys.argv[1]
    timeframe = sys.argv[2]
    full_mode = "--full" in sys.argv

    print(f"Running MSS diagnostics for {symbol} {timeframe}...")
    if full_mode:
        print("Mode: FULL (all structure breaks)")

    from data.exchange_client import exchange_client
    from indicators.engine import IndicatorEngine
    from market_structure.diagnostic import (
        diagnose_mss_funnel,
        diagnose_mss_funnel_full,
    )

    # Connect to exchange
    print("Connecting to exchange...")
    await exchange_client.connect()

    # Fetch data
    print("Fetching OHLCV data...")
    df = await exchange_client.fetch_ohlcv(symbol, timeframe, limit=500)
    if df is None or df.empty:
        print(f"ERROR: No data for {symbol} {timeframe}")
        sys.exit(1)

    print(f"Got {len(df)} candles ({df.index[0]} to {df.index[-1]})")

    # Calculate ATR
    import pandas_ta as ta
    atr_period = 14
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=atr_period)
    atr_value = float(df["atr"].iloc[-1]) if "atr" in df.columns else 0.0
    print(f"ATR({atr_period}) = {atr_value:.4f}")

    # Run diagnostics
    if full_mode:
        stats = diagnose_mss_funnel_full(
            df,
            atr_value=atr_value,
            lookback=400,
            swing_window=5,
            max_causal_bars=10,
        )
    else:
        from liquidity.sweep import detect_sweeps
        sweeps = detect_sweeps(df, lookback=400)
        stats = diagnose_mss_funnel(
            df,
            sweeps=sweeps,
            atr_value=atr_value,
            lookback=400,
            swing_window=5,
            max_causal_bars=10,
        )

    stats.print_summary()


if __name__ == "__main__":
    asyncio.run(main())
