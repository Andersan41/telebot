"""
strategy/decision_engine.py — Decision Engine.

Selects the best hypothesis from a HypothesisSet.
Does NOT handle Portfolio, Risk, or Position Sizing — that's Execution Layer.

Design:
    - MarketState provides narrative weights (not binary allowed/blocked)
    - DecisionEngine only answers: "which hypothesis is best?"
    - Ambiguity: if best_buy ≈ best_sell → NO TRADE
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from strategy.hypothesis import (
    Hypothesis,
    HypothesisSet,
    ALL_NARRATIVE_TYPES,
    compute_utility,
)
from strategy.market_phase_engine import (
    MarketPhase,
    PhaseAssessment,
    get_narrative_weight,
    get_narrative_weights,
)


# ── Market State ───────────────────────────────────────────────────

@dataclass
class MarketState:
    """Market state at decision time.

    Returns narrative weights (not binary allowed/blocked).
    weight > 1.0 = phase favors this narrative
    weight < 1.0 = phase disfavors this narrative
    weight = 0.0 = fully blocked
    """
    phase: MarketPhase
    phase_confidence: float
    narrative_weights: dict[str, float]   # narrative_type → [0, 2.0]

    @classmethod
    def from_assessment(cls, assessment: PhaseAssessment) -> MarketState:
        weights = get_narrative_weights(assessment.phase)
        return cls(
            phase=assessment.phase,
            phase_confidence=assessment.confidence,
            narrative_weights=weights,
        )

    def get_weight(self, narrative_type: str) -> float:
        return self.narrative_weights.get(narrative_type, 1.0)


# ── Decision ───────────────────────────────────────────────────────

@dataclass
class Decision:
    """Result from Decision Engine.

    Does NOT contain Portfolio/Risk/Position sizing — that's Execution.
    """
    trade: bool
    hypothesis: Optional[Hypothesis] = None
    confidence: float = 0.0
    utility: float = 0.0
    reasons: list[str] = field(default_factory=list)
    rejection_reason: Optional[str] = None
    market_state: Optional[MarketState] = None


# ── Decision Engine ────────────────────────────────────────────────

class DecisionEngine:
    """Selects the best hypothesis. Does not handle portfolio or risk.

    Responsibilities:
    1. Apply narrative weights from MarketState
    2. Ambiguity check (BUY ≈ SELL → NO TRADE)
    3. Quality gate (minimum utility)
    4. Winner selection
    """

    def __init__(
        self,
        ambiguity_threshold: float = 0.10,
        min_utility: float = 0.25,
    ):
        self.ambiguity_threshold = ambiguity_threshold
        self.min_utility = min_utility

    def decide(
        self,
        hypothesis_set: HypothesisSet,
        market_state: MarketState,
    ) -> Decision:
        hypotheses = hypothesis_set.ranked()
        if not hypotheses:
            return Decision(
                trade=False,
                reasons=["no hypotheses generated"],
                rejection_reason="no_valid_hypothesis",
            )

        # 1. Apply narrative weights from Market State
        weighted: list[tuple[Hypothesis, float]] = []
        for h in hypotheses:
            weight = market_state.get_weight(h.narrative_type)
            utility = compute_utility(h) * weight
            weighted.append((h, utility))

        weighted.sort(key=lambda x: -x[1])

        # 2. Find best BUY and best SELL
        best_buy: Optional[tuple[Hypothesis, float]] = None
        best_sell: Optional[tuple[Hypothesis, float]] = None
        for h, u in weighted:
            if h.direction == "buy" and best_buy is None:
                best_buy = (h, u)
            elif h.direction == "sell" and best_sell is None:
                best_sell = (h, u)

        # 3. Ambiguity check
        if best_buy and best_sell:
            gap = abs(best_buy[1] - best_sell[1])
            if gap < self.ambiguity_threshold:
                return Decision(
                    trade=False,
                    reasons=[
                        f"ambiguous: buy={best_buy[1]:.3f} "
                        f"sell={best_sell[1]:.3f} gap={gap:.3f}",
                    ],
                    rejection_reason="ambiguous",
                    market_state=market_state,
                )

        # 4. Winner selection
        winner, winner_utility = weighted[0]

        # 5. Quality gate
        if winner_utility < self.min_utility:
            return Decision(
                trade=False,
                reasons=[
                    f"utility {winner_utility:.3f} < min {self.min_utility}",
                ],
                rejection_reason="low_utility",
                market_state=market_state,
            )

        return Decision(
            trade=True,
            hypothesis=winner,
            confidence=winner.confidence,
            utility=winner_utility,
            reasons=[
                f"narrative={winner.narrative_type}",
                f"quality={winner.quality:.0f}",
                f"confidence={winner.confidence:.2f}",
                f"decay={winner.decay_factor:.2f}",
                f"utility={winner_utility:.3f}",
                f"phase={market_state.phase.value}",
            ],
            market_state=market_state,
        )
