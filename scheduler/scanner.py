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
from context.analyzer import context_engine, ContextSnapshot
from context.scorer import context_scorer, ContextVerdict

# Словарь для cooldown: {symbol_timeframe: last_signal_time}
_last_signal_time: dict[str, datetime] = {}

# Порядок вердиктов от худшего к лучшему — используется для CONTEXT_MIN_VERDICT.
_VERDICT_RANK = {"BLOCKED": 0, "CONFLICTED": 1, "WEAK": 2, "CONFIRMED": 3}


def _verdict_passes_min(verdict: str) -> bool:
    """True, если фактический verdict ≥ настроенного CONTEXT_MIN_VERDICT.

    Пустая строка / неизвестное значение → гейт отключён.
    """
    min_v = (config.context_min_verdict or "").strip().upper()
    if min_v not in _VERDICT_RANK:
        return True
    return _VERDICT_RANK.get(verdict, 0) >= _VERDICT_RANK[min_v]


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
    entry_price: Optional[float] = None
    confirmed_on_lower_tf = False
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
            entry_price = ind_confirm.close
            confirmed_on_lower_tf = True
            logger.info(f"Signal CONFIRMED on {confirm_tf}: {result.signal} {symbol}")
            result.reasons.append(f"✅ Подтверждение на {confirm_tf}")
        else:
            logger.warning(f"Could not get {confirm_tf} data for {symbol}, skipping confirmation")
            entry_price = result.close
    else:
        entry_price = result.close

    # Шаг 3: Контекстное обогащение
    context_verdict: Optional[ContextVerdict] = None
    if config.context_enabled:
        try:
            snapshot = await asyncio.wait_for(
                context_engine.get_snapshot(symbol),
                timeout=10.0,
            )
            context_verdict = context_scorer.score(result.signal.value, snapshot)

            if config.context_block_on_blocked and context_verdict.verdict == "BLOCKED":
                logger.info(
                    f"Signal BLOCKED by context: {result.signal} {symbol} {timeframe} "
                    f"(score={context_verdict.score:.2f})"
                )
                return None

            if not _verdict_passes_min(context_verdict.verdict):
                logger.info(
                    f"Signal rejected by CONTEXT_MIN_VERDICT={config.context_min_verdict}: "
                    f"actual={context_verdict.verdict} for {result.signal} {symbol} {timeframe}"
                )
                return None

            logger.info(
                f"Context verdict: {context_verdict.verdict} "
                f"(score={context_verdict.score:.2f}) for {result.signal} {symbol}"
            )
        except asyncio.TimeoutError:
            logger.warning(f"Context enrichment timeout for {symbol}")
        except Exception as e:
            logger.warning(f"Context enrichment error for {symbol}: {e}")

    # Сохраняем контекст в БД
    if context_verdict is not None:
        try:
            await db.save_context_snapshot(
                symbol=symbol,
                signal_id=None,
                verdict=context_verdict.verdict,
                confidence=context_verdict.confidence,
                score=context_verdict.score,
                fear_greed=context_verdict.snapshot.fear_greed_value if context_verdict.snapshot else None,
                funding_rate=context_verdict.snapshot.funding_rate if context_verdict.snapshot else None,
                long_short_ratio=context_verdict.snapshot.long_short_ratio if context_verdict.snapshot else None,
                open_interest_delta=context_verdict.snapshot.open_interest_delta if context_verdict.snapshot else None,
                news_sentiment=context_verdict.snapshot.news_sentiment_score if context_verdict.snapshot else None,
                raw_json=context_verdict.snapshot.to_json() if context_verdict.snapshot else None,
            )
        except Exception as e:
            logger.warning(f"Failed to save context snapshot: {e}")

    # Шаг 4: Сохраняем сигнал в БД
    saved_signal = await db.save_signal(
        symbol=result.symbol,
        timeframe=result.timeframe,
        signal_type=result.signal.value,
        close_price=result.close,
        sl=result.sl,
        tp=result.tp,
        score=result.score,
        reasons=result.reasons,
        confirmed=confirmed_on_lower_tf,
    )

    # Сохраняем связь сигнала с контекстом
    if context_verdict is not None:
        try:
            await db.save_context_snapshot(
                symbol=symbol,
                signal_id=saved_signal.id,
                verdict=context_verdict.verdict,
                confidence=context_verdict.confidence,
                score=context_verdict.score,
                fear_greed=context_verdict.snapshot.fear_greed_value if context_verdict.snapshot else None,
                funding_rate=context_verdict.snapshot.funding_rate if context_verdict.snapshot else None,
                long_short_ratio=context_verdict.snapshot.long_short_ratio if context_verdict.snapshot else None,
                open_interest_delta=context_verdict.snapshot.open_interest_delta if context_verdict.snapshot else None,
                news_sentiment=context_verdict.snapshot.news_sentiment_score if context_verdict.snapshot else None,
                raw_json=context_verdict.snapshot.to_json() if context_verdict.snapshot else None,
            )
        except Exception as e:
            logger.warning(f"Failed to save context snapshot with signal link: {e}")

    # Шаг 5: Cooldown
    _set_cooldown(symbol, timeframe)

    # Шаг 6: Уведомляем
    result.entry_price = entry_price
    await notify_callback(result, context_verdict)

    return result


async def run_scan_cycle(notify_callback, timeframes: Optional[list[str]] = None):
    """
    Один цикл сканирования — обходим все символы и таймфреймы параллельно.

    `timeframes=None` → берёт `config.trading.primary_timeframes` целиком
    (поведение по умолчанию для ручного запуска /scan).
    Cron-джоб может передавать конкретный список, чтобы не дублировать
    сканирование других ТФ.
    """
    symbols = config.trading.symbols
    tfs = timeframes if timeframes is not None else config.trading.primary_timeframes

    logger.info(f"Starting scan: {len(symbols)} symbols × {tfs}")

    tasks = []
    for symbol in symbols:
        for tf in tfs:
            tasks.append(scan_symbol(symbol, tf, notify_callback))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    signals_found = sum(1 for r in results if isinstance(r, SignalResult) and r is not None)
    logger.info(f"Scan complete. Signals found: {signals_found}/{len(tasks)}")
