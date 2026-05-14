import importlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _reload_settings():
    """Reload config.settings before each test to reset to env defaults."""
    import config.settings as settings
    importlib.reload(settings)
    # Re-bind class references after reload so tests use the fresh module
    globals().update({
        "TelegramConfig": settings.TelegramConfig,
        "ExchangeConfig": settings.ExchangeConfig,
        "TradingConfig": settings.TradingConfig,
        "AppConfig": settings.AppConfig,
    })


class TestTelegramConfig:
    def test_reads_from_env(self):
        cfg = TelegramConfig()
        assert len(cfg.token) > 0
        assert len(cfg.channel_id) > 0

    def test_admin_ids_list_of_ints(self):
        cfg = TelegramConfig()
        assert isinstance(cfg.admin_ids, list)
        if cfg.admin_ids:
            assert all(isinstance(i, int) for i in cfg.admin_ids)


class TestExchangeConfig:
    def test_reads_from_env(self):
        cfg = ExchangeConfig()
        assert cfg.name == "binance"
        assert len(cfg.api_key) > 0
        assert len(cfg.api_secret) > 0
        assert cfg.testnet is False


class TestTradingConfig:
    def test_symbols_from_env(self):
        cfg = TradingConfig()
        assert "BTC/USDT" in cfg.symbols
        assert "XRP/USDT" in cfg.symbols

    def test_timeframes_from_env(self):
        cfg = TradingConfig()
        assert "1h" in cfg.primary_timeframes
        assert "4h" in cfg.primary_timeframes
        assert cfg.confirm_timeframe == "15m"

    def test_indicator_params(self):
        cfg = TradingConfig()
        assert cfg.rsi_period == 14
        assert cfg.adx_period == 14
        assert cfg.supertrend_period == 10
        assert cfg.atr_multiplier_sl == 1.5
        assert cfg.atr_multiplier_tp == 3.0
        assert cfg.candles_limit == 200


class TestAppConfig:
    def test_database_url_from_env(self):
        cfg = AppConfig()
        assert "signals.db" in cfg.database_url

    def test_cooldown_default(self):
        cfg = AppConfig()
        assert cfg.signal_cooldown_minutes == 60


class TestIndicatorEnvVars:
    def test_ema_fast_from_env(self, monkeypatch):
        monkeypatch.setenv("EMA_FAST", "5")
        import config.settings as settings
        importlib.reload(settings)
        assert settings.config.trading.ema_fast == 5

    def test_atr_multiplier_from_env(self, monkeypatch):
        monkeypatch.setenv("ATR_MULTIPLIER_SL", "2.5")
        import config.settings as settings
        importlib.reload(settings)
        assert settings.config.trading.atr_multiplier_sl == 2.5

    def test_defaults_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("EMA_FAST", raising=False)
        import config.settings as settings
        importlib.reload(settings)
        assert settings.config.trading.ema_fast == 9

    def test_volume_factor_from_env(self, monkeypatch):
        monkeypatch.setenv("VOLUME_FACTOR", "1.5")
        import config.settings as settings
        importlib.reload(settings)
        assert settings.config.trading.volume_factor == 1.5

    def test_candles_limit_from_env(self, monkeypatch):
        monkeypatch.setenv("CANDLES_LIMIT", "300")
        import config.settings as settings
        importlib.reload(settings)
        assert settings.config.trading.candles_limit == 300


class TestEnvFile:
    ENV_KEYS = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHANNEL_ID",
        "EXCHANGE",
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "SYMBOLS",
        "PRIMARY_TIMEFRAMES",
        "CONFIRM_TIMEFRAME",
        "DATABASE_URL",
        "LOG_LEVEL",
        "LOG_FILE",
        "EMA_FAST",
        "EMA_SLOW",
        "EMA_TREND",
        "RSI_PERIOD",
        "RSI_OVERBOUGHT",
        "RSI_OVERSOLD",
        "RSI_BULL_MIN",
        "RSI_BEAR_MAX",
        "MACD_FAST",
        "MACD_SLOW",
        "MACD_SIGNAL",
        "ADX_PERIOD",
        "ADX_MIN",
        "ATR_PERIOD",
        "ATR_MULTIPLIER_SL",
        "ATR_MULTIPLIER_TP",
        "SUPERTREND_PERIOD",
        "SUPERTREND_MULTIPLIER",
        "VOLUME_FACTOR",
        "CANDLES_LIMIT",
    ]

    def test_env_example_exists(self):
        assert Path(".env.example").exists()

    def test_env_example_contains_all_keys(self):
        content = Path(".env.example").read_text()
        for key in self.ENV_KEYS:
            assert key in content, f"Missing key: {key}"

    def test_env_example_has_no_real_secrets(self):
        content = Path(".env.example").read_text().lower()
        keywords = ["8709934704", "3xg1t2mh"]
        for kw in keywords:
            assert kw not in content, f"Found potential secret: {kw}"

    def test_env_example_placeholder_values(self):
        content = Path(".env.example").read_text()
        assert "your_telegram_bot_token_here" in content
        assert "your_binance_api_key_here" in content
        assert "your_binance_api_secret_here" in content

    def test_env_matches_example_structure(self):
        """Both files must have the same set of keys"""
        env = Path(".env").read_text()
        example = Path(".env.example").read_text()
        for key in self.ENV_KEYS:
            assert key in env, f"Missing key in .env: {key}"
            assert key in example, f"Missing key in .env.example: {key}"
