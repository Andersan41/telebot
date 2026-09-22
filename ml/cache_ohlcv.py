"""
OHLCV cache for ML training pipeline.

Fetches 4h candles from BingX, saves to data/training/ohlcv/ as parquet.
Supports incremental updates — only fetches new candles on subsequent runs.

Usage:
    python -m ml.cache_ohlcv                     # all symbols from .env
    python -m ml.cache_ohlcv --symbols BTC/USDT  # specific symbol
    python -m ml.cache_ohlcv --update            # incremental (append new)
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml.config import OHLCV_DIR, TIMEFRAME, DEFAULT_CANDLES
from data.exchange_client import exchange_client


def _cache_path(symbol: str) -> Path:
    safe = symbol.replace("/", "_")
    return OHLCV_DIR / f"{safe}_{TIMEFRAME}.parquet"


def load_cached(symbol: str) -> pd.DataFrame | None:
    path = _cache_path(symbol)
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(
            f"Cache {path.name} has {type(df.index).__name__} index, "
            f"expected DatetimeIndex. Delete and re-cache."
        )
    return df


def save_cached(symbol: str, df: pd.DataFrame) -> None:
    OHLCV_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(symbol)
    df.to_parquet(path, index=True)


async def fetch_and_cache(symbol: str, candles: int, update: bool = False) -> pd.DataFrame:
    """Fetch OHLCV from BingX (paginated) and cache to disk.

    If update=True and cache exists, only fetch candles newer than last cached.
    """
    existing = load_cached(symbol) if update else None
    if existing is not None and len(existing) >= candles * 0.9:
        print(f"  [CACHE HIT] {symbol} {TIMEFRAME} -> {len(existing)} rows")
        return existing

    if existing is not None and update:
        # Fetch only new candles after last cached timestamp
        last_ts = existing.index[-1]
        print(f"  [UPDATE] {symbol} from {last_ts}...", end=" ", flush=True)
        t0 = time.time()
        new_df = await exchange_client.fetch_ohlcv_paginated(
            symbol, TIMEFRAME, total_limit=candles, page_size=998,
        )
        elapsed = time.time() - t0
        if new_df is not None and not new_df.empty:
            # Merge: keep existing, append new rows not already present
            combined = pd.concat([existing, new_df])
            combined = combined[~combined.index.duplicated(keep="last")]
            combined = combined.sort_index()
            # Trim to requested candle count
            if len(combined) > candles:
                combined = combined.iloc[-candles:]
            save_cached(symbol, combined)
            added = len(combined) - len(existing)
            print(f"+{added} rows ({elapsed:.1f}s) -> {len(combined)} total")
            return combined
        print(f"no new data ({elapsed:.1f}s)")
        return existing

    # Full fetch
    print(f"  [FETCH] {symbol} {TIMEFRAME} {candles}c...", end=" ", flush=True)
    t0 = time.time()
    df = await exchange_client.fetch_ohlcv_paginated(
        symbol, TIMEFRAME, total_limit=candles, page_size=998,
    )
    elapsed = time.time() - t0
    if df is None or df.empty:
        print(f"FAILED ({elapsed:.1f}s)")
        return pd.DataFrame()

    print(f"{len(df)} rows ({elapsed:.1f}s)")
    save_cached(symbol, df)
    return df


async def cache_all(symbols: list[str], candles: int, update: bool = False) -> None:
    OHLCV_DIR.mkdir(parents=True, exist_ok=True)
    await exchange_client.connect()

    print(f"Caching {len(symbols)} symbols x {candles} candles ({TIMEFRAME})")
    print(f"Cache dir: {OHLCV_DIR}")

    total_rows = 0
    for i, symbol in enumerate(symbols, 1):
        print(f"\n[{i}/{len(symbols)}] {symbol}")
        df = await fetch_and_cache(symbol, candles, update=update)
        if df is not None and not df.empty:
            total_rows += len(df)
        await asyncio.sleep(0.5)

    print(f"\nDone: {total_rows:,} total rows cached")
    await exchange_client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Cache 4h OHLCV for ML training")
    parser.add_argument("--symbols", type=str, default=None,
                        help="Comma-separated symbols (default: from .env)")
    parser.add_argument("--candles", type=int, default=DEFAULT_CANDLES)
    parser.add_argument("--update", action="store_true",
                        help="Incremental update — only fetch new candles")
    args = parser.parse_args()

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
    else:
        from config.settings import config
        symbols = list(config.trading.symbols)

    asyncio.run(cache_all(symbols, args.candles, update=args.update))
