"""
Minimal edge discovery runner: pre-compute snapshots ONCE per symbol,
then evaluate full_new preset with score capture. Analyze and generate reports.

Uses batch-computation approach from run_r6_batch.py for speed.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

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

from backtest.engine import (
    BacktestConfig, BacktestResult, BacktestTrade, RejectStats,
    _compute_regime, _normalize_symbol,
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

REPORTS_DIR = Path(__file__).parent.parent / "reports" / "analysis"

FULL_NEW_FLAGS = {
    "enable_unified_entry": True,
    "enable_confirm_tf_gate": False,
    "enable_structural_sl": True,
    "enable_sl_distance_guard": True,
    "enable_rr_filter": True,
    "enable_news_filter": True,
    "enable_stop_hunt_buffer": False,
}


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


def precompute_snapshots(
    symbol: str, df: pd.DataFrame, confirm_df: Optional[pd.DataFrame],
    indicator_engine: IndicatorEngine,
) -> list[CandleSnapshot]:
    tf = TIMEFRAME
    confirm_tf = CONFIRM_TF
    snapshots = []
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

    return snapshots


def evaluate_config(
    symbol: str, df: pd.DataFrame, snapshots: list[CandleSnapshot],
    bt_config: BacktestConfig, min_score: int = 2, compression_enabled: bool = True,
) -> list[dict]:
    tf = TIMEFRAME
    fee_pct = config.trading.exchange_fee_pct / 100.0
    slip_pct = config.trading.slippage_pct / 100.0

    orig_min_score = config.scoring.min_score_for_signal
    orig_compression = config.trading.compression_enabled
    config.scoring.min_score_for_signal = min_score
    config.trading.compression_enabled = compression_enabled

    in_trade = False
    ct = None
    trades = []
    signals_count = 0

    for snap in snapshots:
        if in_trade and ct is not None:
            high, low = float(snap.ind.high), float(snap.ind.low)
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
                trades.append({
                    "symbol": symbol, "direction": ct.direction,
                    "entry_price": ct.entry_price, "exit_price": ct.exit_price,
                    "exit_reason": ct.exit_reason, "pnl_pct": ct.pnl_pct,
                    "net_pnl_pct": ct.net_pnl_pct, "rr": ct.rr,
                    "sl_source": ct.sl_source, "regime": ct.regime,
                    "score": ct.signal_score,
                    "entry_timestamp": ct.entry_timestamp,
                    "exit_timestamp": ct.exit_timestamp,
                })
                in_trade = False
                ct = None

        if not in_trade:
            signals_count += 1

            if bt_config.enable_unified_entry and snap.confirm_entry_price is not None:
                entry_price = snap.confirm_entry_price
            else:
                entry_price = snap.entry_price_base

            if not snap.confirm_ok and bt_config.enable_confirm_tf_gate:
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

            if result.sl is not None and bt_config.enable_structural_sl:
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
                        if result._sl_source == "structural" and bt_config.enable_stop_hunt_buffer and config.trading.stop_hunt_buffer_pct > 0:
                            buffer_pct = config.trading.stop_hunt_buffer_pct / 100.0
                            if is_buy:
                                result.sl = round(result.sl * (1 - buffer_pct), 8)
                            else:
                                result.sl = round(result.sl * (1 + buffer_pct), 8)
                except Exception:
                    pass

            if bt_config.enable_sl_distance_guard:
                sl_dist_pct = abs(entry_price - result.sl) / entry_price * 100
                min_dist = config.trading.min_sl_distance_pct
                max_dist = config.trading.max_sl_distance_pct
                if sl_dist_pct < min_dist:
                    if is_buy:
                        result.sl = round(entry_price * (1 - min_dist / 100), 8)
                    else:
                        result.sl = round(entry_price * (1 + min_dist / 100), 8)
                elif sl_dist_pct > max_dist:
                    continue

            if bt_config.enable_rr_filter:
                risk = abs(entry_price - result.sl)
                reward = abs(result.tp - entry_price)
                rr = reward / risk if risk > 0 else 0
                min_rr = config.trading.min_rr_threshold
                if rr < min_rr:
                    continue

            ct = BacktestTrade(
                symbol=symbol, timeframe=tf, direction=result.signal.value,
                entry_price=entry_price, entry_index=snap.i,
                entry_timestamp=str(df.index[snap.i]),
                sl=result.sl, tp=result.tp,
                sl_source=result._sl_source or "atr",
                regime=snap.regime_obj.regime if hasattr(snap.regime_obj, "regime") else "",
                signal_score=result.score, confidence=result.confidence,
                reasons=list(result.reasons),
                factor_strengths=dict(result._factor_strengths),
                factor_present={k: v > 0 for k, v in result._factor_strengths.items()
                                if k not in ("BUY", "SELL")},
                verdict=result.score_verdict,
                confidence_v2_score=result._confidence_v2.confidence_pct if result._confidence_v2 else 0.0,
                confidence_v2_quality=result._confidence_v2.quality if result._confidence_v2 else "",
            )
            in_trade = True

    if in_trade and ct is not None:
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
        trades.append({
            "symbol": symbol, "direction": ct.direction,
            "entry_price": ct.entry_price, "exit_price": ct.exit_price,
            "exit_reason": ct.exit_reason, "pnl_pct": ct.pnl_pct,
            "net_pnl_pct": ct.net_pnl_pct, "rr": ct.rr,
            "sl_source": ct.sl_source, "regime": ct.regime,
            "score": ct.signal_score,
            "entry_timestamp": ct.entry_timestamp,
            "exit_timestamp": ct.exit_timestamp,
        })

    config.scoring.min_score_for_signal = orig_min_score
    config.trading.compression_enabled = orig_compression
    return trades


# ══════════════════════════════════════════════════════════════════════════
# Analysis helpers
# ══════════════════════════════════════════════════════════════════════════

def compute_group_stats(trades: list[dict]) -> dict:
    if not trades:
        return {"trades": 0, "wr": 0.0, "avg_pnl": 0.0, "pf": 0.0, "expectancy": 0.0}
    n = len(trades)
    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    wr = len(wins) / n * 100
    avg_pnl = sum(t["pnl_pct"] for t in trades) / n
    gross_profit = sum(t["pnl_pct"] for t in wins) if wins else 0.0
    gross_loss = abs(sum(t["pnl_pct"] for t in losses)) if losses else 1.0
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    expectancy = (len(wins) / n) * avg_win - (len(losses) / n) * avg_loss
    return {
        "trades": n, "wr": round(wr, 1), "avg_pnl": round(avg_pnl, 4),
        "pf": round(pf, 2), "expectancy": round(expectancy, 4),
    }

def compute_drawdown(trades: list[dict]) -> float:
    if not trades:
        return 0.0
    cum = np.cumsum([t["pnl_pct"] for t in trades])
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    return round(float(np.max(dd)), 4) if len(dd) > 0 else 0.0

def md_row(cols: list) -> str:
    return "| " + " | ".join(str(c) for c in cols) + " |"

def md_sep(n: int) -> str:
    return "| " + " | ".join(["---"] * n) + " |"


# ══════════════════════════════════════════════════════════════════════════
# Report generators (same as edge_discovery.py)
# ══════════════════════════════════════════════════════════════════════════

def stage1_score_regime(trades):
    scores = sorted(set(t["score"] for t in trades))
    regimes = sorted(set(t["regime"] for t in trades))
    lines = ["# Score x Regime Matrix\n", f"Total trades: {len(trades)}\n",
             md_row(["Score", "Regime", "Trades", "WR", "AvgPnL", "PF", "Expectancy"]), md_sep(7)]
    for score in scores:
        for regime in regimes:
            group = [t for t in trades if t["score"] == score and t["regime"] == regime]
            if not group: continue
            s = compute_group_stats(group)
            lines.append(md_row([score, regime, s["trades"], f"{s['wr']}%", f"{s['avg_pnl']:+.4f}%", s["pf"], f"{s['expectancy']:+.4f}"]))
        lines.append(md_row(["---"]*7))
    lines += ["\n## Summary by Score\n", md_row(["Score", "Trades", "WR", "AvgPnL", "PF", "Expectancy"]), md_sep(6)]
    for score in scores:
        group = [t for t in trades if t["score"] == score]
        if not group: continue
        s = compute_group_stats(group)
        lines.append(md_row([score, s["trades"], f"{s['wr']}%", f"{s['avg_pnl']:+.4f}%", s["pf"], f"{s['expectancy']:+.4f}"]))
    lines += ["\n## Summary by Regime\n", md_row(["Regime", "Trades", "WR", "AvgPnL", "PF", "Expectancy"]), md_sep(6)]
    for regime in regimes:
        group = [t for t in trades if t["regime"] == regime]
        if not group: continue
        s = compute_group_stats(group)
        lines.append(md_row([regime, s["trades"], f"{s['wr']}%", f"{s['avg_pnl']:+.4f}%", s["pf"], f"{s['expectancy']:+.4f}"]))
    return "\n".join(lines)


def stage2_score_sl(trades):
    scores = sorted(set(t["score"] for t in trades))
    sl_sources = sorted(set(t["sl_source"] for t in trades))
    lines = ["# Score x SL Source Matrix\n", md_row(["Score", "SL Source", "Trades", "WR", "AvgPnL", "PF", "Expectancy"]), md_sep(7)]
    for score in scores:
        for sl in sl_sources:
            group = [t for t in trades if t["score"] == score and t["sl_source"] == sl]
            if not group: continue
            s = compute_group_stats(group)
            lines.append(md_row([score, sl, s["trades"], f"{s['wr']}%", f"{s['avg_pnl']:+.4f}%", s["pf"], f"{s['expectancy']:+.4f}"]))
        lines.append(md_row(["---"]*7))
    lines += ["\n## Summary by SL Source\n", md_row(["SL Source", "Trades", "WR", "AvgPnL", "PF", "Expectancy"]), md_sep(6)]
    for sl in sl_sources:
        group = [t for t in trades if t["sl_source"] == sl]
        if not group: continue
        s = compute_group_stats(group)
        lines.append(md_row([sl, s["trades"], f"{s['wr']}%", f"{s['avg_pnl']:+.4f}%", s["pf"], f"{s['expectancy']:+.4f}"]))
    return "\n".join(lines)


def stage3_regime_sl(trades):
    regimes = sorted(set(t["regime"] for t in trades))
    sl_sources = sorted(set(t["sl_source"] for t in trades))
    lines = ["# Regime x SL Source Matrix\n", md_row(["Regime", "SL Source", "Trades", "WR", "AvgPnL", "PF", "Expectancy"]), md_sep(7)]
    for regime in regimes:
        for sl in sl_sources:
            group = [t for t in trades if t["regime"] == regime and t["sl_source"] == sl]
            if not group: continue
            s = compute_group_stats(group)
            lines.append(md_row([regime, sl, s["trades"], f"{s['wr']}%", f"{s['avg_pnl']:+.4f}%", s["pf"], f"{s['expectancy']:+.4f}"]))
        lines.append(md_row(["---"]*7))
    return "\n".join(lines)


def stage4_min_score_sensitivity(t2, t3, t4, t5):
    configs = [("min_score=2 (default)", t2), ("min_score=3", t3), ("min_score=4", t4), ("min_score=5", t5)]
    lines = ["# MIN_SCORE Sensitivity Analysis\n", "All runs use `full_new` preset. Only `min_score` changes.\n",
             md_row(["Config", "Trades", "WR", "AvgPnL", "PF", "Expectancy", "MaxDD"]), md_sep(7)]
    for label, trades in configs:
        if not trades:
            lines.append(md_row([label, 0, "—", "—", "—", "—", "—"])); continue
        s = compute_group_stats(trades); dd = compute_drawdown(trades)
        lines.append(md_row([label, s["trades"], f"{s['wr']}%", f"{s['avg_pnl']:+.4f}%", s["pf"], f"{s['expectancy']:+.4f}%", f"{dd:.2f}%"]))
    base_s = compute_group_stats(t2) if t2 else {"trades": 0, "wr": 0, "avg_pnl": 0, "pf": 0, "expectancy": 0}
    lines += ["\n## Delta vs min_score=2\n", md_row(["Config", "dTrades", "dWR", "dAvgPnL", "dPF", "dExpectancy"]), md_sep(6)]
    for label, trades in configs[1:]:
        if not trades: continue
        s = compute_group_stats(trades)
        lines.append(md_row([label, f"{s['trades']-base_s['trades']:+d}", f"{s['wr']-base_s['wr']:+.1f}%", f"{s['avg_pnl']-base_s['avg_pnl']:+.4f}%", f"{s['pf']-base_s['pf']:+.2f}", f"{s['expectancy']-base_s['expectancy']:+.4f}"]))
    return "\n".join(lines)


def stage5_compression(trades_on, trades_off):
    lines = ["# Compression Impact Analysis\n", "A: `allow_compression = true` (default)\n", "B: `allow_compression = false`\n"]
    configs = [("A: compression=ON", trades_on), ("B: compression=OFF", trades_off)]
    lines += [md_row(["Config", "Trades", "WR", "AvgPnL", "PF", "Expectancy", "MaxDD"]), md_sep(7)]
    for label, trades in configs:
        if not trades:
            lines.append(md_row([label, 0, "—", "—", "—", "—", "—"])); continue
        s = compute_group_stats(trades); dd = compute_drawdown(trades)
        lines.append(md_row([label, s["trades"], f"{s['wr']}%", f"{s['avg_pnl']:+.4f}%", s["pf"], f"{s['expectancy']:+.4f}%", f"{dd:.2f}%"]))
    if trades_on and trades_off:
        s_on = compute_group_stats(trades_on); s_off = compute_group_stats(trades_off)
        dd_on = compute_drawdown(trades_on); dd_off = compute_drawdown(trades_off)
        lines += ["\n## Delta (OFF vs ON)\n", md_row(["Metric", "ON", "OFF", "Delta"]), md_sep(4)]
        lines.append(md_row(["Trades", s_on["trades"], s_off["trades"], f"{s_off['trades']-s_on['trades']:+d}"]))
        lines.append(md_row(["WR", f"{s_on['wr']}%", f"{s_off['wr']}%", f"{s_off['wr']-s_on['wr']:+.1f}%"]))
        lines.append(md_row(["PF", s_on["pf"], s_off["pf"], f"{s_off['pf']-s_on['pf']:+.2f}"]))
        lines.append(md_row(["Expectancy", f"{s_on['expectancy']:+.4f}", f"{s_off['expectancy']:+.4f}", f"{s_off['expectancy']-s_on['expectancy']:+.4f}"]))
        lines.append(md_row(["MaxDD", f"{dd_on:.2f}%", f"{dd_off:.2f}%", f"{dd_off-dd_on:+.2f}%"]))
    comp_trades = [t for t in trades_on if t["regime"] == "compression"]
    if comp_trades:
        s = compute_group_stats(comp_trades); dd = compute_drawdown(comp_trades)
        lines += ["\n## Compression Regime Trades (from ON)\n", md_row(["Metric", "Value"]), md_sep(2)]
        lines += [md_row(["Trades", s["trades"]]), md_row(["WR", f"{s['wr']}%"]), md_row(["AvgPnL", f"{s['avg_pnl']:+.4f}%"]),
                  md_row(["PF", s["pf"]]), md_row(["Expectancy", f"{s['expectancy']:+.4f}"]), md_row(["MaxDD", f"{dd:.2f}%"])]
    return "\n".join(lines)


def stage6_score5(trades):
    s5 = [t for t in trades if t["score"] == 5]
    lines = ["# Score=5 Deep Dive\n", f"Total Score=5 trades: {len(s5)}\n"]
    lines += ["## By Regime\n", md_row(["Regime", "Trades", "WR", "AvgPnL", "PF", "Expectancy"]), md_sep(6)]
    for regime in sorted(set(t["regime"] for t in s5)):
        g = [t for t in s5 if t["regime"] == regime]; s = compute_group_stats(g)
        lines.append(md_row([regime, s["trades"], f"{s['wr']}%", f"{s['avg_pnl']:+.4f}%", s["pf"], f"{s['expectancy']:+.4f}"]))
    lines += ["\n## By SL Source\n", md_row(["SL Source", "Trades", "WR", "AvgPnL", "PF", "Expectancy"]), md_sep(6)]
    for sl in sorted(set(t["sl_source"] for t in s5)):
        g = [t for t in s5 if t["sl_source"] == sl]; s = compute_group_stats(g)
        lines.append(md_row([sl, s["trades"], f"{s['wr']}%", f"{s['avg_pnl']:+.4f}%", s["pf"], f"{s['expectancy']:+.4f}"]))
    lines += ["\n## By Regime x SL Source\n", md_row(["Regime", "SL", "Trades", "WR", "AvgPnL", "PF", "Expectancy"]), md_sep(7)]
    for regime in sorted(set(t["regime"] for t in s5)):
        for sl in sorted(set(t["sl_source"] for t in s5)):
            g = [t for t in s5 if t["regime"] == regime and t["sl_source"] == sl]
            if not g: continue; s = compute_group_stats(g)
            lines.append(md_row([regime, sl, s["trades"], f"{s['wr']}%", f"{s['avg_pnl']:+.4f}%", s["pf"], f"{s['expectancy']:+.4f}"]))
    lines += ["\n## By Direction\n", md_row(["Direction", "Trades", "WR", "AvgPnL", "PF"]), md_sep(5)]
    for d in ["BUY", "SELL"]:
        g = [t for t in s5 if t["direction"] == d]
        if not g: continue; s = compute_group_stats(g)
        lines.append(md_row([d, s["trades"], f"{s['wr']}%", f"{s['avg_pnl']:+.4f}%", s["pf"]]))
    lines += ["\n## By Exit Reason\n", md_row(["Exit", "Count", "WR"]), md_sep(3)]
    for ex in ["sl", "tp", "eob"]:
        g = [t for t in s5 if t["exit_reason"] == ex]
        if not g: continue
        wr = len([t for t in g if t["pnl_pct"] > 0]) / len(g) * 100
        lines.append(md_row([ex, len(g), f"{wr:.1f}%"]))
    return "\n".join(lines)


def stage7_score4(trades):
    s4 = [t for t in trades if t["score"] == 4]
    s5 = [t for t in trades if t["score"] == 5]
    lines = ["# Score=4 Autopsy\n", f"Total Score=4 trades: {len(s4)}\n"]
    lines += ["## By Regime\n", md_row(["Regime", "Trades", "WR", "AvgPnL", "PF", "Expectancy"]), md_sep(6)]
    for regime in sorted(set(t["regime"] for t in s4)):
        g = [t for t in s4 if t["regime"] == regime]; s = compute_group_stats(g)
        lines.append(md_row([regime, s["trades"], f"{s['wr']}%", f"{s['avg_pnl']:+.4f}%", s["pf"], f"{s['expectancy']:+.4f}"]))
    lines += ["\n## By SL Source\n", md_row(["SL Source", "Trades", "WR", "AvgPnL", "PF", "Expectancy"]), md_sep(6)]
    for sl in sorted(set(t["sl_source"] for t in s4)):
        g = [t for t in s4 if t["sl_source"] == sl]; s = compute_group_stats(g)
        lines.append(md_row([sl, s["trades"], f"{s['wr']}%", f"{s['avg_pnl']:+.4f}%", s["pf"], f"{s['expectancy']:+.4f}"]))
    lines += ["\n## By Regime x SL Source\n", md_row(["Regime", "SL", "Trades", "WR", "AvgPnL", "PF", "Expectancy"]), md_sep(7)]
    for regime in sorted(set(t["regime"] for t in s4)):
        for sl in sorted(set(t["sl_source"] for t in s4)):
            g = [t for t in s4 if t["regime"] == regime and t["sl_source"] == sl]
            if not g: continue; s = compute_group_stats(g)
            lines.append(md_row([regime, sl, s["trades"], f"{s['wr']}%", f"{s['avg_pnl']:+.4f}%", s["pf"], f"{s['expectancy']:+.4f}"]))
    lines += ["\n## By Exit Reason\n", md_row(["Exit", "Count", "WR"]), md_sep(3)]
    for ex in ["sl", "tp", "eob"]:
        g = [t for t in s4 if t["exit_reason"] == ex]
        if not g: continue
        wr = len([t for t in g if t["pnl_pct"] > 0]) / len(g) * 100
        lines.append(md_row([ex, len(g), f"{wr:.1f}%"]))
    s4s = compute_group_stats(s4) if s4 else {"trades": 0, "wr": 0, "pf": 0, "expectancy": 0}
    s5s = compute_group_stats(s5) if s5 else {"trades": 0, "wr": 0, "pf": 0, "expectancy": 0}
    lines += ["\n## Score=4 vs Score=5\n", md_row(["Metric", "S4", "S5", "Delta"]), md_sep(4)]
    lines.append(md_row(["Trades", s4s["trades"], s5s["trades"], f"{s5s['trades']-s4s['trades']:+d}"]))
    lines.append(md_row(["WR", f"{s4s['wr']}%", f"{s5s['wr']}%", f"{s5s['wr']-s4s['wr']:+.1f}%"]))
    lines.append(md_row(["PF", s4s["pf"], s5s["pf"], f"{s5s['pf']-s4s['pf']:+.2f}"]))
    lines.append(md_row(["Expectancy", f"{s4s['expectancy']:+.4f}", f"{s5s['expectancy']:+.4f}", f"{s5s['expectancy']-s4s['expectancy']:+.4f}"]))
    lines += ["\n## Per-Regime Edge Loss\n", md_row(["Regime", "S4 WR", "S5 WR", "S4 PF", "S5 PF", "dWR", "dPF"]), md_sep(7)]
    all_regimes = sorted(set(t["regime"] for t in s4 + s5))
    for regime in all_regimes:
        g4 = [t for t in s4 if t["regime"] == regime]
        g5 = [t for t in s5 if t["regime"] == regime]
        s4r = compute_group_stats(g4) if g4 else {"trades": 0, "wr": 0, "pf": 0}
        s5r = compute_group_stats(g5) if g5 else {"trades": 0, "wr": 0, "pf": 0}
        if g4 or g5:
            lines.append(md_row([regime, f"{s4r['wr']}%" if g4 else "—", f"{s5r['wr']}%" if g5 else "—",
                s4r["pf"] if g4 else "—", s5r["pf"] if g5 else "—",
                f"{s5r['wr']-s4r['wr']:+.1f}%" if (g4 and g5) else "—", f"{s5r['pf']-s4r['pf']:+.2f}" if (g4 and g5) else "—"]))
    return "\n".join(lines)


def stage8_top_combinations(trades):
    combos = defaultdict(list)
    for t in trades:
        combos[(t["score"], t["regime"], t["sl_source"])].append(t)
    rows = []
    for (score, regime, sl), group in combos.items():
        s = compute_group_stats(group)
        rows.append({"score": score, "regime": regime, "sl_source": sl,
                      "trades": s["trades"], "wr": s["wr"], "avg_pnl": s["avg_pnl"],
                      "pf": s["pf"], "expectancy": s["expectancy"]})
    rows.sort(key=lambda r: r["expectancy"], reverse=True)
    lines = ["# Top Edge Combinations\n", f"Total unique combinations: {len(rows)}\n",
             "Sorted by Expectancy.\n", md_row(["#", "Score", "Regime", "SL", "Trades", "WR", "AvgPnL", "PF", "Expectancy"]), md_sep(9)]
    for i, r in enumerate(rows[:30], 1):
        lines.append(md_row([i, r["score"], r["regime"], r["sl_source"], r["trades"], f"{r['wr']}%", f"{r['avg_pnl']:+.4f}%", r["pf"], f"{r['expectancy']:+.4f}"]))
    lines += ["\n## Filtered: min 5 trades\n", md_row(["#", "Score", "Regime", "SL", "Trades", "WR", "AvgPnL", "PF", "Expectancy"]), md_sep(9)]
    filtered = [r for r in rows if r["trades"] >= 5]
    for i, r in enumerate(filtered[:30], 1):
        lines.append(md_row([i, r["score"], r["regime"], r["sl_source"], r["trades"], f"{r['wr']}%", f"{r['avg_pnl']:+.4f}%", r["pf"], f"{r['expectancy']:+.4f}"]))
    return "\n".join(lines)


def final_report(trades, t3, t4, t5, t_comp_off):
    s_all = compute_group_stats(trades) if trades else {}
    s3 = compute_group_stats(t3) if t3 else {}
    s4 = compute_group_stats(t4) if t4 else {}
    s5 = compute_group_stats(t5) if t5 else {}
    s_off = compute_group_stats(t_comp_off) if t_comp_off else {}

    score_stats = {}
    for sc in sorted(set(t["score"] for t in trades)):
        score_stats[sc] = compute_group_stats([t for t in trades if t["score"] == sc])
    best_score = max(score_stats.items(), key=lambda x: x[1].get("expectancy", 0)) if score_stats else (0, {})

    regime_stats = {}
    for rg in sorted(set(t["regime"] for t in trades)):
        regime_stats[rg] = compute_group_stats([t for t in trades if t["regime"] == rg])
    best_regime = max(regime_stats.items(), key=lambda x: x[1].get("expectancy", 0)) if regime_stats else ("", {})

    combos = defaultdict(list)
    for t in trades: combos[(t["score"], t["regime"], t["sl_source"])].append(t)
    combo_stats = {k: compute_group_stats(v) for k, v in combos.items()}
    best_combo = max(combo_stats.items(), key=lambda x: x[1].get("expectancy", 0)) if combo_stats else ((0, "", ""), {})

    sl_stats = {}
    for sl in sorted(set(t["sl_source"] for t in trades)):
        sl_stats[sl] = compute_group_stats([t for t in trades if t["sl_source"] == sl])

    comp_trades = [t for t in trades if t["regime"] == "compression"]
    s_comp = compute_group_stats(comp_trades) if comp_trades else {"trades": 0, "wr": 0}

    dd_on = compute_drawdown(trades)
    dd_off = compute_drawdown(t_comp_off)

    score_range = max((s.get("expectancy", 0) for s in score_stats.values()), default=0) - min((s.get("expectancy", 0) for s in score_stats.values()), default=0)
    regime_range = max((s.get("expectancy", 0) for s in regime_stats.values()), default=0) - min((s.get("expectancy", 0) for s in regime_stats.values()), default=0)
    sl_range = max((s.get("expectancy", 0) for s in sl_stats.values()), default=0) - min((s.get("expectancy", 0) for s in sl_stats.values()), default=0)

    L = []
    L.append("# EDGE DISCOVERY REPORT\n")
    L.append("## Executive Summary\n")
    L.append(f"- **Total trades (full_new, min_score=2):** {s_all.get('trades', 0)}")
    L.append(f"- **Overall WR:** {s_all.get('wr', 0)}%")
    L.append(f"- **Overall PF:** {s_all.get('pf', 0)}")
    L.append(f"- **Overall Expectancy:** {s_all.get('expectancy', 0):+.4f}%\n")

    L.append("## 1. Where is the main edge?\n")
    L.append(f"The primary edge is in **Score={best_score[0]}** trades:")
    L.append(f"- {best_score[1].get('trades', 0)} trades, WR {best_score[1].get('wr', 0)}%, PF {best_score[1].get('pf', 0)}, Expectancy {best_score[1].get('expectancy', 0):+.4f}%\n")
    L.append(f"Best regime: **{best_regime[0]}** — {best_regime[1].get('trades', 0)} trades, WR {best_regime[1].get('wr', 0)}%, PF {best_regime[1].get('pf', 0)}, Expectancy {best_regime[1].get('expectancy', 0):+.4f}%\n")
    L.append(f"Best combination: **Score={best_combo[0][0]}, Regime={best_combo[0][1]}, SL={best_combo[0][2]}**")
    L.append(f"- {best_combo[1].get('trades', 0)} trades, WR {best_combo[1].get('wr', 0)}%, PF {best_combo[1].get('pf', 0)}, Expectancy {best_combo[1].get('expectancy', 0):+.4f}%\n")

    L.append("## 2. What is the optimal min_score?\n")
    L += [md_row(["Config", "Trades", "WR", "PF", "Expectancy"]), md_sep(5)]
    L.append(md_row(["min_score=2", s_all.get("trades", 0), f"{s_all.get('wr', 0)}%", s_all.get("pf", 0), f"{s_all.get('expectancy', 0):+.4f}"]))
    L.append(md_row(["min_score=3", s3.get("trades", 0), f"{s3.get('wr', 0)}%", s3.get("pf", 0), f"{s3.get('expectancy', 0):+.4f}"]))
    L.append(md_row(["min_score=4", s4.get("trades", 0), f"{s4.get('wr', 0)}%", s4.get("pf", 0), f"{s4.get('expectancy', 0):+.4f}"]))
    L.append(md_row(["min_score=5", s5.get("trades", 0), f"{s5.get('wr', 0)}%", s5.get("pf", 0), f"{s5.get('expectancy', 0):+.4f}"]))
    L.append("")

    L.append("## 3. Should min_score be raised to 5?\n")
    L.append(f"Score=5: {s5.get('trades', 0)} trades, WR {s5.get('wr', 0)}%, PF {s5.get('pf', 0)}, Expectancy {s5.get('expectancy', 0):+.4f}%")
    L.append(f"Score=4: {s4.get('trades', 0)} trades, WR {s4.get('wr', 0)}%, PF {s4.get('pf', 0)}, Expectancy {s4.get('expectancy', 0):+.4f}%")
    L.append(f"Delta: {s5.get('trades', 0) - s4.get('trades', 0):+d} trades, WR {s5.get('wr', 0) - s4.get('wr', 0):+.1f}%, PF {s5.get('pf', 0) - s4.get('pf', 0):+.2f}\n")

    L.append("## 4. Should compression be disabled?\n")
    L += [md_row(["Config", "Trades", "WR", "PF", "Expectancy", "MaxDD"]), md_sep(6)]
    L.append(md_row(["compression=ON", s_all.get("trades", 0), f"{s_all.get('wr', 0)}%", s_all.get("pf", 0), f"{s_all.get('expectancy', 0):+.4f}%", f"{dd_on:.2f}%"]))
    L.append(md_row(["compression=OFF", s_off.get("trades", 0), f"{s_off.get('wr', 0)}%", s_off.get("pf", 0), f"{s_off.get('expectancy', 0):+.4f}%", f"{dd_off:.2f}%"]))
    L.append(f"\nCompression regime trades: {s_comp.get('trades', 0)} (WR {s_comp.get('wr', 0)}%)\n")

    L.append("## 5. Best Score x Regime combination\n")
    sc_rg = defaultdict(list)
    for t in trades: sc_rg[(t["score"], t["regime"])].append(t)
    sc_rg_s = sorted([(k, compute_group_stats(v)) for k, v in sc_rg.items()], key=lambda x: x[1].get("expectancy", 0), reverse=True)
    L += [md_row(["Regime", "Score", "Trades", "WR", "PF", "Expectancy"]), md_sep(6)]
    for (sc, rg), st in sc_rg_s[:5]:
        L.append(md_row([rg, sc, st["trades"], f"{st['wr']}%", st["pf"], f"{st['expectancy']:+.4f}"]))

    L += ["", "## 6. What influences the result most?\n", "### By Score\n",
          md_row(["Score", "Trades", "WR", "PF", "Expectancy"]), md_sep(5)]
    for sc in sorted(score_stats):
        st = score_stats[sc]; L.append(md_row([sc, st["trades"], f"{st['wr']}%", st["pf"], f"{st['expectancy']:+.4f}"]))
    L += ["", "### By Regime\n", md_row(["Regime", "Trades", "WR", "PF", "Expectancy"]), md_sep(5)]
    for rg in sorted(regime_stats):
        st = regime_stats[rg]; L.append(md_row([rg, st["trades"], f"{st['wr']}%", st["pf"], f"{st['expectancy']:+.4f}"]))
    L += ["", "### By SL Source\n", md_row(["SL Source", "Trades", "WR", "PF", "Expectancy"]), md_sep(5)]
    for sl in sorted(sl_stats):
        st = sl_stats[sl]; L.append(md_row([sl, st["trades"], f"{st['wr']}%", st["pf"], f"{st['expectancy']:+.4f}"]))
    L += ["", "### Impact ranking (expectancy spread)\n",
          f"1. **Regime:** spread = {regime_range:+.4f}%",
          f"2. **Score:** spread = {score_range:+.4f}%",
          f"3. **SL Source:** spread = {sl_range:+.4f}%\n",
          "## 7. What should NOT be changed\n",
          "- Keep the `full_new` preset pipeline flags as-is",
          "- Keep the scoring system (7 factors, count-based)",
          "- Keep the cooldown at 45 min",
          "- Keep the ATR-based regime detection thresholds",
          "- Do NOT add new indicators or filters at this stage"]
    return "\n".join(L)


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════

async def main():
    from backtest.cache_ohlcv import load_cached

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    bt_config = BacktestConfig(**FULL_NEW_FLAGS)
    indicator_engine = IndicatorEngine()

    print("=" * 70, flush=True)
    print("  EDGE DISCOVERY ANALYSIS", flush=True)
    print("=" * 70, flush=True)

    # Phase 1: Pre-compute snapshots
    print("\n  Phase 1: Pre-computing snapshots...", flush=True)
    all_snapshots = {}
    t_total = time.time()
    for sym_idx, symbol in enumerate(SYMBOLS, 1):
        cached_1h = load_cached(symbol, TIMEFRAME, CANDLES)
        cached_15m = load_cached(symbol, CONFIRM_TF, CONFIRM_CANDLES)
        if cached_1h is None:
            print(f"    [{sym_idx:2d}/{len(SYMBOLS)}] {symbol:12s} — NO CACHE", flush=True)
            continue
        df = cached_1h.copy()
        confirm_df = cached_15m.copy() if cached_15m is not None else None
        t0 = time.time()
        snaps = precompute_snapshots(symbol, df, confirm_df, indicator_engine)
        elapsed = time.time() - t0
        all_snapshots[symbol] = (df, snaps)
        print(f"    [{sym_idx:2d}/{len(SYMBOLS)}] {symbol:12s} — {len(snaps):4d} snaps ({elapsed:.1f}s)", flush=True)
    print(f"\n  Snapshots done: {time.time()-t_total:.1f}s, {len(all_snapshots)} symbols", flush=True)

    # Phase 2: Evaluate configs (fast — just walks snapshots)
    print("\n  Phase 2: Evaluating configs...", flush=True)
    configs = [
        ("full_new", 2, True),
        ("min_score_3", 3, True),
        ("min_score_4", 4, True),
        ("min_score_5", 5, True),
        ("comp_off", 2, False),
    ]
    all_results = {}
    for cfg_label, ms, comp in configs:
        t0 = time.time()
        all_trades = []
        for sym, (df, snaps) in all_snapshots.items():
            all_trades.extend(evaluate_config(sym, df, snaps, bt_config, ms, comp))
        elapsed = time.time() - t0
        all_results[cfg_label] = all_trades
        print(f"    {cfg_label:15s} — {len(all_trades):4d} trades ({elapsed:.1f}s)", flush=True)

    t_default = all_results["full_new"]
    t_m3 = all_results["min_score_3"]
    t_m4 = all_results["min_score_4"]
    t_m5 = all_results["min_score_5"]
    t_comp_off = all_results["comp_off"]

    # Save raw trades
    raw_path = REPORTS_DIR / "all_trades_full_new.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(t_default, f, ensure_ascii=False, indent=2)
    print(f"\n  Saved raw trades -> {raw_path}", flush=True)

    # Phase 3: Generate reports
    print("\n  Phase 3: Generating reports...", flush=True)
    (REPORTS_DIR / "score_regime_matrix.md").write_text(stage1_score_regime(t_default), encoding="utf-8")
    print("  [1/8] score_regime_matrix.md", flush=True)
    (REPORTS_DIR / "score_sl_matrix.md").write_text(stage2_score_sl(t_default), encoding="utf-8")
    print("  [2/8] score_sl_matrix.md", flush=True)
    (REPORTS_DIR / "regime_sl_matrix.md").write_text(stage3_regime_sl(t_default), encoding="utf-8")
    print("  [3/8] regime_sl_matrix.md", flush=True)
    (REPORTS_DIR / "min_score_sensitivity.md").write_text(stage4_min_score_sensitivity(t_default, t_m3, t_m4, t_m5), encoding="utf-8")
    print("  [4/8] min_score_sensitivity.md", flush=True)
    (REPORTS_DIR / "compression_impact.md").write_text(stage5_compression(t_default, t_comp_off), encoding="utf-8")
    print("  [5/8] compression_impact.md", flush=True)
    (REPORTS_DIR / "score5_deep_dive.md").write_text(stage6_score5(t_default), encoding="utf-8")
    print("  [6/8] score5_deep_dive.md", flush=True)
    (REPORTS_DIR / "score4_autopsy.md").write_text(stage7_score4(t_default), encoding="utf-8")
    print("  [7/8] score4_autopsy.md", flush=True)
    (REPORTS_DIR / "top_edge_combinations.md").write_text(stage8_top_combinations(t_default), encoding="utf-8")
    print("  [8/8] top_edge_combinations.md", flush=True)
    (REPORTS_DIR / "EDGE_DISCOVERY_REPORT.md").write_text(final_report(t_default, t_m3, t_m4, t_m5, t_comp_off), encoding="utf-8")
    print("  [FINAL] EDGE_DISCOVERY_REPORT.md", flush=True)

    print(f"\n{'='*70}", flush=True)
    print(f"  ALL REPORTS SAVED TO: {REPORTS_DIR}", flush=True)
    print(f"{'='*70}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
