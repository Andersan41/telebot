"""
scheduler/scanner.py — Основной сканер рынка.
Логика: проверяем сигнал на 1H/4H, подтверждаем на 15M.
"""
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional
from loguru import logger
from config.settings import config
from data.exchange_client import exchange_client
from indicators.engine import indicator_engine, IndicatorValues
from strategy.signal_engine import signal_engine, SignalResult, SignalType
from storage.database import db

# Словарь для cooldown: {symbol_timeframe: last_signal_time}
_last_signal_time: dict[str, datetime] = {}


def _is_cooldown_active(symbol: str, timeframe: str) -> bool:
    key = f"{symbol}_{timeframe}"
    last = _last_signal_time.get(key)
    if last is None:
        return False
    delta = datetime.now(timezone.utc) - last
    return delta < timedelta(minutes=config.signal_cooldown_minutes)


def _set_cooldown(symbol: str, timeframe: str):
    key = f"{symbol}_{timeframe}"
    _last_signal_time[key] = datetime.now(timezone.utc)


async def _get_indicators(symbol: str, timeframe: str) -> Optional[IndicatorValues]:
    df = await exchange_client.fetch_ohlcv(symbol, timeframe, limit=config.trading.candles_limit)
    if df is None:
        return None
    return indicator_engine.calculate(df, symbol, timeframe)


async def scan_symbol(symbol: str, timeframe: str, notify_callback) -> Optional[SignalResult]:
    """
    Сканируем один символ на одном таймфрейме.
    Если есть сигнал — подтверждаем на 15M.
    """
    if _is_cooldown_active(symbol, timeframe):
        logger.debug(f"Cooldown active: {symbol} {timeframe}")
        return None

    # Шаг 1: Основной таймфрейм
    ind = await _get_indicators(symbol, timeframe)
    if ind is None:
        return None

    result = signal_engine.evaluate(ind)
    if not result.is_actionable:
        logger.debug(f"No signal: {symbol} {timeframe}")
        return None

    logger.info(f"Signal candidate: {result.signal} {symbol} {timeframe} (score={result.score})")

    # Шаг 2: Подтверждение на 15M
    confirm_tf = config.trading.confirm_timeframe
    if confirm_tf != timeframe:
        ind_confirm = await _get_indicators(symbol, confirm_tf)
        if ind_confirm is not None:
            confirm_result = signal_engine.evaluate(ind_confirm)
            if confirm_result.signal != result.signal:
                logger.info(
                    f"Signal NOT confirmed on {confirm_tf}: "
                    f"main={result.signal}, confirm={confirm_result.signal} — {symbol}"
                )
                return None
            logger.info(f"Signal CONFIRMED on {confirm_tf}: {result.signal} {symbol}")
            result.reasons.append(f"✅ Подтверждение на {confirm_tf}")
        else:
            logger.warning(f"Could not get {confirm_tf} data for {symbol}, skipping confirmation")

    # Шаг 3: Сохраняем в БД
    await db.save_signal(
        symbol=result.symbol,
        timeframe=result.timeframe,
        signal_type=result.signal.value,
        close_price=result.close,
        sl=result.sl,
        tp=result.tp,
        score=result.score,
        reasons=result.reasons,
        confirmed=True,
    )

    # Шаг 4: Cooldown
    _set_cooldown(symbol, timeframe)

    # Шаг 5: Уведомляем
    await notify_callback(result)

    return result


async def run_scan_cycle(notify_callback):
    """
    Один цикл сканирования — обходим все символы и таймфреймы параллельно.
    """
    symbols = config.trading.symbols
    timeframes = config.trading.primary_timeframes

    logger.info(f"Starting scan: {len(symbols)} symbols × {timeframes}")

    tasks = []
    for symbol in symbols:
        for tf in timeframes:
            tasks.append(scan_symbol(symbol, tf, notify_callback))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    signals_found = sum(1 for r in results if isinstance(r, SignalResult) and r is not None)
    logger.info(f"Scan complete. Signals found: {signals_found}/{len(tasks)}")
