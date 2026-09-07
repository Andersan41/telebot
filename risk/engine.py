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
    equity: float = 0.0  # total portfolio equity in USDT


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
        min_rr_ratio: float = 2.0,
        sl_absolute_min_pct: float = 0.8,
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

    @classmethod
    def from_config(cls) -> "RiskEngine":
        """Create RiskEngine from config.risk_engine settings."""
        from config.settings import config
        rc = config.risk_engine
        return cls(
            min_rr_ratio=rc.min_rr_ratio,
            sl_absolute_min_pct=rc.sl_absolute_min_pct,
            sl_absolute_max_pct=rc.sl_absolute_max_pct,
            base_risk_pct=rc.base_risk_pct,
            min_risk_pct=rc.min_risk_pct,
            max_risk_pct=rc.max_risk_pct,
            sl_min_atr_multiplier=getattr(rc, 'sl_min_atr_multiplier', 2.0),
            max_active_signals=getattr(config, 'max_active_signals', 3),
            max_portfolio_risk_pct=getattr(config, 'max_portfolio_risk_pct', 3.0),
        )

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

        # 0. Portfolio limits
        if portfolio.active_count >= portfolio.max_active_signals:
            return RiskDecision(
                should_trade=False,
                rejection_reason=f"max active signals reached ({portfolio.active_count}/{portfolio.max_active_signals})",
            )
        if portfolio.total_risk_pct >= portfolio.max_portfolio_risk_pct:
            return RiskDecision(
                should_trade=False,
                rejection_reason=f"portfolio risk limit reached ({portfolio.total_risk_pct:.2f}%/{portfolio.max_portfolio_risk_pct}%)",
            )

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

        # Account for exchange fees + slippage in R:R calculation
        from config.settings import config
        _fee = getattr(config.trading, 'exchange_fee_pct', 0.05) / 100  # per side
        _slip = getattr(config.trading, 'slippage_pct', 0.05) / 100    # per side
        _round_trip_cost = (_fee + _slip) * 2  # entry + exit costs
        _cost_dist = entry_price * _round_trip_cost

        # Effective risk = SL distance + round-trip costs
        effective_risk = risk_dist + _cost_dist
        # Effective reward = TP distance - round-trip costs
        effective_reward = max(0, reward_dist - _cost_dist)

        rr_ratio = effective_reward / effective_risk if effective_risk > 0 else 0
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

        # Dynamic SL max: A1 fix — dead zone eliminated
        # Formula: sl_max = max(5.0%, ATR × 2.2), clamp ≤ 8.0%
        # If sl_min_atr > sl_max → relaxed (see 3b below)
        atr_pct = atr / entry_price * 100 if entry_price > 0 else 0.0
        dynamic_sl_max = max(self.sl_absolute_max_pct, atr_pct * 2.2)
        dynamic_sl_max = min(dynamic_sl_max, 8.0)  # hard cap at 8%

        if sl_distance_pct > dynamic_sl_max:
            return RiskDecision(
                should_trade=False,
                rr_ratio=rr_ratio,
                rejection_reason=f"SL too wide: {sl_distance_pct:.2f}% > {dynamic_sl_max:.2f}%",
            )

        # 3b. SL minimum ATR multiplier (prevent tight SL on volatile symbols)
        if atr > 0 and entry_price > 0:
            min_sl_from_atr = atr_pct * self.sl_min_atr_multiplier
            # A1 fix: if ATR-min floor exceeds dynamic SL max → relax floor
            # (e.g. ATR=4.5%: min=9.0% > max=8.0% → dead zone)
            if min_sl_from_atr > dynamic_sl_max:
                logger.warning(
                    f"SL ATR-min relaxed: {min_sl_from_atr:.2f}% > "
                    f"dynamic_sl_max={dynamic_sl_max:.2f}% (atr={atr_pct:.2f}%)"
                )
                min_sl_from_atr = dynamic_sl_max
            if sl_distance_pct < min_sl_from_atr:
                return RiskDecision(
                    should_trade=False,
                    rr_ratio=rr_ratio,
                    rejection_reason=f"SL too tight vs ATR: {sl_distance_pct:.2f}% < {self.sl_min_atr_multiplier}x ATR ({min_sl_from_atr:.2f}%)",
                )

        # === POSITION SIZING ===

        # A09: EV gate — applies to BOTH fixed and Kelly modes
        _p = probability.p_tp
        _b = rr_ratio
        _ev = _p * _b - (1 - _p)
        if _ev <= 0:
            return RiskDecision(
                should_trade=False,
                rr_ratio=rr_ratio,
                rejection_reason=f"negative EV: p={_p:.2f} * rr={_b:.2f} - (1-p) = {_ev:.4f} <= 0",
            )

        _risk_mode = getattr(config, 'risk_mode', 'fixed')

        kelly = 0.0
        if _risk_mode == 'fixed':
            # Fixed risk: risk = base_risk_pct, position sized by SL distance
            risk_pct = self.base_risk_pct
        else:
            # Kelly-inspired: f = (p * b - q) / b
            p = probability.p_tp
            q = 1 - p
            b = rr_ratio
            kelly = (p * b - q) / b if b > 0 else 0

            # Reject negative-EV trades (kelly <= 0 means expected loss)
            if kelly <= 0:
                return RiskDecision(
                    should_trade=False,
                    rejection_reason=f"kelly={kelly:.4f} <= 0 (negative EV: p={p:.2f}, rr={rr_ratio:.2f})",
                )

            kelly = min(kelly, 0.20)  # cap at 20% (half-Kelly)

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

        # Min notional check (A10 fix — correct dimension: quantity * entry = notional in USDT)
        min_notional = getattr(config, 'min_notional_usdt', 5.0)
        if portfolio.equity > 0 and entry_price > 0 and risk_dist > 0:
            risk_budget_quote = portfolio.equity * risk_pct / 100.0
            loss_per_unit = risk_dist  # abs(entry - sl) in price units
            quantity_base = risk_budget_quote / loss_per_unit
            notional_quote = quantity_base * entry_price
            if notional_quote < min_notional:
                return RiskDecision(
                    should_trade=False,
                    rejection_reason=f"notional ${notional_quote:.2f} < min ${min_notional} (qty={quantity_base:.6f})",
                )

        logger.info(
            f"Risk decision: risk={risk_pct:.2f}% | "
            f"RR={rr_ratio:.2f} | SL={sl_distance_pct:.2f}% | "
            f"P(TP)={probability.p_tp:.1%} | "
            f"vol_adj={vol_adj:.2f} | mss_adj={mss_adj:.2f} | "
            f"scenario_adj={scenario_adj:.2f} | "
            f"stability_adj={stability_adj:.2f} | "
            f"mode={_risk_mode}"
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
risk_engine = RiskEngine.from_config()
