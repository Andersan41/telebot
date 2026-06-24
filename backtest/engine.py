"""
backtest/engine.py — Consolidated backtest engine with full parity to live pipeline.

Implements all 6 tasks from the audit:
  1. Regime detection via RegimeDetector (risk/market_regime.py)
  2. Structural SL/TP via calculate_structural_sl/tp (risk/dynamic_risk.py)
  3. Stop hunt buffer
  4. SL distance guard (min/max)
  5. RR filter
  6. News filter (documented exclusion — no historical data)

Additional parity features:
  - Confirmation timeframe logic
  - Commission & slippage modeling
  - Reject-reason tracking
  - Telegram output (from backtest_zro.py)

Usage:
    python -m backtest.engine BTC/USDT 1h 336
    python -m backtest.engine BTC/USDT 1h 336 --telegram
    python -m backtest.engine BTC/USDT 1h 336 --market future
    python -m backtest.engine BTC/USDT 1h 336 --preset baseline
    python -m backtest.engine BTC/USDT 1h 336 --preset task2_only
    python -m backtest.engine BTC/USDT 1h 336 --preset full
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from loguru import logger

from config.settings import config
from data.exchange_client import exchange_client
from indicators.engine import IndicatorEngine, IndicatorValues
from strategy.signal_engine import signal_engine, SignalType, SignalResult
from risk.market_regime import RegimeDetector, MarketRegime
from risk.dynamic_risk import calculate_structural_sl, calculate_structural_tp
from liquidity.sweep import detect_sweeps
from liquidity.order_blocks import detect_order_blocks
from liquidity.fvg import detect_fvg
from market_structure.structure import analyze_structure


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BacktestTrade:
    """Single simulated trade with full metadata."""
    symbol: str
    timeframe: str
    direction: Literal["BUY", "SELL"]
    entry_price: float
    entry_index: int
    entry_timestamp: str
    sl: float
    tp: float
    sl_source: str = "atr"
    exit_price: Optional[float] = None
    exit_index: Optional[int] = None
    exit_timestamp: Optional[str] = None
    exit_reason: Optional[str] = None
    pnl_pct: float = 0.0
    net_pnl_pct: float = 0.0
    rr: float = 0.0
    regime: str = ""
    signal_score: int = 0
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass
class RejectStats:
    """Tracks signal rejection reasons."""
    total_rejected: int = 0
    rr_rejected: int = 0
    sl_distance_rejected: int = 0
    news_rejected: int = 0
    confirm_tf_rejected: int = 0
    other_rejected: int = 0


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
    avg_net_pnl: float = 0.0
    avg_rr: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    total_pnl_pct: float = 0.0
    total_net_pnl_pct: float = 0.0
    signals_generated: int = 0
    signals_rejected: int = 0
    exposure_time_pct: float = 0.0
    avg_trade_duration: float = 0.0
    reject_stats: RejectStats = field(default_factory=RejectStats)
    trades: list[BacktestTrade] = field(default_factory=list)
    long_stats: dict = field(default_factory=dict)
    short_stats: dict = field(default_factory=dict)
    regime_stats: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Feature flags for A/B/n backtesting
# ---------------------------------------------------------------------------

@dataclass
class BacktestConfig:
    """Feature flags controlling which pipeline steps are active.

    All flags default to True (= FULL / current live behavior).
    For BASELINE run, all flags should be False simultaneously.

    Dependency note:
      - enable_structural_sl=True implies enable_stop_hunt_buffer can activate,
        because buffer is applied inside the structural SL block. When
        enable_structural_sl=False, buffer is never reached regardless of
        enable_stop_hunt_buffer.
      - enable_unified_entry controls ONLY whether entry_price comes from
        confirm TF close (True) or always uses ind.close (False / baseline).
        This does NOT reject any signals.
      - enable_confirm_tf_gate controls the confirm-TF alignment gate:
        when True, signals where confirm-TF EMA+Supertrend disagree are
        rejected. This is an independent filter from entry price source.
      - min_score_for_signal: override for config.scoring.min_score_for_signal.
        When set (not None), the batch runner temporarily patches the global
        config value during signal_engine.evaluate() calls for this preset,
        then restores it. None = use global config default.

    WARNING: enable_confirm_tf_gate=True without enable_unified_entry=False
    is the recommended combination. Enabling both (gate + unified entry) is
    destructive — the 15m entry price leads to significantly worse fills.
    See docs/report_confirm_tf_gate.md for analysis.
    """
    enable_unified_entry: bool = True
    enable_confirm_tf_gate: bool = True
    enable_structural_sl: bool = True
    enable_sl_distance_guard: bool = True
    enable_rr_filter: bool = True
    enable_news_filter: bool = True
    enable_stop_hunt_buffer: bool = True
    min_score_for_signal: Optional[int] = None


# Preset definitions: name → dict of BacktestConfig field overrides
PRESETS: dict[str, dict[str, bool]] = {
    "baseline": {
        "enable_unified_entry": False,
        "enable_confirm_tf_gate": False,  # true zero-flags baseline
        "enable_structural_sl": False,
        "enable_sl_distance_guard": False,
        "enable_rr_filter": False,
        "enable_news_filter": False,
        "enable_stop_hunt_buffer": False,
    },
    "task1_only": {
        # Unified entry ONLY: entry_price = confirm TF close (no reject gate)
        "enable_unified_entry": True,
        "enable_confirm_tf_gate": False,
        "enable_structural_sl": False,
        "enable_sl_distance_guard": False,
        "enable_rr_filter": False,
        "enable_news_filter": False,
        "enable_stop_hunt_buffer": False,
    },
    "confirm_tf_only": {
        # Confirm-TF gate ONLY: rejects signals where confirm TF disagrees (no entry price change)
        "enable_unified_entry": False,
        "enable_confirm_tf_gate": True,
        "enable_structural_sl": False,
        "enable_sl_distance_guard": False,
        "enable_rr_filter": False,
        "enable_news_filter": False,
        "enable_stop_hunt_buffer": False,
    },
    "task2_only": {
        # Structural SL without buffer (task 2 and 6 are physically coupled:
        # buffer lives inside the structural SL block, so task2_only = structural SL
        # without buffer to isolate the SL recalc effect)
        "enable_unified_entry": False,
        "enable_confirm_tf_gate": True,
        "enable_structural_sl": True,
        "enable_sl_distance_guard": False,
        "enable_rr_filter": False,
        "enable_news_filter": False,
        "enable_stop_hunt_buffer": False,
    },
    "task3_only": {
        "enable_unified_entry": False,
        "enable_confirm_tf_gate": True,
        "enable_structural_sl": False,
        "enable_sl_distance_guard": True,
        "enable_rr_filter": False,
        "enable_news_filter": False,
        "enable_stop_hunt_buffer": False,
    },
    "task4_only": {
        "enable_unified_entry": False,
        "enable_confirm_tf_gate": True,
        "enable_structural_sl": False,
        "enable_sl_distance_guard": False,
        "enable_rr_filter": True,
        "enable_news_filter": False,
        "enable_stop_hunt_buffer": False,
    },
    "task5_only": {
        # News filter is a stub (fetch_macro_events returns []) — this preset
        # exists for A/B/n completeness but will produce identical results to baseline.
        "enable_unified_entry": False,
        "enable_confirm_tf_gate": True,
        "enable_structural_sl": False,
        "enable_sl_distance_guard": False,
        "enable_rr_filter": False,
        "enable_news_filter": True,
        "enable_stop_hunt_buffer": False,
    },
    "task6_only": {
        # Stop hunt buffer alone: requires structural SL to be active (buffer
        # lives inside the structural SL block). This preset enables both
        # structural SL + buffer, but notes the coupling.
        "enable_unified_entry": False,
        "enable_confirm_tf_gate": True,
        "enable_structural_sl": True,
        "enable_sl_distance_guard": False,
        "enable_rr_filter": False,
        "enable_news_filter": False,
        "enable_stop_hunt_buffer": True,
    },
    "gate_plus_unified": {
        "enable_unified_entry": True,
        "enable_confirm_tf_gate": True,
        "enable_structural_sl": False,
        "enable_sl_distance_guard": False,
        "enable_rr_filter": False,
        "enable_news_filter": False,
        "enable_stop_hunt_buffer": False,
    },
    "full": {
        "enable_unified_entry": True,
        "enable_confirm_tf_gate": False,  # disabled: data shows it's counterproductive
        "enable_structural_sl": True,
        "enable_sl_distance_guard": True,
        "enable_rr_filter": True,
        "enable_news_filter": True,
        "enable_stop_hunt_buffer": False,  # disabled: data shows −4.08% with no benefit
    },
    "optimized": {
        # Data-driven config: gate and buffer disabled based on backtest evidence
        "enable_unified_entry": True,
        "enable_confirm_tf_gate": False,
        "enable_structural_sl": True,
        "enable_sl_distance_guard": True,
        "enable_rr_filter": True,
        "enable_news_filter": True,
        "enable_stop_hunt_buffer": False,
    },
}


def get_preset_config(preset_name: str) -> BacktestConfig:
    """Create a BacktestConfig from a named preset."""
    if preset_name not in PRESETS:
        available = ", ".join(sorted(PRESETS.keys()))
        raise ValueError(f"Unknown preset '{preset_name}'. Available: {available}")
    return BacktestConfig(**PRESETS[preset_name])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_symbol(symbol: str) -> str:
    if "/" not in symbol and symbol.endswith("USDT"):
        return symbol[:-4] + "/USDT"
    elif "/" not in symbol:
        return symbol + "/USDT"
    return symbol


def _compute_regime(
    ind: IndicatorValues,
    atr_history: list[float],
    ema_spread_history: list[float],
    volume_history: list[float],
) -> MarketRegime:
    """Compute regime using the production RegimeDetector."""
    try:
        adx_val = float(ind.adx) if ind.adx is not None else 20.0
        atr_val = float(ind.atr) if ind.atr is not None else 0.0
        close_val = float(ind.close) if ind.close is not None else 1.0
        vol_val = float(ind.volume) if ind.volume is not None else 0.0
        ema_fast_val = float(ind.ema_fast) if ind.ema_fast is not None else 0.0
        ema_slow_val = float(ind.ema_slow) if ind.ema_slow is not None else 1.0

        detector = RegimeDetector(
            adx=adx_val,
            atr_history=atr_history,
            ema_spread_history=ema_spread_history,
            volume_history=volume_history,
            current_atr=atr_val,
            current_volume=vol_val,
        )
        return detector.detect()
    except Exception:
        return MarketRegime(
            regime="range", confidence=0.5,
            adx=20.0, atr_percentile=50.0,
            ema_spread_trend="stable",
        )


# ---------------------------------------------------------------------------
# Backtest Engine
# ---------------------------------------------------------------------------

class BacktestEngine:
    """Consolidated backtest engine with full parity to live pipeline."""

    def __init__(
        self,
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        max_trades: int = 0,
        send_telegram: bool = False,
        market_type: Optional[str] = None,
        bt_config: Optional[BacktestConfig] = None,
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.max_trades = max_trades
        self.send_telegram = send_telegram
        self.market_type = market_type
        self.bt_config = bt_config or BacktestConfig()
        self._indicator_engine = IndicatorEngine()

    async def run(self) -> BacktestResult:
        """Run the full backtest pipeline."""
        if self.market_type:
            if self.market_type in ("future", "futures"):
                config.exchange.market_type = "future"
            elif self.market_type == "spot":
                config.exchange.market_type = "spot"

        await exchange_client.connect()

        try:
            return await self._run_backtest()
        finally:
            await exchange_client.close()

    async def _run_backtest(self) -> BacktestResult:
        """Internal: fetch data and walk through candles."""
        limit = max(config.trading.candles_limit + 100, 200)
        df = await exchange_client.fetch_ohlcv(self.symbol, self.timeframe, limit=limit)
        if df is None or len(df) < 100:
            return BacktestResult(symbol=self.symbol, timeframe=self.timeframe)

        warmup = 80
        candle_limit = config.trading.candles_limit
        df = df.iloc[-(candle_limit + 60):] if len(df) > candle_limit + 60 else df

        # Fetch confirm TF data if enabled
        confirm_tf = config.trading.confirm_timeframe
        confirm_df = None
        if config.trading.confirm_tf_enabled and confirm_tf != self.timeframe:
            try:
                confirm_df = await exchange_client.fetch_ohlcv(
                    self.symbol, confirm_tf, limit=limit
                )
                if confirm_df is not None and len(confirm_df) < 20:
                    confirm_df = None
            except Exception:
                confirm_df = None

        trades: list[BacktestTrade] = []
        reject_stats = RejectStats()
        atr_history: list[float] = []
        ema_spread_history: list[float] = []
        volume_history: list[float] = []
        in_trade = False
        ct: Optional[BacktestTrade] = None
        signals_count = 0

        for i in range(warmup, len(df)):
            window = df.iloc[:i + 1].copy()
            ind = self._indicator_engine.calculate(window, self.symbol, self.timeframe)
            if ind is None:
                continue

            atr_history.append(float(ind.atr))
            ema_spread_history.append(
                abs(float(ind.ema_fast) - float(ind.ema_slow)) / float(ind.ema_slow) * 100
                if float(ind.ema_slow) > 0 else 0.0
            )
            volume_history.append(float(ind.volume))

            # --- Exit check ---
            if in_trade and ct is not None:
                high, low = float(ind.high), float(ind.low)
                if ct.direction == "BUY":
                    if low <= ct.sl:
                        ct.exit_price = ct.sl
                        ct.exit_index = i
                        ct.exit_timestamp = str(df.index[i])
                        ct.exit_reason = "sl"
                        trades.append(ct)
                        in_trade = False
                        ct = None
                    elif high >= ct.tp:
                        ct.exit_price = ct.tp
                        ct.exit_index = i
                        ct.exit_timestamp = str(df.index[i])
                        ct.exit_reason = "tp"
                        trades.append(ct)
                        in_trade = False
                        ct = None
                else:
                    if high >= ct.sl:
                        ct.exit_price = ct.sl
                        ct.exit_index = i
                        ct.exit_timestamp = str(df.index[i])
                        ct.exit_reason = "sl"
                        trades.append(ct)
                        in_trade = False
                        ct = None
                    elif low <= ct.tp:
                        ct.exit_price = ct.tp
                        ct.exit_index = i
                        ct.exit_timestamp = str(df.index[i])
                        ct.exit_reason = "tp"
                        trades.append(ct)
                        in_trade = False
                        ct = None

            # --- New signal ---
            if not in_trade:
                signals_count += 1

                # Regime detection (Task 1: RegimeDetector)
                regime_obj = _compute_regime(ind, atr_history, ema_spread_history, volume_history)

                # Structure / liquidity analysis
                try:
                    structure = analyze_structure(window.tail(100))
                except Exception:
                    structure = None
                try:
                    all_sweeps = detect_sweeps(window.tail(100), swing_window=5)
                except Exception:
                    all_sweeps = []
                try:
                    all_obs = detect_order_blocks(window.tail(100)) or []
                except Exception:
                    all_obs = []
                valid_sweeps = [s for s in all_sweeps if getattr(s, "is_valid", False)]
                valid_obs = [ob for ob in all_obs if getattr(ob, "is_valid", False)]

                # Confirmation TF
                # enable_unified_entry: entry_price from confirm TF close (no reject)
                # enable_confirm_tf_gate: reject if confirm TF disagrees (independent filter)
                entry_price = float(ind.close)
                confirm_available = (
                    config.trading.confirm_tf_enabled
                    and confirm_df is not None
                    and confirm_tf != self.timeframe
                )
                if confirm_available:
                    primary_ts = df.index[i]
                    try:
                        confirm_idx = confirm_df.index.get_indexer([primary_ts], method="nearest")[0]
                        if 0 <= confirm_idx < len(confirm_df):
                            confirm_ind = self._indicator_engine.calculate(
                                confirm_df.iloc[:confirm_idx + 1].copy(),
                                self.symbol, confirm_tf,
                            )
                            if confirm_ind is not None:
                                direction_str = "buy" if ind.ema_fast > ind.ema_slow else "sell"
                                confirm_ok = signal_engine.evaluate_confirm(confirm_ind, direction_str)
                                if self.bt_config.enable_unified_entry:
                                    entry_price = float(confirm_ind.close)
                                if not confirm_ok and self.bt_config.enable_confirm_tf_gate:
                                    reject_stats.confirm_tf_rejected += 1
                                    reject_stats.total_rejected += 1
                                    continue
                    except Exception:
                        pass

                # Signal evaluation
                result = signal_engine.evaluate(
                    ind,
                    regime=regime_obj,
                    structure=structure,
                    sweeps=valid_sweeps,
                    order_blocks=valid_obs,
                    entry_price=entry_price,
                )

                if not (result.is_actionable and result.sl is not None and result.tp is not None):
                    continue

                is_buy = result.signal == SignalType.BUY

                # --- Post-signal processing (matching scanner.py pipeline) ---

                # FVG detection
                fvgs = []
                try:
                    _df_clean = window.dropna(subset=["open", "high", "low", "close", "volume"])
                    if len(_df_clean) >= 10:
                        fvgs = detect_fvg(_df_clean, lookback=100)
                except Exception:
                    pass

                # TP recalculation with FVGs (Task 5.2)
                if fvgs and result.tp is not None:
                    try:
                        atr_val = float(ind.atr) if ind.atr is not None else 0.0
                        if atr_val <= 0:
                            atr_val = float(ind.close) * 0.02 if ind.close else 0.02
                        new_targets = calculate_structural_tp(
                            direction=result.signal.value,
                            entry=entry_price,
                            sl=result.sl,
                            sweeps=all_sweeps,
                            order_blocks=all_obs,
                            structure=structure,
                            fvgs=fvgs,
                            atr=atr_val,
                            close=float(ind.close) if ind.close else 0.0,
                        )
                        if new_targets:
                            result.tp = new_targets[0].price
                    except Exception:
                        pass

                # Structural SL (Task 2.3)
                if result.sl is not None and self.bt_config.enable_structural_sl:
                    try:
                        atr_val_sl = float(ind.atr) if ind.atr is not None else 0.0
                        if atr_val_sl <= 0:
                            atr_val_sl = float(ind.close) * 0.02 if ind.close else 0.02

                        skip_structural_sl = result._sl_source == "bos"

                        if not skip_structural_sl:
                            new_sl = calculate_structural_sl(
                                direction=result.signal.value,
                                entry=entry_price,
                                sweeps=all_sweeps,
                                order_blocks=all_obs,
                                structure=structure,
                                atr=atr_val_sl,
                                close=float(ind.close) if ind.close else 0.0,
                            )
                            current_dist = abs(entry_price - result.sl)
                            structural_dist = abs(entry_price - new_sl)
                            structural_sl_applied = False
                            if structural_dist <= current_dist and new_sl != result.sl:
                                result.sl = new_sl
                                structural_sl_applied = True
                                result._sl_source = "structural"

                            # Stop hunt buffer (Task 2.4): apply only when structural SL was accepted
                            if structural_sl_applied and self.bt_config.enable_stop_hunt_buffer and config.trading.stop_hunt_buffer_pct > 0:
                                buffer_pct = config.trading.stop_hunt_buffer_pct / 100.0
                                if is_buy:
                                    result.sl = round(result.sl * (1 - buffer_pct), 8)
                                else:
                                    result.sl = round(result.sl * (1 + buffer_pct), 8)
                    except Exception:
                        pass

                # SL distance guard (Task 2.5)
                if self.bt_config.enable_sl_distance_guard:
                    sl_dist_pct = abs(entry_price - result.sl) / entry_price * 100
                    min_dist = config.trading.min_sl_distance_pct
                    max_dist = config.trading.max_sl_distance_pct
                    if sl_dist_pct < min_dist:
                        if is_buy:
                            result.sl = round(entry_price * (1 - min_dist / 100), 8)
                        else:
                            result.sl = round(entry_price * (1 + min_dist / 100), 8)
                        result.reasons.append(f"SL shifted to min distance {min_dist}%")
                    elif sl_dist_pct > max_dist:
                        reject_stats.sl_distance_rejected += 1
                        reject_stats.total_rejected += 1
                        continue

                # RR filter (Task 2.6)
                if self.bt_config.enable_rr_filter:
                    risk = abs(entry_price - result.sl)
                    reward = abs(result.tp - entry_price)
                    rr = reward / risk if risk > 0 else 0
                    min_rr = config.trading.min_rr_threshold
                    if rr < min_rr:
                        reject_stats.rr_rejected += 1
                        reject_stats.total_rejected += 1
                        continue

                # News filter (Task 2.7: documented exclusion)
                # NOTE: risk/news_filter.py is a stub (fetch_macro_events returns []).
                # No historical news data available for backtesting — skip filter.
                # Gated by enable_news_filter for A/B/n completeness (no-op when enabled).

                # Build trade
                ct = BacktestTrade(
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    direction=result.signal.value,
                    entry_price=entry_price,
                    entry_index=i,
                    entry_timestamp=str(df.index[i]),
                    sl=result.sl,
                    tp=result.tp,
                    sl_source=result._sl_source or "atr",
                    regime=regime_obj.regime,
                    signal_score=result.score,
                    confidence=result.confidence,
                    reasons=list(result.reasons),
                )
                in_trade = True

                if 0 < self.max_trades <= len(trades):
                    break

        # Close open trade at end of data
        if in_trade and ct is not None:
            ct.exit_price = float(df.iloc[-1]["close"])
            ct.exit_index = len(df) - 1
            ct.exit_timestamp = str(df.index[-1])
            ct.exit_reason = "eob"
            trades.append(ct)

        # --- Compute PnL with commission/slippage ---
        fee_pct = config.trading.exchange_fee_pct / 100.0
        slip_pct = config.trading.slippage_pct / 100.0

        for t in trades:
            if t.direction == "BUY":
                gross = (t.exit_price - t.entry_price) / t.entry_price * 100
            else:
                gross = (t.entry_price - t.exit_price) / t.entry_price * 100
            t.pnl_pct = round(gross, 4)

            # Commission: 2 sides (entry + exit)
            total_cost_pct = (fee_pct * 2 + slip_pct * 2) * 100
            t.net_pnl_pct = round(gross - total_cost_pct, 4)

            risk = abs(t.entry_price - t.sl)
            t.rr = round(abs(t.exit_price - t.entry_price) / risk, 2) if risk > 0 else 0.0

        return self._build_result(trades, signals_count, reject_stats, len(df))

    def _build_result(
        self,
        trades: list[BacktestTrade],
        signals_count: int,
        reject_stats: RejectStats,
        total_candles: int,
    ) -> BacktestResult:
        """Build aggregate metrics."""
        total = len(trades)
        if total == 0:
            return BacktestResult(
                symbol=self.symbol,
                timeframe=self.timeframe,
                signals_generated=signals_count,
                signals_rejected=reject_stats.total_rejected,
                reject_stats=reject_stats,
            )

        wins = [t for t in trades if t.pnl_pct > 0]
        losses = [t for t in trades if t.pnl_pct <= 0]
        win_count = len(wins)
        loss_count = len(losses)

        pnl_values = [t.pnl_pct for t in trades]
        net_pnl_values = [t.net_pnl_pct for t in trades]
        rr_values = [t.rr for t in trades]

        total_pnl = sum(pnl_values)
        total_net_pnl = sum(net_pnl_values)
        avg_pnl = total_pnl / total
        avg_net_pnl = total_net_pnl / total
        avg_rr = sum(rr_values) / total

        gross_profit = sum(t.pnl_pct for t in wins) if wins else 0.0
        gross_loss = abs(sum(t.pnl_pct for t in losses)) if losses else 1.0
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        winrate = win_count / total
        avg_win = gross_profit / win_count if win_count > 0 else 0.0
        avg_loss = gross_loss / loss_count if loss_count > 0 else 0.0
        expectancy = winrate * avg_win - (1 - winrate) * avg_loss

        if len(pnl_values) > 1:
            std = float(np.std(pnl_values, ddof=1))
            sharpe = (avg_pnl / std) if std > 0 else 0.0
        else:
            sharpe = 0.0

        # Max drawdown
        cum = np.cumsum(pnl_values)
        peak = np.maximum.accumulate(cum)
        dd = peak - cum
        max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

        # Exposure
        durations = [t.exit_index - t.entry_index for t in trades if t.exit_index is not None]
        total_dur = sum(durations) if durations else 0
        exposure_pct = (total_dur / total_candles * 100) if total_candles > 0 else 0.0
        avg_dur = float(np.mean(durations)) if durations else 0.0

        # Direction breakdown
        long_stats = {}
        short_stats = {}
        for d_label in ["BUY", "SELL"]:
            d_trades = [t for t in trades if t.direction == d_label]
            if not d_trades:
                continue
            d_w = [t for t in d_trades if t.pnl_pct > 0]
            d_pnl = sum(t.pnl_pct for t in d_trades)
            d_net = sum(t.net_pnl_pct for t in d_trades)
            d_wr = len(d_w) / len(d_trades) * 100
            d_pf_num = sum(t.pnl_pct for t in d_w)
            d_pf_den = abs(sum(t.pnl_pct for t in d_trades if t.pnl_pct <= 0))
            d_pf = d_pf_num / d_pf_den if d_pf_den > 0 else float("inf")
            stats = {
                "trades": len(d_trades), "winrate": d_wr,
                "pnl": d_pnl, "net_pnl": d_net, "pf": d_pf,
            }
            if d_label == "BUY":
                long_stats = stats
            else:
                short_stats = stats

        # Regime breakdown
        regimes: dict[str, list[BacktestTrade]] = {}
        for t in trades:
            regimes.setdefault(t.regime or "unknown", []).append(t)
        regime_stats = {}
        for reg, r_trades in regimes.items():
            r_w = [t for t in r_trades if t.pnl_pct > 0]
            r_pnl = sum(t.pnl_pct for t in r_trades)
            r_net = sum(t.net_pnl_pct for t in r_trades)
            r_wr = len(r_w) / len(r_trades) * 100
            regime_stats[reg] = {
                "trades": len(r_trades), "winrate": r_wr,
                "pnl": r_pnl, "net_pnl": r_net,
            }

        return BacktestResult(
            symbol=self.symbol,
            timeframe=self.timeframe,
            total_trades=total,
            wins=win_count,
            losses=loss_count,
            winrate=round(winrate * 100, 1),
            avg_pnl=round(avg_pnl, 4),
            avg_net_pnl=round(avg_net_pnl, 4),
            avg_rr=round(avg_rr, 2),
            profit_factor=round(pf, 2),
            expectancy=round(expectancy, 4),
            sharpe_ratio=round(sharpe, 2),
            max_drawdown=round(max_dd, 4),
            total_pnl_pct=round(total_pnl, 4),
            total_net_pnl_pct=round(total_net_pnl, 4),
            signals_generated=signals_count,
            signals_rejected=reject_stats.total_rejected,
            exposure_time_pct=round(exposure_pct, 2),
            avg_trade_duration=round(avg_dur, 1),
            reject_stats=reject_stats,
            trades=trades,
            long_stats=long_stats,
            short_stats=short_stats,
            regime_stats=regime_stats,
        )


# ---------------------------------------------------------------------------
# Output: Console
# ---------------------------------------------------------------------------

def print_result(result: BacktestResult):
    """Print backtest results to console."""
    df_len = result.total_trades * 4  # approximate
    print(f"\n{'='*60}")
    print(f"  BACKTEST: {result.symbol} {result.timeframe}")
    print(f"  Trades: {result.total_trades} | Signals: {result.signals_generated} | Rejected: {result.signals_rejected}")
    print(f"{'='*60}")

    if result.total_trades == 0:
        print("\n  No trades generated")
        return

    print(f"\n  Total trades:     {result.total_trades}")
    print(f"  Winrate:          {result.winrate:.1f}%")
    print(f"  Avg PnL (gross):  {result.avg_pnl:+.4f}%")
    print(f"  Avg PnL (net):    {result.avg_net_pnl:+.4f}%")
    print(f"  Avg R/R:          {result.avg_rr:.2f}")
    print(f"  Profit Factor:    {result.profit_factor:.2f}")
    print(f"  Expectancy:       {result.expectancy:+.4f}")
    print(f"  Sharpe:           {result.sharpe_ratio:.2f}")
    print(f"  Max DD:           {result.max_drawdown:.2f}%")
    print(f"  Total PnL (gross): {result.total_pnl_pct:+.4f}%")
    print(f"  Total PnL (net):   {result.total_net_pnl_pct:+.4f}%")
    print(f"  Avg trade len:    {result.avg_trade_duration:.1f} candles")
    print(f"  Exposure:         {result.exposure_time_pct:.1f}%")

    # Reject stats
    rs = result.reject_stats
    if rs.total_rejected > 0:
        print(f"\n  Rejected signals: {rs.total_rejected}")
        if rs.rr_rejected:
            print(f"    RR filter:      {rs.rr_rejected}")
        if rs.sl_distance_rejected:
            print(f"    SL distance:    {rs.sl_distance_rejected}")
        if rs.confirm_tf_rejected:
            print(f"    Confirm TF:     {rs.confirm_tf_rejected}")
        if rs.news_rejected:
            print(f"    News filter:    {rs.news_rejected}")

    # Direction breakdown
    for label, stats in [("BUY", result.long_stats), ("SELL", result.short_stats)]:
        if not stats:
            continue
        print(f"\n  {label}: {stats['trades']} trades, wr={stats['winrate']:.0f}%, "
              f"PnL={stats['pnl']:+.2f}%, net={stats['net_pnl']:+.2f}%, PF={stats['pf']:.2f}")

    # Regime breakdown
    for reg, stats in sorted(result.regime_stats.items()):
        print(f"  [{reg}] {stats['trades']} trades, wr={stats['winrate']:.0f}%, "
              f"PnL={stats['pnl']:+.2f}%, net={stats['net_pnl']:+.2f}%")

    # Trade detail
    print(f"\n  DETAIL (last 15):")
    show = result.trades[-15:]
    start = len(result.trades) - len(show) + 1
    for idx, t in enumerate(show):
        em = "+" if t.pnl_pct > 0 else "-"
        dur = (t.exit_index - t.entry_index) if t.exit_index is not None else 0
        print(f"  {em} #{start+idx} {t.direction} entry=${t.entry_price:.4f} → "
              f"${t.exit_price:.4f} ({t.exit_reason}) pnl={t.pnl_pct:+.4f}% "
              f"net={t.net_pnl_pct:+.4f}% rr={t.rr:.2f} "
              f"sl_src={t.sl_source} [{t.regime}] {dur}c")


# ---------------------------------------------------------------------------
# Output: Telegram
# ---------------------------------------------------------------------------

def format_telegram(result: BacktestResult) -> str:
    """Format backtest results as Telegram HTML."""
    if result.total_trades == 0:
        return f"📊 <b>Backtest: {result.symbol} {result.timeframe}</b>\n\nNo trades generated"

    days_approx = result.avg_trade_duration * result.total_trades / 24 if result.timeframe == "1h" else 0

    msg = f"""📊 <b>BACKTEST: {result.symbol} {result.timeframe}</b>
┌─────────────────────────────────────
│ Trades: {result.total_trades} | Signals: {result.signals_generated} | Rejected: {result.signals_rejected}
└─────────────────────────────────────

📈 <b>Metrics:</b>
├ Trades: {result.total_trades}
├ Winrate: {result.winrate:.1f}%
├ Avg PnL (gross): {result.avg_pnl:+.4f}%
├ Avg PnL (net): {result.avg_net_pnl:+.4f}%
├ Avg R/R: {result.avg_rr:.2f}
├ Profit Factor: {result.profit_factor:.2f}
├ Expectancy: {result.expectancy:+.4f}
├ Max DD: {result.max_drawdown:.2f}%
├ Total PnL (gross): {result.total_pnl_pct:+.4f}%
└ Total PnL (net): {result.total_net_pnl_pct:+.4f}%"""

    # Direction breakdown
    msg += "\n\n📐 <b>By direction:</b>"
    for label, emoji, stats in [("BUY", "🟢", result.long_stats), ("SELL", "🔴", result.short_stats)]:
        if not stats:
            continue
        msg += f"\n{emoji} {label}: {stats['trades']} trades, wr={stats['winrate']:.0f}%, PnL={stats['pnl']:+.2f}%, net={stats['net_pnl']:+.2f}%, PF={stats['pf']:.2f}"

    # Regime breakdown
    if result.regime_stats:
        msg += "\n\n🎯 <b>By regime:</b>"
        for reg, stats in sorted(result.regime_stats.items()):
            msg += f"\n├ [{reg}] {stats['trades']} trades, wr={stats['winrate']:.0f}%, PnL={stats['pnl']:+.2f}%, net={stats['net_pnl']:+.2f}%"

    # Reject stats
    rs = result.reject_stats
    if rs.total_rejected > 0:
        msg += f"\n\n🚫 <b>Rejected: {rs.total_rejected}</b>"
        if rs.rr_rejected:
            msg += f"\n├ RR filter: {rs.rr_rejected}"
        if rs.sl_distance_rejected:
            msg += f"\n├ SL distance: {rs.sl_distance_rejected}"
        if rs.confirm_tf_rejected:
            msg += f"\n└ Confirm TF: {rs.confirm_tf_rejected}"

    # Trade detail (last 15)
    show = result.trades[-15:]
    start_idx = len(result.trades) - len(show) + 1
    msg += f"\n\n📝 <b>Last {len(show)} trades:</b>"
    for idx, t in enumerate(show):
        em = "✅" if t.pnl_pct > 0 else "❌"
        msg += (f"\n{em} #{start_idx+idx} {t.direction} ${t.entry_price:.4f}→${t.exit_price:.4f} "
                f"({t.exit_reason}) {t.pnl_pct:+.4f}% net={t.net_pnl_pct:+.4f}% "
                f"rr={t.rr:.2f} [{t.regime}]")

    return msg


async def send_to_telegram(text: str):
    """Send message to Telegram channel."""
    from telegram import Bot
    from telegram.constants import ParseMode
    from telegram.error import TelegramError

    channel_id = config.telegram.channel_id
    if not channel_id:
        print("TELEGRAM_CHANNEL_ID not set")
        return

    bot = Bot(token=config.telegram.token)

    if len(text) > 4000:
        parts = []
        lines = text.split("\n")
        current = ""
        for line in lines:
            if len(current) + len(line) + 1 > 4000:
                parts.append(current)
                current = line
            else:
                current = current + "\n" + line if current else line
        if current:
            parts.append(current)

        for part in parts:
            try:
                await bot.send_message(chat_id=channel_id, text=part, parse_mode=ParseMode.HTML)
                await asyncio.sleep(1)
            except TelegramError:
                try:
                    await bot.send_message(chat_id=channel_id, text=part)
                except Exception:
                    pass
    else:
        try:
            await bot.send_message(chat_id=channel_id, text=text, parse_mode=ParseMode.HTML)
        except TelegramError:
            try:
                await bot.send_message(chat_id=channel_id, text=text)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def main():
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "BTC/USDT"
    tf = (sys.argv[2] if len(sys.argv) > 2 else "1h").lower()
    candle_limit = int(sys.argv[3]) if len(sys.argv) > 3 else 336

    send_tg = "--telegram" in sys.argv
    market_type = None
    for arg in sys.argv[4:]:
        if arg.lower() in ("future", "futures", "spot"):
            market_type = arg.lower()

    # Parse --preset <name>
    bt_config = BacktestConfig()
    if "--preset" in sys.argv:
        preset_idx = sys.argv.index("--preset")
        if preset_idx + 1 < len(sys.argv):
            preset_name = sys.argv[preset_idx + 1].lower()
            bt_config = get_preset_config(preset_name)
            print(f"Using preset: {preset_name}")
            print(f"  Flags: {bt_config}")
        else:
            print("Error: --preset requires a name (baseline, task1_only, ..., full)")
            sys.exit(1)

    symbol = _normalize_symbol(symbol)
    config.trading.candles_limit = candle_limit

    print(f"Running backtest: {symbol} {tf} ({candle_limit} candles)...")

    engine = BacktestEngine(
        symbol=symbol,
        timeframe=tf,
        send_telegram=send_tg,
        market_type=market_type,
        bt_config=bt_config,
    )
    result = await engine.run()

    print_result(result)

    if send_tg:
        print("\nSending to Telegram...")
        await send_to_telegram(format_telegram(result))
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
