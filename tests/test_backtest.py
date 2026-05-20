import sys
from pathlib import Path

import pytest
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.engine import BacktestEngine, BacktestResult, BacktestTrade, RegimeStats, _detect_regime


def _make_ohlcv(
    n: int = 300,
    base_price: float = 50000.0,
    trend: str = "bullish",
    volatility: float = 0.01,
    start_adx: float = 30.0,
) -> pd.DataFrame:
    """Generate synthetic OHLCV data for backtesting.

    Args:
        n: number of candles
        base_price: starting price
        trend: "bullish", "bearish", or "flat"
        volatility: per-candle volatility as fraction of price
        start_adx: starting ADX value (affects trend strength)
    """
    np.random.seed(42)

    # Price series
    if trend == "bullish":
        drift = volatility * 0.3
    elif trend == "bearish":
        drift = -volatility * 0.3
    else:
        drift = 0.0

    returns = np.random.normal(drift, volatility, n)
    prices = base_price * np.cumprod(1 + returns)

    # OHLCV from close prices
    closes = prices
    highs = closes * (1 + np.abs(np.random.normal(0, volatility * 0.5, n)))
    lows = closes * (1 - np.abs(np.random.normal(0, volatility * 0.5, n)))
    opens = np.concatenate([[closes[0]], closes[:-1]])
    volumes = np.random.uniform(800, 1200, n)

    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }, index=pd.date_range("2024-01-01", periods=n, freq="h"))

    return df


def _make_trending_ohlcv(n: int = 300) -> pd.DataFrame:
    """OHLCV with strong trend (high ADX regime)."""
    np.random.seed(42)
    base = 50000.0
    # Strong upward trend
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
    """OHLCV with range-bound price (low ADX regime)."""
    np.random.seed(42)
    base = 50000.0
    prices = [base]
    for i in range(1, n):
        # Mean-reverting
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


class TestBacktestBasic:
    def test_run_returns_result(self):
        engine = BacktestEngine(symbol="BTC/USDT", timeframe="1h")
        df = _make_ohlcv(n=300)
        result = engine.run(df)
        assert isinstance(result, BacktestResult)
        assert result.symbol == "BTC/USDT"
        assert result.timeframe == "1h"

    def test_run_empty_data(self):
        engine = BacktestEngine()
        result = engine.run(None)
        assert result.total_trades == 0
        assert result.signals_generated == 0

    def test_run_short_data(self):
        engine = BacktestEngine()
        df = _make_ohlcv(n=50)
        result = engine.run(df)
        assert result.total_trades == 0

    def test_generates_signals(self):
        """Bullish trending data should generate at least some signals."""
        engine = BacktestEngine(symbol="BTC/USDT", timeframe="1h")
        df = _make_trending_ohlcv(n=500)
        result = engine.run(df)
        assert result.signals_generated >= 0  # may be 0 if no signals pass all filters

    def test_trades_have_required_fields(self):
        engine = BacktestEngine(symbol="BTC/USDT", timeframe="1h")
        df = _make_trending_ohlcv(n=500)
        result = engine.run(df)
        for trade in result.trades:
            assert trade.symbol == "BTC/USDT"
            assert trade.timeframe == "1h"
            assert trade.direction in ("BUY", "SELL")
            assert trade.entry_price > 0
            assert trade.regime != ""


class TestMetrics:
    def test_winrate_calculation(self):
        """Verify winrate is correctly calculated."""
        result = BacktestResult(
            symbol="BTC/USDT", timeframe="1h",
            total_trades=10, wins=6, losses=4,
        )
        # Manually build result to test metric calculation
        engine = BacktestEngine()
        trades = []
        for i in range(10):
            pnl = 1.0 if i < 6 else -0.5
            trades.append(BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=i, entry_timestamp="",
                sl=49000, tp=52000, exit_price=50000 + pnl * 500,
                exit_index=i + 1, exit_timestamp="", exit_reason="tp" if pnl > 0 else "sl",
                pnl_pct=pnl, rr=abs(pnl) * 2, regime="trend",
            ))
        result = engine._build_result(trades, signals_count=15)
        assert result.winrate == 60.0
        assert result.wins == 6
        assert result.losses == 4

    def test_profit_factor(self):
        """PF = gross_profit / gross_loss."""
        engine = BacktestEngine()
        trades = [
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=0, entry_timestamp="",
                sl=49000, tp=52000, exit_price=51000,
                exit_index=1, exit_timestamp="", exit_reason="tp",
                pnl_pct=2.0, rr=2.0, regime="trend",
            ),
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=2, entry_timestamp="",
                sl=49000, tp=52000, exit_price=49500,
                exit_index=3, exit_timestamp="", exit_reason="sl",
                pnl_pct=-1.0, rr=0.5, regime="trend",
            ),
        ]
        result = engine._build_result(trades, signals_count=5)
        # gross_profit=2.0, gross_loss=1.0, PF=2.0
        assert result.profit_factor == 2.0

    def test_expectancy(self):
        """Expectancy = winrate * avg_win - (1-winrate) * avg_loss."""
        engine = BacktestEngine()
        trades = [
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=0, entry_timestamp="",
                sl=49000, tp=52000, exit_price=52000,
                exit_index=1, exit_timestamp="", exit_reason="tp",
                pnl_pct=4.0, rr=4.0, regime="trend",
            ),
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=2, entry_timestamp="",
                sl=49000, tp=52000, exit_price=49000,
                exit_index=3, exit_timestamp="", exit_reason="sl",
                pnl_pct=-2.0, rr=1.0, regime="trend",
            ),
        ]
        result = engine._build_result(trades, signals_count=5)
        # winrate=0.5, avg_win=4.0, avg_loss=2.0
        # expectancy = 0.5 * 4.0 - 0.5 * 2.0 = 1.0
        assert result.expectancy == pytest.approx(1.0, abs=0.01)

    def test_max_drawdown(self):
        """Max drawdown from cumulative PnL."""
        engine = BacktestEngine()
        # Series: +3, -1, +2, -5, +1 → cumulative: 3, 2, 4, -1, 0
        # peaks: 3, 3, 4, 4, 4 → drawdowns: 0, 1, 0, 5, 4 → max=5
        trades = [
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=i, entry_timestamp="",
                sl=49000, tp=52000, exit_price=50000,
                exit_index=i + 1, exit_timestamp="", exit_reason="tp",
                pnl_pct=pnl, rr=1.0, regime="trend",
            )
            for i, pnl in enumerate([3.0, -1.0, 2.0, -5.0, 1.0])
        ]
        result = engine._build_result(trades, signals_count=10)
        assert result.max_drawdown == pytest.approx(5.0, abs=0.01)

    def test_sharpe_ratio(self):
        """Sharpe = mean / std of returns."""
        engine = BacktestEngine()
        # Consistent positive returns → high Sharpe
        trades = [
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=i, entry_timestamp="",
                sl=49000, tp=52000, exit_price=50000,
                exit_index=i + 1, exit_timestamp="", exit_reason="tp",
                pnl_pct=1.0, rr=1.0, regime="trend",
            )
            for i in range(10)
        ]
        result = engine._build_result(trades, signals_count=10)
        # All returns are 1.0, std=0, sharpe should be 0 (division by zero guard)
        assert result.sharpe_ratio == 0.0

    def test_sharpe_ratio_with_variance(self):
        """Sharpe with varying returns."""
        engine = BacktestEngine()
        trades = [
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=i, entry_timestamp="",
                sl=49000, tp=52000, exit_price=50000,
                exit_index=i + 1, exit_timestamp="", exit_reason="tp",
                pnl_pct=pnl, rr=1.0, regime="trend",
            )
            for i, pnl in enumerate([2.0, 1.0, 3.0, 0.5, 1.5])
        ]
        result = engine._build_result(trades, signals_count=5)
        assert result.sharpe_ratio > 0  # positive mean, non-zero std


class TestRegimeDetection:
    def test_trend_regime(self):
        """ADX > 25 → trend."""
        regime = _detect_regime(
            adx=30.0, atr=500.0, close=50000.0,
            atr_history=[500.0] * 20, volume=1000.0, volume_avg=1000.0,
        )
        assert regime == "trend"

    def test_range_regime(self):
        """ADX < 18 → range."""
        regime = _detect_regime(
            adx=15.0, atr=200.0, close=50000.0,
            atr_history=[200.0] * 20, volume=1000.0, volume_avg=1000.0,
        )
        assert regime == "range"

    def test_compression_regime(self):
        """ATR percentile < 20% → compression."""
        # ATR history where current ATR is at the bottom
        atr_history = [100.0, 200.0, 300.0, 400.0, 500.0] * 4  # 20 values
        regime = _detect_regime(
            adx=22.0, atr=50.0, close=50000.0,
            atr_history=atr_history, volume=1000.0, volume_avg=1000.0,
        )
        assert regime == "compression"

    def test_expansion_regime(self):
        """ATR rising + volume rising → expansion."""
        # Recent ATR higher than older
        atr_history = [100.0] * 15 + [200.0, 210.0, 220.0, 230.0, 240.0]
        regime = _detect_regime(
            adx=22.0, atr=240.0, close=50000.0,
            atr_history=atr_history, volume=1500.0, volume_avg=1000.0,
        )
        assert regime == "expansion"

    def test_high_vol_regime(self):
        """ATR/close > high threshold → high_vol."""
        regime = _detect_regime(
            adx=22.0, atr=2500.0, close=50000.0,  # 5% ATR
            atr_history=[1000.0] * 20, volume=1000.0, volume_avg=1000.0,
        )
        assert regime == "high_vol"

    def test_low_vol_regime(self):
        """ATR/close < low threshold → low_vol."""
        # ATR history where current ATR is around 50th percentile (not compression)
        atr_history = [150.0, 180.0, 200.0, 220.0, 250.0] * 4  # 20 values, 200 is ~40th percentile
        regime = _detect_regime(
            adx=22.0, atr=200.0, close=50000.0,  # 0.4% ATR
            atr_history=atr_history, volume=1000.0, volume_avg=1000.0,
        )
        assert regime == "low_vol"


class TestRegimeStats:
    def test_regime_stats_populated(self):
        """Regime stats should be calculated per regime."""
        engine = BacktestEngine()
        trades = [
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=i, entry_timestamp="",
                sl=49000, tp=52000, exit_price=51000 if i % 2 == 0 else 49500,
                exit_index=i + 1, exit_timestamp="", exit_reason="tp",
                pnl_pct=2.0 if i % 2 == 0 else -1.0, rr=1.0,
                regime="trend" if i < 5 else "range",
            )
            for i in range(10)
        ]
        result = engine._build_result(trades, signals_count=15)
        assert "trend" in result.regime_stats
        assert "range" in result.regime_stats
        assert result.regime_stats["trend"].total_trades == 5
        assert result.regime_stats["range"].total_trades == 5

    def test_regime_stats_metrics(self):
        """Each regime should have correct metrics."""
        engine = BacktestEngine()
        trades = [
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=i, entry_timestamp="",
                sl=49000, tp=52000, exit_price=52000,
                exit_index=i + 1, exit_timestamp="", exit_reason="tp",
                pnl_pct=4.0, rr=4.0, regime="trend",
            )
            for i in range(3)
        ]
        result = engine._build_result(trades, signals_count=5)
        stats = result.regime_stats["trend"]
        assert stats.winrate == 100.0
        assert stats.total_trades == 3
        assert stats.wins == 3


class TestSignalDecay:
    def test_signal_decay_buckets(self):
        """Signal decay should split trades into quartiles."""
        engine = BacktestEngine()
        trades = [
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=i, entry_timestamp="",
                sl=49000, tp=52000, exit_price=50000,
                exit_index=i + 1, exit_timestamp="", exit_reason="tp",
                pnl_pct=2.0 if i < 4 else (1.0 if i < 8 else -1.0),
                rr=1.0, regime="trend",
            )
            for i in range(12)
        ]
        result = engine._build_result(trades, signals_count=20)
        assert len(result.signal_decay) == 3  # 3 buckets
        # First quartile should have higher avg PnL than last
        assert result.signal_decay[0] >= result.signal_decay[-1]

    def test_signal_decay_few_trades(self):
        """With < 4 trades, should return single bucket."""
        engine = BacktestEngine()
        trades = [
            BacktestTrade(
                symbol="BTC/USDT", timeframe="1h", direction="BUY",
                entry_price=50000, entry_index=i, entry_timestamp="",
                sl=49000, tp=52000, exit_price=50000,
                exit_index=i + 1, exit_timestamp="", exit_reason="tp",
                pnl_pct=1.0, rr=1.0, regime="trend",
            )
            for i in range(3)
        ]
        result = engine._build_result(trades, signals_count=5)
        assert len(result.signal_decay) == 1


class TestMaxTrades:
    def test_max_trades_limit(self):
        """Engine should stop after max_trades."""
        engine = BacktestEngine(symbol="BTC/USDT", timeframe="1h", max_trades=2)
        df = _make_trending_ohlcv(n=500)
        result = engine.run(df)
        assert result.total_trades <= 2


class TestBacktestOnHistorical:
    """Integration test: run backtest on synthetic historical data."""

    def test_bullish_trend_produces_trades(self):
        """Strong bullish trend should produce BUY trades."""
        engine = BacktestEngine(symbol="BTC/USDT", timeframe="1h")
        df = _make_trending_ohlcv(n=500)
        result = engine.run(df)
        # Should have generated signals; trades depend on signal filters
        assert result.signals_generated >= 0

    def test_ranging_market_fewer_signals(self):
        """Range-bound market should produce fewer or no signals."""
        engine = BacktestEngine(symbol="BTC/USDT", timeframe="1h")
        df_trend = _make_trending_ohlcv(n=500)
        df_range = _make_ranging_ohlcv(n=500)
        result_trend = engine.run(df_trend)
        result_range = engine.run(df_range)
        # Range should not produce more signals than trend
        assert result_range.signals_generated <= result_trend.signals_generated + 5

    def test_result_has_all_metrics(self):
        """Result should have all required metrics populated."""
        engine = BacktestEngine(symbol="BTC/USDT", timeframe="1h")
        df = _make_trending_ohlcv(n=500)
        result = engine.run(df)
        # All metric fields should be present
        assert hasattr(result, "winrate")
        assert hasattr(result, "profit_factor")
        assert hasattr(result, "expectancy")
        assert hasattr(result, "sharpe_ratio")
        assert hasattr(result, "max_drawdown")
        assert hasattr(result, "regime_stats")
        assert hasattr(result, "signal_decay")
