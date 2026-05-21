"""
scheduler/outcome_tracker.py — Фоновый трекинг закрытия сигналов (SL/TP).
"""
import asyncio
import os
from datetime import datetime, timezone, timedelta
from loguru import logger
from data.exchange_client import exchange_client
from storage.database import db, Signal


OUTCOME_CHECK_INTERVAL_SECONDS = int(
    os.getenv("OUTCOME_CHECK_INTERVAL_SECONDS", "300")
)
OUTCOME_TTL_DAYS = int(os.getenv("OUTCOME_TTL_DAYS", "7"))


async def check_open_outcomes() -> None:
    outcomes = await db.get_open_outcomes()
    if not outcomes:
        return
    logger.debug(f"Checking {len(outcomes)} open outcomes")
    for outcome in outcomes:
        signal = await db.get_signal(outcome.signal_id)
        if signal is None:
            continue
        # Просроченный сигнал → EXPIRED
        age = datetime.now(timezone.utc) - signal.created_at.replace(
            tzinfo=timezone.utc
        )
        if age > timedelta(days=OUTCOME_TTL_DAYS):
            await db.close_outcome(
                outcome.id, "EXPIRED",
                close_price=signal.close_price, pnl_pct=0.0,
            )
            continue
        # Текущая цена через 1m свечу (с повторными попытками при сетевых ошибках)
        df = None
        for attempt in range(3):
            df = await exchange_client.fetch_ohlcv(signal.symbol, "1m", limit=2)
            if df is not None:
                break
            if attempt < 2:
                await asyncio.sleep(5 * (attempt + 1))
        if df is None or df.empty:
            continue
        current = float(df["close"].iloc[-1])
        hit_tp = (
            signal.signal_type == "BUY" and signal.tp and current >= signal.tp
        ) or (
            signal.signal_type == "SELL" and signal.tp and current <= signal.tp
        )
        hit_sl = (
            signal.signal_type == "BUY" and signal.sl and current <= signal.sl
        ) or (
            signal.signal_type == "SELL" and signal.sl and current >= signal.sl
        )
        if hit_tp:
            pnl = (current - signal.close_price) / signal.close_price * 100
            if signal.signal_type == "SELL":
                pnl = -pnl
            await db.close_outcome(outcome.id, "HIT_TP", current, pnl)
            logger.info(f"Outcome HIT_TP: signal_id={signal.id} pnl={pnl:.2f}%")
        elif hit_sl:
            pnl = (current - signal.close_price) / signal.close_price * 100
            if signal.signal_type == "SELL":
                pnl = -pnl
            await db.close_outcome(outcome.id, "HIT_SL", current, pnl)
            logger.info(f"Outcome HIT_SL: signal_id={signal.id} pnl={pnl:.2f}%")


async def outcome_tracker_loop() -> None:
    while True:
        try:
            await check_open_outcomes()
        except Exception as e:
            logger.warning(f"Outcome tracker error: {e}")
        await asyncio.sleep(OUTCOME_CHECK_INTERVAL_SECONDS)
