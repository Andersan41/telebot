"""
data/exchange_client.py — Получение OHLCV данных через ccxt
"""
import asyncio
from typing import Optional
import ccxt.async_support as ccxt
import pandas as pd
from loguru import logger
from config.settings import config, get_active_symbols


class ExchangeClient:
    def __init__(self):
        self._exchange: Optional[ccxt.Exchange] = None

    async def connect(self):
        """Создаём подключение к бирже"""
        exchange_class = getattr(ccxt, config.exchange.name)
        self._exchange = exchange_class({
            "apiKey": config.exchange.api_key,
            "secret": config.exchange.api_secret,
            "enableRateLimit": True,
            "options": {
                "defaultType": config.exchange.market_type,
            },
        })
        # Отключаем fetchCurrencies — он стучится в sapi/v1/capital/config/getall,
        # который часто недоступен. Без него load_markets всё равно работает через
        # exchangeInfo.
        self._exchange.has["fetchCurrencies"] = False
        try:
            await self._exchange.load_markets()
            logger.info(f"Markets loaded: {len(self._exchange.markets)} symbols")
        except Exception as e:
            logger.warning(f"Failed to load markets (will retry on first fetch): {e}")
        logger.info(f"Exchange client created: {config.exchange.name}")

    async def close(self):
        if self._exchange:
            await self._exchange.close()
            logger.info("Exchange connection closed")

    async def _fetch_taker_buy_volumes(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
    ) -> Optional[list]:
        """Fetch taker buy base asset volume from Binance futures API.

        Binance fapi/v1/klines returns taker_buy_base_asset_volume at index 9.
        Returns None for spot market or on error.
        """
        if config.exchange.market_type != "future":
            return None

        try:
            symbol_for_api = symbol.replace("/", "")
            url = f"fapi/v1/klines?symbol={symbol_for_api}&interval={timeframe}&limit={limit}"
            raw_klines = await self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            # ccxt doesn't expose taker buy volume, so we use the internal request
            # for binance futures
            if hasattr(self._exchange, "fapiPublicGetKlines"):
                params = {"symbol": symbol_for_api, "interval": timeframe, "limit": limit}
                klines = await self._exchange.fapiPublicGetKlines(params)
                return [float(k[9]) for k in klines]  # index 9 = taker_buy_base_asset_volume
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
        try:
            raw = await self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not raw:
                logger.warning(f"No data for {symbol} {timeframe}")
                return None

            df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.set_index("timestamp")
            df = df.astype(float)
            df = df.dropna()

            # Fetch taker buy volume for futures (for delta calculation)
            taker_buy_volumes = await self._fetch_taker_buy_volumes(symbol, timeframe, limit)
            if taker_buy_volumes and len(taker_buy_volumes) == len(raw):
                df["taker_buy_volume"] = taker_buy_volumes[:len(raw)]

            # Убираем последнюю незакрытую свечу
            df = df.iloc[:-1]

            logger.debug(f"Fetched {len(df)} candles: {symbol} {timeframe}")
            return df

        except ccxt.NetworkError as e:
            logger.error(f"Network error fetching {symbol} {timeframe}: {e}")
        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error fetching {symbol} {timeframe}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching {symbol} {timeframe}: {e}")
        return None

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
