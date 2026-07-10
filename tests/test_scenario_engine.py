import sys
from pathlib import Path
from dataclasses import dataclass, field

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.scenario_engine import (
    ScenarioEngine, MarketScenario, ScenarioComponent, ScenarioEvaluation,
)
from strategy.market_thesis_engine import (
    LiquidityNode, LiquidityGraph,
    NODE_STATE_ACTIVE, NODE_STATE_TESTED, NODE_STATE_CREATED,
)


class TestMarketScenario:
    """Tests for immutable MarketScenario."""

    def test_frozen(self):
        scenario = MarketScenario(
            id="test_1",
            direction="buy",
            name="Sweep+BOS+OB",
            description="Test scenario",
            components=tuple(),
            entry_zone=(100.0, 101.0),
            invalidation_price=99.0,
            target_price=105.0,
            rr_ratio=2.0,
        )
        with pytest.raises(AttributeError):
            scenario.id = "changed"

    def test_components_count(self):
        components = (
            ScenarioComponent(id="1", type="sweep", description="sweep"),
            ScenarioComponent(id="2", type="bos", description="bos"),
        )
        scenario = MarketScenario(
            id="test_1", direction="buy", name="test",
            description="test", components=components,
            entry_zone=(100, 101), invalidation_price=99,
            target_price=105, rr_ratio=2.0,
        )
        assert scenario.components_count == 2

    def test_critical_components(self):
        components = (
            ScenarioComponent(id="1", type="sweep", description="sweep", is_critical=True),
            ScenarioComponent(id="2", type="ob", description="ob", is_critical=True),
            ScenarioComponent(id="3", type="fvg", description="fvg", is_critical=False),
        )
        scenario = MarketScenario(
            id="test_1", direction="buy", name="test",
            description="test", components=components,
            entry_zone=(100, 101), invalidation_price=99,
            target_price=105, rr_ratio=2.0,
        )
        assert scenario.critical_components == 2


class TestScenarioEvaluation:
    """Tests for mutable ScenarioEvaluation."""

    def test_quality_label(self):
        e = ScenarioEvaluation(scenario_id="test")
        e.probability = 0.70
        assert e.quality_label == "strong"

        e.probability = 0.55
        assert e.quality_label == "moderate"

        e.probability = 0.30
        assert e.quality_label == "weak"

    def test_mutable(self):
        e = ScenarioEvaluation(scenario_id="test")
        e.probability = 0.65
        assert e.probability == 0.65
        e.probability = 0.80
        assert e.probability == 0.80


class TestScenarioEngine:
    """Tests for ScenarioEngine."""

    def setup_method(self):
        self.engine = ScenarioEngine()

    def _make_node(self, ntype, price, state=NODE_STATE_ACTIVE, created_at=0):
        node = LiquidityNode(type=ntype, price=price, state=state)
        node.created_at = created_at
        node.state = state
        return node

    def test_no_nodes_returns_empty(self):
        graph = LiquidityGraph()
        scenarios = self.engine.detect_scenarios(graph)
        assert scenarios == []

    def test_single_ob_creates_ob_retest_scenario(self):
        graph = LiquidityGraph()
        node = self._make_node("ob", 100.0, state=NODE_STATE_TESTED, created_at=0)
        graph.add_node(node)

        scenarios = self.engine.detect_scenarios(graph, direction="buy")
        names = [s.name for s in scenarios]
        assert "OB Retest" in names

    def test_sweep_bos_ob_scenario(self):
        graph = LiquidityGraph()
        sweep = self._make_node("sweep", 95.0, created_at=0)
        bos = self._make_node("bos", 96.0, created_at=1)
        ob = self._make_node("ob", 97.0, created_at=2)

        for n in [sweep, bos, ob]:
            n.state = NODE_STATE_ACTIVE
            graph.add_node(n)

        scenarios = self.engine.detect_scenarios(graph, direction="buy")
        names = [s.name for s in scenarios]
        assert "Sweep+BOS+OB" in names

    def test_scenario_is_immutable(self):
        graph = LiquidityGraph()
        node = self._make_node("ob", 100.0, state=NODE_STATE_TESTED, created_at=0)
        graph.add_node(node)

        scenarios = self.engine.detect_scenarios(graph, direction="buy")
        assert len(scenarios) > 0
        scenario = scenarios[0]
        with pytest.raises(AttributeError):
            scenario.id = "changed"

    def test_direction_filter(self):
        graph = LiquidityGraph()
        # Bullish nodes only
        ob_bull = self._make_node("ob", 100.0, state=NODE_STATE_TESTED, created_at=0)
        ob_bull.source = type("", (), {"type": "bullish"})()
        graph.add_node(ob_bull)

        buy_scenarios = self.engine.detect_scenarios(graph, direction="buy")
        sell_scenarios = self.engine.detect_scenarios(graph, direction="sell")

        # Only buy scenarios should exist for bullish OB
        for s in buy_scenarios:
            assert s.direction == "buy"

    def test_components_are_tuple(self):
        graph = LiquidityGraph()
        node = self._make_node("ob", 100.0, state=NODE_STATE_TESTED, created_at=0)
        graph.add_node(node)

        scenarios = self.engine.detect_scenarios(graph, direction="buy")
        for s in scenarios:
            assert isinstance(s.components, tuple)
