"""
tests/test_decision_engine.py — Tests for Decision Engine.

Covers:
    - MarketState
    - DecisionEngine.decide()
    - Ambiguity detection
    - Quality gate
"""
import sys
from pathlib import Path

import pytest

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from strategy.hypothesis import Hypothesis, HypothesisSet
from strategy.decision_engine import DecisionEngine, MarketState, Decision
from strategy.market_phase_engine import MarketPhase


# ── Helpers ────────────────────────────────────────────────────────

def _make_h(id, direction, quality, confidence, decay, narrative="test"):
    return Hypothesis(
        id=id, direction=direction, narrative_type=narrative,
        name=f"h {id}", description=f"h {id}",
        quality=quality, confidence=confidence, decay_factor=decay,
        entry_price=100, invalidation_price=99, target_price=102,
        rr_ratio=2.0,
    )


def _make_state(phase=MarketPhase.EXPANSION):
    return MarketState(
        phase=phase,
        phase_confidence=0.8,
        narrative_weights={},
    )


# ── MarketState ────────────────────────────────────────────────────

class TestMarketState:
    def test_default_weight(self):
        ms = _make_state()
        assert ms.get_weight("any_narrative") == 1.0

    def test_known_weight(self):
        ms = MarketState(
            phase=MarketPhase.EXPANSION,
            phase_confidence=0.9,
            narrative_weights={"ob_retest": 1.5, "sweep_bos_ob": 0.8},
        )
        assert ms.get_weight("ob_retest") == 1.5
        assert ms.get_weight("sweep_bos_ob") == 0.8


# ── DecisionEngine ─────────────────────────────────────────────────

class TestDecisionEngine:
    def test_no_hypotheses(self):
        engine = DecisionEngine()
        hset = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        decision = engine.decide(hset, _make_state())
        assert decision.trade is False
        assert decision.rejection_reason == "no_valid_hypothesis"

    def test_single_buy_wins(self):
        engine = DecisionEngine()
        hset = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        hset.add(_make_h("h1", "buy", 80, 0.8, 0.9))
        decision = engine.decide(hset, _make_state())
        assert decision.trade is True
        assert decision.hypothesis.direction == "buy"

    def test_single_sell_wins(self):
        engine = DecisionEngine()
        hset = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        hset.add(_make_h("h1", "sell", 80, 0.8, 0.9))
        decision = engine.decide(hset, _make_state())
        assert decision.trade is True
        assert decision.hypothesis.direction == "sell"

    def test_ambiguity_detection(self):
        engine = DecisionEngine(ambiguity_threshold=0.10)
        hset = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        # Same quality — should be ambiguous
        hset.add(_make_h("h1", "buy", 80, 0.8, 0.9))
        hset.add(_make_h("h2", "sell", 80, 0.8, 0.9))
        decision = engine.decide(hset, _make_state())
        assert decision.trade is False
        assert decision.rejection_reason == "ambiguous"

    def test_clear_winner_no_ambiguity(self):
        engine = DecisionEngine(ambiguity_threshold=0.10)
        hset = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        hset.add(_make_h("h1", "buy", 90, 0.9, 0.95))
        hset.add(_make_h("h2", "sell", 50, 0.5, 0.5))
        decision = engine.decide(hset, _make_state())
        assert decision.trade is True
        assert decision.hypothesis.direction == "buy"

    def test_low_utility_rejected(self):
        engine = DecisionEngine(min_utility=0.5)
        hset = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        hset.add(_make_h("h1", "buy", 10, 0.1, 0.1))
        decision = engine.decide(hset, _make_state())
        assert decision.trade is False
        assert decision.rejection_reason == "low_utility"

    def test_narrative_weight_applied(self):
        engine = DecisionEngine(ambiguity_threshold=0.10)
        hset = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        hset.add(_make_h("h1", "buy", 80, 0.8, 0.9, narrative="ob_retest"))
        hset.add(_make_h("h2", "sell", 80, 0.8, 0.9, narrative="sweep_bos_ob"))

        # Weight OB retest higher
        state = MarketState(
            phase=MarketPhase.MITIGATION,
            phase_confidence=0.9,
            narrative_weights={"ob_retest": 2.0, "sweep_bos_ob": 0.5},
        )
        decision = engine.decide(hset, state)
        assert decision.trade is True
        assert decision.hypothesis.direction == "buy"
        assert decision.hypothesis.narrative_type == "ob_retest"

    def test_decision_has_reasons(self):
        engine = DecisionEngine()
        hset = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        hset.add(_make_h("h1", "buy", 80, 0.8, 0.9))
        decision = engine.decide(hset, _make_state())
        assert len(decision.reasons) > 0

    def test_decision_has_market_state(self):
        engine = DecisionEngine()
        hset = HypothesisSet(symbol="BTC/USDT", timeframe="1h")
        hset.add(_make_h("h1", "buy", 80, 0.8, 0.9))
        ms = _make_state()
        decision = engine.decide(hset, ms)
        assert decision.market_state == ms
