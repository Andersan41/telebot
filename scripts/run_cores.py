"""
scripts/run_cores.py — Run ICT core pipeline on live market data.

Usage:
    python scripts/run_cores.py [--symbols BTC/USDT,ETH/USDT] [--timeframe 1h]
"""
from __future__ import annotations

import asyncio
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from config.settings import config, get_active_symbols
from scheduler.scanner import scan_symbol_v2


async def run_scan(symbols: list[str], timeframes: list[str]):
    """Run ICT core pipeline on the same data."""
    print("=" * 80)
    print("ICT Core Pipeline Scan")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"Symbols: {symbols}")
    print(f"Timeframes: {timeframes}")
    print("=" * 80)

    signals = []

    for symbol in symbols:
        for tf in timeframes:
            print(f"\n--- {symbol} {tf} ---")

            try:
                result = await scan_symbol_v2(
                    symbol, tf,
                    notify_callback=None,
                    blocked_callback=None,
                )
                if result is not None:
                    signals.append({
                        "symbol": symbol,
                        "timeframe": tf,
                        "type": result.signal.value,
                        "entry": result.close,
                        "sl": result.sl,
                        "tp": result.tp,
                        "score": result.score,
                    })
                    print(f"  {result.signal.value} entry={result.close:.4f} "
                          f"SL={result.sl:.4f} TP={result.tp:.4f}")
                else:
                    print(f"  BLOCKED")
            except Exception as e:
                print(f"  ERROR - {e}")

    # Summary
    print(f"\n{'='*80}")
    print(f"SUMMARY: {len(signals)} signals found")
    print(f"{'='*80}")

    if signals:
        print(f"\n  {'Symbol':<12} {'TF':<5} {'Type':<5} {'Entry':>12} {'SL':>12} {'TP':>12}")
        print(f"  {'-'*12} {'-'*5} {'-'*5} {'-'*12} {'-'*12} {'-'*12}")
        for s in signals:
            print(f"  {s['symbol']:<12} {s['timeframe']:<5} {s['type']:<5} "
                  f"{s['entry']:>12.4f} {s['sl']:>12.4f} {s['tp']:>12.4f}")


def main():
    parser = argparse.ArgumentParser(description="Run ICT core pipeline")
    parser.add_argument("--symbols", default=None, help="Comma-separated symbols")
    parser.add_argument("--timeframe", default="1h", help="Timeframe to scan")
    args = parser.parse_args()

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
    else:
        symbols = get_active_symbols()

    timeframes = [args.timeframe]

    asyncio.run(run_scan(symbols, timeframes))


if __name__ == "__main__":
    main()
