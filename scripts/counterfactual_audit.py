"""
Counterfactual Audit: log every signal evaluation with all features.
For each bar, record: features, gates passed/failed, rejection reason.
Output: CSV for counterfactual analysis.
"""
import asyncio
import csv
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.exchange_client import exchange_client
from strategy.pattern_engine import pattern_engine
from liquidity.sweep import detect_sweeps
from liquidity.order_blocks import detect_order_blocks
from liquidity.fvg import detect_fvg
from liquidity.candle_quality import analyze_last_candle
from market_structure.structure import analyze_structure
from indicators.engine import indicator_engine
import pandas_ta as ta


FIELDS = [
    "symbol", "timeframe", "bar_idx", "timestamp", "close", "atr",
    # Pattern Engine
    "setup_type", "direction", "has_sweep", "sweep_type", "has_mss",
    "has_bos", "has_displacement", "has_ob", "has_fvg", "confirmation_score",
    "entry_armed",
    # Structure
    "trend", "choch_strength", "displacement_score",
    # Rejection
    "detected", "rejection_reason",
    # Gate results (True=PASS, False=BLOCKED)
    "gate_mss", "gate_bos", "gate_displacement", "gate_confirmation",
    "gate_htf_bias", "gate_session", "gate_min_p_tp",
]


async def audit_symbol(symbol: str, timeframe: str, candles: int = 500):
    await exchange_client.connect()
    try:
        df = await exchange_client.fetch_ohlcv_paginated(
            symbol, timeframe, total_limit=candles, page_size=998
        )
    finally:
        await exchange_client.close()

    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)

    output_file = f"scripts/data/audit_{symbol.replace('/', '_')}_{timeframe}.csv"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    with open(output_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()

        lookback = min(80, len(df) - 1)
        for i in range(lookback, len(df)):
            window = df.iloc[: i + 1]
            current_price = float(df["close"].iloc[i])
            atr_val = float(df["atr"].iloc[i]) if df["atr"].iloc[i] is not None and str(df["atr"].iloc[i]) != "nan" else 0.0
            ts = df.index[i]

            try:
                sweeps = detect_sweeps(window, lookback=50)
                obs = detect_order_blocks(window, lookback=100)
                fvgs = detect_fvg(window, lookback=100)
                cq = analyze_last_candle(window, atr_value=atr_val if atr_val > 0 else None)
                structure = analyze_structure(window, lookback=50, sweeps=sweeps, atr_value=atr_val)

                setup = pattern_engine.detect(
                    sweeps=sweeps,
                    order_blocks=obs,
                    structure=structure,
                    fvgs=fvgs,
                    candle_quality=cq,
                    current_price=current_price,
                    atr=atr_val,
                )

                # Structure features
                trend = structure.trend if structure else "unknown"
                choch = structure.last_choch if structure else None
                choch_strength = choch.strength if choch else "none"
                disp_score = choch.displacement_score if choch else 0.0

                # Gate simulation (simplified)
                gate_mss = setup.has_mss if setup.setup_type == "reversal" else True
                gate_bos = setup.has_bos if setup.setup_type == "continuation" else True
                gate_displacement = setup.has_displacement if setup.setup_type == "reversal" else True
                gate_confirmation = setup.confirmation_score >= 2
                gate_htf_bias = True  # would need HTF data
                gate_session = True  # would need session data
                gate_min_p_tp = True  # would need probability engine

                row = {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "bar_idx": i,
                    "timestamp": str(ts),
                    "close": current_price,
                    "atr": atr_val,
                    "setup_type": setup.setup_type or "",
                    "direction": setup.direction or "",
                    "has_sweep": setup.has_sweep,
                    "sweep_type": setup.sweep_type or "",
                    "has_mss": setup.has_mss,
                    "has_bos": setup.has_bos,
                    "has_displacement": setup.has_displacement,
                    "has_ob": setup.has_ob,
                    "has_fvg": setup.has_fvg,
                    "confirmation_score": setup.confirmation_score,
                    "entry_armed": setup.entry_armed,
                    "trend": trend,
                    "choch_strength": choch_strength,
                    "displacement_score": disp_score,
                    "detected": setup.detected,
                    "rejection_reason": setup.rejection_reason or "",
                    "gate_mss": gate_mss,
                    "gate_bos": gate_bos,
                    "gate_displacement": gate_displacement,
                    "gate_confirmation": gate_confirmation,
                    "gate_htf_bias": gate_htf_bias,
                    "gate_session": gate_session,
                    "gate_min_p_tp": gate_min_p_tp,
                }
                writer.writerow(row)

            except Exception as e:
                writer.writerow({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "bar_idx": i,
                    "timestamp": str(df.index[i]),
                    "close": current_price,
                    "rejection_reason": f"error: {e}",
                    "detected": False,
                })

    return output_file


async def main():
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT"]
    timeframe = "1h"
    candles = 500

    for sym in symbols:
        print(f"Auditing {sym}...")
        f = await audit_symbol(sym, timeframe, candles)
        print(f"  -> {f}")


if __name__ == "__main__":
    asyncio.run(main())
