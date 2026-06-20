import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scheduler.scanner import scan_symbol, run_scan_cycle, _is_cooldown_active, _set_cooldown


def _make_ind_mock(atr=600.0, close=50000.0):
    """Create an indicator mock with real numeric atr/close for volatility regime."""
    m = MagicMock()
    m.atr = atr
    m.close = close
    m.volume = 1200.0
    m.volume_sma = 1000.0
    m.volume_above_avg = True
    m.rsi = 55.0
    m.macd_hist = 30.0
    m.adx = 30.0
    m.dmi_plus = 25.0
    m.dmi_minus = 15.0
    m.ema_fast = 50100.0
    m.ema_slow = 49900.0
    return m


@pytest.fixture
def mock_cooldown(monkeypatch):
    """Подменяет db.get_cooldown / db.set_cooldown на in-memory dict."""
    store: dict[tuple[str, str], "datetime"] = {}

    async def fake_get(symbol, timeframe):
        return store.get((symbol, timeframe))

    async def fake_set(symbol, timeframe, ts):
        store[(symbol, timeframe)] = ts

    monkeypatch.setattr("scheduler.scanner.db.get_cooldown", fake_get)
    monkeypatch.setattr("scheduler.scanner.db.set_cooldown", fake_set)
    return store


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
    ind_mock = MagicMock()
    ind_mock.atr = 600.0
    ind_mock.close = 50000.0
    ind_mock.volume = 1200.0
    ind_mock.volume_sma = 1000.0
    ind_mock.volume_above_avg = True
    ind_mock.rsi = 55.0
    ind_mock.macd_hist = 30.0
    ind_mock.adx = 30.0
    ind_mock.dmi_plus = 25.0
    ind_mock.dmi_minus = 15.0
    ind_mock.ema_fast = 50100.0
    ind_mock.ema_slow = 49900.0
    m.calculate.return_value = ind_mock
    return m


class TestCooldown:
    @pytest.mark.asyncio
    async def test_no_cooldown_initially(self, mock_cooldown):
        assert await _is_cooldown_active("BTC/USDT", "1h") is False

    @pytest.mark.asyncio
    async def test_cooldown_blocks_repeat(self, mock_cooldown):
        await _set_cooldown("BTC/USDT", "1h")
        assert await _is_cooldown_active("BTC/USDT", "1h") is True

    @pytest.mark.asyncio
    async def test_cooldown_other_symbol_independent(self, mock_cooldown):
        await _set_cooldown("BTC/USDT", "1h")
        assert await _is_cooldown_active("ETH/USDT", "1h") is False

    @pytest.mark.asyncio
    async def test_cooldown_different_timeframe_independent(self, mock_cooldown):
        await _set_cooldown("BTC/USDT", "1h")
        assert await _is_cooldown_active("BTC/USDT", "4h") is False


class TestDedup:
    @pytest.mark.asyncio
    async def test_dedup_skips_same_direction_recent(self, mock_signal_result, mock_exchange, mock_ind_engine):
        from datetime import datetime, timezone, timedelta
        from context.scorer import ContextVerdict
        with (
            patch("scheduler.scanner.exchange_client", mock_exchange),
            patch("scheduler.scanner.indicator_engine", mock_ind_engine),
            patch("scheduler.scanner.signal_engine") as mock_sig,
            patch("scheduler.scanner.db") as mock_db,
            patch("scheduler.scanner.context_engine") as mock_ctx_engine,
            patch("scheduler.scanner.context_scorer") as mock_ctx_scorer,
        ):
            mock_sig.evaluate.return_value = mock_signal_result
            mock_db.save_signal = AsyncMock()
            mock_db.create_outcome = AsyncMock()
            mock_db.get_cooldown = AsyncMock(return_value=None)
            mock_db.set_cooldown = AsyncMock()
            mock_ctx_engine.get_snapshot = AsyncMock(return_value=MagicMock())
            mock_ctx_scorer.score.return_value = ContextVerdict(
                verdict="WEAK", confidence=0.15, score=0.15,
            )
            last_signal = MagicMock()
            last_signal.signal_type = "BUY"
            last_signal.sent_at = datetime.now(timezone.utc) - timedelta(minutes=10)
            mock_db.get_last_signal = AsyncMock(return_value=last_signal)

            result = await scan_symbol("BTC/USDT", "1h", AsyncMock())
            assert result is None
            mock_db.save_signal.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedup_allows_opposite_direction(self, mock_signal_result, mock_exchange, mock_ind_engine):
        from datetime import datetime, timezone, timedelta
        from context.scorer import ContextVerdict
        with (
            patch("scheduler.scanner.exchange_client", mock_exchange),
            patch("scheduler.scanner.indicator_engine", mock_ind_engine),
            patch("scheduler.scanner.signal_engine") as mock_sig,
            patch("scheduler.scanner.db") as mock_db,
            patch("scheduler.scanner.context_engine") as mock_ctx_engine,
            patch("scheduler.scanner.context_scorer") as mock_ctx_scorer,
        ):
            mock_sig.evaluate.return_value = mock_signal_result
            mock_db.save_signal = AsyncMock()
            mock_db.create_outcome = AsyncMock()
            mock_db.get_cooldown = AsyncMock(return_value=None)
            mock_db.set_cooldown = AsyncMock()
            mock_ctx_engine.get_snapshot = AsyncMock(return_value=MagicMock())
            mock_ctx_scorer.score.return_value = ContextVerdict(
                verdict="WEAK", confidence=0.15, score=0.15,
            )
            last_signal = MagicMock()
            last_signal.signal_type = "SELL"
            last_signal.sent_at = datetime.now(timezone.utc) - timedelta(minutes=25)
            mock_db.get_last_signal = AsyncMock(return_value=last_signal)

            result = await scan_symbol("BTC/USDT", "1h", AsyncMock())
            assert result is not None
            mock_db.save_signal.assert_called_once()


class TestScanSymbol:
    @pytest.mark.asyncio
    async def test_returns_none_when_cooldown(self, mock_signal_result, mock_cooldown):
        await _set_cooldown("BTC/USDT", "1h")
        result = await scan_symbol("BTC/USDT", "1h", AsyncMock())
        assert result is None

    @pytest.mark.asyncio
    async def test_full_successful_scan(self, mock_signal_result, mock_exchange, mock_ind_engine):
        from context.scorer import ContextVerdict
        with (
            patch("scheduler.scanner.exchange_client", mock_exchange),
            patch("scheduler.scanner.indicator_engine", mock_ind_engine),
            patch("scheduler.scanner.signal_engine") as mock_sig,
            patch("scheduler.scanner.db") as mock_db,
            patch("scheduler.scanner.context_engine") as mock_ctx_engine,
            patch("scheduler.scanner.context_scorer") as mock_ctx_scorer,
        ):
            mock_sig.evaluate.return_value = mock_signal_result
            mock_db.save_signal = AsyncMock()
            mock_db.create_outcome = AsyncMock()
            mock_db.get_cooldown = AsyncMock(return_value=None)
            mock_db.set_cooldown = AsyncMock()
            mock_db.get_last_signal = AsyncMock(return_value=None)
            mock_ctx_engine.get_snapshot = AsyncMock(return_value=MagicMock())
            mock_ctx_scorer.score.return_value = ContextVerdict(
                verdict="WEAK", confidence=0.15, score=0.15,
            )

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
        with (
            patch("scheduler.scanner.exchange_client", mock_exchange),
            patch("scheduler.scanner.indicator_engine", mock_ind_engine),
            patch("scheduler.scanner.signal_engine") as mock_sig,
            patch("scheduler.scanner.db") as mock_db,
        ):
            mock_sig.evaluate.return_value = mock_signal_result
            mock_sig.evaluate_confirm.return_value = False
            mock_db.save_signal = AsyncMock()
            mock_db.create_outcome = AsyncMock()
            mock_db.get_cooldown = AsyncMock(return_value=None)
            mock_db.set_cooldown = AsyncMock()
            mock_db.get_last_signal = AsyncMock(return_value=None)
            result = await scan_symbol("BTC/USDT", "1h", AsyncMock())
            assert result is None

    @pytest.mark.asyncio
    async def test_sets_cooldown_after_signal(self, mock_signal_result, mock_exchange, mock_ind_engine, mock_cooldown):
        from context.scorer import ContextVerdict
        from storage.database import db
        with (
            patch("scheduler.scanner.exchange_client", mock_exchange),
            patch("scheduler.scanner.indicator_engine", mock_ind_engine),
            patch("scheduler.scanner.signal_engine") as mock_sig,
            patch("scheduler.scanner.context_engine") as mock_ctx_engine,
            patch("scheduler.scanner.context_scorer") as mock_ctx_scorer,
        ):
            mock_sig.evaluate.return_value = mock_signal_result
            db.save_signal = AsyncMock()
            db.create_outcome = AsyncMock()
            db.get_last_signal = AsyncMock(return_value=None)
            mock_ctx_engine.get_snapshot = AsyncMock(return_value=MagicMock())
            mock_ctx_scorer.score.return_value = ContextVerdict(
                verdict="WEAK", confidence=0.15, score=0.15,
            )

            await scan_symbol("BTC/USDT", "1h", AsyncMock())
            assert await _is_cooldown_active("BTC/USDT", "1h") is True


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
            mock_db.get_cooldown = AsyncMock(return_value=None)
            mock_db.set_cooldown = AsyncMock()
            mock_db.get_disabled_symbols = AsyncMock(return_value=[])
            await run_scan_cycle(AsyncMock())


class TestEntryPrice:
    @pytest.mark.asyncio
    async def test_entry_price_set_on_same_timeframe(self, mock_signal_result, mock_exchange, mock_ind_engine):
        mock_signal_result.entry_price = None
        mock_exchange.fetch_ohlcv.return_value = {"close": [50000.0]}
        from context.scorer import ContextVerdict
        with (
            patch("scheduler.scanner.exchange_client", mock_exchange),
            patch("scheduler.scanner.indicator_engine", mock_ind_engine),
            patch("scheduler.scanner.signal_engine") as mock_sig,
            patch("scheduler.scanner.db") as mock_db,
            patch("scheduler.scanner.config.trading.confirm_timeframe", "1h"),
            patch("scheduler.scanner.context_engine") as mock_ctx_engine,
            patch("scheduler.scanner.context_scorer") as mock_ctx_scorer,
        ):
            mock_sig.evaluate.return_value = mock_signal_result
            mock_db.save_signal = AsyncMock()
            mock_db.create_outcome = AsyncMock()
            mock_db.get_cooldown = AsyncMock(return_value=None)
            mock_db.set_cooldown = AsyncMock()
            mock_db.get_last_signal = AsyncMock(return_value=None)
            mock_ctx_engine.get_snapshot = AsyncMock(return_value=MagicMock())
            mock_ctx_scorer.score.return_value = ContextVerdict(
                verdict="WEAK", confidence=0.15, score=0.15,
            )
            result = await scan_symbol("BTC/USDT", "1h", AsyncMock())
            assert result is not None
            assert result.entry_price == 50000.0

    @pytest.mark.asyncio
    async def test_entry_price_from_confirm_candle(self, mock_signal_result, mock_exchange, mock_ind_engine):
        mock_signal_result.entry_price = None
        confirm_close = 50100.0
        confirm_ind = MagicMock()
        confirm_ind.close = confirm_close
        confirm_ind.atr = 1000.0
        confirm_ind.volume = 1200.0
        confirm_ind.volume_sma = 1000.0
        confirm_ind.volume_above_avg = True
        confirm_ind.rsi = 55.0
        confirm_ind.macd_hist = 30.0
        confirm_ind.adx = 30.0
        confirm_ind.dmi_plus = 25.0
        confirm_ind.dmi_minus = 15.0
        confirm_ind.ema_fast = 50200.0
        confirm_ind.ema_slow = 50000.0
        from strategy.signal_engine import SignalResult, SignalType
        confirm_sig = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT",
            timeframe="15m", close=confirm_close, score=6, reasons=[],
        )
        from context.scorer import ContextVerdict
        with (
            patch("scheduler.scanner.exchange_client", mock_exchange),
            patch("scheduler.scanner.indicator_engine", mock_ind_engine),
            patch("scheduler.scanner.signal_engine") as mock_sig,
            patch("scheduler.scanner.db") as mock_db,
            patch("scheduler.scanner.config.trading.confirm_timeframe", "15m"),
            patch("scheduler.scanner.context_engine") as mock_ctx_engine,
            patch("scheduler.scanner.context_scorer") as mock_ctx_scorer,
        ):
            mock_sig.evaluate.side_effect = [mock_signal_result, confirm_sig]
            mock_ind_engine.calculate.return_value = confirm_ind
            mock_db.save_signal = AsyncMock()
            mock_db.create_outcome = AsyncMock()
            mock_db.get_cooldown = AsyncMock(return_value=None)
            mock_db.set_cooldown = AsyncMock()
            mock_db.get_last_signal = AsyncMock(return_value=None)
            mock_ctx_engine.get_snapshot = AsyncMock(return_value=MagicMock())
            mock_ctx_scorer.score.return_value = ContextVerdict(
                verdict="WEAK", confidence=0.15, score=0.15,
            )
            result = await scan_symbol("BTC/USDT", "1h", AsyncMock())
            assert result is not None
            assert result.entry_price == confirm_close

    @pytest.mark.asyncio
    async def test_entry_price_from_close_when_no_confirm_data(self, mock_signal_result, mock_exchange, mock_ind_engine):
        from context.scorer import ContextVerdict
        mock_signal_result.entry_price = None
        async def flexible_fetch(*args, **kwargs):
            tf = args[1] if len(args) > 1 else kwargs.get("timeframe", "")
            if tf == "15m":
                return None
            return {"close": [50000.0]}
        mock_exchange.fetch_ohlcv.side_effect = flexible_fetch
        with (
            patch("scheduler.scanner.exchange_client", mock_exchange),
            patch("scheduler.scanner.indicator_engine", mock_ind_engine),
            patch("scheduler.scanner.signal_engine") as mock_sig,
            patch("scheduler.scanner.db") as mock_db,
            patch("scheduler.scanner.config.trading.confirm_timeframe", "15m"),
            patch("scheduler.scanner.context_engine") as mock_ctx_engine,
            patch("scheduler.scanner.context_scorer") as mock_ctx_scorer,
        ):
            mock_sig.evaluate.return_value = mock_signal_result
            mock_db.save_signal = AsyncMock()
            mock_db.create_outcome = AsyncMock()
            mock_db.get_cooldown = AsyncMock(return_value=None)
            mock_db.set_cooldown = AsyncMock()
            mock_db.get_last_signal = AsyncMock(return_value=None)
            mock_ctx_engine.get_snapshot = AsyncMock(return_value=MagicMock())
            mock_ctx_scorer.score.return_value = ContextVerdict(
                verdict="WEAK", confidence=0.15, score=0.15,
            )
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
            mock_sig.evaluate_confirm.return_value = False
            mock_db.save_signal = AsyncMock()
            mock_db.get_cooldown = AsyncMock(return_value=None)
            mock_db.set_cooldown = AsyncMock()
            result = await scan_symbol("BTC/USDT", "1h", AsyncMock())
            assert result is None


class TestMinVerdictGate:
    @pytest.mark.asyncio
    async def test_scan_blocks_on_below_min_verdict(self, mock_signal_result, mock_cooldown, monkeypatch):
        from scheduler import scanner as sc
        from context.scorer import ContextVerdict

        fake_result = MagicMock(is_actionable=True, signal=MagicMock(value="BUY"),
                                reasons=[], close=100.0)
        monkeypatch.setattr(sc.signal_engine, "evaluate", lambda ind, **kw: fake_result)
        monkeypatch.setattr(sc, "_get_indicators",
                            AsyncMock(return_value=(_make_ind_mock(), MagicMock())))
        monkeypatch.setattr(
            sc.context_scorer, "score",
            lambda direction, snap: ContextVerdict(
                verdict="CONFLICTED", confidence=0.05, score=0.0,
            ),
        )
        monkeypatch.setattr(
            sc.context_engine, "get_snapshot",
            AsyncMock(return_value=MagicMock()),
        )
        monkeypatch.setattr(sc.config, "context_min_verdict", "WEAK")
        monkeypatch.setattr(sc.config, "context_enabled", True)

        cb = AsyncMock()
        result = await sc.scan_symbol("BTC/USDT", "1h", cb)
        assert result is None
        cb.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_scan_passes_when_verdict_meets_min(self, mock_signal_result, mock_cooldown, monkeypatch):
        from scheduler import scanner as sc
        from context.scorer import ContextVerdict
        from strategy.signal_engine import SignalResult, SignalType

        real_result = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT",
            timeframe="1h", close=50000.0, sl=48500.0, tp=53000.0,
            score=6, reasons=["test"],
        )
        monkeypatch.setattr(sc.signal_engine, "evaluate", lambda ind, **kw: real_result)
        monkeypatch.setattr(sc.signal_engine, "evaluate_confirm", lambda ind, direction: True)
        monkeypatch.setattr(sc, "_get_indicators",
                            AsyncMock(return_value=(_make_ind_mock(), MagicMock())))
        monkeypatch.setattr(
            sc.context_scorer, "score",
            lambda direction, snap: ContextVerdict(
                verdict="WEAK", confidence=0.15, score=0.15,
            ),
        )
        monkeypatch.setattr(
            sc.context_engine, "get_snapshot",
            AsyncMock(return_value=MagicMock()),
        )
        monkeypatch.setattr(sc.config, "context_min_verdict", "WEAK")
        monkeypatch.setattr(sc.config, "context_enabled", True)
        monkeypatch.setattr(sc.config.market_structure, "mtf_enabled", False)
        monkeypatch.setattr(sc.db, "save_signal", AsyncMock())
        monkeypatch.setattr(sc.db, "create_outcome", AsyncMock())

        cb = AsyncMock()
        result = await sc.scan_symbol("BTC/USDT", "1h", cb)
        assert result is not None
        cb.assert_awaited()


class TestConfirmedFlag:
    @pytest.mark.asyncio
    async def test_confirmed_false_when_primary_eq_confirm(self, mock_signal_result, mock_cooldown, monkeypatch):
        from scheduler import scanner as sc
        from strategy.signal_engine import SignalResult, SignalType

        real_result = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT",
            timeframe="1h", close=50000.0, sl=48500.0, tp=53000.0,
            score=6, reasons=["test"],
        )
        monkeypatch.setattr(sc.signal_engine, "evaluate", lambda ind, **kw: real_result)
        monkeypatch.setattr(sc, "_get_indicators",
                            AsyncMock(return_value=(_make_ind_mock(), MagicMock())))
        monkeypatch.setattr(sc.config.trading, "confirm_timeframe", "1h")
        mock_save = AsyncMock(return_value=MagicMock(id=1))
        monkeypatch.setattr(sc.db, "save_signal", mock_save)
        monkeypatch.setattr(sc.config, "context_enabled", False)
        monkeypatch.setattr(sc.config.market_structure, "mtf_enabled", False)

        await sc.scan_symbol("BTC/USDT", "1h", AsyncMock())
        mock_save.assert_awaited_once()
        call_kwargs = mock_save.call_args.kwargs
        assert call_kwargs["confirmed"] is False

    @pytest.mark.asyncio
    async def test_confirmed_false_when_no_confirm_data(self, mock_signal_result, mock_cooldown, monkeypatch):
        from scheduler import scanner as sc
        from strategy.signal_engine import SignalResult, SignalType

        real_result = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT",
            timeframe="1h", close=50000.0, sl=48500.0, tp=53000.0,
            score=6, reasons=["test"],
        )
        monkeypatch.setattr(sc.signal_engine, "evaluate", lambda ind, **kw: real_result)

        async def fake_get_indicators(symbol, timeframe):
            if timeframe == "15m":
                return None
            return (_make_ind_mock(), MagicMock())

        monkeypatch.setattr(sc, "_get_indicators", fake_get_indicators)
        monkeypatch.setattr(sc.config.trading, "confirm_timeframe", "15m")
        mock_save = AsyncMock(return_value=MagicMock(id=1))
        monkeypatch.setattr(sc.db, "save_signal", mock_save)
        monkeypatch.setattr(sc.config, "context_enabled", False)
        monkeypatch.setattr(sc.config.market_structure, "mtf_enabled", False)

        await sc.scan_symbol("BTC/USDT", "1h", AsyncMock())
        mock_save.assert_awaited_once()
        call_kwargs = mock_save.call_args.kwargs
        assert call_kwargs["confirmed"] is False

    @pytest.mark.asyncio
    async def test_confirmed_true_when_15m_confirms(self, mock_signal_result, mock_cooldown, monkeypatch):
        from scheduler import scanner as sc
        from strategy.signal_engine import SignalResult, SignalType

        main_result = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT",
            timeframe="1h", close=50000.0, sl=48500.0, tp=53000.0,
            score=6, reasons=["test"],
        )
        confirm_result = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT",
            timeframe="15m", close=50100.0, sl=49000.0, tp=53500.0,
            score=6, reasons=["confirm"],
        )
        monkeypatch.setattr(sc.signal_engine, "evaluate",
                            lambda ind, **kw: main_result if hasattr(ind, 'timeframe') and getattr(ind, 'timeframe', None) != "15m" else confirm_result)
        monkeypatch.setattr(sc.signal_engine, "evaluate_confirm", lambda ind, direction: True)

        call_count = [0]
        async def fake_get_indicators(symbol, timeframe):
            call_count[0] += 1
            if timeframe == "15m":
                ind = MagicMock()
                ind.close = 50100.0
                ind.atr = 500.0
                ind.volume = 1200.0
                ind.volume_sma = 1000.0
                ind.volume_above_avg = True
                ind.rsi = 55.0
                ind.macd_hist = 30.0
                ind.adx = 30.0
                ind.dmi_plus = 25.0
                ind.dmi_minus = 15.0
                ind.ema_fast = 50200.0
                ind.ema_slow = 50000.0
                return (ind, MagicMock())
            return (_make_ind_mock(), MagicMock())

        monkeypatch.setattr(sc, "_get_indicators", fake_get_indicators)
        monkeypatch.setattr(sc.config.trading, "confirm_timeframe", "15m")
        mock_save = AsyncMock(return_value=MagicMock(id=1))
        monkeypatch.setattr(sc.db, "save_signal", mock_save)
        monkeypatch.setattr(sc.config, "context_enabled", False)
        monkeypatch.setattr(sc.config.market_structure, "mtf_enabled", False)

        await sc.scan_symbol("BTC/USDT", "1h", AsyncMock())
        mock_save.assert_awaited_once()
        call_kwargs = mock_save.call_args.kwargs
        assert call_kwargs["confirmed"] is True


# === News Filter Tests (Task 5) ===

class TestNewsFilter:
    @pytest.mark.asyncio
    async def test_news_filter_disabled_passes(self):
        """When NEWS_FILTER_ENABLED=false, no blocking occurs."""
        from risk.news_filter import check_news_block
        result = await check_news_block("BUY", entry_price=100.0)
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_news_filter_no_events_passes(self):
        """When no events are cached, no blocking occurs."""
        from risk.news_filter import check_news_block, _cache_events, _events_cache
        _cache_events([])
        result = await check_news_block("BUY", entry_price=100.0)
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_news_filter_blocks_during_event(self):
        """Signal blocked during high-impact event window."""
        from risk.news_filter import check_news_block, _cache_events, MacroEvent
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        event = MacroEvent(
            name="FOMC Rate Decision",
            timestamp=now,
            impact="high",
            currency="USD",
        )
        _cache_events([event])
        # Patch config to enable the filter
        import config.settings as settings_mod
        old_val = settings_mod.config.risk.news_filter_enabled
        settings_mod.config.risk.news_filter_enabled = True
        try:
            result = await check_news_block("BUY", entry_price=100.0)
            assert result.blocked is True
            assert "FOMC" in result.event_name
        finally:
            settings_mod.config.risk.news_filter_enabled = old_val

    @pytest.mark.asyncio
    async def test_news_filter_ignores_medium_impact(self):
        """Medium-impact events do not block signals."""
        from risk.news_filter import check_news_block, _cache_events, MacroEvent
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        event = MacroEvent(
            name="Retail Sales",
            timestamp=now,
            impact="medium",
            currency="USD",
        )
        _cache_events([event])
        import config.settings as settings_mod
        old_val = settings_mod.config.risk.news_filter_enabled
        settings_mod.config.risk.news_filter_enabled = True
        try:
            result = await check_news_block("BUY", entry_price=100.0)
            assert result.blocked is False
        finally:
            settings_mod.config.risk.news_filter_enabled = old_val

    @pytest.mark.asyncio
    async def test_news_filter_passes_outside_window(self):
        """Signal passes when event is outside the block window."""
        from risk.news_filter import check_news_block, _cache_events, MacroEvent
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        # Event 3 hours in the future — outside the 60min window
        event = MacroEvent(
            name="CPI",
            timestamp=now + timedelta(hours=3),
            impact="high",
            currency="USD",
        )
        _cache_events([event])
        import config.settings as settings_mod
        old_val = settings_mod.config.risk.news_filter_enabled
        settings_mod.config.risk.news_filter_enabled = True
        try:
            result = await check_news_block("BUY", entry_price=100.0)
            assert result.blocked is False
        finally:
            settings_mod.config.risk.news_filter_enabled = old_val
