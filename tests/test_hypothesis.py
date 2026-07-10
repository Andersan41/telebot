"""
tests/test_hypothesis.py — Tests for Hypothesis Engine core.

Covers:
    - Hypothesis dataclass
    - HypothesisSet container
    - compute_utility()
    - compute_exponential_decay()
"""
import sys
from pathlib import Path

import pytest

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from strategy.hypothesis import (
    Hypothesis,
    HypothesisSet,
    ScenarioComponent,
    compute_utility,
    compute_exponential_decay,
    UTILITY_WEIGHTS,
    ALL_NARRATIVE_TYPES,
)


# ── Hypothesis ─────────────────────────────────────────────────────

class TestHypothesis:
    def test_basic_creation(self):
        h = Hypothesis(
            id="h1",
            direction="buy",
            narrative_type="sweep_bos_ob_fvg",
            name="Sweep → BOS → OB → FVG",
            description="Classic ICT chain",
            quality=75.0,
            confidence=0.8,
            decay_factor=0.9,
            entry_price=100.0,
            invalidation_price=98.0,
            target_price=105.0,
            rr_ratio=2.5,
        )
        assert h.id == "h1"
        assert h.direction == "buy"
        assert h.quality == 75.0
        assert h.confidence == 0.8
        assert h.decay_factor == 0.9

    def test_age_bars(self):
        h = Hypothesis(
            id="h1", direction="buy", narrative_type="ob_retest",
            name="test", description="test",
            quality=50, confidence=0.5, decay_factor=0.5,
            entry_price=100, invalidation_price=99, target_price=102,
            rr_ratio=2.0, created_at_bar=10, current_bar=15,
        )
        assert h.age_bars == 5

    def test_is_alive(self):
        h = Hypothesis(
            id="h1", direction="buy", narrative_type="ob_retest",
            name="test", description="test",
            quality=50, confidence=0.5, decay_factor=0.15,
            entry_price=100, invalidation_price=99, target_price=102,
            rr_ratio=2.0,
        )
        assert h.is_alive is True

        h.decay_factor = 0.05
        assert h.is_alive is False


# ── Utility Function ───────────────────────────────────────────────

class TestUtility:
    def test_utility_weights_sum_to_one(self):
        total = sum(UTILITY_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-6

    def test_compute_utility_perfect(self):
        h = Hypothesis(
            id="h1", direction="buy", narrative_type="test",
            name="test", description="test",
            quality=100.0, confidence=1.0, decay_factor=1.0,
            entry_price=100, invalidation_price=99, target_price=102,
            rr_ratio=2.0,
        )
        u = compute_utility(h)
        assert abs(u - 1.0) < 1e-6

    def test_compute_utility_zero(self):
        h = Hypothesis(
            id="h1", direction="buy", narrative_type="test",
            name="test", description="test",
            quality=0.0, confidence=0.0, decay_factor=0.0,
            entry_price=100, invalidation_price=99, target_price=102,
            rr_ratio=2.0,
        )
        u = compute_utility(h)
        assert abs(u - 0.0) < 1e-6

    def test_compute_utility_weighted(self):
        h = Hypothesis(
            id="h1", direction="buy", narrative_type="test",
            name="test", description="test",
            quality=80.0, confidence=0.6, decay_factor=0.8,
            entry_price=100, invalidation_price=99, target_price=102,
            rr_ratio=2.0,
        )
        u = compute_utility(h)
        expected = (
            UTILITY_WEIGHTS["quality"] * 0.8
            + UTILITY_WEIGHTS["confidence"] * 0.6
            + UTILITY_WEIGHTS["decay"] * 0.8
        )
        assert abs(u - expected) < 1e-6


# ── Exponential Decay ──────────────────────────────────────────────

class TestDecay:
    def test_fresh_hypothesis(self):
        d = compute_exponential_decay(0, [1.0, 1.0])
        assert abs(d - 1.0) < 1e-6

    def test_old_hypothesis(self):
        d = compute_exponential_decay(100, [1.0])
        assert d < 0.2

    def test_node_state_affects_decay(self):
        d_alive = compute_exponential_decay(10, [1.0, 1.0])
        d_dead = compute_exponential_decay(10, [0.0, 0.0])
        assert d_alive > d_dead

    def test_empty_node_scores(self):
        d = compute_exponential_decay(10, [])
        assert 0.0 <= d <= 1.0


# ── HypothesisSet ──────────────────────────────────────────────────

class TestHypothesisSet:
    def _make_h(self, id, direction, quality, confidence, decay, narrative="test"):
        return Hypothesis(
            id=id, direction=direction, narrative_type=narrative,
            name=f"h {id}", description=f"h {id}",
            quality=quality, confidence=confidence, decay_factor=decay,
            entry_price=100, invalidation_price=99, target_price=102,
            rr_ratio=2.0,
        )

    def test_add_and_len(self):
        hs = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        hs.add(self._make_h("h1", "buy", 80, 0.8, 0.9))
        hs.add(self._make_h("h2", "sell", 70, 0.7, 0.8))
        assert len(hs) == 2

    def test_best_buy(self):
        hs = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        hs.add(self._make_h("h1", "buy", 60, 0.6, 0.7))
        hs.add(self._make_h("h2", "buy", 90, 0.9, 0.95))
        assert hs.best_buy.id == "h2"

    def test_best_sell(self):
        hs = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        hs.add(self._make_h("h1", "sell", 50, 0.5, 0.6))
        hs.add(self._make_h("h2", "sell", 85, 0.85, 0.9))
        assert hs.best_sell.id == "h2"

    def test_ambiguity_gap(self):
        hs = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        hs.add(self._make_h("h1", "buy", 80, 0.8, 0.9))
        hs.add(self._make_h("h2", "sell", 80, 0.8, 0.9))
        gap = hs.ambiguity_gap
        assert gap < 0.01  # nearly identical

    def test_ambiguity_gap_one_direction(self):
        hs = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        hs.add(self._make_h("h1", "buy", 80, 0.8, 0.9))
        assert hs.ambiguity_gap == 1.0  # no sell

    def test_ranked(self):
        hs = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        hs.add(self._make_h("h1", "buy", 50, 0.5, 0.5))
        hs.add(self._make_h("h2", "buy", 90, 0.9, 0.9))
        hs.add(self._make_h("h3", "buy", 70, 0.7, 0.7))
        ranked = hs.ranked()
        assert ranked[0].id == "h2"
        assert ranked[-1].id == "h1"

    def test_top_n(self):
        hs = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        for i in range(10):
            hs.add(self._make_h(f"h{i}", "buy", i * 10, 0.5, 0.5))
        top3 = hs.top(3)
        assert len(top3) == 3

    def test_remove_expired(self):
        hs = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        hs.add(self._make_h("h1", "buy", 80, 0.8, 0.9))
        hs.add(self._make_h("h2", "buy", 80, 0.8, 0.05))  # low decay
        hs.remove_expired(max_age_bars=100)
        assert len(hs) == 1

    def test_by_narrative(self):
        hs = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        hs.add(self._make_h("h1", "buy", 80, 0.8, 0.9, narrative="ob_retest"))
        hs.add(self._make_h("h2", "buy", 70, 0.7, 0.8, narrative="sweep_bos_ob"))
        ob = hs.by_narrative("ob_retest")
        assert len(ob) == 1
        assert ob[0].id == "h1"

    def test_by_direction(self):
        hs = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        hs.add(self._make_h("h1", "buy", 80, 0.8, 0.9))
        hs.add(self._make_h("h2", "sell", 70, 0.7, 0.8))
        buys = hs.by_direction("buy")
        assert len(buys) == 1

    def test_update_decay(self):
        hs = HypothesisSet(symbol="BTC/USDT", timeframe="1h", created_at_bar=0)
        h = self._make_h("h1", "buy", 80, 0.8, 0.9)
        h.current_bar = 0
        hs.add(h)
        hs.update_decay(10)
        assert h.current_bar == 10

    def test_repr(self):
        hs = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        assert "BTC/USDT" in repr(hs)


# ── Narrative Types ────────────────────────────────────────────────

class TestNarrativeTypes:
    def test_all_narrative_types_count(self):
        assert len(ALL_NARRATIVE_TYPES) == 12

    def test_all_are_strings(self):
        for nt in ALL_NARRATIVE_TYPES:
            assert isinstance(nt, str)
