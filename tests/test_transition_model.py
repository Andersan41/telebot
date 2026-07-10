import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.transition_model import (
    TransitionModelBase, HeuristicTransitionModel, MLTransitionModel,
    create_transition_model, transition_model,
)


class TestHeuristicTransitionModel:
    def setup_method(self):
        self.model = HeuristicTransitionModel()

    def test_predict_transition_returns_float(self):
        result = self.model.predict_transition("sweep", "bos")
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    def test_predict_sweep_causes_bos(self):
        prob = self.model.predict_transition("sweep", "bos")
        assert prob > 0.5  # should be high

    def test_predict_bos_causes_ob(self):
        prob = self.model.predict_transition("bos", "ob")
        # Base=0.65, with default strength 0.5: 0.65 * 0.85 * 0.85 ≈ 0.47
        assert prob > 0.4

    def test_predict_unknown_returns_mid(self):
        prob = self.model.predict_transition("unknown", "unknown")
        assert 0.3 <= prob <= 0.7

    def test_strength_affects_probability(self):
        low = self.model.predict_transition("sweep", "bos", 0.2, 0.2)
        high = self.model.predict_transition("sweep", "bos", 0.9, 0.9)
        assert high > low

    def test_update_on_candle_tested_boosts(self):
        prob = self.model.update_on_candle(
            edge_type="causes",
            source_type="sweep", target_type="bos",
            source_state="tested", target_state="active",
            current_probability=0.5, age_bars=5,
        )
        assert prob > 0.5

    def test_update_on_candle_mitigated_reduces(self):
        prob = self.model.update_on_candle(
            edge_type="causes",
            source_type="sweep", target_type="bos",
            source_state="mitigated", target_state="active",
            current_probability=0.5, age_bars=5,
        )
        assert prob < 0.5

    def test_update_on_candle_broken_reduces_more(self):
        mitigated = self.model.update_on_candle(
            edge_type="causes",
            source_type="sweep", target_type="bos",
            source_state="mitigated", target_state="active",
            current_probability=0.5, age_bars=5,
        )
        broken = self.model.update_on_candle(
            edge_type="causes",
            source_type="sweep", target_type="bos",
            source_state="broken", target_state="active",
            current_probability=0.5, age_bars=5,
        )
        assert broken < mitigated

    def test_age_decay(self):
        fresh = self.model.update_on_candle(
            edge_type="causes",
            source_type="sweep", target_type="bos",
            source_state="active", target_state="active",
            current_probability=0.5, age_bars=5,
        )
        old = self.model.update_on_candle(
            edge_type="causes",
            source_type="sweep", target_type="bos",
            source_state="active", target_state="active",
            current_probability=0.5, age_bars=50,
        )
        assert old < fresh

    def test_probability_clamped(self):
        # Try to push below 0.05
        prob = self.model.update_on_candle(
            edge_type="causes",
            source_type="sweep", target_type="bos",
            source_state="broken", target_state="mitigated",
            current_probability=0.01, age_bars=0,
        )
        assert prob >= 0.05


class TestMLTransitionModel:
    def test_fallback_to_heuristic(self):
        model = MLTransitionModel()
        prob = model.predict_transition("sweep", "bos")
        assert isinstance(prob, float)
        assert 0.0 <= prob <= 1.0


class TestFactory:
    def test_create_heuristic(self):
        model = create_transition_model(ml_enabled=False)
        assert isinstance(model, HeuristicTransitionModel)

    def test_create_ml(self):
        model = create_transition_model(ml_enabled=True)
        assert isinstance(model, MLTransitionModel)


class TestSingleton:
    def test_singleton_is_heuristic(self):
        assert isinstance(transition_model, HeuristicTransitionModel)
