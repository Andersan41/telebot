import sys
import os
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
    # storage.database читает config.database_url при импорте (db = Database()):
    # если первый импорт случится внутри patch("config.settings.config"),
    # URL окажется MagicMock -> ValueError в create_engine. Импортируем заранее.
    import storage.database  # noqa: F401
    yield


@pytest.fixture(autouse=True)
def lock_file_env(tmp_path, monkeypatch):
    """Изолирует single-instance lock от боевого .trading_bot.lock"""
    monkeypatch.setenv(
        "TRADING_BOT_LOCK_FILE", str(tmp_path / ".trading_bot.lock")
    )


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
            # фоновые циклы (веб-сервер, outcome tracker, error sink) не даём
            # утечь: их asyncio.sleep упрётся в KeyboardInterrupt-mock уже на
            # teardown event loop и оборвёт всю сессию pytest
            patch(
                "scheduler.outcome_tracker.outcome_tracker_loop", AsyncMock()
            ),
            patch("scheduler.price_alerts.price_alert_loop", AsyncMock()),
            patch("scheduler.audit_resolver.audit_resolver_loop", AsyncMock()),
            patch("config.logger.setup_error_sink"),
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
            mock_cfg.web.enabled = False

            mock_updater = MagicMock()
            mock_updater.start_polling = AsyncMock()
            mock_updater.stop = AsyncMock()
            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.start = AsyncMock()
            mock_app.updater = mock_updater
            mock_app.stop = AsyncMock()
            mock_app.shutdown = AsyncMock()
            # цепочка должна совпадать с main.py: builder().token().request().build()
            (
                mock_builder.return_value.token.return_value.request.return_value.build
            ).return_value = mock_app

            mock_scheduler = MagicMock()
            mock_scheduler_cls.return_value = mock_scheduler

            from main import main
            await main()
            # If we get here, startup succeeded and KeyboardInterrupt was handled gracefully
            assert True


class TestSingleInstanceLock:
    def test_second_acquire_exits_and_release_reopens(self):
        from main import acquire_lock, release_lock

        lock = Path(os.environ["TRADING_BOT_LOCK_FILE"])
        acquire_lock()
        try:
            assert lock.read_text().strip() == str(os.getpid())
            with pytest.raises(SystemExit) as exc:
                acquire_lock()
            assert exc.value.code == 1
        finally:
            release_lock()
        # файл остаётся (unlink гонка inode'ов), но блокировка снята ОС
        assert lock.exists()
        acquire_lock()
        release_lock()

    def test_stale_pid_in_lock_file_does_not_block(self):
        from main import acquire_lock, release_lock

        lock = Path(os.environ["TRADING_BOT_LOCK_FILE"])
        lock.write_text("999999")
        acquire_lock()
        try:
            assert lock.read_text().strip() == str(os.getpid())
        finally:
            release_lock()
