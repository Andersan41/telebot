"""
strategy/scenario_memory.py — Scenario Memory

Stores Expected vs Observed statistics per narrative type per symbol.
Collects data ONLY — no auto-learning until 300+ trades per type.

Expected (at entry):
    expected_rr, expected_p_tp, expected_quality, expected_confidence

Observed (at close):
    actual_rr, actual_pnl_pct, outcome, mfe_pct, mae_pct, hold_bars

Flow:
    Trade opened  → ScenarioMemory.record_expected()
    Trade closed  → ScenarioMemory.record_outcome()
    WeightManager queries → ScenarioMemory.get_stats()
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from loguru import logger


# ── Outcome Record (Expected vs Observed) ──────────────────────────

@dataclass
class ScenarioOutcomeRecord:
    """One trade: expected metrics vs observed outcome."""
    symbol: str
    hypothesis_name: str
    narrative_type: str
    direction: str

    # Expected (at entry)
    expected_rr: float = 0.0
    expected_p_tp: float = 0.0
    expected_quality: float = 0.0
    expected_confidence: float = 0.0

    # Observed (at close)
    actual_rr: Optional[float] = None
    actual_pnl_pct: Optional[float] = None
    outcome: Optional[str] = None       # HIT_TP / HIT_SL / EXPIRED

    # Excursion
    mfe_pct: Optional[float] = None     # Maximum Favorable Excursion
    mae_pct: Optional[float] = None     # Maximum Adverse Excursion
    hold_bars: Optional[int] = None


# ── Stats (aggregated per narrative type) ───────────────────────────

@dataclass
class ScenarioStats:
    """Aggregated statistics for a narrative type on a symbol."""
    scenario_name: str       # narrative_type
    symbol: str
    direction: str = ""      # buy / sell / ""

    total_seen: int = 0
    total_activated: int = 0
    total_wins: int = 0
    total_losses: int = 0
    total_breakeven: int = 0

    total_rr: float = 0.0
    avg_rr: float = 0.0
    avg_hold_bars: float = 0.0

    # Expected vs Observed aggregates
    avg_expected_rr: float = 0.0
    avg_expected_p_tp: float = 0.0
    avg_expected_quality: float = 0.0
    avg_expected_confidence: float = 0.0
    avg_actual_pnl_pct: float = 0.0
    avg_mfe_pct: float = 0.0
    avg_mae_pct: float = 0.0

    # Recent performance (last 30 trades)
    recent_win_count: int = 0
    recent_loss_count: int = 0
    recent_rr_sum: float = 0.0

    @property
    def closed_count(self) -> int:
        return self.total_wins + self.total_losses + self.total_breakeven

    @property
    def winrate(self) -> float:
        closed = self.closed_count
        if closed == 0:
            return 0.0
        return self.total_wins / closed

    @property
    def expectancy(self) -> float:
        closed = self.closed_count
        if closed == 0:
            return 0.0
        win_avg = self.avg_rr if self.avg_rr > 0 else 1.0
        return (self.winrate * win_avg) - (1 - self.winrate)

    @property
    def profit_factor(self) -> float:
        wr = self.winrate
        if wr >= 1.0:
            return float("inf")
        if wr <= 0.0:
            return 0.0
        return (wr * self.avg_rr) / ((1 - wr) * 1.0) if self.avg_rr > 0 else 0.0

    @property
    def is_reliable(self) -> bool:
        return self.closed_count >= 30

    @property
    def sample_label(self) -> str:
        if self.closed_count < 10:
            return "insufficient"
        elif self.closed_count < 30:
            return "limited"
        elif self.closed_count < 100:
            return "moderate"
        return "sufficient"

    @property
    def calibration_gap(self) -> float:
        """Expected P vs actual winrate. Lower = better calibrated."""
        if self.closed_count < 10:
            return 0.0
        return abs(self.avg_expected_p_tp - self.winrate)

    def __repr__(self) -> str:
        return (
            f"Stats({self.symbol} {self.scenario_name}: "
            f"n={self.closed_count} wr={self.winrate:.0%} "
            f"rr={self.avg_rr:.2f} pf={self.profit_factor:.2f} "
            f"E={self.expectancy:.2f}R [{self.sample_label}])"
        )


# ── Memory ─────────────────────────────────────────────────────────

class ScenarioMemory:
    """Stores and queries scenario statistics per symbol.

    In-memory store. NO auto-learning — only collects data.
    """

    def __init__(self):
        self.stats: dict[str, ScenarioStats] = {}
        self.records: list[ScenarioOutcomeRecord] = []

    def _key(self, symbol: str, scenario_name: str, direction: str = "") -> str:
        return f"{symbol}:{scenario_name}:{direction}"

    def record_outcome(self, record: ScenarioOutcomeRecord) -> None:
        """Record the outcome of a completed trade."""
        self.records.append(record)

        key = self._key(record.symbol, record.narrative_type, record.direction)
        if key not in self.stats:
            self.stats[key] = ScenarioStats(
                scenario_name=record.narrative_type,
                symbol=record.symbol,
                direction=record.direction,
            )

        stats = self.stats[key]
        stats.total_activated += 1

        if record.outcome == "HIT_TP":
            stats.total_wins += 1
            stats.total_seen += 1
        elif record.outcome == "HIT_SL":
            stats.total_losses += 1
            stats.total_seen += 1
        elif record.outcome == "EXPIRED":
            stats.total_breakeven += 1
            stats.total_seen += 1

        # Update rolling averages
        n = stats.closed_count
        if n > 0 and record.actual_rr is not None:
            stats.total_rr += record.actual_rr
            stats.avg_rr = stats.total_rr / n

        if record.hold_bars is not None and record.hold_bars > 0:
            stats.avg_hold_bars = (
                (stats.avg_hold_bars * (n - 1) + record.hold_bars) / n
                if n > 0 else float(record.hold_bars)
            )

        # Expected vs Observed aggregates
        if record.expected_rr > 0:
            stats.avg_expected_rr = (
                (stats.avg_expected_rr * (stats.total_activated - 1) + record.expected_rr)
                / stats.total_activated
            )
        if record.expected_p_tp > 0:
            stats.avg_expected_p_tp = (
                (stats.avg_expected_p_tp * (stats.total_activated - 1) + record.expected_p_tp)
                / stats.total_activated
            )
        if record.expected_quality > 0:
            stats.avg_expected_quality = (
                (stats.avg_expected_quality * (stats.total_activated - 1) + record.expected_quality)
                / stats.total_activated
            )
        if record.expected_confidence > 0:
            stats.avg_expected_confidence = (
                (stats.avg_expected_confidence * (stats.total_activated - 1) + record.expected_confidence)
                / stats.total_activated
            )
        if record.actual_pnl_pct is not None:
            stats.avg_actual_pnl_pct = (
                (stats.avg_actual_pnl_pct * (stats.total_activated - 1) + record.actual_pnl_pct)
                / stats.total_activated
            )
        if record.mfe_pct is not None:
            stats.avg_mfe_pct = (
                (stats.avg_mfe_pct * (stats.total_activated - 1) + record.mfe_pct)
                / stats.total_activated
            )
        if record.mae_pct is not None:
            stats.avg_mae_pct = (
                (stats.avg_mae_pct * (stats.total_activated - 1) + record.mae_pct)
                / stats.total_activated
            )

        logger.debug(
            f"ScenarioMemory: recorded {record.outcome} for {record.symbol} "
            f"{record.narrative_type} (rr={record.actual_rr}, wr={stats.winrate:.0%}, n={n})"
        )

    def record_expected(
        self,
        symbol: str,
        hypothesis_name: str,
        narrative_type: str,
        direction: str,
        expected_rr: float,
        expected_p_tp: float,
        expected_quality: float,
        expected_confidence: float,
    ) -> None:
        """Record expected metrics when hypothesis is selected (before close)."""
        key = self._key(symbol, narrative_type, direction)
        if key not in self.stats:
            self.stats[key] = ScenarioStats(
                scenario_name=narrative_type,
                symbol=symbol,
                direction=direction,
            )
        self.stats[key].total_seen += 1

    def record_observation(self, symbol: str, scenario_name: str) -> None:
        """Record that a scenario was detected by the ScenarioEngine (no trade taken).

        Tracks detection frequency independent of whether a trade was taken.
        """
        key = self._key(symbol, scenario_name)
        if key not in self.stats:
            self.stats[key] = ScenarioStats(
                scenario_name=scenario_name,
                symbol=symbol,
            )
        self.stats[key].total_seen += 1

    def get_stats(
        self, symbol: str, narrative_type: str, direction: str = "",
    ) -> Optional[ScenarioStats]:
        return self.stats.get(self._key(symbol, narrative_type, direction))

    def get_symbol_stats(self, symbol: str) -> list[ScenarioStats]:
        return [s for s in self.stats.values() if s.symbol == symbol]

    def get_reliable_scenarios(self, symbol: str) -> list[ScenarioStats]:
        return [s for s in self.get_symbol_stats(symbol) if s.is_reliable]

    def get_best_scenarios(
        self,
        symbol: str,
        min_trades: int = 30,
        min_expectancy: float = 0.0,
    ) -> list[ScenarioStats]:
        candidates = [
            s for s in self.get_symbol_stats(symbol)
            if s.closed_count >= min_trades and s.expectancy >= min_expectancy
        ]
        candidates.sort(key=lambda s: s.expectancy, reverse=True)
        return candidates


# Module-level singleton
scenario_memory = ScenarioMemory()
