"""
analyze_ena.py — Полный анализ ENA/USDT на 1H
"""
import asyncio
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from datetime import datetime, timezone
from typing import Any
import pandas as pd
import numpy as np

from config.settings import config
from data.exchange_client import exchange_client
from indicators.engine import indicator_engine, IndicatorValues
from strategy.levels import get_support_resistance
from strategy.signal_engine import signal_engine, SignalType
from risk.market_regime import RegimeDetector

def _safe(val: Any, fmt: str = ".2f") -> str:
    if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
        return "N/A"
    return f"{val:{fmt}}"

def print_indicators(ind: IndicatorValues):
    print(f"\n  {'='*50}")
    print(f"  INDICATORS")
    print(f"  {'='*50}")
    print(f"  Close:         ${_safe(ind.close, '.5f')}")
    print(f"  High:          ${_safe(ind.high, '.5f')}")
    print(f"  Low:           ${_safe(ind.low, '.5f')}")
    print(f"  Volume:        {_safe(ind.volume, '.0f')}")

    print(f"\n  -- EMA ({config.trading.ema_fast}/{config.trading.ema_slow}/{config.trading.ema_trend}) --")
    print(f"  Fast:          ${_safe(ind.ema_fast, '.5f')}")
    print(f"  Slow:          ${_safe(ind.ema_slow, '.5f')}")
    print(f"  Trend:         ${_safe(ind.ema_trend, '.5f')}")
    al = "BULLISH" if ind.ema_bullish_alignment else ("BEARISH" if ind.ema_bearish_alignment else "NONE")
    print(f"  Alignment:     {al}")
    cr = "BULLISH" if ind.ema_bullish_cross else ("BEARISH" if ind.ema_bearish_cross else "NONE")
    print(f"  Cross:         {cr}")
    sp = (ind.ema_fast - ind.ema_slow) / ind.ema_slow * 100 if ind.ema_slow else 0
    print(f"  Spread:        {sp:.3f}% (min {config.trading.min_ema_spread_pct:.2f}%)")

    print(f"\n  -- SUPERTREND --")
    sd = "BULLISH" if ind.supertrend_bullish else ("BEARISH" if ind.supertrend_bearish else "NEUTRAL")
    print(f"  Direction:     {sd}")
    print(f"  Level:         ${_safe(ind.supertrend, '.5f')}")
    print(f"  Price vs ST:   {'Above (bullish)' if ind.close > ind.supertrend else 'Below (bearish)'} ({abs(ind.close - ind.supertrend)/ind.close*100:.2f}%)")

    print(f"\n  -- RSI ({config.trading.rsi_period}) --")
    print(f"  RSI:           {_safe(ind.rsi, '.1f')}")
    ob, os_ = config.trading.rsi_overbought, config.trading.rsi_oversold
    if ind.rsi >= ob: z = "OVERBOUGHT"
    elif ind.rsi <= os_: z = "OVERSOLD"
    elif ind.rsi >= config.trading.rsi_bull_min: z = "BULLISH"
    elif ind.rsi <= config.trading.rsi_bear_max: z = "BEARISH"
    else: z = "NEUTRAL"
    print(f"  Zone:          {z}")

    print(f"\n  -- MACD ({config.trading.macd_fast}/{config.trading.macd_slow}/{config.trading.macd_signal}) --")
    print(f"  Histogram:     {_safe(ind.macd_hist, '.8f')}")
    mc = "BULLISH" if ind.macd_bullish_cross else ("BEARISH" if ind.macd_bearish_cross else "NONE")
    print(f"  Cross:         {mc}")

    print(f"\n  -- ADX/DMI ({config.trading.adx_period}) --")
    print(f"  ADX:           {_safe(ind.adx, '.1f')} (min {config.trading.adx_min})")
    tr = "STRONG" if ind.adx >= config.trading.adx_strong else ("WEAK/FLAT" if ind.adx < config.trading.adx_min else "MODERATE")
    print(f"  Trend:         {tr}")
    print(f"  DMI+:          {_safe(ind.dmi_plus, '.1f')}")
    print(f"  DMI-:          {_safe(ind.dmi_minus, '.1f')}")
    dd = ind.dmi_plus - ind.dmi_minus
    print(f"  DMI bias:      {'BULLISH' if dd > 0 else 'BEARISH' if dd < 0 else 'NEUTRAL'} ({dd:+.1f})")

    print(f"\n  -- VOLUME --")
    print(f"  Vol:           {_safe(ind.volume, '.0f')}")
    print(f"  SMA(20):       {_safe(ind.volume_sma, '.0f')}")
    vr = ind.volume / ind.volume_sma if ind.volume_sma else 0
    print(f"  Ratio:         {vr:.2f}x (factor {config.trading.volume_factor}x)")
    va = ind.volume > ind.volume_sma * config.trading.volume_factor
    print(f"  Above avg:     {'YES' if va else 'NO'}")

    print(f"\n  -- ATR --")
    print(f"  ATR:           ${_safe(ind.atr, '.5f')}")
    print(f"  ATR%:          {ind.atr/ind.close*100:.2f}%" if ind.close else "  ATR%: N/A")

async def analyze_ena():
    symbol = "ENA/USDT"
    tf = "1h"

    print(f"\n{'='*60}")
    print(f"  FULL ANALYSIS: {symbol} -- {tf}")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")

    print(f"\n  >> Connecting to {config.exchange.name}...")
    await exchange_client.connect()
    print(f"  OK")

    print(f"\n  >> Fetching OHLCV {symbol} {tf}...")
    df = await exchange_client.fetch_ohlcv(symbol, tf, limit=config.trading.candles_limit)
    if df is None:
        print(f"  FAILED: no data")
        return
    current_price = float(df["close"].iloc[-1])
    print(f"  OK: {len(df)} candles, price=${current_price:.5f}")

    print(f"\n  >> Calculating indicators...")
    ind = indicator_engine.calculate(df, symbol, tf)
    if ind is None:
        print(f"  FAILED")
        return
    print_indicators(ind)

    # Support/Resistance
    print(f"\n\n  >> Support / Resistance levels...")
    sr_levels = {}
    for sr_tf in ["1h", "4h"]:
        sr_df = df if sr_tf == "1h" else await exchange_client.fetch_ohlcv(symbol, sr_tf, limit=100)
        if sr_df is not None:
            levels = get_support_resistance(sr_df, current_price, window=8, threshold=0.003, max_levels=3)
            sr_levels[sr_tf] = levels
    for tf_name, lvls in sr_levels.items():
        r = " / ".join(f"${v:.5f}" for v in lvls.get("resistance", [])) or "--"
        s = " / ".join(f"${v:.5f}" for v in lvls.get("support", [])) or "--"
        print(f"  [{tf_name}]")
        print(f"    Resistance:  {r}")
        print(f"    Support:     {s}")
        if lvls.get("resistance") and current_price:
            for v in lvls["resistance"]:
                print(f"      -> dist to R: {(v-current_price)/current_price*100:+.2f}%")
        if lvls.get("support") and current_price:
            for v in lvls["support"]:
                print(f"      -> dist to S: {(v-current_price)/current_price*100:+.2f}%")

    # Market regime
    print(f"\n\n  >> Market regime...")
    atr_vals = df["atr"].dropna().tolist() if "atr" in df.columns else [ind.atr] * 20
    ema_spread = ((df["ema_fast"] - df["ema_slow"]) / df["ema_slow"] * 100).dropna().tolist() if "ema_fast" in df.columns else [0] * 20
    vol_hist = df["volume"].dropna().tolist() if "volume" in df.columns else []
    regime_detector = RegimeDetector(
        adx=ind.adx,
        atr_history=atr_vals[-30:],
        ema_spread_history=ema_spread[-30:],
        volume_history=vol_hist[-30:],
        current_atr=ind.atr,
        current_volume=ind.volume,
    )
    regime = regime_detector.detect()
    if regime:
        print(f"  Regime:        {regime.regime}")
        print(f"  Confidence:    {regime.confidence:.2f}")
        print(f"  ATR percentile:{regime.atr_percentile:.2f}")
        print(f"  EMA spread:    {regime.ema_spread_trend}")

    # Signal engine
    print(f"\n\n  >> Signal Engine...")
    result = signal_engine.evaluate(ind, regime=regime)
    print(f"  Signal:        {result.signal.name}")
    print(f"  Score:         {result.score}")
    if result.reasons:
        print(f"  Reasons:")
        for r in result.reasons:
            print(f"    - {r}")
    if result.entry_price:
        print(f"  Entry:         ${_safe(result.entry_price, '.5f')}")
    if result.sl:
        print(f"  SL:            ${_safe(result.sl, '.5f')}")
    if result.tp:
        print(f"  TP:            ${_safe(result.tp, '.5f')}")
    if result.signal != SignalType.NO_SIGNAL and result.entry_price and result.sl:
        side_mult = 1 if result.signal == SignalType.BUY else -1
        sl_pct = (result.entry_price - result.sl) / result.entry_price * 100 * side_mult
        tp_pct = (result.tp - result.entry_price) / result.entry_price * 100 * side_mult if result.tp else 0
        rr = abs(tp_pct / sl_pct) if sl_pct else 0
        print(f"  SL%:           {abs(sl_pct):.2f}%")
        print(f"  TP%:           {abs(tp_pct):.2f}%")
        print(f"  R:R:           {rr:.2f}")

    # Condition summary (4 of 6)
    print(f"\n\n  {'='*50}")
    print(f"  CONDITION CHECKLIST (per AGENTS.md: 4 of 6)")
    print(f"  {'='*50}")
    conds = {}
    al = ind.ema_bullish_alignment or ind.ema_bearish_alignment
    conds["EMA alignment"] = al
    ec = ind.ema_bullish_cross or ind.ema_bearish_cross
    conds["EMA cross/pos"] = ec
    conds["Supertrend"] = ind.supertrend_direction != 0
    conds["RSI"] = True  # always contributes
    conds["MACD"] = ind.macd_bullish_cross or ind.macd_bearish_cross
    va_ = ind.volume > ind.volume_sma * config.trading.volume_factor
    conds["Volume"] = va_
    adx_pass = ind.adx >= config.trading.adx_min
    conds["ADX >= 20"] = adx_pass

    ok_count = sum(1 for v in conds.values() if v)
    for name, passed in conds.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    print(f"\n  TOTAL: {ok_count} / {len(conds)} passed")
    print(f"  NEED: 4 of 6 (ADX is a hard filter, excluded from 4-of-6 count)")

    print(f"\n{'='*60}")
    print(f"  ANALYSIS COMPLETE")
    print(f"{'='*60}\n")

    await exchange_client.close()

if __name__ == "__main__":
    asyncio.run(analyze_ena())
