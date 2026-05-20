"""
derivatives/funding.py — Funding rate analysis with strong/moderate/neutral classification.
"""
from dataclasses import dataclass
from typing import Literal

from config.settings import config


@dataclass
class FundingState:
    current_rate: float
    predicted_rate: float | None
    state: Literal["bullish", "bearish", "neutral"]
    strength: Literal["strong", "moderate", "weak"]

    def contributes_to(self, direction: str) -> int:
        """Score contribution for direction: +5, 0, -5"""
        if self.strength == "weak":
            return 0

        if direction.upper() == "BUY":
            if self.state == "bullish":
                return 5 if self.strength == "strong" else 2
            elif self.state == "bearish":
                return -5 if self.strength == "strong" else -2
            return 0
        else:
            if self.state == "bearish":
                return 5 if self.strength == "strong" else 2
            elif self.state == "bullish":
                return -5 if self.strength == "strong" else -2
            return 0


def classify_funding(rate: float, predicted_rate: float | None = None) -> FundingState:
    """Classify funding rate into state and strength.

    Rules (from plan/update1/phase03_derivatives.md):
    - SHORT strong: Funding > 0.03% (overcrowded longs)
    - LONG strong:  Funding < -0.03% (short squeeze setup)
    - Ignore zone:  -0.01% .. +0.01% → neutral
    """
    strong_thresh = config.derivatives.funding_strong_threshold
    neutral_zone = config.derivatives.funding_neutral_zone

    abs_rate = abs(rate)

    if abs_rate <= neutral_zone:
        return FundingState(
            current_rate=rate,
            predicted_rate=predicted_rate,
            state="neutral",
            strength="weak",
        )

    if rate > 0:
        state = "bearish"
    else:
        state = "bullish"

    if abs_rate >= strong_thresh:
        strength = "strong"
    elif abs_rate > neutral_zone:
        strength = "moderate"
    else:
        strength = "weak"

    return FundingState(
        current_rate=rate,
        predicted_rate=predicted_rate,
        state=state,
        strength=strength,
    )
