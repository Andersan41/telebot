"""
risk/no_trade_zones.py — Blocks signals when market conditions are unfavorable.

Blocks if ANY condition is true:
- ATR too low (no momentum)
- Market range-bound (no trend)
- BTC unclear (correlation risk)
- TP blocked (path to target obstructed)
- OI weak (no institutional participation)

Note: Neutral funding no longer blocks trades (FIX M5) — only logged for visibility.
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class NoTradeCheck:
    blocked: bool = False
    reasons: list = field(default_factory=list)

    def add(self, condition: bool, reason: str) -> None:
        if condition:
            self.blocked = True
            self.reasons.append(reason)


def _low_atr_threshold() -> float:
    return float(os.getenv("NO_TRADE_MIN_ATR_PCT", "0.5"))


def check_no_trade_zones(
    funding_state: Optional[str] = None,
    funding_strength: Optional[str] = None,
    atr_pct: float = 0.0,
    market_structure: Optional[str] = None,
    btc_aligned: bool = True,
    tp_blocked: bool = False,
    oi_significance: Optional[str] = None,
    oi_pattern: Optional[str] = None,
    market_type: str = 'futures',
) -> NoTradeCheck:
    """Check all no-trade zone conditions.

    Args:
        funding_state: "bullish", "bearish", or "neutral"
        funding_strength: "strong", "moderate", or "weak"
        atr_pct: ATR as percentage of price
        market_structure: "bullish", "bearish", or "ranging"
        btc_aligned: True if BTC correlation is OK for the trade
        tp_blocked: True if TP path is obstructed
        oi_significance: "ignore", "moderate", or "strong"
        oi_pattern: "extreme_long", "extreme_short", or None
        market_type: "spot" or "futures"
    """
    check = NoTradeCheck()

    # FIX M5: neutral funding no longer blocks — just log for visibility
    if funding_state == "neutral" and funding_strength == "weak":
        logger.debug("Funding neutral — no derivatives edge (info only, not blocking)")

    check.add(
        atr_pct < _low_atr_threshold(),
        f"ATR too low ({atr_pct:.2f}%) — no momentum",
    )

    check.add(
        market_structure == "ranging",
        "Market range-bound — no trend to follow",
    )

    check.add(
        not btc_aligned,
        "BTC unclear — correlation risk",
    )

    check.add(
        tp_blocked,
        "TP blocked — path to target obstructed",
    )

    # FIX P3: OI None/ignore не блокирует — нет данных != опасность
    if oi_significance is None or oi_significance == 'ignore':
        if market_type == 'spot':
            logger.debug("OI unavailable on spot market — skipping OI gate")
        else:
            logger.debug("OI significance=ignore — allowing trade (no data != danger)")
    elif oi_pattern in ('extreme_long', 'extreme_short'):
        check.add(
            True,
            f"OI extreme: {oi_pattern}",
        )

    return check
