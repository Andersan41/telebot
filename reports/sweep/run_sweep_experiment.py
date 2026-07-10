"""
reports/sweep/run_sweep_experiment.py — A/B backtest: sweep disabled for SELL only.

Hypothesis: Liquidity Sweep degrades SELL signal quality but not BUY.

Method: Monkey-patch signal_engine.evaluate() to pass empty sweeps list
for SELL direction, removing sweep from:
  1. Leading trigger gate
  2. Compression breakout detection
  3. Candle close confirmation bypass

BUY logic remains completely unchanged.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

_saved_stdout = sys.stdout
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from loguru import logger as _loguru_logger
_loguru_logger.disable("strategy.signal_engine")
_loguru_logger.disable("indicators.engine")
import logging
logging.getLogger("strategy.signal_engine").setLevel(logging.WARNING)
logging.getLogger("indicators.engine").setLevel(logging.WARNING)

import numpy as np
import pandas as pd
from dataclasses import dataclass, field

from backtest.engine import (
    BacktestConfig,
    BacktestResult,
    BacktestTrade,
    RejectStats,
    _compute_regime,
    _normalize_symbol,
)
from indicators.engine import IndicatorEngine, IndicatorValues
from strategy.signal_engine import signal_engine, SignalType, SignalResult
from risk.dynamic_risk import calculate_structural_sl, calculate_structural_tp
from liquidity.sweep import detect_sweeps
from liquidity.order_blocks import detect_order_blocks
from liquidity.fvg import detect_fvg
from market_structure.structure import analyze_structure
from config.settings import config

sys.stdout = _saved_stdout

# ─── Experiment Config ────────────────────────────────────────────────
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "APT/USDT"]
TIMEFRAME = "1h"
CANDLES = 3900
CONFIRM_TF = "15m"
CONFIRM_CANDLES = 15552
WARMUP = 80

# full_new preset flags
FULL_NEW_FLAGS = {
    "enable_unified_entry": True,
    "enable_confirm_tf_gate": False,
    "enable_structural_sl": True,
    "enable_sl_distance_guard": True,
    "enable_rr_filter": True,
    "enable_news_filter": True,
    "enable_stop_hunt_buffer": False,
}

RESULTS_DIR = Path(__file__).parent
REPORTS_DIR = RESULTS_DIR


# ─── Monkey-patch: sell_sweep_disabled ───────────────────────────────

_original_evaluate = signal_engine.evaluate

def _patched_evaluate(self, ind, regime=None, sweeps=None, order_blocks=None,
                      entry_price=None, **kwargs):
    """Monkey-patched evaluate: for SELL direction, strip sweep from all logic."""
    # Pre-determine direction using the same logic as signal_engine
    # We need to know direction BEFORE calling evaluate to conditionally strip sweep.
    # Direction depends on: structure BOS, sweep type, delta, EMA cross, MACD cross, EMA alignment.
    # This is complex, so we use a simpler approach: call evaluate TWICE if needed.

    # Step 1: Quick direction check (simplified)
    _direction = _quick_direction(ind, kwargs.get("structure"), sweeps)

    # Step 2: For SELL, strip sweep; for BUY, keep as-is
    if _direction == "sell" and sweeps:
        return _original_evaluate(self, ind, regime=regime, sweeps=[],
                                  order_blocks=order_blocks, entry_price=entry_price, **kwargs)
    else:
        return _original_evaluate(self, ind, regime=regime, sweeps=sweeps,
                                  order_blocks=order_blocks, entry_price=entry_price, **kwargs)


def _quick_direction(ind: IndicatorValues, structure, sweeps) -> str:
    """Fast direction pre-check matching signal_engine logic."""
    # Check BOS first
    if structure and hasattr(structure, 'last_bos') and structure.last_bos:
        bos = structure.last_bos
        if bos.type == "bullish":
            return "buy"
        elif bos.type == "bearish":
            return "sell"

    # Check sweep type
    if sweeps:
        for sw in sweeps:
            if getattr(sw, "is_valid", False):
                if sw.type == "bullish":
                    return "buy"
                elif sw.type == "bearish":
                    return "sell"
                break

    # Check delta
    vol_above = ind.volume > ind.volume_sma * config.trading.volume_factor
    if ind.volume_delta_pct is not None and vol_above:
        delta = ind.volume_delta_pct
        if delta > config.trading.delta_bullish:
            return "buy"
        elif delta < config.trading.delta_bearish:
            return "sell"

    # Check EMA/MACD cross
    if ind.ema_bullish_cross:
        return "buy"
    elif ind.ema_bearish_cross:
        return "sell"
    if ind.close > 0:
        macd_norm = abs(ind.macd_hist / ind.close) * 100
        if macd_norm >= config.trading.min_macd_pct:
            if ind.macd_hist > 0 and ind.macd_hist_prev <= 0:
                return "buy"
            elif ind.macd_hist < 0 and ind.macd_hist_prev >= 0:
                return "sell"

    # Fallback: EMA alignment
    return "buy" if ind.ema_fast > ind.ema_slow else "sell"


# ─── Dataclasses ──────────────────────────────────────────────────────

@dataclass
class CandleSnapshot:
    i: int
    ind: IndicatorValues
    regime_obj: object
    structure: object
    all_sweeps: list
    all_obs: list
    valid_sweeps: list
    valid_obs: list
    fvgs: list
    entry_price_base: float
    confirm_entry_price: Optional[float]
    confirm_ok: bool


@dataclass
class PresetState:
    in_trade: bool = False
    ct: Optional[BacktestTrade] = None
    trades: list = field(default_factory=list)
    reject_stats: RejectStats = field(default_factory=RejectStats)
    signals_count: int = 0


# ─── Helpers ──────────────────────────────────────────────────────────

def make_config(flags: dict) -> BacktestConfig:
    return BacktestConfig(**flags)


def build_result_from_state(symbol: str, timeframe: str, state: PresetState, total_candles: int) -> BacktestResult:
    trades = state.trades
    rs = state.reject_stats
    total = len(trades)
    if total == 0:
        return BacktestResult(symbol=symbol, timeframe=timeframe,
                              signals_generated=state.signals_count,
                              signals_rejected=rs.total_rejected, reject_stats=rs)

    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]
    win_count = len(wins)
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
    avg_loss = gross_loss / len(losses) if losses else 0.0
    expectancy = winrate * avg_win - (1 - winrate) * avg_loss
    if len(pnl_values) > 1:
        std = float(np.std(pnl_values, ddof=1))
        sharpe = (avg_pnl / std) if std > 0 else 0.0
    else:
        sharpe = 0.0
    cum = np.cumsum(pnl_values)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0
    durations = [t.exit_index - t.entry_index for t in trades if t.exit_index is not None]
    total_dur = sum(durations) if durations else 0
    exposure_pct = (total_dur / total_candles * 100) if total_candles > 0 else 0.0
    avg_dur = float(np.mean(durations)) if durations else 0.0

    long_stats = {}
    short_stats = {}
    for d_label in ["BUY", "SELL"]:
        d_trades = [t for t in trades if t.direction == d_label]
        if not d_trades: continue
        d_w = [t for t in d_trades if t.pnl_pct > 0]
        d_pnl = sum(t.pnl_pct for t in d_trades)
        d_net = sum(t.net_pnl_pct for t in d_trades)
        d_wr = len(d_w) / len(d_trades) * 100
        d_pf_num = sum(t.pnl_pct for t in d_w)
        d_pf_den = abs(sum(t.pnl_pct for t in d_trades if t.pnl_pct <= 0))
        d_pf = d_pf_num / d_pf_den if d_pf_den > 0 else float("inf")
        stats = {"trades": len(d_trades), "winrate": d_wr, "pnl": d_pnl, "net_pnl": d_net, "pf": d_pf}
        if d_label == "BUY": long_stats = stats
        else: short_stats = stats

    regimes = {}
    for t in trades:
        regimes.setdefault(t.regime or "unknown", []).append(t)
    regime_stats = {}
    for reg, r_trades in regimes.items():
        r_w = [t for t in r_trades if t.pnl_pct > 0]
        r_pnl = sum(t.pnl_pct for t in r_trades)
        r_net = sum(t.net_pnl_pct for t in r_trades)
        r_wr = len(r_w) / len(r_trades) * 100
        regime_stats[reg] = {"trades": len(r_trades), "winrate": r_wr, "pnl": r_pnl, "net_pnl": r_net}

    return BacktestResult(
        symbol=symbol, timeframe=timeframe, total_trades=total,
        wins=win_count, losses=len(losses), winrate=round(winrate * 100, 1),
        avg_pnl=round(avg_pnl, 4), avg_net_pnl=round(avg_net_pnl, 4),
        avg_rr=round(avg_rr, 2), profit_factor=round(pf, 2),
        expectancy=round(expectancy, 4), sharpe_ratio=round(sharpe, 2),
        max_drawdown=round(max_dd, 4), total_pnl_pct=round(total_pnl, 4),
        total_net_pnl_pct=round(total_net_pnl, 4),
        signals_generated=state.signals_count, signals_rejected=rs.total_rejected,
        exposure_time_pct=round(exposure_pct, 2), avg_trade_duration=round(avg_dur, 1),
        reject_stats=rs, trades=trades, long_stats=long_stats,
        short_stats=short_stats, regime_stats=regime_stats,
    )


def result_to_record(symbol: str, preset: str, r: BacktestResult) -> dict:
    rs = r.reject_stats
    rec = {
        "symbol": symbol, "preset": preset,
        "total_trades": r.total_trades, "wins": r.wins, "losses": r.losses,
        "winrate": r.winrate, "avg_pnl": r.avg_pnl, "avg_net_pnl": r.avg_net_pnl,
        "avg_rr": r.avg_rr, "profit_factor": r.profit_factor, "expectancy": r.expectancy,
        "sharpe_ratio": r.sharpe_ratio, "max_drawdown": r.max_drawdown,
        "total_pnl_pct": r.total_pnl_pct, "total_net_pnl_pct": r.total_net_pnl_pct,
        "signals_generated": r.signals_generated, "signals_rejected": r.signals_rejected,
        "exposure_time_pct": r.exposure_time_pct, "avg_trade_duration": r.avg_trade_duration,
        "reject_rr": rs.rr_rejected, "reject_sl_dist": rs.sl_distance_rejected,
        "reject_confirm_tf": rs.confirm_tf_rejected, "reject_news": rs.news_rejected,
        "reject_sell_sweep": rs.sell_sweep_rejected,
        "long_stats": r.long_stats, "short_stats": r.short_stats,
        "regime_stats": r.regime_stats,
        "exit_sl": 0, "exit_tp": 0, "exit_eob": 0,
        "src_atr": 0, "src_bos": 0, "src_structural": 0,
        "trades": [],
    }
    for t in r.trades:
        rec["trades"].append({
            "symbol": t.symbol, "direction": t.direction,
            "entry_price": t.entry_price, "exit_price": t.exit_price,
            "exit_reason": t.exit_reason, "pnl_pct": t.pnl_pct,
            "net_pnl_pct": t.net_pnl_pct, "rr": t.rr, "sl_source": t.sl_source,
            "regime": t.regime, "entry_timestamp": str(t.entry_timestamp),
            "exit_timestamp": str(t.exit_timestamp),
            "signal_score": t.signal_score,
            "reasons": t.reasons,
            "sl_price": t.sl, "tp_price": t.tp,
        })
        if t.exit_reason == "sl": rec["exit_sl"] += 1
        elif t.exit_reason == "tp": rec["exit_tp"] += 1
        elif t.exit_reason == "eob": rec["exit_eob"] += 1
        src = t.sl_source or "atr"
        if src == "bos": rec["src_bos"] += 1
        elif src == "structural": rec["src_structural"] += 1
        else: rec["src_atr"] += 1
    return rec


# ─── Core A/B runner ─────────────────────────────────────────────────

async def run_ab_for_symbol(
    symbol: str,
    df: pd.DataFrame,
    confirm_df: Optional[pd.DataFrame],
    indicator_engine: IndicatorEngine,
) -> dict[str, dict]:
    """Run full_new and sell_sweep_disabled for one symbol."""
    tf = TIMEFRAME
    confirm_tf = CONFIRM_TF
    results = {}

    # Pre-compute all candle snapshots (ONCE for both presets)
    snapshots: list[CandleSnapshot] = []
    atr_history = []
    ema_spread_history = []
    volume_history = []

    for i in range(WARMUP, len(df)):
        window = df.iloc[:i + 1].copy()
        ind = indicator_engine.calculate(window, symbol, tf)
        if ind is None:
            continue

        atr_history.append(float(ind.atr))
        ema_spread_history.append(
            abs(float(ind.ema_fast) - float(ind.ema_slow)) / float(ind.ema_slow) * 100
            if float(ind.ema_slow) > 0 else 0.0
        )
        volume_history.append(float(ind.volume))

        regime_obj = _compute_regime(ind, atr_history, ema_spread_history, volume_history)

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

        fvgs = []
        try:
            _df_clean = window.dropna(subset=["open", "high", "low", "close", "volume"])
            if len(_df_clean) >= 10:
                fvgs = detect_fvg(_df_clean, lookback=100)
        except Exception:
            pass

        entry_price_base = float(ind.close)
        confirm_entry_price = None
        confirm_ok = True

        confirm_available = (
            config.trading.confirm_tf_enabled
            and confirm_df is not None
            and confirm_tf != tf
        )
        if confirm_available:
            try:
                primary_ts = df.index[i]
                confirm_idx = confirm_df.index.get_indexer([primary_ts], method="nearest")[0]
                if 0 <= confirm_idx < len(confirm_df):
                    confirm_ind = indicator_engine.calculate(
                        confirm_df.iloc[:confirm_idx + 1].copy(), symbol, confirm_tf,
                    )
                    if confirm_ind is not None:
                        direction_str = "buy" if ind.ema_fast > ind.ema_slow else "sell"
                        confirm_ok = signal_engine.evaluate_confirm(confirm_ind, direction_str)
                        confirm_entry_price = float(confirm_ind.close)
            except Exception:
                pass

        snapshots.append(CandleSnapshot(
            i=i, ind=ind, regime_obj=regime_obj, structure=structure,
            all_sweeps=all_sweeps, all_obs=all_obs,
            valid_sweeps=valid_sweeps, valid_obs=valid_obs, fvgs=fvgs,
            entry_price_base=entry_price_base,
            confirm_entry_price=confirm_entry_price, confirm_ok=confirm_ok,
        ))

    # ── Run preset A: full_new (baseline) ──────────────────────────────
    cfg_full = make_config(FULL_NEW_FLAGS)
    state_full = PresetState()
    fee_pct = config.trading.exchange_fee_pct / 100.0
    slip_pct = config.trading.slippage_pct / 100.0

    for snap in snapshots:
        if state_full.in_trade and state_full.ct is not None:
            high, low = float(snap.ind.high), float(snap.ind.low)
            ct = state_full.ct
            exited = False
            if ct.direction == "BUY":
                if low <= ct.sl:
                    ct.exit_price = ct.sl; ct.exit_index = snap.i
                    ct.exit_timestamp = str(df.index[snap.i]); ct.exit_reason = "sl"
                    exited = True
                elif high >= ct.tp:
                    ct.exit_price = ct.tp; ct.exit_index = snap.i
                    ct.exit_timestamp = str(df.index[snap.i]); ct.exit_reason = "tp"
                    exited = True
            else:
                if high >= ct.sl:
                    ct.exit_price = ct.sl; ct.exit_index = snap.i
                    ct.exit_timestamp = str(df.index[snap.i]); ct.exit_reason = "sl"
                    exited = True
                elif low <= ct.tp:
                    ct.exit_price = ct.tp; ct.exit_index = snap.i
                    ct.exit_timestamp = str(df.index[snap.i]); ct.exit_reason = "tp"
                    exited = True
            if exited:
                if ct.direction == "BUY":
                    gross = (ct.exit_price - ct.entry_price) / ct.entry_price * 100
                else:
                    gross = (ct.entry_price - ct.exit_price) / ct.entry_price * 100
                ct.pnl_pct = round(gross, 4)
                ct.net_pnl_pct = round(gross - (fee_pct * 2 + slip_pct * 2) * 100, 4)
                risk = abs(ct.entry_price - ct.sl)
                ct.rr = round(abs(ct.exit_price - ct.entry_price) / risk, 2) if risk > 0 else 0.0
                state_full.trades.append(ct)
                state_full.in_trade = False
                state_full.ct = None

        if not state_full.in_trade:
            state_full.signals_count += 1
            if cfg_full.enable_unified_entry and snap.confirm_entry_price is not None:
                entry_price = snap.confirm_entry_price
            else:
                entry_price = snap.entry_price_base

            if not snap.confirm_ok and cfg_full.enable_confirm_tf_gate:
                state_full.reject_stats.confirm_tf_rejected += 1
                state_full.reject_stats.total_rejected += 1
                continue

            result = signal_engine.evaluate(
                snap.ind, regime=snap.regime_obj, structure=snap.structure,
                sweeps=snap.valid_sweeps, order_blocks=snap.valid_obs,
                entry_price=entry_price,
            )
            if not (result.is_actionable and result.sl is not None and result.tp is not None):
                continue

            is_buy = result.signal == SignalType.BUY

            if snap.fvgs and result.tp is not None:
                try:
                    atr_val = float(snap.ind.atr) if snap.ind.atr is not None else 0.0
                    if atr_val <= 0:
                        atr_val = float(snap.ind.close) * 0.02 if snap.ind.close else 0.02
                    new_targets = calculate_structural_tp(
                        direction=result.signal.value, entry=entry_price, sl=result.sl,
                        sweeps=snap.all_sweeps, order_blocks=snap.all_obs,
                        structure=snap.structure, fvgs=snap.fvgs, atr=atr_val,
                        close=float(snap.ind.close) if snap.ind.close else 0.0,
                    )
                    if new_targets:
                        result.tp = new_targets[0].price
                except Exception:
                    pass

            if result.sl is not None and cfg_full.enable_structural_sl:
                try:
                    atr_val_sl = float(snap.ind.atr) if snap.ind.atr is not None else 0.0
                    if atr_val_sl <= 0:
                        atr_val_sl = float(snap.ind.close) * 0.02 if snap.ind.close else 0.02
                    skip_structural_sl = result._sl_source == "bos"
                    if not skip_structural_sl:
                        new_sl = calculate_structural_sl(
                            direction=result.signal.value, entry=entry_price,
                            sweeps=snap.all_sweeps, order_blocks=snap.all_obs,
                            structure=snap.structure, atr=atr_val_sl,
                            close=float(snap.ind.close) if snap.ind.close else 0.0,
                        )
                        current_dist = abs(entry_price - result.sl)
                        structural_dist = abs(entry_price - new_sl)
                        if structural_dist <= current_dist and new_sl != result.sl:
                            result.sl = new_sl
                            result._sl_source = "structural"
                except Exception:
                    pass

            if cfg_full.enable_sl_distance_guard:
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
                    state_full.reject_stats.sl_distance_rejected += 1
                    state_full.reject_stats.total_rejected += 1
                    continue

            if cfg_full.enable_rr_filter:
                risk = abs(entry_price - result.sl)
                reward = abs(result.tp - entry_price)
                rr = reward / risk if risk > 0 else 0
                min_rr = config.trading.min_rr_threshold
                if rr < min_rr:
                    state_full.reject_stats.rr_rejected += 1
                    state_full.reject_stats.total_rejected += 1
                    continue

            ct = BacktestTrade(
                symbol=symbol, timeframe=tf, direction=result.signal.value,
                entry_price=entry_price, entry_index=snap.i,
                entry_timestamp=str(df.index[snap.i]),
                sl=result.sl, tp=result.tp,
                sl_source=result._sl_source or "atr",
                regime=snap.regime_obj.regime if hasattr(snap.regime_obj, 'regime') else "",
                signal_score=result.score, confidence=result.confidence,
                reasons=list(result.reasons),
            )
            state_full.in_trade = True
            state_full.ct = ct

    if state_full.in_trade and state_full.ct is not None:
        ct = state_full.ct
        ct.exit_price = float(df.iloc[-1]["close"])
        ct.exit_index = len(df) - 1
        ct.exit_timestamp = str(df.index[-1])
        ct.exit_reason = "eob"
        if ct.direction == "BUY":
            gross = (ct.exit_price - ct.entry_price) / ct.entry_price * 100
        else:
            gross = (ct.entry_price - ct.exit_price) / ct.entry_price * 100
        ct.pnl_pct = round(gross, 4)
        ct.net_pnl_pct = round(gross - (fee_pct * 2 + slip_pct * 2) * 100, 4)
        risk = abs(ct.entry_price - ct.sl)
        ct.rr = round(abs(ct.exit_price - ct.entry_price) / risk, 2) if risk > 0 else 0.0
        state_full.trades.append(ct)

    bt_full = build_result_from_state(symbol, tf, state_full, len(df))
    results["full_new"] = result_to_record(symbol, "full_new", bt_full)

    # ── Run preset B: sell_sweep_disabled (monkey-patched) ─────────────
    cfg_exp = make_config(FULL_NEW_FLAGS)
    state_exp = PresetState()

    for snap in snapshots:
        if state_exp.in_trade and state_exp.ct is not None:
            high, low = float(snap.ind.high), float(snap.ind.low)
            ct = state_exp.ct
            exited = False
            if ct.direction == "BUY":
                if low <= ct.sl:
                    ct.exit_price = ct.sl; ct.exit_index = snap.i
                    ct.exit_timestamp = str(df.index[snap.i]); ct.exit_reason = "sl"
                    exited = True
                elif high >= ct.tp:
                    ct.exit_price = ct.tp; ct.exit_index = snap.i
                    ct.exit_timestamp = str(df.index[snap.i]); ct.exit_reason = "tp"
                    exited = True
            else:
                if high >= ct.sl:
                    ct.exit_price = ct.sl; ct.exit_index = snap.i
                    ct.exit_timestamp = str(df.index[snap.i]); ct.exit_reason = "sl"
                    exited = True
                elif low <= ct.tp:
                    ct.exit_price = ct.tp; ct.exit_index = snap.i
                    ct.exit_timestamp = str(df.index[snap.i]); ct.exit_reason = "tp"
                    exited = True
            if exited:
                if ct.direction == "BUY":
                    gross = (ct.exit_price - ct.entry_price) / ct.entry_price * 100
                else:
                    gross = (ct.entry_price - ct.exit_price) / ct.entry_price * 100
                ct.pnl_pct = round(gross, 4)
                ct.net_pnl_pct = round(gross - (fee_pct * 2 + slip_pct * 2) * 100, 4)
                risk = abs(ct.entry_price - ct.sl)
                ct.rr = round(abs(ct.exit_price - ct.entry_price) / risk, 2) if risk > 0 else 0.0
                state_exp.trades.append(ct)
                state_exp.in_trade = False
                state_exp.ct = None

        if not state_exp.in_trade:
            state_exp.signals_count += 1
            if cfg_exp.enable_unified_entry and snap.confirm_entry_price is not None:
                entry_price = snap.confirm_entry_price
            else:
                entry_price = snap.entry_price_base

            if not snap.confirm_ok and cfg_exp.enable_confirm_tf_gate:
                state_exp.reject_stats.confirm_tf_rejected += 1
                state_exp.reject_stats.total_rejected += 1
                continue

            # KEY DIFFERENCE: monkey-patched evaluate strips sweep for SELL
            result = _patched_evaluate(
                signal_engine, snap.ind, regime=snap.regime_obj, structure=snap.structure,
                sweeps=snap.valid_sweeps, order_blocks=snap.valid_obs,
                entry_price=entry_price,
            )
            if not (result.is_actionable and result.sl is not None and result.tp is not None):
                continue

            is_buy = result.signal == SignalType.BUY

            if snap.fvgs and result.tp is not None:
                try:
                    atr_val = float(snap.ind.atr) if snap.ind.atr is not None else 0.0
                    if atr_val <= 0:
                        atr_val = float(snap.ind.close) * 0.02 if snap.ind.close else 0.02
                    new_targets = calculate_structural_tp(
                        direction=result.signal.value, entry=entry_price, sl=result.sl,
                        sweeps=snap.all_sweeps, order_blocks=snap.all_obs,
                        structure=snap.structure, fvgs=snap.fvgs, atr=atr_val,
                        close=float(snap.ind.close) if snap.ind.close else 0.0,
                    )
                    if new_targets:
                        result.tp = new_targets[0].price
                except Exception:
                    pass

            if result.sl is not None and cfg_exp.enable_structural_sl:
                try:
                    atr_val_sl = float(snap.ind.atr) if snap.ind.atr is not None else 0.0
                    if atr_val_sl <= 0:
                        atr_val_sl = float(snap.ind.close) * 0.02 if snap.ind.close else 0.02
                    skip_structural_sl = result._sl_source == "bos"
                    if not skip_structural_sl:
                        new_sl = calculate_structural_sl(
                            direction=result.signal.value, entry=entry_price,
                            sweeps=snap.all_sweeps, order_blocks=snap.all_obs,
                            structure=snap.structure, atr=atr_val_sl,
                            close=float(snap.ind.close) if snap.ind.close else 0.0,
                        )
                        current_dist = abs(entry_price - result.sl)
                        structural_dist = abs(entry_price - new_sl)
                        if structural_dist <= current_dist and new_sl != result.sl:
                            result.sl = new_sl
                            result._sl_source = "structural"
                except Exception:
                    pass

            if cfg_exp.enable_sl_distance_guard:
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
                    state_exp.reject_stats.sl_distance_rejected += 1
                    state_exp.reject_stats.total_rejected += 1
                    continue

            if cfg_exp.enable_rr_filter:
                risk = abs(entry_price - result.sl)
                reward = abs(result.tp - entry_price)
                rr = reward / risk if risk > 0 else 0
                min_rr = config.trading.min_rr_threshold
                if rr < min_rr:
                    state_exp.reject_stats.rr_rejected += 1
                    state_exp.reject_stats.total_rejected += 1
                    continue

            ct = BacktestTrade(
                symbol=symbol, timeframe=tf, direction=result.signal.value,
                entry_price=entry_price, entry_index=snap.i,
                entry_timestamp=str(df.index[snap.i]),
                sl=result.sl, tp=result.tp,
                sl_source=result._sl_source or "atr",
                regime=snap.regime_obj.regime if hasattr(snap.regime_obj, 'regime') else "",
                signal_score=result.score, confidence=result.confidence,
                reasons=list(result.reasons),
            )
            state_exp.in_trade = True
            state_exp.ct = ct

    if state_exp.in_trade and state_exp.ct is not None:
        ct = state_exp.ct
        ct.exit_price = float(df.iloc[-1]["close"])
        ct.exit_index = len(df) - 1
        ct.exit_timestamp = str(df.index[-1])
        ct.exit_reason = "eob"
        if ct.direction == "BUY":
            gross = (ct.exit_price - ct.entry_price) / ct.entry_price * 100
        else:
            gross = (ct.entry_price - ct.exit_price) / ct.entry_price * 100
        ct.pnl_pct = round(gross, 4)
        ct.net_pnl_pct = round(gross - (fee_pct * 2 + slip_pct * 2) * 100, 4)
        risk = abs(ct.entry_price - ct.sl)
        ct.rr = round(abs(ct.exit_price - ct.entry_price) / risk, 2) if risk > 0 else 0.0
        state_exp.trades.append(ct)

    bt_exp = build_result_from_state(symbol, tf, state_exp, len(df))
    results["sell_sweep_disabled"] = result_to_record(symbol, "sell_sweep_disabled", bt_exp)

    return results


# ─── Significance testing ─────────────────────────────────────────────

def wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score confidence interval for proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    spread = z * np.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denom
    return (round((center - spread) * 100, 2), round((center + spread) * 100, 2))


def bootstrap_ci(
    pnl_a: list[float], pnl_b: list[float], n_boot: int = 10000, ci: float = 0.95
) -> dict:
    """Bootstrap CI for difference in mean PnL."""
    rng = np.random.default_rng(42)
    diffs = []
    for _ in range(n_boot):
        sample_a = rng.choice(pnl_a, size=len(pnl_a), replace=True)
        sample_b = rng.choice(pnl_b, size=len(pnl_b), replace=True)
        diffs.append(np.mean(sample_a) - np.mean(sample_b))
    diffs = np.array(diffs)
    alpha = (1 - ci) / 2
    lo = float(np.percentile(diffs, alpha * 100))
    hi = float(np.percentile(diffs, (1 - alpha) * 100))
    return {
        "mean_diff": round(float(np.mean(diffs)), 4),
        "ci_lo": round(lo, 4),
        "ci_hi": round(hi, 4),
        "significant": lo > 0 or hi < 0,
    }


def bootstrap_wr_ci(
    wins_a: int, n_a: int, wins_b: int, n_b: int, n_boot: int = 10000
) -> dict:
    """Bootstrap CI for difference in winrate."""
    rng = np.random.default_rng(42)
    wr_a = np.array([1.0] * wins_a + [0.0] * (n_a - wins_a))
    wr_b = np.array([1.0] * wins_b + [0.0] * (n_b - wins_b))
    diffs = []
    for _ in range(n_boot):
        sa = rng.choice(wr_a, size=len(wr_a), replace=True)
        sb = rng.choice(wr_b, size=len(wr_b), replace=True)
        diffs.append(np.mean(sa) - np.mean(sb))
    diffs = np.array(diffs)
    lo = float(np.percentile(diffs, 2.5))
    hi = float(np.percentile(diffs, 97.5))
    return {
        "mean_diff_pp": round(float(np.mean(diffs)) * 100, 2),
        "ci_lo_pp": round(lo * 100, 2),
        "ci_hi_pp": round(hi * 100, 2),
        "significant": lo > 0 or hi < 0,
    }


def compute_significance(full_rec: dict, exp_rec: dict) -> dict:
    """Compute significance for all metrics."""
    sig = {}

    # Overall WR
    n_a = full_rec["total_trades"]
    n_b = exp_rec["total_trades"]
    w_a = full_rec["wins"]
    w_b = exp_rec["wins"]

    if n_a >= 30 and n_b >= 30:
        wr_boot = bootstrap_wr_ci(w_a, n_a, w_b, n_b)
        wilson_a = wilson_ci(w_a, n_a)
        wilson_b = wilson_ci(w_b, n_b)
        sig["overall_wr"] = {
            "full_new_wr": full_rec["winrate"],
            "sell_sweep_disabled_wr": exp_rec["winrate"],
            "delta_pp": round(exp_rec["winrate"] - full_rec["winrate"], 2),
            "wilson_ci_full": wilson_a,
            "wilson_ci_exp": wilson_b,
            "bootstrap_diff": wr_boot,
            "verdict": "SIGNIFICANT" if wr_boot["significant"] else "NOT SIGNIFICANT",
        }
    else:
        sig["overall_wr"] = {
            "full_new_wr": full_rec["winrate"],
            "sell_sweep_disabled_wr": exp_rec["winrate"],
            "delta_pp": round(exp_rec["winrate"] - full_rec["winrate"], 2),
            "verdict": "Low statistical confidence (N<30)",
        }

    # Overall PnL
    full_pnls = [t["pnl_pct"] for t in full_rec["trades"]]
    exp_pnls = [t["pnl_pct"] for t in exp_rec["trades"]]
    if len(full_pnls) >= 10 and len(exp_pnls) >= 10:
        pnl_boot = bootstrap_ci(full_pnls, exp_pnls)
        sig["overall_pnl"] = {
            "full_new_avg": full_rec["avg_pnl"],
            "exp_avg": exp_rec["avg_pnl"],
            "delta": round(exp_rec["avg_pnl"] - full_rec["avg_pnl"], 4),
            "bootstrap": pnl_boot,
            "verdict": "SIGNIFICANT" if pnl_boot["significant"] else "NOT SIGNIFICANT",
        }

    # BY DIRECTION
    for direction in ["BUY", "SELL"]:
        d_key = "long_stats" if direction == "BUY" else "short_stats"
        d_full = full_rec.get(d_key, {})
        d_exp = exp_rec.get(d_key, {})

        if not d_full or not d_exp:
            continue

        dn_a = d_full.get("trades", 0)
        dn_b = d_exp.get("trades", 0)
        dw_a = int(d_full.get("winrate", 0) * dn_a / 100) if dn_a > 0 else 0
        dw_b = int(d_exp.get("winrate", 0) * dn_b / 100) if dn_b > 0 else 0

        if dn_a >= 10 and dn_b >= 10:
            d_wr_boot = bootstrap_wr_ci(dw_a, dn_a, dw_b, dn_b)
            d_wilson_a = wilson_ci(dw_a, dn_a)
            d_wilson_b = wilson_ci(dw_b, dn_b)
            sig[f"{direction}_wr"] = {
                "full_new_wr": d_full.get("winrate", 0),
                "exp_wr": d_exp.get("winrate", 0),
                "delta_pp": round(d_exp.get("winrate", 0) - d_full.get("winrate", 0), 2),
                "n_full": dn_a, "n_exp": dn_b,
                "wilson_ci_full": d_wilson_a,
                "wilson_ci_exp": d_wilson_b,
                "bootstrap_diff": d_wr_boot,
                "verdict": "SIGNIFICANT" if d_wr_boot["significant"] else "NOT SIGNIFICANT",
            }
        else:
            sig[f"{direction}_wr"] = {
                "full_new_wr": d_full.get("winrate", 0),
                "exp_wr": d_exp.get("winrate", 0),
                "delta_pp": round(d_exp.get("winrate", 0) - d_full.get("winrate", 0), 2),
                "n_full": dn_a, "n_exp": dn_b,
                "verdict": "Low statistical confidence (N<30)",
            }

        # Direction PnL
        d_full_pnls = [t["pnl_pct"] for t in full_rec["trades"] if t["direction"] == direction]
        d_exp_pnls = [t["pnl_pct"] for t in exp_rec["trades"] if t["direction"] == direction]
        if len(d_full_pnls) >= 5 and len(d_exp_pnls) >= 5:
            d_pnl_boot = bootstrap_ci(d_full_pnls, d_exp_pnls)
            sig[f"{direction}_pnl"] = {
                "full_new_avg": d_full.get("pnl", 0),
                "exp_avg": d_exp.get("pnl", 0),
                "delta": round(d_exp.get("pnl", 0) - d_full.get("pnl", 0), 4),
                "bootstrap": d_pnl_boot,
                "verdict": "SIGNIFICANT" if d_pnl_boot["significant"] else "NOT SIGNIFICANT",
            }

    # BY REGIME
    for regime in ["expansion", "trend", "range", "compression"]:
        r_full = full_rec.get("regime_stats", {}).get(regime, {})
        r_exp = exp_rec.get("regime_stats", {}).get(regime, {})
        if not r_full or not r_exp:
            continue

        rn_a = r_full.get("trades", 0)
        rn_b = r_exp.get("trades", 0)
        rw_a = int(r_full.get("winrate", 0) * rn_a / 100) if rn_a > 0 else 0
        rw_b = int(r_exp.get("winrate", 0) * rn_b / 100) if rn_b > 0 else 0

        if rn_a >= 5 and rn_b >= 5:
            r_wr_boot = bootstrap_wr_ci(rw_a, rn_a, rw_b, rn_b)
            sig[f"regime_{regime}"] = {
                "full_new_wr": r_full.get("winrate", 0),
                "exp_wr": r_exp.get("winrate", 0),
                "delta_pp": round(r_exp.get("winrate", 0) - r_full.get("winrate", 0), 2),
                "n_full": rn_a, "n_exp": rn_b,
                "bootstrap_diff": r_wr_boot,
                "verdict": "SIGNIFICANT" if r_wr_boot["significant"] else "NOT SIGNIFICANT",
            }
        else:
            sig[f"regime_{regime}"] = {
                "full_new_wr": r_full.get("winrate", 0),
                "exp_wr": r_exp.get("winrate", 0),
                "delta_pp": round(r_exp.get("winrate", 0) - r_full.get("winrate", 0), 2),
                "n_full": rn_a, "n_exp": rn_b,
                "verdict": "Low statistical confidence (N<30)",
            }

    return sig


# ─── Proxy correlation analysis ───────────────────────────────────────

def compute_proxy_correlations(all_trades: list[dict]) -> dict:
    """Check if sweep is a proxy for other factors."""
    from scipy import stats as sp_stats

    sweep_trades = [t for t in all_trades if any("sweep" in r.lower() for r in t.get("reasons", []))]
    no_sweep_trades = [t for t in all_trades if not any("sweep" in r.lower() for r in t.get("reasons", []))]

    correlations = {}

    # Compare regime distribution
    for regime in ["expansion", "trend", "range", "compression"]:
        sweep_pct = sum(1 for t in sweep_trades if t.get("regime") == regime) / len(sweep_trades) * 100 if sweep_trades else 0
        no_sweep_pct = sum(1 for t in no_sweep_trades if t.get("regime") == regime) / len(no_sweep_trades) * 100 if no_sweep_trades else 0
        correlations[f"regime_{regime}"] = {
            "sweep_pct": round(sweep_pct, 1),
            "no_sweep_pct": round(no_sweep_pct, 1),
            "delta_pp": round(sweep_pct - no_sweep_pct, 1),
        }

    # Compare average score
    sweep_scores = [t.get("signal_score", 0) for t in sweep_trades]
    no_sweep_scores = [t.get("signal_score", 0) for t in no_sweep_trades]
    if sweep_scores and no_sweep_scores:
        correlations["avg_score"] = {
            "sweep": round(np.mean(sweep_scores), 2),
            "no_sweep": round(np.mean(no_sweep_scores), 2),
        }

    # Compare SL source distribution
    for src in ["atr", "bos", "structural"]:
        sweep_pct = sum(1 for t in sweep_trades if t.get("sl_source") == src) / len(sweep_trades) * 100 if sweep_trades else 0
        no_sweep_pct = sum(1 for t in no_sweep_trades if t.get("sl_source") == src) / len(no_sweep_trades) * 100 if no_sweep_trades else 0
        correlations[f"sl_source_{src}"] = {
            "sweep_pct": round(sweep_pct, 1),
            "no_sweep_pct": round(no_sweep_pct, 1),
        }

    return correlations


# ─── Feature importance (if sklearn available) ────────────────────────

def compute_feature_importance(trades: list[dict]) -> Optional[dict]:
    """Compute permutation importance for sweep vs other features."""
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.inspection import permutation_importance
    except ImportError:
        return None

    if len(trades) < 50:
        return None

    # Build feature matrix
    feature_names = ["score", "regime_trend", "regime_range", "regime_expansion", "regime_compression"]
    X = []
    y = []
    for t in trades:
        regime = t.get("regime", "range")
        row = [
            t.get("signal_score", 0),
            1 if regime == "trend" else 0,
            1 if regime == "range" else 0,
            1 if regime == "expansion" else 0,
            1 if regime == "compression" else 0,
        ]
        X.append(row)
        y.append(1 if t.get("pnl_pct", 0) > 0 else 0)

    X = np.array(X)
    y = np.array(y)

    clf = RandomForestClassifier(n_estimators=100, random_state=42, max_depth=5)
    clf.fit(X, y)

    # Permutation importance
    perm_imp = permutation_importance(clf, X, y, n_repeats=10, random_state=42)

    result = {}
    for i, name in enumerate(feature_names):
        result[name] = {
            "importance_mean": round(float(perm_imp.importances_mean[i]), 4),
            "importance_std": round(float(perm_imp.importances_std[i]), 4),
        }

    return result


# ─── Main ─────────────────────────────────────────────────────────────

async def main():
    from backtest.cache_ohlcv import load_cached

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("  SWEEP DIRECTIONAL A/B EXPERIMENT")
    print("  Hypothesis: Sweep degrades SELL but not BUY")
    print("  Presets: full_new vs sell_sweep_disabled")
    print("  Symbols:", ", ".join(SYMBOLS))
    print("=" * 70)

    indicator_engine = IndicatorEngine()
    all_symbol_results = {}

    for sym_idx, symbol in enumerate(SYMBOLS, 1):
        print(f"\n[{sym_idx}/{len(SYMBOLS)}] {symbol} — loading data...", end=" ", flush=True)
        t0 = time.time()

        cached_1h = load_cached(symbol, TIMEFRAME, CANDLES)
        cached_15m = load_cached(symbol, CONFIRM_TF, CONFIRM_CANDLES)

        if cached_1h is None:
            print("NO 1h CACHE — skipping")
            continue

        df = cached_1h.copy()
        confirm_df = cached_15m.copy() if cached_15m is not None else None

        elapsed_load = time.time() - t0
        print(f"loaded ({elapsed_load:.1f}s) — running A/B...", end=" ", flush=True)

        t1 = time.time()
        sym_results = await run_ab_for_symbol(symbol, df, confirm_df, indicator_engine)
        elapsed_run = time.time() - t1

        all_symbol_results[symbol] = sym_results

        fn = sym_results.get("full_new", {})
        ssd = sym_results.get("sell_sweep_disabled", {})
        print(f"done ({elapsed_run:.1f}s)  full_new={fn.get('total_trades',0)}T WR={fn.get('winrate',0):.1f}%  "
              f"exp={ssd.get('total_trades',0)}T WR={ssd.get('winrate',0):.1f}%")

    # ── Aggregate results ──────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("  AGGREGATING RESULTS")
    print(f"{'='*70}")

    agg = {"full_new": {}, "sell_sweep_disabled": {}}
    all_trades_full = []
    all_trades_exp = []

    for preset in ["full_new", "sell_sweep_disabled"]:
        preset_records = [all_symbol_results[s][preset] for s in SYMBOLS if s in all_symbol_results and preset in all_symbol_results[s]]
        if not preset_records:
            continue

        total_trades = sum(r["total_trades"] for r in preset_records)
        if total_trades == 0:
            agg[preset] = {"total_trades": 0}
            continue

        total_wins = sum(r["wins"] for r in preset_records)
        total_pnl = sum(r["total_pnl_pct"] for r in preset_records)
        total_net = sum(r["total_net_pnl_pct"] for r in preset_records)
        total_signals = sum(r["signals_generated"] for r in preset_records)
        total_rejected = sum(r["signals_rejected"] for r in preset_records)

        # Collect all trades for direction/regime analysis
        all_preset_trades = []
        for r in preset_records:
            all_preset_trades.extend(r["trades"])
            if preset == "full_new":
                all_trades_full.extend(r["trades"])
            else:
                all_trades_exp.extend(r["trades"])

        # Aggregate direction stats
        long_stats = {}
        short_stats = {}
        for d_label in ["BUY", "SELL"]:
            d_trades = [t for t in all_preset_trades if t["direction"] == d_label]
            if not d_trades: continue
            d_wins = sum(1 for t in d_trades if t["pnl_pct"] > 0)
            d_pnl = sum(t["pnl_pct"] for t in d_trades)
            d_net = sum(t["net_pnl_pct"] for t in d_trades)
            d_wr = d_wins / len(d_trades) * 100 if d_trades else 0
            d_pf_num = sum(t["pnl_pct"] for t in d_trades if t["pnl_pct"] > 0)
            d_pf_den = abs(sum(t["pnl_pct"] for t in d_trades if t["pnl_pct"] <= 0))
            d_pf = d_pf_num / d_pf_den if d_pf_den > 0 else float("inf")
            stats = {"trades": len(d_trades), "winrate": round(d_wr, 1), "pnl": round(d_pnl, 4),
                     "net_pnl": round(d_net, 4), "pf": round(d_pf, 2)}
            if d_label == "BUY": long_stats = stats
            else: short_stats = stats

        # Aggregate regime stats
        regimes = {}
        for t in all_preset_trades:
            regimes.setdefault(t.get("regime", "unknown"), []).append(t)
        regime_stats = {}
        for reg, r_trades in regimes.items():
            r_wins = sum(1 for t in r_trades if t["pnl_pct"] > 0)
            r_pnl = sum(t["pnl_pct"] for t in r_trades)
            r_net = sum(t["net_pnl_pct"] for t in r_trades)
            r_wr = r_wins / len(r_trades) * 100 if r_trades else 0
            regime_stats[reg] = {"trades": len(r_trades), "winrate": round(r_wr, 1),
                                 "pnl": round(r_pnl, 4), "net_pnl": round(r_net, 4)}

        gross_profit = sum(r["total_pnl_pct"] for r in preset_records if r["total_pnl_pct"] > 0)
        gross_loss = abs(sum(r["total_pnl_pct"] for r in preset_records if r["total_pnl_pct"] < 0))

        agg[preset] = {
            "total_trades": total_trades,
            "symbols": len(preset_records),
            "winrate": round(total_wins / total_trades * 100, 1) if total_trades else 0,
            "total_pnl_pct": round(total_pnl, 4),
            "total_net_pnl_pct": round(total_net, 4),
            "avg_pnl": round(sum(r["avg_pnl"] * r["total_trades"] for r in preset_records) / total_trades, 4) if total_trades else 0,
            "avg_net_pnl": round(sum(r["avg_net_pnl"] * r["total_trades"] for r in preset_records) / total_trades, 4) if total_trades else 0,
            "avg_rr": round(sum(r["avg_rr"] * r["total_trades"] for r in preset_records) / total_trades, 2) if total_trades else 0,
            "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0,
            "expectancy": round(sum(r["expectancy"] * r["total_trades"] for r in preset_records) / total_trades, 4) if total_trades else 0,
            "sharpe_ratio": round(sum(r["sharpe_ratio"] for r in preset_records) / len(preset_records), 2) if preset_records else 0,
            "max_drawdown": round(max(r["max_drawdown"] for r in preset_records), 4) if preset_records else 0,
            "signals_generated": total_signals,
            "signals_rejected": total_rejected,
            "exit_sl": sum(r["exit_sl"] for r in preset_records),
            "exit_tp": sum(r["exit_tp"] for r in preset_records),
            "exit_eob": sum(r["exit_eob"] for r in preset_records),
            "src_atr": sum(r["src_atr"] for r in preset_records),
            "src_bos": sum(r["src_bos"] for r in preset_records),
            "src_structural": sum(r["src_structural"] for r in preset_records),
            "long_stats": long_stats,
            "short_stats": short_stats,
            "regime_stats": regime_stats,
        }

    # ── Significance testing ───────────────────────────────────────────
    print("\n  Computing significance...")
    significance = compute_significance(agg["full_new"], agg["sell_sweep_disabled"])

    # ── Proxy correlation ──────────────────────────────────────────────
    print("  Computing proxy correlations...")
    proxy_corr = compute_proxy_correlations(all_trades_full)

    # ── Feature importance ─────────────────────────────────────────────
    print("  Computing feature importance...")
    feat_imp_full = compute_feature_importance(all_trades_full)
    feat_imp_exp = compute_feature_importance(all_trades_exp)

    # ── Unintended consequences ────────────────────────────────────────
    unintended = {
        "signal_count_change": agg["sell_sweep_disabled"].get("total_trades", 0) - agg["full_new"].get("total_trades", 0),
        "regime_mix_change": {},
        "sl_source_change": {},
    }
    for regime in set(list(agg["full_new"].get("regime_stats", {}).keys()) + list(agg["sell_sweep_disabled"].get("regime_stats", {}).keys())):
        fn_r = agg["full_new"].get("regime_stats", {}).get(regime, {}).get("trades", 0)
        exp_r = agg["sell_sweep_disabled"].get("regime_stats", {}).get(regime, {}).get("trades", 0)
        unintended["regime_mix_change"][regime] = {"full_new": fn_r, "sell_sweep_disabled": exp_r, "delta": exp_r - fn_r}

    for src in ["atr", "bos", "structural"]:
        fn_s = agg["full_new"].get(f"src_{src}", 0)
        exp_s = agg["sell_sweep_disabled"].get(f"src_{src}", 0)
        unintended["sl_source_change"][src] = {"full_new": fn_s, "sell_sweep_disabled": exp_s, "delta": exp_s - fn_s}

    # ── Trade diff analysis ────────────────────────────────────────────
    # Match trades by (symbol, entry_timestamp) to find disappeared/new trades
    full_trade_keys = {(t["symbol"], t["entry_timestamp"]): t for t in all_trades_full}
    exp_trade_keys = {(t["symbol"], t["entry_timestamp"]): t for t in all_trades_exp}

    disappeared = []
    for key, t in full_trade_keys.items():
        if key not in exp_trade_keys and t["direction"] == "SELL":
            disappeared.append(t)

    new_trades = []
    for key, t in exp_trade_keys.items():
        if key not in full_trade_keys and t["direction"] == "SELL":
            new_trades.append(t)

    # ── Save raw results ───────────────────────────────────────────────
    raw_output = {
        "agg": agg,
        "significance": significance,
        "proxy_correlation": proxy_corr,
        "feature_importance": {"full_new": feat_imp_full, "sell_sweep_disabled": feat_imp_exp},
        "unintended_consequences": unintended,
        "disappeared_sell_trades": disappeared[:50],
        "new_sell_trades": new_trades[:50],
        "per_symbol": {s: {p: {k: v for k, v in r.items() if k != "trades"} for p, r in presets.items()} for s, presets in all_symbol_results.items()},
    }

    raw_path = RESULTS_DIR / "sweep_experiment_results.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Saved raw results to {raw_path}")

    # ── Print summary ──────────────────────────────────────────────────
    print(f"\n{'='*90}")
    print(f"  RESULTS SUMMARY")
    print(f"{'='*90}")
    print(f"  {'Metric':30s} {'full_new':>14s} {'sell_sweep_dis':>14s} {'Delta':>10s} {'Verdict':>16s}")
    print(f"  {'-'*30} {'-'*14} {'-'*14} {'-'*10} {'-'*16}")

    fn = agg.get("full_new", {})
    ex = agg.get("sell_sweep_disabled", {})

    rows = [
        ("Trades", fn.get("total_trades", 0), ex.get("total_trades", 0), ex.get("total_trades", 0) - fn.get("total_trades", 0), ""),
        ("Winrate %", fn.get("winrate", 0), ex.get("winrate", 0), ex.get("winrate", 0) - fn.get("winrate", 0),
         significance.get("overall_wr", {}).get("verdict", "")),
        ("Avg PnL %", fn.get("avg_pnl", 0), ex.get("avg_pnl", 0), ex.get("avg_pnl", 0) - fn.get("avg_pnl", 0), ""),
        ("Avg Net PnL %", fn.get("avg_net_pnl", 0), ex.get("avg_net_pnl", 0), ex.get("avg_net_pnl", 0) - fn.get("avg_net_pnl", 0), ""),
        ("Profit Factor", fn.get("profit_factor", 0), ex.get("profit_factor", 0), ex.get("profit_factor", 0) - fn.get("profit_factor", 0), ""),
        ("Expectancy", fn.get("expectancy", 0), ex.get("expectancy", 0), ex.get("expectancy", 0) - fn.get("expectancy", 0), ""),
        ("Max DD %", fn.get("max_drawdown", 0), ex.get("max_drawdown", 0), ex.get("max_drawdown", 0) - fn.get("max_drawdown", 0), ""),
        ("Sharpe", fn.get("sharpe_ratio", 0), ex.get("sharpe_ratio", 0), ex.get("sharpe_ratio", 0) - fn.get("sharpe_ratio", 0), ""),
    ]
    for label, v_a, v_b, delta, verdict in rows:
        print(f"  {label:30s} {v_a:14.2f} {v_b:14.2f} {delta:+10.2f} {verdict:>16s}")

    # Direction breakdown
    print(f"\n  {'Direction':10s} {'Metric':20s} {'full_new':>12s} {'sell_sweep_dis':>14s} {'Delta':>10s} {'Verdict':>16s}")
    print(f"  {'-'*10} {'-'*20} {'-'*12} {'-'*14} {'-'*10} {'-'*16}")
    for direction in ["BUY", "SELL"]:
        d_key = "long_stats" if direction == "BUY" else "short_stats"
        d_fn = fn.get(d_key, {})
        d_ex = ex.get(d_key, {})
        if not d_fn or not d_ex:
            continue
        for metric, key in [("Trades", "trades"), ("WR%", "winrate"), ("PnL%", "pnl")]:
            v_a = d_fn.get(key, 0)
            v_b = d_ex.get(key, 0)
            delta = v_b - v_a
            sig_key = f"{direction}_wr" if key == "winrate" else f"{direction}_pnl" if key == "pnl" else ""
            verdict = significance.get(sig_key, {}).get("verdict", "") if sig_key else ""
            print(f"  {direction:10s} {metric:20s} {v_a:12.2f} {v_b:14.2f} {delta:+10.2f} {verdict:>16s}")

    # Regime breakdown
    print(f"\n  {'Regime':15s} {'Metric':12s} {'full_new':>10s} {'sell_sweep_dis':>14s} {'Delta':>8s} {'Verdict':>16s}")
    print(f"  {'-'*15} {'-'*12} {'-'*10} {'-'*14} {'-'*8} {'-'*16}")
    for regime in ["expansion", "trend", "range", "compression"]:
        r_fn = fn.get("regime_stats", {}).get(regime, {})
        r_ex = ex.get("regime_stats", {}).get(regime, {})
        if not r_fn and not r_ex:
            continue
        for metric, key in [("Trades", "trades"), ("WR%", "winrate"), ("PnL%", "pnl")]:
            v_a = r_fn.get(key, 0)
            v_b = r_ex.get(key, 0)
            delta = v_b - v_a
            sig_key = f"regime_{regime}"
            verdict = significance.get(sig_key, {}).get("verdict", "") if metric == "WR%" else ""
            print(f"  {regime:15s} {metric:12s} {v_a:10.2f} {v_b:14.2f} {delta:+8.2f} {verdict:>16s}")

    print(f"\n  Disappeared SELL trades: {len(disappeared)}")
    print(f"  New SELL trades: {len(new_trades)}")

    return raw_output


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
