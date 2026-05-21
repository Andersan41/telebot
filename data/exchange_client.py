"""
data/exchange_client.py — Получение OHLCV данных через ccxt

Workaround для Windows: aiohappyeyeballs (aiohttp 3.10+) ломает DNS resolution.
Все сетевые запросы идут через sync ccxt в run_in_executor.
"""
import asyncio
import sys
from typing import Optional
import ccxt as ccxt_sync
import pandas as pd
from loguru import logger
from config.settings import config, get_active_symbols


class ExchangeClient:
    def __init__(self):
        self._exchange: Optional[ccxt_sync.Exchange] = None
        self._markets_loaded = False
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._available_symbols: set[str] = set()

    async def connect(self):
        """Создаём подключение к бирже (sync exchange для Windows compatibility)"""
        exchange_class = getattr(ccxt_sync, config.exchange.name)
        self._exchange = exchange_class({
            "apiKey": config.exchange.api_key,
            "secret": config.exchange.api_secret,
            "enableRateLimit": True,
            "timeout": 30000,
            "options": {
                "defaultType": config.exchange.market_type,
            },
        })
        self._exchange.has["fetchCurrencies"] = False

        max_retries = 5
        retry_delay = 5
        for attempt in range(1, max_retries + 1):
            try:
                markets = await asyncio.get_event_loop().run_in_executor(
                    None, self._exchange.load_markets
                )
                logger.info(f"Markets loaded: {len(markets)} symbols")
                self._markets_loaded = True
                active = set()
                for sym, m in self._exchange.markets.items():
                    if m.get("active", True) and m.get(config.exchange.market_type, False):
                        active.add(sym)
                self._available_symbols = active
                break
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(
                        f"Failed to load markets (attempt {attempt}/{max_retries}), "
                        f"retrying in {retry_delay}s: {e}"
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.error(f"Failed to load markets after {max_retries} attempts: {e}")
                    raise

        logger.info(f"Exchange client created: {config.exchange.name}")

        # Семафор для сериализации запросов — ccxt rate limiter не thread-safe
        self._semaphore = asyncio.Semaphore(1)

    async def close(self):
        if self._exchange:
            # Sync ccxt exchange — просто обнуляем ссылку, requests session закроется сама
            self._exchange = None
            logger.info("Exchange connection closed")

    async def _ensure_markets_loaded(self):
        if not self._markets_loaded and self._exchange:
            logger.warning("Markets not loaded, attempting to reload...")
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._exchange.load_markets
                )
                self._markets_loaded = True
                active = set()
                for sym, m in self._exchange.markets.items():
                    if m.get("active", True) and m.get(config.exchange.market_type, False):
                        active.add(sym)
                self._available_symbols = active
                logger.info(
                    f"Markets reloaded: {len(self._exchange.markets)} loaded, "
                    f"{len(active)} active {config.exchange.market_type} symbols"
                )
            except Exception as e:
                logger.error(f"Failed to reload markets: {e}")
                raise

    def _fetch_ohlcv_raw(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        max_retries: int = 3,
    ) -> Optional[list]:
        """Sync fetch_ohlcv — вызывается через run_in_executor

        Встроенные повторные попытки при сетевых ошибках.
        RateLimitExceeded/DDoSProtection получают больше попыток.
        BadSymbol/BadRequest не ретраятся.
        """
        if symbol not in self._available_symbols:
            logger.warning(
                f"Symbol {symbol} not available on {config.exchange.market_type}, skipping"
            )
            return None

        last_error = None
        for attempt in range(max_retries):
            try:
                return self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            except (ccxt_sync.BadSymbol, ccxt_sync.BadRequest) as e:
                logger.warning(
                    f"Invalid symbol/request for {symbol} {timeframe}: {e}"
                )
                return None
            except (ccxt_sync.RateLimitExceeded, ccxt_sync.DDoSProtection) as e:
                last_error = e
                if attempt < max_retries - 1:
                    import time
                    delay = 5 * (2 ** attempt)
                    logger.warning(
                        f"Rate limited fetching {symbol} {timeframe} "
                        f"(attempt {attempt + 1}/{max_retries}), "
                        f"retrying in {delay}s: {e}"
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"Rate limited fetching {symbol} {timeframe} "
                        f"after {max_retries} attempts: {e}"
                    )
            except ccxt_sync.NetworkError as e:
                last_error = e
                if attempt < max_retries - 1:
                    import time
                    delay = 2 ** attempt
                    logger.warning(
                        f"Network error fetching {symbol} {timeframe} "
                        f"(attempt {attempt + 1}/{max_retries}), "
                        f"retrying in {delay}s: {e}"
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"Network error fetching {symbol} {timeframe} "
                        f"after {max_retries} attempts: {e}"
                    )
            except ccxt_sync.ExchangeError as e:
                logger.error(f"Exchange error fetching {symbol} {timeframe}: {e}")
                return None
            except Exception as e:
                logger.error(f"Unexpected error fetching {symbol} {timeframe}: {e}")
                return None
        return None

    async def _fetch_taker_buy_volumes(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
    ) -> Optional[list]:
        """Fetch taker buy base asset volume from Binance futures API."""
        if config.exchange.market_type != "future":
            return None

        try:
            symbol_for_api = symbol.replace("/", "")
            if hasattr(self._exchange, "fapiPublicGetKlines"):
                params = {"symbol": symbol_for_api, "interval": timeframe, "limit": limit}
                klines = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._exchange.fapiPublicGetKlines(params)
                )
                return [float(k[9]) for k in klines]
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch taker buy volumes for {symbol}: {e}")
            return None

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
    ) -> Optional[pd.DataFrame]:
        """
        Получаем OHLCV свечи и возвращаем как DataFrame.
        Колонки: timestamp, open, high, low, close, volume
        Для futures: также добавляем taker_buy_volume (index 9 из Binance API).
        """
        await self._ensure_markets_loaded()

        async with self._semaphore:
            raw = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._fetch_ohlcv_raw(symbol, timeframe, limit)
            )
            if raw is None:
                return None
            if not raw:
                logger.warning(f"No data for {symbol} {timeframe}")
                return None

            df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.set_index("timestamp")
            df = df.astype(float)
            df = df.dropna()

            taker_buy_volumes = await self._fetch_taker_buy_volumes(symbol, timeframe, limit)
            if taker_buy_volumes and len(taker_buy_volumes) == len(raw):
                df["taker_buy_volume"] = taker_buy_volumes[:len(raw)]

            df = df.iloc[:-1]

        logger.debug(f"Fetched {len(df)} candles: {symbol} {timeframe}")
        return df

    async def fetch_all_symbols(
        self,
        timeframe: str,
        limit: int = 200,
    ) -> dict[str, pd.DataFrame]:
        """Загружаем данные по всем символам параллельно"""
        tasks = {
            symbol: self.fetch_ohlcv(symbol, timeframe, limit)
            for symbol in get_active_symbols()
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        data = {}
        for symbol, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.error(f"Error fetching {symbol}: {result}")
            elif result is not None:
                data[symbol] = result
        return data


# Singleton
exchange_client = ExchangeClient()
