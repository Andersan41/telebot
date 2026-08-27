"""
Build ML training dataset by replaying the v2 pipeline on historical OHLCV.

For each bar with a triple-barrier label, runs the full v2 pipeline:
  OHLCV window → Indicators → Liquidity → Pattern → Features → to_vector()

Usage:
    python -m ml.build_dataset                         # all labeled symbols
    python -m ml.build_dataset --symbols BTC/USDT      # specific symbol
    python -m ml.build_dataset --lookback 100           # indicator window
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd
from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml.config import (
    LABELED_DIR, DATASET_PATH, TIMEFRAME, EXPIRED_LABEL,
)

# --- Pipeline imports ---
from indicators.engine import indicator_engine, IndicatorValues
from liquidity.sweep import detect_sweeps
from liquidity.order_blocks import detect_order_blocks
from liquidity.fvg import detect_fvg
from liquidity.candle_quality import analyze_last_candle
from market_structure.structure import analyze_structure
from strategy.pattern_engine import PatternEngine
from strategy.feature_builder import FeatureBuilder, SetupFeatures
from risk.market_regime import RegimeDetector
from risk.volatility_regime import classify_volatility
from config.settings import config

# Singletons
_pattern_engine = PatternEngine()
_feature_builder = FeatureBuilder()


def _safe_indicators(df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[IndicatorValues]:
    """Compute indicators, return None on failure."""
    try:
        return indicator_engine.calculate(df, symbol, timeframe)
    except Exception:
        return None


def _safe_structure(df, sweeps, atr_val):
    """Compute market structure, return None on failure."""
    try:
        return analyze_structure(
            df, sweeps=sweeps, lookback=50, swing_window=5,
            displacement_atr=atr_val, atr_value=atr_val,
        )
    except Exception:
        return None


def _safe_regime(ind, df):
    """Compute regime detection, return default on failure."""
    try:
        atr_history = df["high"].rolling(14).max() - df["low"].rolling(14).min()
        atr_hist = atr_history.dropna().tolist()[-50:]
        ema_spread = ((df["close"].ewm(span=8).mean() - df["close"].ewm(span=21).mean()) / df["close"].ewm(span=21).mean() * 100)
        ema_hist = ema_spread.dropna().tolist()[-50:]
        vol_hist = df["volume"].tolist()[-50:]

        detector = RegimeDetector(
            adx=ind.adx,
            atr_history=atr_hist,
            ema_spread_history=ema_hist,
            volume_history=vol_hist,
            current_atr=ind.atr,
            current_volume=ind.volume,
        )
        return detector.detect()
    except Exception:
        from risk.market_regime import MarketRegime
        return MarketRegime(regime="range", confidence=0.5, adx=20, atr_percentile=50, ema_spread_trend="stable")


def _detect_session(ts: pd.Timestamp) -> str:
    """Detect trading session from UTC hour."""
    hour = ts.hour
    if 0 <= hour < 8:
        return "asian"
    elif 8 <= hour < 12:
        return "london"
    elif 12 <= hour < 16:
        return "overlap"
    elif 16 <= hour < 21:
        return "new_york"
    return "off_hours"


def replay_pipeline(
    df: pd.DataFrame,
    bar_idx: int,
    symbol: str,
    timeframe: str,
    tp_price: float,
    sl_price: float,
    entry_price: float,
) -> Optional[Dict]:
    """Replay full v2 pipeline for a single bar. Returns feature dict or None."""
    # Need at least 100 bars before signal for indicators
    lookback = 100
    if bar_idx < lookback:
        return None

    window = df.iloc[bar_idx - lookback: bar_idx + 1].copy()
    if len(window) < lookback:
        return None

    # 1. Indicators
    ind = _safe_indicators(window, symbol, timeframe)
    if ind is None:
        return None

    # 2. Liquidity analysis
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
        candle_quality = analyze_last_candle(window, atr_value=ind.atr)
    except Exception:
        candle_quality = None

    # 3. Market structure
    structure = _safe_structure(window, sweeps, ind.atr)
    if structure is None:
        return None

    # 4. Regime detection
    regime = _safe_regime(ind, window)
    vol_regime = classify_volatility(ind.atr, ind.close)

    # 5. Pattern detection
    try:
        setup = _pattern_engine.detect(
            sweeps=sweeps,
            order_blocks=order_blocks,
            structure=structure,
            fvgs=fvgs,
            candle_quality=candle_quality,
            current_price=ind.close,
            atr=ind.atr,
        )
    except Exception:
        return None

    if not setup.detected:
        return None

    # 6. Get structural TP/SL from TradeEngine (fixes label mismatch)
    #    If trade_engine fails, SKIP the sample — using outcome tp_price/sl_price
    #    would be label leakage (features like rr_ratio would see future info).
    structural_tp = 0.0
    structural_sl = 0.0
    try:
        from strategy.trade_engine import trade_engine
        direction = setup.direction or ("buy" if setup.setup_type and "buy" in setup.setup_type.lower() else "sell")
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
            structural_tp = trade_plan.tp
            structural_sl = trade_plan.sl
        else:
            return None  # No valid structural TP/SL
    except Exception:
        return None  # No valid structural TP/SL — skip to avoid leakage

    # 7. Compute S/R levels (simplified)
    sr_levels = None
    try:
        recent = window.tail(50)
        sr_levels = {
            "offline": {
                "support": [recent["low"].min()],
                "resistance": [recent["high"].max()],
            }
        }
    except Exception:
        pass

    # 8. Build features (use structural TP/SL, not ATR-based)
    try:
        features = _feature_builder.build(
            setup=setup,
            ind=ind,
            structure=structure,
            regime=regime,
            vol_regime=vol_regime,
            mtf_aligned=False,  # No MTF in offline training
            mtf_count=0,
            context_score=0.0,  # Neutral
            fear_greed=50,      # Neutral
            funding_rate=0.0,   # Neutral
            sl=structural_sl,
            tp=structural_tp,
            entry_price=entry_price,
            candle_quality=candle_quality,
            sr_levels=sr_levels,
            is_reversal=setup.is_reversal,
            htf_alignment_score=None,
            premium_discount_score=None,
            htf_bias_penalty=1.0,
            ob_state_multiplier=1.0,
            smt_divergence_score=0.0,
        )
    except Exception:
        return None

    vector = features.to_vector()
    vector["is_4h_aligned"] = 0  # Default: not aligned (no HTF data)
    vector["volume_above_avg"] = int(ind.volume > ind.volume_sma * config.trading.volume_factor)

    return vector


def build_symbol_dataset(
    symbol: str,
    lookback: int = 100,
) -> pd.DataFrame | None:
    """Build dataset for a single symbol from labeled data."""
    safe = symbol.replace("/", "_")
    labeled_path = LABELED_DIR / f"{safe}_{TIMEFRAME}.parquet"
    if not labeled_path.exists():
        print(f"  [SKIP] {symbol} — no labeled data")
        return None

    labeled = pd.read_parquet(labeled_path)

    # Load cached OHLCV for pipeline replay
    from ml.cache_ohlcv import load_cached
    ohlcv = load_cached(symbol)
    if ohlcv is None or ohlcv.empty:
        print(f"  [SKIP] {symbol} — no cached OHLCV")
        return None

    # Include bars with valid labels: TP, SL, and EXPIRED (for expected return)
    # EXPIRED bars with NaN prices (old ATR labeling) are excluded
    has_valid_prices = labeled["entry_price"].notna() & labeled["tp_price"].notna() & labeled["sl_price"].notna()
    train_mask = (labeled["label"] != EXPIRED_LABEL) | ((labeled["label"] == EXPIRED_LABEL) & has_valid_prices)
    train_bars = labeled[train_mask]

    if len(train_bars) == 0:
        print(f"  [SKIP] {symbol} — no labeled bars")
        return None

    tp_bars = (train_bars["label"] == 1).sum()
    sl_bars = (train_bars["label"] == 0).sum()
    exp_bars = (train_bars["label"] == EXPIRED_LABEL).sum()
    print(f"  {symbol}: {len(train_bars)} bars (TP={tp_bars}, SL={sl_bars}, EXPIRED={exp_bars})")

    rows = []
    errors = 0
    for ts, row in train_bars.iterrows():
        # Find bar index in OHLCV
        if ts not in ohlcv.index:
            # Try to find closest
            idx = ohlcv.index.get_indexer([ts], method="nearest")[0]
        else:
            idx = ohlcv.index.get_loc(ts)

        try:
            vector = replay_pipeline(
                df=ohlcv,
                bar_idx=idx,
                symbol=symbol,
                timeframe=TIMEFRAME,
                tp_price=row["tp_price"],
                sl_price=row["sl_price"],
                entry_price=row["entry_price"],
            )
        except Exception:
            errors += 1
            continue

        if vector is None:
            errors += 1
            continue

        # Add metadata
        vector["symbol"] = symbol
        vector["timeframe"] = TIMEFRAME
        vector["timestamp"] = ts
        vector["label"] = row["label"]
        vector["entry_price"] = row["entry_price"]
        vector["tp_price"] = row["tp_price"]
        vector["sl_price"] = row["sl_price"]
        vector["exit_bar"] = row["exit_bar"]
        rows.append(vector)

    if not rows:
        print(f"  [SKIP] {symbol} — no features built (errors={errors})")
        return None

    df = pd.DataFrame(rows)
    tp_count = (df["label"] == 1).sum()
    sl_count = (df["label"] == 0).sum()
    exp_count = (df["label"] == EXPIRED_LABEL).sum()
    print(f"  {symbol}: {len(df)} rows built (TP={tp_count}, SL={sl_count}, EXPIRED={exp_count}, errors={errors})")
    return df


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Build ML training dataset from labeled OHLCV")
    parser.add_argument("--symbols", type=str, default=None)
    parser.add_argument("--lookback", type=int, default=100)
    parser.add_argument("--output", type=str, default=str(DATASET_PATH))
    args = parser.parse_args()

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
    else:
        symbols = []
        for f in LABELED_DIR.glob(f"*_{TIMEFRAME}.parquet"):
            name = f.stem.replace(f"_{TIMEFRAME}", "").replace("_", "/")
            symbols.append(name)

    if not symbols:
        print("No labeled data found. Run: python -m ml.triple_barrier")
        return

    print(f"Building dataset for {len(symbols)} symbols (lookback={args.lookback})")
    print(f"Labeled dir: {LABELED_DIR}")
    print(f"Output: {args.output}\n")

    all_dfs = []
    for symbol in symbols:
        df = build_symbol_dataset(symbol, args.lookback)
        if df is not None and not df.empty:
            all_dfs.append(df)

    if not all_dfs:
        print("\nNo data to combine.")
        return

    combined = pd.concat(all_dfs, ignore_index=True)
    combined.to_parquet(args.output, index=False)

    tp = (combined["label"] == 1).sum()
    sl = (combined["label"] == 0).sum()
    exp = (combined["label"] == EXPIRED_LABEL).sum()
    print(f"\nDataset saved: {args.output}")
    print(f"Total: {len(combined)} rows (TP={tp}, SL={sl}, EXPIRED={exp})")
    print(f"Features: {len([c for c in combined.columns if c not in ('symbol', 'timeframe', 'timestamp', 'label', 'entry_price', 'tp_price', 'sl_price', 'exit_bar')])}")


if __name__ == "__main__":
    main()
