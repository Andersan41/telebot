"""
Batch runner: for each symbol, compute indicators ONCE, then evaluate all 10 presets.
This reduces 200 full runs to 20 indicator passes + 10 preset evaluations each.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_saved_stdout = sys.stdout
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger as _loguru_logger
_loguru_logger.disable("strategy.signal_engine")
_loguru_logger.disable("indicators.engine")
import logging
logging.getLogger("strategy.signal_engine").setLevel(logging.WARNING)
logging.getLogger("indicators.engine").setLevel(logging.WARNING)

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional, Literal

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

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "XRP/USDT", "SOL/USDT", "DOGE/USDT",
    "AVAX/USDT", "LINK/USDT", "ADA/USDT", "DOT/USDT", "UNI/USDT",
    "NEAR/USDT", "APT/USDT", "ARB/USDT", "OP/USDT", "SUI/USDT",
    "INJ/USDT", "WIF/USDT", "FLOKI/USDT", "FIL/USDT", "GRT/USDT",
]

TIMEFRAME = "1h"
CANDLES = 3900
CONFIRM_TF = "15m"
CONFIRM_CANDLES = 15552
WARMUP = 80

PRESETS = {
    "true_baseline": {
        "enable_unified_entry": False, "enable_confirm_tf_gate": False,
        "enable_structural_sl": False, "enable_sl_distance_guard": False,
        "enable_rr_filter": False, "enable_news_filter": False, "enable_stop_hunt_buffer": False,
    },
    "unified_only": {
        "enable_unified_entry": True, "enable_confirm_tf_gate": False,
        "enable_structural_sl": False, "enable_sl_distance_guard": False,
        "enable_rr_filter": False, "enable_news_filter": False, "enable_stop_hunt_buffer": False,
    },
    "structural_sl_only": {
        "enable_unified_entry": False, "enable_confirm_tf_gate": False,
        "enable_structural_sl": True, "enable_sl_distance_guard": False,
        "enable_rr_filter": False, "enable_news_filter": False, "enable_stop_hunt_buffer": False,
    },
    "sl_guard_only": {
        "enable_unified_entry": False, "enable_confirm_tf_gate": False,
        "enable_structural_sl": False, "enable_sl_distance_guard": True,
        "enable_rr_filter": False, "enable_news_filter": False, "enable_stop_hunt_buffer": False,
    },
    "rr_filter_only": {
        "enable_unified_entry": False, "enable_confirm_tf_gate": False,
        "enable_structural_sl": False, "enable_sl_distance_guard": False,
        "enable_rr_filter": True, "enable_news_filter": False, "enable_stop_hunt_buffer": False,
    },
    "gate_only": {
        "enable_unified_entry": False, "enable_confirm_tf_gate": True,
        "enable_structural_sl": False, "enable_sl_distance_guard": False,
        "enable_rr_filter": False, "enable_news_filter": False, "enable_stop_hunt_buffer": False,
    },
    "buffer_only": {
        "enable_unified_entry": False, "enable_confirm_tf_gate": False,
        "enable_structural_sl": True, "enable_sl_distance_guard": False,
        "enable_rr_filter": False, "enable_news_filter": False, "enable_stop_hunt_buffer": True,
    },
    "full_old": {
        "enable_unified_entry": True, "enable_confirm_tf_gate": True,
        "enable_structural_sl": True, "enable_sl_distance_guard": True,
        "enable_rr_filter": True, "enable_news_filter": True, "enable_stop_hunt_buffer": True,
    },
    "full_new": {
        "enable_unified_entry": True, "enable_confirm_tf_gate": False,
        "enable_structural_sl": True, "enable_sl_distance_guard": True,
        "enable_rr_filter": True, "enable_news_filter": True, "enable_stop_hunt_buffer": False,
    },
    "unified_plus_filters": {
        "enable_unified_entry": True, "enable_confirm_tf_gate": False,
        "enable_structural_sl": True, "enable_sl_distance_guard": True,
        "enable_rr_filter": True, "enable_news_filter": False, "enable_stop_hunt_buffer": False,
    },
    "score5_only": {
        "enable_unified_entry": True, "enable_confirm_tf_gate": False,
        "enable_structural_sl": True, "enable_sl_distance_guard": True,
        "enable_rr_filter": True, "enable_news_filter": True, "enable_stop_hunt_buffer": False,
        "min_score_for_signal": 5,
    },
}
PRESET_ORDER = list(PRESETS.keys())

RESULTS_DIR = Path(__file__).parent.parent / "reports" / "abn"


@dataclass
class CandleSnapshot:
    """Pre-computed per-candle data shared across all presets."""
    i: int
    ind: IndicatorValues
    regime_obj: object
    structure: object
    all_sweeps: list
    all_obs: list
    valid_sweeps: list
    valid_obs: list
    fvgs: list
    entry_price_base: float  # ind.close
    confirm_entry_price: Optional[float]  # from confirm TF (if available)
    confirm_ok: bool  # confirm TF alignment


@dataclass
class PresetState:
    """Mutable state for a single preset during candle walk."""
    in_trade: bool = False
    ct: Optional[BacktestTrade] = None
    trades: list = field(default_factory=list)
    reject_stats: RejectStats = field(default_factory=RejectStats)
    signals_count: int = 0


def make_config(flags: dict) -> BacktestConfig:
    return BacktestConfig(**flags)


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
            "regime": t.regime, "entry_timestamp": t.entry_timestamp,
            "exit_timestamp": t.exit_timestamp,
        })
        if t.exit_reason == "sl": rec["exit_sl"] += 1
        elif t.exit_reason == "tp": rec["exit_tp"] += 1
        elif t.exit_reason == "eob": rec["exit_eob"] += 1
        src = t.sl_source or "atr"
        if src == "bos": rec["src_bos"] += 1
        elif src == "structural": rec["src_structural"] += 1
        else: rec["src_atr"] += 1
    return rec


def aggregate_records(records: list[dict]) -> dict:
    if not records:
        return {}
    total_trades = sum(r["total_trades"] for r in records)
    if total_trades == 0:
        return {"total_trades": 0, "symbols": len(records), "winrate": 0.0,
                "total_pnl_pct": 0.0, "total_net_pnl_pct": 0.0}
    total_wins = sum(r["wins"] for r in records)
    total_pnl = sum(r["total_pnl_pct"] for r in records)
    total_net_pnl = sum(r["total_net_pnl_pct"] for r in records)
    total_signals = sum(r["signals_generated"] for r in records)
    total_rejected = sum(r["signals_rejected"] for r in records)
    total_exit_sl = sum(r["exit_sl"] for r in records)
    total_exit_tp = sum(r["exit_tp"] for r in records)
    total_exit_eob = sum(r["exit_eob"] for r in records)
    total_src_atr = sum(r["src_atr"] for r in records)
    total_src_bos = sum(r["src_bos"] for r in records)
    total_src_structural = sum(r["src_structural"] for r in records)
    total_rr = sum(r["avg_rr"] * r["total_trades"] for r in records)
    total_reject_rr = sum(r["reject_rr"] for r in records)
    total_reject_sl = sum(r["reject_sl_dist"] for r in records)
    total_reject_ctf = sum(r["reject_confirm_tf"] for r in records)
    max_dd = max(r["max_drawdown"] for r in records) if records else 0.0
    gross_profit = sum(r["total_pnl_pct"] for r in records if r["total_pnl_pct"] > 0)
    gross_loss = abs(sum(r["total_pnl_pct"] for r in records if r["total_pnl_pct"] < 0))
    return {
        "total_trades": total_trades, "symbols": len(records),
        "winrate": round(total_wins / total_trades * 100, 1),
        "avg_pnl": round(sum(r["avg_pnl"] * r["total_trades"] for r in records) / total_trades, 4),
        "avg_net_pnl": round(sum(r["avg_net_pnl"] * r["total_trades"] for r in records) / total_trades, 4),
        "avg_rr": round(total_rr / total_trades, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0,
        "expectancy": round(sum(r["expectancy"] * r["total_trades"] for r in records) / total_trades, 4),
        "max_drawdown": round(max_dd, 4),
        "total_pnl_pct": round(total_pnl, 4),
        "total_net_pnl_pct": round(total_net_pnl, 4),
        "signals_generated": total_signals, "signals_rejected": total_rejected,
        "exit_sl": total_exit_sl, "exit_tp": total_exit_tp, "exit_eob": total_exit_eob,
        "src_atr": total_src_atr, "src_bos": total_src_bos, "src_structural": total_src_structural,
        "reject_rr": total_reject_rr, "reject_sl_dist": total_reject_sl,
        "reject_confirm_tf": total_reject_ctf,
    }


def build_result_from_state(symbol: str, timeframe: str, state: PresetState, total_candles: int) -> BacktestResult:
    """Build BacktestResult from PresetState."""
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


async def run_symbol_batch(symbol: str, df: pd.DataFrame, confirm_df: Optional[pd.DataFrame],
                           indicator_engine: IndicatorEngine,
                           presets: Optional[dict] = None,
                           preset_order: Optional[list] = None) -> dict[str, dict]:
    """Run presets for one symbol, sharing indicator computation.
    
    If presets/preset_order are None, uses module-level PRESETS/PRESET_ORDER.
    """
    _presets = presets if presets is not None else PRESETS
    _order = preset_order if preset_order is not None else PRESET_ORDER
    tf = TIMEFRAME
    confirm_tf = CONFIRM_TF
    results = {}

    # Pre-compute all candle snapshots
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

    # Now evaluate each preset using pre-computed snapshots
    for preset_name in _order:
        cfg = make_config(_presets[preset_name])
        state = PresetState()
        fee_pct = config.trading.exchange_fee_pct / 100.0
        slip_pct = config.trading.slippage_pct / 100.0

        # Override min_score_for_signal if configured in BacktestConfig
        _orig_min_score = config.scoring.min_score_for_signal
        if cfg.min_score_for_signal is not None:
            config.scoring.min_score_for_signal = cfg.min_score_for_signal

        for snap in snapshots:
            # --- Exit check ---
            if state.in_trade and state.ct is not None:
                high, low = float(snap.ind.high), float(snap.ind.low)
                ct = state.ct
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
                    # Compute PnL
                    if ct.direction == "BUY":
                        gross = (ct.exit_price - ct.entry_price) / ct.entry_price * 100
                    else:
                        gross = (ct.entry_price - ct.exit_price) / ct.entry_price * 100
                    ct.pnl_pct = round(gross, 4)
                    ct.net_pnl_pct = round(gross - (fee_pct * 2 + slip_pct * 2) * 100, 4)
                    risk = abs(ct.entry_price - ct.sl)
                    ct.rr = round(abs(ct.exit_price - ct.entry_price) / risk, 2) if risk > 0 else 0.0
                    state.trades.append(ct)
                    state.in_trade = False
                    state.ct = None

            # --- New signal ---
            if not state.in_trade:
                state.signals_count += 1

                # Entry price
                if cfg.enable_unified_entry and snap.confirm_entry_price is not None:
                    entry_price = snap.confirm_entry_price
                else:
                    entry_price = snap.entry_price_base

                # Confirm TF gate
                if not snap.confirm_ok and cfg.enable_confirm_tf_gate:
                    state.reject_stats.confirm_tf_rejected += 1
                    state.reject_stats.total_rejected += 1
                    continue

                # Signal evaluation
                result = signal_engine.evaluate(
                    snap.ind, regime=snap.regime_obj, structure=snap.structure,
                    sweeps=snap.valid_sweeps, order_blocks=snap.valid_obs,
                    entry_price=entry_price,
                )
                if not (result.is_actionable and result.sl is not None and result.tp is not None):
                    continue

                is_buy = result.signal == SignalType.BUY

                # TP recalc with FVGs
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

                # Structural SL
                if result.sl is not None and cfg.enable_structural_sl:
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
                            structural_sl_applied = False
                            if structural_dist <= current_dist and new_sl != result.sl:
                                result.sl = new_sl
                                structural_sl_applied = True
                                result._sl_source = "structural"
                            if structural_sl_applied and cfg.enable_stop_hunt_buffer and config.trading.stop_hunt_buffer_pct > 0:
                                buffer_pct = config.trading.stop_hunt_buffer_pct / 100.0
                                if is_buy:
                                    result.sl = round(result.sl * (1 - buffer_pct), 8)
                                else:
                                    result.sl = round(result.sl * (1 + buffer_pct), 8)
                    except Exception:
                        pass

                # SL distance guard
                if cfg.enable_sl_distance_guard:
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
                        state.reject_stats.sl_distance_rejected += 1
                        state.reject_stats.total_rejected += 1
                        continue

                # RR filter
                if cfg.enable_rr_filter:
                    risk = abs(entry_price - result.sl)
                    reward = abs(result.tp - entry_price)
                    rr = reward / risk if risk > 0 else 0
                    min_rr = config.trading.min_rr_threshold
                    if rr < min_rr:
                        state.reject_stats.rr_rejected += 1
                        state.reject_stats.total_rejected += 1
                        continue

                # Build trade
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
                state.in_trade = True
                state.ct = ct

        # Close open trade at end
        if state.in_trade and state.ct is not None:
            ct = state.ct
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
            state.trades.append(ct)

        # Restore min_score_for_signal after preset evaluation
        config.scoring.min_score_for_signal = _orig_min_score

        bt_result = build_result_from_state(symbol, tf, state, len(df))
        results[preset_name] = result_to_record(symbol, preset_name, bt_result)

    return results


async def main():
    from backtest.cache_ohlcv import load_cached, CACHE_DIR

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    partial_path = RESULTS_DIR / "raw_results_r6.jsonl"

    # Load existing results
    all_results: dict[str, dict] = {}
    if partial_path.exists():
        with open(partial_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                rec = json.loads(line)
                key = f"{rec['symbol']}|{rec['preset']}"
                all_results[key] = rec

    total_runs = len(SYMBOLS) * len(PRESETS)
    completed = len(all_results)
    print(f"=" * 70)
    print(f"  BATCH BACKTEST R6: {len(SYMBOLS)} symbols x {len(PRESETS)} presets = {total_runs} runs")
    print(f"  Candles: {CANDLES} (~{CANDLES / 24:.0f} days)")
    print(f"  Already completed: {completed}/{total_runs}")
    print(f"=" * 70)

    indicator_engine = IndicatorEngine()

    with open(partial_path, "a", encoding="utf-8") as f:
        for sym_idx, symbol in enumerate(SYMBOLS, 1):
            # Check if all presets for this symbol are done
            all_done = all(f"{symbol}|{p}" in all_results for p in PRESET_ORDER)
            if all_done:
                print(f"  [{sym_idx}/{len(SYMBOLS)}] SKIP {symbol} (all presets done)")
                continue

            print(f"\n  [{sym_idx}/{len(SYMBOLS)}] {symbol} — loading data...", end=" ", flush=True)
            t0 = time.time()

            cached_1h = load_cached(symbol, TIMEFRAME, CANDLES)
            cached_15m = load_cached(symbol, CONFIRM_TF, CONFIRM_CANDLES)

            if cached_1h is None:
                print(f"NO 1h CACHE — skipping")
                continue

            df = cached_1h.copy()
            confirm_df = cached_15m.copy() if cached_15m is not None else None

            elapsed_load = time.time() - t0
            print(f"loaded ({elapsed_load:.1f}s) — running 10 presets...", end=" ", flush=True)

            t1 = time.time()
            batch_results = await run_symbol_batch(symbol, df, confirm_df, indicator_engine)
            elapsed_run = time.time() - t1

            # Save results
            for preset_name, rec in batch_results.items():
                key = f"{symbol}|{preset_name}"
                all_results[key] = rec
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()

            # Summary for this symbol
            best_preset = max(batch_results.items(), key=lambda x: x[1].get("total_net_pnl_pct", 0))
            print(f"done ({elapsed_run:.1f}s) best={best_preset[0]} pnl={best_preset[1]['total_net_pnl_pct']:+.2f}%")

    # Save complete results
    results_json = RESULTS_DIR / "raw_results_r6.json"
    with open(results_json, "w", encoding="utf-8") as f:
        json.dump(list(all_results.values()), f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(all_results)} results to {results_json}")

    # Build aggregates
    agg: dict[str, dict] = {}
    for preset in PRESET_ORDER:
        preset_records = [all_results[f"{s}|{preset}"] for s in SYMBOLS if f"{s}|{preset}" in all_results]
        agg[preset] = aggregate_records(preset_records)

    agg_json = RESULTS_DIR / "aggregates_r6.json"
    with open(agg_json, "w", encoding="utf-8") as f:
        json.dump(agg, f, indent=2, ensure_ascii=False)
    print(f"Saved aggregates to {agg_json}")

    # Print summary
    print(f"\n{'='*90}")
    print(f"  SUMMARY: {len(PRESETS)} presets × {len(SYMBOLS)} symbols")
    print(f"{'='*90}")
    print(f"  {'Preset':28s} {'Trades':>6s} {'WR%':>6s} {'PnL(net)':>10s} {'PF':>6s} {'MaxDD':>8s} {'AvgRR':>6s}")
    print(f"  {'-'*28} {'-'*6} {'-'*6} {'-'*10} {'-'*6} {'-'*8} {'-'*6}")
    for preset in PRESET_ORDER:
        a = agg.get(preset, {})
        print(f"  {preset:28s} {a.get('total_trades', 0):6d} {a.get('winrate', 0):5.1f}% "
              f"{a.get('total_net_pnl_pct', 0):+9.2f}% {a.get('profit_factor', 0):5.2f} "
              f"{a.get('max_drawdown', 0):7.2f}% {a.get('avg_rr', 0):5.2f}")


if __name__ == "__main__":
    asyncio.run(main())
