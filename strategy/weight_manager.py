"""
strategy/weight_manager.py — Weight Manager

Corrects Probability Engine outputs based on cumulative statistics.
ProbabilityEngine outputs a raw probability → WeightManager adjusts.

Activation: starts adjusting after 30+ closed scenarios per symbol+type.
Full confidence after 100+ closed scenarios.
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

from strategy.scenario_engine import ScenarioEvaluation
from strategy.scenario_memory import scenario_memory


class WeightManager:
    """Adjusts scenario evaluations based on cumulative statistics.

    Does NOT modify the Probability Engine — works as a separate layer.
    Probability outputs assessment → WeightManager corrects.
    """

    MIN_SCENARIOS_FOR_ADJUSTMENT = 30
    FULL_CONFIDENCE_SCENARIOS = 100

    def adjust(
        self,
        evaluation: ScenarioEvaluation,
        symbol: str,
        scenario_name: str,
        regime: Optional[str] = None,
    ) -> ScenarioEvaluation:
        """Adjust evaluation based on historical scenario statistics.

        Uses winrate and expectancy from ScenarioMemory to correct P(TP).
        Scaling factor: linearly interpolates between 1.0 (no adjustment)
        and full adjustment as sample size grows.
        """
        stats = scenario_memory.get_stats(symbol, scenario_name)

        if stats is None or stats.closed_count < self.MIN_SCENARIOS_FOR_ADJUSTMENT:
            return evaluation

        # Calculate adjustment factor
        wr = stats.winrate
        expectancy = stats.expectancy  # in R

        # Base adjustment: how much the historical WR differs from 50%
        # If WR=60% → positive adjustment; if WR=35% → negative adjustment
        wr_adjustment = (wr - 0.5) * 0.4  # [-0.2, +0.2] range

        # Expectancy adjustment: positive expectancy → boost, negative → penalty
        exp_adjustment = max(-0.15, min(0.15, expectancy * 0.05))

        # Combined adjustment
        total_adjustment = wr_adjustment + exp_adjustment

        # Confidence scaling: linear interpolation based on sample size
        if stats.closed_count >= self.FULL_CONFIDENCE_SCENARIOS:
            confidence_scale = 1.0
        else:
            confidence_scale = (stats.closed_count - self.MIN_SCENARIOS_FOR_ADJUSTMENT) / (
                self.FULL_CONFIDENCE_SCENARIOS - self.MIN_SCENARIOS_FOR_ADJUSTMENT
            )

        # Apply scaled adjustment
        scaled_adjustment = total_adjustment * confidence_scale
        new_probability = max(0.1, min(0.85, evaluation.probability + scaled_adjustment))

        logger.info(
            f"WeightManager: {symbol} {scenario_name} "
            f"P(TP) {evaluation.probability:.2f} → {new_probability:.2f} "
            f"(wr={wr:.0%}, E={expectancy:.2f}R, n={stats.closed_count}, "
            f"adj={scaled_adjustment:+.3f})"
        )

        evaluation.probability = new_probability
        evaluation.confidence = min(1.0, evaluation.confidence * (1.0 + 0.1 * confidence_scale))

        return evaluation


# Module-level singleton
weight_manager = WeightManager()
