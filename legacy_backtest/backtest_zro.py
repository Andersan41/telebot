"""
backtest_zro.py — Run backtest on ZRO/USDT and send results to Telegram.
"""
import asyncio
import sys
import io
import os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
from datetime import datetime

from config.settings import config
from data.exchange_client import exchange_client
from indicators.engine import indicator_engine, IndicatorValues
from strategy.signal_engine import signal_engine, SignalType, SignalResult
from risk.market_regime import RegimeDetector, MarketRegime
from liquidity.sweep import detect_sweeps
from liquidity.order_blocks import detect_order_blocks
from liquidity.fvg import detect_fvg
from market_structure.structure import analyze_structure
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError


def _detect_regime(ind: IndicatorValues, atr_history: list) -> str:
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


def make_regime_obj(ind: IndicatorValues, atr_history: list) -> MarketRegime:
    label = _detect_regime(ind, atr_history)
    atr_pct = sum(1 for a in atr_history if a <= ind.atr) / max(len(atr_history), 1) * 100 if atr_history else 50
    return MarketRegime(regime=label, confidence=0.5, adx=float(ind.adx), atr_percentile=min(atr_pct, 100), ema_spread_trend="stable")


async def run_backtest(symbol: str, tf: str, candle_limit: int) -> str:
    """Run backtest and return formatted results as string."""
    await exchange_client.connect()

    limit = max(candle_limit + 100, 200)
    df = await exchange_client.fetch_ohlcv(symbol, tf, limit=limit)
    if df is None or len(df) < 100:
        return f"❌ Not enough data for {symbol}"

    df = df.iloc[-(candle_limit + 60):] if len(df) > candle_limit + 60 else df

    trades = []
    atr_history = []
    warmup = 80
    in_trade = False
    ct = None

    for i in range(warmup, len(df)):
        window = df.iloc[:i + 1].copy()
        ind = indicator_engine.calculate(window, symbol, tf)
        if ind is None:
            continue
        atr_history.append(float(ind.atr))

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

    if in_trade and ct is not None:
        ct["exit"] = float(df.iloc[-1]["close"])
        ct["exit_i"] = len(df) - 1
        ct["reason"] = "EOB"
        trades.append(ct)

    # Calculate metrics
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

    if not full_trades:
        return f"📊 <b>Backtest: {symbol} {tf}</b>\n\n❌ No trades generated over {len(df)} candles"

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
    total_pnl = sum(t["pnl"] for t in full_trades)

    # Format message
    days = len(df) / 24 if tf == "1h" else len(df) / 6
    period_start = df.index[0].strftime('%Y-%m-%d %H:%M')
    period_end = df.index[-1].strftime('%Y-%m-%d %H:%M')

    msg = f"""📊 <b>BACKTEST: {symbol} {tf}</b>
┌─────────────────────────────────────
│ Период: {period_start} → {period_end}
│ Свечей: {len(df)} ({days:.0f} дн.)
└─────────────────────────────────────

📈 <b>Метрики:</b>
├ Сделок: {total}
├ Винрейт: {winrate:.1f}%
├ Средний PnL: {avg_pnl:+.2f}%
├ Средний R/R: {avg_rr:.2f}
├ Profit Factor: {pf:.2f}
├ Expectancy: {expectancy:+.3f}
├ Макс. просадка: {max_dd:.2f}%
└ Общий PnL: {total_pnl:+.2f}%"""

    # Direction breakdown
    msg += "\n\n📐 <b>По направлениям:</b>"
    for d in ["BUY", "SELL"]:
        d_trades = [t for t in full_trades if t["dir"] == d]
        if not d_trades:
            continue
        d_w = [t for t in d_trades if t["pnl"] > 0]
        d_pnl = sum(t["pnl"] for t in d_trades)
        d_pf = sum(t["pnl"] for t in d_w) / max(abs(sum(t["pnl"] for t in d_trades if t["pnl"] <= 0)), 0.001)
        d_wr = len(d_w) / len(d_trades) * 100
        emoji = "🟢" if d == "BUY" else "🔴"
        msg += f"\n{emoji} {d}: {len(d_trades)} сделок, wr={d_wr:.0f}%, PnL={d_pnl:+.2f}%, PF={d_pf:.2f}"

    # Regime breakdown
    regimes = sorted(set(t["regime"] for t in full_trades))
    if regimes:
        msg += "\n\n🎯 <b>По режимам:</b>"
        for reg in regimes:
            r_trades = [t for t in full_trades if t["regime"] == reg]
            r_w = [t for t in r_trades if t["pnl"] > 0]
            r_pnl = sum(t["pnl"] for t in r_trades)
            r_wr = len(r_w) / len(r_trades) * 100
            msg += f"\n├ [{reg}] {len(r_trades)} сделок, wr={r_wr:.0f}%, PnL={r_pnl:+.2f}%"

    # Trade detail (last 15 trades max)
    show_trades = full_trades[-15:]
    start_idx = len(full_trades) - len(show_trades) + 1
    msg += f"\n\n📝 <b>Последние {len(show_trades)} сделок:</b>"
    for i, t in enumerate(show_trades):
        em = "✅" if t["pnl"] > 0 else "❌"
        msg += f"\n{em} #{start_idx+i} {t['dir']} ${t['entry']:.4f}→${t['exit']:.4f} ({t['reason']}) {t['pnl']:+.2f}% rr={t['rr']:.2f} [{t['regime']}]"

    await exchange_client.close()
    return msg


async def send_to_telegram(text: str):
    """Send message to Telegram channel."""
    channel_id = config.telegram.channel_id
    if not channel_id:
        print("❌ TELEGRAM_CHANNEL_ID not set")
        return

    bot = Bot(token=config.telegram.token)

    # Split if too long (Telegram limit = 4096)
    if len(text) > 4000:
        parts = []
        lines = text.split('\n')
        current = ""
        for line in lines:
            if len(current) + len(line) + 1 > 4000:
                parts.append(current)
                current = line
            else:
                current = current + '\n' + line if current else line
        if current:
            parts.append(current)

        for part in parts:
            try:
                await bot.send_message(chat_id=channel_id, text=part, parse_mode=ParseMode.HTML)
                await asyncio.sleep(1)
            except TelegramError as e:
                print(f"❌ Telegram error: {e}")
                # Try without HTML
                try:
                    await bot.send_message(chat_id=channel_id, text=part)
                except Exception as e2:
                    print(f"❌ Fallback send failed: {e2}")
    else:
        try:
            await bot.send_message(chat_id=channel_id, text=text, parse_mode=ParseMode.HTML)
            print("✅ Sent to Telegram channel")
        except TelegramError as e:
            print(f"❌ Telegram error: {e}")
            try:
                await bot.send_message(chat_id=channel_id, text=text)
                print("✅ Sent (plain text)")
            except Exception as e2:
                print(f"❌ Fallback send failed: {e2}")


async def main():
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "ZRO/USDT"
    tf = (sys.argv[2] if len(sys.argv) > 2 else "1h").lower()
    candle_limit = int(sys.argv[3]) if len(sys.argv) > 3 else 500
    market_type = (sys.argv[4] if len(sys.argv) > 4 else "").lower()

    if "/" not in symbol and symbol.endswith("USDT"):
        symbol = symbol[:-4] + "/USDT"
    elif "/" not in symbol:
        symbol += "/USDT"

    # Override market_type if specified (e.g. "future" for HYPE, "spot" for LIT)
    if market_type in ("future", "futures"):
        config.exchange.market_type = "future"
    elif market_type == "spot":
        config.exchange.market_type = "spot"

    print(f"Running backtest: {symbol} {tf} ({candle_limit} candles, market={config.exchange.market_type})...")
    result_text = await run_backtest(symbol, tf, candle_limit)

    print("\n" + result_text)

    print("\nSending to Telegram...")
    await send_to_telegram(result_text)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
