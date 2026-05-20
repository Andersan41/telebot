"""
bot/rate_limit.py — Простой rate limiter для Telegram-команд (T3.3).

Параметры rate limiting берутся из config.rate_limit (hot-reload safe).
"""
from collections import defaultdict
from aiolimiter import AsyncLimiter
from config.settings import config

_limiters: dict[int, AsyncLimiter] = {}


def _create_limiter() -> AsyncLimiter:
    """Создать лимитер с текущими параметрами из config."""
    return AsyncLimiter(max_rate=config.rate_limit.max_rate, time_period=config.rate_limit.time_period)


def get_limiter(user_id: int) -> AsyncLimiter:
    if user_id not in _limiters:
        _limiters[user_id] = _create_limiter()
    return _limiters[user_id]
