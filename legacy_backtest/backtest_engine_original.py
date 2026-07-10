"""
backtest/engine.py — Backtest engine for validating signal strategy on historical OHLCV data.

Walks through candles progressively (no lookahead bias), computes indicators via
IndicatorEngine, evaluates signals via SignalEngine, simulates trades with SL/TP,
and calculates performance metrics split by market regime.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Optional

import numpy as np
import pandas as pd

from config.settings import config
from indicators.engine import IndicatorEngine, IndicatorValues
from strategy.signal_engine import SignalEngine, SignalType
from risk.market_regime import MarketRegime


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BacktestTrade:
    """Single simulated trade."""
    symbol: str
    timeframe: str
    direction: Literal["BUY", "SELL"]
    entry_price: float
    entry_index: int
    entry_timestamp: str
    sl: float
    tp: float
    exit_price: Optional[float] = None
    exit_index: Optional[int] = None
    exit_timestamp: Optional[str] = None
    exit_reason: Optional[str] = None  # "tp", "sl", "eob"
    pnl_pct: float = 0.0
    rr: float = 0.0
    regime: str = ""  # trend, range, compression, expansion, high_vol, low_vol
    signal_score: int = 0
    confidence: float = 0.0
    verdict: str = ""  # "STRONG", "MODERATE", "WEAK", "VERY WEAK"
    factor_strengths: dict[str, float] = field(default_factory=dict)  # name → [-1.0, 1.0]
    factor_present: dict[str, bool] = field(default_factory=dict)  # name → True if contributed positively


@dataclass
class RegimeStats:
    """Performance stats for a single regime."""
    regime: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    winrate: float = 0.0
    avg_pnl: float = 0.0
    avg_rr: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    max_drawdown: float = 0.0


@dataclass
class BacktestResult:
    """Aggregate backtest result."""
    symbol: str
    timeframe: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    winrate: float = 0.0
    avg_pnl: float = 0.0
    avg_rr: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    total_pnl_pct: float = 0.0
    signals_generated: int = 0
    exposure_time_pct: float = 0.0       # time in market %
    avg_trade_duration: float = 0.0      # average trade duration in candles
    regime_stats: dict[str, RegimeStats] = field(default_factory=dict)
    long_stats: Optional[RegimeStats] = None   # BUY trades breakdown
    short_stats: Optional[RegimeStats] = None  # SELL trades breakdown
    volatility_stats: dict[str, RegimeStats] = field(default_factory=dict)  # low/medium/high vol
    trades: list[BacktestTrade] = field(default_factory=list)
    signal_decay: list[float] = field(default_factory=list)  # avg PnL by trade index bucket


# ---------------------------------------------------------------------------
# Regime detection (lightweight, inline — no external dependency)
# ---------------------------------------------------------------------------

def _detect_regime(
    adx: float,
    atr: float,
    close: float,
    atr_history: list[float],
    volume: float,
    volume_avg: float,
) -> str:
    """Detect market regime from indicator snapshot.

    Regimes (priority order):
    - compression: ATR percentile < 20%
    - expansion:   ATR rising + volume rising
    - trend:       ADX > 25
    - range:       ADX < 18
    - high_vol:    ATR/close > high threshold
    - low_vol:     ATR/close < low threshold
    """
    atr_pct = (atr / close * 100) if close > 0 else 0.0

    # ATR percentile from history
    if len(atr_history) >= 20:
        atr_percentile = sum(1 for a in atr_history if a <= atr) / len(atr_history) * 100
    else:
        atr_percentile = 50.0

    # Compression
    if atr_percentile < 20:
        return "compression"

    # Expansion
    if len(atr_history) >= 5:
        recent_atr = np.mean(atr_history[-5:])
        older_atr = np.mean(atr_history[-20:-5]) if len(atr_history) >= 20 else recent_atr * 0.9
        atr_rising = recent_atr > older_atr
        vol_rising = volume > volume_avg * 1.2
        if atr_rising and vol_rising:
            return "expansion"

    # Trend / Range
    if adx > 25:
        return "trend"
    if adx < 18:
        return "range"

    # Volatility-based
    vol_high = getattr(config.risk, "volatility_high_threshold", 4.0)
    vol_low = getattr(config.risk, "volatility_low_threshold", 1.0)
    if atr_pct > vol_high:
        return "high_vol"
    if atr_pct < vol_low:
        return "low_vol"

    return "trend"  # default


# ---------------------------------------------------------------------------
# Backtest Engine
# ---------------------------------------------------------------------------

class BacktestEngine:
    """Runs signal strategy on historical OHLCV data and measures performance."""

    def __init__(
        self,
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        max_trades: int = 0,  # 0 = unlimited
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.max_trades = max_trades
        self._indicator_engine = IndicatorEngine()
        self._signal_engine = SignalEngine()

    def run(self, df: pd.DataFrame) -> BacktestResult:
        """Run backtest on OHLCV DataFrame.

        Args:
            df: DataFrame with columns [open, high, low, close, volume].
                Index should be datetime-like. Must have >= 100 candles.

        Returns:
            BacktestResult with metrics and individual trades.
        """
        if df is None or len(df) < 100:
            return BacktestResult(
                symbol=self.symbol,
                timeframe=self.timeframe,
            )

        trades: list[BacktestTrade] = []
        atr_history: list[float] = []
        signals_count = 0
        in_trade = False
        current_trade: Optional[BacktestTrade] = None

        # Walk through candles with a rolling window
        # We need enough history for indicators to warm up
        warmup = 60  # minimum candles for indicator calculation
        min_window = max(warmup, config.trading.candles_limit // 2)

        for i in range(min_window, len(df)):
            window = df.iloc[:i + 1]  # all candles up to current (inclusive)

            # Compute indicators on the rolling window
            ind = self._indicator_engine.calculate(window.copy(), self.symbol, self.timeframe)
            if ind is None:
                continue

            # Track ATR history for regime detection
            atr_history.append(float(ind.atr))

            # If we're in a trade, check for exit
            if in_trade and current_trade is not None:
                exit_result = self._check_exit(current_trade, ind, i, df.index[i])
                if exit_result is not None:
                    current_trade = exit_result
                    trades.append(current_trade)
                    in_trade = False
                    if 0 < self.max_trades <= len(trades):
                        break
                    current_trade = None

            # If not in a trade, check for new signal
            if not in_trade:
                regime_label = _detect_regime(
                    adx=float(ind.adx),
                    atr=float(ind.atr),
                    close=float(ind.close),
                    atr_history=atr_history,
                    volume=float(ind.volume),
                    volume_avg=float(ind.volume_sma),
                )
                regime_obj = MarketRegime(
                    regime=regime_label,
                    confidence=0.5,
                    adx=float(ind.adx),
                    atr_percentile=50.0,
                    ema_spread_trend="stable",
                )
                result = self._signal_engine.evaluate(ind, regime=regime_obj, structure=None)
                if result.is_actionable:
                    signals_count += 1
                    regime = regime_label
                    current_trade = BacktestTrade(
                        symbol=self.symbol,
                        timeframe=self.timeframe,
                        direction=result.signal.value,
                        entry_price=float(ind.close),
                        entry_index=i,
                        entry_timestamp=str(df.index[i]),
                        sl=result.sl if result.sl is not None else 0.0,
                        tp=result.tp if result.tp is not None else 0.0,
                        regime=regime,
                        signal_score=result.score,
                        confidence=result.confidence,
                        verdict=result.verdict,
                        factor_strengths=dict(result._factor_strengths),
                        factor_present={
                            k: v > 0 for k, v in result._factor_strengths.items()
                        },
                    )
                    in_trade = True

        # Close any remaining open trade at end of data
        if in_trade and current_trade is not None:
            current_trade.exit_price = float(df.iloc[-1]["close"])
            current_trade.exit_index = len(df) - 1
            current_trade.exit_timestamp = str(df.index[-1])
            current_trade.exit_reason = "eob"
            current_trade.pnl_pct = self._calc_pnl_pct(current_trade)
            current_trade.rr = self._calc_rr(current_trade)
            trades.append(current_trade)

        return self._build_result(trades, signals_count, total_candles=len(df))

    def _check_exit(
        self,
        trade: BacktestTrade,
        ind: IndicatorValues,
        candle_index: int,
        candle_timestamp,
    ) -> Optional[BacktestTrade]:
        """Check if trade should be exited (SL or TP hit)."""
        high = float(ind.high)
        low = float(ind.low)
        close = float(ind.close)

        if trade.direction == "BUY":
            if low <= trade.sl:
                trade.exit_price = trade.sl
                trade.exit_reason = "sl"
            elif high >= trade.tp:
                trade.exit_price = trade.tp
                trade.exit_reason = "tp"
            else:
                return None
        else:  # SELL
            if high >= trade.sl:
                trade.exit_price = trade.sl
                trade.exit_reason = "sl"
            elif low <= trade.tp:
                trade.exit_price = trade.tp
                trade.exit_reason = "tp"
            else:
                return None

        trade.exit_index = candle_index
        trade.exit_timestamp = str(candle_timestamp)
        trade.pnl_pct = self._calc_pnl_pct(trade)
        trade.rr = self._calc_rr(trade)
        return trade

    def _calc_pnl_pct(self, trade: BacktestTrade) -> float:
        if trade.exit_price is None or trade.entry_price == 0:
            return 0.0
        if trade.direction == "BUY":
            return (trade.exit_price - trade.entry_price) / trade.entry_price * 100
        else:
            return (trade.entry_price - trade.exit_price) / trade.entry_price * 100

    def _calc_rr(self, trade: BacktestTrade) -> float:
        if trade.exit_price is None or trade.entry_price == 0:
            return 0.0
        risk = abs(trade.entry_price - trade.sl)
        if risk == 0:
            return 0.0
        reward = abs(trade.exit_price - trade.entry_price)
        return round(reward / risk, 2)

    def _build_result(
        self,
        trades: list[BacktestTrade],
        signals_count: int,
        total_candles: int = 0,
    ) -> BacktestResult:
        """Calculate aggregate metrics from trades."""
        total = len(trades)
        if total == 0:
            return BacktestResult(
                symbol=self.symbol,
                timeframe=self.timeframe,
                signals_generated=signals_count,
            )

        wins = [t for t in trades if t.pnl_pct > 0]
        losses = [t for t in trades if t.pnl_pct <= 0]
        win_count = len(wins)
        loss_count = len(losses)

        pnl_values = [t.pnl_pct for t in trades]
        rr_values = [t.rr for t in trades]

        total_pnl = sum(pnl_values)
        avg_pnl = total_pnl / total
        avg_rr = sum(rr_values) / total

        # Profit factor
        gross_profit = sum(t.pnl_pct for t in wins) if wins else 0.0
        gross_loss = abs(sum(t.pnl_pct for t in losses)) if losses else 1.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Expectancy
        winrate = win_count / total
        avg_win = gross_profit / win_count if win_count > 0 else 0.0
        avg_loss = gross_loss / loss_count if loss_count > 0 else 0.0
        expectancy = winrate * avg_win - (1 - winrate) * avg_loss

        # Sharpe ratio (simplified: mean / std of returns)
        if len(pnl_values) > 1:
            std = float(np.std(pnl_values, ddof=1))
            sharpe = (avg_pnl / std) if std > 0 else 0.0
        else:
            sharpe = 0.0

        # Max drawdown
        max_dd = self._calc_max_drawdown(pnl_values)

        # Signal decay: average PnL by trade bucket (first 25%, mid 50%, last 25%)
        signal_decay = self._calc_signal_decay(trades)

        # Regime stats
        regime_stats = self._calc_regime_stats(trades)

        # Exposure time & avg trade duration
        durations = [t.exit_index - t.entry_index for t in trades if t.exit_index is not None]
        total_candles_in_trades = sum(durations) if durations else 0
        exposure_time_pct = (total_candles_in_trades / total_candles * 100) if total_candles > 0 else 0.0
        avg_trade_duration = float(np.mean(durations)) if durations else 0.0

        # Long vs Short breakdown
        long_trades = [t for t in trades if t.direction == "BUY"]
        short_trades = [t for t in trades if t.direction == "SELL"]
        long_stats = self._calc_direction_stats(long_trades, "LONG") if long_trades else None
        short_stats = self._calc_direction_stats(short_trades, "SHORT") if short_trades else None

        # Volatility regime breakdown (low / medium / high)
        volatility_stats = self._calc_volatility_stats(trades)

        return BacktestResult(
            symbol=self.symbol,
            timeframe=self.timeframe,
            total_trades=total,
            wins=win_count,
            losses=loss_count,
            winrate=round(winrate * 100, 1),
            avg_pnl=round(avg_pnl, 4),
            avg_rr=round(avg_rr, 2),
            profit_factor=round(profit_factor, 2),
            expectancy=round(expectancy, 4),
            sharpe_ratio=round(sharpe, 2),
            max_drawdown=round(max_dd, 4),
            total_pnl_pct=round(total_pnl, 4),
            signals_generated=signals_count,
            exposure_time_pct=round(exposure_time_pct, 2),
            avg_trade_duration=round(avg_trade_duration, 1),
            regime_stats=regime_stats,
            long_stats=long_stats,
            short_stats=short_stats,
            volatility_stats=volatility_stats,
            trades=trades,
            signal_decay=signal_decay,
        )

    def _calc_max_drawdown(self, pnl_values: list[float]) -> float:
        """Calculate max drawdown from cumulative PnL series."""
        cumulative = np.cumsum(pnl_values)
        if len(cumulative) == 0:
            return 0.0
        peak = np.maximum.accumulate(cumulative)
        drawdowns = peak - cumulative
        return float(np.max(drawdowns))

    def _calc_signal_decay(self, trades: list[BacktestTrade]) -> list[float]:
        """Average PnL by trade quartile to detect signal decay over time."""
        if len(trades) < 4:
            return [np.mean([t.pnl_pct for t in trades])] if trades else []

        n = len(trades)
        q1_end = max(1, n // 4)
        q3_start = n - n // 4

        buckets = [
            trades[:q1_end],
            trades[q1_end:q3_start],
            trades[q3_start:],
        ]
        return [round(np.mean([t.pnl_pct for t in b]), 4) for b in buckets if b]

    def _calc_direction_stats(self, trades: list[BacktestTrade], label: str) -> RegimeStats:
        """Calculate performance stats for a direction (LONG/SHORT)."""
        total = len(trades)
        if total == 0:
            return RegimeStats(regime=label)
        wins = [t for t in trades if t.pnl_pct > 0]
        losses = [t for t in trades if t.pnl_pct <= 0]
        pnl_values = [t.pnl_pct for t in trades]
        gross_profit = sum(t.pnl_pct for t in wins) if wins else 0.0
        gross_loss = abs(sum(t.pnl_pct for t in losses)) if losses else 1.0
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        winrate = len(wins) / total
        avg_win = gross_profit / len(wins) if wins else 0.0
        avg_loss = gross_loss / len(losses) if losses else 0.0
        exp_val = winrate * avg_win - (1 - winrate) * avg_loss
        return RegimeStats(
            regime=label,
            total_trades=total,
            wins=len(wins),
            losses=len(losses),
            winrate=round(winrate * 100, 1),
            avg_pnl=round(np.mean(pnl_values), 4) if pnl_values else 0.0,
            avg_rr=round(np.mean([t.rr for t in trades]), 2),
            profit_factor=round(pf, 2),
            expectancy=round(exp_val, 4),
            max_drawdown=round(self._calc_max_drawdown(pnl_values), 4),
        )

    def _calc_volatility_stats(self, trades: list[BacktestTrade]) -> dict[str, RegimeStats]:
        """Group trades by volatility regime (low/medium/high) and compute stats."""
        vol_regimes: dict[str, list[BacktestTrade]] = {"low": [], "medium": [], "high": []}
        for t in trades:
            r = t.regime or "unknown"
            if r == "low_vol":
                vol_regimes["low"].append(t)
            elif r == "high_vol":
                vol_regimes["high"].append(t)
            else:
                vol_regimes["medium"].append(t)
        result = {}
        for label, reg_trades in vol_regimes.items():
            if not reg_trades:
                continue
            result[label] = self._calc_direction_stats(reg_trades, label)
        return result

    def _calc_regime_stats(self, trades: list[BacktestTrade]) -> dict[str, RegimeStats]:
        """Calculate per-regime performance breakdown."""
        regimes: dict[str, list[BacktestTrade]] = {}
        for t in trades:
            regimes.setdefault(t.regime or "unknown", []).append(t)

        result = {}
        for regime, regime_trades in regimes.items():
            total = len(regime_trades)
            wins = [t for t in regime_trades if t.pnl_pct > 0]
            losses = [t for t in regime_trades if t.pnl_pct <= 0]
            win_count = len(wins)

            pnl_values = [t.pnl_pct for t in regime_trades]
            gross_profit = sum(t.pnl_pct for t in wins) if wins else 0.0
            gross_loss = abs(sum(t.pnl_pct for t in losses)) if losses else 1.0
            pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

            winrate = win_count / total if total > 0 else 0.0
            avg_win = gross_profit / win_count if win_count > 0 else 0.0
            avg_loss = gross_loss / len(losses) if losses else 0.0
            exp_val = winrate * avg_win - (1 - winrate) * avg_loss

            result[regime] = RegimeStats(
                regime=regime,
                total_trades=total,
                wins=win_count,
                losses=len(losses),
                winrate=round(winrate * 100, 1),
                avg_pnl=round(np.mean(pnl_values), 4) if pnl_values else 0.0,
                avg_rr=round(np.mean([t.rr for t in regime_trades]), 2),
                profit_factor=round(pf, 2),
                expectancy=round(exp_val, 4),
                max_drawdown=round(self._calc_max_drawdown(pnl_values), 4),
            )
        return result
