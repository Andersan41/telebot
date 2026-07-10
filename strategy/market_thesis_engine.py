"""
strategy/market_thesis_engine.py — Dynamic Market Thesis Engine

A directed acyclic graph (DAG) engine that models market scenarios
as chains of causally connected liquidity EVENTS (not just levels).

Key difference from static engine:
- Nodes have a lifecycle: pending → active → mitigated/invalidated/completed
- Edge probabilities update as new candles arrive
- DynamicTradeThesis recalculates on each candle without recreating structure
- Competing BUY/SELL scenarios run in parallel with relative probabilities
- TransitionModel interface allows future ML-learned probabilities

Flow:
    Market Data (each candle close)
        ↓
    LiquidityGraph.update_on_candle()
        ↓
    DynamicTradeThesis.update()
        ↓
    Competing Scenarios (BUY vs SELL with probabilities)
        ↓
    Risk Engine uses scenario stability for sizing

The engine answers: "What is the market trying to do RIGHT NOW?"
NOT: "What did the market try to do 5 candles ago?"
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Optional

from loguru import logger

from strategy import weights as w
from strategy.weights import weighted_score, normalize


# ══════════════════════════════════════════════════════════════════
# Edge — typed, weighted, directed relationship between nodes
# ══════════════════════════════════════════════════════════════════

@dataclass
class Edge:
    """A typed, weighted, directed edge in the liquidity DAG.

    Each edge represents a causal or structural relationship.
    transition_probability is mutable and updates as new data arrives.
    """
    source_id: str
    target_id: str
    type: Literal["causes", "confirms", "mitigates", "targets"]
    strength: float = 0.5
    transition_probability: float = 0.5
    metadata: dict = field(default_factory=dict)

    # Temporal tracking
    created_at: Optional[int] = None    # bar index when edge was created
    last_updated: Optional[int] = None  # bar index of last probability update
    age_bars: int = 0                   # bars since creation

    def update_probability(self, new_prob: float, current_bar: int) -> None:
        """Update transition probability and track when it changed."""
        self.transition_probability = max(0.05, min(0.95, new_prob))
        self.last_updated = current_bar
        if self.created_at is None:
            self.created_at = current_bar
        self.age_bars = current_bar - (self.created_at or current_bar)

    def __repr__(self) -> str:
        return (
            f"Edge({self.source_id} --[{self.type}, "
            f"s={self.strength:.2f}, p={self.transition_probability:.2f}]--> "
            f"{self.target_id})"
        )


# ══════════════════════════════════════════════════════════════════
# TransitionModel — interface for probability computation
# ══════════════════════════════════════════════════════════════════

class TransitionModel(ABC):
    """Interface for computing edge transition probabilities.

    Implementations:
    - HeuristicTransitionModel: rule-based (current default)
    - Future: ML-learned from historical data

    The model is called:
    1. When edges are created (initial probability)
    2. After each candle close (probability update)
    """

    @abstractmethod
    def compute_initial(
        self,
        edge_type: str,
        source_strength: float,
        target_strength: float,
    ) -> float:
        """Compute initial transition probability for a new edge."""
        ...

    @abstractmethod
    def update_on_candle(
        self,
        edge: Edge,
        source_state: str,
        target_state: str,
        candle_data: dict,
    ) -> float:
        """Update edge probability based on new candle data.

        Args:
            edge: the edge to update
            source_state: current state of source node
            target_state: current state of target node
            candle_data: OHLCV data for the latest candle

        Returns:
            Updated probability value.
        """
        ...


class HeuristicTransitionModel(TransitionModel):
    """Rule-based transition probability model.

    Uses base probabilities per edge type, adjusted by node strengths
    and state changes. This is the default model — designed to be
    replaced by ML-learned probabilities later.
    """

    # Base probabilities per edge type
    BASE_PROBS = {
        "sweep_causes_bos": 0.75,
        "bos_causes_ob": 0.65,
        "displacement_causes_fvg": 0.80,
        "ob_causes_fvg": 0.60,
        "fvg_targets_ext": 0.55,
        "ob_targets_ext": 0.50,
        "fvg_targets_eq": 0.45,
    }

    def compute_initial(
        self,
        edge_type: str,
        source_strength: float,
        target_strength: float,
    ) -> float:
        base = self.BASE_PROBS.get(edge_type, 0.5)
        source_factor = 0.7 + 0.3 * max(0.0, min(1.0, source_strength))
        target_factor = 0.7 + 0.3 * max(0.0, min(1.0, target_strength))
        prob = base * source_factor * target_factor
        return round(max(0.05, min(0.95, prob)), 3)

    def update_on_candle(
        self,
        edge: Edge,
        source_state: str,
        target_state: str,
        candle_data: dict,
    ) -> float:
        """Update probability based on source/target state changes.

        Heuristics:
        - If source becomes "tested" (event confirmed by price): probability ↑
        - If source becomes "mitigated" (event negated): probability ↓
        - If source becomes "broken": probability ↓↓
        - If target state changes: adjust accordingly
        - Age decay: very old edges lose probability slowly
        """
        current = edge.transition_probability

        # Source confirmation boost
        if source_state == NODE_STATE_TESTED:
            current = min(0.95, current * 1.15)
        elif source_state == NODE_STATE_MITIGATED:
            current = max(0.05, current * 0.3)
        elif source_state == NODE_STATE_BROKEN:
            current = max(0.05, current * 0.1)

        # Target confirmation
        if target_state == NODE_STATE_TESTED:
            current = min(0.95, current * 1.10)
        elif target_state == NODE_STATE_MITIGATED:
            current = max(0.05, current * 0.5)

        # Age decay (edges older than 20 bars lose probability)
        if edge.age_bars > 20:
            decay = max(0.7, 1.0 - (edge.age_bars - 20) * 0.005)
            current *= decay

        return round(max(0.05, min(0.95, current)), 3)


# ══════════════════════════════════════════════════════════════════
# Node State Machine — 8-state lifecycle
# ══════════════════════════════════════════════════════════════════
#
#   created → active → tested → partially_mitigated → mitigated
#                    → broken → reactivated
#                    → stale
#
# "tested" = price touched the level (retest/wick into)
# "partially_mitigated" = price closed through 50% of zone (not full)
# "mitigated" = level fully consumed (OB filled, FVG filled)
# "broken" = level breached (price closed through)
# "reactivated" = broken level reclaimed by new sweep/BOS
# "stale" = too old to be relevant

NODE_STATE_CREATED = "created"
NODE_STATE_ACTIVE = "active"
NODE_STATE_TESTED = "tested"
NODE_STATE_PARTIALLY_MITIGATED = "partially_mitigated"
NODE_STATE_MITIGATED = "mitigated"
NODE_STATE_BROKEN = "broken"
NODE_STATE_REACTIVATED = "reactivated"
NODE_STATE_STALE = "stale"

# Terminal states — no further transitions
TERMINAL_STATES = frozenset({NODE_STATE_MITIGATED, NODE_STATE_STALE})

# Backward compat aliases
NODE_STATE_PENDING = NODE_STATE_CREATED
NODE_STATE_COMPLETED = NODE_STATE_TESTED
NODE_STATE_INVALIDATED = NODE_STATE_MITIGATED
NODE_STATE_SWEPT = NODE_STATE_BROKEN
NODE_STATE_FILLED = NODE_STATE_MITIGATED

# Valid states for scenario participation
VALID_PARTICIPATION_STATES = frozenset({
    NODE_STATE_ACTIVE, NODE_STATE_CREATED, NODE_STATE_TESTED,
    NODE_STATE_REACTIVATED, NODE_STATE_PARTIALLY_MITIGATED,
})

# State scores: how alive/relevant a node is [0, 1]
NODE_STATE_SCORES: dict[str, float] = {
    NODE_STATE_CREATED: 0.9,
    NODE_STATE_ACTIVE: 1.0,
    NODE_STATE_TESTED: 0.7,
    NODE_STATE_PARTIALLY_MITIGATED: 0.4,
    NODE_STATE_MITIGATED: 0.0,
    NODE_STATE_BROKEN: 0.0,
    NODE_STATE_REACTIVATED: 0.85,
    NODE_STATE_STALE: 0.1,
}


@dataclass
class NodeTransition:
    """Record of a single state transition for a LiquidityNode."""
    old: str
    new: str
    bar: int
    reason: str = ""

    def __repr__(self) -> str:
        return f"Transition({self.old} → {self.new} @ bar {self.bar})"


class NodeStateMachine:
    """Manages state transitions for LiquidityNode.

    Enforces valid transitions and records history.
    """

    VALID_TRANSITIONS: dict[str, list[str]] = {
        NODE_STATE_CREATED:  [NODE_STATE_ACTIVE, NODE_STATE_STALE],
        NODE_STATE_ACTIVE:   [NODE_STATE_TESTED, NODE_STATE_MITIGATED, NODE_STATE_BROKEN, NODE_STATE_STALE],
        NODE_STATE_TESTED:   [NODE_STATE_MITIGATED, NODE_STATE_PARTIALLY_MITIGATED, NODE_STATE_BROKEN, NODE_STATE_STALE],
        NODE_STATE_PARTIALLY_MITIGATED: [NODE_STATE_MITIGATED, NODE_STATE_BROKEN, NODE_STATE_STALE],
        NODE_STATE_MITIGATED: [],
        NODE_STATE_BROKEN:   [NODE_STATE_REACTIVATED],
        NODE_STATE_REACTIVATED: [NODE_STATE_TESTED, NODE_STATE_MITIGATED, NODE_STATE_BROKEN, NODE_STATE_STALE],
        NODE_STATE_STALE:    [],
    }

    def can_transition(self, current: str, target: str) -> bool:
        return target in self.VALID_TRANSITIONS.get(current, [])

    def transition(
        self,
        node: "LiquidityNode",
        new_state: str,
        bar: int,
        reason: str = "",
    ) -> bool:
        """Attempt a state transition. Returns True if successful."""
        if not self.can_transition(node.state, new_state):
            logger.debug(
                f"Node {node.type}@{node.price:.4f}: "
                f"cannot transition {node.state} → {new_state}"
            )
            return False

        old = node.state
        node.state = new_state
        node.last_updated = bar
        if bar is not None and node.created_at is None:
            node.created_at = bar

        node.transition_history.append(NodeTransition(
            old=old, new=new_state, bar=bar, reason=reason,
        ))

        logger.debug(
            f"Node {node.type}@{node.price:.4f}: "
            f"{old} → {new_state} ({reason})"
        )
        return True


# Module-level singleton
_node_state_machine = NodeStateMachine()


@dataclass
class LiquidityNode:
    """A node in the directed liquidity graph (DAG).

    Represents a market EVENT (not just a level):
    - LiquidityGrab, Sweep, Displacement, BOS, CHoCH,
      Mitigation, Order Block, FVG, External Liquidity

    Lifecycle: created → active → tested → mitigated / broken / stale

    Temporal tracking:
    - created_at: bar index when node was created
    - last_updated: bar index of last state change
    - age_bars: bars since creation (updated on each candle)
    - transition_history: full list of state transitions
    """
    type: Literal[
        "sweep", "bos", "choch", "ob", "fvg",
        "equal_high", "equal_low",
        "old_high", "old_low",
        "swing_high", "swing_low",
        "displacement",
        # New event types (backward compat: same as above)
        "liquidity_grab", "mitigation",
    ]
    price: float
    strength: float = 0.0
    quality_score: float = 0.0
    timeframe: str = "1h"
    state: str = NODE_STATE_CREATED
    timestamp: Optional[object] = None
    source: Optional[object] = None

    # ── DAG edges ──
    edges: list[Edge] = field(default_factory=list)

    # ── Backward compatibility ──
    created_by: Optional[str] = None
    creates: list[str] = field(default_factory=list)
    invalidated_by: Optional[str] = None

    # ── Temporal tracking ──
    created_at: Optional[int] = None    # bar index when created
    last_updated: Optional[int] = None  # bar index of last state change
    age_bars: int = 0                   # bars since creation

    # ── State machine ──
    transition_history: list[NodeTransition] = field(default_factory=list)
    times_tested: int = 0

    # Metadata
    displacement_atr: float = 0.0
    volume_ratio: float = 1.0
    distance_from_price_pct: float = 0.0

    # Backward compat properties
    @property
    def caused_by(self) -> Optional[str]:
        return self.created_by

    @caused_by.setter
    def caused_by(self, value: Optional[str]):
        self.created_by = value

    @property
    def causes(self) -> list[str]:
        return self.creates

    @causes.setter
    def causes(self, value: list[str]):
        self.creates = value

    @property
    def is_bullish(self) -> bool:
        return self.type in (
            "sweep", "bos", "ob", "fvg", "equal_low",
            "old_low", "swing_low", "displacement",
            "liquidity_grab",
        )

    @property
    def is_bearish(self) -> bool:
        return self.type in (
            "sweep", "bos", "ob", "fvg", "equal_high",
            "old_high", "swing_high", "displacement",
            "liquidity_grab",
        )

    @property
    def is_valid(self) -> bool:
        """A node is valid if it can participate in a scenario."""
        return self.state in VALID_PARTICIPATION_STATES

    @property
    def is_alive(self) -> bool:
        """A node is alive if it hasn't reached a terminal state."""
        return self.state not in TERMINAL_STATES

    @property
    def state_score(self) -> float:
        """How alive/relevant this node is. [0, 1].

        Used by Hypothesis decay calculation.
        """
        return NODE_STATE_SCORES.get(self.state, 0.5)

    def transition_to(self, new_state: str, current_bar: Optional[int] = None, reason: str = "") -> None:
        """Transition to a new state via NodeStateMachine with history tracking."""
        _node_state_machine.transition(self, new_state, current_bar or 0, reason)

    def update_age(self, current_bar: int) -> None:
        """Update age based on current bar index."""
        if self.created_at is not None:
            self.age_bars = current_bar - self.created_at

    def add_edge(self, edge: Edge) -> None:
        """Add an outgoing edge and sync backward-compat fields."""
        self.edges.append(edge)
        if edge.type == "causes" and edge.target_id not in self.creates:
            self.creates.append(edge.target_id)
        elif edge.type == "mitigates":
            self.invalidated_by = edge.target_id

    def get_edges(self, edge_type: Optional[str] = None) -> list[Edge]:
        """Get outgoing edges, optionally filtered by type."""
        if edge_type:
            return [e for e in self.edges if e.type == edge_type]
        return list(self.edges)

    def __repr__(self) -> str:
        return (
            f"LiquidityNode({self.type} @ {self.price:.4f} "
            f"score={self.quality_score:.0f} state={self.state} "
            f"age={self.age_bars} edges={len(self.edges)})"
        )


# ══════════════════════════════════════════════════════════════════
# LiquidityGraph — dynamic DAG with candle updates
# ══════════════════════════════════════════════════════════════════

@dataclass
class LiquidityGraph:
    """Dynamic directed acyclic graph of market events.

    Updates on each candle close without recreating the structure.
    Tracks graph version for change detection.
    """
    nodes: list[LiquidityNode] = field(default_factory=list)
    current_price: float = 0.0
    symbol: str = ""
    timeframe: str = ""

    # Dynamic state
    graph_version: int = 0           # incremented on each update
    last_update_bar: Optional[int] = None
    current_bar: int = 0             # current bar index

    # Internal index
    _node_index: dict[str, LiquidityNode] = field(
        default_factory=dict, repr=False
    )

    # Transition model (pluggable)
    _transition_model: Optional[TransitionModel] = field(
        default=None, repr=False
    )

    def __post_init__(self):
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._node_index = {}
        for node in self.nodes:
            self._node_index[_node_id(node)] = node

    def set_transition_model(self, model: TransitionModel) -> None:
        """Set the transition model for probability computation."""
        self._transition_model = model

    @property
    def transition_model(self) -> TransitionModel:
        """Get the transition model (default: HeuristicTransitionModel)."""
        if self._transition_model is None:
            self._transition_model = HeuristicTransitionModel()
        return self._transition_model

    def add_node(self, node: LiquidityNode) -> None:
        """Add a node to the graph."""
        if node.created_at is None:
            node.created_at = self.current_bar
        node.last_updated = self.current_bar
        self.nodes.append(node)
        self._node_index[_node_id(node)] = node
        self.graph_version += 1

    def add_edge(
        self,
        source: LiquidityNode,
        target: LiquidityNode,
        edge_type: Literal["causes", "confirms", "mitigates", "targets"],
        strength: float = 0.5,
        transition_probability: Optional[float] = None,
        metadata: dict = None,
    ) -> Edge:
        """Add a typed, weighted edge between two nodes."""
        # Use transition model if no probability provided
        if transition_probability is None:
            edge_key = f"{source.type}_{edge_type}_{target.type}"
            transition_probability = self.transition_model.compute_initial(
                edge_key, source.strength, target.strength
            )

        edge = Edge(
            source_id=_node_id(source),
            target_id=_node_id(target),
            type=edge_type,
            strength=strength,
            transition_probability=transition_probability,
            metadata=metadata or {},
            created_at=self.current_bar,
            last_updated=self.current_bar,
        )
        source.add_edge(edge)
        self.graph_version += 1
        return edge

    def get_node(self, node_id: str) -> Optional[LiquidityNode]:
        return self._node_index.get(node_id)

    def get_children(
        self, node: LiquidityNode, edge_type: Optional[str] = None
    ) -> list[LiquidityNode]:
        children = []
        for edge in node.get_edges(edge_type):
            child = self.get_node(edge.target_id)
            if child:
                children.append(child)
        return children

    def get_parents(
        self, node: LiquidityNode, edge_type: Optional[str] = None
    ) -> list[LiquidityNode]:
        parents = []
        node_id = _node_id(node)
        for other in self.nodes:
            for edge in other.get_edges(edge_type):
                if edge.target_id == node_id:
                    parents.append(other)
                    break
        return parents

    def get_roots(self) -> list[LiquidityNode]:
        caused_ids = set()
        for node in self.nodes:
            for edge in node.get_edges("causes"):
                caused_ids.add(edge.target_id)
        return [n for n in self.nodes if _node_id(n) not in caused_ids]

    def topological_sort(self) -> list[LiquidityNode]:
        visited = set()
        result = []

        def _visit(node_id: str):
            if node_id in visited:
                return
            visited.add(node_id)
            node = self.get_node(node_id)
            if not node:
                return
            for edge in node.get_edges("causes"):
                _visit(edge.target_id)
            result.append(node)

        for node in self.nodes:
            _visit(_node_id(node))

        return result

    def update_on_candle(
        self,
        candle_data: dict,
        current_price: float,
        new_bar: bool = False,
    ) -> None:
        """Update the graph after a new candle closes.

        This is the core dynamic method:
        1. Update current price and bar index
        2. Update node ages
        3. Update edge probabilities via TransitionModel
        4. Transition node states based on price action
        5. Increment graph version

        Args:
            candle_data: {"open", "high", "low", "close", "volume"}
            current_price: current close price
            new_bar: True if this is a new bar (not just a tick update)
        """
        self.current_price = current_price

        if new_bar:
            self.current_bar += 1
            self.last_update_bar = self.current_bar

        # 1. Update node ages
        for node in self.nodes:
            node.update_age(self.current_bar)

        # 2. Update edge probabilities
        for node in self.nodes:
            for edge in node.edges:
                source = self.get_node(edge.source_id)
                target = self.get_node(edge.target_id)
                if source and target:
                    new_prob = self.transition_model.update_on_candle(
                        edge, source.state, target.state, candle_data,
                    )
                    edge.update_probability(new_prob, self.current_bar)

        # 3. Check state transitions based on price action
        if new_bar:
            self._check_state_transitions(candle_data)

        self.graph_version += 1

    def _check_state_transitions(self, candle_data: dict) -> None:
        """Check if any nodes should change state based on new candle.

        Uses the 8-state lifecycle:
        created → active → tested → partially_mitigated → mitigated
                         → broken → reactivated
                         → stale
        """
        high = candle_data.get("high", 0)
        low = candle_data.get("low", 0)
        close = candle_data.get("close", 0)

        for node in self.nodes:
            if not node.is_alive:
                continue

            # Transition created → active (always on first update)
            if node.state == NODE_STATE_CREATED:
                _node_state_machine.transition(
                    node, NODE_STATE_ACTIVE, self.current_bar, "first update"
                )

            # FVG: tested if wick touches, mitigated if filled
            if node.type == "fvg" and node.state == NODE_STATE_ACTIVE:
                source = node.source
                if source and hasattr(source, "top") and hasattr(source, "bottom"):
                    if low <= source.top and high >= source.bottom:
                        _node_state_machine.transition(
                            node, NODE_STATE_TESTED, self.current_bar, "wick into FVG"
                        )
                    if low <= source.bottom:
                        _node_state_machine.transition(
                            node, NODE_STATE_MITIGATED, self.current_bar, "FVG filled"
                        )

            # FVG: tested → mitigated
            if node.type == "fvg" and node.state == NODE_STATE_TESTED:
                source = node.source
                if source and hasattr(source, "bottom"):
                    if low <= source.bottom:
                        _node_state_machine.transition(
                            node, NODE_STATE_MITIGATED, self.current_bar, "FVG filled"
                        )

            # OB: tested if wick enters
            if node.type == "ob" and node.state == NODE_STATE_ACTIVE:
                source = node.source
                if source and hasattr(source, "type"):
                    is_bullish = source.type == "bullish"
                    if is_bullish and low <= node.price:
                        _node_state_machine.transition(
                            node, NODE_STATE_TESTED, self.current_bar, "wick into bullish OB"
                        )
                    elif not is_bullish and high >= node.price:
                        _node_state_machine.transition(
                            node, NODE_STATE_TESTED, self.current_bar, "wick into bearish OB"
                        )

            # OB: tested → partially_mitigated (close through 50% but not full)
            if node.type == "ob" and node.state == NODE_STATE_TESTED:
                source = node.source
                if source and hasattr(source, "type") and hasattr(source, "midpoint"):
                    midpoint = getattr(source, "midpoint", node.price)
                    if source.type == "bullish" and close < midpoint and close > node.price * 0.98:
                        _node_state_machine.transition(
                            node, NODE_STATE_PARTIALLY_MITIGATED, self.current_bar,
                            "bullish OB partially mitigated"
                        )
                    elif source.type == "bearish" and close > midpoint and close < node.price * 1.02:
                        _node_state_machine.transition(
                            node, NODE_STATE_PARTIALLY_MITIGATED, self.current_bar,
                            "bearish OB partially mitigated"
                        )

            # OB: tested/partially_mitigated → mitigated (close through midpoint)
            if node.type == "ob" and node.state in (NODE_STATE_TESTED, NODE_STATE_PARTIALLY_MITIGATED):
                source = node.source
                if source and hasattr(source, "type"):
                    if source.type == "bullish" and close < node.price:
                        _node_state_machine.transition(
                            node, NODE_STATE_MITIGATED, self.current_bar, "bullish OB mitigated"
                        )
                    elif source.type == "bearish" and close > node.price:
                        _node_state_machine.transition(
                            node, NODE_STATE_MITIGATED, self.current_bar, "bearish OB mitigated"
                        )

            # OB: broken → reactivated (new sweep/BOS to same level)
            if node.type == "ob" and node.state == NODE_STATE_BROKEN:
                # Reactivation happens when a new sweep or BOS targets this level
                # This is handled externally by the graph when new nodes are added
                pass

            # Liquidity levels (swing, equal): broken if swept
            if node.type in ("swing_high", "equal_high") and node.state in (NODE_STATE_ACTIVE, NODE_STATE_TESTED):
                if high > node.price:
                    _node_state_machine.transition(
                        node, NODE_STATE_BROKEN, self.current_bar, "sweep above"
                    )
            if node.type in ("swing_low", "equal_low") and node.state in (NODE_STATE_ACTIVE, NODE_STATE_TESTED):
                if low < node.price:
                    _node_state_machine.transition(
                        node, NODE_STATE_BROKEN, self.current_bar, "sweep below"
                    )

            # Stale check (age > 50 bars without activity)
            if node.state == NODE_STATE_ACTIVE and node.age_bars > 50:
                _node_state_machine.transition(
                    node, NODE_STATE_STALE, self.current_bar, "age > 50 bars"
                )

    def nodes_below(self, price: float = None) -> list[LiquidityNode]:
        p = price if price is not None else self.current_price
        return sorted(
            [n for n in self.nodes if n.price < p and n.is_valid],
            key=lambda n: n.price,
            reverse=True,
        )

    def nodes_above(self, price: float = None) -> list[LiquidityNode]:
        p = price if price is not None else self.current_price
        return sorted(
            [n for n in self.nodes if n.price > p and n.is_valid],
            key=lambda n: n.price,
        )

    def bullish_nodes(self) -> list[LiquidityNode]:
        return [n for n in self.nodes if n.is_bullish and n.is_valid]

    def bearish_nodes(self) -> list[LiquidityNode]:
        return [n for n in self.nodes if n.is_bearish and n.is_valid]

    def confirmed_nodes(self) -> list[LiquidityNode]:
        """Nodes that have been confirmed (tested state = price touched)."""
        return [n for n in self.nodes if n.state == NODE_STATE_TESTED]

    def alive_nodes(self) -> list[LiquidityNode]:
        """Nodes that are still alive (not mitigated/invalidated)."""
        return [n for n in self.nodes if n.is_alive]

    def scenario_stability(self) -> float:
        """Compute scenario stability [0, 1].

        Stability increases when:
        - More nodes are tested (price confirmed the level)
        - Fewer nodes are mitigated/broken/stale
        - Strong edge probabilities

        Stability decreases when:
        - Nodes transition to terminal states
        - Edges lose probability
        """
        if not self.nodes:
            return 0.0

        total = len(self.nodes)
        tested = sum(1 for n in self.nodes if n.state == NODE_STATE_TESTED)
        alive = sum(1 for n in self.nodes if n.is_alive)
        terminal = sum(1 for n in self.nodes if n.state in TERMINAL_STATES)

        # Tested ratio (confirmed by price action)
        tested_ratio = tested / total if total > 0 else 0

        # Alive ratio
        alive_ratio = alive / total if total > 0 else 0

        # Average edge probability
        all_probs = []
        for node in self.nodes:
            for edge in node.edges:
                all_probs.append(edge.transition_probability)
        avg_prob = sum(all_probs) / len(all_probs) if all_probs else 0.5

        # Combine: tested is strongest signal
        stability = (
            tested_ratio * 0.4
            + alive_ratio * 0.3
            + avg_prob * 0.3
        )

        return round(min(1.0, max(0.0, stability)), 3)


# ══════════════════════════════════════════════════════════════════
# LiquidityPath, ScenarioScore, MarketThesis, Scenario
# ══════════════════════════════════════════════════════════════════

@dataclass
class LiquidityPathNode:
    """A single step in the liquidity path."""
    node: LiquidityNode
    role: Literal[
        "trigger", "confirmation", "target",
        "invalidation", "obstacle",
    ]
    reason: str = ""


@dataclass
class LiquidityPath:
    """Ordered sequence of events that the market is expected to follow."""
    direction: Literal["buy", "sell"]
    nodes: list[LiquidityPathNode] = field(default_factory=list)
    target_node: Optional[LiquidityNode] = None
    invalidation_node: Optional[LiquidityNode] = None

    @property
    def is_complete(self) -> bool:
        triggers = [n for n in self.nodes if n.role == "trigger"]
        targets = [n for n in self.nodes if n.role == "target"]
        return len(triggers) > 0 and len(targets) > 0

    @property
    def path_length(self) -> int:
        return len(self.nodes)

    def format(self) -> str:
        lines = [f"{self.direction.upper()} Liquidity Path:"]
        for i, node in enumerate(self.nodes):
            arrow = "  ↓" if i < len(self.nodes) - 1 else ""
            lines.append(
                f"  [{node.role}] {node.node.type} @ "
                f"{node.node.price:.4f}{arrow}"
            )
            if node.reason:
                lines.append(f"         {node.reason}")
        return "\n".join(lines)


@dataclass
class ScenarioScore:
    """Explainable score for a scenario."""
    ob_contribution: float = 0.0
    sweep_contribution: float = 0.0
    bos_contribution: float = 0.0
    fvg_contribution: float = 0.0
    liquidity_contribution: float = 0.0
    htf_contribution: float = 0.0

    @property
    def total(self) -> float:
        raw = (
            self.ob_contribution + self.sweep_contribution
            + self.bos_contribution + self.fvg_contribution
            + self.liquidity_contribution + self.htf_contribution
        )
        return round(min(100.0, max(0.0, raw)), 1)

    def breakdown(self) -> dict[str, float]:
        return {
            "ob": round(self.ob_contribution, 1),
            "sweep": round(self.sweep_contribution, 1),
            "bos": round(self.bos_contribution, 1),
            "fvg": round(self.fvg_contribution, 1),
            "liquidity": round(self.liquidity_contribution, 1),
            "htf": round(self.htf_contribution, 1),
            "total": self.total,
        }

    def __repr__(self) -> str:
        return (
            f"ScenarioScore(total={self.total:.1f} "
            f"OB={self.ob_contribution:.1f} "
            f"Sweep={self.sweep_contribution:.1f} "
            f"BOS={self.bos_contribution:.1f} "
            f"FVG={self.fvg_contribution:.1f} "
            f"Liq={self.liquidity_contribution:.1f} "
            f"HTF={self.htf_contribution:.1f})"
        )


@dataclass
class MarketThesis:
    """A complete market scenario — what the market is trying to do."""
    direction: Literal["buy", "sell"]
    scenario: str
    components: list[str]
    scenario_score: float = 0.0
    confidence: float = 0.0
    score_breakdown: Optional[ScenarioScore] = None
    liquidity_path: Optional[LiquidityPath] = None
    entry_zone: Optional[tuple[float, float]] = None
    invalidation_price: float = 0.0
    invalidation_reason: str = ""
    target_price: float = 0.0
    target_reason: str = ""
    expected_rr: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def has_invalidation(self) -> bool:
        return self.invalidation_price > 0

    @property
    def has_target(self) -> bool:
        return self.target_price > 0

    @property
    def quality_confidence_ratio(self) -> float:
        return self.scenario_score * self.confidence / 100.0


@dataclass
class Scenario:
    """A ranked market scenario — the primary output of the engine."""
    direction: Literal["buy", "sell"]
    symbol: str
    timeframe: str
    thesis: MarketThesis
    score_breakdown: ScenarioScore = field(default_factory=ScenarioScore)
    explanation: str = ""
    alternative_rank: int = 0

    entry_price: float = 0.0
    invalidation_price: float = 0.0
    target_price: float = 0.0
    expected_rr: float = 0.0

    @property
    def score(self) -> float:
        return self.thesis.scenario_score

    @property
    def confidence(self) -> float:
        return self.thesis.confidence

    @property
    def quality_confidence_ratio(self) -> float:
        return self.thesis.quality_confidence_ratio

    @property
    def components(self) -> list[str]:
        return self.thesis.components

    @property
    def liquidity_path(self) -> Optional[LiquidityPath]:
        return self.thesis.liquidity_path

    def format_explanation(self) -> str:
        lines = [
            f"{'BUY' if self.direction == 'buy' else 'SELL'} "
            f"{self.symbol} {self.timeframe}",
            f"Scenario: {self.thesis.scenario}",
            f"Score: {self.score:.1f}/100 "
            f"(rank #{self.alternative_rank + 1})",
            f"Confidence: {self.confidence:.0f}/100",
        ]
        if self.score_breakdown:
            lines.append(f"Breakdown: {self.score_breakdown.breakdown()}")
        if self.liquidity_path:
            lines.append(self.liquidity_path.format())
        if self.invalidation_price > 0:
            lines.append(f"Invalidation: {self.invalidation_price:.4f}")
        if self.target_price > 0:
            lines.append(f"Target: {self.target_price:.4f}")
        if self.expected_rr > 0:
            lines.append(f"RR: 1:{self.expected_rr:.1f}")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# TradeOpportunity — backward-compatible wrapper
# ══════════════════════════════════════════════════════════════════

@dataclass
class TradeOpportunity:
    """Backward-compatible wrapper around Scenario."""
    direction: Literal["buy", "sell"]
    symbol: str
    timeframe: str
    thesis: MarketThesis
    scenario_score: float = 0.0
    expected_path: Optional[LiquidityPath] = None
    expected_probability: float = 0.0
    expected_target: float = 0.0
    invalidation: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def expected_rr(self) -> float:
        if self.invalidation == 0 or self.expected_target == 0:
            return 0.0
        entry = (
            (self.thesis.entry_zone[0] + self.thesis.entry_zone[1]) / 2
            if self.thesis.entry_zone else 0.0
        )
        if entry == 0:
            return 0.0
        risk = abs(entry - self.invalidation)
        reward = abs(self.expected_target - entry)
        return reward / risk if risk > 0 else 0.0

    @classmethod
    def from_scenario(cls, scenario: Scenario) -> TradeOpportunity:
        return cls(
            direction=scenario.direction,
            symbol=scenario.symbol,
            timeframe=scenario.timeframe,
            thesis=scenario.thesis,
            scenario_score=scenario.score,
            expected_path=scenario.liquidity_path,
            expected_probability=scenario.confidence / 100.0,
            expected_target=scenario.target_price,
            invalidation=scenario.invalidation_price,
            reasons=list(scenario.thesis.reasons),
        )


# ══════════════════════════════════════════════════════════════════
# DynamicTradeThesis — recalculates on each candle
# ══════════════════════════════════════════════════════════════════

@dataclass
class CompetingScenario:
    """A single competing scenario (BUY or SELL) with probability."""
    direction: Literal["buy", "sell"]
    thesis: Optional[MarketThesis] = None
    probability: float = 0.0       # relative probability [0, 1]
    confirmed_nodes: list[str] = field(default_factory=list)
    invalidated_nodes: list[str] = field(default_factory=list)
    score: float = 0.0
    confidence: float = 0.0

    @property
    def is_active(self) -> bool:
        return self.thesis is not None and self.probability > 0

    @property
    def stability(self) -> float:
        """Stability = confirmed / (confirmed + invalidated + 1)."""
        total = len(self.confirmed_nodes) + len(self.invalidated_nodes) + 1
        return len(self.confirmed_nodes) / total


class DynamicTradeThesis:
    """Dynamic trade thesis that recalculates on each candle close.

    Maintains competing BUY/SELL scenarios and tracks their evolution.
    Does NOT recreate the graph on each candle — updates in place.

    Usage:
        thesis = DynamicTradeThesis(symbol="BTC/USDT", timeframe="1h")
        thesis.update(graph, entry_price, candle_data)
        best = thesis.best_scenario
    """

    def __init__(
        self,
        symbol: str = "",
        timeframe: str = "",
        ambiguity_threshold: float = 0.15,
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.ambiguity_threshold = ambiguity_threshold

        # Competing scenarios
        self.buy_scenario = CompetingScenario(direction="buy")
        self.sell_scenario = CompetingScenario(direction="sell")

        # Tracking
        self.last_update_bar: int = 0
        self.update_count: int = 0
        self.history: list[dict] = []  # snapshot history

    @property
    def best_scenario(self) -> Optional[CompetingScenario]:
        """Return the scenario with higher probability."""
        if not self.buy_scenario.is_active and not self.sell_scenario.is_active:
            return None
        if self.buy_scenario.probability >= self.sell_scenario.probability:
            return self.buy_scenario
        return self.sell_scenario

    @property
    def is_ambiguous(self) -> bool:
        """True if BUY and SELL probabilities are too close."""
        if not self.buy_scenario.is_active or not self.sell_scenario.is_active:
            return False
        diff = abs(
            self.buy_scenario.probability - self.sell_scenario.probability
        )
        return diff < self.ambiguity_threshold

    @property
    def direction(self) -> Optional[str]:
        """Best direction, or None if ambiguous."""
        if self.is_ambiguous:
            return None
        best = self.best_scenario
        return best.direction if best else None

    @property
    def scenario_stability(self) -> float:
        """Overall stability of the current thesis."""
        best = self.best_scenario
        if not best:
            return 0.0
        return best.stability

    def update(
        self,
        graph: LiquidityGraph,
        entry_price: float,
        candle_data: dict = None,
        atr: float = 0.0,
    ) -> None:
        """Update thesis after a new candle close.

        This method:
        1. Updates the graph (node ages, edge probabilities)
        2. Checks for invalidation of existing scenarios
        3. Re-detects scenarios for both BUY and SELL
        4. Computes relative probabilities
        5. Tracks confirmed/invalidated nodes
        6. Takes a snapshot for history
        """
        # Update graph
        if candle_data:
            graph.update_on_candle(candle_data, entry_price, new_bar=True)

        # Check for invalidation of existing scenarios
        from strategy.scenario_invalidator import ScenarioInvalidator
        invalidator = ScenarioInvalidator()

        # Check BUY scenario invalidation
        if self.buy_scenario.thesis and self.buy_scenario.is_active:
            # Create a temporary hypothesis for invalidation check
            from strategy.hypothesis import Hypothesis
            temp_h = Hypothesis(
                id="temp_buy",
                direction="buy",
                narrative_type="temp",
                name="temp",
                description="temp",
                quality=50.0,
                confidence=0.5,
                decay_factor=1.0,
                entry_price=entry_price,
                invalidation_price=self.buy_scenario.thesis.invalidation_price,
                target_price=self.buy_scenario.thesis.target_price,
                rr_ratio=0.0,
            )
            inv_result = invalidator.invalidate(temp_h, graph, entry_price, graph.current_bar)
            if inv_result.is_invalid:
                logger.debug(
                    f"DynamicThesis BUY scenario invalidated: "
                    f"{inv_result.reason} ({inv_result.details})"
                )
                self.buy_scenario.thesis = None
                self.buy_scenario.probability = 0.0

        # Check SELL scenario invalidation
        if self.sell_scenario.thesis and self.sell_scenario.is_active:
            temp_h = Hypothesis(
                id="temp_sell",
                direction="sell",
                narrative_type="temp",
                name="temp",
                description="temp",
                quality=50.0,
                confidence=0.5,
                decay_factor=1.0,
                entry_price=entry_price,
                invalidation_price=self.sell_scenario.thesis.invalidation_price,
                target_price=self.sell_scenario.thesis.target_price,
                rr_ratio=0.0,
            )
            inv_result = invalidator.invalidate(temp_h, graph, entry_price, graph.current_bar)
            if inv_result.is_invalid:
                logger.debug(
                    f"DynamicThesis SELL scenario invalidated: "
                    f"{inv_result.reason} ({inv_result.details})"
                )
                self.sell_scenario.thesis = None
                self.sell_scenario.probability = 0.0

        # Detect scenarios for both directions
        engine = MarketThesisEngine()

        buy_theses = engine.detect_scenarios(graph, direction="buy")
        sell_theses = engine.detect_scenarios(graph, direction="sell")

        # Update BUY scenario
        if buy_theses:
            best_buy = buy_theses[0]
            self.buy_scenario.thesis = best_buy
            self.buy_scenario.score = best_buy.scenario_score
            self.buy_scenario.confidence = best_buy.confidence
            self._track_node_changes(
                self.buy_scenario, best_buy, graph
            )
        else:
            self.buy_scenario.thesis = None
            self.buy_scenario.probability = 0.0

        # Update SELL scenario
        if sell_theses:
            best_sell = sell_theses[0]
            self.sell_scenario.thesis = best_sell
            self.sell_scenario.score = best_sell.scenario_score
            self.sell_scenario.confidence = best_sell.confidence
            self._track_node_changes(
                self.sell_scenario, best_sell, graph
            )
        else:
            self.sell_scenario.thesis = None
            self.sell_scenario.probability = 0.0

        # Compute relative probabilities
        self._compute_probabilities(graph)

        # Update tracking
        self.last_update_bar = graph.current_bar
        self.update_count += 1

        # Take snapshot
        self._take_snapshot()

        logger.debug(
            f"DynamicThesis {self.symbol} {self.timeframe}: "
            f"BUY={self.buy_scenario.probability:.2f} "
            f"SELL={self.sell_scenario.probability:.2f} "
            f"ambiguous={self.is_ambiguous} "
            f"stability={self.scenario_stability:.2f}"
        )

    def _track_node_changes(
        self,
        scenario: CompetingScenario,
        thesis: MarketThesis,
        graph: LiquidityGraph,
    ) -> None:
        """Track which nodes were confirmed or invalidated."""
        if not thesis.liquidity_path:
            return

        current_node_ids = set()
        for path_node in thesis.liquidity_path.nodes:
            node_id = _node_id(path_node.node)
            current_node_ids.add(node_id)

            # Check if node is now tested (confirmed by price)
            if path_node.node.state == NODE_STATE_TESTED:
                if node_id not in scenario.confirmed_nodes:
                    scenario.confirmed_nodes.append(node_id)
            # Check if node was mitigated or broken (invalidated)
            elif path_node.node.state in (
                NODE_STATE_MITIGATED, NODE_STATE_BROKEN
            ):
                if node_id not in scenario.invalidated_nodes:
                    scenario.invalidated_nodes.append(node_id)

        # Remove nodes no longer in the scenario
        scenario.confirmed_nodes = [
            nid for nid in scenario.confirmed_nodes
            if nid in current_node_ids
        ]

    def _compute_probabilities(self, graph: LiquidityGraph) -> None:
        """Compute relative probabilities for BUY vs SELL."""
        buy_score = self.buy_scenario.score * self.buy_scenario.confidence / 100
        sell_score = self.sell_scenario.score * self.sell_scenario.confidence / 100

        total = buy_score + sell_score
        if total <= 0:
            self.buy_scenario.probability = 0.5
            self.sell_scenario.probability = 0.5
            return

        self.buy_scenario.probability = round(buy_score / total, 3)
        self.sell_scenario.probability = round(sell_score / total, 3)

    def _take_snapshot(self) -> None:
        """Take a snapshot for history tracking."""
        snapshot = {
            "bar": self.last_update_bar,
            "buy_prob": self.buy_scenario.probability,
            "sell_prob": self.sell_scenario.probability,
            "buy_score": self.buy_scenario.score,
            "sell_score": self.sell_scenario.score,
            "stability": self.scenario_stability,
            "ambiguous": self.is_ambiguous,
        }
        self.history.append(snapshot)
        # Keep last 100 snapshots
        if len(self.history) > 100:
            self.history = self.history[-100:]

    def format_status(self) -> str:
        """Human-readable status of the dynamic thesis."""
        lines = [
            f"DynamicThesis {self.symbol} {self.timeframe}",
            f"  BUY:  prob={self.buy_scenario.probability:.2f} "
            f"score={self.buy_scenario.score:.1f} "
            f"conf={self.buy_scenario.confidence:.0f} "
            f"stability={self.buy_scenario.stability:.2f}",
            f"  SELL: prob={self.sell_scenario.probability:.2f} "
            f"score={self.sell_scenario.score:.1f} "
            f"conf={self.sell_scenario.confidence:.0f} "
            f"stability={self.sell_scenario.stability:.2f}",
            f"  Ambiguous: {self.is_ambiguous}",
            f"  Best direction: {self.direction or 'NONE'}",
            f"  Updates: {self.update_count}",
        ]
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# Market Thesis Engine (static + dynamic support)
# ══════════════════════════════════════════════════════════════════

class MarketThesisEngine:
    """Engine that builds the liquidity DAG and detects scenarios.

    Supports both static (build + detect) and dynamic (update_on_candle)
    usage patterns.
    """

    def __init__(self, transition_model: Optional[TransitionModel] = None):
        self._transition_model = transition_model or HeuristicTransitionModel()

    def build_liquidity_graph(
        self,
        current_price: float,
        sweeps: list = None,
        order_blocks: list = None,
        fvgs: list = None,
        structure=None,
        equal_levels: list = None,
        external_levels: list = None,
        candle_quality=None,
        timeframe: str = "1h",
        current_bar: int = 0,
    ) -> LiquidityGraph:
        """Build a liquidity DAG from all detected objects."""
        graph = LiquidityGraph(
            current_price=current_price,
            timeframe=timeframe,
            current_bar=current_bar,
        )
        graph.set_transition_model(self._transition_model)

        # 1. Swing Points
        if structure:
            for sp in (getattr(structure, "swing_points", []) or []):
                ntype = "swing_high" if sp.type == "high" else "swing_low"
                graph.add_node(LiquidityNode(
                    type=ntype,
                    price=sp.price,
                    strength=0.5,
                    timeframe=timeframe,
                    timestamp=sp.timestamp,
                    distance_from_price_pct=(
                        abs(sp.price - current_price) / current_price * 100
                    ),
                ))

        # 2. BOS
        if structure and structure.last_bos:
            bos = structure.last_bos
            graph.add_node(LiquidityNode(
                type="bos",
                price=bos.level,
                strength=0.7,
                timeframe=timeframe,
                timestamp=bos.timestamp,
            ))

        # 3. CHoCH
        if structure and getattr(structure, "last_choch", None):
            choch = structure.last_choch
            graph.add_node(LiquidityNode(
                type="choch",
                price=choch.level,
                strength=0.6,
                timeframe=timeframe,
                timestamp=choch.timestamp,
            ))

        # 4. Sweeps
        for sweep in (sweeps or []):
            if not sweep.is_valid:
                continue
            graph.add_node(LiquidityNode(
                type="sweep",
                price=sweep.swept_level,
                strength=sweep.strength,
                timeframe=timeframe,
                state=NODE_STATE_BROKEN,
                displacement_atr=getattr(sweep, "displacement_after", 0.0),
                volume_ratio=getattr(sweep, "volume_ratio", 1.0),
                source=sweep,
            ))

        # 5. Order Blocks
        for ob in (order_blocks or []):
            if not ob.is_valid:
                continue
            state = NODE_STATE_MITIGATED if ob.mitigated else NODE_STATE_ACTIVE
            graph.add_node(LiquidityNode(
                type="ob",
                price=ob.midpoint,
                strength=normalize(ob.displacement_atr, 0, 3.0),
                timeframe=timeframe,
                state=state,
                displacement_atr=ob.displacement_atr,
                volume_ratio=ob.volume_ratio,
                source=ob,
            ))

        # 6. FVGs
        for fvg in (fvgs or []):
            avg_price = (fvg.top + fvg.bottom) / 2
            state = NODE_STATE_MITIGATED if fvg.filled else NODE_STATE_ACTIVE
            graph.add_node(LiquidityNode(
                type="fvg",
                price=avg_price,
                strength=normalize(fvg.size_pct, 0, 3.0),
                timeframe=timeframe,
                state=state,
                source=fvg,
            ))

        # 7. Equal Levels
        for el in (equal_levels or []):
            state = NODE_STATE_BROKEN if el.swept else NODE_STATE_ACTIVE
            graph.add_node(LiquidityNode(
                type=el.type,
                price=el.level,
                strength=el.strength,
                timeframe=timeframe,
                state=state,
                source=el,
            ))

        # 8. External Liquidity
        for ext in (external_levels or []):
            state = NODE_STATE_BROKEN if getattr(ext, "swept", False) else NODE_STATE_ACTIVE
            graph.add_node(LiquidityNode(
                type=ext.type,
                price=ext.level,
                strength=ext.strength,
                timeframe=timeframe,
                state=state,
                source=ext,
            ))

        # 9. Displacement
        if candle_quality and candle_quality.is_displacement:
            graph.add_node(LiquidityNode(
                type="displacement",
                price=current_price,
                strength=candle_quality.quality_score,
                timeframe=timeframe,
                displacement_atr=candle_quality.body_atr_ratio,
            ))

        # Infer edges
        self._infer_edges(graph)

        logger.debug(
            f"Liquidity graph: {len(graph.nodes)} nodes, "
            f"{sum(len(n.edges) for n in graph.nodes)} edges "
            f"for {timeframe}"
        )

        return graph

    def _infer_edges(self, graph: LiquidityGraph) -> None:
        """Infer typed, weighted edges between nodes."""
        by_type: dict[str, list[LiquidityNode]] = {}
        for n in graph.nodes:
            by_type.setdefault(n.type, []).append(n)

        sweeps = by_type.get("sweep", [])
        bos_list = by_type.get("bos", [])
        obs = by_type.get("ob", [])
        fvgs = by_type.get("fvg", [])
        displacements = by_type.get("displacement", [])
        externals = [n for n in graph.nodes if n.type in ("old_high", "old_low")]
        equals = [n for n in graph.nodes if n.type in ("equal_high", "equal_low")]

        # Rule 1: Sweep → BOS (causes)
        for s in sweeps:
            for b in bos_list:
                if not _same_direction(s, b):
                    continue
                if not _near(s.price, b.price, pct=0.03):
                    continue
                if not _temporal_order(s, b):
                    continue
                strength = (s.strength + b.strength) / 2
                graph.add_edge(s, b, "causes", strength)
                if b.created_by is None:
                    b.created_by = _node_id(s)

        # Rule 2: BOS → OB (causes)
        for b in bos_list:
            for ob in obs:
                if not _same_direction(b, ob):
                    continue
                if not _near(b.price, ob.price, pct=0.05):
                    continue
                if not _temporal_order(b, ob):
                    continue
                strength = (b.strength + ob.strength) / 2
                graph.add_edge(b, ob, "causes", strength)
                if ob.created_by is None:
                    ob.created_by = _node_id(b)

        # Rule 3: Displacement → FVG (causes)
        for d in displacements:
            for f in fvgs:
                if not _near(d.price, f.price, pct=0.03):
                    continue
                strength = (d.strength + f.strength) / 2
                graph.add_edge(d, f, "causes", strength)
                if f.created_by is None:
                    f.created_by = _node_id(d)

        # Rule 4: OB → FVG (causes)
        for ob in obs:
            for f in fvgs:
                if not _same_direction(ob, f):
                    continue
                if not _near(ob.price, f.price, pct=0.03):
                    continue
                if not _temporal_order(ob, f):
                    continue
                strength = (ob.strength + f.strength) / 2
                graph.add_edge(ob, f, "causes", strength)
                if f.created_by is None:
                    f.created_by = _node_id(ob)

        # Rule 5: FVG → External (targets)
        for f in fvgs:
            for ext in externals:
                if _is_bullish_fvg_targets(f, ext):
                    strength = (f.strength + ext.strength) / 2
                    graph.add_edge(f, ext, "targets", strength)
                    if ext.created_by is None:
                        ext.created_by = _node_id(f)

        # Rule 5b: OB → External (targets)
        for ob in obs:
            for ext in externals:
                if _ob_targets_external(ob, ext):
                    strength = (ob.strength + ext.strength) / 2
                    graph.add_edge(ob, ext, "targets", strength)
                    if ext.created_by is None:
                        ext.created_by = _node_id(ob)

        # Rule 6: Equal Levels as targets
        for f in fvgs:
            for eq in equals:
                if _is_bullish_fvg_targets(f, eq):
                    strength = (f.strength + eq.strength) / 2
                    graph.add_edge(f, eq, "targets", strength)
                    if eq.created_by is None:
                        eq.created_by = _node_id(f)

        # Rule 7: Sweep invalidates opposite OB (mitigates)
        for s in sweeps:
            for ob in obs:
                if _sweep_invalidates_ob(s, ob):
                    strength = s.strength
                    prob = min(1.0, s.strength * 1.2)
                    graph.add_edge(s, ob, "mitigates", strength, prob)
                    ob.invalidated_by = _node_id(s)
                    ob.state = NODE_STATE_MITIGATED

    def detect_scenarios(
        self,
        graph: LiquidityGraph,
        direction: Optional[str] = None,
        atr: float = 0.0,
    ) -> list[MarketThesis]:
        """Detect complete, validated scenarios from the liquidity DAG.
        
        Args:
            graph: LiquidityGraph with nodes and edges
            direction: optional filter ("buy", "sell", or None for both)
            atr: current ATR value for scoring
        """
        scenarios: list[MarketThesis] = []
        directions = [direction] if direction else ["buy", "sell"]

        for d in directions:
            if d == "buy":
                roots = [
                    n for n in graph.nodes
                    if n.type in ("sweep", "bos") and n.is_valid
                ]
                roots = [
                    n for n in roots
                    if n.price < graph.current_price or n.type == "sweep"
                ]
            else:
                roots = [
                    n for n in graph.nodes
                    if n.type in ("sweep", "bos") and n.is_valid
                ]
                roots = [
                    n for n in roots
                    if n.price > graph.current_price or n.type == "sweep"
                ]

            for root in roots:
                chain = self._build_chain(root, graph, direction=d)
                if len(chain) < 2:
                    continue

                components = [n.type for n in chain]
                is_valid, reason = validate_scenario(components, d)
                if not is_valid:
                    logger.debug(
                        f"Scenario rejected: "
                        f"{' → '.join(components)} — {reason}"
                    )
                    continue

                thesis = self._chain_to_thesis(chain, graph, direction=d, atr=atr)
                if thesis:
                    scenarios.append(thesis)

        # Pattern-based scenarios
        pattern_scenarios = self._detect_pattern_scenarios(graph, direction, atr)
        for thesis in pattern_scenarios:
            components = thesis.components
            is_valid, reason = validate_scenario(components, thesis.direction)
            if is_valid:
                scenarios.append(thesis)
            else:
                logger.debug(f"Pattern scenario rejected: {reason}")

        scenarios = self._deduplicate_scenarios(scenarios)
        scenarios.sort(key=lambda t: t.quality_confidence_ratio, reverse=True)

        return scenarios

    def build_hypothesis_set(
        self,
        graph: LiquidityGraph,
        direction: Optional[str] = None,
        atr: float = 0.0,
        current_bar: int = 0,
    ) -> "HypothesisSet":
        """Build a HypothesisSet from all detected scenarios.

        This is the bridge between the old MarketThesis system and the new
        Hypothesis Engine. Generates ALL valid hypotheses without selection.

        Args:
            graph: LiquidityGraph with nodes and edges
            direction: optional filter ("buy", "sell", or None for both)
            atr: current ATR for scoring
            current_bar: current bar index for decay calculation

        Returns:
            HypothesisSet with all competing hypotheses
        """
        from strategy.hypothesis import (
            Hypothesis,
            HypothesisSet,
            ScenarioComponent,
            compute_exponential_decay,
        )

        # Detect all scenarios (old system)
        theses = self.detect_scenarios(graph, direction=direction, atr=atr)

        hset = HypothesisSet(
            symbol=graph.symbol or "",
            timeframe=graph.timeframe or "",
            created_at_bar=current_bar,
        )

        for i, thesis in enumerate(theses):
            # Determine narrative type from thesis components
            narrative_type = self._classify_narrative(thesis)

            # Compute decay from node states
            node_ids = []
            node_state_scores = []
            if thesis.liquidity_path:
                for path_node in thesis.liquidity_path.nodes:
                    nid = path_node.node_id if hasattr(path_node, "node_id") else None
                    if nid:
                        node_ids.append(nid)
                        graph_node = graph.get_node(nid)
                        if graph_node:
                            node_state_scores.append(graph_node.state_score)

            decay = compute_exponential_decay(
                age_bars=current_bar - (graph.last_update_bar or current_bar),
                node_state_scores=node_state_scores,
            )

            # Build components
            components = tuple(
                ScenarioComponent(
                    id=f"{thesis.direction}_{i}_{j}",
                    type=comp_type,
                    description=f"{comp_type} in {thesis.direction} narrative",
                )
                for j, comp_type in enumerate(thesis.components)
            )

            # Compute quality from thesis score
            quality = min(100.0, max(0.0, thesis.scenario_score))

            # Compute confidence
            confidence = min(1.0, max(0.0, thesis.confidence))

            hypothesis = Hypothesis(
                id=f"h_{graph.symbol}_{current_bar}_{i}",
                direction=thesis.direction,
                narrative_type=narrative_type,
                name=thesis.scenario,
                description=f"{thesis.direction} {thesis.scenario}",
                quality=quality,
                confidence=confidence,
                decay_factor=decay,
                entry_price=thesis.entry_zone[0] if thesis.entry_zone else graph.current_price,
                invalidation_price=thesis.invalidation_price,
                target_price=thesis.target_price,
                rr_ratio=thesis.expected_rr,
                components=components,
                node_ids=tuple(node_ids),
                created_at_bar=current_bar,
                current_bar=current_bar,
                source="chain",
                expected_rr=thesis.expected_rr,
                expected_p_tp=confidence,  # proxy for probability
            )

            hset.add(hypothesis)

        # Also add pattern-based hypotheses
        pattern_theses = self._detect_pattern_scenarios(graph, direction, atr)
        for i, thesis in enumerate(pattern_theses):
            narrative_type = self._classify_narrative(thesis)
            components = tuple(
                ScenarioComponent(
                    id=f"pat_{thesis.direction}_{i}_{j}",
                    type=comp_type,
                    description=f"{comp_type} in pattern narrative",
                )
                for j, comp_type in enumerate(thesis.components)
            )

            hypothesis = Hypothesis(
                id=f"h_pat_{graph.symbol}_{current_bar}_{i}",
                direction=thesis.direction,
                narrative_type=narrative_type,
                name=thesis.scenario,
                description=f"{thesis.direction} {thesis.scenario} (pattern)",
                quality=min(100.0, max(0.0, thesis.scenario_score)),
                confidence=min(1.0, max(0.0, thesis.confidence)),
                decay_factor=1.0,  # fresh pattern
                entry_price=thesis.entry_zone[0] if thesis.entry_zone else graph.current_price,
                invalidation_price=thesis.invalidation_price,
                target_price=thesis.target_price,
                rr_ratio=thesis.expected_rr,
                components=components,
                node_ids=(),
                created_at_bar=current_bar,
                current_bar=current_bar,
                source="pattern",
                expected_rr=thesis.expected_rr,
                expected_p_tp=thesis.confidence,
            )
            hset.add(hypothesis)

        logger.debug(
            f"build_hypothesis_set: {graph.symbol} {graph.timeframe} "
            f"→ {len(hset)} hypotheses"
        )
        return hset

    def _classify_narrative(self, thesis: "MarketThesis") -> str:
        """Classify a MarketThesis into a NarrativeType."""
        components = set(thesis.components) if thesis.components else set()
        direction = thesis.direction

        # Map component combinations to narrative types
        if "sweep" in components and "bos" in components and "ob" in components and "fvg" in components:
            return "sweep_bos_ob_fvg"
        if "sweep" in components and "bos" in components and "ob" in components:
            return "sweep_bos_ob"
        if "bos" in components and "ob" in components and "fvg" in components:
            return "bos_ob_fvg"
        if "choch" in components and "ob" in components:
            return "choch_ob"
        if "ob" in components and len(components) <= 2:
            return "ob_retest"
        if "sweep" in components and "displacement" in components:
            return "liquidity_grab"
        if "bos" in components and "ob" in components:
            return "trend_continuation"
        if "choch" in components:
            return "reversal"

        # Default based on thesis name
        name_lower = thesis.scenario.lower() if thesis.scenario else ""
        if "retest" in name_lower:
            return "ob_retest"
        if "reversal" in name_lower:
            return "reversal"
        if "continuation" in name_lower:
            return "trend_continuation"

        return "sweep_bos_ob"  # default

    def _build_chain(
        self,
        root: LiquidityNode,
        graph: LiquidityGraph,
        direction: str,
        max_depth: int = 6,
    ) -> list[LiquidityNode]:
        """Build a chain of connected nodes following 'causes' edges."""
        chain = [root]
        visited = {_node_id(root)}
        current = root

        for _ in range(max_depth):
            next_node = None
            for edge in current.get_edges("causes"):
                if edge.target_id not in visited:
                    node = graph.get_node(edge.target_id)
                    if node and node.is_valid:
                        next_node = node
                        break

            if not next_node:
                for edge in current.get_edges("targets"):
                    if edge.target_id not in visited:
                        node = graph.get_node(edge.target_id)
                        if node and node.is_valid:
                            next_node = node
                            break

            if not next_node:
                break

            chain.append(next_node)
            visited.add(_node_id(next_node))
            current = next_node

        return chain

    def _chain_to_thesis(
        self,
        chain: list[LiquidityNode],
        graph: LiquidityGraph,
        direction: str,
        atr: float = 0.0,
    ) -> Optional[MarketThesis]:
        """Convert a chain of nodes into a MarketThesis with ScenarioScore."""
        if len(chain) < 2:
            return None

        components = [n.type for n in chain]

        # Build liquidity path
        path_nodes = []
        for i, node in enumerate(chain):
            if i == 0:
                role = "trigger"
                reason = f"{node.type} initiates the scenario"
            elif node.type in ("ob", "fvg"):
                role = "confirmation"
                reason = f"{node.type} confirms the direction"
            elif node.type in (
                "old_high", "old_low", "equal_high", "equal_low"
            ):
                role = "target"
                reason = f"external liquidity at {node.price:.4f}"
            elif node.type == "displacement":
                role = "confirmation"
                reason = "displacement confirms momentum"
            else:
                role = "confirmation"
                reason = f"{node.type} in the chain"

            path_nodes.append(LiquidityPathNode(
                node=node, role=role, reason=reason,
            ))

        # Find invalidation and target
        invalidation_node = None
        target_node = None

        if direction == "buy":
            candidates_below = [
                n for n in chain
                if n.price < graph.current_price
                and n.type in ("swing_low", "ob")
            ]
            if candidates_below:
                invalidation_node = min(candidates_below, key=lambda n: n.price)

            candidates_above = [
                n for n in chain
                if n.price > graph.current_price
                and n.type in ("old_high", "equal_high", "fvg")
            ]
            if candidates_above:
                target_node = max(candidates_above, key=lambda n: n.price)
        else:
            candidates_above = [
                n for n in chain
                if n.price > graph.current_price
                and n.type in ("swing_high", "ob")
            ]
            if candidates_above:
                invalidation_node = max(candidates_above, key=lambda n: n.price)

            candidates_below = [
                n for n in chain
                if n.price < graph.current_price
                and n.type in ("old_low", "equal_low", "fvg")
            ]
            if candidates_below:
                target_node = min(candidates_below, key=lambda n: n.price)

        # Build path
        path = LiquidityPath(
            direction=direction,
            nodes=path_nodes,
            target_node=target_node,
            invalidation_node=invalidation_node,
        )

        # Score with component breakdown
        score_breakdown = self._score_scenario_breakdown(
            chain, graph, direction, atr
        )

        # Calculate confidence
        confidence = self._calculate_confidence(chain, graph, direction, atr)

        # Entry zone
        confirmation_nodes = [
            n for n in chain if n.type in ("ob", "fvg")
        ]
        if confirmation_nodes:
            last_confirm = confirmation_nodes[-1]
            entry_zone = (
                last_confirm.price * 0.998,
                last_confirm.price * 1.002,
            )
        else:
            entry_zone = (
                graph.current_price * 0.998,
                graph.current_price * 1.002,
            )

        # Build reasons
        reasons = []
        reasons.append(f"Scenario: {' → '.join(components)}")
        reasons.append(f"Score: {score_breakdown.total:.0f}/100")
        reasons.append(f"Confidence: {confidence:.0f}/100")
        if invalidation_node:
            reasons.append(
                f"Invalidation: {invalidation_node.type} "
                f"@ {invalidation_node.price:.4f}"
            )
        if target_node:
            reasons.append(
                f"Target: {target_node.type} "
                f"@ {target_node.price:.4f}"
            )

        # Expected RR
        invalid_price = invalidation_node.price if invalidation_node else 0
        target_price = target_node.price if target_node else 0
        entry_mid = (entry_zone[0] + entry_zone[1]) / 2
        if invalid_price > 0 and target_price > 0 and direction == "buy":
            risk = entry_mid - invalid_price
            reward = target_price - entry_mid
            expected_rr = reward / risk if risk > 0 else 0
        elif invalid_price > 0 and target_price > 0 and direction == "sell":
            risk = invalid_price - entry_mid
            reward = entry_mid - target_price
            expected_rr = reward / risk if risk > 0 else 0
        else:
            expected_rr = 0

        scenario_name = f"{direction.upper()}: {' → '.join(components[:4])}"

        return MarketThesis(
            direction=direction,
            scenario=scenario_name,
            components=components,
            scenario_score=score_breakdown.total,
            confidence=confidence,
            score_breakdown=score_breakdown,
            liquidity_path=path,
            entry_zone=entry_zone,
            invalidation_price=invalid_price,
            invalidation_reason=(
                invalidation_node.type if invalidation_node else ""
            ),
            target_price=target_price,
            target_reason=target_node.type if target_node else "",
            expected_rr=round(expected_rr, 2),
            reasons=reasons,
        )

    def _score_scenario_breakdown(
        self,
        chain: list[LiquidityNode],
        graph: LiquidityGraph,
        direction: str,
        atr: float = 0.0,
    ) -> ScenarioScore:
        """Score the scenario with component breakdown.
        
        Uses causal chain quality scoring instead of summing components.
        The score represents the quality of the entire causal chain.
        """
        if not chain:
            return ScenarioScore()

        breakdown = ScenarioScore()

        # Use the new causal chain scoring
        chain_score = _chain_causal_score(chain, direction, atr)

        # Still collect per-component contributions for diagnostics
        for node in chain:
            contrib = self._score_node_contribution(node, graph, direction)

            if node.type == "ob":
                breakdown.ob_contribution += contrib
            elif node.type == "sweep":
                breakdown.sweep_contribution += contrib
            elif node.type == "bos":
                breakdown.bos_contribution += contrib
            elif node.type == "fvg":
                breakdown.fvg_contribution += contrib
            elif node.type in (
                "old_high", "old_low", "equal_high", "equal_low"
            ):
                breakdown.liquidity_contribution += contrib
            elif node.type in ("swing_high", "swing_low"):
                breakdown.liquidity_contribution += contrib * 0.5

        # Override liquidity_contribution with chain score
        # This is the primary score used for ranking
        breakdown.liquidity_contribution = chain_score

        return breakdown

    def _score_node_contribution(
        self,
        node: LiquidityNode,
        graph: LiquidityGraph,
        direction: str,
    ) -> float:
        """Score a single node's contribution."""
        base = node.quality_score if node.quality_score > 0 else 50.0
        comp_weight = w.SCENARIO_COMPONENT_WEIGHTS.get(node.type, 0.5)
        strength_factor = node.strength if node.strength > 0 else 0.5

        displacement_bonus = 0.0
        if node.type in ("ob", "fvg") and node.displacement_atr > 1.5:
            displacement_bonus = 5.0

        active_bonus = 3.0 if node.state == NODE_STATE_ACTIVE else 0.0

        contribution = (
            base * comp_weight * 0.3
            + strength_factor * 10.0
            + displacement_bonus
            + active_bonus
        )

        return min(25.0, max(0.0, contribution))

    def _calculate_confidence(
        self,
        chain: list[LiquidityNode],
        graph: LiquidityGraph,
        direction: str,
        atr: float = 0.0,
    ) -> float:
        """Calculate confidence in the scenario.
        
        Confidence is now based on chain quality, not sum of factors.
        """
        if not chain or len(chain) < 2:
            return 0.0

        # Use chain quality as primary confidence metric
        chain_quality = _chain_causal_score(chain, direction, atr)

        # Adjust for node validity
        active_count = sum(1 for n in chain if n.is_valid)
        activation = active_count / len(chain)

        # Final confidence = chain quality * activation factor
        confidence = chain_quality * (0.7 + 0.3 * activation)

        return round(min(100.0, max(0.0, confidence)), 1)

    def _detect_pattern_scenarios(
        self,
        graph: LiquidityGraph,
        direction: Optional[str] = None,
        atr: float = 0.0,
    ) -> list[MarketThesis]:
        """Detect scenarios based on common ICT patterns."""
        scenarios = []
        directions = [direction] if direction else ["buy", "sell"]

        for d in directions:
            if d == "buy":
                sweeps = [
                    n for n in graph.nodes
                    if n.type == "sweep" and n.is_valid
                ]
                obs = [
                    n for n in graph.nodes
                    if n.type == "ob" and n.is_valid
                    and n.price < graph.current_price
                ]
                fvgs = [
                    n for n in graph.nodes
                    if n.type == "fvg" and n.is_valid
                    and n.price < graph.current_price
                ]
                targets = [
                    n for n in graph.nodes
                    if n.type in ("old_high", "equal_high")
                    and n.is_valid and n.price > graph.current_price
                ]

                if obs and targets:
                    chain = []
                    if sweeps:
                        chain.append(sweeps[0])
                    chain.append(obs[0])
                    if fvgs:
                        chain.append(fvgs[0])
                    chain.append(targets[0])

                    thesis = self._chain_to_thesis(chain, graph, direction=d, atr=atr)
                    if thesis:
                        scenarios.append(thesis)
            else:
                sweeps = [
                    n for n in graph.nodes
                    if n.type == "sweep" and n.is_valid
                ]
                obs = [
                    n for n in graph.nodes
                    if n.type == "ob" and n.is_valid
                    and n.price > graph.current_price
                ]
                fvgs = [
                    n for n in graph.nodes
                    if n.type == "fvg" and n.is_valid
                    and n.price > graph.current_price
                ]
                targets = [
                    n for n in graph.nodes
                    if n.type in ("old_low", "equal_low")
                    and n.is_valid and n.price < graph.current_price
                ]

                if obs and targets:
                    chain = []
                    if sweeps:
                        chain.append(sweeps[0])
                    chain.append(obs[0])
                    if fvgs:
                        chain.append(fvgs[0])
                    chain.append(targets[0])

                    thesis = self._chain_to_thesis(chain, graph, direction=d, atr=atr)
                    if thesis:
                        scenarios.append(thesis)

        return scenarios

    def _deduplicate_scenarios(
        self, scenarios: list[MarketThesis]
    ) -> list[MarketThesis]:
        seen = set()
        unique = []
        for t in scenarios:
            key = (t.direction, tuple(sorted(set(t.components))))
            if key not in seen:
                seen.add(key)
                unique.append(t)
        return unique

    def find_best_invalidation(
        self,
        graph: LiquidityGraph,
        direction: str,
        entry_price: float,
        atr: float = 0.0,
    ) -> Optional[LiquidityNode]:
        if direction == "buy":
            candidates = graph.nodes_below(entry_price)
        else:
            candidates = graph.nodes_above(entry_price)

        if not candidates:
            if atr > 0:
                fallback_price = (
                    entry_price - atr * 1.5 if direction == "buy"
                    else entry_price + atr * 1.5
                )
                return LiquidityNode(
                    type="swing_low" if direction == "buy" else "swing_high",
                    price=fallback_price,
                    quality_score=20.0,
                    state=NODE_STATE_ACTIVE,
                )
            return None

        min_dist = entry_price * 0.005
        scored = []
        for node in candidates:
            dist = abs(node.price - entry_price)
            if dist < min_dist:
                continue

            base_score = node.quality_score if node.quality_score > 0 else 50.0
            dist_pct = dist / entry_price

            if 0.005 <= dist_pct <= 0.03:
                proximity_bonus = 15.0
            elif 0.03 < dist_pct <= 0.05:
                proximity_bonus = 10.0
            elif dist_pct > 0.05:
                proximity_bonus = 0.0
            else:
                proximity_bonus = 5.0

            type_bonus = 0.0
            if node.type == "ob":
                type_bonus = 10.0
            elif node.type in ("swing_low", "swing_high"):
                type_bonus = 5.0
            elif node.type == "bos":
                type_bonus = 8.0

            total = base_score + proximity_bonus + type_bonus
            scored.append((node, total))

        if not scored:
            return None

        scored.sort(key=lambda x: x[1], reverse=True)
        best_node = scored[0][0]
        best_node.quality_score = scored[0][1]
        return best_node

    def find_best_target(
        self,
        graph: LiquidityGraph,
        direction: str,
        entry_price: float,
        atr: float = 0.0,
        invalidation_price: float = 0.0,
    ) -> Optional[LiquidityNode]:
        if direction == "buy":
            candidates = graph.nodes_above(entry_price)
        else:
            candidates = graph.nodes_below(entry_price)

        if not candidates:
            if atr > 0:
                fallback_price = (
                    entry_price + atr * 2.0 if direction == "buy"
                    else entry_price - atr * 2.0
                )
                return LiquidityNode(
                    type="old_high" if direction == "buy" else "old_low",
                    price=fallback_price,
                    quality_score=30.0,
                    state=NODE_STATE_ACTIVE,
                )
            return None

        min_distance = atr * 1.0 if atr > 0 else entry_price * 0.01

        scored = []
        for node in candidates:
            dist = abs(node.price - entry_price)
            if dist < min_distance:
                continue

            base_score = (
                node.quality_score if node.quality_score > 0 else 50.0
            )

            type_bonus = 0.0
            if node.type in ("old_high", "old_low"):
                type_bonus = 15.0
            elif node.type in ("equal_high", "equal_low"):
                type_bonus = 12.0
            elif node.type == "ob":
                type_bonus = 10.0
            elif node.type == "fvg":
                type_bonus = 8.0

            if invalidation_price > 0 and direction == "buy":
                risk = entry_price - invalidation_price
                reward = node.price - entry_price
                rr = reward / risk if risk > 0 else 0
            elif invalidation_price > 0 and direction == "sell":
                risk = invalidation_price - entry_price
                reward = entry_price - node.price
                rr = reward / risk if risk > 0 else 0
            else:
                rr = 0

            rr_bonus = min(rr / 3.0, 1.0) * 15.0

            total = base_score + type_bonus + rr_bonus
            scored.append((node, total))

        if not scored:
            return None

        scored.sort(key=lambda x: x[1], reverse=True)
        best_node = scored[0][0]
        best_node.quality_score = scored[0][1]
        return best_node

    def evaluate_trade_opportunity(
        self,
        graph: LiquidityGraph,
        direction: str,
        entry_price: float,
        atr: float = 0.0,
        symbol: str = "",
        timeframe: str = "1h",
    ) -> Optional[TradeOpportunity]:
        """Main entry point. Returns backward-compatible TradeOpportunity."""
        scenarios = self.detect_scenarios(graph, direction=direction, atr=atr)
        if not scenarios:
            logger.debug(f"No scenarios detected for {symbol} {timeframe}")
            return None

        best_thesis = scenarios[0]

        if not best_thesis.has_invalidation:
            inv_node = self.find_best_invalidation(
                graph, direction, entry_price, atr
            )
            if inv_node:
                best_thesis.invalidation_price = inv_node.price
                best_thesis.invalidation_reason = inv_node.type

        if not best_thesis.has_target:
            target_node = self.find_best_target(
                graph, direction, entry_price, atr,
                invalidation_price=best_thesis.invalidation_price,
            )
            if target_node:
                best_thesis.target_price = target_node.price
                best_thesis.target_reason = target_node.type

        if not best_thesis.has_invalidation or not best_thesis.has_target:
            logger.debug(
                f"Incomplete scenario: inv={best_thesis.has_invalidation} "
                f"target={best_thesis.has_target} for {symbol} {timeframe}"
            )
            return None

        if direction == "buy":
            risk = entry_price - best_thesis.invalidation_price
            reward = best_thesis.target_price - entry_price
        else:
            risk = best_thesis.invalidation_price - entry_price
            reward = entry_price - best_thesis.target_price

        rr = reward / risk if risk > 0 else 0

        reasons = list(best_thesis.reasons)
        reasons.append(f"RR: 1:{rr:.1f}")
        reasons.append(
            f"Path length: "
            f"{best_thesis.liquidity_path.path_length if best_thesis.liquidity_path else 0}"
        )

        return TradeOpportunity(
            direction=direction,
            symbol=symbol,
            timeframe=timeframe,
            thesis=best_thesis,
            scenario_score=best_thesis.scenario_score,
            expected_path=best_thesis.liquidity_path,
            expected_probability=best_thesis.scenario_score / 100.0,
            expected_target=best_thesis.target_price,
            invalidation=best_thesis.invalidation_price,
            reasons=reasons,
        )

    def evaluate_scenarios(
        self,
        graph: LiquidityGraph,
        direction: str,
        entry_price: float,
        atr: float = 0.0,
        symbol: str = "",
        timeframe: str = "1h",
        max_alternatives: int = 3,
    ) -> list[Scenario]:
        """Evaluate and return multiple ranked scenarios."""
        theses = self.detect_scenarios(graph, direction=direction, atr=atr)
        if not theses:
            logger.debug(f"No scenarios detected for {symbol} {timeframe}")
            return []

        scenarios: list[Scenario] = []

        for i, thesis in enumerate(theses[:max_alternatives]):
            if not thesis.has_invalidation:
                inv_node = self.find_best_invalidation(
                    graph, direction, entry_price, atr
                )
                if inv_node:
                    thesis.invalidation_price = inv_node.price
                    thesis.invalidation_reason = inv_node.type

            if not thesis.has_target:
                target_node = self.find_best_target(
                    graph, direction, entry_price, atr,
                    invalidation_price=thesis.invalidation_price,
                )
                if target_node:
                    thesis.target_price = target_node.price
                    thesis.target_reason = target_node.type

            if not thesis.has_invalidation or not thesis.has_target:
                continue

            if direction == "buy":
                risk = entry_price - thesis.invalidation_price
                reward = thesis.target_price - entry_price
            else:
                risk = thesis.invalidation_price - entry_price
                reward = entry_price - thesis.target_price

            rr = reward / risk if risk > 0 else 0

            scenario = Scenario(
                direction=direction,
                symbol=symbol,
                timeframe=timeframe,
                thesis=thesis,
                score_breakdown=thesis.score_breakdown or ScenarioScore(),
                explanation=self._build_explanation(thesis, rr),
                alternative_rank=i,
                entry_price=entry_price,
                invalidation_price=thesis.invalidation_price,
                target_price=thesis.target_price,
                expected_rr=round(rr, 2),
            )
            scenarios.append(scenario)

        return scenarios

    def _build_explanation(
        self, thesis: MarketThesis, rr: float
    ) -> str:
        parts = [
            f"{'BUY' if thesis.direction == 'buy' else 'SELL'}: "
            f"{' → '.join(thesis.components)}",
            f"Score: {thesis.scenario_score:.1f}/100, "
            f"Confidence: {thesis.confidence:.0f}/100",
            f"RR: 1:{rr:.1f}",
        ]
        if thesis.score_breakdown:
            bd = thesis.score_breakdown.breakdown()
            parts.append(
                f"Components: OB={bd['ob']:.1f} "
                f"Sweep={bd['sweep']:.1f} BOS={bd['bos']:.1f} "
                f"FVG={bd['fvg']:.1f} Liq={bd['liquidity']:.1f} "
                f"HTF={bd['htf']:.1f}"
            )
        return " | ".join(parts)


# ══════════════════════════════════════════════════════════════════
# Helper functions
# ══════════════════════════════════════════════════════════════════

def _node_id(node: LiquidityNode) -> str:
    return f"{node.type}_{node.price:.6f}"


def _same_direction(a: LiquidityNode, b: LiquidityNode) -> bool:
    return True


def _near(price_a: float, price_b: float, pct: float = 0.03) -> bool:
    if price_a == 0:
        return False
    return abs(price_a - price_b) / abs(price_a) < pct


def _freshness_score(age_bars: int, half_life: int = 15) -> float:
    """Exponential decay freshness score.
    
    Returns [0, 1]. Half-life controls how fast score decays:
    - half_life=10: 50% decay in 10 bars, ~6% at 40 bars
    - half_life=15: 50% decay in 15 bars, ~16% at 40 bars
    - half_life=20: 50% decay in 20 bars, ~25% at 40 bars
    """
    import math
    return math.exp(-0.693 * age_bars / half_life)


def _atr_distance(price_a: float, price_b: float, atr: float) -> float:
    """Distance between two prices in ATR units.
    
    Returns absolute distance / ATR. If ATR <= 0, returns 0.
    """
    if atr <= 0:
        return 0.0
    return abs(price_a - price_b) / atr


def _chain_causal_score(chain: list, direction: str, atr: float = 0.0) -> float:
    """Score the quality of the entire causal chain.
    
    Instead of summing component scores, this evaluates:
    1. Chain completeness (all expected links present)
    2. Link quality (each link has causal edge)
    3. Freshness (recent events score higher)
    4. Spatial coherence (distances in ATR units)
    
    Args:
        chain: list of LiquidityNode in causal order
        direction: "buy" or "sell"
        atr: current ATR value for distance normalization
    
    Returns [0, 100].
    """
    if not chain or len(chain) < 2:
        return 0.0

    score = 0.0

    # 1. Chain completeness (0-30)
    # Expected: trigger → confirmation → target
    has_trigger = any(n.type in ("sweep", "bos") for n in chain)
    has_confirm = any(n.type in ("ob", "fvg") for n in chain)
    has_target = any(
        n.type in ("old_high", "old_low", "equal_high", "equal_low")
        for n in chain
    )
    completeness = sum([has_trigger, has_confirm, has_target]) / 3.0
    score += completeness * 30.0

    # 2. Link quality (0-30) — causal edges exist between consecutive nodes
    causal_edges = 0
    for i in range(1, len(chain)):
        prev_node = chain[i - 1]
        curr_node = chain[i]
        # Check if there's a causal edge from prev to curr
        for edge in prev_node.get_edges("causes"):
            if edge.target_id == _node_id(curr_node):
                causal_edges += 1
                break
        else:
            # Check if there's a "targets" edge
            for edge in prev_node.get_edges("targets"):
                if edge.target_id == _node_id(curr_node):
                    causal_edges += 1
                    break
            else:
                # Check created_by attribute for implicit causality
                if (hasattr(curr_node, "created_by") and curr_node.created_by
                        and curr_node.created_by == _node_id(prev_node)):
                    causal_edges += 1

    if len(chain) > 1:
        link_quality = causal_edges / (len(chain) - 1)
    else:
        link_quality = 0.0
    score += link_quality * 30.0

    # 3. Freshness (0-25) — exponential decay on age
    freshest = 0.0
    for node in chain:
        age = getattr(node, "age_bars", 0) or 0
        fs = _freshness_score(age, half_life=15)
        freshest = max(freshest, fs)
    score += freshest * 25.0

    # 4. Spatial coherence (0-15) — distances in ATR units
    # OB/FVG should be within 2-5 ATR of trigger, target should be 1-3 ATR away
    if atr > 0:
        trigger_nodes = [n for n in chain if n.type in ("sweep", "bos")]
        confirm_nodes = [n for n in chain if n.type in ("ob", "fvg")]
        target_nodes = [n for n in chain if n.type in (
            "old_high", "old_low", "equal_high", "equal_low"
        )]

        spatial_score = 0.0
        spatial_count = 0

        if trigger_nodes and confirm_nodes:
            dist = _atr_distance(
                trigger_nodes[0].price, confirm_nodes[0].price, atr
            )
            # Ideal: 0.5-3 ATR
            if 0.5 <= dist <= 3.0:
                spatial_score += 1.0
            elif dist < 0.5:
                spatial_score += 0.5
            else:
                spatial_score += max(0.0, 1.0 - (dist - 3.0) * 0.2)
            spatial_count += 1

        if confirm_nodes and target_nodes:
            dist = _atr_distance(
                confirm_nodes[-1].price, target_nodes[0].price, atr
            )
            # Ideal: 1-5 ATR
            if 1.0 <= dist <= 5.0:
                spatial_score += 1.0
            elif dist < 1.0:
                spatial_score += 0.5
            else:
                spatial_score += max(0.0, 1.0 - (dist - 5.0) * 0.15)
            spatial_count += 1

        if spatial_count > 0:
            score += (spatial_score / spatial_count) * 15.0
    else:
        # No ATR available, give partial credit
        score += 7.5

    return round(min(100.0, max(0.0, score)), 1)


def _temporal_order(
    cause: LiquidityNode, effect: LiquidityNode
) -> bool:
    if cause.timestamp is None or effect.timestamp is None:
        return True
    try:
        return cause.timestamp <= effect.timestamp
    except TypeError:
        return True


def _is_bullish_fvg_targets(
    fvg: LiquidityNode, target: LiquidityNode
) -> bool:
    if fvg.type == "fvg":
        return target.price > fvg.price
    return False


def _ob_targets_external(
    ob: LiquidityNode, ext: LiquidityNode
) -> bool:
    if ob.type == "ob":
        return ext.price > ob.price
    return False


def _sweep_invalidates_ob(
    sweep: LiquidityNode, ob: LiquidityNode
) -> bool:
    if not _near(sweep.price, ob.price, pct=0.05):
        return False

    ob_source = ob.source
    if ob_source and hasattr(ob_source, "type"):
        ob_direction = getattr(ob_source, "type", "unknown")
    else:
        ob_direction = "unknown"

    sweep_source = sweep.source
    if sweep_source and hasattr(sweep_source, "type"):
        sweep_direction = getattr(sweep_source, "type", "unknown")
    else:
        sweep_direction = "unknown"

    if ob_direction != "unknown" and sweep_direction != "unknown":
        if ob_direction == "bullish" and sweep_direction == "bearish":
            return True
        if ob_direction == "bearish" and sweep_direction == "bullish":
            return True
        return False

    if sweep.price > ob.price:
        return True
    return False


# ══════════════════════════════════════════════════════════════════
# Scenario Validator
# ══════════════════════════════════════════════════════════════════

VALID_BUY_CHAINS = [
    ["sweep", "bos", "ob", "fvg", "old_high"],
    ["sweep", "bos", "ob", "old_high"],
    ["sweep", "bos", "fvg", "old_high"],
    ["sweep", "ob", "fvg", "old_high"],
    ["sweep", "bos", "ob", "equal_high"],
    ["sweep", "bos", "fvg", "equal_high"],
    ["bos", "ob", "fvg", "old_high"],
    ["bos", "ob", "old_high"],
    ["bos", "fvg", "old_high"],
    ["bos", "ob", "equal_high"],
    ["sweep", "ob", "old_high"],
    ["sweep", "fvg", "old_high"],
    ["bos", "ob", "old_high"],
]

VALID_SELL_CHAINS = [
    ["sweep", "bos", "ob", "fvg", "old_low"],
    ["sweep", "bos", "ob", "old_low"],
    ["sweep", "bos", "fvg", "old_low"],
    ["sweep", "ob", "fvg", "old_low"],
    ["sweep", "bos", "ob", "equal_low"],
    ["sweep", "bos", "fvg", "equal_low"],
    ["bos", "ob", "fvg", "old_low"],
    ["bos", "ob", "old_low"],
    ["bos", "fvg", "old_low"],
    ["bos", "ob", "equal_low"],
    ["sweep", "ob", "old_low"],
    ["sweep", "fvg", "old_low"],
    ["bos", "ob", "old_low"],
]


def validate_scenario(
    components: list[str], direction: str
) -> tuple[bool, str]:
    """Validate that a scenario has proper internal ICT causal chain.
    
    Enforces causal chain: Sweep/BOS → OB/FVG → Target
    Each link must causally connect to the next.
    """
    if len(components) < 2:
        return False, "too few components"

    triggers = {"sweep", "bos"}
    if not any(c in triggers for c in components):
        return False, "no trigger (need sweep or BOS)"

    confirmations = {"ob", "fvg"}
    if not any(c in confirmations for c in components):
        return False, "no confirmation (need OB or FVG)"

    targets = {"old_high", "old_low", "equal_high", "equal_low"}
    if not any(c in targets for c in components):
        return False, "no target (need external/equal level)"

    # Enforce causal chain order
    # Valid chains: Sweep→BOS→OB→FVG→Target or subsets
    first_trigger = next(
        (i for i, c in enumerate(components) if c in triggers), None
    )
    first_confirm = next(
        (i for i, c in enumerate(components) if c in confirmations), None
    )
    first_target = next(
        (i for i, c in enumerate(components) if c in targets), None
    )

    if first_trigger is not None and first_confirm is not None:
        if first_trigger > first_confirm:
            return False, (
                "trigger comes after confirmation (invalid chain order)"
            )

    if first_trigger is not None and first_target is not None:
        if first_trigger > first_target:
            return False, (
                "trigger comes after target (invalid chain order)"
            )

    # Check causal connectivity: each non-trigger must have a preceding trigger
    # or confirmation that logically precedes it
    for i, comp in enumerate(components):
        if comp in triggers:
            continue  # triggers are roots

        # Find preceding trigger or confirmation
        preceding = components[:i]
        if not any(c in triggers for c in preceding):
            # No trigger before this component
            # Allow displacement as alternative trigger
            if comp != "displacement" and "displacement" not in preceding:
                return False, (
                    f"{comp} at position {i} has no preceding trigger"
                )

    # Verify target is at the end (causal endpoint)
    if first_target is not None:
        # Target should be the last component or close to it
        after_target = components[first_target + 1:]
        if after_target:
            # Allow only confirmations after target, not new triggers
            if any(c in triggers for c in after_target):
                return False, "trigger after target (invalid chain order)"

    # Direction-specific validation
    if direction == "buy":
        bearish_only = {"old_low", "equal_low"}
        if any(c in bearish_only for c in components):
            target_idx = next(
                (i for i, c in enumerate(components) if c in bearish_only),
                None,
            )
            if target_idx is not None and target_idx == len(components) - 1:
                return False, "bearish target in buy scenario"

    elif direction == "sell":
        bullish_only = {"old_high", "equal_high"}
        if any(c in bullish_only for c in components):
            target_idx = next(
                (i for i, c in enumerate(components) if c in bullish_only),
                None,
            )
            if target_idx is not None and target_idx == len(components) - 1:
                return False, "bullish target in sell scenario"

    return True, "valid scenario"


# Singleton
market_thesis_engine = MarketThesisEngine()
