import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bot.notifier as notifier_mod
from bot.notifier import send_signal, send_error_alert, get_bot, _bot


@pytest.fixture(autouse=True)
def reset_bot():
    notifier_mod._bot = None
    yield
    notifier_mod._bot = None


class TestNotifier:
    @pytest.mark.asyncio
    async def test_send_signal_no_channel(self):
        with patch("bot.notifier.config.telegram.channel_id", ""):
            await send_signal(MagicMock())

    @pytest.mark.asyncio
    async def test_send_signal_calls_bot(self):
        from strategy.signal_engine import SignalResult, SignalType
        sig = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT",
            timeframe="1h", close=50000.0, sl=48500.0, tp=53000.0,
            score=5, reasons=["test"],
        )
        with (
            patch("bot.notifier.config.telegram.channel_id", "-1000000"),
            patch("bot.notifier.Bot") as mock_bot_class,
        ):
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_bot_class.return_value = mock_bot
            await send_signal(sig)
            mock_bot.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_signal_telegram_error(self):
        from strategy.signal_engine import SignalResult, SignalType
        sig = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT",
            timeframe="1h", close=50000.0, sl=48500.0, tp=53000.0,
            score=5, reasons=[],
        )
        with (
            patch("bot.notifier.config.telegram.channel_id", "-1000000"),
            patch("bot.notifier.Bot") as mock_bot_class,
        ):
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock(side_effect=Exception("API error"))
            mock_bot_class.return_value = mock_bot
            await send_signal(sig)

    @pytest.mark.asyncio
    async def test_send_error_alert_no_admins(self):
        with patch("bot.notifier.config.telegram.admin_ids", []):
            await send_error_alert("test error")

    @pytest.mark.asyncio
    async def test_send_error_alert_sends_to_admins(self):
        with (
            patch("bot.notifier.config.telegram.admin_ids", [123, 456]),
            patch("bot.notifier.config.telegram.token", "fake:token"),
            patch("bot.notifier.Bot") as mock_bot_class,
        ):
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_bot_class.return_value = mock_bot
            await send_error_alert("critical error")
            assert mock_bot.send_message.await_count == 2

    def test_get_bot_creates_singleton(self):
        with patch("bot.notifier.config.telegram.token", "fake:token"):
            bot1 = get_bot()
            bot2 = get_bot()
            assert bot1 is bot2

    def test_get_bot_uses_correct_token(self):
        with (
            patch("bot.notifier.Bot") as mock_bot_class,
            patch("bot.notifier.config.telegram.token", "test_token_here"),
        ):
            notifier_mod._bot = None
            get_bot()
            mock_bot_class.assert_called_once_with(token="test_token_here")
