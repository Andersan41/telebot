"""
context/analyzer.py — Сбор данных из источников в единый объект ContextSnapshot.
"""
import json
import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, List, Any
from loguru import logger

from config.settings import config
from context.fetcher import context_fetcher


@dataclass
class ContextSnapshot:
    """Результат сбора контекстных данных."""
    symbol: str
    timestamp: datetime

    # Alternative.me Fear & Greed
    fear_greed_value: Optional[int] = None
    fear_greed_label: Optional[str] = None

    # CoinGecko
    price_change_24h: Optional[float] = None
    price_change_7d: Optional[float] = None
    volume_change_24h: Optional[float] = None
    market_cap_rank: Optional[int] = None
    is_trending: bool = False

    # Binance Futures
    funding_rate: Optional[float] = None
    open_interest_delta: Optional[float] = None
    long_short_ratio: Optional[float] = None

    # Новости
    news_sentiment_score: Optional[float] = None
    news_count: int = 0

    errors: list = field(default_factory=list)

    def to_json(self) -> str:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return json.dumps(d, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "ContextSnapshot":
        d = json.loads(json_str)
        d["timestamp"] = datetime.fromisoformat(d["timestamp"])
        return cls(**d)


class ContextEngine:
    """Собирает контекстные данные из всех источников."""

    def __init__(self):
        self._fear_greed_cache: tuple = (None, None)
        self._trending_cache: tuple = (None, None)

    async def get_snapshot(self, symbol: str) -> ContextSnapshot:
        """Собирает все доступные контекстные данные для символа."""
        snapshot = ContextSnapshot(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
        )
        # Аккумулятор news_sentiment: (score, count) от каждого источника.
        # Объединяем в конце, чтобы не зависеть от порядка завершения корутин.
        news_collected: list[tuple[float, int]] = []

        coin_id = config.coingecko_symbol_map.get(symbol)

        tasks = [
            self._safe_fetch("Fear & Greed", self._fetch_fear_greed, snapshot),
            self._safe_fetch("CoinGecko", self._fetch_coingecko, snapshot, coin_id),
            self._safe_fetch("Trending", self._fetch_trending, snapshot),
            self._safe_fetch("Funding Rate", self._fetch_funding_rate, snapshot, symbol),
            self._safe_fetch("OI", self._fetch_open_interest, snapshot, symbol),
            self._safe_fetch("Long/Short", self._fetch_long_short_ratio, snapshot, symbol),
        ]

        if config.cryptopanic_api_key:
            tasks.append(
                self._safe_fetch("CryptoPanic", self._fetch_cryptopanic, snapshot, symbol, news_collected)
            )

        tasks.append(self._safe_fetch("RSS", self._fetch_rss, snapshot, symbol, news_collected))

        await asyncio.gather(*tasks, return_exceptions=True)

        # Свернём накопленные оценки новостей в один итоговый score, взвешенный
        # по количеству статей. Если оба источника промолчали — поле остаётся None.
        if news_collected:
            total_count = sum(c for _, c in news_collected) or 1
            snapshot.news_sentiment_score = sum(s * c for s, c in news_collected) / total_count
            snapshot.news_count = sum(c for _, c in news_collected)

        return snapshot

    async def _safe_fetch(self, name: str, coro_func, snapshot: ContextSnapshot, *args):
        try:
            await coro_func(snapshot, *args)
        except Exception as e:
            snapshot.errors.append(f"{name}: {e}")
            logger.debug(f"Context fetch error ({name}): {e}")

    async def _fetch_fear_greed(self, snapshot: ContextSnapshot):
        data = await context_fetcher.fetch_fear_greed()
        if data:
            snapshot.fear_greed_value = data["value"]
            snapshot.fear_greed_label = data["label"]

    async def _fetch_coingecko(self, snapshot: ContextSnapshot, coin_id: Optional[str]):
        if not coin_id:
            return
        data = await context_fetcher.fetch_coingecko(coin_id)
        if data:
            snapshot.price_change_24h = data.get("price_change_24h")
            snapshot.price_change_7d = data.get("price_change_7d")
            snapshot.volume_change_24h = data.get("total_volume")
            snapshot.market_cap_rank = data.get("market_cap_rank")

    async def _fetch_trending(self, snapshot: ContextSnapshot):
        coins = await context_fetcher.fetch_trending()
        base_currency = self._get_base_currency(snapshot.symbol)
        snapshot.is_trending = base_currency in coins

    async def _fetch_funding_rate(self, snapshot: ContextSnapshot, symbol: str):
        rate = await context_fetcher.fetch_funding_rate(symbol)
        if rate is not None:
            snapshot.funding_rate = rate

    async def _fetch_open_interest(self, snapshot: ContextSnapshot, symbol: str):
        data = await context_fetcher.fetch_open_interest(symbol)
        if data:
            snapshot.open_interest_delta = data.get("open_interest_delta")

    async def _fetch_long_short_ratio(self, snapshot: ContextSnapshot, symbol: str):
        ratio = await context_fetcher.fetch_long_short_ratio(symbol)
        if ratio is not None:
            snapshot.long_short_ratio = ratio

    async def _fetch_cryptopanic(
        self, snapshot: ContextSnapshot, symbol: str, collected: list[tuple[float, int]]
    ):
        data = await context_fetcher.fetch_cryptopanic(symbol)
        if data and data.get("count"):
            collected.append((float(data["score"]), int(data["count"])))

    async def _fetch_rss(
        self, snapshot: ContextSnapshot, symbol: str, collected: list[tuple[float, int]]
    ):
        data = await context_fetcher.fetch_rss_news(symbol)
        if data and data.get("count"):
            collected.append((float(data["score"]), int(data["count"])))

    def _get_base_currency(self, symbol: str) -> str:
        return symbol.split("/")[0]


# Singleton
context_engine = ContextEngine()
