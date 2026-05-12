"""
config/settings.py — Централизованная конфигурация бота
"""
import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


@dataclass
class TelegramConfig:
    token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    channel_id: str = os.getenv("TELEGRAM_CHANNEL_ID", "")
    admin_ids: List[int] = field(default_factory=lambda: [
        int(x.strip()) for x in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip()
    ])


@dataclass
class ExchangeConfig:
    name: str = os.getenv("EXCHANGE", "binance")
    api_key: str = os.getenv("BINANCE_API_KEY", "")
    api_secret: str = os.getenv("BINANCE_API_SECRET", "")
    testnet: bool = os.getenv("USE_TESTNET", "false").lower() == "true"


@dataclass
class TradingConfig:
    symbols: List[str] = field(default_factory=lambda: [
        s.strip() for s in os.getenv("SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")
    ])
    primary_timeframes: List[str] = field(default_factory=lambda: [
        tf.strip() for tf in os.getenv("PRIMARY_TIMEFRAMES", "1h,4h").split(",")
    ])
    confirm_timeframe: str = os.getenv("CONFIRM_TIMEFRAME", "15m")

    # Параметры индикаторов
    ema_fast: int = 9
    ema_slow: int = 21
    ema_trend: int = 50
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    rsi_bull_min: float = 50.0      # Минимальный RSI для BUY
    rsi_bear_max: float = 50.0      # Максимальный RSI для SELL
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    adx_period: int = 14
    adx_min: float = 20.0           # Минимальный ADX (фильтр флэта)
    atr_period: int = 14
    atr_multiplier_sl: float = 1.5  # ATR × multiplier = SL
    atr_multiplier_tp: float = 3.0  # ATR × multiplier = TP
    supertrend_period: int = 10
    supertrend_multiplier: float = 3.0
    volume_factor: float = 1.2      # Объём должен быть выше SMA(volume) × factor

    # Параметры расчёта свечей
    candles_limit: int = 200        # Сколько свечей загружать


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


# Singleton
config = AppConfig()
