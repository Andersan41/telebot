"""
derivatives/open_interest.py — Open Interest analysis with pattern detection.
"""
from dataclasses import dataclass
from typing import Literal

from config.settings import config


@dataclass
class OIState:
    current_oi: float
    oi_change_pct: float
    significance: Literal["ignore", "moderate", "strong"]
    pattern: Literal["bullish_cont", "short_squeeze", "long_squeeze", "trap", "neutral"]

    def contributes_to(self, direction: str) -> int:
        """Score contribution for direction."""
        if self.significance == "ignore":
            return 0

        base = 5 if self.significance == "strong" else 2

        pattern_scores = {
            "bullish_cont": {"BUY": base, "SELL": -base},
            "short_squeeze": {"BUY": base, "SELL": -base},
            "long_squeeze": {"BUY": -base, "SELL": base},
            "trap": {"BUY": 0, "SELL": 0},
            "neutral": {"BUY": 0, "SELL": 0},
        }

        return pattern_scores.get(self.pattern, {}).get(direction.upper(), 0)


def classify_oi(oi_change_pct: float, price_change_pct: float, current_oi: float = 0.0) -> OIState:
    """Classify OI change and detect patterns.

    OI Change classification:
    - < 0.5% → ignore
    - 0.5% – 2% → moderate
    - > 2% → strong

    Pattern detection:
    - Price ↑ + OI ↑ → bullish continuation
    - Price ↑ + OI ↓ → short squeeze
    - Price ↓ + OI ↓ → long squeeze
    - OI ↑ but price flat → trap
    """
    moderate_thresh = config.derivatives.oi_moderate_threshold
    strong_thresh = config.derivatives.oi_strong_threshold

    abs_change = abs(oi_change_pct)

    if abs_change < moderate_thresh:
        significance = "ignore"
    elif abs_change < strong_thresh:
        significance = "moderate"
    else:
        significance = "strong"

    pattern = _detect_pattern(oi_change_pct, price_change_pct)

    return OIState(
        current_oi=current_oi,
        oi_change_pct=oi_change_pct,
        significance=significance,
        pattern=pattern,
    )


def _detect_pattern(oi_change: float, price_change: float) -> str:
    """Detect OI+Price pattern."""
    price_flat = abs(price_change) < 1.0

    if oi_change > 0 and price_change > 0 and not price_flat:
        return "bullish_cont"
    elif oi_change < 0 and price_change > 0:
        return "short_squeeze"
    elif oi_change < 0 and price_change < 0:
        return "long_squeeze"
    elif oi_change > 0 and price_flat:
        return "trap"
    return "neutral"
