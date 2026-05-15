"""
config/settings.py — Централизованная конфигурация бота
"""
import os
from dataclasses import dataclass, field
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class TelegramConfig:
    token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    channel_id: str = os.getenv("TELEGRAM_CHANNEL_ID", "")
    admin_ids: List[int] = field(default_factory=lambda: [
        int(x.strip()) for x in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip()
    ])
    error_channel_id: str = os.getenv("TELEGRAM_ERROR_CHANNEL_ID", "")


@dataclass
class ExchangeConfig:
    name: str = os.getenv("EXCHANGE", "binance")
    api_key: str = os.getenv("BINANCE_API_KEY", "")
    api_secret: str = os.getenv("BINANCE_API_SECRET", "")
    testnet: bool = os.getenv("USE_TESTNET", "false").lower() == "true"
    market_type: str = os.getenv("MARKET_TYPE", "spot")  # spot | future


@dataclass
class TradingConfig:
    symbols: List[str] = field(default_factory=lambda: [
        s.strip() for s in os.getenv("SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")
    ])
    primary_timeframes: List[str] = field(default_factory=lambda: [
        tf.strip() for tf in os.getenv("PRIMARY_TIMEFRAMES", "1h,4h").split(",")
    ])
    confirm_timeframe: str = os.getenv("CONFIRM_TIMEFRAME", "15m")

    # Параметры индикаторов (читаются из .env, дефолты — в скобках)
    ema_fast: int = int(os.getenv("EMA_FAST", "9"))
    ema_slow: int = int(os.getenv("EMA_SLOW", "21"))
    ema_trend: int = int(os.getenv("EMA_TREND", "50"))
    rsi_period: int = int(os.getenv("RSI_PERIOD", "14"))
    rsi_overbought: float = float(os.getenv("RSI_OVERBOUGHT", "70"))
    rsi_oversold: float = float(os.getenv("RSI_OVERSOLD", "30"))
    rsi_bull_min: float = float(os.getenv("RSI_BULL_MIN", "50"))
    rsi_bear_max: float = float(os.getenv("RSI_BEAR_MAX", "50"))
    macd_fast: int = int(os.getenv("MACD_FAST", "12"))
    macd_slow: int = int(os.getenv("MACD_SLOW", "26"))
    macd_signal: int = int(os.getenv("MACD_SIGNAL", "9"))
    adx_period: int = int(os.getenv("ADX_PERIOD", "14"))
    adx_min: float = float(os.getenv("ADX_MIN", "20"))
    atr_period: int = int(os.getenv("ATR_PERIOD", "14"))
    atr_multiplier_sl: float = float(os.getenv("ATR_MULTIPLIER_SL", "1.5"))
    atr_multiplier_tp: float = float(os.getenv("ATR_MULTIPLIER_TP", "3.0"))
    supertrend_period: int = int(os.getenv("SUPERTREND_PERIOD", "10"))
    supertrend_multiplier: float = float(os.getenv("SUPERTREND_MULTIPLIER", "3.0"))
    volume_factor: float = float(os.getenv("VOLUME_FACTOR", "1.2"))

    # Параметры расчёта свечей
    candles_limit: int = int(os.getenv("CANDLES_LIMIT", "200"))


@dataclass
class AppConfig:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/signals.db")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_file: str = os.getenv("LOG_FILE", "logs/bot.log")

    # Cooldown между сигналами по одному инструменту (минуты)
    signal_cooldown_minutes: int = int(os.getenv("SIGNAL_COOLDOWN_MINUTES", "60"))

    # Контекстный модуль
    context_enabled: bool = os.getenv("CONTEXT_ENABLED", "true").lower() == "true"
    context_min_verdict: str = os.getenv("CONTEXT_MIN_VERDICT", "WEAK")
    context_block_on_blocked: bool = os.getenv("CONTEXT_BLOCK_ON_BLOCKED", "true").lower() == "true"
    cryptopanic_api_key: str = os.getenv("CRYPTOPANIC_API_KEY", "")
    coingecko_symbol_map_str: str = os.getenv("COINGECKO_SYMBOL_MAP", "BTC/USDT:bitcoin,ETH/USDT:ethereum")

    def _parse_coingecko_map(self, map_str: str) -> dict[str, str]:
        result = {}
        for pair in map_str.split(","):
            if ":" in pair:
                symbol, slug = pair.strip().split(":")
                result[symbol.strip()] = slug.strip()
        return result

    @property
    def coingecko_symbol_map(self) -> dict[str, str]:
        return self._parse_coingecko_map(self.coingecko_symbol_map_str)


# Singleton
config = AppConfig()

# Runtime symbols cache — динамически обновляется через /addsymbol / /removesymbol
_runtime_symbols_cache: Optional[list[str]] = None


async def refresh_runtime_symbols() -> None:
    """Перечитать список символов из БД. Зови при старте и после /addsymbol / /removesymbol.

    dynamic_symbols из БД — это ДОБАВЛЕННЫЕ символы (через /addsymbol).
    Итоговый список = env SYMBOLS + dynamic.
    """
    global _runtime_symbols_cache
    from storage.database import db  # lazy чтобы избежать циклов импорта
    dynamic = await db.get_dynamic_symbols()
    if dynamic:
        merged = list(config.trading.symbols)
        for s in dynamic:
            if s not in merged:
                merged.append(s)
        _runtime_symbols_cache = merged
    else:
        _runtime_symbols_cache = config.trading.symbols


def get_active_symbols() -> list[str]:
    return _runtime_symbols_cache if _runtime_symbols_cache is not None else config.trading.symbols
