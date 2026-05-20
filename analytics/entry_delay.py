"""
analytics/entry_delay.py — Entry timing analysis.

Task 7.2 — Entry timing analysis:
  Measure how much of a price move happens BEFORE vs AFTER a signal.
  Goal: > 60% of the movement should occur AFTER the signal (not before).

Metrics:
  - move_before_atr:  ATR-normalized distance price moved before signal
  - move_after_atr:   ATR-normalized distance price moved after signal
  - entry_efficiency: (move_after / total_move) * 100
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from backtest.engine import BacktestTrade


@dataclass
class EntryTimingRecord:
    """Timing analysis for a single signal entry."""
    symbol: str
    timeframe: str
    direction: str  # BUY or SELL
    entry_price: float
    exit_price: float
    atr: float  # ATR at signal time
    swing_start: float  # price where the move started (swing low for BUY, swing high for SELL)
    swing_end: float  # price where the move ended (swing high for BUY, swing low for SELL)
    move_before: float  # absolute price distance from swing_start to entry
    move_after: float  # absolute price distance from entry to exit
    total_move: float  # absolute price distance from swing_start to swing_end
    move_before_atr: float  # move_before normalized by ATR
    move_after_atr: float  # move_after normalized by ATR
    entry_efficiency: float  # (move_after / total_move) * 100, capped at 100


@dataclass
class EntryEfficiencySummary:
    """Aggregate entry efficiency metrics across all analyzed trades."""
    total_records: int = 0
    avg_efficiency: float = 0.0
    median_efficiency: float = 0.0
    pct_above_60: float = 0.0  # % of trades with efficiency >= 60%
    pct_above_50: float = 0.0  # % of trades with efficiency >= 50%
    avg_move_before_atr: float = 0.0
    avg_move_after_atr: float = 0.0
    by_direction: dict[str, "EntryEfficiencySummary"] = field(default_factory=dict)
    records: list[EntryTimingRecord] = field(default_factory=list)


def analyze_entry_timing(
    trades: list[BacktestTrade],
    swing_data: Optional[dict[int, dict[str, float]]] = None,
) -> list[EntryTimingRecord]:
    """Analyze entry timing for a list of backtest trades.

    For each trade, calculates how much of the total price move happened
    BEFORE the signal vs AFTER the signal.

    Args:
        trades: List of completed backtest trades.
        swing_data: Optional dict mapping entry_index → {
            "swing_start": float,  # swing low for BUY, swing high for SELL
            "swing_end": float,    # swing high for BUY, swing low for SELL
            "atr": float,          # ATR at signal time
        }.
        If not provided, uses trade prices to approximate swings.

    Returns:
        List of EntryTimingRecord with timing metrics for each trade.
    """
    records: list[EntryTimingRecord] = []

    for t in trades:
        swing_start, swing_end, atr = _get_swing_data(t, swing_data)

        if t.direction == "BUY":
            move_before = max(0.0, t.entry_price - swing_start)
            move_after = max(0.0, t.exit_price - t.entry_price) if t.exit_price else 0.0
            total_move = max(0.0001, swing_end - swing_start)
        else:  # SELL
            move_before = max(0.0, swing_start - t.entry_price)
            move_after = max(0.0, t.entry_price - t.exit_price) if t.exit_price else 0.0
            total_move = max(0.0001, swing_start - swing_end)

        move_before_atr = move_before / atr if atr > 0 else 0.0
        move_after_atr = move_after / atr if atr > 0 else 0.0
        entry_efficiency = min(100.0, (move_after / total_move) * 100) if total_move > 0 else 0.0

        records.append(EntryTimingRecord(
            symbol=t.symbol,
            timeframe=t.timeframe,
            direction=t.direction,
            entry_price=t.entry_price,
            exit_price=t.exit_price or t.entry_price,
            atr=atr,
            swing_start=swing_start,
            swing_end=swing_end,
            move_before=round(move_before, 8),
            move_after=round(move_after, 8),
            total_move=round(total_move, 8),
            move_before_atr=round(move_before_atr, 4),
            move_after_atr=round(move_after_atr, 4),
            entry_efficiency=round(entry_efficiency, 2),
        ))

    return records


def compute_entry_efficiency_summary(
    records: list[EntryTimingRecord],
) -> EntryEfficiencySummary:
    """Compute aggregate entry efficiency metrics.

    Args:
        records: List of EntryTimingRecord from analyze_entry_timing().

    Returns:
        EntryEfficiencySummary with avg, median, and breakdown by direction.
    """
    if not records:
        return EntryEfficiencySummary()

    efficiencies = [r.entry_efficiency for r in records]
    before_atrs = [r.move_before_atr for r in records]
    after_atrs = [r.move_after_atr for r in records]

    sorted_eff = sorted(efficiencies)
    n = len(sorted_eff)
    median = sorted_eff[n // 2] if n % 2 == 1 else (sorted_eff[n // 2 - 1] + sorted_eff[n // 2]) / 2

    above_60 = sum(1 for e in efficiencies if e >= 60)
    above_50 = sum(1 for e in efficiencies if e >= 50)

    # Breakdown by direction (flat summaries, no nested by_direction)
    by_direction: dict[str, EntryEfficiencySummary] = {}
    for direction in ("BUY", "SELL"):
        dir_records = [r for r in records if r.direction == direction]
        if dir_records:
            by_direction[direction] = _compute_flat_summary(dir_records)

    return EntryEfficiencySummary(
        total_records=n,
        avg_efficiency=round(sum(efficiencies) / n, 2),
        median_efficiency=round(median, 2),
        pct_above_60=round(above_60 / n * 100, 1),
        pct_above_50=round(above_50 / n * 100, 1),
        avg_move_before_atr=round(sum(before_atrs) / n, 4),
        avg_move_after_atr=round(sum(after_atrs) / n, 4),
        by_direction=by_direction,
        records=records,
    )


def _compute_flat_summary(records: list[EntryTimingRecord]) -> EntryEfficiencySummary:
    """Compute summary without nested by_direction (for sub-summaries)."""
    if not records:
        return EntryEfficiencySummary()

    efficiencies = [r.entry_efficiency for r in records]
    before_atrs = [r.move_before_atr for r in records]
    after_atrs = [r.move_after_atr for r in records]

    sorted_eff = sorted(efficiencies)
    n = len(sorted_eff)
    median = sorted_eff[n // 2] if n % 2 == 1 else (sorted_eff[n // 2 - 1] + sorted_eff[n // 2]) / 2

    above_60 = sum(1 for e in efficiencies if e >= 60)
    above_50 = sum(1 for e in efficiencies if e >= 50)

    return EntryEfficiencySummary(
        total_records=n,
        avg_efficiency=round(sum(efficiencies) / n, 2),
        median_efficiency=round(median, 2),
        pct_above_60=round(above_60 / n * 100, 1),
        pct_above_50=round(above_50 / n * 100, 1),
        avg_move_before_atr=round(sum(before_atrs) / n, 4),
        avg_move_after_atr=round(sum(after_atrs) / n, 4),
    )


def _get_swing_data(
    trade: BacktestTrade,
    swing_data: Optional[dict[int, dict[str, float]]],
) -> tuple[float, float, float]:
    """Get swing start, swing end, and ATR for a trade.

    Returns (swing_start, swing_end, atr):
    - BUY: swing_start = swing low, swing_end = swing high
    - SELL: swing_start = swing high, swing_end = swing low
    """
    if swing_data and trade.entry_index in swing_data:
        sd = swing_data[trade.entry_index]
        atr = sd.get("atr", 0.0)
        if atr <= 0:
            atr = _approximate_atr(trade)
        return sd["swing_start"], sd["swing_end"], atr

    # Approximate from trade prices
    atr = _approximate_atr(trade)
    if trade.direction == "BUY":
        swing_start = trade.sl
        swing_end = trade.tp if trade.tp else trade.entry_price * 1.02
    else:
        swing_start = trade.sl
        swing_end = trade.tp if trade.tp else trade.entry_price * 0.98

    return swing_start, swing_end, atr


def _approximate_atr(trade: BacktestTrade) -> float:
    """Approximate ATR from trade risk if not available."""
    risk = abs(trade.entry_price - trade.sl)
    if risk > 0:
        return risk / 1.5  # assume SL = ATR * 1.5
    return trade.entry_price * 0.02  # fallback: 2% of price
