"""
Triple-barrier labeling for historical OHLCV data.

Two modes:
  - ATR mode (legacy): TP/SL from fixed ATR multiples
  - Structural mode: TP/SL from TradeEngine (OB/FVG/Structure/Liquidity)

Labels:
  - label=1  (HIT_TP)  : price hit take-profit within MAX_BARS
  - label=0  (HIT_SL)  : price hit stop-loss within MAX_BARS
  - label=-1 (EXPIRED) : timeout — used as 0R in expected return

Usage:
    python -m ml.triple_barrier                              # all cached symbols (default mode)
    python -m ml.triple_barrier --mode structural            # structural TP/SL
    python -m ml.triple_barrier --symbols BTC/USDT           # specific symbol
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml.config import (
    OHLCV_DIR, LABELED_DIR, TIMEFRAME,
    LABELING_MODE, TP_ATR_MULT, SL_ATR_MULT, MAX_BARS, EXPIRED_LABEL,
)


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute ATR from OHLCV DataFrame using pandas-ta."""
    import pandas_ta as ta
    atr = ta.atr(df["high"], df["low"], df["close"], length=period)
    return atr


def triple_barrier_label(
    df: pd.DataFrame,
    tp_mult: float = TP_ATR_MULT,
    sl_mult: float = SL_ATR_MULT,
    max_bars: int = MAX_BARS,
    atr_period: int = 14,
) -> pd.DataFrame:
    """Apply triple-barrier labeling to OHLCV DataFrame.

    Returns DataFrame with columns:
        entry_price, tp_price, sl_price, label, exit_bar, exit_price, atr
    """
    atr = compute_atr(df, atr_period)
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    n = len(df)

    entries = np.full(n, np.nan)
    tp_prices = np.full(n, np.nan)
    sl_prices = np.full(n, np.nan)
    labels = np.full(n, EXPIRED_LABEL, dtype=int)
    exit_bars = np.full(n, -1, dtype=int)
    exit_prices = np.full(n, np.nan)

    for i in range(n - 1):
        current_atr = atr.iloc[i] if pd.notna(atr.iloc[i]) else 0.0
        if current_atr <= 0 or close[i] <= 0:
            continue

        entry = close[i]  # Entry at close of signal bar (= open of next bar approximately)
        atr_pct = current_atr / close[i]

        tp_level = entry * (1 + tp_mult * atr_pct)
        sl_level = entry * (1 - sl_mult * atr_pct)

        entries[i] = entry
        tp_prices[i] = tp_level
        sl_prices[i] = sl_level

        # Scan forward from i+1 to i+max_bars
        label = EXPIRED_LABEL
        exit_bar = -1
        exit_price = np.nan

        end = min(i + 1 + max_bars, n)
        for j in range(i + 1, end):
            # Check TP hit (high reached TP)
            if high[j] >= tp_level:
                label = 1
                exit_bar = j - i
                exit_price = tp_level
                break
            # Check SL hit (low reached SL)
            if low[j] <= sl_level:
                label = 0
                exit_bar = j - i
                exit_price = sl_level
                break

        labels[i] = label
        exit_bars[i] = exit_bar
        exit_prices[i] = exit_price

    result = df.copy()
    result["entry_price"] = entries
    result["tp_price"] = tp_prices
    result["sl_price"] = sl_prices
    result["label"] = labels
    result["exit_bar"] = exit_bars
    result["exit_price"] = exit_prices
    result["atr"] = atr.values

    return result


def _get_structural_tp_sl(
    df: pd.DataFrame,
    bar_idx: int,
    symbol: str,
    timeframe: str,
) -> tuple[float, float] | None:
    """Get TP/SL from TradeEngine for a single bar. Returns (tp, sl) or None."""
    try:
        from indicators.engine import indicator_engine
        from liquidity.sweep import detect_sweeps
        from liquidity.order_blocks import detect_order_blocks
        from liquidity.fvg import detect_fvg
        from market_structure.structure import analyze_structure
        from strategy.trade_engine import trade_engine
    except ImportError:
        return None

    lookback = 100
    if bar_idx < lookback:
        return None

    window = df.iloc[bar_idx - lookback: bar_idx + 1].copy()
    if len(window) < lookback:
        return None

    # Indicators
    try:
        ind = indicator_engine.calculate(window, symbol, timeframe)
    except Exception:
        return None
    if ind is None or not ind.atr or ind.atr <= 0:
        return None

    # Liquidity / structure
    try:
        sweeps = detect_sweeps(window, lookback=50, swing_window=5)
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
        structure = analyze_structure(
            window, sweeps=sweeps, lookback=50, swing_window=5,
            displacement_atr=ind.atr, atr_value=ind.atr,
        )
    except Exception:
        structure = None

    # Detect direction from structure trend
    direction = "buy"
    if structure and structure.trend == "bearish":
        direction = "sell"

    # Build trade plan
    try:
        trade_plan = trade_engine.build_trade_plan(
            ind=ind,
            direction=direction,
            structure=structure,
            order_blocks=order_blocks,
            sweeps=sweeps,
            fvgs=fvgs,
            df=window,
            timeframe=timeframe,
        )
        if trade_plan and trade_plan.sl > 0 and trade_plan.tp > 0:
            return (trade_plan.tp, trade_plan.sl)
    except Exception:
        pass

    return None


def triple_barrier_structural(
    df: pd.DataFrame,
    symbol: str,
    max_bars: int = MAX_BARS,
    atr_period: int = 14,
) -> pd.DataFrame:
    """Triple-barrier labeling using TradeEngine's dynamic TP/SL.

    For each bar:
      1. Run full v2 pipeline (indicators, sweeps, OBs, FVGs, structure)
      2. Call TradeEngine to get structural TP/SL
      3. Fallback to ATR if TradeEngine fails
      4. Forward scan to determine TP/SL/EXPIRED label
    """
    atr = compute_atr(df, atr_period)
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    n = len(df)

    entries = np.full(n, np.nan)
    tp_prices = np.full(n, np.nan)
    sl_prices = np.full(n, np.nan)
    labels = np.full(n, EXPIRED_LABEL, dtype=int)
    exit_bars = np.full(n, -1, dtype=int)
    exit_prices = np.full(n, np.nan)

    lookback = 100
    structural_count = 0
    atr_fallback_count = 0

    for i in range(n - 1):
        current_atr = atr.iloc[i] if pd.notna(atr.iloc[i]) else 0.0
        if current_atr <= 0 or close[i] <= 0:
            continue

        entry = close[i]
        entry_price_for_engine = entry

        # Try structural TP/SL first
        tp_level = 0.0
        sl_level = 0.0

        if i >= lookback:
            result = _get_structural_tp_sl(df, i, symbol, TIMEFRAME)
            if result is not None:
                tp_level, sl_level = result
                structural_count += 1

        # Fallback to ATR
        if tp_level <= 0 or sl_level <= 0:
            atr_pct = current_atr / close[i]
            tp_level = entry * (1 + TP_ATR_MULT * atr_pct)
            sl_level = entry * (1 - SL_ATR_MULT * atr_pct)
            atr_fallback_count += 1

        # Ensure valid levels (tp > entry for buy, sl < entry for buy)
        if tp_level <= entry:
            tp_level = entry * 1.01
        if sl_level >= entry:
            sl_level = entry * 0.99

        entries[i] = entry
        tp_prices[i] = tp_level
        sl_prices[i] = sl_level

        # Forward scan (identical to ATR version)
        label = EXPIRED_LABEL
        exit_bar = -1
        exit_price = np.nan

        end = min(i + 1 + max_bars, n)
        for j in range(i + 1, end):
            if high[j] >= tp_level:
                label = 1
                exit_bar = j - i
                exit_price = tp_level
                break
            if low[j] <= sl_level:
                label = 0
                exit_bar = j - i
                exit_price = sl_level
                break

        labels[i] = label
        exit_bars[i] = exit_bar
        exit_prices[i] = exit_price

    result_df = df.copy()
    result_df["entry_price"] = entries
    result_df["tp_price"] = tp_prices
    result_df["sl_price"] = sl_prices
    result_df["label"] = labels
    result_df["exit_bar"] = exit_bars
    result_df["exit_price"] = exit_prices
    result_df["atr"] = atr.values

    print(f"    structural={structural_count}, atr_fallback={atr_fallback_count}")
    return result_df


def label_symbol(
    symbol: str,
    tp_mult: float = TP_ATR_MULT,
    sl_mult: float = SL_ATR_MULT,
    max_bars: int = MAX_BARS,
    mode: str = LABELING_MODE,
) -> pd.DataFrame | None:
    """Load cached OHLCV, apply triple-barrier, save labeled data."""
    safe = symbol.replace("/", "_")
    cache_path = OHLCV_DIR / f"{safe}_{TIMEFRAME}.parquet"
    if not cache_path.exists():
        print(f"  [SKIP] {symbol} — no cached OHLCV")
        return None

    df = pd.read_parquet(cache_path)
    if len(df) < 50:
        print(f"  [SKIP] {symbol} — only {len(df)} rows (need 50+)")
        return None

    if mode == "structural":
        labeled = triple_barrier_structural(df, max_bars)
    else:
        labeled = triple_barrier_label(df, tp_mult, sl_mult, max_bars)

    # Stats
    total = (labeled["label"] != EXPIRED_LABEL).sum()
    tp_count = (labeled["label"] == 1).sum()
    sl_count = (labeled["label"] == 0).sum()
    expired_count = (labeled["label"] == EXPIRED_LABEL).sum()

    print(f"  {symbol}: {len(labeled)} bars -> TP={tp_count} SL={sl_count} EXPIRED={expired_count} (labeled={total})")

    # Save
    LABELED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = LABELED_DIR / f"{safe}_{TIMEFRAME}.parquet"
    labeled.to_parquet(out_path, index=True)

    return labeled


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Triple-barrier labeling for ML training")
    parser.add_argument("--symbols", type=str, default=None)
    parser.add_argument("--mode", type=str, default=LABELING_MODE,
                        choices=["atr", "structural"],
                        help="Labeling mode: atr (fixed ATR) or structural (TradeEngine)")
    parser.add_argument("--tp-mult", type=float, default=TP_ATR_MULT)
    parser.add_argument("--sl-mult", type=float, default=SL_ATR_MULT)
    parser.add_argument("--max-bars", type=int, default=MAX_BARS)
    args = parser.parse_args()

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
    else:
        # Discover from cached files
        symbols = []
        for f in OHLCV_DIR.glob(f"*_{TIMEFRAME}.parquet"):
            name = f.stem.replace(f"_{TIMEFRAME}", "").replace("_", "/")
            symbols.append(name)

    if not symbols:
        print("No cached OHLCV found. Run: python -m ml.cache_ohlcv")
        return

    if args.mode == "structural":
        print(f"Labeling {len(symbols)} symbols (mode=structural, max={args.max_bars} bars)")
    else:
        print(f"Labeling {len(symbols)} symbols (TP={args.tp_mult}xATR, SL={args.sl_mult}xATR, max={args.max_bars} bars)")
    print(f"Cache dir: {OHLCV_DIR}")
    print(f"Output dir: {LABELED_DIR}\n")

    total_labeled = 0
    for symbol in symbols:
        result = label_symbol(symbol, args.tp_mult, args.sl_mult, args.max_bars, mode=args.mode)
        if result is not None:
            total_labeled += (result["label"] != EXPIRED_LABEL).sum()

    print(f"\nDone: {total_labeled} total labeled setups")


if __name__ == "__main__":
    main()
