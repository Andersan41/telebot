"""
tests/test_scenario_invalidator.py — Tests for Scenario Invalidator.

Covers:
    - Node alive ratio check
    - Critical node check
    - Invalidation level check
    - Decay check
"""
import sys
from pathlib import Path

import pytest

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from strategy.hypothesis import Hypothesis, ScenarioComponent
from strategy.scenario_invalidator import ScenarioInvalidator, InvalidationResult


# ── Helpers ────────────────────────────────────────────────────────

class MockNode:
    """Minimal mock for LiquidityNode."""
    def __init__(self, state="active", is_alive=True):
        self.state = state
        self.is_alive = is_alive
        self.state_score = 1.0 if is_alive else 0.0


class MockGraph:
    """Minimal mock for LiquidityGraph."""
    def __init__(self, nodes=None):
        self._nodes = nodes or {}

    def get_node(self, node_id):
        return self._nodes.get(node_id)


def _make_h(
    direction="buy",
    quality=50.0,
    confidence=0.5,
    decay=0.5,
    invalidation_price=98.0,
    node_ids=(),
    components=(),
):
    return Hypothesis(
        id="h1",
        direction=direction,
        narrative_type="test",
        name="test",
        description="test",
        quality=quality,
        confidence=confidence,
        decay_factor=decay,
        entry_price=100.0,
        invalidation_price=invalidation_price,
        target_price=105.0,
        rr_ratio=2.5,
        node_ids=node_ids,
        components=components,
        created_at_bar=0,
        current_bar=10,
    )


# ── Tests ──────────────────────────────────────────────────────────

class TestScenarioInvalidator:
    def test_valid_hypothesis(self):
        invalidator = ScenarioInvalidator()
        h = _make_h()
        graph = MockGraph()
        result = invalidator.invalidate(h, graph, current_price=100.0, current_bar=10)
        assert result.is_invalid is False

    def test_invalidation_level_breach_buy(self):
        invalidator = ScenarioInvalidator()
        h = _make_h(direction="buy", invalidation_price=98.0)
        graph = MockGraph()
        # Price below invalidation
        result = invalidator.invalidate(h, graph, current_price=97.0, current_bar=10)
        assert result.is_invalid is True
        assert result.reason == "invalidation_breached"

    def test_invalidation_level_breach_sell(self):
        invalidator = ScenarioInvalidator()
        h = _make_h(direction="sell", invalidation_price=102.0)
        graph = MockGraph()
        # Price above invalidation
        result = invalidator.invalidate(h, graph, current_price=103.0, current_bar=10)
        assert result.is_invalid is True
        assert result.reason == "invalidation_breached"

    def test_price_safe_buy(self):
        invalidator = ScenarioInvalidator()
        h = _make_h(direction="buy", invalidation_price=98.0)
        graph = MockGraph()
        result = invalidator.invalidate(h, graph, current_price=99.0, current_bar=10)
        assert result.is_invalid is False

    def test_price_safe_sell(self):
        invalidator = ScenarioInvalidator()
        h = _make_h(direction="sell", invalidation_price=102.0)
        graph = MockGraph()
        result = invalidator.invalidate(h, graph, current_price=101.0, current_bar=10)
        assert result.is_invalid is False

    def test_decay_expired(self):
        invalidator = ScenarioInvalidator()
        h = _make_h(decay=0.05)
        graph = MockGraph()
        result = invalidator.invalidate(h, graph, current_price=100.0, current_bar=10)
        assert result.is_invalid is True
        assert result.reason == "decay_expired"

    def test_node_alive_ratio_low(self):
        invalidator = ScenarioInvalidator()
        comp = ScenarioComponent(
            id="c1", type="ob", description="test", node_id="n1",
        )
        h = _make_h(node_ids=("n1", "n2", "n3"), components=(comp,))
        graph = MockGraph({
            "n1": MockNode(state="mitigated", is_alive=False),
            "n2": MockNode(state="mitigated", is_alive=False),
            "n3": MockNode(state="active", is_alive=True),
        })
        result = invalidator.invalidate(h, graph, current_price=100.0, current_bar=10)
        assert result.is_invalid is True
        assert result.reason == "node_degraded"

    def test_critical_node_dead(self):
        invalidator = ScenarioInvalidator(min_critical_alive=True)
        comp = ScenarioComponent(
            id="c1", type="ob", description="test",
            node_id="n1", is_critical=True,
        )
        h = _make_h(node_ids=("n1",), components=(comp,))
        graph = MockGraph({
            "n1": MockNode(state="mitigated", is_alive=False),
        })
        result = invalidator.invalidate(h, graph, current_price=100.0, current_bar=10)
        assert result.is_invalid is True
        # Either node_degraded or critical_node_dead is acceptable
        assert result.reason in ("node_degraded", "critical_node_dead")

    def test_critical_node_alive(self):
        invalidator = ScenarioInvalidator(min_critical_alive=True)
        comp = ScenarioComponent(
            id="c1", type="ob", description="test",
            node_id="n1", is_critical=True,
        )
        h = _make_h(node_ids=("n1",), components=(comp,))
        graph = MockGraph({
            "n1": MockNode(state="active", is_alive=True),
        })
        result = invalidator.invalidate(h, graph, current_price=100.0, current_bar=10)
        assert result.is_invalid is False

    def test_no_nodes_no_crash(self):
        invalidator = ScenarioInvalidator()
        h = _make_h(node_ids=(), components=())
        graph = MockGraph()
        result = invalidator.invalidate(h, graph, current_price=100.0, current_bar=10)
        assert result.is_invalid is False
