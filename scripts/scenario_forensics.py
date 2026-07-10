"""
scripts/scenario_forensics.py — Scenario Forensics Toolkit

Identifies where statistical edge is destroyed by analyzing completed trades.

Answers:
  1. Are entries bad or exits bad? (MAE/MFE analysis)
  2. Which market regimes destroy expectancy?
  3. Which scenario components actually improve expectancy?
  4. Which gates improve expectancy vs merely reducing trade count?
  5. Is directional bias responsible for losses?
  6. What is the actual half-life of market scenarios?

Usage:
    python scripts/scenario_forensics.py [--db data/signals.db] [--days 90]
    python scripts/scenario_forensics.py --reports-only
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional


# ══════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "signals.db"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"

TF_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720, "1d": 1440,
}

# Regime numeric → human-readable mapping
REGIME_MAP = {
    "1": "trend", "1.0": "trend",
    "0.5": "expansion",
    "-0.5": "range",
    "-1": "compression", "-1.0": "compression",
    "0": "unknown", "0.0": "unknown",
}

ADX_BINS = [
    ("adx_<18", lambda a: a is not None and a < 18),
    ("adx_18-25", lambda a: a is not None and 18 <= a < 25),
    ("adx_25-30", lambda a: a is not None and 25 <= a < 30),
    ("adx_>=30", lambda a: a is not None and a >= 30),
]

BOS_AGE_BINS = [
    ("bos_age_<=3", lambda a: a is not None and a <= 3),
    ("bos_age_4-10", lambda a: a is not None and 4 <= a <= 10),
    ("bos_age_>10", lambda a: a is not None and a > 10),
]

OB_DISTANCE_BINS = [
    ("ob_dist_<1atr", lambda d: d is not None and d < 1.0),
    ("ob_dist_1-2atr", lambda d: d is not None and 1.0 <= d < 2.0),
    ("ob_dist_>2atr", lambda d: d is not None and d >= 2.0),
]

RR_BINS = [
    ("rr_<1.5", lambda r: r is not None and r < 1.5),
    ("rr_1.5-2", lambda r: r is not None and 1.5 <= r < 2.0),
    ("rr_2-3", lambda r: r is not None and 2.0 <= r < 3.0),
    ("rr_>=3", lambda r: r is not None and r >= 3.0),
]

SWEEP_RECLAIM_BINS = [
    ("sweep_reclaim_<=2", lambda s: s is not None and 0 < s <= 2),
    ("sweep_reclaim_>2", lambda s: s is not None and s > 2),
    ("no_sweep", lambda s: s is None or s == 0),
]


# ══════════════════════════════════════════════════════════════════
# Data classes
# ══════════════════════════════════════════════════════════════════

@dataclass
class TradeRecord:
    """Enriched trade record with all forensics fields."""
    # Trade metadata
    signal_id: int = 0
    symbol: str = ""
    timeframe: str = ""
    direction: str = ""           # BUY / SELL
    outcome: str = ""             # HIT_TP / HIT_SL / EXPIRED
    pnl_pct: float = 0.0
    pnl_r: float = 0.0
    hold_bars: int = 0
    hold_minutes: float = 0.0
    mfe_pct: float = 0.0
    mae_pct: float = 0.0
    mfe_r: float = 0.0
    mae_r: float = 0.0
    created_at: str = ""
    closed_at: str = ""

    # Hypothesis metadata
    hypothesis_name: str = ""
    scenario_type: str = ""
    scenario_score: float = 0.0
    scenario_probability: float = 0.0
    scenario_confidence: float = 0.0
    scenario_stability: float = 0.0
    decay_factor: float = 0.0
    ambiguity_gap: float = 0.0

    # Structure
    structure_trend: str = ""     # bullish / bearish / ranging
    bos_direction: str = ""       # bullish / bearish
    bos_age_bars: Optional[int] = None
    choch_present: bool = False
    structure_alignment: bool = False

    # Liquidity
    sweep_present: bool = False
    sweep_strength: float = 0.0
    sweep_reclaim_bars: Optional[int] = None
    ob_present: bool = False
    ob_distance_atr: Optional[float] = None
    ob_state: str = ""            # fresh / retesting / broken
    fvg_present: bool = False
    fvg_distance_atr: Optional[float] = None
    external_liquidity_distance_atr: Optional[float] = None

    # Market regime
    regime: str = ""
    adx: Optional[float] = None
    atr_pct: Optional[float] = None
    btc_correlation: Optional[float] = None
    mtf_alignment: Optional[float] = None

    # Execution
    entry_trigger_type: str = ""
    spread_pct: Optional[float] = None
    sl_distance_atr: Optional[float] = None
    tp_distance_atr: Optional[float] = None
    rr_ratio: Optional[float] = None


@dataclass
class FeatureStats:
    """Statistics for one feature bin."""
    name: str = ""
    sample_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    winrate: float = 0.0
    profit_factor: float = 0.0
    expectancy_r: float = 0.0
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0
    avg_pnl_pct: float = 0.0
    avg_hold_bars: float = 0.0
    avg_mfe_r: float = 0.0
    avg_mae_r: float = 0.0


@dataclass
class ClusterInfo:
    """Failure cluster description."""
    cluster_id: int = 0
    trade_count: int = 0
    features: dict = field(default_factory=dict)
    expectancy_r: float = 0.0
    avg_pnl_pct: float = 0.0
    winrate: float = 0.0
    dominant_regime: str = ""
    dominant_direction: str = ""


# ══════════════════════════════════════════════════════════════════
# R-multiple calculation
# ══════════════════════════════════════════════════════════════════

def compute_r_multiple(
    direction: str,
    entry_price: float,
    exit_price: float,
    sl: Optional[float],
) -> float:
    """Compute R-multiple from entry/exit/SL."""
    if not sl or not entry_price or entry_price == sl:
        return 0.0
    risk = abs(entry_price - sl)
    if risk < 1e-10:
        return 0.0
    reward = (exit_price - entry_price) if direction == "BUY" else (entry_price - exit_price)
    return reward / risk


def compute_r_from_pnl(
    direction: str,
    entry_price: float,
    pnl_pct: float,
    sl: Optional[float],
) -> float:
    """Compute R-multiple from pnl_pct and SL distance."""
    if not sl or not entry_price or entry_price == sl:
        return 0.0
    risk = abs(entry_price - sl)
    if risk < 1e-10:
        return 0.0
    price_change = pnl_pct / 100.0 * entry_price
    return price_change / risk


# ══════════════════════════════════════════════════════════════════
# Data loading
# ══════════════════════════════════════════════════════════════════

def _get_available_trace_columns(conn: sqlite3.Connection) -> set[str]:
    """Get column names that actually exist in decision_traces."""
    cursor = conn.execute("PRAGMA table_info(decision_traces)")
    return {row[1] for row in cursor.fetchall()}


def load_trades(db_path: str, days: int = 90) -> list[TradeRecord]:
    """Load all resolved trades with enriched data from all tables."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Join signals + outcomes + decision_traces
    # NOTE: hypothesis_snapshot and execution_snapshot columns may not exist
    # in older DBs. We query only columns that are guaranteed to exist.
    traces_cols = _get_available_trace_columns(conn)

    select_parts = [
        "s.id as signal_id", "s.symbol", "s.timeframe",
        "s.signal_type as direction", "s.close_price as entry_price",
        "s.sl", "s.tp", "s.created_at", "s.mfe_pct", "s.mae_pct",
        "s.entry_spread", "s.entry_atr", "s.confidence_v2_pct",
        "o.status as outcome", "o.pnl_pct", "o.closed_at", "o.risk_pct",
    ]

    # Add trace columns that actually exist
    trace_fields = [
        "adx", "rsi", "regime", "atr_pct", "rr_ratio",
        "has_bos", "has_sweep", "has_ob", "ob_distance_pct",
        "btc_trend_strength", "mtf_alignment_score",
        "sl_distance_pct", "tp_distance_pct", "sl_source",
        "signal_type as dt_direction", "supertrend_direction",
        "ema_short", "ema_long", "ema_spread_pct",
        "dmi_strength", "ema_strength", "confidence",
        "volume_ratio",
    ]
    for field in trace_fields:
        if field in traces_cols or field.split(" as ")[0] in traces_cols:
            select_parts.append(f"dt.{field}")

    # hypothesis_snapshot — may or may not exist
    if "hypothesis_snapshot" in traces_cols:
        select_parts.append("dt.hypothesis_snapshot")

    sql = f"""
        SELECT {', '.join(select_parts)}
        FROM signals s
        JOIN signal_outcomes o ON o.signal_id = s.id
        LEFT JOIN decision_traces dt ON dt.signal_id = s.id
        WHERE o.status IN ('HIT_TP', 'HIT_SL', 'EXPIRED')
          AND s.created_at > ?
        ORDER BY s.created_at
    """
    rows = conn.execute(sql, (cutoff,)).fetchall()
    conn.close()

    trades = []
    for row in rows:
        t = _row_to_trade(row)
        if t is not None:
            trades.append(t)

    return trades


def _row_to_trade(row: sqlite3.Row) -> Optional[TradeRecord]:
    """Convert a joined DB row to TradeRecord."""
    try:
        r = dict(row)
        entry = r["entry_price"] or 0.0
        sl = r["sl"]
        tp = r["tp"]
        direction = r["direction"] or "BUY"
        pnl_pct = r["pnl_pct"] or 0.0
        outcome = r["outcome"] or ""

        # R-multiple
        if outcome == "HIT_TP" and sl and entry:
            pnl_r = compute_r_multiple(direction, entry, tp or entry, sl)
        elif outcome == "HIT_SL" and sl and entry:
            pnl_r = compute_r_multiple(direction, entry, sl, sl)
        elif pnl_pct != 0 and sl and entry:
            pnl_r = compute_r_from_pnl(direction, entry, pnl_pct, sl)
        else:
            pnl_r = 0.0

        # Hold bars
        hold_bars = 0
        hold_minutes = 0.0
        created = r["created_at"] or ""
        closed = r["closed_at"] or ""
        if created and closed:
            try:
                ct = datetime.fromisoformat(created.replace("Z", "+00:00"))
                cl = datetime.fromisoformat(closed.replace("Z", "+00:00"))
                tf_min = TF_MINUTES.get(r["timeframe"] or "1h", 60)
                delta_min = (cl - ct).total_seconds() / 60.0
                hold_minutes = delta_min
                hold_bars = max(1, int(delta_min / tf_min))
            except Exception:
                pass

        # MFE/MAE in R
        mfe_pct = r["mfe_pct"] or 0.0
        mae_pct = r["mae_pct"] or 0.0
        risk_pct = r["sl_distance_pct"] or 0.0
        mfe_r = mfe_pct / risk_pct if risk_pct > 0 else 0.0
        mae_r = mae_pct / risk_pct if risk_pct > 0 else 0.0

        # Structure
        atr_pct = r["atr_pct"] or 0.0
        ob_dist_pct = r["ob_distance_pct"] or 0.0
        ob_distance_atr = ob_dist_pct / atr_pct if atr_pct > 0 else None

        # Derive structure_trend
        st_dir = r.get("supertrend_direction")
        ema_spread = r.get("ema_spread_pct") or 0.0
        if st_dir == 1 and ema_spread > 0:
            structure_trend = "bullish"
        elif st_dir == -1 and ema_spread < 0:
            structure_trend = "bearish"
        else:
            structure_trend = "ranging"

        # BOS direction
        bos_direction = "bullish" if direction == "BUY" else "bearish"

        # Structure alignment
        structure_alignment = (structure_trend == bos_direction)

        # Hypothesis snapshot (may not exist in older DBs)
        h_snap = {}
        h_raw = r.get("hypothesis_snapshot")
        if h_raw:
            try:
                h_snap = json.loads(h_raw)
            except Exception:
                pass

        scenario_type = h_snap.get("narrative_type", "")
        scenario_score = h_snap.get("quality", 0.0)
        scenario_confidence = h_snap.get("confidence", 0.0)
        scenario_probability = h_snap.get("confidence", 0.0)
        decay_factor = h_snap.get("decay_factor", 0.0)
        hypothesis_name = h_snap.get("hypothesis_id", "")

        # BOS age from hypothesis
        created_bar = h_snap.get("created_at_bar")
        current_bar = h_snap.get("current_bar")
        bos_age_bars = None
        if created_bar is not None and current_bar is not None:
            bos_age_bars = current_bar - created_bar

        # CHoCH
        choch_present = "choch" in scenario_type.lower() if scenario_type else False

        # Liquidity features
        sweep_present = bool(r["has_sweep"])
        ob_present = bool(r["has_ob"])
        fvg_present = "fvg" in scenario_type.lower() if scenario_type else False

        # OB state
        ob_state = "unknown"
        if ob_present:
            if ob_distance_atr is not None:
                if ob_distance_atr < 0.5:
                    ob_state = "fresh"
                elif ob_distance_atr < 1.5:
                    ob_state = "retesting"
                else:
                    ob_state = "broken"

        # Scenario stability
        scenario_stability = decay_factor

        # Spread
        spread = r["entry_spread"] or 0.0
        entry_atr = r["entry_atr"] or 0.0
        spread_pct = (spread / entry * 100) if entry > 0 and spread > 0 else None

        # SL/TP distance in ATR
        sl_dist_pct = r["sl_distance_pct"] or 0.0
        tp_dist_pct = r["tp_distance_pct"] or 0.0
        sl_distance_atr = sl_dist_pct / atr_pct if atr_pct > 0 else None
        tp_distance_atr = tp_dist_pct / atr_pct if atr_pct > 0 else None

        return TradeRecord(
            signal_id=r["signal_id"] or 0,
            symbol=r["symbol"] or "",
            timeframe=r["timeframe"] or "",
            direction=direction,
            outcome=outcome,
            pnl_pct=pnl_pct,
            pnl_r=pnl_r,
            hold_bars=hold_bars,
            hold_minutes=hold_minutes,
            mfe_pct=mfe_pct,
            mae_pct=mae_pct,
            mfe_r=mfe_r,
            mae_r=mae_r,
            created_at=created,
            closed_at=closed,
            hypothesis_name=hypothesis_name,
            scenario_type=scenario_type,
            scenario_score=scenario_score,
            scenario_probability=scenario_probability,
            scenario_confidence=scenario_confidence,
            scenario_stability=scenario_stability,
            decay_factor=decay_factor,
            ambiguity_gap=0.0,
            structure_trend=structure_trend,
            bos_direction=bos_direction,
            bos_age_bars=bos_age_bars,
            choch_present=choch_present,
            structure_alignment=structure_alignment,
            sweep_present=sweep_present,
            sweep_strength=0.0,
            sweep_reclaim_bars=None,
            ob_present=ob_present,
            ob_distance_atr=ob_distance_atr,
            ob_state=ob_state,
            fvg_present=fvg_present,
            fvg_distance_atr=None,
            external_liquidity_distance_atr=None,
            regime=REGIME_MAP.get(r["regime"] or "", r["regime"] or ""),
            adx=r["adx"],
            atr_pct=atr_pct,
            btc_correlation=r["btc_trend_strength"],
            mtf_alignment=r["mtf_alignment_score"],
            entry_trigger_type=scenario_type,
            spread_pct=spread_pct,
            sl_distance_atr=sl_distance_atr,
            tp_distance_atr=tp_distance_atr,
            rr_ratio=r["rr_ratio"],
        )
    except Exception as e:
        return None


# ══════════════════════════════════════════════════════════════════
# Statistics engine
# ══════════════════════════════════════════════════════════════════

def compute_group_stats(trades: list[TradeRecord], label: str = "") -> FeatureStats:
    """Compute stats for a group of trades."""
    if not trades:
        return FeatureStats(name=label)

    closed = [t for t in trades if t.outcome in ("HIT_TP", "HIT_SL")]
    wins = [t for t in closed if t.outcome == "HIT_TP"]
    losses = [t for t in closed if t.outcome == "HIT_SL"]

    n = len(closed)
    n_win = len(wins)
    n_loss = len(losses)
    wr = n_win / n if n > 0 else 0.0

    # Profit factor
    gross_profit = sum(t.pnl_r for t in wins) if wins else 0.0
    gross_loss = abs(sum(t.pnl_r for t in losses)) if losses else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

    # Expectancy in R
    avg_win_r = gross_profit / n_win if n_win > 0 else 0.0
    avg_loss_r = -gross_loss / n_loss if n_loss > 0 else 0.0
    expectancy_r = (wr * avg_win_r) + ((1 - wr) * avg_loss_r) if n > 0 else 0.0

    avg_pnl = sum(t.pnl_pct for t in closed) / n if n > 0 else 0.0
    avg_hold = sum(t.hold_bars for t in closed) / n if n > 0 else 0.0
    avg_mfe = sum(t.mfe_r for t in closed) / n if n > 0 else 0.0
    avg_mae = sum(t.mae_r for t in closed) / n if n > 0 else 0.0

    return FeatureStats(
        name=label,
        sample_count=n,
        win_count=n_win,
        loss_count=n_loss,
        winrate=wr,
        profit_factor=pf if pf != float("inf") else 999.99,
        expectancy_r=expectancy_r,
        avg_win_r=avg_win_r,
        avg_loss_r=avg_loss_r,
        avg_pnl_pct=avg_pnl,
        avg_hold_bars=avg_hold,
        avg_mfe_r=avg_mfe,
        avg_mae_r=avg_mae,
    )


def compute_feature_binned_stats(
    trades: list[TradeRecord],
    bins: list[tuple[str, callable]],
    accessor: callable,
) -> list[FeatureStats]:
    """Compute stats for each bin of a feature."""
    results = []
    for bin_name, predicate in bins:
        subset = [t for t in trades if predicate(accessor(t))]
        stats = compute_group_stats(subset, bin_name)
        results.append(stats)
    return results


# ══════════════════════════════════════════════════════════════════
# Stage 1: MAE/MFE Analysis
# ══════════════════════════════════════════════════════════════════

def analyze_mae_mfe(trades: list[TradeRecord]) -> dict:
    """Determine whether entry logic or exit logic is broken.

    Key insight: if losers reach high MFE before hitting SL, the exit is bad.
    If losers never reach positive territory, the entry is bad.
    """
    closed = [t for t in trades if t.outcome in ("HIT_TP", "HIT_SL")]
    winners = [t for t in closed if t.outcome == "HIT_TP"]
    losers = [t for t in closed if t.outcome == "HIT_SL"]

    def avg(lst, attr):
        vals = [getattr(t, attr) for t in lst if getattr(t, attr) is not None]
        return sum(vals) / len(vals) if vals else 0.0

    # Percentage of losers reaching positive R thresholds
    thresholds = [0.5, 1.0, 1.5, 2.0]
    loser_reach = {}
    for threshold in thresholds:
        count = sum(1 for t in losers if t.mfe_r >= threshold)
        loser_reach[f"reach_{threshold}r"] = count / len(losers) * 100 if losers else 0.0

    # Diagnosis
    avg_loser_mfe = avg(losers, "mfe_r")
    avg_loser_mae = avg(losers, "mae_r")
    loser_reach_1r = loser_reach.get("reach_1r", 0.0)

    if loser_reach_1r > 50:
        diagnosis = "EXIT_PROBLEM: >50% of losers reach +1R before SL — exits are too loose or trailing stop absent"
    elif avg_loser_mfe > 1.0:
        diagnosis = "EXIT_PROBLEM: losers achieve significant favorable excursion before stopping out"
    elif avg_loser_mae > 0.8 and avg_loser_mfe < 0.5:
        diagnosis = "ENTRY_PROBLEM: losers move against entry immediately with minimal favorable excursion"
    else:
        diagnosis = "MIXED: both entry and exit contribute to losses"

    return {
        "total_trades": len(closed),
        "winners": {
            "count": len(winners),
            "avg_mfe_r": round(avg(winners, "mfe_r"), 3),
            "avg_mae_r": round(avg(winners, "mae_r"), 3),
            "avg_pnl_pct": round(avg(winners, "pnl_pct"), 3),
            "avg_hold_bars": round(avg(winners, "hold_bars"), 1),
        },
        "losers": {
            "count": len(losers),
            "avg_mfe_r": round(avg_loser_mfe, 3),
            "avg_mae_r": round(avg_loser_mae, 3),
            "avg_pnl_pct": round(avg(losers, "pnl_pct"), 3),
            "avg_hold_bars": round(avg(losers, "hold_bars"), 1),
            "pct_reaching": loser_reach,
        },
        "diagnosis": diagnosis,
    }


# ══════════════════════════════════════════════════════════════════
# Stage 2: Time-To-Failure Analysis
# ══════════════════════════════════════════════════════════════════

def analyze_time_to_failure(trades: list[TradeRecord]) -> dict:
    """Detect premature entries and knife-catching behaviour."""
    closed = [t for t in trades if t.outcome in ("HIT_TP", "HIT_SL")]
    losers = [t for t in closed if t.outcome == "HIT_SL"]
    winners = [t for t in closed if t.outcome == "HIT_TP"]

    def avg_bars(lst):
        bars = [t.hold_bars for t in lst if t.hold_bars > 0]
        return sum(bars) / len(bars) if bars else 0.0

    # Histogram of holding periods
    bins = [(0, 1), (1, 2), (2, 3), (3, 5), (5, 10), (10, 20), (20, 50), (50, 999)]
    histogram = {}
    for lo, hi in bins:
        label = f"{lo}-{hi}" if hi < 999 else f"{lo}+"
        count = sum(1 for t in losers if lo <= t.hold_bars < hi)
        pct = count / len(losers) * 100 if losers else 0.0
        histogram[label] = {"count": count, "pct": round(pct, 1)}

    # Early failure rates
    early = {}
    for n in [1, 2, 3]:
        count = sum(1 for t in losers if t.hold_bars <= n)
        early[f"within_{n}_bars"] = {
            "count": count,
            "pct": round(count / len(losers) * 100, 1) if losers else 0.0,
        }

    avg_loss_bars = avg_bars(losers)
    avg_win_bars = avg_bars(winners)

    # Diagnosis
    pct_within_2 = early.get("within_2_bars", {}).get("pct", 0.0)
    if pct_within_2 > 40:
        diagnosis = "PREMATURE_ENTRIES: >40% of losses occur within 2 bars — entries against immediate momentum"
    elif avg_loss_bars < avg_win_bars * 0.3:
        diagnosis = "KNIFE_CATCHING: losses resolved much faster than wins — entering too early in moves"
    else:
        diagnosis = "ACCEPTABLE: loss timing within normal range"

    return {
        "avg_bars_to_sl": round(avg_loss_bars, 1),
        "avg_bars_to_tp": round(avg_win_bars, 1),
        "histogram": histogram,
        "early_failure": early,
        "diagnosis": diagnosis,
    }


# ══════════════════════════════════════════════════════════════════
# Stage 3: Directional Analysis
# ══════════════════════════════════════════════════════════════════

def analyze_directional_bias(trades: list[TradeRecord]) -> dict:
    """Detect directional bias in expectancy."""
    buy_trades = [t for t in trades if t.direction == "BUY"]
    sell_trades = [t for t in trades if t.direction == "SELL"]

    buy_stats = compute_group_stats(buy_trades, "BUY")
    sell_stats = compute_group_stats(sell_trades, "SELL")

    delta_expectancy = buy_stats.expectancy_r - sell_stats.expectancy_r

    if abs(delta_expectancy) < 0.1:
        diagnosis = "BALANCED: no significant directional bias"
    elif delta_expectancy > 0.3:
        diagnosis = "BUY_BIAS: BUY trades significantly outperform SELL trades"
    elif delta_expectancy < -0.3:
        diagnosis = "SELL_BIAS: SELL trades significantly outperform BUY trades"
    else:
        diagnosis = "SLIGHT_IMBALANCE: minor directional performance difference"

    return {
        "buy": {
            "trades": buy_stats.sample_count,
            "wr": round(buy_stats.winrate * 100, 1),
            "pf": round(buy_stats.profit_factor, 2),
            "expectancy_r": round(buy_stats.expectancy_r, 3),
            "avg_pnl_pct": round(buy_stats.avg_pnl_pct, 3),
            "avg_hold_bars": round(buy_stats.avg_hold_bars, 1),
            "avg_mfe_r": round(buy_stats.avg_mfe_r, 3),
            "avg_mae_r": round(buy_stats.avg_mae_r, 3),
        },
        "sell": {
            "trades": sell_stats.sample_count,
            "wr": round(sell_stats.winrate * 100, 1),
            "pf": round(sell_stats.profit_factor, 2),
            "expectancy_r": round(sell_stats.expectancy_r, 3),
            "avg_pnl_pct": round(sell_stats.avg_pnl_pct, 3),
            "avg_hold_bars": round(sell_stats.avg_hold_bars, 1),
            "avg_mfe_r": round(sell_stats.avg_mfe_r, 3),
            "avg_mae_r": round(sell_stats.avg_mae_r, 3),
        },
        "delta_expectancy_r": round(delta_expectancy, 3),
        "diagnosis": diagnosis,
    }


# ══════════════════════════════════════════════════════════════════
# Stage 4: Scenario Freshness Analysis
# ══════════════════════════════════════════════════════════════════

def analyze_scenario_freshness(trades: list[TradeRecord]) -> dict:
    """Estimate empirical half-life of scenarios.

    Groups expectancy by BOS age, scenario age, stability, and decay.
    """
    # BOS age bins
    bos_stats = compute_feature_binned_stats(
        trades, BOS_AGE_BINS, lambda t: t.bos_age_bars,
    )

    # Scenario stability bins
    stability_bins = [
        ("stability_<0.3", lambda s: s is not None and s < 0.3),
        ("stability_0.3-0.6", lambda s: s is not None and 0.3 <= s < 0.6),
        ("stability_0.6-0.8", lambda s: s is not None and 0.6 <= s < 0.8),
        ("stability_>=0.8", lambda s: s is not None and s >= 0.8),
    ]
    stability_stats = compute_feature_binned_stats(
        trades, stability_bins, lambda t: t.scenario_stability,
    )

    # Decay factor bins
    decay_bins = [
        ("decay_<0.3", lambda s: s is not None and s < 0.3),
        ("decay_0.3-0.6", lambda s: s is not None and 0.3 <= s < 0.6),
        ("decay_0.6-0.8", lambda s: s is not None and 0.6 <= s < 0.8),
        ("decay_>=0.8", lambda s: s is not None and s >= 0.8),
    ]
    decay_stats = compute_feature_binned_stats(
        trades, decay_bins, lambda t: t.decay_factor,
    )

    # Find half-life: where expectancy drops to 50% of peak
    half_life = None
    qualifying = [s for s in bos_stats if s.sample_count >= 3]
    if qualifying:
        peak_exp = max(s.expectancy_r for s in qualifying)
        for s in qualifying:
            if s.expectancy_r <= peak_exp * 0.5:
                label = s.name
                if "<=3" in label:
                    half_life = 3
                elif "4-10" in label:
                    half_life = 7
                elif ">10" in label:
                    half_life = 12
                break

    return {
        "bos_age": [_stats_to_dict(s) for s in bos_stats],
        "stability": [_stats_to_dict(s) for s in stability_stats],
        "decay": [_stats_to_dict(s) for s in decay_stats],
        "estimated_half_life_bars": half_life,
        "diagnosis": (
            f"Scenarios lose 50% expectancy after ~{half_life} bars"
            if half_life else "Insufficient data to estimate half-life"
        ),
    }


# ══════════════════════════════════════════════════════════════════
# Stage 5: Feature Expectancy Analysis
# ══════════════════════════════════════════════════════════════════

def analyze_feature_expectancy(trades: list[TradeRecord]) -> dict:
    """For each feature, compute expectancy metrics."""
    results = {}

    # ADX
    results["adx"] = [_stats_to_dict(s) for s in compute_feature_binned_stats(
        trades, ADX_BINS, lambda t: t.adx,
    )]

    # BOS Age
    results["bos_age"] = [_stats_to_dict(s) for s in compute_feature_binned_stats(
        trades, BOS_AGE_BINS, lambda t: t.bos_age_bars,
    )]

    # OB Distance
    results["ob_distance"] = [_stats_to_dict(s) for s in compute_feature_binned_stats(
        trades, OB_DISTANCE_BINS, lambda t: t.ob_distance_atr,
    )]

    # R:R
    results["rr_ratio"] = [_stats_to_dict(s) for s in compute_feature_binned_stats(
        trades, RR_BINS, lambda t: t.rr_ratio,
    )]

    # Regime
    regimes = list(set(t.regime for t in trades if t.regime))
    results["regime"] = []
    for regime in regimes:
        subset = [t for t in trades if t.regime == regime]
        stats = compute_group_stats(subset, regime)
        results["regime"].append(_stats_to_dict(stats))

    # Direction
    results["direction"] = []
    for direction in ["BUY", "SELL"]:
        subset = [t for t in trades if t.direction == direction]
        stats = compute_group_stats(subset, direction)
        results["direction"].append(_stats_to_dict(stats))

    # Structure alignment
    results["structure_alignment"] = []
    for aligned in [True, False]:
        subset = [t for t in trades if t.structure_alignment == aligned]
        label = "aligned" if aligned else "counter_trend"
        stats = compute_group_stats(subset, label)
        results["structure_alignment"].append(_stats_to_dict(stats))

    # Sweep present
    results["sweep"] = []
    for present in [True, False]:
        subset = [t for t in trades if t.sweep_present == present]
        label = "sweep_present" if present else "no_sweep"
        stats = compute_group_stats(subset, label)
        results["sweep"].append(_stats_to_dict(stats))

    # OB present
    results["ob_present"] = []
    for present in [True, False]:
        subset = [t for t in trades if t.ob_present == present]
        label = "ob_present" if present else "no_ob"
        stats = compute_group_stats(subset, label)
        results["ob_present"].append(_stats_to_dict(stats))

    # FVG present
    results["fvg"] = []
    for present in [True, False]:
        subset = [t for t in trades if t.fvg_present == present]
        label = "fvg_present" if present else "no_fvg"
        stats = compute_group_stats(subset, label)
        results["fvg"].append(_stats_to_dict(stats))

    # Scenario confidence bins
    conf_bins = [
        ("conf_<0.3", lambda c: c is not None and c < 0.3),
        ("conf_0.3-0.5", lambda c: c is not None and 0.3 <= c < 0.5),
        ("conf_0.5-0.7", lambda c: c is not None and 0.5 <= c < 0.7),
        ("conf_>=0.7", lambda c: c is not None and c >= 0.7),
    ]
    results["scenario_confidence"] = [_stats_to_dict(s) for s in compute_feature_binned_stats(
        trades, conf_bins, lambda t: t.scenario_confidence,
    )]

    # Scenario score bins
    score_bins = [
        ("score_<30", lambda s: s is not None and s < 30),
        ("score_30-50", lambda s: s is not None and 30 <= s < 50),
        ("score_50-70", lambda s: s is not None and 50 <= s < 70),
        ("score_>=70", lambda s: s is not None and s >= 70),
    ]
    results["scenario_score"] = [_stats_to_dict(s) for s in compute_feature_binned_stats(
        trades, score_bins, lambda t: t.scenario_score,
    )]

    return results


# ══════════════════════════════════════════════════════════════════
# Stage 6: Scenario Type Ranking
# ══════════════════════════════════════════════════════════════════

def rank_scenario_types(trades: list[TradeRecord]) -> list[dict]:
    """Rank scenario types by expectancy."""
    by_type = defaultdict(list)
    for t in trades:
        key = t.scenario_type if t.scenario_type else "unknown"
        by_type[key].append(t)

    rankings = []
    for scenario_type, type_trades in by_type.items():
        stats = compute_group_stats(type_trades, scenario_type)
        rankings.append({
            "scenario_type": scenario_type,
            "trades": stats.sample_count,
            "wr": round(stats.winrate * 100, 1),
            "pf": round(stats.profit_factor, 2),
            "expectancy_r": round(stats.expectancy_r, 3),
            "avg_rr": round(stats.avg_win_r, 2),
            "avg_pnl_pct": round(stats.avg_pnl_pct, 3),
        })

    rankings.sort(key=lambda x: x["expectancy_r"], reverse=True)
    return rankings


# ══════════════════════════════════════════════════════════════════
# Stage 7: Failure Clustering
# ══════════════════════════════════════════════════════════════════

def cluster_failures(trades: list[TradeRecord], min_cluster: int = 5) -> list[ClusterInfo]:
    """Cluster losing trades to find repeating defeat patterns.

    Rule-based clustering (no external ML):
    1. Define feature fingerprints from categorical bins
    2. Group trades with identical fingerprints
    3. Filter clusters with >= min_cluster trades
    """
    losers = [t for t in trades if t.outcome == "HIT_SL"]
    if not losers:
        return []

    # Create fingerprints
    def fingerprint(t: TradeRecord) -> str:
        parts = []
        # Regime
        parts.append(f"regime={t.regime or 'unknown'}")
        # ADX bin
        if t.adx is not None:
            if t.adx < 18:
                parts.append("adx=low")
            elif t.adx < 25:
                parts.append("adx=mid")
            elif t.adx < 30:
                parts.append("adx=high")
            else:
                parts.append("adx=very_high")
        else:
            parts.append("adx=unknown")
        # Direction
        parts.append(f"dir={t.direction}")
        # Structure alignment
        parts.append(f"aligned={t.structure_alignment}")
        # BOS age
        if t.bos_age_bars is not None:
            if t.bos_age_bars <= 3:
                parts.append("bos=fresh")
            elif t.bos_age_bars <= 10:
                parts.append("bos=mid")
            else:
                parts.append("bos=stale")
        # OB distance
        if t.ob_distance_atr is not None:
            if t.ob_distance_atr < 1:
                parts.append("ob=near")
            elif t.ob_distance_atr < 2:
                parts.append("ob=mid")
            else:
                parts.append("ob=far")
        else:
            parts.append("ob=none")
        # Sweep
        parts.append(f"sweep={t.sweep_present}")
        # R:R
        if t.rr_ratio is not None:
            if t.rr_ratio < 1.5:
                parts.append("rr=low")
            elif t.rr_ratio < 2.5:
                parts.append("rr=mid")
            else:
                parts.append("rr=high")
        return "|".join(parts)

    # Group by fingerprint
    groups = defaultdict(list)
    for t in losers:
        fp = fingerprint(t)
        groups[fp].append(t)

    # Build clusters
    clusters = []
    for i, (fp, group) in enumerate(
        sorted(groups.items(), key=lambda x: -len(x[1]))
    ):
        if len(group) < min_cluster:
            continue

        # Parse fingerprint into readable features
        features = {}
        for part in fp.split("|"):
            k, v = part.split("=", 1)
            features[k] = v

        stats = compute_group_stats(group, f"Cluster {i+1}")
        clusters.append(ClusterInfo(
            cluster_id=len(clusters) + 1,
            trade_count=len(group),
            features=features,
            expectancy_r=round(stats.expectancy_r, 3),
            avg_pnl_pct=round(stats.avg_pnl_pct, 3),
            winrate=round(stats.winrate * 100, 1),
            dominant_regime=features.get("regime", ""),
            dominant_direction=features.get("dir", ""),
        ))

    return clusters[:10]  # Top 10 clusters


# ══════════════════════════════════════════════════════════════════
# Stage 8: Survivor Analysis
# ══════════════════════════════════════════════════════════════════

def analyze_survivors(trades: list[TradeRecord]) -> dict:
    """Find what winners have that losers don't."""
    winners = [t for t in trades if t.outcome == "HIT_TP"]
    losers = [t for t in trades if t.outcome == "HIT_SL"]

    if not winners or not losers:
        return {"error": "Need both winners and losers for survivor analysis"}

    # Feature frequency comparison
    features_to_check = [
        ("regime", lambda t: t.regime),
        ("structure_trend", lambda t: t.structure_trend),
        ("direction", lambda t: t.direction),
        ("sweep_present", lambda t: t.sweep_present),
        ("ob_present", lambda t: t.ob_present),
        ("fvg_present", lambda t: t.fvg_present),
        ("structure_alignment", lambda t: t.structure_alignment),
        ("choch_present", lambda t: t.choch_present),
    ]

    comparisons = []
    for name, accessor in features_to_check:
        win_vals = defaultdict(int)
        loss_vals = defaultdict(int)
        for t in winners:
            win_vals[str(accessor(t))] += 1
        for t in losers:
            loss_vals[str(accessor(t))] += 1

        all_vals = set(list(win_vals.keys()) + list(loss_vals.keys()))
        for val in all_vals:
            w_count = win_vals.get(val, 0)
            l_count = loss_vals.get(val, 0)
            w_pct = w_count / len(winners) * 100 if winners else 0
            l_pct = l_count / len(losers) * 100 if losers else 0
            delta = w_pct - l_pct
            comparisons.append({
                "feature": name,
                "value": val,
                "winners_pct": round(w_pct, 1),
                "losers_pct": round(l_pct, 1),
                "delta": round(delta, 1),
            })

    # Sort by absolute delta (most differentiating features first)
    comparisons.sort(key=lambda x: abs(x["delta"]), reverse=True)

    # Top winner fingerprints
    win_fps = defaultdict(int)
    for t in winners:
        fp = f"{t.regime}_{t.direction}_{t.structure_alignment}_{t.sweep_present}_{t.ob_present}"
        win_fps[fp] += 1
    top_win_fps = sorted(win_fps.items(), key=lambda x: -x[1])[:5]

    # Features almost absent in winners (potential negative indicators)
    absent_in_winners = [c for c in comparisons if c["delta"] < -10 and c["feature"] not in ("direction",)]

    return {
        "top_discriminating_features": comparisons[:15],
        "top_winner_fingerprints": [
            {"fingerprint": fp, "count": count} for fp, count in top_win_fps
        ],
        "negative_indicators": absent_in_winners[:5],
    }


# ══════════════════════════════════════════════════════════════════
# Helper: stats to dict
# ══════════════════════════════════════════════════════════════════

def _stats_to_dict(s: FeatureStats) -> dict:
    return {
        "name": s.name,
        "trades": s.sample_count,
        "wr": round(s.winrate * 100, 1),
        "pf": round(s.profit_factor, 2),
        "expectancy_r": round(s.expectancy_r, 3),
        "avg_win_r": round(s.avg_win_r, 3),
        "avg_loss_r": round(s.avg_loss_r, 3),
        "avg_pnl_pct": round(s.avg_pnl_pct, 3),
        "avg_hold_bars": round(s.avg_hold_bars, 1),
        "avg_mfe_r": round(s.avg_mfe_r, 3),
        "avg_mae_r": round(s.avg_mae_r, 3),
    }


# ══════════════════════════════════════════════════════════════════
# Report generators
# ══════════════════════════════════════════════════════════════════

def generate_expectancy_report(
    trades: list[TradeRecord],
    feature_stats: dict,
    scenario_rankings: list[dict],
    mae_mfe: dict,
    ttf: dict,
    directional: dict,
    freshness: dict,
    output_path: Path,
) -> None:
    """Generate scenario_expectancy_report.md."""
    lines = []
    w = lines.append

    w("# Scenario Expectancy Report\n")
    w(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")
    w(f"Trades analyzed: {len(trades)}\n")

    # Overall stats
    overall = compute_group_stats(trades, "ALL")
    w("## Overall Performance\n")
    w(f"| Metric | Value |")
    w(f"|--------|-------|")
    w(f"| Total trades | {overall.sample_count} |")
    w(f"| Win rate | {overall.winrate*100:.1f}% |")
    w(f"| Profit factor | {overall.profit_factor:.2f} |")
    w(f"| Expectancy (R) | {overall.expectancy_r:+.3f} |")
    w(f"| Avg win (R) | {overall.avg_win_r:+.3f} |")
    w(f"| Avg loss (R) | {overall.avg_loss_r:+.3f} |")
    w(f"| Avg PnL % | {overall.avg_pnl_pct:+.3f}% |")
    w("")

    # MAE/MFE
    w("## MAE/MFE Analysis — Entry vs Exit Quality\n")
    w(f"**Diagnosis: {mae_mfe['diagnosis']}**\n")
    w("| Metric | Winners | Losers |")
    w("|--------|---------|--------|")
    w(f"| Count | {mae_mfe['winners']['count']} | {mae_mfe['losers']['count']} |")
    w(f"| Avg MFE (R) | {mae_mfe['winners']['avg_mfe_r']:+.3f} | {mae_mfe['losers']['avg_mfe_r']:+.3f} |")
    w(f"| Avg MAE (R) | {mae_mfe['winners']['avg_mae_r']:+.3f} | {mae_mfe['losers']['avg_mae_r']:+.3f} |")
    w(f"| Avg PnL % | {mae_mfe['winners']['avg_pnl_pct']:+.3f}% | {mae_mfe['losers']['avg_pnl_pct']:+.3f}% |")
    w(f"| Avg hold bars | {mae_mfe['winners']['avg_hold_bars']:.1f} | {mae_mfe['losers']['avg_hold_bars']:.1f} |")
    w("")

    w("### Loser Excursion Thresholds\n")
    w("| Threshold | % of losers reaching |")
    w("|-----------|---------------------|")
    for k, v in mae_mfe["losers"]["pct_reaching"].items():
        label = k.replace("reach_", "").replace("r", "R")
        w(f"| +{label} | {v:.1f}% |")
    w("")

    # Time-to-Failure
    w("## Time-To-Failure Analysis\n")
    w(f"**Diagnosis: {ttf['diagnosis']}**\n")
    w(f"- Average bars to SL: **{ttf['avg_bars_to_sl']}**")
    w(f"- Average bars to TP: **{ttf['avg_bars_to_tp']}**\n")
    w("### Holding Period Distribution (Losers)\n")
    w("| Bars | Count | % |")
    w("|------|-------|---|")
    for label, data in ttf["histogram"].items():
        w(f"| {label} | {data['count']} | {data['pct']}% |")
    w("")
    w("### Early Failure Rates\n")
    for k, v in ttf["early_failure"].items():
        label = k.replace("_", " ")
        w(f"- {label}: **{v['count']}** trades ({v['pct']}%)")
    w("")

    # Directional
    w("## Directional Analysis\n")
    w(f"**Diagnosis: {directional['diagnosis']}**\n")
    w("| Metric | BUY | SELL | Delta |")
    w("|--------|-----|------|-------|")
    b, s = directional["buy"], directional["sell"]
    w(f"| Trades | {b['trades']} | {s['trades']} | {b['trades']-s['trades']:+d} |")
    w(f"| Win rate | {b['wr']}% | {s['wr']}% | {b['wr']-s['wr']:+.1f}% |")
    w(f"| PF | {b['pf']} | {s['pf']} | {b['pf']-s['pf']:+.2f} |")
    w(f"| Expectancy (R) | {b['expectancy_r']:+.3f} | {s['expectancy_r']:+.3f} | {directional['delta_expectancy_r']:+.3f} |")
    w(f"| Avg PnL % | {b['avg_pnl_pct']:+.3f}% | {s['avg_pnl_pct']:+.3f}% | {b['avg_pnl_pct']-s['avg_pnl_pct']:+.3f}% |")
    w(f"| Avg hold bars | {b['avg_hold_bars']:.1f} | {s['avg_hold_bars']:.1f} | |")
    w(f"| Avg MFE (R) | {b['avg_mfe_r']:+.3f} | {s['avg_mfe_r']:+.3f} | |")
    w(f"| Avg MAE (R) | {b['avg_mae_r']:+.3f} | {s['avg_mae_r']:+.3f} | |")
    w("")

    # Scenario Type Ranking
    w("## Scenario Type Ranking\n")
    w("| Scenario Type | Trades | WR | PF | Expectancy | Avg RR |")
    w("|---------------|--------|----|----|------------|--------|")
    for r in scenario_rankings:
        w(f"| {r['scenario_type']} | {r['trades']} | {r['wr']}% | {r['pf']} | {r['expectancy_r']:+.3f} | {r['avg_rr']} |")
    w("")

    # Feature Expectancy
    w("## Feature Expectancy Analysis\n")
    for feature_name, bins in feature_stats.items():
        w(f"### {feature_name.replace('_', ' ').title()}\n")
        w("| Bin | Trades | WR | PF | Expectancy | Avg Win | Avg Loss |")
        w("|-----|--------|----|----|------------|---------|----------|")
        for b in bins:
            if b["trades"] >= 3:
                w(f"| {b['name']} | {b['trades']} | {b['wr']}% | {b['pf']} | {b['expectancy_r']:+.3f} | {b['avg_win_r']:+.3f} | {b['avg_loss_r']:+.3f} |")
        w("")

    # Scenario Freshness
    w("## Scenario Freshness Analysis\n")
    w(f"**Estimated half-life: {freshness['estimated_half_life_bars']} bars**\n")
    w(f"**Diagnosis: {freshness['diagnosis']}**\n")
    for category in ["bos_age", "stability", "decay"]:
        w(f"### {category.replace('_', ' ').title()}\n")
        w("| Bin | Trades | WR | PF | Expectancy |")
        w("|-----|--------|----|----|------------|")
        for b in freshness[category]:
            if b["trades"] >= 3:
                w(f"| {b['name']} | {b['trades']} | {b['wr']}% | {b['pf']} | {b['expectancy_r']:+.3f} |")
        w("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written: {output_path}")


def generate_failure_clusters_report(
    clusters: list[ClusterInfo],
    output_path: Path,
) -> None:
    """Generate failure_clusters.md."""
    lines = []
    w = lines.append

    w("# Failure Clusters\n")
    w(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    if not clusters:
        w("No significant failure clusters found (minimum 5 trades per cluster).\n")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"Report written: {output_path}")
        return

    w(f"Found **{len(clusters)}** failure clusters.\n")

    for c in clusters:
        w(f"## Cluster #{c.cluster_id} — {c.trade_count} trades\n")
        w(f"- **Expectancy: {c.expectancy_r:+.3f}R**")
        w(f"- **Avg PnL: {c.avg_pnl_pct:+.3f}%**")
        w(f"- **Win rate: {c.winrate}%**\n")
        w("**Pattern:**\n")
        for k, v in sorted(c.features.items()):
            w(f"- {k}: `{v}`")
        w("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written: {output_path}")


def generate_survivor_report(
    survivor_data: dict,
    output_path: Path,
) -> None:
    """Generate survivor_analysis.md."""
    lines = []
    w = lines.append

    w("# Survivor Analysis\n")
    w(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    if "error" in survivor_data:
        w(f"Error: {survivor_data['error']}\n")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"Report written: {output_path}")
        return

    w("## Top Discriminating Features\n")
    w("Features that most differentiate winners from losers:\n")
    w("| Feature | Value | Winners % | Losers % | Delta |")
    w("|---------|-------|-----------|----------|-------|")
    for f in survivor_data["top_discriminating_features"]:
        w(f"| {f['feature']} | {f['value']} | {f['winners_pct']}% | {f['losers_pct']}% | {f['delta']:+.1f}% |")
    w("")

    w("## Top Winner Fingerprints\n")
    w("Most common feature combinations among winning trades:\n")
    for fp in survivor_data["top_winner_fingerprints"]:
        w(f"- `{fp['fingerprint']}` — {fp['count']} trades")
    w("")

    if survivor_data["negative_indicators"]:
        w("## Negative Indicators\n")
        w("Features that appear significantly more in losers than winners:\n")
        for f in survivor_data["negative_indicators"]:
            w(f"- **{f['feature']}={f['value']}**: {f['losers_pct']}% of losers vs {f['winners_pct']}% of winners (delta: {f['delta']:+.1f}%)")
        w("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written: {output_path}")


# ══════════════════════════════════════════════════════════════════
# Console output
# ══════════════════════════════════════════════════════════════════

def print_summary(
    trades: list[TradeRecord],
    mae_mfe: dict,
    ttf: dict,
    directional: dict,
    freshness: dict,
    scenario_rankings: list[dict],
    clusters: list[ClusterInfo],
) -> None:
    """Print concise console summary."""
    overall = compute_group_stats(trades, "ALL")

    print("\n" + "=" * 70)
    print("SCENARIO FORENSICS — SUMMARY")
    print("=" * 70)

    print(f"\n  Trades: {overall.sample_count} | WR: {overall.winrate*100:.1f}% | "
          f"PF: {overall.profit_factor:.2f} | E: {overall.expectancy_r:+.3f}R")

    print(f"\n  MAE/MFE: {mae_mfe['diagnosis']}")
    print(f"  Time-to-Failure: {ttf['diagnosis']}")
    print(f"  Directional: {directional['diagnosis']}")
    print(f"  Scenario Freshness: {freshness['diagnosis']}")

    print("\n  Top Scenario Types:")
    for r in scenario_rankings[:5]:
        print(f"    {r['scenario_type']:<25} E={r['expectancy_r']:+.3f}R  "
              f"WR={r['wr']}%  n={r['trades']}")

    if clusters:
        print(f"\n  Failure Clusters: {len(clusters)} found")
        for c in clusters[:3]:
            print(f"    Cluster #{c.cluster_id}: {c.trade_count} trades, "
                  f"E={c.expectancy_r:+.3f}R — {c.features}")

    print("\n" + "=" * 70)


# ══════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Scenario Forensics — identify where statistical edge is destroyed"
    )
    parser.add_argument("--db", default=str(DB_PATH), help="Path to SQLite database")
    parser.add_argument("--days", type=int, default=90, help="Analyze trades from last N days")
    parser.add_argument("--reports-only", action="store_true", help="Skip console summary, only generate reports")
    args = parser.parse_args()

    db_path = args.db
    if not Path(db_path).exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    print(f"Loading trades from {db_path} (last {args.days} days)...")
    trades = load_trades(db_path, args.days)
    print(f"Loaded {len(trades)} resolved trades")

    if not trades:
        print("No resolved trades found. Nothing to analyze.")
        sys.exit(0)

    # Run all analyses
    print("Running MAE/MFE analysis...")
    mae_mfe = analyze_mae_mfe(trades)

    print("Running Time-to-Failure analysis...")
    ttf = analyze_time_to_failure(trades)

    print("Running Directional analysis...")
    directional = analyze_directional_bias(trades)

    print("Running Feature Expectancy analysis...")
    feature_stats = analyze_feature_expectancy(trades)

    print("Running Scenario Type ranking...")
    scenario_rankings = rank_scenario_types(trades)

    print("Running Scenario Freshness analysis...")
    freshness = analyze_scenario_freshness(trades)

    print("Running Failure Clustering...")
    clusters = cluster_failures(trades)

    print("Running Survivor Analysis...")
    survivor_data = analyze_survivors(trades)

    # Generate reports
    print("\nGenerating reports...")
    generate_expectancy_report(
        trades, feature_stats, scenario_rankings,
        mae_mfe, ttf, directional, freshness,
        REPORTS_DIR / "scenario_expectancy_report.md",
    )
    generate_failure_clusters_report(
        clusters,
        REPORTS_DIR / "failure_clusters.md",
    )
    generate_survivor_report(
        survivor_data,
        REPORTS_DIR / "survivor_analysis.md",
    )

    if not args.reports_only:
        print_summary(trades, mae_mfe, ttf, directional, freshness, scenario_rankings, clusters)


if __name__ == "__main__":
    main()
