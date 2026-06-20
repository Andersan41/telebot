"""
backtest_real.py — Full pipeline backtest on live exchange data.

Usage:
    python backtest_real.py BTC/USDT 1h 336
    python backtest_real.py ETH/USDT 4h 200
"""
import asyncio
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from datetime import datetime, timezone
from typing import Optional
import numpy as np
import pandas as pd

sys.path.insert(0, __file__.rsplit("\\", 2)[0])

from config.settings import config
from data.exchange_client import exchange_client
from indicators.engine import indicator_engine, IndicatorValues
from strategy.signal_engine import signal_engine, SignalType, SignalResult
from risk.market_regime import RegimeDetector, MarketRegime
from liquidity.sweep import detect_sweeps
from liquidity.order_blocks import detect_order_blocks
from liquidity.fvg import detect_fvg
from market_structure.structure import analyze_structure

# ── helpers ──────────────────────────────────────────────────────────────

def _detect_regime(ind: IndicatorValues, atr_history: list[float]) -> str:
    atr_pct = (ind.atr / ind.close * 100) if ind.close > 0 else 0
    if len(atr_history) >= 20:
        atr_percentile = sum(1 for a in atr_history if a <= ind.atr) / len(atr_history) * 100
    else:
        atr_percentile = 50.0
    if atr_percentile < 20:
        return "compression"
    if len(atr_history) >= 5:
        recent = np.mean(atr_history[-5:])
        older = np.mean(atr_history[-20:-5]) if len(atr_history) >= 20 else recent * 0.9
        if recent > older and ind.volume > ind.volume_sma * 1.2:
            return "expansion"
    if ind.adx > 25:
        return "trend"
    if ind.adx < 18:
        return "range"
    vh = getattr(config.risk, "volatility_high_threshold", 4.0)
    vl = getattr(config.risk, "volatility_low_threshold", 1.0)
    if atr_pct > vh:
        return "high_vol"
    if atr_pct < vl:
        return "low_vol"
    return "trend"

def make_regime_obj(ind: IndicatorValues, atr_history: list[float]) -> MarketRegime:
    label = _detect_regime(ind, atr_history)
    atr_pct = sum(1 for a in atr_history if a <= ind.atr) / max(len(atr_history), 1) * 100 if atr_history else 50
    return MarketRegime(regime=label, confidence=0.5, adx=float(ind.adx), atr_percentile=min(atr_pct, 100), ema_spread_trend="stable")

# ── main ─────────────────────────────────────────────────────────────────

async def main():
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "BTC/USDT"
    tf = (sys.argv[2] if len(sys.argv) > 2 else "1h").lower()
    candle_limit = int(sys.argv[3]) if len(sys.argv) > 3 else 336

    if "/" not in symbol and symbol.endswith("USDT"):
        symbol = symbol[:-4] + "/USDT"
    elif "/" not in symbol:
        symbol += "/USDT"

    print(f"Connecting…")
    await exchange_client.connect()

    limit = max(candle_limit + 100, 200)
    print(f"Fetching {symbol} {tf} last {candle_limit} candles…")
    df = await exchange_client.fetch_ohlcv(symbol, tf, limit=limit)
    if df is None or len(df) < 100:
        print("Not enough data")
        return
    print(f"Loaded {len(df)} candles")

    # trim to requested count (keep warmup)
    df = df.iloc[-(candle_limit + 60):] if len(df) > candle_limit + 60 else df

    trades: list[dict] = []
    atr_history: list[float] = []
    warmup = 80
    in_trade = False
    ct: Optional[dict] = None  # current trade

    for i in range(warmup, len(df)):
        window = df.iloc[:i + 1].copy()
        ind = indicator_engine.calculate(window, symbol, tf)
        if ind is None:
            continue
        atr_history.append(float(ind.atr))

        # exit check
        if in_trade and ct is not None:
            high, low = float(ind.high), float(ind.low)
            entry, sl, tp, direction = ct["entry"], ct["sl"], ct["tp"], ct["dir"]
            if direction == "BUY":
                if low <= sl:
                    ct["exit"] = sl; ct["exit_i"] = i; ct["reason"] = "SL"
                    trades.append(ct); in_trade = False; ct = None
                elif high >= tp:
                    ct["exit"] = tp; ct["exit_i"] = i; ct["reason"] = "TP"
                    trades.append(ct); in_trade = False; ct = None
            else:
                if high >= sl:
                    ct["exit"] = sl; ct["exit_i"] = i; ct["reason"] = "SL"
                    trades.append(ct); in_trade = False; ct = None
                elif low <= tp:
                    ct["exit"] = tp; ct["exit_i"] = i; ct["reason"] = "TP"
                    trades.append(ct); in_trade = False; ct = None

        # new signal
        if not in_trade:
            try:
                structure = analyze_structure(window.tail(100))
            except Exception:
                structure = None
            try:
                valid_sweeps = [s for s in detect_sweeps(window.tail(100), swing_window=5) if getattr(s, "is_valid", False)]
            except Exception:
                valid_sweeps = []
            try:
                valid_obs = [ob for ob in (detect_order_blocks(window.tail(100)) or []) if getattr(ob, "is_valid", False)]
            except Exception:
                valid_obs = []

            regime_obj = make_regime_obj(ind, atr_history)
            result = signal_engine.evaluate(ind, regime=regime_obj, structure=structure, sweeps=valid_sweeps, order_blocks=valid_obs)

            if result.is_actionable and result.sl and result.tp:
                ct = {
                    "entry": float(ind.close), "exit": None, "exit_i": None, "reason": None,
                    "sl": float(result.sl), "tp": float(result.tp),
                    "dir": result.signal.value, "score": result.score,
                    "regime": regime_obj.regime, "entry_i": i,
                }
                in_trade = True

    # close last trade at end of data
    if in_trade and ct is not None:
        ct["exit"] = float(df.iloc[-1]["close"])
        ct["exit_i"] = len(df) - 1
        ct["reason"] = "EOB"
        trades.append(ct)

    # ── results ──
    print(f"\n{'='*55}")
    print(f"  BACKTEST: {symbol} {tf} — {len(df)} candles ({(len(df)/4/24 if '4h' in tf else len(df)/24):.1f} days)")
    print(f"  Period: {df.index[0].strftime('%Y-%m-%d %H:%M')} → {df.index[-1].strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}")

    if not trades:
        print("\n  No trades generated")
        await exchange_client.close()
        return

    full_trades = []
    for t in trades:
        if t["dir"] == "BUY":
            t["pnl"] = (t["exit"] - t["entry"]) / t["entry"] * 100
            t["rr"] = abs(t["exit"] - t["entry"]) / abs(t["entry"] - t["sl"]) if t["sl"] != t["entry"] else 0
        else:
            t["pnl"] = (t["entry"] - t["exit"]) / t["entry"] * 100
            t["rr"] = abs(t["entry"] - t["exit"]) / abs(t["sl"] - t["entry"]) if t["sl"] != t["entry"] else 0
        t["exit_idx"] = t["exit_i"] - t["entry_i"] if t["exit_i"] is not None else 0
        full_trades.append(t)

    total = len(full_trades)
    wins = [t for t in full_trades if t["pnl"] > 0]
    losses = [t for t in full_trades if t["pnl"] <= 0]
    winrate = len(wins) / total * 100

    gross_profit = sum(t["pnl"] for t in wins) if wins else 0
    gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    avg_pnl = np.mean([t["pnl"] for t in full_trades])
    avg_rr = np.mean([t["rr"] for t in full_trades])
    expectancy = (winrate / 100) * (gross_profit / max(len(wins), 1)) - \
                 (1 - winrate / 100) * (gross_loss / max(len(losses), 1))

    cum = np.cumsum([t["pnl"] for t in full_trades])
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0
    sharpe = np.mean([t["pnl"] for t in full_trades]) / max(np.std([t["pnl"] for t in full_trades], ddof=1), 0.001)

    print(f"\n  Total trades:     {total}")
    print(f"  Winrate:          {winrate:.1f}%")
    print(f"  Avg PnL:          {avg_pnl:+.2f}%")
    print(f"  Avg R/R:          {avg_rr:.2f}")
    print(f"  Profit Factor:    {pf:.2f}")
    print(f"  Expectancy:       {expectancy:+.2f}")
    print(f"  Sharpe:           {sharpe:.2f}")
    print(f"  Max DD:           {max_dd:.2f}%")
    print(f"  Total PnL:        {sum(t['pnl'] for t in full_trades):+.2f}%")
    print(f"  Avg trade len:    {np.mean([t['exit_idx'] for t in full_trades]):.1f} candles")

    # direction breakdown
    for d in ["BUY", "SELL"]:
        d_trades = [t for t in full_trades if t["dir"] == d]
        if not d_trades:
            continue
        d_w = [t for t in d_trades if t["pnl"] > 0]
        d_pnl = sum(t["pnl"] for t in d_trades)
        d_pf = sum(t["pnl"] for t in d_w) / max(abs(sum(t["pnl"] for t in d_trades if t["pnl"] <= 0)), 0.001)
        print(f"\n  {d}: {len(d_trades)} trades, wr={len(d_w)/len(d_trades)*100:.0f}%, PnL={d_pnl:+.2f}%, PF={d_pf:.2f}")

    # regime breakdown
    for reg in sorted(set(t["regime"] for t in full_trades)):
        r_trades = [t for t in full_trades if t["regime"] == reg]
        r_w = [t for t in r_trades if t["pnl"] > 0]
        r_pnl = sum(t["pnl"] for t in r_trades)
        print(f"  [{reg}] {len(r_trades)} trades, wr={len(r_w)/len(r_trades)*100:.0f}%, PnL={r_pnl:+.2f}%")

    # each trade
    print(f"\n  DETAIL:")
    for i, t in enumerate(full_trades):
        em = "🟢" if t["pnl"] > 0 else "🔴"
        print(f"  {em} #{i+1} {t['dir']} entry=${t['entry']:.1f} → ${t['exit']:.1f} "
              f"({t['reason']}) pnl={t['pnl']:+.2f}% rr={t['rr']:.2f} "
              f"score={t['score']} [{t['regime']}] {t['exit_idx']}h")

    await exchange_client.close()

if __name__ == "__main__":
    asyncio.run(main())
