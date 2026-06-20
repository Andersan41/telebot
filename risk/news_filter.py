"""
risk/news_filter.py — Фильтр новостных событий (Task 5).

Блокирует новые сигналы во время окна вокруг high-impact макро-событий
(FOMC, CPI, NFP, PCE, Powell speech и т.п.).

Статус: ИНТЕРФЕЙС + TODO-ЗАГЛУШКИ.
Для полноценной работы требуется внешний источник данных (API календаря
экономических событий), которого в проекте сейчас нет.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import config.settings as settings


@dataclass
class MacroEvent:
    """Одно макро-событие."""
    name: str
    timestamp: datetime
    impact: str  # "high", "medium", "low"
    currency: str = "USD"


@dataclass
class NewsBlockResult:
    """Результат проверки новостного фильтра."""
    blocked: bool
    reason: str = ""
    event_name: str = ""


# ─── Кэш событий ──────────────────────────────────────────────────────────
_events_cache: list[MacroEvent] = []
_cache_ts: Optional[datetime] = None
_CACHE_TTL_SECONDS = 300  # 5 минут


def _is_cache_valid() -> bool:
    global _cache_ts
    if _cache_ts is None:
        return False
    now = datetime.now(timezone.utc)
    return (now - _cache_ts).total_seconds() < _CACHE_TTL_SECONDS


async def fetch_macro_events() -> list[MacroEvent]:
    """Загрузить макро-события из внешнего источника.

    TODO: Интегрировать реальный API (например):
    - investing.com/economic-calendar/
    - forexfactory.com/calendar/
    - TradingEconomics API
    - CoinMarketCal API

    Сейчас возвращает пустой список — фильтр отключён.
    """
    # TODO: реализовать загрузку из API
    # Пример структуры ответа:
    # events = []
    # for raw in api_response:
    #     events.append(MacroEvent(
    #         name=raw["name"],
    #         timestamp=datetime.fromisoformat(raw["date"]),
    #         impact=raw["impact"],
    #         currency=raw.get("currency", "USD"),
    #     ))
    # return events
    return []


def _cache_events(events: list[MacroEvent]) -> None:
    global _events_cache, _cache_ts
    _events_cache = events
    _cache_ts = datetime.now(timezone.utc)


async def check_news_block(
    direction: str,
    entry_price: float = 0.0,
) -> NewsBlockResult:
    """Проверить, не попадает ли сигнал в окно блокировки вокруг события.

    Args:
        direction: "BUY" или "SELL"
        entry_price: цена входа (для логирования)

    Returns:
        NewsBlockResult с blocked=True если есть активное high-impact событие
    """
    cfg = settings.config

    # Если фильтр отключён — пропускаем
    if not getattr(cfg.risk, "news_filter_enabled", False):
        return NewsBlockResult(blocked=False)

    if not _is_cache_valid():
        events = await fetch_macro_events()
        _cache_events(events)

    now = datetime.now(timezone.utc)
    before_min = getattr(cfg, "news_block_before_minutes", 60)
    after_min = getattr(cfg, "news_block_after_minutes", 30)

    for event in _events_cache:
        if event.impact != "high":
            continue

        event_start = event.timestamp - __import__("datetime").timedelta(minutes=before_min)
        event_end = event.timestamp + __import__("datetime").timedelta(minutes=after_min)

        if event_start <= now <= event_end:
            return NewsBlockResult(
                blocked=True,
                reason=(
                    f"High-impact news: {event.name} "
                    f"(window: {event_start.strftime('%H:%M')} — {event_end.strftime('%H:%M')} UTC)"
                ),
                event_name=event.name,
            )

    return NewsBlockResult(blocked=False)
