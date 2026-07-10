"""
strategy/hypothesis.py — Hypothesis Engine core.

Defines:
    NarrativeType     — classification of market stories
    ScenarioComponent — single node in a narrative chain
    Hypothesis        — one market hypothesis (NOT a signal)
    HypothesisSet     — container for competing hypotheses
    compute_utility() — weighted scoring function
    compute_exponential_decay() — freshness calculation

Design principles:
    - Quality (0-100), Confidence (0-1), Decay (0-1) are NEVER mixed
    - HypothesisSet does NOT make decisions (no winner property)
    - Utility function uses controlled weights, not multiplication
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Optional


# ── Narrative Types ────────────────────────────────────────────────
# Classification for statistics. Each hypothesis has exactly one type.

NarrativeType = Literal[
    "sweep_bos_ob_fvg",       # classic ICT chain
    "sweep_bos_ob",           # without FVG
    "bos_ob_fvg",             # without sweep
    "ob_retest",              # OB retest / mitigation
    "choch_ob",               # CHoCH + OB
    "liquidity_grab",         # sweep + reclaim
    "trend_continuation",     # pullback in trend
    "reversal",               # market reversal
    "range_bound",            # range trading
    "bos_mitigation",         # BOS + mitigation
    "fvg_fill",               # FVG fill
    "pullback_ob",            # pullback to OB in trend
]

ALL_NARRATIVE_TYPES: list[str] = [
    "sweep_bos_ob_fvg", "sweep_bos_ob", "bos_ob_fvg",
    "ob_retest", "choch_ob", "liquidity_grab",
    "trend_continuation", "reversal", "range_bound",
    "bos_mitigation", "fvg_fill", "pullback_ob",
]


# ── Scenario Component ─────────────────────────────────────────────

@dataclass(frozen=True)
class ScenarioComponent:
    """One component in a narrative chain (a node in the graph)."""
    id: str
    type: str
    description: str
    node_id: Optional[str] = None
    price_level: Optional[float] = None
    is_critical: bool = True


# ── Hypothesis ─────────────────────────────────────────────────────

@dataclass
class Hypothesis:
    """One market hypothesis. NOT a signal.

    This is "the market CAN do this".
    Three dimensions: Quality, Confidence, Decay — never mixed.

    Attributes:
        direction: buy / sell
        narrative_type: classification for statistics
        quality: [0, 100] — how good is the scenario structure
        confidence: [0, 1] — how confident is the system
        decay_factor: [0, 1] — freshness (1.0 = brand new)
    """
    id: str
    direction: Literal["buy", "sell"]
    narrative_type: str  # NarrativeType
    name: str                           # "Sweep → BOS → OB → Target"
    description: str

    # ── Core metrics (separate, never mixed) ──
    quality: float                      # [0, 100]
    confidence: float                   # [0, 1]
    decay_factor: float                 # [0, 1]

    # ── Trade parameters ──
    entry_price: float
    invalidation_price: float           # SL level
    target_price: float                 # TP level
    rr_ratio: float

    # ── Metadata ──
    components: tuple[ScenarioComponent, ...] = ()
    node_ids: tuple[str, ...] = ()
    created_at_bar: int = 0
    current_bar: int = 0
    source: str = "chain"               # "chain" | "pattern"

    # ── Expected metrics (for memory) ──
    expected_rr: float = 0.0
    expected_p_tp: float = 0.0

    @property
    def age_bars(self) -> int:
        return self.current_bar - self.created_at_bar

    @property
    def is_alive(self) -> bool:
        return self.decay_factor > 0.1


# ── Utility Function ───────────────────────────────────────────────
# Weights: sum = 1.0. Controls contribution of each parameter.
# NOT multiplication — weighted sum with normalized quality.

UTILITY_WEIGHTS = {
    "quality": 0.55,
    "confidence": 0.30,
    "decay": 0.15,
}


def compute_utility(h: Hypothesis) -> float:
    """Weighted utility function.

    quality: [0, 100] → normalized to [0, 1]
    confidence: [0, 1]
    decay: [0, 1]

    Result: [0, 1]. Higher = better hypothesis.
    """
    q = h.quality / 100.0
    c = h.confidence
    d = h.decay_factor
    return (
        UTILITY_WEIGHTS["quality"] * q
        + UTILITY_WEIGHTS["confidence"] * c
        + UTILITY_WEIGHTS["decay"] * d
    )


# ── Exponential Decay ──────────────────────────────────────────────

def compute_exponential_decay(
    age_bars: int,
    node_state_scores: list[float],
    lambda_decay: float = 0.02,
) -> float:
    """Exponential decay: exp(-λt) × mean(node_state_scores).

    λ = 0.02 → half-life ~35 bars
    λ = 0.01 → half-life ~70 bars

    Args:
        age_bars: how many bars since hypothesis was created
        node_state_scores: state_score for each node in the hypothesis
        lambda_decay: decay rate (higher = faster decay)

    Returns:
        [0, 1] — 1.0 = fresh, 0.0 = dead
    """
    base = math.exp(-lambda_decay * age_bars)
    avg_node = (
        sum(node_state_scores) / len(node_state_scores)
        if node_state_scores
        else 0.5
    )
    return max(0.0, min(1.0, base * avg_node))


# ── HypothesisSet ──────────────────────────────────────────────────

@dataclass
class HypothesisSet:
    """Container for all competing hypotheses.

    Does NOT make decisions. Only stores, sorts, computes decay.
    """
    symbol: str
    timeframe: str
    hypotheses: list[Hypothesis] = field(default_factory=list)
    created_at_bar: int = 0
    version: int = 0

    def add(self, h: Hypothesis) -> None:
        self.hypotheses.append(h)
        self.version += 1

    def update_decay(self, current_bar: int) -> None:
        """Update current_bar for all hypotheses (decay recomputed externally)."""
        for h in self.hypotheses:
            h.current_bar = current_bar

    def remove_expired(self, max_age_bars: int = 100) -> None:
        self.hypotheses = [
            h for h in self.hypotheses
            if h.age_bars < max_age_bars and h.is_alive
        ]

    # ── Queries ──

    @property
    def best_buy(self) -> Optional[Hypothesis]:
        buys = [h for h in self.hypotheses if h.direction == "buy" and h.is_alive]
        return max(buys, key=lambda h: compute_utility(h), default=None)

    @property
    def best_sell(self) -> Optional[Hypothesis]:
        sells = [h for h in self.hypotheses if h.direction == "sell" and h.is_alive]
        return max(sells, key=lambda h: compute_utility(h), default=None)

    @property
    def ambiguity_gap(self) -> float:
        """|best_buy_utility - best_sell_utility|. [0, 1]."""
        b, s = self.best_buy, self.best_sell
        if not b or not s:
            return 1.0
        return abs(compute_utility(b) - compute_utility(s))

    def by_narrative(self, narrative_type: str) -> list[Hypothesis]:
        return [h for h in self.hypotheses if h.narrative_type == narrative_type]

    def by_direction(self, direction: str) -> list[Hypothesis]:
        return [h for h in self.hypotheses if h.direction == direction and h.is_alive]

    def ranked(self) -> list[Hypothesis]:
        """All hypotheses sorted by utility (descending)."""
        return sorted(self.hypotheses, key=lambda h: -compute_utility(h))

    def top(self, n: int = 5) -> list[Hypothesis]:
        return self.ranked()[:n]

    def __len__(self) -> int:
        return len(self.hypotheses)

    def __repr__(self) -> str:
        return (
            f"HypothesisSet({self.symbol} {self.timeframe}: "
            f"{len(self.hypotheses)} hypotheses, v{self.version})"
        )
