"""
risk/volatility_regime.py — Volatility regime classification based on ATR%.

Regimes (configurable via .env):
- Low:    ATR% < VOLATILITY_LOW_THRESHOLD  (default 1.0%) → avoid breakouts
- Medium: between thresholds               → normal operation
- High:   ATR% > VOLATILITY_HIGH_THRESHOLD (default 4.0%) → reduce position size
"""
import os
from dataclasses import dataclass
from typing import Literal

from config.settings import config


@dataclass
class VolatilityRegime:
    regime: Literal["low", "medium", "high"]
    atr_pct: float
    atr_value: float

    @property
    def allow_breakout(self) -> bool:
        return self.regime != "low"

    @property
    def position_size_multiplier(self) -> float:
        if self.regime == "high":
            return 0.5
        return 1.0


def _low_threshold() -> float:
    return float(os.getenv("VOLATILITY_LOW_THRESHOLD", "1.0"))


def _high_threshold() -> float:
    return float(os.getenv("VOLATILITY_HIGH_THRESHOLD", "4.0"))


def classify_volatility(atr_value: float, close_price: float) -> VolatilityRegime:
    """Classify volatility regime from ATR value and current close price.

    ATR% = (ATR / close) * 100
    """
    if close_price <= 0:
        return VolatilityRegime(regime="medium", atr_pct=0.0, atr_value=atr_value)

    atr_pct = (atr_value / close_price) * 100.0

    low = _low_threshold()
    high = _high_threshold()

    if atr_pct < low:
        regime = "low"
    elif atr_pct > high:
        regime = "high"
    else:
        regime = "medium"

    return VolatilityRegime(regime=regime, atr_pct=round(atr_pct, 2), atr_value=atr_value)


def get_volatility_config() -> dict:
    """Return current volatility thresholds for logging/debugging."""
    return {
        "low_threshold": _low_threshold(),
        "high_threshold": _high_threshold(),
        "atr_period": int(os.getenv("VOLATILITY_ATR_PERIOD", "14")),
    }
