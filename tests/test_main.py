import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# Prevent config.logger from running setup_logger() during import
import config.logger as _cfg_logger
_cfg_logger.setup_logger = lambda: None


@pytest.fixture(autouse=True)
def fresh_main():
    """Remove main from cache so each test gets a fresh import"""
    if "main" in sys.modules:
        del sys.modules["main"]
    yield


class TestMainStartup:
    @pytest.mark.asyncio
    async def test_validates_token_presence(self):
        with (
            patch("config.settings.config") as mock_cfg,
            patch("main.send_error_alert", AsyncMock()),
            patch("main.logger"),
        ):
            mock_cfg.telegram.token = ""
            mock_cfg.telegram.channel_id = ""
            mock_cfg.telegram.admin_ids = []
            mock_cfg.exchange.name = "binance"
            mock_cfg.trading.symbols = ["BTC/USDT"]
            mock_cfg.trading.primary_timeframes = ["1h"]
            mock_cfg.trading.confirm_timeframe = "15m"
            mock_cfg.trading.candles_limit = 200
            mock_cfg.signal_cooldown_minutes = 60

            from main import main
            with pytest.raises(SystemExit) as exc:
                await main()
            assert exc.value.code == 1

    @pytest.mark.asyncio
    async def test_empty_token_logs_error(self):
        with (
            patch("config.settings.config") as mock_cfg,
            patch("main.logger") as mock_logger,
            patch("main.send_error_alert", AsyncMock()),
        ):
            mock_cfg.telegram.token = ""
            mock_cfg.telegram.channel_id = ""
            mock_cfg.telegram.admin_ids = []
            mock_cfg.exchange.name = "binance"
            mock_cfg.trading.symbols = ["BTC/USDT"]
            mock_cfg.trading.primary_timeframes = ["1h"]
            mock_cfg.trading.confirm_timeframe = "15m"
            mock_cfg.trading.candles_limit = 200
            mock_cfg.signal_cooldown_minutes = 60

            from main import main
            with pytest.raises(SystemExit):
                await main()
            mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_successful_startup_sequence(self):
        with (
            patch("config.settings.config") as mock_cfg,
            patch("main.db.init", AsyncMock()),
            patch("main.exchange_client.connect", AsyncMock()),
            patch("main.Application.builder") as mock_builder,
            patch("main.register_handlers"),
            patch("main.TaskScheduler") as mock_scheduler_cls,
            patch("main.send_error_alert", AsyncMock()),
            patch("main.logger"),
            patch("main.asyncio.sleep", AsyncMock(side_effect=KeyboardInterrupt)),
        ):
            mock_cfg.telegram.token = "valid:token"
            mock_cfg.telegram.channel_id = "-1000000"
            mock_cfg.telegram.admin_ids = []
            mock_cfg.exchange.name = "binance"
            mock_cfg.trading.symbols = ["BTC/USDT"]
            mock_cfg.trading.primary_timeframes = ["1h"]
            mock_cfg.trading.confirm_timeframe = "15m"
            mock_cfg.trading.candles_limit = 200
            mock_cfg.signal_cooldown_minutes = 60

            mock_updater = MagicMock()
            mock_updater.start_polling = AsyncMock()
            mock_updater.stop = AsyncMock()
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.start = AsyncMock()
            mock_app.updater = mock_updater
            mock_app.stop = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_builder.return_value.token.return_value.build.return_value = mock_app

            mock_scheduler = MagicMock()
            mock_scheduler_cls.return_value = mock_scheduler

            from main import main
            await main()
            # If we get here, startup succeeded and KeyboardInterrupt was handled gracefully
            assert True
