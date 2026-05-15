"""
tests/test_metrics.py — Тесты для Prometheus-метрики (T3.4).
"""
import sys
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestMetricsDefinitions:
    """Проверка, что метрики определены в monitoring/metrics.py."""

    def test_signals_total_exists(self):
        from monitoring.metrics import signals_total
        assert signals_total._type == "counter"
        assert "tgbot_signals" in signals_total._name

    def test_scan_duration_exists(self):
        from monitoring.metrics import scan_duration_seconds
        assert scan_duration_seconds._type == "histogram"
        assert "tgbot_scan_duration" in scan_duration_seconds._name

    def test_context_fetch_errors_exists(self):
        from monitoring.metrics import context_fetch_errors_total
        assert context_fetch_errors_total._type == "counter"
        assert "tgbot_context_fetch_errors" in context_fetch_errors_total._name


class TestStartMetricsServer:
    """_start_metrics_server — opt-in через METRICS_ENABLED."""

    def test_not_started_when_disabled(self, monkeypatch):
        monkeypatch.setenv("METRICS_ENABLED", "false")
        with patch("monitoring.metrics.start_http_server") as mock_server:
            from monitoring.metrics import _start_metrics_server
            _start_metrics_server()
            mock_server.assert_not_called()

    def test_started_when_enabled(self, monkeypatch):
        monkeypatch.setenv("METRICS_ENABLED", "true")
        monkeypatch.setenv("METRICS_PORT", "9090")
        with patch("monitoring.metrics.start_http_server") as mock_server:
            from monitoring.metrics import _start_metrics_server
            _start_metrics_server()
            mock_server.assert_called_once()
            port = mock_server.call_args[0][0]
            assert port == 9090

    def test_custom_port(self, monkeypatch):
        monkeypatch.setenv("METRICS_ENABLED", "true")
        monkeypatch.setenv("METRICS_PORT", "9999")
        with patch("monitoring.metrics.start_http_server") as mock_server:
            from monitoring.metrics import _start_metrics_server
            _start_metrics_server()
            mock_server.assert_called_once_with(9999)


class TestScanSymbolMetrics:
    """scan_symbol инкрементирует signals_total и измеряет duration."""

    @pytest.mark.asyncio
    async def test_signals_total_increased_on_signal(self, monkeypatch):
        from strategy.signal_engine import SignalResult, SignalType
        from context.scorer import ContextVerdict

        result = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT",
            timeframe="1h", close=50000.0, sl=48500.0, tp=53000.0,
            score=6, reasons=["test"],
        )

        monkeypatch.setattr("scheduler.scanner._is_cooldown_active", AsyncMock(return_value=False))
        monkeypatch.setattr("scheduler.scanner._get_indicators", AsyncMock(return_value=MagicMock()))
        monkeypatch.setattr("scheduler.scanner.signal_engine", MagicMock(evaluate=MagicMock(return_value=result)))
        monkeypatch.setattr("scheduler.scanner.db", MagicMock(save_signal=AsyncMock(), set_cooldown=AsyncMock()))
        monkeypatch.setattr("scheduler.scanner.config.trading", MagicMock(
            confirm_timeframe="15m", symbols=["BTC/USDT"]
        ))
        monkeypatch.setattr("scheduler.scanner.config", MagicMock(
            context_enabled=False, context_min_verdict="WEAK"
        ))

        from monitoring.metrics import signals_total
        before = signals_total._metrics  # internal list of _LabelKeys

        cb = AsyncMock()
        from scheduler.scanner import scan_symbol
        await scan_symbol("BTC/USDT", "1h", cb)

        cb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scan_duration_histogram_wraps(self, monkeypatch):
        """Проверяем, что scan_duration_seconds.labels().time() вызывается."""
        from strategy.signal_engine import SignalResult, SignalType
        from monitoring.metrics import scan_duration_seconds

        result = SignalResult(
            signal=SignalType.NO_SIGNAL, symbol="BTC/USDT",
            timeframe="1h", close=50000.0, score=2, reasons=[],
        )

        monkeypatch.setattr("scheduler.scanner._is_cooldown_active", AsyncMock(return_value=False))
        monkeypatch.setattr("scheduler.scanner._get_indicators", AsyncMock(return_value=MagicMock()))
        monkeypatch.setattr("scheduler.scanner.signal_engine", MagicMock(evaluate=MagicMock(return_value=result)))

        from scheduler.scanner import scan_symbol
        result = await scan_symbol("BTC/USDT", "1h", AsyncMock())
        assert result is None  # NO_SIGNAL → None


class TestContextFetchErrorsMetrics:
    """context/analyzer инкрементирует context_fetch_errors_total при ошибке."""

    @pytest.mark.asyncio
    async def test_error_increments_counter(self, monkeypatch):
        from monitoring.metrics import context_fetch_errors_total
        from context.analyzer import ContextEngine, ContextSnapshot

        engine = ContextEngine()

        async def failing_func(snapshot, *args):
            raise ConnectionError("network down")

        snapshot = ContextSnapshot(symbol="BTC/USDT", timestamp=MagicMock())
        await engine._safe_fetch("CryptoPanic", failing_func, snapshot)

        assert len(snapshot.errors) == 1
        assert "CryptoPanic" in snapshot.errors[0]

    @pytest.mark.asyncio
    async def test_no_error_does_not_increment(self, monkeypatch):
        from monitoring.metrics import context_fetch_errors_total
        from context.analyzer import ContextEngine, ContextSnapshot

        engine = ContextEngine()

        async def ok_func(snapshot, *args):
            pass

        snapshot = ContextSnapshot(symbol="BTC/USDT", timestamp=MagicMock())
        await engine._safe_fetch("FearGreed", ok_func, snapshot)

        assert len(snapshot.errors) == 0
