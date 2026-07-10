"""
tools/show_near_miss.py — Show candles around near-miss MSS events.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from data.exchange_client import exchange_client
import pandas_ta as ta


async def main():
    await exchange_client.connect()
    df = await exchange_client.fetch_ohlcv("BTC/USDT", "4h", limit=500)
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)

    print("BTC/USDT 4h - Candles around idx=154 (near-miss MSS)")
    print("CHoCH bearish at idx=154, sweep at idx=150 (bars_since=4)")
    print()
    print(" Idx       Open       High        Low      Close      ATR   Body/ATR")

    for i in range(145, 165):
        row = df.iloc[i]
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        atr = float(row["atr"]) if "atr" in df.columns else 0
        body = abs(c - o)
        disp = body / atr if atr > 0 else 0
        marker = ""
        if i == 154:
            marker = "  <-- CHoCH (disp=0.979)"
        elif i == 150:
            marker = "  <-- SWEEP"
        print(f"{i:>4} {o:>10.2f} {h:>10.2f} {l:>10.2f} {c:>10.2f} {atr:>8.2f} {disp:>10.3f}{marker}")


if __name__ == "__main__":
    asyncio.run(main())
