"""
strategy/scenario_engine.py — Scenario Engine

Generates competing market scenarios from the LiquidityGraph.

Key principle: Scenario is an immutable "map". Evaluation is mutable.
- MarketScenario (frozen) — never changes once created
- ScenarioEvaluation (mutable) — probability, confidence, RR, PF
- ScenarioEngine — generates scenarios, does NOT evaluate them

Flow:
    LiquidityGraph + MarketStructure + PhaseAssessment
        ↓
    ScenarioEngine.detect_scenarios()
        ↓
    list[MarketScenario]  (immutable maps)
        ↓
    ProbabilityEngine.estimate_scenario()  (for each)
        ↓
    list[(MarketScenario, ScenarioEvaluation)]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Tuple

from loguru import logger


# ══════════════════════════════════════════════════════════════════
# ScenarioComponent — one step in a scenario (immutable)
# ══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ScenarioComponent:
    """One expected event in a scenario — immutable."""
    id: str
    type: str          # "sweep", "bos", "ob", "fvg", "external_liq", "choch"
    description: str   # "Sweep below equal lows @ 67200.0000"
    node_id: Optional[str] = None
    price_level: Optional[float] = None
    is_critical: bool = True  # if False, scenario can survive without this


# ══════════════════════════════════════════════════════════════════
# MarketScenario — immutable "map" of market expectations
# ══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class MarketScenario:
    """A market scenario — immutable "map".

    Once created, never changes. The probability/evaluation is stored
    separately in ScenarioEvaluation.
    """
    id: str
    direction: Literal["buy", "sell"]
    name: str                              # "Sweep+BOS+OB+FVG"
    description: str

    # Components (ordered sequence of expected events)
    components: Tuple[ScenarioComponent, ...]  # tuple = immutable

    # Path (immutable price levels)
    entry_zone: Tuple[float, float]       # (low, high)
    invalidation_price: float             # SL level
    target_price: float                   # TP level
    rr_ratio: float

    # Metadata
    market_phase: Optional[str] = None    # phase at creation time
    created_at_bar: int = 0

    @property
    def components_count(self) -> int:
        return len(self.components)

    @property
    def critical_components(self) -> int:
        return sum(1 for c in self.components if c.is_critical)

    def __repr__(self) -> str:
        return (
            f"Scenario({self.direction.upper()} {self.name} "
            f"rr={self.rr_ratio:.1f} "
            f"components={len(self.components)})"
        )


# ══════════════════════════════════════════════════════════════════
# ScenarioEvaluation — mutable assessment of a scenario
# ══════════════════════════════════════════════════════════════════

@dataclass
class ScenarioEvaluation:
    """Mutable evaluation of a scenario.

    probability, confidence, expected_rr, profit_factor — all change
    as new data arrives. The scenario itself never changes.
    """
    scenario_id: str

    probability: float = 0.0       # P(scenario) — 0..1
    confidence: float = 0.0        # model confidence
    expected_rr: float = 0.0
    profit_factor: float = 0.0

    # Component-level scores
    component_scores: dict = field(default_factory=dict)

    # Model info
    model_type: str = "rules"      # "rules" / "xgboost"
    model_version: str = "1.0"

    # Timestamp
    evaluated_at_bar: int = 0

    @property
    def quality_label(self) -> str:
        if self.probability >= 0.65:
            return "strong"
        elif self.probability >= 0.50:
            return "moderate"
        return "weak"

    def __repr__(self) -> str:
        return (
            f"Eval(p={self.probability:.2f} "
            f"conf={self.confidence:.2f} "
            f"rr={self.expected_rr:.1f} "
            f"pf={self.profit_factor:.2f})"
        )


# ══════════════════════════════════════════════════════════════════
# ScenarioEngine — generates scenarios from graph
# ══════════════════════════════════════════════════════════════════

class ScenarioEngine:
    """Generates competing market scenarios from the LiquidityGraph.

    Does NOT evaluate probability — that's the ProbabilityEngine's job.
    Only constructs the "maps" (immutable scenarios).
    """

    def detect_scenarios(
        self,
        graph,         # LiquidityGraph
        structure=None, # MarketStructure (optional)
        phase=None,     # PhaseAssessment (optional)
        direction: Optional[str] = None,  # None = both
    ) -> list[MarketScenario]:
        """Detect all plausible scenarios from the graph.

        Returns scenarios sorted by component count (more components = more developed).
        Probability is NOT set here — that's for ProbabilityEngine.
        """
        scenarios = []

        if direction in (None, "buy"):
            scenarios.extend(self._build_buy_scenarios(graph, structure, phase))
        if direction in (None, "sell"):
            scenarios.extend(self._build_sell_scenarios(graph, structure, phase))

        # Deduplicate by id
        seen = set()
        unique = []
        for s in scenarios:
            if s.id not in seen:
                seen.add(s.id)
                unique.append(s)

        # Sort by component count (more components = better formed)
        unique.sort(key=lambda s: (s.components_count, s.rr_ratio), reverse=True)

        logger.debug(
            f"ScenarioEngine: detected {len(unique)} scenarios "
            f"({sum(1 for s in unique if s.direction == 'buy')} buy, "
            f"{sum(1 for s in unique if s.direction == 'sell')} sell)"
        )

        return unique

    # ──────────────────────────────────────────────────────
    # BUY scenarios
    # ──────────────────────────────────────────────────────

    def _build_buy_scenarios(self, graph, structure, phase) -> list[MarketScenario]:
        alive = graph.alive_nodes()

        sweeps = [n for n in alive if n.type == "sweep" and n.is_bullish]
        boses = [n for n in alive if n.type == "bos" and n.is_bullish]
        obs = [n for n in alive if n.type == "ob" and n.is_bullish]
        fvgs = [n for n in alive if n.type == "fvg" and n.is_bullish]
        chochs = [n for n in alive if n.type == "choch" and n.is_bullish]

        scenarios = []
        phase_name = phase.phase.value if phase else None

        # ── Pattern A: Sweep → BOS → OB → FVG ──
        for sweep in sweeps:
            for bos in boses:
                if bos.created_at is not None and sweep.created_at is not None:
                    if bos.created_at <= sweep.created_at:
                        continue
                for ob in obs:
                    if ob.created_at is not None and bos.created_at is not None:
                        if ob.created_at <= bos.created_at:
                            continue
                    for fvg in fvgs:
                        if fvg.created_at is not None and ob.created_at is not None:
                            if fvg.created_at <= ob.created_at:
                                continue
                        scenarios.append(self._compose(
                            "buy", "Sweep+BOS+OB+FVG",
                            [sweep, bos, ob, fvg], graph, phase_name,
                        ))

        # ── Pattern B: Sweep → BOS → OB (no FVG) ──
        for sweep in sweeps:
            for bos in boses:
                if bos.created_at is not None and sweep.created_at is not None:
                    if bos.created_at <= sweep.created_at:
                        continue
                for ob in obs:
                    if ob.created_at is not None and bos.created_at is not None:
                        if ob.created_at <= bos.created_at:
                            continue
                    scenarios.append(self._compose(
                        "buy", "Sweep+BOS+OB",
                        [sweep, bos, ob], graph, phase_name,
                    ))

        # ── Pattern C: CHoCH → OB ──
        for choch in chochs:
            for ob in obs:
                if ob.created_at is not None and choch.created_at is not None:
                    if ob.created_at <= choch.created_at:
                        continue
                scenarios.append(self._compose(
                    "buy", "CHoCH+OB",
                    [choch, ob], graph, phase_name,
                ))

        # ── Pattern D: OB Retest (tested node) ──
        for ob in obs:
            if ob.state == "tested":
                scenarios.append(self._compose(
                    "buy", "OB Retest",
                    [ob], graph, phase_name,
                ))

        return scenarios

    # ──────────────────────────────────────────────────────
    # SELL scenarios
    # ──────────────────────────────────────────────────────

    def _build_sell_scenarios(self, graph, structure, phase) -> list[MarketScenario]:
        alive = graph.alive_nodes()

        sweeps = [n for n in alive if n.type == "sweep" and n.is_bearish]
        boses = [n for n in alive if n.type == "bos" and n.is_bearish]
        obs = [n for n in alive if n.type == "ob" and n.is_bearish]
        fvgs = [n for n in alive if n.type == "fvg" and n.is_bearish]
        chochs = [n for n in alive if n.type == "choch" and n.is_bearish]

        scenarios = []
        phase_name = phase.phase.value if phase else None

        # ── Pattern A: Sweep → BOS → OB → FVG ──
        for sweep in sweeps:
            for bos in boses:
                if bos.created_at is not None and sweep.created_at is not None:
                    if bos.created_at <= sweep.created_at:
                        continue
                for ob in obs:
                    if ob.created_at is not None and bos.created_at is not None:
                        if ob.created_at <= bos.created_at:
                            continue
                    for fvg in fvgs:
                        if fvg.created_at is not None and ob.created_at is not None:
                            if fvg.created_at <= ob.created_at:
                                continue
                        scenarios.append(self._compose(
                            "sell", "Sweep+BOS+OB+FVG",
                            [sweep, bos, ob, fvg], graph, phase_name,
                        ))

        # ── Pattern B: Sweep → BOS → OB ──
        for sweep in sweeps:
            for bos in boses:
                if bos.created_at is not None and sweep.created_at is not None:
                    if bos.created_at <= sweep.created_at:
                        continue
                for ob in obs:
                    if ob.created_at is not None and bos.created_at is not None:
                        if ob.created_at <= bos.created_at:
                            continue
                    scenarios.append(self._compose(
                        "sell", "Sweep+BOS+OB",
                        [sweep, bos, ob], graph, phase_name,
                    ))

        # ── Pattern C: CHoCH → OB ──
        for choch in chochs:
            for ob in obs:
                if ob.created_at is not None and choch.created_at is not None:
                    if ob.created_at <= choch.created_at:
                        continue
                scenarios.append(self._compose(
                    "sell", "CHoCH+OB",
                    [choch, ob], graph, phase_name,
                ))

        # ── Pattern D: OB Retest ──
        for ob in obs:
            if ob.state == "tested":
                scenarios.append(self._compose(
                    "sell", "OB Retest",
                    [ob], graph, phase_name,
                ))

        return scenarios

    # ──────────────────────────────────────────────────────
    # Composition
    # ──────────────────────────────────────────────────────

    def _compose(
        self,
        direction: str,
        name: str,
        nodes: list,
        graph,
        phase_name: Optional[str] = None,
    ) -> MarketScenario:
        """Compose a MarketScenario from ordered nodes."""
        components = []
        for i, node in enumerate(nodes):
            node_id = f"{node.type}_{node.price:.6f}"
            components.append(ScenarioComponent(
                id=f"{name}_{i}",
                type=node.type,
                description=f"{node.type} @ {node.price:.4f}",
                node_id=node_id,
                price_level=node.price,
                is_critical=(i < 2),  # first 2 components are critical
            ))

        entry = self._compute_entry(nodes, direction)
        sl = self._compute_invalidation(nodes, direction)
        tp = self._compute_target(nodes, direction, entry, sl)
        rr = abs(tp - entry) / abs(entry - sl) if sl and tp and entry and abs(entry - sl) > 1e-10 else 0

        scenario_id = f"{direction}_{name}_{nodes[0].price:.4f}"

        return MarketScenario(
            id=scenario_id,
            direction=direction,
            name=name,
            description=f"{direction.upper()}: " + " → ".join(c.description for c in components),
            components=tuple(components),
            entry_zone=(entry * 0.999, entry * 1.001) if entry else (0.0, 0.0),
            invalidation_price=sl or 0.0,
            target_price=tp or 0.0,
            rr_ratio=round(rr, 2),
            market_phase=phase_name,
        )

    def _compute_entry(self, nodes: list, direction: str) -> float:
        """Entry: price of the last confirmation node (OB or FVG)."""
        for node in reversed(nodes):
            if node.type in ("ob", "fvg"):
                return node.price
        # Fallback: price of the most recent node
        return nodes[-1].price if nodes else 0.0

    def _compute_invalidation(self, nodes: list, direction: str) -> float:
        """SL: beyond the trigger (sweep/BOS) level."""
        for node in nodes:
            if node.type in ("sweep", "bos"):
                if direction == "buy":
                    return node.price * 0.995  # slightly below
                else:
                    return node.price * 1.005  # slightly above
        # Fallback: 1% from entry
        entry = self._compute_entry(nodes, direction)
        return entry * 0.99 if direction == "buy" else entry * 1.01

    def _compute_target(self, nodes: list, direction: str, entry: float, sl: float) -> float:
        """TP: external liquidity or next structural level."""
        # Look for external/equal level targets
        for node in nodes:
            if node.type in ("equal_high", "equal_low", "old_high", "old_low"):
                return node.price

        # Fallback: 2x risk from entry
        if sl and entry:
            risk = abs(entry - sl)
            if direction == "buy":
                return entry + risk * 2
            else:
                return entry - risk * 2

        return entry * 1.02 if direction == "buy" else entry * 0.98


# Module-level singleton
scenario_engine = ScenarioEngine()
