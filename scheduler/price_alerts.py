"""
scheduler/price_alerts.py — Фоновая проверка веб-алертов на цену.

Вкладка Alerts в дашборде создаёт строку в `price_alerts`; цикл раз в
PRICE_ALERT_CHECK_SECONDS сверяет текущую цену с уровнем и при касании
шлёт админу уведомление. One-shot: после успешной отправки алерт гаснет
(active=False, triggered_at/triggered_price фиксируются).

Интервал 15s -> 1 ticker-запрос на уникальный символ за тик
(ccxt rate-limit + Semaphore(3) в exchange_client).
"""
import asyncio
import os
import time
from loguru import logger

from bot.notifier import send_price_alert
from data.exchange_client import exchange_client
from storage.database import db

PRICE_ALERT_CHECK_SECONDS = int(os.getenv("PRICE_ALERT_CHECK_SECONDS", "15"))

# Анти-спам по упавшему тикеру: N неудач подряд -> cooldown на символ
# (тот же паттерн, что в scheduler/outcome_tracker.py)
_FAIL_THRESHOLD = 3
_COOLDOWN_SECONDS = 600
_fail_counts: dict = {}
_cooldowns: dict = {}  # symbol -> time.monotonic() момента окончания cooldown


def _is_triggered(alert, price: float) -> bool:
    """Условие срабатывания по direction."""
    if alert.direction == "ABOVE":
        return price >= alert.price
    if alert.direction == "BELOW":
        return price <= alert.price
    # ANY: пересечение уровнем (prev и текущая цена по разные стороны)
    # либо точное касание. Гэп через уровень тоже считается пересечением.
    if price == alert.price:
        return True
    if alert.prev_price is None:
        return False
    return (alert.prev_price - alert.price) * (price - alert.price) < 0


async def check_price_alerts() -> int:
    """Проверка всех активных алертов. Возвращает число сработавших."""
    alerts = await db.get_price_alerts(active_only=True)
    if not alerts:
        return 0

    now = time.monotonic()
    prices: dict = {}
    for symbol in {a.symbol for a in alerts}:
        if _cooldowns.get(symbol, 0) > now:
            prices[symbol] = None
            continue
        price = None
        if exchange_client._exchange is not None:
            try:
                price = await exchange_client.fetch_ticker_price(symbol)
            except Exception as e:
                logger.warning(f"Price alert ticker fetch failed for {symbol}: {e}")
        prices[symbol] = price
        if price is None:
            _fail_counts[symbol] = _fail_counts.get(symbol, 0) + 1
            if _fail_counts[symbol] >= _FAIL_THRESHOLD:
                _cooldowns[symbol] = now + _COOLDOWN_SECONDS
                logger.warning(
                    f"Price alerts: {symbol} cooldown {_COOLDOWN_SECONDS}s "
                    f"after {_fail_counts[symbol]} failed ticker fetches"
                )
        else:
            _fail_counts.pop(symbol, None)

    triggered = 0
    for alert in alerts:
        price = prices.get(alert.symbol)
        if price is None:
            continue
        if _is_triggered(alert, price):
            try:
                await send_price_alert(
                    alert.symbol, alert.price, price, alert.direction
                )
            except Exception as e:
                # не гасим алерт без подтверждённой отправки — повтор на
                # следующем тике (15s) и так далее, пока Telegram не примет
                logger.warning(
                    f"Price alert notify failed for {alert.symbol}: {e}"
                )
                continue
            await db.trigger_price_alert(alert.id, price)
            triggered += 1
            logger.info(
                f"Price alert #{alert.id} {alert.symbol} {alert.direction} "
                f"target={alert.price} current={price}"
            )
        elif alert.direction == "ANY":
            # prev нужен только для ANY (crossing); ABOVE/BELOW — без записи
            await db.update_price_alert_prev(alert.id, price)
    return triggered


async def price_alert_loop() -> None:
    """Фоновый цикл (см. outcome_tracker_loop — тот же паттерн)."""
    while True:
        try:
            n = await check_price_alerts()
            if n:
                logger.info(f"Price alerts triggered: {n}")
        except Exception as e:
            logger.warning(f"Price alert check failed: {e}")
        await asyncio.sleep(PRICE_ALERT_CHECK_SECONDS)
