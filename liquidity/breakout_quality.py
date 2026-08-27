"""
liquidity/breakout_quality.py — Distinguish a real breakout from a manipulation (AMD/stop-hunt).

The market often fakes a breakout: price pierces a range boundary to hunt stop losses
("AMD" — Accumulation/Manipulation/Distribution pattern), collects orders, then reverses.
This engine classifies whether the move beyond a boundary is:

  - real   : close (not just wick) beyond the boundary + displacement + volume/OI confirm
  - fake   : pierce beyond the boundary but close back inside (AMD sweep), or weak volume
  - ambiguous : not enough confirmation either way

Pure heuristic computation. No blocking by itself — the caller decides how to use the
verdict (shadow log, soft feature, or hard gate).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

import pandas as pd

from config.settings import config


@dataclass
class BreakoutQuality:
    """Result of the breakout-quality classification."""

    verdict: Literal["real", "fake", "ambiguous"] = "ambiguous"
    direction: Optional[str] = None  # the direction we tested ("buy"/"sell")
    score: float = 0.0  # 0..100, how strongly a real breakout is supported
    boundary: float = 0.0  # the price level being tested (swing high/low)
    close_past_boundary: bool = False
    pierce_pct: float = 0.0  # how far close pierced the boundary (% of price)
    body_pct: float = 0.0  # portion of the candle body beyond the boundary (0..1)
    retention: int = 0  # consecutive closes beyond the boundary (bars)
    volume_ratio: float = 0.0
    taker_delta_pct: float = 0.0
    oi_change_pct: Optional[float] = None
    displacement_atr: float = 0.0
    triggers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_real(self) -> bool:
        return self.verdict == "real"


def classify_breakout(
    df: pd.DataFrame,
    direction: str,  # "buy" or "sell"
    atr: float = 0.0,
    oi_change_pct: Optional[float] = None,
    lookback: int = 40,
) -> BreakoutQuality:
    """Classify the most recent candle against the settled range boundary.

    boundary is derived from swing high/low over the lookback window EXCLUDING the last
    2 candles, so we test against a settled, not forming, structure.

    A "real" breakout requires the candle CLOSE to sit beyond the boundary with at least
    half the body beyond it, plus optional volume / OI / displacement confirmation.

    An "fake" (AMD) report is given when price pierced past the boundary but the close
    returned inside the range, or volume is too weak to sustain the move.

    Never raises.
    """
    if direction not in ("buy", "sell"):
        return BreakoutQuality(verdict="ambiguous", direction=direction)

    if df is None or len(df) < lookback + 2:
        return BreakoutQuality(verdict="ambiguous", direction=direction)

    tail = df.tail(lookback + 2).reset_index(drop=True)
    settled = tail.iloc[:-2]

    boundary_high = float(settled["high"].max())
    boundary_low = float(settled["low"].min())

    last = tail.iloc[-1]
    close = float(last["close"])

    if direction == "buy":
        boundary = boundary_high
        valid = close >= boundary and boundary > 0
        pierce_extreme = float(tail["high"].iloc[-2:].max())
    else:
        boundary = boundary_low
        valid = close <= boundary and boundary > 0
        pierce_extreme = float(tail["low"].iloc[-2:].min())

    if boundary <= 0:
        return BreakoutQuality(verdict="ambiguous", direction=direction, boundary=boundary)

    if not valid:
        # AMD fake-break: price WICKED past the boundary within the last bars but
        # closed back inside the range (stop-hunt, no close beyond the level).
        if direction == "buy" and pierce_extreme > boundary:
            return BreakoutQuality(
                verdict="fake", direction=direction, boundary=boundary,
                close_past_boundary=False,
                pierce_pct=abs(pierce_extreme - boundary) / boundary * 100,
                body_pct=0.0, retention=0, volume_ratio=0.0,
                displacement_atr=abs(pierce_extreme - boundary) / atr if atr else 0.0,
                warnings=["AMD fake-break: wick past boundary, close back inside"],
            )
        if direction == "sell" and pierce_extreme < boundary:
            return BreakoutQuality(
                verdict="fake", direction=direction, boundary=boundary,
                close_past_boundary=False,
                pierce_pct=abs(boundary - pierce_extreme) / boundary * 100,
                body_pct=0.0, retention=0, volume_ratio=0.0,
                displacement_atr=abs(boundary - pierce_extreme) / atr if atr else 0.0,
                warnings=["AMD raid-break: wick past boundary, close back inside"],
            )
        return BreakoutQuality(verdict="ambiguous", direction=direction, boundary=boundary)

    pierce = abs(close - boundary)
    pierce_pct = pierce / boundary * 100

    rng = float(last["high"]) - float(last["low"])
    body_pct = 0.0
    if rng > 0:
        if direction == "buy":
            body_pct = max(0.0, min(1.0, (close - boundary) / rng))
        else:
            body_pct = max(0.0, min(1.0, (boundary - close) / rng))

    retention = 0
    for i in range(len(tail) - 1, -1, -1):
        c = float(tail.iloc[i]["close"])
        if (direction == "buy" and c >= boundary) or (direction == "sell" and c <= boundary):
            retention += 1
        else:
            break

    vol = float(last["volume"]) if "volume" in last else 0.0
    avg_vol = float(tail["volume"].iloc[-lookback:].mean()) if lookback > 0 else 0.0
    volume_ratio = vol / avg_vol if avg_vol > 0 else 0.0

    disp_atr = pierce / atr if atr and pierce > 0 else 0.0

    score = 0.0
    triggers: list[str] = []
    warnings: list[str] = []
    min_vol = getattr(config, "liquidity_sweep_min_volume_ratio", 1.8)

    if body_pct >= 0.5:
        triggers.append("close beyond boundary")
        score += 40
    if retention >= 2:
        triggers.append(f"retention {retention} bars")
        score += 20
    if disp_atr >= 1.0:
        triggers.append(f"displacement {disp_atr:.1f} ATR")
        score += 15
    if volume_ratio >= min_vol:
        triggers.append(f"volume {volume_ratio:.1f}x")
        score += 15

    if oi_change_pct is not None:
        oi_pos = oi_change_pct > 0
        if (direction == "buy" and oi_pos) or (direction == "sell" and not oi_pos):
            triggers.append(f"OI {oi_change_pct:+.1f}%")
            score += 15
    else:
        warnings.append("no OI data")

    penalty = 0
    if body_pct < 0.5:
        warnings.append("mostly wick, close returned inside range")
        penalty += 25
    if retention < 2:
        warnings.append("no retention (AMD fake-break risk)")
        penalty += 15

    score = max(0.0, score - penalty)

    if score >= 55:
        verdict = "real"
    elif body_pct >= 0.5:
        verdict = "real" if score >= 25 else "ambiguous"
    else:
        verdict = "ambiguous" if score < 40 else "real"

    return BreakoutQuality(
        verdict=verdict,
        direction=direction,
        score=score,
        boundary=boundary,
        close_past_boundary=valid,
        pierce_pct=pierce_pct,
        body_pct=body_pct,
        retention=retention,
        volume_ratio=volume_ratio,
        taker_delta_pct=0.0,
        oi_change_pct=oi_change_pct,
        displacement_atr=disp_atr,
        triggers=triggers,
        warnings=warnings,
    )