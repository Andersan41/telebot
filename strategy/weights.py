"""
strategy/weights.py — Configurable weights for Market Thesis Engine.

All scoring uses floating-point multipliers, not hardcoded point additions.
These weights can be tuned manually or optimized via ML later.

Scoring formula:
    score = sum(weight_i * feature_i) / sum(weight_i) * 100

Where feature_i is a normalized [0, 1] value and weight_i is the
corresponding multiplier from this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


# ══════════════════════════════════════════════════════════════════
# Order Block scoring
# ══════════════════════════════════════════════════════════════════

OB_FROM_BOS = 1.0          # OB was created after a BOS event
OB_DISPLACEMENT = 0.7      # displacement strength (ATR-normalized)
OB_VOLUME = 0.5            # volume above average
OB_NOT_MITIGATED = 0.6     # OB zone not yet revisited by price
OB_FVG_ALIGN = 0.4         # OB aligns with an FVG
OB_HTF_ALIGN = 0.8         # OB aligns with higher-timeframe structure
OB_NEARBY_LIQUIDITY = 0.5  # liquidity cluster near the OB
OB_RETESTED = 0.3          # OB was retested and held


# ══════════════════════════════════════════════════════════════════
# Sweep scoring
# ══════════════════════════════════════════════════════════════════

SWEEP_FAST_RECLAIM = 0.7   # price reclaimed quickly (few candles)
SWEEP_VOLUME = 0.6         # high volume during sweep
SWEEP_DISPLACEMENT = 0.8   # strong displacement after sweep
SWEEP_DELTA_ALIGNED = 0.4  # delta (buy/sell) aligned with direction


# ══════════════════════════════════════════════════════════════════
# BOS scoring
# ══════════════════════════════════════════════════════════════════

BOS_DISPLACEMENT = 0.8     # displacement strength after BOS
BOS_VOLUME = 0.5           # volume confirmation
BOS_CLOSE_STRENGTH = 0.6   # candle closed strongly beyond level
BOS_RECENCY = 0.3          # how recent the BOS is (fewer candles = better)


# ══════════════════════════════════════════════════════════════════
# Equal High/Low scoring
# ══════════════════════════════════════════════════════════════════

EQ_TOUCHES = 0.7           # number of touches (more = stronger)
EQ_TIGHTNESS = 0.5         # how tight the cluster is
EQ_VOLUME = 0.3            # volume at the level


# ══════════════════════════════════════════════════════════════════
# FVG scoring
# ══════════════════════════════════════════════════════════════════

FVG_SIZE = 0.6             # FVG size relative to ATR
FVG_NOT_FILLED = 0.8       # FVG not yet filled by price
FVG_DISPLACEMENT = 0.5     # displacement that created the FVG


# ══════════════════════════════════════════════════════════════════
# External Liquidity scoring (old highs/lows)
# ══════════════════════════════════════════════════════════════════

EXT_AGE = 0.4              # how old the level is
EXT_VOLUME = 0.6           # volume at the level
EXT_STRUCTURE_ALIGN = 0.5  # aligns with current structure


# ══════════════════════════════════════════════════════════════════
# Scenario scoring — weights for the entire chain
# ══════════════════════════════════════════════════════════════════

# How much each component type contributes to the scenario score
SCENARIO_COMPONENT_WEIGHTS: Dict[str, float] = {
    "sweep": 1.0,
    "bos": 0.9,
    "ob": 0.8,
    "fvg": 0.6,
    "displacement": 0.7,
    "equal_level": 0.5,
    "external_liquidity": 0.4,
}

# Bonus for scenario completeness (more components = more confluence)
SCENARIO_COMPLETENESS_BONUS = 0.15  # up to 15% bonus for full scenario

# Penalty for broken/invalidated components
SCENARIO_INVALIDATED_PENALITY = 0.3  # 30% penalty per invalidated component


# ══════════════════════════════════════════════════════════════════
# Liquidity Path scoring
# ══════════════════════════════════════════════════════════════════

# Bonus for clear path (no strong opposing levels)
PATH_CLEAR_BONUS = 0.2

# Penalty for obstacles in path
PATH_OBSTACLE_PENALTY = 0.15  # per strong obstacle


# ══════════════════════════════════════════════════════════════════
# Helper functions
# ══════════════════════════════════════════════════════════════════

def weighted_score(features: Dict[str, float], weights: Dict[str, float]) -> float:
    """Calculate weighted score from feature values and weights.

    Args:
        features: {feature_name: normalized_value [0, 1]}
        weights: {feature_name: weight}

    Returns:
        Score in [0, 100].
    """
    if not weights:
        return 0.0

    total = 0.0
    weight_sum = 0.0

    for key, weight in weights.items():
        value = features.get(key, 0.0)
        total += weight * max(0.0, min(1.0, value))
        weight_sum += weight

    if weight_sum == 0:
        return 0.0

    return round(total / weight_sum * 100, 1)


def normalize(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    """Normalize value to [0, 1] range."""
    if max_val == min_val:
        return 0.0
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))
