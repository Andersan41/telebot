"""
liquidity/equal_levels.py — Equal Highs/Lows detection.

Clusters swing points at similar prices into "equal levels" —
these represent concentrated liquidity pools where retail stops cluster.

ICT concept: Equal Highs / Equal Low = "where the stops are".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

from loguru import logger
from config.settings import config


@dataclass
class EqualLevel:
    """A cluster of swing points at the same price — a liquidity pool."""
    type: Literal["equal_high", "equal_low"]
    level: float                          # average price of the cluster
    touches: int                          # number of swing points in the cluster
    prices: list[float]                   # individual swing point prices
    timestamps: list[datetime]            # when each touch occurred
    strength: float = 0.0                 # density score [0, 1]
    swept: bool = False                   # has this level been swept?
    sweep_timestamp: Optional[datetime] = None

    @property
    def is_valid(self) -> bool:
        """Valid if at least 2 touches (true equality)."""
        return self.touches >= 2

    @property
    def range_pct(self) -> float:
        """Price range within the cluster as % of level."""
        if not self.prices or self.level == 0:
            return 0.0
        return (max(self.prices) - min(self.prices)) / self.level * 100


def detect_equal_levels(
    swing_highs: list,
    swing_lows: list,
    tolerance_pct: float = 0.15,
    min_touches: int = 2,
) -> list[EqualLevel]:
    """Detect equal highs and equal lows by clustering swing points.

    Args:
        swing_highs: list of SwingPoint objects with .price and .timestamp
        swing_lows: list of SwingPoint objects with .price and .timestamp
        tolerance_pct: max % distance between points to consider "equal"
        min_touches: minimum touches to form an equal level

    Returns:
        List of EqualLevel objects, sorted by strength (descending)
    """
    levels = []

    # Cluster swing highs → Equal Highs
    if len(swing_highs) >= min_touches:
        clusters = _cluster_points(
            [(sp.price, sp.timestamp) for sp in swing_highs],
            tolerance_pct,
        )
        for cluster in clusters:
            if len(cluster) >= min_touches:
                prices = [p for p, _ in cluster]
                timestamps = [ts for _, ts in cluster]
                avg_price = sum(prices) / len(prices)
                strength = _calc_strength(len(cluster), tolerance_pct, prices, avg_price)
                levels.append(EqualLevel(
                    type="equal_high",
                    level=round(avg_price, 8),
                    touches=len(cluster),
                    prices=prices,
                    timestamps=timestamps,
                    strength=strength,
                ))

    # Cluster swing lows → Equal Lows
    if len(swing_lows) >= min_touches:
        clusters = _cluster_points(
            [(sp.price, sp.timestamp) for sp in swing_lows],
            tolerance_pct,
        )
        for cluster in clusters:
            if len(cluster) >= min_touches:
                prices = [p for p, _ in cluster]
                timestamps = [ts for _, ts in cluster]
                avg_price = sum(prices) / len(prices)
                strength = _calc_strength(len(cluster), tolerance_pct, prices, avg_price)
                levels.append(EqualLevel(
                    type="equal_low",
                    level=round(avg_price, 8),
                    touches=len(cluster),
                    prices=prices,
                    timestamps=timestamps,
                    strength=strength,
                ))

    # Sort by strength (more touches = stronger liquidity pool)
    levels.sort(key=lambda x: x.strength, reverse=True)
    return levels


def _cluster_points(
    points: list[tuple[float, datetime]],
    tolerance_pct: float,
) -> list[list[tuple[float, datetime]]]:
    """Group points that are within tolerance_pct of each other."""
    if not points:
        return []

    # Sort by price
    sorted_pts = sorted(points, key=lambda x: x[0])
    clusters = []
    current = [sorted_pts[0]]

    for i in range(1, len(sorted_pts)):
        price, ts = sorted_pts[i]
        # Compare to the first point in the cluster (cheapest)
        ref_price = current[0][0]
        if ref_price > 0 and abs(price - ref_price) / ref_price * 100 <= tolerance_pct:
            current.append((price, ts))
        else:
            clusters.append(current)
            current = [(price, ts)]
    clusters.append(current)

    return clusters


def _calc_strength(
    touches: int,
    tolerance_pct: float,
    prices: list[float],
    avg_price: float,
) -> float:
    """Calculate strength score [0, 1] for an equal level.

    Factors:
    - More touches = stronger (concentrated liquidity)
    - Tighter cluster = stronger (more precise level)
    """
    # Touch score: 2 touches = 0.5, 3 = 0.75, 4+ = 1.0
    touch_score = min(1.0, touches / 4.0)

    # Tightness score: tighter cluster = stronger
    if avg_price > 0 and len(prices) > 1:
        spread = (max(prices) - min(prices)) / avg_price * 100
        tightness = max(0.0, 1.0 - spread / tolerance_pct)
    else:
        tightness = 1.0

    return round(touch_score * 0.6 + tightness * 0.4, 3)
