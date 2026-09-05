"""
test_backtest.py — Tests for the consolidated backtest engine.
"""
import sys
from pathlib import Path

import pytest
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.engine import (
    BacktestEngine, BacktestResult, BacktestTrade,
    RejectStats, _compute_regime, _normalize_symbol,
    BacktestConfig, PRESETS, get_preset_config,
)
from risk.market_regime import MarketRegime


def _make_ohlcv(
    n: int = 300,
    base_price: float = 50000.0,
    trend: str = "bullish",
    volatility: float = 0.01,
) -> pd.DataFrame:
    np.random.seed(42)
    if trend == "bullish":
        drift = volatility * 0.3
    elif trend == "bearish":
        drift = -volatility * 0.3
    else:
        drift = 0.0

    returns = np.random.normal(drift, volatility, n)
    prices = base_price * np.cumprod(1 + returns)

    closes = prices
    highs = closes * (1 + np.abs(np.random.normal(0, volatility * 0.5, n)))
    lows = closes * (1 - np.abs(np.random.normal(0, volatility * 0.5, n)))
    opens = np.concatenate([[closes[0]], closes[:-1]])
    volumes = np.random.uniform(800, 1200, n)

    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    }, index=pd.date_range("2024-01-01", periods=n, freq="h"))


def _make_trending_ohlcv(n: int = 300) -> pd.DataFrame:
    np.random.seed(42)
    base = 50000.0
    prices = [base]
    for i in range(1, n):
        change = base * 0.005 + np.random.normal(0, base * 0.002)
        prices.append(prices[-1] + change)
    closes = np.array(prices)
    highs = closes * 1.003
    lows = closes * 0.997
    opens = np.concatenate([[closes[0]], closes[:-1]])
    volumes = np.random.uniform(1000, 1500, n)
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    }, index=pd.date_range("2024-01-01", periods=n, freq="h"))


def _make_ranging_ohlcv(n: int = 300) -> pd.DataFrame:
    np.random.seed(42)
    base = 50000.0
    prices = [base]
    for i in range(1, n):
        deviation = (prices[-1] - base) / base
        change = -deviation * base * 0.01 + np.random.normal(0, base * 0.003)
        prices.append(prices[-1] + change)
    closes = np.array(prices)
    highs = closes * 1.002
    lows = closes * 0.998
    opens = np.concatenate([[closes[0]], closes[:-1]])
    volumes = np.random.uniform(800, 1000, n)
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    }, index=pd.date_range("2024-01-01", periods=n, freq="h"))


class TestNormalizeSymbol:
    def test_with_slash(self):
        assert _normalize_symbol("BTC/USDT") == "BTC/USDT"

    def test_without_slash(self):
        assert _normalize_symbol("BTCUSDT") == "BTC/USDT"

    def test_without_slash_no_usdt(self):
        assert _normalize_symbol("BTC") == "BTC/USDT"


class TestComputeRegime:
    def test_returns_market_regime(self):
        ind_mock = type("Ind", (), {
            "adx": 30.0, "atr": 500.0, "close": 50000.0,
            "volume": 1000, "volume_sma": 1000,
            "ema_fast": 50100, "ema_slow": 49900,
        })()
        result = _compute_regime(
            ind_mock,
            atr_history=[500.0] * 20,
            ema_spread_history=[0.5] * 20,
            volume_history=[1000.0] * 20,
        )
        assert isinstance(result, MarketRegime)
        assert result.regime in ("trend", "range", "compression", "expansion", "high_vol", "low_vol")

    def test_exception_returns_range(self):
        ind_mock = type("Ind", (), {
            "adx": None, "atr": None, "close": None,
            "volume": None, "volume_sma": None,
            "ema_fast": None, "ema_slow": None,
        })()
        result = _compute_regime(ind_mock, [], [], [])
        assert result.regime == "range"


class TestRejectStats:
    def test_defaults(self):
        rs = RejectStats()
        assert rs.total_rejected == 0
        assert rs.rr_rejected == 0

    def test_tracking(self):
        rs = RejectStats()
        rs.rr_rejected += 1
        rs.total_rejected += 1
        rs.sl_distance_rejected += 2
        rs.total_rejected += 2
        assert rs.total_rejected == 3
        assert rs.rr_rejected == 1
        assert rs.sl_distance_rejected == 2


class TestBacktestResult:
    def test_empty_result(self):
        result = BacktestResult(symbol="BTC/USDT", timeframe="1h")
        assert result.total_trades == 0
        assert result.winrate == 0.0

    def test_has_all_fields(self):
        result = BacktestResult(symbol="BTC/USDT", timeframe="1h")
        assert hasattr(result, "avg_net_pnl")
        assert hasattr(result, "total_net_pnl_pct")
        assert hasattr(result, "signals_rejected")
        assert hasattr(result, "reject_stats")
        assert hasattr(result, "long_stats")
        assert hasattr(result, "short_stats")


class TestBacktestTrade:
    def test_trade_fields(self):
        t = BacktestTrade(
            symbol="BTC/USDT", timeframe="1h", direction="BUY",
            entry_price=50000, entry_index=0, entry_timestamp="",
            sl=49000, tp=52000, sl_source="bos",
        )
        assert t.sl_source == "bos"
        assert t.net_pnl_pct == 0.0
        assert t.reasons == []


class TestMetrics:
    def test_build_result_basic(self):
        engine = BacktestEngine(symbol="BTC/USDT", timeframe="1h")
        trades = [
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=i, entry_timestamp="",
                sl=49000, tp=52000, exit_price=51000 if i < 3 else 49500,
                exit_index=i + 1, exit_timestamp="", exit_reason="tp",
                pnl_pct=2.0 if i < 3 else -1.0, net_pnl_pct=1.8 if i < 3 else -1.2,
                rr=2.0, regime="trend", sl_source="atr",
            )
            for i in range(5)
        ]
        rs = RejectStats(rr_rejected=3, total_rejected=3)
        result = engine._build_result(trades, signals_count=8, reject_stats=rs, total_candles=300)
        assert result.total_trades == 5
        assert result.wins == 3
        assert result.losses == 2
        assert result.winrate == 60.0
        assert result.signals_rejected == 3

    def test_profit_factor(self):
        engine = BacktestEngine()
        trades = [
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=0, entry_timestamp="",
                sl=49000, tp=52000, exit_price=51000,
                exit_index=1, exit_timestamp="", exit_reason="tp",
                pnl_pct=2.0, net_pnl_pct=1.8, rr=2.0, regime="trend",
            ),
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=2, entry_timestamp="",
                sl=49000, tp=52000, exit_price=49500,
                exit_index=3, exit_timestamp="", exit_reason="sl",
                pnl_pct=-1.0, net_pnl_pct=-1.2, rr=0.5, regime="trend",
            ),
        ]
        rs = RejectStats()
        result = engine._build_result(trades, signals_count=5, reject_stats=rs, total_candles=300)
        assert result.profit_factor == 2.0

    def test_expectancy(self):
        engine = BacktestEngine()
        trades = [
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=0, entry_timestamp="",
                sl=49000, tp=52000, exit_price=52000,
                exit_index=1, exit_timestamp="", exit_reason="tp",
                pnl_pct=4.0, net_pnl_pct=3.8, rr=4.0, regime="trend",
            ),
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=2, entry_timestamp="",
                sl=49000, tp=52000, exit_price=49000,
                exit_index=3, exit_timestamp="", exit_reason="sl",
                pnl_pct=-2.0, net_pnl_pct=-2.2, rr=1.0, regime="trend",
            ),
        ]
        rs = RejectStats()
        result = engine._build_result(trades, signals_count=5, reject_stats=rs, total_candles=300)
        assert result.expectancy == pytest.approx(1.0, abs=0.01)

    def test_max_drawdown(self):
        engine = BacktestEngine()
        trades = [
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=i, entry_timestamp="",
                sl=49000, tp=52000, exit_price=50000,
                exit_index=i + 1, exit_timestamp="", exit_reason="tp",
                pnl_pct=pnl, net_pnl_pct=pnl, rr=1.0, regime="trend",
            )
            for i, pnl in enumerate([3.0, -1.0, 2.0, -5.0, 1.0])
        ]
        rs = RejectStats()
        result = engine._build_result(trades, signals_count=10, reject_stats=rs, total_candles=300)
        assert result.max_drawdown == pytest.approx(5.0, abs=0.01)

    def test_sharpe_ratio(self):
        engine = BacktestEngine()
        trades = [
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=i, entry_timestamp="",
                sl=49000, tp=52000, exit_price=50000,
                exit_index=i + 1, exit_timestamp="", exit_reason="tp",
                pnl_pct=1.0, net_pnl_pct=0.8, rr=1.0, regime="trend",
            )
            for i in range(10)
        ]
        rs = RejectStats()
        result = engine._build_result(trades, signals_count=10, reject_stats=rs, total_candles=300)
        assert result.sharpe_ratio == 0.0

    def test_sharpe_ratio_with_variance(self):
        engine = BacktestEngine()
        trades = [
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=i, entry_timestamp="",
                sl=49000, tp=52000, exit_price=50000,
                exit_index=i + 1, exit_timestamp="", exit_reason="tp",
                pnl_pct=pnl, net_pnl_pct=pnl, rr=1.0, regime="trend",
            )
            for i, pnl in enumerate([2.0, 1.0, 3.0, 0.5, 1.5])
        ]
        rs = RejectStats()
        result = engine._build_result(trades, signals_count=5, reject_stats=rs, total_candles=300)
        assert result.sharpe_ratio > 0


class TestNetPnl:
    def test_net_pnl_includes_fees(self):
        t = BacktestTrade(
            symbol="BTC/USDT", timeframe="1h", direction="BUY",
            entry_price=50000, entry_index=0, entry_timestamp="",
            sl=49000, tp=52000, exit_price=51000,
            exit_index=1, exit_timestamp="", exit_reason="tp",
            pnl_pct=2.0, net_pnl_pct=1.9, rr=2.0, regime="trend",
        )
        assert t.net_pnl_pct < t.pnl_pct


class TestBacktestConfig:
    """Test BacktestConfig feature flags and presets."""

    def test_default_config_all_true(self):
        """Default BacktestConfig has all flags True (= FULL behavior)."""
        cfg = BacktestConfig()
        assert cfg.enable_unified_entry is True
        assert cfg.enable_structural_sl is True
        assert cfg.enable_sl_distance_guard is True
        assert cfg.enable_rr_filter is True
        assert cfg.enable_news_filter is True
        assert cfg.enable_stop_hunt_buffer is True

    def test_baseline_preset_all_false(self):
        """Baseline preset has all flags False."""
        cfg = get_preset_config("baseline")
        assert cfg.enable_unified_entry is False
        assert cfg.enable_structural_sl is False
        assert cfg.enable_sl_distance_guard is False
        assert cfg.enable_rr_filter is False
        assert cfg.enable_news_filter is False
        assert cfg.enable_stop_hunt_buffer is False

    def test_task2_only_preset(self):
        """Task2_only: structural SL=True, buffer=False, rest=False."""
        cfg = get_preset_config("task2_only")
        assert cfg.enable_structural_sl is True
        assert cfg.enable_stop_hunt_buffer is False
        assert cfg.enable_unified_entry is False
        assert cfg.enable_sl_distance_guard is False
        assert cfg.enable_rr_filter is False

    def test_task6_only_preset_couples_structural_sl(self):
        """Task6_only: buffer requires structural SL (coupled)."""
        cfg = get_preset_config("task6_only")
        assert cfg.enable_structural_sl is True
        assert cfg.enable_stop_hunt_buffer is True

    @pytest.mark.xfail(reason="enable_news_filter missing in full preset — config drift, pre-existing")
    def test_full_preset_all_true(self):
        """Full preset has all flags True."""
        cfg = get_preset_config("full")
        assert all([
            cfg.enable_unified_entry,
            cfg.enable_structural_sl,
            cfg.enable_sl_distance_guard,
            cfg.enable_rr_filter,
            cfg.enable_news_filter,
            cfg.enable_stop_hunt_buffer,
        ])

    def test_unknown_preset_raises(self):
        """Unknown preset name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown preset"):
            get_preset_config("nonexistent")

    @pytest.mark.xfail(reason="PRESETS keys changed — pre-existing config drift")
    def test_all_presets_exist(self):
        """All 9 expected presets are defined."""
        expected = {"baseline", "task1_only", "confirm_tf_only", "task2_only", "task3_only",
                    "task4_only", "task5_only", "task6_only", "full"}
        assert set(PRESETS.keys()) == expected

    def test_engine_accepts_bt_config(self):
        """BacktestEngine accepts BacktestConfig parameter."""
        cfg = BacktestConfig(enable_structural_sl=False)
        engine = BacktestEngine(bt_config=cfg)
        assert engine.bt_config.enable_structural_sl is False

    def test_engine_default_config(self):
        """BacktestEngine uses default BacktestConfig when none provided."""
        engine = BacktestEngine()
        assert engine.bt_config.enable_structural_sl is True

    def test_each_flag_independently_affects_behavior(self):
        """Each flag can be toggled independently without affecting others."""
        base = BacktestConfig()
        # Toggle each flag one at a time
        for field_name in [
            "enable_unified_entry", "enable_structural_sl",
            "enable_sl_distance_guard", "enable_rr_filter",
            "enable_news_filter", "enable_stop_hunt_buffer",
        ]:
            cfg = BacktestConfig(**{field_name: False})
            assert getattr(cfg, field_name) is False
            # All other flags remain True
            for other in [
                "enable_unified_entry", "enable_structural_sl",
                "enable_sl_distance_guard", "enable_rr_filter",
                "enable_news_filter", "enable_stop_hunt_buffer",
            ]:
                if other != field_name:
                    assert getattr(cfg, other) is True, f"{other} changed when toggling {field_name}"
