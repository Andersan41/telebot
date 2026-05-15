"""
bot/rate_limit.py — Простой rate limiter для Telegram-команд (T3.3).

5 событий в 10 секунд на user_id. Limiter'ы создаются лениво и живут
пока работает процесс; для prod добавь LRU-ограничение (~10k юзеров).
"""
from collections import defaultdict
from aiolimiter import AsyncLimiter

_limiters: dict[int, AsyncLimiter] = defaultdict(
    lambda: AsyncLimiter(max_rate=5, time_period=10)
)


def get_limiter(user_id: int) -> AsyncLimiter:
    return _limiters[user_id]
