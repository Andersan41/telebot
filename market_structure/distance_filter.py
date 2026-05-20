"""
market_structure/distance_filter.py — Distance Filter.

Blocks signals that are too close to support/resistance levels.

Rules:
- LONG blocked if distance to nearest resistance < threshold
- SHORT blocked if distance to nearest support < threshold
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Literal, Optional

from config.settings import config


@dataclass
class DistanceFilterResult:
    blocked: bool
    direction: Literal["long", "short"]
    entry_price: float
    nearest_level: Optional[float] = None
    distance_pct: Optional[float] = None
    threshold_pct: float = 1.5
    reasons: List[str] = field(default_factory=list)


def check_distance_filter(
    direction: Literal["long", "short"],
    entry_price: float,
    sr_levels: Dict[str, Dict[str, List[float]]],
    threshold_pct: Optional[float] = None,
) -> DistanceFilterResult:
    """
    Check if a signal should be blocked due to proximity to S/R levels.

    Args:
        direction: "long" or "short".
        entry_price: Proposed entry price.
        sr_levels: S/R levels by timeframe, e.g.
            {"1h": {"resistance": [...], "support": [...]}, "4h": {...}}.
        threshold_pct: Minimum distance percentage (from config if None).

    Returns:
        DistanceFilterResult with blocked flag and details.
    """
    if threshold_pct is None:
        threshold_pct = getattr(config, "distance_filter_min_pct", 1.5)

    reasons: List[str] = []
    nearest_level: Optional[float] = None
    min_distance_pct: Optional[float] = None

    if direction == "long":
        for tf, levels in sr_levels.items():
            for resistance in levels.get("resistance", []):
                dist_pct = (resistance - entry_price) / entry_price * 100
                if dist_pct < 0:
                    continue
                if min_distance_pct is None or dist_pct < min_distance_pct:
                    min_distance_pct = dist_pct
                    nearest_level = resistance
                if dist_pct < threshold_pct:
                    reasons.append(
                        f"Resistance at {resistance} on {tf} "
                        f"only {dist_pct:.2f}% away (min {threshold_pct}%)"
                    )

    elif direction == "short":
        for tf, levels in sr_levels.items():
            for support in levels.get("support", []):
                dist_pct = (entry_price - support) / entry_price * 100
                if dist_pct < 0:
                    continue
                if min_distance_pct is None or dist_pct < min_distance_pct:
                    min_distance_pct = dist_pct
                    nearest_level = support
                if dist_pct < threshold_pct:
                    reasons.append(
                        f"Support at {support} on {tf} "
                        f"only {dist_pct:.2f}% away (min {threshold_pct}%)"
                    )

    blocked = len(reasons) > 0

    return DistanceFilterResult(
        blocked=blocked,
        direction=direction,
        entry_price=entry_price,
        nearest_level=nearest_level,
        distance_pct=min_distance_pct,
        threshold_pct=threshold_pct,
        reasons=reasons,
    )
