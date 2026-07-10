"""
strategy/scenario_invalidator.py — Scenario Invalidator.

Separate module that checks when a hypothesis becomes invalid.
Not Risk. Not Thesis. Standalone.

Checks:
    - BOS broken (structure shift)
    - OB mitigated (price closed through midpoint)
    - FVG filled (price filled the gap)
    - Invalidation level hit (SL would have triggered)
    - Node state degraded (critical node died)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from strategy.hypothesis import Hypothesis


# ── Invalidation Reasons ───────────────────────────────────────────

@dataclass(frozen=True)
class InvalidationEvent:
    """Record of why a hypothesis was invalidated."""
    hypothesis_id: str
    reason: str
    details: str
    bar: int
    price: float


# ── Invalidation Conditions ────────────────────────────────────────

@dataclass
class InvalidationResult:
    """Result of checking a hypothesis for invalidation."""
    is_invalid: bool
    reason: Optional[str] = None
    details: Optional[str] = None


@dataclass
class ScenarioInvalidator:
    """Checks if a hypothesis should be killed.

    Responsibilities:
    - Check if critical nodes are dead
    - Check if invalidation level was breached
    - Check if structure shifted against the hypothesis
    - Does NOT handle position sizing or risk
    """
    # Thresholds
    min_node_alive_ratio: float = 0.5     # at least 50% of nodes must be alive
    min_critical_alive: bool = True       # ALL critical nodes must be alive

    def invalidate(
        self,
        hypothesis: Hypothesis,
        graph: object,  # LiquidityGraph
        current_price: float,
        current_bar: int,
    ) -> InvalidationResult:
        """Check if hypothesis should be killed.

        Args:
            hypothesis: the hypothesis to check
            graph: LiquidityGraph (used for node state lookup)
            current_price: current market price
            current_bar: current bar index

        Returns:
            InvalidationResult with is_invalid=True if hypothesis is dead
        """
        # 1. Check node alive ratio
        node_check = self._check_node_alive_ratio(hypothesis, graph)
        if node_check.is_invalid:
            return node_check

        # 2. Check critical nodes
        critical_check = self._check_critical_nodes(hypothesis, graph)
        if critical_check.is_invalid:
            return critical_check

        # 3. Check invalidation level (price breach)
        level_check = self._check_invalidation_level(
            hypothesis, current_price, current_bar,
        )
        if level_check.is_invalid:
            return level_check

        # 4. Check decay (hypothesis too old)
        decay_check = self._check_decay(hypothesis, current_bar)
        if decay_check.is_invalid:
            return decay_check

        return InvalidationResult(is_invalid=False)

    def _check_node_alive_ratio(
        self, h: Hypothesis, graph: object,
    ) -> InvalidationResult:
        """At least min_node_alive_ratio of nodes must be alive."""
        if not h.node_ids:
            return InvalidationResult(is_invalid=False)

        alive_count = 0
        total = len(h.node_ids)
        for nid in h.node_ids:
            node = graph.get_node(nid) if hasattr(graph, "get_node") else None
            if node and hasattr(node, "is_alive") and node.is_alive:
                alive_count += 1

        ratio = alive_count / total if total > 0 else 0.0
        if ratio < self.min_node_alive_ratio:
            return InvalidationResult(
                is_invalid=True,
                reason="node_degraded",
                details=f"alive ratio {ratio:.2f} < {self.min_node_alive_ratio}",
            )
        return InvalidationResult(is_invalid=False)

    def _check_critical_nodes(
        self, h: Hypothesis, graph: object,
    ) -> InvalidationResult:
        """ALL critical nodes must be alive."""
        if not self.min_critical_alive:
            return InvalidationResult(is_invalid=False)

        for comp in h.components:
            if not comp.is_critical or not comp.node_id:
                continue
            node = graph.get_node(comp.node_id) if hasattr(graph, "get_node") else None
            if node and hasattr(node, "is_alive") and not node.is_alive:
                return InvalidationResult(
                    is_invalid=True,
                    reason="critical_node_dead",
                    details=f"critical node {comp.node_id} ({comp.type}) is {node.state}",
                )
        return InvalidationResult(is_invalid=False)

    def _check_invalidation_level(
        self, h: Hypothesis, current_price: float, current_bar: int,
    ) -> InvalidationResult:
        """Check if price breached the invalidation level."""
        if h.invalidation_price <= 0:
            return InvalidationResult(is_invalid=False)

        if h.direction == "buy" and current_price < h.invalidation_price:
            return InvalidationResult(
                is_invalid=True,
                reason="invalidation_breached",
                details=(
                    f"price {current_price:.4f} < "
                    f"invalidation {h.invalidation_price:.4f}"
                ),
            )

        if h.direction == "sell" and current_price > h.invalidation_price:
            return InvalidationResult(
                is_invalid=True,
                reason="invalidation_breached",
                details=(
                    f"price {current_price:.4f} > "
                    f"invalidation {h.invalidation_price:.4f}"
                ),
            )

        return InvalidationResult(is_invalid=False)

    def _check_decay(self, h: Hypothesis, current_bar: int) -> InvalidationResult:
        """Check if hypothesis has decayed too much."""
        if h.decay_factor < 0.1:
            return InvalidationResult(
                is_invalid=True,
                reason="decay_expired",
                details=f"decay_factor {h.decay_factor:.3f} < 0.1",
            )
        return InvalidationResult(is_invalid=False)
