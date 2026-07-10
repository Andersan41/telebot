"""Diagnostic: check why structural SL never applies."""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backtest.engine import BacktestEngine, get_preset_config, BacktestConfig
from config.settings import config
from data.exchange_client import exchange_client
from indicators.engine import IndicatorEngine
from strategy.signal_engine import signal_engine, SignalType
from risk.dynamic_risk import calculate_structural_sl
from liquidity.sweep import detect_sweeps
from liquidity.order_blocks import detect_order_blocks
from market_structure.structure import analyze_structure

import pandas as pd
import numpy as np


async def diagnose():
    config.trading.candles_limit = 3900
    bt_config = BacktestConfig(
        enable_unified_entry=False,
        enable_confirm_tf_gate=False,
        enable_structural_sl=True,
        enable_sl_distance_guard=False,
        enable_rr_filter=False,
        enable_news_filter=False,
        enable_stop_hunt_buffer=False,
    )

    # Paginated fetch
    _orig_fetch = exchange_client.fetch_ohlcv
    async def _fetch_paginated(symbol, timeframe, limit=200):
        if limit > 998:
            return await exchange_client.fetch_ohlcv_paginated(
                symbol, timeframe, total_limit=limit, page_size=998,
            )
        return await _orig_fetch(symbol, timeframe, limit)
    exchange_client.fetch_ohlcv = _fetch_paginated

    await exchange_client.connect()
    try:
        symbol = "BTC/USDT"
        timeframe = "1h"
        limit = max(config.trading.candles_limit + 100, 200)
        df = await exchange_client.fetch_ohlcv(symbol, timeframe, limit=limit)
        warmup = 80
        candle_limit = config.trading.candles_limit
        df = df.iloc[-(candle_limit + 60):] if len(df) > candle_limit + 60 else df

        indicator_engine = IndicatorEngine()
        eligible = 0
        structural_found = 0
        structural_rejected_gate = 0
        structural_rejected_same = 0

        for i in range(warmup, len(df)):
            window = df.iloc[:i + 1].copy()
            ind = indicator_engine.calculate(window, symbol, timeframe)
            if ind is None:
                continue

            # Get liquidity data
            try:
                _df_clean = window.dropna(subset=["open", "high", "low", "close", "volume"])
                all_sweeps = detect_sweeps(_df_clean) if len(_df_clean) >= 10 else []
                valid_sweeps = [s for s in all_sweeps if getattr(s, "is_valid", True)]
                all_obs = detect_order_blocks(_df_clean) if len(_df_clean) >= 10 else []
                valid_obs = [ob for ob in all_obs if getattr(ob, "is_valid", False)]
                structure = analyze_structure(_df_clean) if len(_df_clean) >= 20 else None
            except Exception:
                valid_sweeps = []
                valid_obs = []
                structure = None

            # Run signal engine
            result = signal_engine.evaluate(ind, structure=structure, sweeps=valid_sweeps, order_blocks=valid_obs)
            if not (result.is_actionable and result.sl is not None):
                continue

            if result._sl_source == "bos":
                continue  # BOS skips structural SL

            eligible += 1
            entry_price = float(ind.close)
            atr_val = float(ind.atr) if ind.atr is not None else 0.0
            if atr_val <= 0:
                atr_val = float(ind.close) * 0.02

            new_sl = calculate_structural_sl(
                direction=result.signal.value,
                entry=entry_price,
                sweeps=valid_sweeps,
                order_blocks=valid_obs,
                structure=structure,
                atr=atr_val,
                close=float(ind.close) if ind.close else 0.0,
            )

            current_dist = abs(entry_price - result.sl)
            structural_dist = abs(entry_price - new_sl)

            if new_sl == result.sl:
                structural_rejected_same += 1
            elif structural_dist > current_dist:
                structural_rejected_gate += 1
            else:
                structural_found += 1
                if structural_found <= 5:
                    print(f"  FOUND: {result.signal.value} entry={entry_price:.2f} atr_sl={result.sl:.2f} struct_sl={new_sl:.2f} dist_ratio={structural_dist/current_dist:.3f}")

        print(f"\nDiagnosis for {symbol}:")
        print(f"  ATR-sourced eligible trades: {eligible}")
        print(f"  Structural SL found (candidates): {structural_found}")
        print(f"  Structural SL same as ATR: {structural_rejected_same}")
        print(f"  Structural SL rejected by gate (dist > current): {structural_rejected_gate}")
        print(f"  Activation rate: {structural_found}/{eligible} = {structural_found/eligible*100:.1f}%" if eligible > 0 else "  N/A")
    finally:
        exchange_client.fetch_ohlcv = _orig_fetch
        await exchange_client.close()


asyncio.run(diagnose())
