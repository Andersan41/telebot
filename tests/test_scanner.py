import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scheduler.scanner import scan_symbol, run_scan_cycle, _is_cooldown_active, _set_cooldown, _last_signal_time


@pytest.fixture(autouse=True)
def clear_cooldown():
    _last_signal_time.clear()
    yield


@pytest.fixture
def mock_signal_result():
    from strategy.signal_engine import SignalResult, SignalType
    sig = SignalResult(
        signal=SignalType.BUY,
        symbol="BTC/USDT",
        timeframe="1h",
        close=50000.0,
        sl=48500.0,
        tp=53000.0,
        score=6,
        reasons=["ADX > 20", "Supertrend bullish"],
    )
    return sig


@pytest.fixture
def mock_exchange():
    m = MagicMock()
    m.fetch_ohlcv = AsyncMock()
    return m


@pytest.fixture
def mock_ind_engine():
    m = MagicMock()
    m.calculate.return_value = MagicMock()
    return m


class TestCooldown:
    def test_no_cooldown_initially(self):
        assert _is_cooldown_active("BTC/USDT", "1h") is False

    def test_cooldown_active_after_set(self):
        _set_cooldown("BTC/USDT", "1h")
        assert _is_cooldown_active("BTC/USDT", "1h") is True

    def test_different_symbol_no_cooldown(self):
        _set_cooldown("BTC/USDT", "1h")
        assert _is_cooldown_active("ETH/USDT", "1h") is False

    def test_different_timeframe_no_cooldown(self):
        _set_cooldown("BTC/USDT", "1h")
        assert _is_cooldown_active("BTC/USDT", "4h") is False


class TestScanSymbol:
    @pytest.mark.asyncio
    async def test_returns_none_when_cooldown(self, mock_signal_result):
        _set_cooldown("BTC/USDT", "1h")
        result = await scan_symbol("BTC/USDT", "1h", AsyncMock())
        assert result is None

    @pytest.mark.asyncio
    async def test_full_successful_scan(self, mock_signal_result, mock_exchange, mock_ind_engine):
        with (
            patch("scheduler.scanner.exchange_client", mock_exchange),
            patch("scheduler.scanner.indicator_engine", mock_ind_engine),
            patch("scheduler.scanner.signal_engine") as mock_sig,
            patch("scheduler.scanner.db") as mock_db,
        ):
            mock_sig.evaluate.return_value = mock_signal_result
            mock_db.save_signal = AsyncMock()

            result = await scan_symbol("BTC/USDT", "1h", AsyncMock())

            assert result is not None
            assert result.signal.value == "BUY"
            assert result.symbol == "BTC/USDT"

    @pytest.mark.asyncio
    async def test_skips_when_no_indicator_data(self, mock_exchange):
        mock_exchange.fetch_ohlcv.return_value = None
        with patch("scheduler.scanner.exchange_client", mock_exchange):
            result = await scan_symbol("BTC/USDT", "1h", AsyncMock())
            assert result is None

    @pytest.mark.asyncio
    async def test_skips_when_signal_not_actionable(self, mock_exchange, mock_ind_engine):
        from strategy.signal_engine import SignalResult, SignalType
        non_actionable = SignalResult(
            signal=SignalType.NO_SIGNAL, symbol="BTC/USDT",
            timeframe="1h", close=50000.0, score=2, reasons=[],
        )
        with (
            patch("scheduler.scanner.exchange_client", mock_exchange),
            patch("scheduler.scanner.indicator_engine", mock_ind_engine),
            patch("scheduler.scanner.signal_engine") as mock_sig,
        ):
            mock_sig.evaluate.return_value = non_actionable
            result = await scan_symbol("BTC/USDT", "1h", AsyncMock())
            assert result is None

    @pytest.mark.asyncio
    async def test_confirmation_rejects_mismatch(self, mock_signal_result, mock_exchange, mock_ind_engine):
        from strategy.signal_engine import SignalResult, SignalType
        opposite = SignalResult(
            signal=SignalType.SELL, symbol="BTC/USDT",
            timeframe="15m", close=50000.0, sl=51000.0, tp=48000.0, score=5, reasons=[],
        )
        with (
            patch("scheduler.scanner.exchange_client", mock_exchange),
            patch("scheduler.scanner.indicator_engine", mock_ind_engine),
            patch("scheduler.scanner.signal_engine") as mock_sig,
            patch("scheduler.scanner.db") as mock_db,
        ):
            mock_sig.evaluate.side_effect = [mock_signal_result, opposite]
            mock_db.save_signal = AsyncMock()
            result = await scan_symbol("BTC/USDT", "1h", AsyncMock())
            assert result is None

    @pytest.mark.asyncio
    async def test_sets_cooldown_after_signal(self, mock_signal_result, mock_exchange, mock_ind_engine):
        with (
            patch("scheduler.scanner.exchange_client", mock_exchange),
            patch("scheduler.scanner.indicator_engine", mock_ind_engine),
            patch("scheduler.scanner.signal_engine") as mock_sig,
            patch("scheduler.scanner.db") as mock_db,
        ):
            mock_sig.evaluate.return_value = mock_signal_result
            mock_db.save_signal = AsyncMock()

            _last_signal_time.clear()
            await scan_symbol("BTC/USDT", "1h", AsyncMock())
            assert _is_cooldown_active("BTC/USDT", "1h") is True


    @pytest.mark.asyncio
    async def test_scan_cycle_runs_all_symbols(self, mock_exchange, mock_ind_engine):
        with (
            patch("scheduler.scanner.exchange_client", mock_exchange),
            patch("scheduler.scanner.indicator_engine", mock_ind_engine),
            patch("scheduler.scanner.signal_engine") as mock_sig,
            patch("scheduler.scanner.db") as mock_db,
        ):
            from strategy.signal_engine import SignalResult, SignalType
            mock_sig.evaluate.return_value = SignalResult(
                signal=SignalType.NO_SIGNAL, symbol="BTC/USDT",
                timeframe="1h", close=50000.0, score=2, reasons=[],
            )
            mock_db.save_signal = AsyncMock()
            await run_scan_cycle(AsyncMock())


class TestEntryPrice:
    @pytest.mark.asyncio
    async def test_entry_price_set_on_same_timeframe(self, mock_signal_result, mock_exchange, mock_ind_engine):
        mock_signal_result.entry_price = None
        mock_exchange.fetch_ohlcv.return_value = {"close": [50000.0]}
        with (
            patch("scheduler.scanner.exchange_client", mock_exchange),
            patch("scheduler.scanner.indicator_engine", mock_ind_engine),
            patch("scheduler.scanner.signal_engine") as mock_sig,
            patch("scheduler.scanner.db") as mock_db,
            patch("scheduler.scanner.config.trading.confirm_timeframe", "1h"),
        ):
            mock_sig.evaluate.return_value = mock_signal_result
            mock_db.save_signal = AsyncMock()
            result = await scan_symbol("BTC/USDT", "1h", AsyncMock())
            assert result is not None
            assert result.entry_price == 50000.0

    @pytest.mark.asyncio
    async def test_entry_price_from_confirm_candle(self, mock_signal_result, mock_exchange, mock_ind_engine):
        mock_signal_result.entry_price = None
        confirm_close = 50100.0
        confirm_ind = MagicMock(close=confirm_close)
        from strategy.signal_engine import SignalResult, SignalType
        confirm_sig = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT",
            timeframe="15m", close=confirm_close, score=6, reasons=[],
        )
        with (
            patch("scheduler.scanner.exchange_client", mock_exchange),
            patch("scheduler.scanner.indicator_engine", mock_ind_engine),
            patch("scheduler.scanner.signal_engine") as mock_sig,
            patch("scheduler.scanner.db") as mock_db,
            patch("scheduler.scanner.config.trading.confirm_timeframe", "15m"),
        ):
            mock_sig.evaluate.side_effect = [mock_signal_result, confirm_sig]
            mock_ind_engine.calculate.return_value = confirm_ind
            mock_db.save_signal = AsyncMock()
            result = await scan_symbol("BTC/USDT", "1h", AsyncMock())
            assert result is not None
            assert result.entry_price == confirm_close

    @pytest.mark.asyncio
    async def test_entry_price_from_close_when_no_confirm_data(self, mock_signal_result, mock_exchange, mock_ind_engine):
        mock_signal_result.entry_price = None
        mock_exchange.fetch_ohlcv.side_effect = [
            {"close": [50000.0]},  # main timeframe
            None,                  # confirm timeframe
        ]
        with (
            patch("scheduler.scanner.exchange_client", mock_exchange),
            patch("scheduler.scanner.indicator_engine", mock_ind_engine),
            patch("scheduler.scanner.signal_engine") as mock_sig,
            patch("scheduler.scanner.db") as mock_db,
            patch("scheduler.scanner.config.trading.confirm_timeframe", "15m"),
        ):
            mock_sig.evaluate.return_value = mock_signal_result
            mock_db.save_signal = AsyncMock()
            result = await scan_symbol("BTC/USDT", "1h", AsyncMock())
            assert result is not None
            assert result.entry_price == 50000.0

    @pytest.mark.asyncio
    async def test_entry_price_not_set_on_rejected_confirm(self, mock_signal_result, mock_exchange, mock_ind_engine):
        mock_signal_result.entry_price = None
        from strategy.signal_engine import SignalResult, SignalType
        opposite = SignalResult(
            signal=SignalType.SELL, symbol="BTC/USDT",
            timeframe="15m", close=50000.0, score=5, reasons=[],
        )
        with (
            patch("scheduler.scanner.exchange_client", mock_exchange),
            patch("scheduler.scanner.indicator_engine", mock_ind_engine),
            patch("scheduler.scanner.signal_engine") as mock_sig,
            patch("scheduler.scanner.db") as mock_db,
            patch("scheduler.scanner.config.trading.confirm_timeframe", "15m"),
        ):
            mock_sig.evaluate.side_effect = [mock_signal_result, opposite]
            mock_db.save_signal = AsyncMock()
            result = await scan_symbol("BTC/USDT", "1h", AsyncMock())
            assert result is None
