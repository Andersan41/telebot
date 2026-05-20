"""
market_structure/tp_path.py — TP Path Quality Engine.

Evaluates the quality of the path from entry to take-profit.
Checks for obstacles between entry and TP that could block price movement.

Scoring:
- Clear path: +15
- 1 weak obstacle: +5
- Strong obstacle: -20
- TP inside support/resistance: REJECT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Literal, Optional

from config.settings import config


@dataclass
class Obstacle:
    type: Literal["resistance", "support", "liquidity_zone", "hvn", "order_block", "fvg"]
    price: float
    timeframe: str
    strength: Literal["weak", "strong"]
    description: str = ""


@dataclass
class TPEvaluation:
    score: int
    obstacles: List[Obstacle] = field(default_factory=list)
    blocked: bool = False
    reject_reason: str = ""


def evaluate_tp_path(
    direction: Literal["long", "short"],
    entry_price: float,
    tp_price: float,
    sr_levels: Dict[str, Dict[str, List[float]]],
    threshold_pct: Optional[float] = None,
    order_blocks: Optional[List] = None,
    fvgs: Optional[List] = None,
) -> TPEvaluation:
    """
    Evaluate the quality of the path from entry to TP.

    Args:
        direction: "long" or "short".
        entry_price: Entry price.
        tp_price: Take-profit price.
        sr_levels: S/R levels by timeframe.
        threshold_pct: Distance threshold for obstacle detection.

    Returns:
        TPEvaluation with score, obstacles, and blocked flag.
    """
    if threshold_pct is None:
        threshold_pct = getattr(config, "distance_filter_min_pct", 1.5)

    obstacles: List[Obstacle] = []
    score = 15

    if direction == "long":
        if tp_price <= entry_price:
            return TPEvaluation(score=0, blocked=True, reject_reason="TP <= entry for LONG")

        for tf, levels in sr_levels.items():
            for resistance in levels.get("resistance", []):
                if entry_price < resistance < tp_price:
                    dist_from_entry = (resistance - entry_price) / entry_price * 100
                    strength = "strong" if dist_from_entry < threshold_pct else "weak"
                    obstacles.append(
                        Obstacle(
                            type="resistance",
                            price=resistance,
                            timeframe=tf,
                            strength=strength,
                            description=f"Resistance at {resistance} on {tf} ({dist_from_entry:.1f}% from entry)",
                        )
                    )

            for support in levels.get("support", []):
                tp_dist = abs(tp_price - support) / support * 100
                if tp_dist < threshold_pct:
                    obstacles.append(
                        Obstacle(
                            type="support",
                            price=support,
                            timeframe=tf,
                            strength="strong",
                            description=f"TP near support at {support} on {tf} ({tp_dist:.1f}%)",
                        )
                    )

    elif direction == "short":
        if tp_price >= entry_price:
            return TPEvaluation(score=0, blocked=True, reject_reason="TP >= entry for SHORT")

        for tf, levels in sr_levels.items():
            for support in levels.get("support", []):
                if tp_price < support < entry_price:
                    dist_from_entry = (entry_price - support) / entry_price * 100
                    strength = "strong" if dist_from_entry < threshold_pct else "weak"
                    obstacles.append(
                        Obstacle(
                            type="support",
                            price=support,
                            timeframe=tf,
                            strength=strength,
                            description=f"Support at {support} on {tf} ({dist_from_entry:.1f}% from entry)",
                        )
                    )

            for resistance in levels.get("resistance", []):
                tp_dist = abs(tp_price - resistance) / resistance * 100
                if tp_dist < threshold_pct:
                    obstacles.append(
                        Obstacle(
                            type="resistance",
                            price=resistance,
                            timeframe=tf,
                            strength="strong",
                            description=f"TP near resistance at {resistance} on {tf} ({tp_dist:.1f}%)",
                        )
                    )

    if order_blocks:
        for ob in order_blocks:
            ob_mid = getattr(ob, "midpoint", (ob.high + ob.low) / 2)
            if direction == "long" and entry_price < ob_mid < tp_price:
                dist = (ob_mid - entry_price) / entry_price * 100
                strength = "strong" if dist < threshold_pct else "weak"
                obstacles.append(
                    Obstacle(
                        type="order_block",
                        price=ob_mid,
                        timeframe="liquidity",
                        strength=strength,
                        description=f"{ob.type} OB at {ob_mid:.4f} ({dist:.1f}% from entry)",
                    )
                )
            elif direction == "short" and tp_price < ob_mid < entry_price:
                dist = (entry_price - ob_mid) / entry_price * 100
                strength = "strong" if dist < threshold_pct else "weak"
                obstacles.append(
                    Obstacle(
                        type="order_block",
                        price=ob_mid,
                        timeframe="liquidity",
                        strength=strength,
                        description=f"{ob.type} OB at {ob_mid:.4f} ({dist:.1f}% from entry)",
                    )
                )

    if fvgs:
        for fvg in fvgs:
            fvg_mid = (fvg.top + fvg.bottom) / 2
            if direction == "long" and entry_price < fvg_mid < tp_price:
                dist = (fvg_mid - entry_price) / entry_price * 100
                strength = "strong" if dist < threshold_pct else "weak"
                obstacles.append(
                    Obstacle(
                        type="fvg",
                        price=fvg_mid,
                        timeframe="liquidity",
                        strength=strength,
                        description=f"{fvg.type} FVG at {fvg_mid:.4f} ({dist:.1f}% from entry)",
                    )
                )
            elif direction == "short" and tp_price < fvg_mid < entry_price:
                dist = (entry_price - fvg_mid) / entry_price * 100
                strength = "strong" if dist < threshold_pct else "weak"
                obstacles.append(
                    Obstacle(
                        type="fvg",
                        price=fvg_mid,
                        timeframe="liquidity",
                        strength=strength,
                        description=f"{fvg.type} FVG at {fvg_mid:.4f} ({dist:.1f}% from entry)",
                    )
                )

    strong_obstacles = [o for o in obstacles if o.strength == "strong"]
    weak_obstacles = [o for o in obstacles if o.strength == "weak"]

    if len(strong_obstacles) > 0:
        score = -20
    elif len(weak_obstacles) == 1:
        score = 5
    elif len(weak_obstacles) > 1:
        score = -10

    blocked = score <= -20

    if blocked:
        reject_reasons = [o.description for o in strong_obstacles]
        reject_reason = "; ".join(reject_reasons) if reject_reasons else "Strong obstacles on TP path"
    else:
        reject_reason = ""

    return TPEvaluation(
        score=score,
        obstacles=obstacles,
        blocked=blocked,
        reject_reason=reject_reason,
    )
