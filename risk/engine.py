"""
risk/engine.py — Risk Engine (Layer 3)

Capital protection + position sizing.

Hard gates (MUST pass):
- R:R minimum
- SL absolute limits
- Portfolio risk
- Max active signals
- Data integrity

Soft adjustments (affect sizing, not blocking):
- Volatility scaling
- SL distance quality
- Probability-based Kelly sizing
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from loguru import logger

from strategy.feature_builder import SetupFeatures
from strategy.probability_engine import TradeProbability


@dataclass
class PortfolioState:
    """Current portfolio state for risk calculations."""
    active_count: int = 0
    total_risk_pct: float = 0.0
    max_active_signals: int = 3
    max_portfolio_risk_pct: float = 3.0


@dataclass
class RiskDecision:
    """Output of the Risk Engine."""
    should_trade: bool
    risk_pct: float = 0.0  # % of capital to risk
    rr_ratio: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0
    rejection_reason: Optional[str] = None

    # Sizing details (for logging/analytics)
    kelly_fraction: float = 0.0
    volatility_adjustment: float = 1.0
    probability_confidence: float = 0.0
    scenario_score_adjustment: float = 1.0   # multiplier from ScenarioScore
    scenario_stability_adjustment: float = 1.0  # multiplier from scenario_stability


class RiskEngine:
    """Evaluates whether a trade can be executed and sizes the position.

    Only checks capital protection constraints. Does NOT evaluate setup quality.
    """

    def __init__(
        self,
        min_rr_ratio: float = 1.5,
        sl_absolute_min_pct: float = 0.25,
        sl_absolute_max_pct: float = 5.0,
        base_risk_pct: float = 1.0,
        min_risk_pct: float = 0.1,
        max_risk_pct: float = 1.0,
        max_active_signals: int = 3,
        max_portfolio_risk_pct: float = 3.0,
        sl_min_atr_multiplier: float = 2.0,
    ):
        self.min_rr_ratio = min_rr_ratio
        self.sl_absolute_min_pct = sl_absolute_min_pct
        self.sl_absolute_max_pct = sl_absolute_max_pct
        self.base_risk_pct = base_risk_pct
        self.min_risk_pct = min_risk_pct
        self.max_risk_pct = max_risk_pct
        self.max_active_signals = max_active_signals
        self.max_portfolio_risk_pct = max_portfolio_risk_pct
        self.sl_min_atr_multiplier = sl_min_atr_multiplier

    def evaluate(
        self,
        features: SetupFeatures,
        probability: TradeProbability,
        portfolio: PortfolioState,
        entry_price: float,
        sl: float,
        tp: float,
        scenario_score: float = 0.0,
        scenario_stability: float = 0.0,
        hypothesis: Optional[object] = None,
        mss_quality: float = 0.0,
        atr: float = 0.0,
    ) -> RiskDecision:
        """Evaluate risk and size the position.

        Args:
            features: SetupFeatures from FeatureBuilder
            probability: TradeProbability from ProbabilityEngine
            portfolio: current portfolio state
            entry_price: entry price
            sl: stop loss price
            tp: take profit price
            scenario_score: scenario quality score [0, 100] from MarketThesisEngine
            scenario_stability: scenario stability [0, 1] from DynamicTradeThesis
            hypothesis: optional Hypothesis from DecisionEngine (new pipeline)

        Returns:
            RiskDecision with should_trade, risk_pct, and details.
        """
        # === HARD GATES ===

        # 1. Data integrity
        if entry_price <= 0 or sl <= 0 or tp <= 0:
            return RiskDecision(
                should_trade=False,
                rejection_reason="invalid price data",
            )

        risk_dist = abs(entry_price - sl)
        reward_dist = abs(tp - entry_price)

        if risk_dist <= 0:
            return RiskDecision(
                should_trade=False,
                rejection_reason="zero risk distance",
            )

        rr_ratio = reward_dist / risk_dist
        sl_distance_pct = risk_dist / entry_price * 100

        # 2. R:R minimum
        if rr_ratio < self.min_rr_ratio:
            return RiskDecision(
                should_trade=False,
                rr_ratio=rr_ratio,
                rejection_reason=f"RR={rr_ratio:.2f} < {self.min_rr_ratio}",
            )

        # 3. SL absolute limits
        if sl_distance_pct < self.sl_absolute_min_pct:
            return RiskDecision(
                should_trade=False,
                rr_ratio=rr_ratio,
                rejection_reason=f"SL too tight: {sl_distance_pct:.2f}% < {self.sl_absolute_min_pct}%",
            )

        if sl_distance_pct > self.sl_absolute_max_pct:
            return RiskDecision(
                should_trade=False,
                rr_ratio=rr_ratio,
                rejection_reason=f"SL too wide: {sl_distance_pct:.2f}% > {self.sl_absolute_max_pct}%",
            )

        # 3b. SL minimum ATR multiplier (prevent tight SL on volatile symbols)
        if atr > 0 and entry_price > 0:
            atr_pct = atr / entry_price * 100
            min_sl_from_atr = atr_pct * self.sl_min_atr_multiplier
            if sl_distance_pct < min_sl_from_atr:
                return RiskDecision(
                    should_trade=False,
                    rr_ratio=rr_ratio,
                    rejection_reason=f"SL too tight vs ATR: {sl_distance_pct:.2f}% < {self.sl_min_atr_multiplier}x ATR ({min_sl_from_atr:.2f}%)",
                )

        # === POSITION SIZING ===

        # Kelly-inspired: f = (p * b - q) / b
        p = probability.p_tp
        q = 1 - p
        b = rr_ratio
        kelly = (p * b - q) / b if b > 0 else 0
        kelly = max(0.0, min(kelly, 0.20))  # cap at 20% (half-Kelly)

        # Scale by model confidence
        kelly *= probability.confidence

        # Final risk = min(kelly, base_risk)
        risk_pct = min(kelly * 100, self.base_risk_pct)

        # Scenario score scaling (from MarketThesisEngine)
        # Higher scenario quality → larger position (up to 1.2x)
        # Lower scenario quality → smaller position (down to 0.6x)
        scenario_adj = 1.0
        if scenario_score > 0:
            # Map [0, 100] → [0.6, 1.2]
            scenario_adj = 0.6 + (scenario_score / 100.0) * 0.6
            scenario_adj = max(0.6, min(1.2, scenario_adj))
        risk_pct *= scenario_adj

        # Scenario stability scaling (from DynamicTradeThesis)
        # High stability (confirmed nodes) → higher risk tolerance (up to 1.15x)
        # Low stability (decaying/invalidated) → reduced risk (down to 0.7x)
        stability_adj = 1.0
        if scenario_stability > 0:
            # Map [0, 1] → [0.7, 1.15]
            stability_adj = 0.7 + max(0.0, min(1.0, scenario_stability)) * 0.45
            stability_adj = max(0.7, min(1.15, stability_adj))
        risk_pct *= stability_adj

        # Volatility adjustment
        vol_adj = 1.0
        if features.atr_pct > 4.0:
            vol_adj = 0.5
        elif features.atr_pct > 2.5:
            vol_adj = 0.75
        risk_pct *= vol_adj

        # MSS quality soft adjustment (0-100 → 0.8x-1.1x)
        mss_adj = 1.0
        if mss_quality > 0:
            mss_adj = 0.8 + (mss_quality / 100.0) * 0.3
            mss_adj = max(0.8, min(1.1, mss_adj))
        risk_pct *= mss_adj

        # SL distance quality (soft)
        if sl_distance_pct < 1.0:
            risk_pct *= 1.1  # bonus for tight SL
        elif sl_distance_pct > 3.0:
            risk_pct *= 0.8  # penalty for wide SL

        # Clamp
        risk_pct = max(self.min_risk_pct, min(risk_pct, self.max_risk_pct))

        logger.info(
            f"Risk decision: risk={risk_pct:.2f}% | "
            f"RR={rr_ratio:.2f} | SL={sl_distance_pct:.2f}% | "
            f"P(TP)={probability.p_tp:.1%} | Kelly={kelly:.3f} | "
            f"vol_adj={vol_adj:.2f} | mss_adj={mss_adj:.2f} | "
            f"scenario_adj={scenario_adj:.2f} | "
            f"stability_adj={stability_adj:.2f}"
        )

        return RiskDecision(
            should_trade=True,
            risk_pct=round(risk_pct, 4),
            rr_ratio=round(rr_ratio, 2),
            sl_price=sl,
            tp_price=tp,
            kelly_fraction=round(kelly, 4),
            volatility_adjustment=vol_adj,
            probability_confidence=probability.confidence,
            scenario_score_adjustment=round(scenario_adj, 4),
            scenario_stability_adjustment=round(stability_adj, 4),
        )


# Singleton
risk_engine = RiskEngine()
