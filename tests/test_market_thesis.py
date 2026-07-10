import sys
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.weights import weighted_score, normalize, OB_FROM_BOS, OB_DISPLACEMENT
from strategy.market_thesis_engine import (
    MarketThesisEngine, LiquidityNode, LiquidityGraph,
    LiquidityPath, LiquidityPathNode, MarketThesis, TradeOpportunity,
    Scenario, ScenarioScore, Edge, HeuristicTransitionModel,
    market_thesis_engine, _node_id,
)


# ══════════════════════════════════════════════════════════════════
# Mock objects
# ══════════════════════════════════════════════════════════════════

@dataclass
class MockBOS:
    type: str = "bullish"
    level: float = 50000.0
    timestamp: datetime = None
    candle_index: int = 10


@dataclass
class MockCHoCH:
    type: str = "bullish"
    level: float = 49000.0
    timestamp: datetime = None
    candle_index: int = 5


@dataclass
class MockStructure:
    trend: str = "bullish"
    last_bos: object = None
    last_choch: object = None
    recent_highs: list = None
    recent_lows: list = None
    swing_points: list = None

    def __post_init__(self):
        if self.recent_highs is None:
            self.recent_highs = []
        if self.recent_lows is None:
            self.recent_lows = []
        if self.swing_points is None:
            self.swing_points = []


@dataclass
class MockSwingPoint:
    price: float = 50000.0
    type: str = "low"
    timestamp: datetime = None


@dataclass
class MockSweep:
    type: str = "bullish"
    is_valid: bool = True
    strength: float = 0.75
    reclaim_candles: int = 2
    swept_level: float = 50000.0
    sweep_low: float = 49500.0
    sweep_high: float = 50200.0
    volume_ratio: float = 2.0
    displacement_after: float = 1.5
    timestamp: datetime = None


@dataclass
class MockOB:
    type: str = "bullish"
    high: float = 50200.0
    low: float = 49800.0
    midpoint: float = 50000.0
    is_valid: bool = True
    has_bos: bool = True
    displacement_atr: float = 2.0
    volume_ratio: float = 2.0
    mitigated: bool = False
    timestamp: datetime = None


@dataclass
class MockFVG:
    type: str = "bearish"
    top: float = 51000.0
    bottom: float = 50500.0
    is_active: bool = True
    filled: bool = False
    size_pct: float = 1.0
    timestamp: datetime = None


@dataclass
class MockEqualLevel:
    type: str = "equal_high"
    level: float = 52000.0
    strength: float = 0.7
    swept: bool = False


@dataclass
class MockExternalLiquidity:
    type: str = "old_high"
    level: float = 53000.0
    strength: float = 0.6
    swept: bool = False


@dataclass
class MockCandleQuality:
    is_displacement: bool = True
    body_pct: float = 0.75
    body_atr_ratio: float = 1.5
    quality_score: float = 70.0


# ══════════════════════════════════════════════════════════════════
# Weights Tests
# ══════════════════════════════════════════════════════════════════

class TestWeights:
    def test_weighted_score_basic(self):
        features = {"has_bos": 1.0, "volume": 0.8}
        weights = {"has_bos": 1.0, "volume": 0.5}
        score = weighted_score(features, weights)
        assert 90.0 <= score <= 95.0

    def test_weighted_score_empty(self):
        assert weighted_score({}, {}) == 0.0

    def test_weighted_score_zero_weights(self):
        features = {"has_bos": 1.0}
        weights = {"has_bos": 0.0}
        assert weighted_score(features, weights) == 0.0

    def test_weighted_score_clamps_values(self):
        features = {"x": 2.0}
        weights = {"x": 1.0}
        score = weighted_score(features, weights)
        assert score == 100.0

    def test_weighted_score_negative_values_clamped(self):
        features = {"x": -0.5}
        weights = {"x": 1.0}
        score = weighted_score(features, weights)
        assert score == 0.0

    def test_normalize_basic(self):
        assert normalize(50, 0, 100) == 0.5
        assert normalize(0, 0, 100) == 0.0
        assert normalize(100, 0, 100) == 1.0

    def test_normalize_clamps(self):
        assert normalize(150, 0, 100) == 1.0
        assert normalize(-10, 0, 100) == 0.0

    def test_normalize_zero_range(self):
        assert normalize(5, 5, 5) == 0.0

    def test_weights_are_floats(self):
        from strategy import weights
        for attr in dir(weights):
            if attr.startswith("_") or attr.startswith("SCENARIO"):
                continue
            val = getattr(weights, attr)
            if isinstance(val, (int, float)):
                assert isinstance(val, float), f"{attr} should be float, got {type(val)}"


# ══════════════════════════════════════════════════════════════════
# Edge Tests
# ══════════════════════════════════════════════════════════════════

class TestEdge:
    def test_edge_creation(self):
        edge = Edge(
            source_id="sweep_49000.000000",
            target_id="bos_49100.000000",
            type="causes",
            strength=0.8,
            transition_probability=0.75,
        )
        assert edge.source_id == "sweep_49000.000000"
        assert edge.type == "causes"
        assert edge.strength == 0.8
        assert edge.transition_probability == 0.75

    def test_edge_repr(self):
        edge = Edge(
            source_id="a", target_id="b",
            type="causes", strength=0.5, transition_probability=0.6,
        )
        r = repr(edge)
        assert "causes" in r
        assert "0.50" in r
        assert "0.60" in r

    def test_edge_metadata(self):
        edge = Edge(
            source_id="a", target_id="b",
            type="targets", metadata={"reason": "FVG targets old_high"},
        )
        assert edge.metadata["reason"] == "FVG targets old_high"


# ══════════════════════════════════════════════════════════════════
# LiquidityNode Tests
# ══════════════════════════════════════════════════════════════════

class TestLiquidityNode:
    def test_node_creation(self):
        node = LiquidityNode(type="ob", price=50000.0, strength=0.8)
        assert node.price == 50000.0
        assert node.strength == 0.8
        assert node.state == "created"  # default state in 6-state lifecycle

    def test_node_is_valid(self):
        node = LiquidityNode(type="ob", price=50000.0, state="active")
        assert node.is_valid is True

    def test_node_is_not_valid_when_mitigated(self):
        node = LiquidityNode(type="ob", price=50000.0, state="mitigated")
        assert node.is_valid is False

    def test_node_repr(self):
        node = LiquidityNode(type="ob", price=50000.0, quality_score=85.0)
        r = repr(node)
        assert "ob" in r
        assert "50000" in r

    def test_node_id(self):
        node = LiquidityNode(type="ob", price=50000.123456)
        nid = _node_id(node)
        assert nid == "ob_50000.123456"

    def test_node_add_edge(self):
        node = LiquidityNode(type="sweep", price=49000.0)
        target = LiquidityNode(type="bos", price=49100.0)
        edge = Edge(
            source_id=_node_id(node),
            target_id=_node_id(target),
            type="causes",
            strength=0.8,
            transition_probability=0.75,
        )
        node.add_edge(edge)
        assert len(node.edges) == 1
        assert _node_id(target) in node.creates  # backward compat synced

    def test_node_get_edges_filtered(self):
        node = LiquidityNode(type="sweep", price=49000.0)
        target1 = LiquidityNode(type="bos", price=49100.0)
        target2 = LiquidityNode(type="ob", price=49500.0)
        node.add_edge(Edge(
            source_id=_node_id(node), target_id=_node_id(target1),
            type="causes", strength=0.8,
        ))
        node.add_edge(Edge(
            source_id=_node_id(node), target_id=_node_id(target2),
            type="targets", strength=0.6,
        ))
        causes = node.get_edges("causes")
        targets = node.get_edges("targets")
        assert len(causes) == 1
        assert len(targets) == 1

    def test_node_backward_compat_created_by(self):
        node = LiquidityNode(type="ob", price=49500.0)
        node.created_by = "sweep_49000.000000"
        assert node.caused_by == "sweep_49000.000000"

    def test_node_backward_compat_creates(self):
        node = LiquidityNode(type="sweep", price=49000.0)
        node.causes = ["bos_49100.000000"]
        assert node.creates == ["bos_49100.000000"]


# ══════════════════════════════════════════════════════════════════
# LiquidityGraph Tests (DAG)
# ══════════════════════════════════════════════════════════════════

class TestLiquidityGraph:
    def test_graph_creation(self):
        graph = LiquidityGraph(current_price=50000.0)
        assert graph.current_price == 50000.0
        assert len(graph.nodes) == 0

    def test_graph_add_node(self):
        graph = LiquidityGraph(current_price=50000.0)
        node = LiquidityNode(type="ob", price=49500.0)
        graph.add_node(node)
        assert len(graph.nodes) == 1
        assert graph.get_node(_node_id(node)) is node

    def test_graph_add_edge(self):
        graph = LiquidityGraph(current_price=50000.0)
        n1 = LiquidityNode(type="sweep", price=49000.0)
        n2 = LiquidityNode(type="bos", price=49100.0)
        graph.add_node(n1)
        graph.add_node(n2)
        edge = graph.add_edge(n1, n2, "causes", strength=0.8, transition_probability=0.75)
        assert edge.type == "causes"
        assert edge.strength == 0.8
        assert len(n1.edges) == 1
        assert _node_id(n2) in n1.creates

    def test_graph_get_children(self):
        graph = LiquidityGraph(current_price=50000.0)
        n1 = LiquidityNode(type="sweep", price=49000.0)
        n2 = LiquidityNode(type="bos", price=49100.0)
        n3 = LiquidityNode(type="ob", price=49500.0)
        graph.add_node(n1)
        graph.add_node(n2)
        graph.add_node(n3)
        graph.add_edge(n1, n2, "causes")
        graph.add_edge(n1, n3, "targets")
        children = graph.get_children(n1)
        assert len(children) == 2
        causes_children = graph.get_children(n1, "causes")
        assert len(causes_children) == 1

    def test_graph_get_parents(self):
        graph = LiquidityGraph(current_price=50000.0)
        n1 = LiquidityNode(type="sweep", price=49000.0)
        n2 = LiquidityNode(type="bos", price=49100.0)
        graph.add_node(n1)
        graph.add_node(n2)
        graph.add_edge(n1, n2, "causes")
        parents = graph.get_parents(n2)
        assert len(parents) == 1
        assert parents[0] is n1

    def test_graph_get_roots(self):
        graph = LiquidityGraph(current_price=50000.0)
        n1 = LiquidityNode(type="sweep", price=49000.0)
        n2 = LiquidityNode(type="bos", price=49100.0)
        n3 = LiquidityNode(type="ob", price=49500.0)
        graph.add_node(n1)
        graph.add_node(n2)
        graph.add_node(n3)
        graph.add_edge(n1, n2, "causes")
        graph.add_edge(n2, n3, "causes")
        roots = graph.get_roots()
        assert len(roots) == 1
        assert roots[0] is n1

    def test_graph_topological_sort(self):
        graph = LiquidityGraph(current_price=50000.0)
        n1 = LiquidityNode(type="sweep", price=49000.0)
        n2 = LiquidityNode(type="bos", price=49100.0)
        n3 = LiquidityNode(type="ob", price=49500.0)
        graph.add_node(n3)
        graph.add_node(n1)
        graph.add_node(n2)
        graph.add_edge(n1, n2, "causes")
        graph.add_edge(n2, n3, "causes")
        sorted_nodes = graph.topological_sort()
        ids = [_node_id(n) for n in sorted_nodes]
        # DFS post-order: children first, then parents
        # So n3 (leaf) should come before n2, n2 before n1
        assert ids.index(_node_id(n3)) < ids.index(_node_id(n2))
        assert ids.index(_node_id(n2)) < ids.index(_node_id(n1))

    def test_nodes_above(self):
        graph = LiquidityGraph(current_price=50000.0)
        graph.nodes = [
            LiquidityNode(type="ob", price=51000.0),
            LiquidityNode(type="ob", price=49000.0),
            LiquidityNode(type="fvg", price=52000.0, state="mitigated"),
        ]
        above = graph.nodes_above()
        assert len(above) == 1
        assert above[0].price == 51000.0

    def test_nodes_below(self):
        graph = LiquidityGraph(current_price=50000.0)
        graph.nodes = [
            LiquidityNode(type="ob", price=51000.0),
            LiquidityNode(type="ob", price=49000.0),
            LiquidityNode(type="swing_low", price=48000.0),
        ]
        below = graph.nodes_below()
        assert len(below) == 2
        assert below[0].price == 49000.0

    def test_bullish_nodes(self):
        graph = LiquidityGraph()
        graph.nodes = [
            LiquidityNode(type="ob", price=50000.0),
            LiquidityNode(type="fvg", price=51000.0),
            LiquidityNode(type="equal_high", price=52000.0),
        ]
        bullish = graph.bullish_nodes()
        assert len(bullish) >= 1

    def test_bearish_nodes(self):
        graph = LiquidityGraph()
        graph.nodes = [
            LiquidityNode(type="equal_high", price=52000.0),
            LiquidityNode(type="old_high", price=53000.0),
            LiquidityNode(type="ob", price=50000.0),
        ]
        bearish = graph.bearish_nodes()
        assert len(bearish) >= 1


# ══════════════════════════════════════════════════════════════════
# ScenarioScore Tests
# ══════════════════════════════════════════════════════════════════

class TestScenarioScore:
    def test_scenario_score_creation(self):
        score = ScenarioScore(
            ob_contribution=20.0,
            sweep_contribution=15.0,
            bos_contribution=10.0,
            fvg_contribution=8.0,
            liquidity_contribution=12.0,
            htf_contribution=5.0,
        )
        assert score.total == 70.0

    def test_scenario_score_total_clamped(self):
        score = ScenarioScore(
            ob_contribution=50.0,
            sweep_contribution=50.0,
            bos_contribution=50.0,
        )
        assert score.total == 100.0  # clamped

    def test_scenario_score_breakdown(self):
        score = ScenarioScore(
            ob_contribution=20.0,
            sweep_contribution=15.0,
            bos_contribution=10.0,
            fvg_contribution=8.0,
            liquidity_contribution=12.0,
            htf_contribution=5.0,
        )
        bd = score.breakdown()
        assert bd["ob"] == 20.0
        assert bd["sweep"] == 15.0
        assert bd["total"] == 70.0
        assert len(bd) == 7

    def test_scenario_score_repr(self):
        score = ScenarioScore(ob_contribution=20.0, sweep_contribution=15.0)
        r = repr(score)
        assert "OB=20.0" in r
        assert "Sweep=15.0" in r

    def test_scenario_score_empty(self):
        score = ScenarioScore()
        assert score.total == 0.0


# ══════════════════════════════════════════════════════════════════
# LiquidityPath Tests
# ══════════════════════════════════════════════════════════════════

class TestLiquidityPath:
    def test_path_is_complete(self):
        path = LiquidityPath(
            direction="buy",
            nodes=[
                LiquidityPathNode(
                    node=LiquidityNode(type="sweep", price=49000.0),
                    role="trigger",
                ),
                LiquidityPathNode(
                    node=LiquidityNode(type="ob", price=49500.0),
                    role="confirmation",
                ),
                LiquidityPathNode(
                    node=LiquidityNode(type="old_high", price=52000.0),
                    role="target",
                ),
            ],
        )
        assert path.is_complete is True

    def test_path_is_incomplete_no_target(self):
        path = LiquidityPath(
            direction="buy",
            nodes=[
                LiquidityPathNode(
                    node=LiquidityNode(type="sweep", price=49000.0),
                    role="trigger",
                ),
            ],
        )
        assert path.is_complete is False

    def test_path_format(self):
        path = LiquidityPath(
            direction="buy",
            nodes=[
                LiquidityPathNode(
                    node=LiquidityNode(type="sweep", price=49000.0),
                    role="trigger",
                    reason="sweep initiates",
                ),
                LiquidityPathNode(
                    node=LiquidityNode(type="ob", price=49500.0),
                    role="confirmation",
                ),
            ],
        )
        fmt = path.format()
        assert "BUY" in fmt
        assert "sweep" in fmt
        assert "49000" in fmt


# ══════════════════════════════════════════════════════════════════
# MarketThesisEngine Tests
# ══════════════════════════════════════════════════════════════════

class TestMarketThesisEngine:
    def test_singleton_exists(self):
        assert market_thesis_engine is not None
        assert isinstance(market_thesis_engine, MarketThesisEngine)

    def test_build_liquidity_graph_empty(self):
        graph = market_thesis_engine.build_liquidity_graph(
            current_price=50000.0,
        )
        assert isinstance(graph, LiquidityGraph)
        assert graph.current_price == 50000.0

    def test_build_liquidity_graph_with_obs(self):
        obs = [MockOB(type="bullish", midpoint=49500.0)]
        graph = market_thesis_engine.build_liquidity_graph(
            current_price=50000.0,
            order_blocks=obs,
        )
        ob_nodes = [n for n in graph.nodes if n.type == "ob"]
        assert len(ob_nodes) == 1
        assert ob_nodes[0].price == 49500.0

    def test_build_liquidity_graph_with_fvgs(self):
        fvgs = [MockFVG(type="bearish", top=51000.0, bottom=50500.0)]
        graph = market_thesis_engine.build_liquidity_graph(
            current_price=50000.0,
            fvgs=fvgs,
        )
        fvg_nodes = [n for n in graph.nodes if n.type == "fvg"]
        assert len(fvg_nodes) == 1
        assert fvg_nodes[0].price == 50750.0

    def test_build_liquidity_graph_with_structure(self):
        structure = MockStructure(
            last_bos=MockBOS(type="bullish", level=48000.0),
            swing_points=[MockSwingPoint(price=47500.0, type="low")],
        )
        graph = market_thesis_engine.build_liquidity_graph(
            current_price=50000.0,
            structure=structure,
        )
        bos_nodes = [n for n in graph.nodes if n.type == "bos"]
        swing_nodes = [n for n in graph.nodes if "swing" in n.type]
        assert len(bos_nodes) == 1
        assert len(swing_nodes) == 1

    def test_build_liquidity_graph_with_equal_levels(self):
        eq = [MockEqualLevel(type="equal_high", level=52000.0, strength=0.7)]
        graph = market_thesis_engine.build_liquidity_graph(
            current_price=50000.0,
            equal_levels=eq,
        )
        eq_nodes = [n for n in graph.nodes if n.type == "equal_high"]
        assert len(eq_nodes) == 1

    def test_build_liquidity_graph_with_external(self):
        ext = [MockExternalLiquidity(type="old_high", level=53000.0, strength=0.6)]
        graph = market_thesis_engine.build_liquidity_graph(
            current_price=50000.0,
            external_levels=ext,
        )
        ext_nodes = [n for n in graph.nodes if n.type == "old_high"]
        assert len(ext_nodes) == 1

    def test_build_liquidity_graph_creates_edges(self):
        sweeps = [MockSweep(type="bullish", swept_level=49000.0)]
        structure = MockStructure(
            last_bos=MockBOS(type="bullish", level=49200.0),
        )
        graph = market_thesis_engine.build_liquidity_graph(
            current_price=50000.0,
            sweeps=sweeps,
            structure=structure,
        )
        # Should have edges from sweep to bos
        sweep_nodes = [n for n in graph.nodes if n.type == "sweep"]
        assert len(sweep_nodes) == 1
        assert len(sweep_nodes[0].edges) > 0

    def test_detect_scenarios_empty_graph(self):
        graph = LiquidityGraph(current_price=50000.0)
        scenarios = market_thesis_engine.detect_scenarios(graph, direction="buy")
        assert isinstance(scenarios, list)

    def test_detect_scenarios_with_obs_and_targets(self):
        sweeps = [MockSweep(type="bullish", swept_level=49000.0)]
        structure = MockStructure(
            last_bos=MockBOS(type="bullish", level=49200.0),
        )
        obs = [MockOB(type="bullish", midpoint=49500.0, displacement_atr=2.0)]
        ext = [MockExternalLiquidity(type="old_high", level=53000.0)]
        graph = market_thesis_engine.build_liquidity_graph(
            current_price=50000.0,
            sweeps=sweeps,
            order_blocks=obs,
            external_levels=ext,
            structure=structure,
        )
        scenarios = market_thesis_engine.detect_scenarios(graph, direction="buy")
        assert len(scenarios) >= 1
        assert scenarios[0].direction == "buy"

    def test_score_scenario(self):
        chain = [
            LiquidityNode(type="sweep", price=49000.0, strength=0.8, quality_score=70.0),
            LiquidityNode(type="ob", price=49500.0, strength=0.7, quality_score=80.0),
            LiquidityNode(type="fvg", price=49800.0, strength=0.5, quality_score=60.0),
            LiquidityNode(type="old_high", price=53000.0, strength=0.6, quality_score=75.0),
        ]
        graph = LiquidityGraph(current_price=50000.0)
        score = market_thesis_engine._score_scenario_breakdown(chain, graph, direction="buy")
        assert isinstance(score, ScenarioScore)
        assert 0 <= score.total <= 100
        assert score.total > 0

    def test_find_best_invalidation_buy(self):
        graph = LiquidityGraph(current_price=50000.0)
        graph.nodes = [
            LiquidityNode(type="swing_low", price=49000.0, quality_score=60.0),
            LiquidityNode(type="ob", price=49500.0, quality_score=80.0),
            LiquidityNode(type="bos", price=48000.0, quality_score=50.0),
        ]
        best = market_thesis_engine.find_best_invalidation(
            graph, direction="buy", entry_price=50000.0, atr=200.0,
        )
        assert best is not None
        assert best.price < 50000.0

    def test_find_best_invalidation_sell(self):
        graph = LiquidityGraph(current_price=50000.0)
        graph.nodes = [
            LiquidityNode(type="swing_high", price=51000.0, quality_score=60.0),
            LiquidityNode(type="ob", price=50500.0, quality_score=80.0),
            LiquidityNode(type="bos", price=52000.0, quality_score=50.0),
        ]
        best = market_thesis_engine.find_best_invalidation(
            graph, direction="sell", entry_price=50000.0, atr=200.0,
        )
        assert best is not None
        assert best.price > 50000.0

    def test_find_best_target_buy(self):
        graph = LiquidityGraph(current_price=50000.0)
        graph.nodes = [
            LiquidityNode(type="old_high", price=53000.0, quality_score=70.0),
            LiquidityNode(type="equal_high", price=52000.0, quality_score=65.0),
            LiquidityNode(type="fvg", price=51000.0, quality_score=50.0),
        ]
        best = market_thesis_engine.find_best_target(
            graph, direction="buy", entry_price=50000.0, atr=200.0,
            invalidation_price=49500.0,
        )
        assert best is not None
        assert best.price > 50000.0

    def test_find_best_target_sell(self):
        graph = LiquidityGraph(current_price=50000.0)
        graph.nodes = [
            LiquidityNode(type="old_low", price=47000.0, quality_score=70.0),
            LiquidityNode(type="equal_low", price=48000.0, quality_score=65.0),
            LiquidityNode(type="fvg", price=49000.0, quality_score=50.0),
        ]
        best = market_thesis_engine.find_best_target(
            graph, direction="sell", entry_price=50000.0, atr=200.0,
            invalidation_price=50500.0,
        )
        assert best is not None
        assert best.price < 50000.0

    def test_evaluate_trade_opportunity_no_graph(self):
        graph = LiquidityGraph(current_price=50000.0)
        opp = market_thesis_engine.evaluate_trade_opportunity(
            graph=graph, direction="buy", entry_price=50000.0,
            atr=200.0, symbol="BTC/USDT", timeframe="1h",
        )
        if opp is not None:
            assert isinstance(opp, TradeOpportunity)

    def test_evaluate_trade_opportunity_with_data(self):
        obs = [MockOB(type="bullish", midpoint=49500.0, displacement_atr=2.0)]
        ext = [MockExternalLiquidity(type="old_high", level=53000.0)]
        structure = MockStructure(
            last_bos=MockBOS(type="bullish", level=48000.0),
            swing_points=[MockSwingPoint(price=47500.0, type="low")],
        )
        graph = market_thesis_engine.build_liquidity_graph(
            current_price=50000.0,
            order_blocks=obs,
            external_levels=ext,
            structure=structure,
        )
        opp = market_thesis_engine.evaluate_trade_opportunity(
            graph=graph, direction="buy", entry_price=50000.0,
            atr=200.0, symbol="BTC/USDT", timeframe="1h",
        )
        if opp is not None:
            assert opp.direction == "buy"
            assert opp.symbol == "BTC/USDT"
            assert opp.scenario_score > 0

    def test_infer_relationships(self):
        sweep = LiquidityNode(type="sweep", price=49000.0)
        bos = LiquidityNode(type="bos", price=49100.0)
        ob = LiquidityNode(type="ob", price=49500.0)
        graph = LiquidityGraph(current_price=50000.0)
        graph.add_node(sweep)
        graph.add_node(bos)
        graph.add_node(ob)
        market_thesis_engine._infer_edges(graph)
        assert len(sweep.edges) > 0 or len(bos.edges) > 0


# ══════════════════════════════════════════════════════════════════
# Scenario Tests
# ══════════════════════════════════════════════════════════════════

class TestScenario:
    def test_scenario_creation(self):
        thesis = MarketThesis(
            direction="buy",
            scenario="Sweep → OB → External",
            components=["sweep", "ob", "old_high"],
            scenario_score=82.0,
            confidence=94.0,
        )
        scenario = Scenario(
            direction="buy",
            symbol="BTC/USDT",
            timeframe="1h",
            thesis=thesis,
            score_breakdown=ScenarioScore(
                ob_contribution=20.0,
                sweep_contribution=15.0,
                liquidity_contribution=12.0,
            ),
            explanation="Test scenario",
            alternative_rank=0,
            entry_price=50000.0,
            invalidation_price=49500.0,
            target_price=53000.0,
            expected_rr=4.0,
        )
        assert scenario.score == 82.0
        assert scenario.confidence == 94.0
        assert scenario.quality_confidence_ratio == 77.08
        assert scenario.alternative_rank == 0

    def test_scenario_format_explanation(self):
        thesis = MarketThesis(
            direction="buy",
            scenario="Sweep → OB → External",
            components=["sweep", "ob", "old_high"],
            scenario_score=82.0,
            confidence=94.0,
        )
        scenario = Scenario(
            direction="buy",
            symbol="BTC/USDT",
            timeframe="1h",
            thesis=thesis,
            score_breakdown=ScenarioScore(ob_contribution=20.0),
            entry_price=50000.0,
            invalidation_price=49500.0,
            target_price=53000.0,
            expected_rr=4.0,
        )
        explanation = scenario.format_explanation()
        assert "BUY" in explanation
        assert "BTC/USDT" in explanation
        assert "82.0" in explanation
        assert "94" in explanation

    def test_scenario_quality_confidence_ratio(self):
        # Scenario A: score=82, conf=94 → ratio=77.1
        a_thesis = MarketThesis(
            direction="buy", scenario="a", components=[],
            scenario_score=82.0, confidence=94.0,
        )
        a = Scenario(
            direction="buy", symbol="X", timeframe="1h",
            thesis=a_thesis,
        )
        # Scenario B: score=90, conf=37 → ratio=33.3
        b_thesis = MarketThesis(
            direction="buy", scenario="b", components=[],
            scenario_score=90.0, confidence=37.0,
        )
        b = Scenario(
            direction="buy", symbol="X", timeframe="1h",
            thesis=b_thesis,
        )
        assert a.quality_confidence_ratio > b.quality_confidence_ratio

    def test_evaluate_scenarios(self):
        obs = [MockOB(type="bullish", midpoint=49500.0, displacement_atr=2.0)]
        ext = [MockExternalLiquidity(type="old_high", level=53000.0)]
        structure = MockStructure(
            last_bos=MockBOS(type="bullish", level=48000.0),
            swing_points=[MockSwingPoint(price=47500.0, type="low")],
        )
        graph = market_thesis_engine.build_liquidity_graph(
            current_price=50000.0,
            order_blocks=obs,
            external_levels=ext,
            structure=structure,
        )
        scenarios = market_thesis_engine.evaluate_scenarios(
            graph=graph, direction="buy", entry_price=50000.0,
            atr=200.0, symbol="BTC/USDT", timeframe="1h",
        )
        assert isinstance(scenarios, list)
        if scenarios:
            assert isinstance(scenarios[0], Scenario)
            assert scenarios[0].direction == "buy"
            # Should be sorted by quality_confidence_ratio
            for i in range(len(scenarios) - 1):
                assert (
                    scenarios[i].quality_confidence_ratio >=
                    scenarios[i + 1].quality_confidence_ratio
                )

    def test_evaluate_scenarios_empty_graph(self):
        graph = LiquidityGraph(current_price=50000.0)
        scenarios = market_thesis_engine.evaluate_scenarios(
            graph=graph, direction="buy", entry_price=50000.0,
            atr=200.0, symbol="BTC/USDT", timeframe="1h",
        )
        assert scenarios == []


# ══════════════════════════════════════════════════════════════════
# TradeOpportunity Tests (backward compat)
# ══════════════════════════════════════════════════════════════════

class TestTradeOpportunity:
    def test_expected_rr_buy(self):
        thesis = MarketThesis(
            direction="buy",
            scenario="test",
            components=["sweep", "ob"],
            entry_zone=(49900.0, 50100.0),
        )
        opp = TradeOpportunity(
            direction="buy",
            symbol="BTC/USDT",
            timeframe="1h",
            thesis=thesis,
            invalidation=49500.0,
            expected_target=52000.0,
        )
        assert opp.expected_rr == 4.0

    def test_expected_rr_sell(self):
        thesis = MarketThesis(
            direction="sell",
            scenario="test",
            components=["sweep", "ob"],
            entry_zone=(49900.0, 50100.0),
        )
        opp = TradeOpportunity(
            direction="sell",
            symbol="BTC/USDT",
            timeframe="1h",
            thesis=thesis,
            invalidation=50500.0,
            expected_target=48000.0,
        )
        assert opp.expected_rr == 4.0

    def test_expected_rr_zero_when_no_invalidation(self):
        thesis = MarketThesis(
            direction="buy", scenario="test", components=[],
            entry_zone=(50000.0, 50000.0),
        )
        opp = TradeOpportunity(
            direction="buy", symbol="X", timeframe="1h",
            thesis=thesis, invalidation=0, expected_target=52000.0,
        )
        assert opp.expected_rr == 0.0

    def test_from_scenario(self):
        thesis = MarketThesis(
            direction="buy",
            scenario="test",
            components=["sweep", "ob"],
            entry_zone=(49900.0, 50100.0),
            scenario_score=82.0,
            confidence=94.0,
        )
        scenario = Scenario(
            direction="buy",
            symbol="BTC/USDT",
            timeframe="1h",
            thesis=thesis,
            entry_price=50000.0,
            invalidation_price=49500.0,
            target_price=52000.0,
        )
        opp = TradeOpportunity.from_scenario(scenario)
        assert opp.direction == "buy"
        assert opp.scenario_score == 82.0
        assert opp.expected_target == 52000.0
        assert opp.invalidation == 49500.0


# ══════════════════════════════════════════════════════════════════
# TradePlan with MarketThesis integration
# ══════════════════════════════════════════════════════════════════

class TestTradePlanIntegration:
    def test_trade_plan_has_thesis_fields(self):
        from strategy.trade_plan import TradePlan
        plan = TradePlan(
            direction="buy",
            symbol="BTC/USDT",
            timeframe="1h",
            entry_price=50000.0,
        )
        assert plan.market_thesis is None
        assert plan.liquidity_path is None
        assert plan.scenario_score == 0.0
        assert plan.thesis_source == ""

    def test_trade_plan_with_thesis(self):
        from strategy.trade_plan import TradePlan
        thesis = MarketThesis(
            direction="buy",
            scenario="Sweep → OB → FVG → External",
            components=["sweep", "ob", "fvg", "old_high"],
            scenario_score=85.0,
        )
        path = LiquidityPath(
            direction="buy",
            nodes=[
                LiquidityPathNode(
                    node=LiquidityNode(type="sweep", price=49000.0),
                    role="trigger",
                ),
            ],
        )
        plan = TradePlan(
            direction="buy",
            symbol="BTC/USDT",
            timeframe="1h",
            entry_price=50000.0,
            market_thesis=thesis,
            liquidity_path=path,
            scenario_score=85.0,
            thesis_source="market_thesis",
        )
        assert plan.scenario_score == 85.0
        assert plan.thesis_source == "market_thesis"
        summary = plan.format_summary()
        assert "Thesis:" in summary
        assert "85" in summary


# ══════════════════════════════════════════════════════════════════
# Scenario Validator Tests
# ══════════════════════════════════════════════════════════════════

from strategy.market_thesis_engine import validate_scenario


class TestScenarioValidator:
    def test_valid_buy_chain(self):
        is_valid, reason = validate_scenario(
            ["sweep", "bos", "ob", "fvg", "old_high"], "buy"
        )
        assert is_valid is True

    def test_valid_sell_chain(self):
        is_valid, reason = validate_scenario(
            ["sweep", "bos", "ob", "old_low"], "sell"
        )
        assert is_valid is True

    def test_reject_no_trigger(self):
        is_valid, reason = validate_scenario(
            ["ob", "fvg", "old_high"], "buy"
        )
        assert is_valid is False
        assert "trigger" in reason

    def test_reject_no_confirmation(self):
        is_valid, reason = validate_scenario(
            ["sweep", "old_high"], "buy"
        )
        assert is_valid is False
        assert "confirmation" in reason

    def test_reject_no_target(self):
        is_valid, reason = validate_scenario(
            ["sweep", "bos", "ob"], "buy"
        )
        assert is_valid is False
        assert "target" in reason

    def test_reject_too_few(self):
        is_valid, reason = validate_scenario(["sweep"], "buy")
        assert is_valid is False

    def test_reject_trigger_after_confirmation(self):
        is_valid, reason = validate_scenario(
            ["ob", "sweep", "old_high"], "buy"
        )
        assert is_valid is False
        assert "order" in reason

    def test_reject_bearish_target_in_buy(self):
        is_valid, reason = validate_scenario(
            ["sweep", "ob", "old_low"], "buy"
        )
        assert is_valid is False
        assert "bearish" in reason

    def test_reject_bullish_target_in_sell(self):
        is_valid, reason = validate_scenario(
            ["sweep", "ob", "old_high"], "sell"
        )
        assert is_valid is False
        assert "bullish" in reason

    def test_valid_minimal_buy(self):
        is_valid, _ = validate_scenario(
            ["sweep", "ob", "old_high"], "buy"
        )
        assert is_valid is True

    def test_valid_bos_based(self):
        is_valid, _ = validate_scenario(
            ["bos", "ob", "fvg", "old_high"], "buy"
        )
        assert is_valid is True


# ══════════════════════════════════════════════════════════════════
# Confidence Tests
# ══════════════════════════════════════════════════════════════════

class TestConfidence:
    def test_thesis_has_confidence(self):
        thesis = MarketThesis(
            direction="buy",
            scenario="test",
            components=["sweep", "bos", "ob"],
            scenario_score=80.0,
            confidence=70.0,
        )
        assert thesis.confidence == 70.0

    def test_quality_confidence_ratio(self):
        a = MarketThesis(
            direction="buy", scenario="a", components=[],
            scenario_score=82.0, confidence=94.0,
        )
        b = MarketThesis(
            direction="buy", scenario="b", components=[],
            scenario_score=90.0, confidence=37.0,
        )
        assert a.quality_confidence_ratio > b.quality_confidence_ratio

    def test_confidence_calculated_from_chain(self):
        chain = [
            LiquidityNode(type="sweep", price=49000.0, strength=0.8),
            LiquidityNode(type="bos", price=49500.0, strength=0.7,
                         created_by="sweep_49000.000000"),
            LiquidityNode(type="ob", price=49800.0, strength=0.6,
                         created_by="bos_49500.000000"),
            LiquidityNode(type="fvg", price=50000.0, strength=0.5,
                         created_by="ob_49800.000000"),
            LiquidityNode(type="old_high", price=53000.0, strength=0.7,
                         created_by="fvg_50000.000000"),
        ]
        graph = LiquidityGraph(current_price=50000.0)
        confidence = market_thesis_engine._calculate_confidence(
            chain, graph, direction="buy"
        )
        assert confidence > 50.0

    def test_confidence_lower_without_causality(self):
        chain = [
            LiquidityNode(type="sweep", price=49000.0),
            LiquidityNode(type="ob", price=49800.0),
            LiquidityNode(type="old_high", price=53000.0),
        ]
        graph = LiquidityGraph(current_price=50000.0)
        confidence_no_causality = market_thesis_engine._calculate_confidence(
            chain, graph, direction="buy"
        )

        chain_with_causality = [
            LiquidityNode(type="sweep", price=49000.0),
            LiquidityNode(type="ob", price=49800.0,
                         created_by="sweep_49000.000000"),
            LiquidityNode(type="old_high", price=53000.0,
                         created_by="ob_49800.000000"),
        ]
        confidence_with_causality = market_thesis_engine._calculate_confidence(
            chain_with_causality, graph, direction="buy"
        )
        assert confidence_with_causality > confidence_no_causality

    def test_scenarios_sorted_by_quality_confidence(self):
        obs = [MockOB(type="bullish", midpoint=49500.0, displacement_atr=2.0)]
        ext = [MockExternalLiquidity(type="old_high", level=53000.0)]
        graph = market_thesis_engine.build_liquidity_graph(
            current_price=50000.0,
            order_blocks=obs,
            external_levels=ext,
        )
        scenarios = market_thesis_engine.detect_scenarios(graph, direction="buy")
        if len(scenarios) >= 2:
            for i in range(len(scenarios) - 1):
                assert (
                    scenarios[i].quality_confidence_ratio >=
                    scenarios[i + 1].quality_confidence_ratio
                )


# ══════════════════════════════════════════════════════════════════
# Transition Probability Tests
# ══════════════════════════════════════════════════════════════════

class TestTransitionProbability:
    def test_sweep_causes_bos(self):
        model = HeuristicTransitionModel()
        prob = model.compute_initial("sweep_causes_bos", 0.8, 0.7)
        assert 0.5 < prob < 1.0

    def test_displacement_causes_fvg(self):
        model = HeuristicTransitionModel()
        prob = model.compute_initial("displacement_causes_fvg", 0.9, 0.6)
        assert 0.5 < prob < 1.0

    def test_unknown_edge_type(self):
        model = HeuristicTransitionModel()
        prob = model.compute_initial("unknown", 0.5, 0.5)
        assert 0.1 <= prob <= 0.95

    def test_probability_bounds(self):
        model = HeuristicTransitionModel()
        # Very low strengths should still give reasonable probability
        prob = model.compute_initial("sweep_causes_bos", 0.0, 0.0)
        assert prob >= 0.05
        # Very high strengths should not exceed 0.95
        prob = model.compute_initial("sweep_causes_bos", 1.0, 1.0)
        assert prob <= 0.95


# ══════════════════════════════════════════════════════════════════
# Risk Engine ScenarioScore Integration Tests
# ══════════════════════════════════════════════════════════════════

class TestRiskEngineScenarioScore:
    def test_risk_engine_accepts_scenario_score(self):
        from risk.engine import RiskEngine, PortfolioState
        from strategy.feature_builder import SetupFeatures
        from strategy.probability_engine import TradeProbability

        engine = RiskEngine()
        features = SetupFeatures(
            atr_pct=1.5,
            adx=25.0,
            rsi=55.0,
            volume_ratio=1.2,
        )
        probability = TradeProbability(
            p_tp=0.6, expected_rr=2.0, profit_factor=1.5,
            confidence=0.7, model_type="rules",
        )
        portfolio = PortfolioState()

        # With high scenario score → larger position
        decision_high = engine.evaluate(
            features, probability, portfolio,
            entry_price=50000.0, sl=49500.0, tp=52000.0,
            scenario_score=90.0,
        )
        # With low scenario score → smaller position
        decision_low = engine.evaluate(
            features, probability, portfolio,
            entry_price=50000.0, sl=49500.0, tp=52000.0,
            scenario_score=30.0,
        )
        assert decision_high.scenario_score_adjustment > decision_low.scenario_score_adjustment

    def test_risk_engine_backward_compat_no_score(self):
        from risk.engine import RiskEngine, PortfolioState
        from strategy.feature_builder import SetupFeatures
        from strategy.probability_engine import TradeProbability

        engine = RiskEngine()
        features = SetupFeatures(
            atr_pct=1.5, adx=25.0, rsi=55.0,
            volume_ratio=1.2,
        )
        probability = TradeProbability(
            p_tp=0.6, expected_rr=2.0, profit_factor=1.5,
            confidence=0.7, model_type="rules",
        )
        portfolio = PortfolioState()

        # Without scenario_score (backward compat)
        decision = engine.evaluate(
            features, probability, portfolio,
            entry_price=50000.0, sl=49500.0, tp=52000.0,
        )
        assert decision.scenario_score_adjustment == 1.0
