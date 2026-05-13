"""
context/fetcher.py — Асинхронный клиент для получения данных из открытых источников.
"""
import re
import html
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from loguru import logger

import aiohttp
import feedparser
from config.settings import config


class ContextFetcher:
    """Асинхронный клиент для опроса источников данных."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._timeout = aiohttp.ClientTimeout(total=8)
        self._rss_cache: Dict[str, tuple] = {}
        self._fng_cache: tuple = (None, None)
        self._trending_cache: tuple = (None, None)
        # Последнее наблюдённое значение OI per-symbol — для расчёта дельты.
        # In-memory: после рестарта первый расчёт даст delta=0.0.
        self._last_oi: Dict[str, float] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def _get_base_currency(self, symbol: str) -> str:
        return symbol.split("/")[0]

    def _is_cached(self, cache_entry: tuple, ttl: int) -> bool:
        if cache_entry[0] is None:
            return False
        age = datetime.now(timezone.utc) - cache_entry[1]
        return age.total_seconds() < ttl

    # --- 1. Fear & Greed Index ---

    async def fetch_fear_greed(self) -> Optional[Dict[str, Any]]:
        """Alternative.me Fear & Greed Index."""
        if self._is_cached(self._fng_cache, 3600):
            return self._fng_cache[0]

        try:
            session = await self._get_session()
            url = "https://api.alternative.me/fng/?limit=1"
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"Fear & Greed API returned status {resp.status}")
                    return None
                data = await resp.json()
                result = data.get("data", [{}])[0]
                value = int(result.get("value", 0))
                label = result.get("value_classification", "Unknown")
                self._fng_cache = ({"value": value, "label": label}, datetime.now(timezone.utc))
                logger.debug(f"Fear & Greed: {value} ({label})")
                return {"value": value, "label": label}
        except Exception as e:
            logger.warning(f"Error fetching Fear & Greed: {e}")
            return None

    # --- 2. CoinGecko market data ---

    async def fetch_coingecko(self, coin_id: str) -> Optional[Dict[str, Any]]:
        """CoinGecko market data for a coin."""
        try:
            session = await self._get_session()
            url = (
                f"https://api.coingecko.com/api/v3/coins/{coin_id}"
                f"?localization=false&tickers=false&market_data=true"
                f"&community_data=false&developer_data=false"
            )
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"CoinGecko API returned status {resp.status} for {coin_id}")
                    return None
                data = await resp.json()
                market_data = data.get("market_data", {})
                result = {
                    "price_change_24h": market_data.get("price_change_percentage_24h"),
                    "price_change_7d": market_data.get("price_change_percentage_7d"),
                    "total_volume": market_data.get("total_volume", {}).get("usd"),
                    "market_cap_rank": market_data.get("market_cap_rank"),
                }
                logger.debug(f"CoinGecko {coin_id}: rank={result['market_cap_rank']}")
                return result
        except Exception as e:
            logger.warning(f"Error fetching CoinGecko for {coin_id}: {e}")
            return None

    # --- 3. CoinGecko trending coins ---

    async def fetch_trending(self) -> list:
        """CoinGecko trending coins."""
        if self._is_cached(self._trending_cache, 1800):
            return self._trending_cache[0]

        try:
            session = await self._get_session()
            url = "https://api.coingecko.com/api/v3/search/trending"
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"CoinGecko trending returned status {resp.status}")
                    return []
                data = await resp.json()
                coins = []
                for item in data.get("coins", [])[:7]:
                    coin = item.get("item", {})
                    coins.append(coin.get("symbol", "").upper())
                self._trending_cache = (coins, datetime.now(timezone.utc))
                logger.debug(f"CoinGecko trending: {coins}")
                return coins
        except Exception as e:
            logger.warning(f"Error fetching CoinGecko trending: {e}")
            return []

    # --- 4. Binance Funding Rate ---

    async def fetch_funding_rate(self, symbol: str) -> Optional[float]:
        """Binance USDT-margined futures funding rate via direct HTTP.

        ccxt-spot не поддерживает futures funding, а futures-инстанс отдельно
        не создаётся — берём публичный premiumIndex с fapi.binance.com тем же
        способом, что и open interest / long-short ratio.
        """
        try:
            session = await self._get_session()
            binance_symbol = symbol.replace("/", "")
            url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={binance_symbol}"
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"Funding rate API returned status {resp.status} for {symbol}")
                    return None
                data = await resp.json()
                if "lastFundingRate" not in data:
                    return None
                result = float(data["lastFundingRate"])
                logger.debug(f"Funding rate {symbol}: {result:.6f}")
                return result
        except Exception as e:
            logger.warning(f"Error fetching funding rate for {symbol}: {e}")
            return None

    # --- 5. Binance Open Interest ---

    async def fetch_open_interest(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Binance Open Interest via direct HTTP.

        Возвращает текущее абсолютное значение и % изменение относительно
        предыдущего вызова для того же символа. На первом вызове delta=0.0
        (предыдущее значение неизвестно).
        """
        try:
            session = await self._get_session()
            binance_symbol = symbol.replace("/", "")
            url = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={binance_symbol}"
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"Open Interest API returned status {resp.status}")
                    return None
                data = await resp.json()
                current = float(data.get("openInterest", 0))
                previous = self._last_oi.get(symbol)
                if previous and previous > 0:
                    delta_pct = (current - previous) / previous * 100.0
                else:
                    delta_pct = 0.0
                self._last_oi[symbol] = current
                result = {
                    "open_interest": current,
                    "open_interest_delta": delta_pct,
                    "timestamp": datetime.fromtimestamp(
                        data.get("time", 0) / 1000, tz=timezone.utc
                    ),
                }
                logger.debug(f"OI {symbol}: {current} (Δ {delta_pct:+.2f}%)")
                return result
        except Exception as e:
            logger.warning(f"Error fetching OI for {symbol}: {e}")
            return None

    # --- 6. Binance Long/Short Ratio ---

    async def fetch_long_short_ratio(self, symbol: str) -> Optional[float]:
        """Binance global Long/Short Account Ratio."""
        try:
            session = await self._get_session()
            binance_symbol = symbol.replace("/", "")
            url = (
                f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
                f"?symbol={binance_symbol}&period=1h&limit=1"
            )
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"Long/Short Ratio API returned status {resp.status}")
                    return None
                data = await resp.json()
                if data:
                    ratio = float(data[0].get("longShortRatio", 0))
                    logger.debug(f"Long/Short ratio {symbol}: {ratio}")
                    return ratio
                return None
        except Exception as e:
            logger.warning(f"Error fetching long/short ratio for {symbol}: {e}")
            return None

    # --- 7. CryptoPanic news ---

    async def fetch_cryptopanic(self, symbol: str) -> Optional[Dict[str, Any]]:
        """CryptoPanic news sentiment (requires API key)."""
        if not config.cryptopanic_api_key:
            return None

        base_currency = self._get_base_currency(symbol)
        try:
            session = await self._get_session()
            url = (
                f"https://cryptopanic.com/api/v1/posts/"
                f"?auth_token={config.cryptopanic_api_key}"
                f"&currencies={base_currency}"
                f"&filter=important&public=true"
            )
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"CryptoPanic API returned status {resp.status}")
                    return None
                data = await resp.json()
                posts = data.get("results", [])
                positive = 0
                negative = 0
                for post in posts:
                    votes = post.get("votes", {})
                    pos = votes.get("positive", 0)
                    neg = votes.get("negative", 0)
                    if pos > neg:
                        positive += 1
                    elif neg > pos:
                        negative += 1
                total = positive + negative
                if total == 0:
                    score = 0.0
                else:
                    score = (positive - negative) / total
                logger.debug(f"CryptoPanic {symbol}: score={score:.2f} (pos={positive}, neg={negative})")
                return {"score": score, "count": len(posts), "positive": positive, "negative": negative}
        except Exception as e:
            logger.warning(f"Error fetching CryptoPanic for {symbol}: {e}")
            return None

    # --- 8. RSS feeds ---

    async def fetch_rss_news(self, symbol: str) -> Optional[Dict[str, Any]]:
        """RSS news from CoinDesk and Cointelegraph."""
        base_currency = self._get_base_currency(symbol)

        # Check cache
        cache_key = f"rss_{base_currency}"
        if self._is_cached(self._rss_cache.get(cache_key, (None, None)), 300):
            return self._rss_cache.get(cache_key, (None, None))[0]

        negative_words = [
            "hack", "crash", "ban", "lawsuit", "exploit", "fraud", "scam",
            "liquidation", "sec", "charge", "sued", "fine", "collapse",
            "bankruptcy", "rug", "pump", "dump",
        ]
        positive_words = [
            "partnership", "launch", "upgrade", "adoption", "etf", "approval",
            "listing", "integration", "milestone", "record", "growth",
            "bullish", "surge", "rally", "high", "all-time",
        ]

        try:
            session = await self._get_session()
            rss_urls = [
                "https://www.coindesk.com/arc/outboundfeeds/rss/",
                "https://cointelegraph.com/rss",
            ]
            positive_count = 0
            negative_count = 0
            total_articles = 0

            for url in rss_urls:
                try:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            continue
                        text = await resp.text(errors="replace")
                        feed = feedparser.parse(text)
                        for entry in feed.entries[:20]:
                            title = entry.get("title", "").lower()
                            if not re.search(rf"\b{re.escape(base_currency.lower())}\b", title):
                                continue
                            total_articles += 1
                            title_clean = re.sub(rf"\b{re.escape(base_currency.lower())}\b", "", title)
                            for word in negative_words:
                                if word in title_clean:
                                    negative_count += 1
                                    break
                            else:
                                for word in positive_words:
                                    if word in title_clean:
                                        positive_count += 1
                                        break
                except Exception as e:
                    logger.warning(f"RSS fetch error for {url}: {e}")
                    continue

            if total_articles == 0:
                return None

            score = (positive_count - negative_count) / total_articles if total_articles > 0 else 0.0
            result = {
                "score": score,
                "count": total_articles,
                "positive": positive_count,
                "negative": negative_count,
            }
            self._rss_cache[cache_key] = (result, datetime.now(timezone.utc))
            logger.debug(f"RSS {symbol}: score={score:.2f} (articles={total_articles})")
            return result
        except Exception as e:
            logger.warning(f"Error fetching RSS for {symbol}: {e}")
            return None


# Singleton
context_fetcher = ContextFetcher()
