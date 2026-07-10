"""
strategy/weight_manager.py — Weight Manager (stub)

Corrects Probability Engine outputs based on cumulative statistics.
ProbabilityEngine outputs a raw probability → WeightManager adjusts.

DEFERRED: Per-Symbol Weights require 300-500 closed scenarios per symbol.
Currently a no-op stub that returns evaluations unchanged.

Future flow:
    ProbabilityEngine.estimate_scenario() → ScenarioEvaluation
    WeightManager.adjust(evaluation, symbol, regime) → ScenarioEvaluation
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

    Currently a stub — returns evaluations unchanged.
    Will activate after 300+ closed scenarios per symbol.
    """

    MIN_SCENARIOS_FOR_ADJUSTMENT = 300

    def adjust(
        self,
        evaluation: ScenarioEvaluation,
        symbol: str,
        scenario_name: str,
        regime: Optional[str] = None,
    ) -> ScenarioEvaluation:
        """Adjust evaluation based on historical scenario statistics.

        Currently returns evaluation unchanged (stub).
        Will adjust probability based on winrate and expectancy
        when sufficient data is available.
        """
        stats = scenario_memory.get_stats(symbol, scenario_name)

        if stats is None or stats.closed_count < self.MIN_SCENARIOS_FOR_ADJUSTMENT:
            # Not enough data — return unchanged
            return evaluation

        # Future: adjust based on stats
        # adjustment = stats.winrate * stats.avg_rr
        # evaluation.probability *= adjustment
        # evaluation.confidence = min(1.0, evaluation.confidence * 1.1)

        logger.debug(
            f"WeightManager: {symbol} {scenario_name} "
            f"stats available (n={stats.closed_count}, "
            f"wr={stats.winrate:.0%}, E={stats.expectancy:.2f}R) "
            f"— adjustment deferred"
        )

        return evaluation


# Module-level singleton
weight_manager = WeightManager()
