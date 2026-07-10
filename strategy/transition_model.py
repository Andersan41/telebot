"""
strategy/transition_model.py — Transition Probability Interface

Separates the transition probability logic from the graph engine.
Provides an interface for future ML replacement of heuristics.

Current: HeuristicTransitionModel (rules-based, in market_thesis_engine.py)
Future: MLTransitionModel (learned from historical data)

The existing HeuristicTransitionModel in market_thesis_engine.py is kept
for backward compatibility. This module provides the abstract interface
and a clean ML-ready implementation.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from loguru import logger


# ══════════════════════════════════════════════════════════════════
# Abstract interface
# ══════════════════════════════════════════════════════════════════

class TransitionModelBase(ABC):
    """Abstract interface for transition probability computation.

    Implementations:
    - HeuristicTransitionModel: rule-based (default)
    - MLTransitionModel: learned from historical data (future)

    Used by:
    - LiquidityGraph._infer_edges() — initial edge probabilities
    - LiquidityGraph.update_on_candle() — probability updates
    """

    @abstractmethod
    def predict_transition(
        self,
        source_type: str,
        target_type: str,
        source_strength: float = 0.5,
        target_strength: float = 0.5,
        context: Optional[dict] = None,
    ) -> float:
        """Predict the probability of a transition from source to target.

        Args:
            source_type: type of source node (e.g., "sweep", "bos")
            target_type: type of target node (e.g., "ob", "fvg")
            source_strength: source node strength (0..1)
            target_strength: target node strength (0..1)
            context: optional context (phase, regime, etc.)

        Returns:
            Transition probability (0..1)
        """
        ...

    @abstractmethod
    def update_on_candle(
        self,
        edge_type: str,
        source_type: str,
        target_type: str,
        source_state: str,
        target_state: str,
        current_probability: float,
        age_bars: int,
        candle_data: Optional[dict] = None,
    ) -> float:
        """Update transition probability after a new candle.

        Args:
            edge_type: "causes", "confirms", "mitigates", "targets"
            source_type: source node type
            target_type: target node type
            source_state: current state of source node
            target_state: current state of target node
            current_probability: current transition probability
            age_bars: how old is the edge
            candle_data: OHLCV data

        Returns:
            Updated probability (0..1)
        """
        ...


# ══════════════════════════════════════════════════════════════════
# Heuristic implementation (mirrors existing logic)
# ══════════════════════════════════════════════════════════════════

class HeuristicTransitionModel(TransitionModelBase):
    """Rule-based transition probability model.

    Mirrors the existing logic in market_thesis_engine.py but
    provides a clean interface for future replacement.
    """

    # Base probabilities per transition type
    BASE_PROBS = {
        "sweep_causes_bos": 0.75,
        "bos_causes_ob": 0.65,
        "displacement_causes_fvg": 0.80,
        "ob_causes_fvg": 0.60,
        "fvg_targets_ext": 0.55,
        "ob_targets_ext": 0.50,
        "fvg_targets_eq": 0.45,
        "sweep_causes_ob": 0.50,
        "bos_causes_choch": 0.60,
    }

    def predict_transition(
        self,
        source_type: str,
        target_type: str,
        source_strength: float = 0.5,
        target_strength: float = 0.5,
        context: Optional[dict] = None,
    ) -> float:
        edge_key = f"{source_type}_causes_{target_type}"
        base = self.BASE_PROBS.get(edge_key, 0.5)

        source_factor = 0.7 + 0.3 * max(0.0, min(1.0, source_strength))
        target_factor = 0.7 + 0.3 * max(0.0, min(1.0, target_strength))
        prob = base * source_factor * target_factor

        return round(max(0.05, min(0.95, prob)), 3)

    def update_on_candle(
        self,
        edge_type: str,
        source_type: str,
        target_type: str,
        source_state: str,
        target_state: str,
        current_probability: float,
        age_bars: int,
        candle_data: Optional[dict] = None,
    ) -> float:
        current = current_probability

        # Source confirmation boost
        if source_state == "tested":
            current = min(0.95, current * 1.15)
        elif source_state == "mitigated":
            current = max(0.05, current * 0.3)
        elif source_state == "broken":
            current = max(0.05, current * 0.1)

        # Target confirmation
        if target_state == "tested":
            current = min(0.95, current * 1.10)
        elif target_state == "mitigated":
            current = max(0.05, current * 0.5)

        # Age decay
        if age_bars > 20:
            decay = max(0.7, 1.0 - (age_bars - 20) * 0.005)
            current *= decay

        return round(max(0.05, min(0.95, current)), 3)


# ══════════════════════════════════════════════════════════════════
# ML implementation (placeholder for future)
# ══════════════════════════════════════════════════════════════════

class MLTransitionModel(TransitionModelBase):
    """ML-learned transition probability model.

    Placeholder for future implementation.
    Uses HeuristicTransitionModel as fallback until ML model is trained.
    """

    def __init__(self, model_path: str = "models/transition_model.pkl"):
        self.model_path = model_path
        self.model = None
        self._heuristic_fallback = HeuristicTransitionModel()
        # self._load_model()

    def _load_model(self) -> None:
        """Load trained ML model."""
        import os
        import pickle

        if not os.path.exists(self.model_path):
            logger.debug(f"No transition model at {self.model_path}")
            return

        try:
            with open(self.model_path, "rb") as f:
                self.model = pickle.load(f)
            logger.info(f"Loaded transition model: {self.model.__class__.__name__}")
        except Exception as e:
            logger.warning(f"Failed to load transition model: {e}")

    def predict_transition(
        self,
        source_type: str,
        target_type: str,
        source_strength: float = 0.5,
        target_strength: float = 0.5,
        context: Optional[dict] = None,
    ) -> float:
        if self.model is None:
            return self._heuristic_fallback.predict_transition(
                source_type, target_type, source_strength, target_strength, context,
            )

        # Future: ML prediction
        # features = [source_type, target_type, source_strength, target_strength, ...]
        # return self.model.predict_proba([features])[0][1]
        return self._heuristic_fallback.predict_transition(
            source_type, target_type, source_strength, target_strength, context,
        )

    def update_on_candle(
        self,
        edge_type: str,
        source_type: str,
        target_type: str,
        source_state: str,
        target_state: str,
        current_probability: float,
        age_bars: int,
        candle_data: Optional[dict] = None,
    ) -> float:
        if self.model is None:
            return self._heuristic_fallback.update_on_candle(
                edge_type, source_type, target_type,
                source_state, target_state,
                current_probability, age_bars, candle_data,
            )

        # Future: ML update
        return self._heuristic_fallback.update_on_candle(
            edge_type, source_type, target_type,
            source_state, target_state,
            current_probability, age_bars, candle_data,
        )


# ══════════════════════════════════════════════════════════════════
# Factory
# ══════════════════════════════════════════════════════════════════

def create_transition_model(ml_enabled: bool = False) -> TransitionModelBase:
    """Create a transition model instance.

    Args:
        ml_enabled: if True, use ML model (falls back to heuristic)
    """
    if ml_enabled:
        return MLTransitionModel()
    return HeuristicTransitionModel()


# Module-level singleton (default: heuristic)
transition_model = HeuristicTransitionModel()
