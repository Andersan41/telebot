"""
strategy/probability_engine.py — Probability Engine

Evaluates P(TP) for a detected ICT setup based on accumulated features.

Two modes:
1. Rules-based fallback (when no ML model available) — simple heuristics
2. ML-based (XGBoost/RandomForest) — trained on historical outcomes

The ML model replaces rules once enough data is accumulated (100+ outcomes).
"""
from __future__ import annotations

import os
import pickle
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
from loguru import logger

from strategy.feature_builder import SetupFeatures
from strategy.scenario_engine import MarketScenario, ScenarioEvaluation
from strategy.market_phase_engine import MarketPhase, PhaseAssessment, get_phase_modifier
from config.settings import config


@dataclass
class TradeProbability:
    """Probability assessment for an ICT setup."""
    p_tp: float  # 0.0–1.0 probability of hitting TP
    expected_rr: float  # expected risk-reward
    profit_factor: float  # expected profit factor
    confidence: float  # 0.0–1.0 how confident is the model
    model_type: str  # "rules" / "xgboost" / "random_forest"
    feature_importance: Optional[Dict[str, float]] = None

    @property
    def quality_label(self) -> str:
        if self.p_tp >= 0.65:
            return "strong"
        elif self.p_tp >= 0.50:
            return "moderate"
        else:
            return "weak"

    @property
    def p_tp_pct(self) -> float:
        return self.p_tp * 100

    @property
    def profit_factor_label(self) -> str:
        if self.profit_factor >= 2.0:
            return "excellent"
        elif self.profit_factor >= 1.5:
            return "good"
        elif self.profit_factor >= 1.0:
            return "marginal"
        else:
            return "poor"


class ProbabilityEngine:
    """Estimates P(TP) for detected ICT setups.

    Uses ML model if available, otherwise falls back to rules-based estimation.
    Rules are NOT hand-tuned weights — they are simple heuristics that will be
    replaced by ML once we have enough historical outcome data.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        historical_winrate: Optional[float] = None,
    ):
        self.model_path = model_path or os.getenv(
            "PROBABILITY_MODEL_PATH", "models/probability_model.pkl"
        )
        self.historical_winrate = historical_winrate
        self.model = None
        self.rr_model = None
        self.isotonic = None
        self.model_type = "legacy"
        self.feature_names: List[str] = []
        self._load_model()

    def _load_model(self) -> None:
        """Load trained ML model if available.

        Supports two formats:
          - Legacy: {"classifier": ..., "regressor": ...}
          - Expected return: {"regressor": ..., "isotonic": ..., "model_type": "expected_return"}
        """
        if not os.path.exists(self.model_path):
            logger.debug(
                f"No probability model at {self.model_path} — using rules fallback"
            )
            return
        try:
            with open(self.model_path, "rb") as f:
                data = pickle.load(f)

            self.model_type = data.get("model_type", "legacy")

            if self.model_type == "expected_return":
                # New format: regressor predicts expected return, isotonic calibrates probability
                self.model = data.get("regressor")
                self.rr_model = None  # No separate RR model — regressor IS the return model
                self.isotonic = data.get("isotonic")
            else:
                # Legacy format: classifier for P(TP), regressor for expected RR
                self.model = data.get("classifier")
                self.rr_model = data.get("regressor")
                self.isotonic = None

            self.feature_names = data.get("feature_names", [])
            logger.info(
                f"Loaded probability model ({self.model_type}): "
                f"{self.model.__class__.__name__} "
                f"({len(self.feature_names)} features)"
            )
        except Exception as e:
            logger.warning(f"Failed to load probability model: {e}")
            self.model = None

    def predict(
        self,
        features: SetupFeatures,
        symbol: str = "",
        scenario_name: str = "",
    ) -> TradeProbability:
        """Predict trade probability from features.

        Args:
            features: SetupFeatures from FeatureBuilder
            symbol: optional symbol for scenario memory lookup
            scenario_name: optional scenario name for scenario memory lookup

        Returns:
            TradeProbability with P(TP), expected RR, profit factor.
        """
        if self.model is not None:
            return self._predict_ml(features)
        return self._predict_rules(features, symbol=symbol, scenario_name=scenario_name)

    def _predict_rules(
        self,
        f: SetupFeatures,
        symbol: str = "",
        scenario_name: str = "",
    ) -> TradeProbability:
        """Rules-based probability estimation.

        This is a TEMPORARY bootstrap model. NOT hand-tuned weights.
        Equal-weight starting point that will be replaced by ML after
        200-300 trades with observed expectancy.

        Reversal scoring:
          sweep: +3.0, displacement: +3.0, MSS: +4.0 (highest)
          OB/FVG: +1.5/+1.0 (confirmation, not trigger)
          MSS quality >70: +2.0, 50-70: +1.0

        Continuation scoring:
          BOS: +3.0, structure aligned: +2.0
          OB/FVG: +1.5/+1.0

        Common: volume, R:R, MTF, session, ATR, context
        """
        # Base rate: prefer scenario_memory stats, fallback to historical, then 50
        base = self.historical_winrate if self.historical_winrate else 50.0
        if symbol and scenario_name:
            try:
                from strategy.scenario_memory import scenario_memory
                stats = scenario_memory.get_stats(symbol, scenario_name)
                if stats and stats.closed_count >= 10:
                    base = stats.winrate * 100.0
            except Exception:
                pass

        # ═══ Regime-adaptive adjustment ═══
        # Different regimes favor different setup types
        regime_edge = 0.0
        regime = f.regime if f.regime else ""
        if regime == "expansion":
            # Expansion: continuation works better, reversal worse
            if f.setup_type == "continuation":
                regime_edge += 2.0
            elif f.setup_type == "reversal":
                regime_edge -= 1.5
        elif regime == "compression":
            # Compression: breakout (continuation with BOS) works, reversal risky
            if f.setup_type == "continuation" and f.has_bos:
                regime_edge += 1.5
            elif f.setup_type == "reversal":
                regime_edge -= 1.0
        elif regime == "trend":
            # Strong trend: continuation aligned = good, reversal against trend = bad
            if f.setup_type == "continuation" and f.structure_bos_aligned:
                regime_edge += 2.5
            elif f.setup_type == "reversal":
                regime_edge -= 2.0
        elif regime == "range":
            # Range: reversal works better, continuation struggles
            if f.setup_type == "reversal":
                regime_edge += 1.5
            elif f.setup_type == "continuation":
                regime_edge -= 1.0
        elif regime == "high_vol":
            # High volatility: both directions risky, slight penalty
            regime_edge -= 1.0
        elif regime == "low_vol":
            # Low volatility: tight ranges, breakout potential
            if f.setup_type == "continuation" and f.has_bos:
                regime_edge += 1.0

        # ═══ Setup-type-specific scoring ═══
        component_edge = 0.0

        if f.setup_type == "reversal":
            # Reversal: sweep + displacement + MSS are the core
            if f.has_sweep:
                component_edge += 3.0
            if f.has_displacement:
                component_edge += 3.0
            if f.has_mss:
                component_edge += 4.0  # MSS is the strongest signal
                # MSS quality bonus
                if f.mss_score >= 70:
                    component_edge += 2.0
                elif f.mss_score >= 50:
                    component_edge += 1.0
            # Entry zones (confirmation)
            if f.has_ob:
                component_edge += 1.5
            if f.has_fvg:
                component_edge += 1.0
            if f.entry_armed:
                component_edge += 1.5

        elif f.setup_type == "continuation":
            # Continuation: BOS + trend alignment
            if f.has_bos:
                component_edge += 3.0
            if f.structure_bos_aligned:
                component_edge += 2.0
            # Entry zones (confirmation)
            if f.has_ob:
                component_edge += 1.5
            if f.has_fvg:
                component_edge += 1.0
            if f.entry_armed:
                component_edge += 1.5

        # ═══ Common scoring (both types) ═══

        # Structure alignment (continuation) or MSS quality (reversal)
        structure_edge = 0.0
        if f.structure_bos_aligned:
            structure_edge += 2.0

        # Volume — displacement confirmation
        volume_edge = 0.0
        if f.volume_ratio > 2.0:
            volume_edge += 3.0
        elif f.volume_ratio > 1.5:
            volume_edge += 2.0
        elif f.volume_ratio > 1.2:
            volume_edge += 1.0

        # R:R quality — REMOVED (A3): RR is already used to calculate SL/TP,
        # adding it to probability creates a feedback loop (RR ≠ P(TP))

        # MTF alignment
        mtf_edge = 0.0
        if f.mtf_aligned:
            mtf_edge += 2.0

        # Session quality
        session_edge = 0.0
        if f.session in ("overlap", "london", "new_york"):
            session_edge += 1.0

        # ATR quality (sweet spot: 1-3%)
        atr_edge = 0.0
        if 1.0 <= f.atr_pct <= 3.0:
            atr_edge += 1.5
        elif f.atr_pct > 5.0:
            atr_edge -= 2.0
        elif f.atr_pct < 0.5:
            atr_edge -= 1.5

        # Context (secondary — small adjustments)
        ctx_edge = 0.0
        if f.context_score > 0.3:
            ctx_edge += 1.0
        elif f.context_score < -0.3:
            ctx_edge -= 1.5

        # Total
        winrate = (
            base + component_edge + structure_edge + volume_edge
            + mtf_edge + session_edge + atr_edge + ctx_edge
            + regime_edge
        )

        # ═══ Soft multipliers ═══
        # HTF alignment: W1/D1/H4 agreement [0.0–1.0]
        # Premium/Discount: price location vs equilibrium [0.0–1.0]
        # Formula: factor ∈ [0.5, 1.0] — context influences but never kills
        # None = unknown → no adjustment (mult = 1.0)
        winrate_mult = 1.0
        if f.htf_alignment_score is not None:
            winrate_mult *= 0.5 + 0.5 * f.htf_alignment_score
        if f.premium_discount_score is not None:
            winrate_mult *= 0.5 + 0.5 * f.premium_discount_score

        # HTF bias penalty (reversal mismatch → 0.8x)
        winrate_mult *= f.htf_bias_penalty

        # OB mitigation factor
        # 0.0 = broken OB → signal rejected
        if f.ob_state_multiplier <= 0.0:
            return TradeProbability(
                p_tp=0.0,
                expected_rr=0.0,
                profit_factor=0.0,
                confidence=0.0,
                model_type="rules",
            )
        winrate_mult *= f.ob_state_multiplier

        # ═══ Elliott Wave (soft feature) ═══
        if f.wave_confidence >= config.wave.min_confidence and not f.wave_conflict:
            wave_edge = f.wave_confidence * config.wave.weight
            winrate += wave_edge
        elif f.wave_conflict:
            winrate *= config.wave.conflict_penalty

        winrate = winrate * winrate_mult
        winrate = max(20.0, min(85.0, winrate))  # clamp

        # Expected RR
        expected_rr = f.rr_ratio * (winrate / 100.0) * 1.1

        # Profit factor
        p = winrate / 100.0
        q = 1 - p
        profit_factor = (p * expected_rr) / max(q * 1.0, 0.01)

        return TradeProbability(
            p_tp=round(winrate / 100.0, 4),
            expected_rr=round(expected_rr, 2),
            profit_factor=round(profit_factor, 2),
            confidence=0.4,  # low confidence — rules-based
            model_type="rules",
        )

    def _predict_ml(self, f: SetupFeatures) -> TradeProbability:
        """ML-based prediction from trained model.

        Legacy mode: classifier → P(TP), regressor → expected RR
        Expected return mode: regressor → expected return, isotonic → P(TP)
        """
        # OB mitigation hard gate (applied before ML)
        if f.ob_state_multiplier <= 0.0:
            return TradeProbability(
                p_tp=0.0,
                expected_rr=0.0,
                profit_factor=0.0,
                confidence=0.0,
                model_type="rejected_ob_mitigated",
            )

        try:
            import pandas as pd
            vector = f.to_vector()
            X = pd.DataFrame([vector])

            # Ensure column order matches training
            if self.feature_names:
                X = X.reindex(columns=self.feature_names, fill_value=0)

            if getattr(self, "model_type", "legacy") == "expected_return":
                # Expected return mode: regressor predicts expected return
                raw_return = float(self.model.predict(X)[0])

                # Convert to P(TP) via isotonic calibration
                if self.isotonic is not None:
                    # Isotonic expects a probability-like input; use sigmoid
                    proba_input = 1.0 / (1.0 + np.exp(-raw_return))
                    p_tp = float(self.isotonic.predict([proba_input])[0])
                else:
                    # Fallback: sigmoid normalization
                    p_tp = 1.0 / (1.0 + np.exp(-raw_return))

                # Clamp
                p_tp = max(0.05, min(0.85, p_tp))

                # Expected RR from features (structural TP/SL already baked in)
                expected_rr = f.rr_ratio if f.rr_ratio > 0 else 1.0

                # Apply HTF bias penalty and OB mitigation
                multiplier = f.htf_bias_penalty * f.ob_state_multiplier
                p_tp = min(0.85, p_tp * multiplier)

                model_type = f"expected_return({self.model.__class__.__name__})"
            else:
                # Legacy mode: classifier for P(TP)
                p_tp = float(self.model.predict_proba(X)[0][1])

                # Apply HTF bias penalty and OB mitigation
                multiplier = f.htf_bias_penalty * f.ob_state_multiplier
                p_tp = min(0.85, p_tp * multiplier)

                # Regressor: expected RR
                expected_rr = f.rr_ratio
                if self.rr_model is not None:
                    expected_rr = float(self.rr_model.predict(X)[0])
                    expected_rr = max(0.1, min(expected_rr, 10.0))

                model_type = self.model.__class__.__name__

            # Profit factor
            q = 1 - p_tp
            profit_factor = (p_tp * expected_rr) / max(q * 1.0, 0.01)

            # Feature importance
            importances = None
            if hasattr(self.model, "feature_importances_") and self.feature_names:
                importances = dict(zip(
                    self.feature_names,
                    self.model.feature_importances_,
                ))

            return TradeProbability(
                p_tp=round(p_tp, 4),
                expected_rr=round(expected_rr, 2),
                profit_factor=round(profit_factor, 2),
                confidence=0.80,
                model_type=model_type,
                feature_importance=importances,
            )
        except Exception as e:
            logger.warning(f"ML prediction failed, falling back to rules: {e}")
            return self._predict_rules(f)

    def get_top_features(self, n: int = 10) -> List[tuple]:
        """Return top N most important features from ML model."""
        if not self.model or not self.feature_names:
            return []
        if not hasattr(self.model, "feature_importances_"):
            return []
        pairs = list(zip(self.feature_names, self.model.feature_importances_))
        pairs.sort(key=lambda x: x[1], reverse=True)
        return pairs[:n]

    # ──────────────────────────────────────────────────────
    # Scenario-based estimation (new pipeline)
    # ──────────────────────────────────────────────────────

    def estimate_scenario(
        self,
        scenario: MarketScenario,
        features: SetupFeatures,
        graph=None,       # LiquidityGraph
        phase=None,       # PhaseAssessment
    ) -> ScenarioEvaluation:
        """Estimate P(scenario) — probability that this scenario materializes.

        Does NOT know about SymbolWeights — that's WeightManager's job.
        Returns a ScenarioEvaluation with probability, confidence, etc.
        """
        eval_ = ScenarioEvaluation(
            scenario_id=scenario.id,
            evaluated_at_bar=scenario.created_at_bar,
        )

        # ── 1. Component scores ──
        component_scores = {}
        for comp in scenario.components:
            score = self._score_component_for_scenario(comp, features)
            component_scores[comp.id] = score
        eval_.component_scores = component_scores

        # ── 2. Base probability from features (reuse existing rules logic) ──
        tp = self.predict(features)
        base_p = tp.p_tp

        # ── 3. Scenario-specific adjustments ──
        # More components = higher confidence in the scenario
        if scenario.components_count >= 4:
            base_p *= 1.10
        elif scenario.components_count >= 3:
            base_p *= 1.05

        # Critical components all confirmed = boost (never reduce)
        if scenario.critical_components > 0:
            critical_score = sum(
                component_scores.get(c.id, 0)
                for c in scenario.components
                if c.is_critical
            ) / scenario.critical_components
            blended = base_p * 0.7 + critical_score * 0.3
            base_p = max(base_p, blended)

        # ── 4. Phase modifier ──
        if phase:
            modifier = get_phase_modifier(phase.phase, scenario.name)
            base_p *= modifier

        # ── 5. R:R quality — REMOVED (A3): feedback loop ──

        # ── 6. Clamp ──
        eval_.probability = max(0.10, min(0.85, base_p))
        eval_.expected_rr = scenario.rr_ratio
        eval_.profit_factor = tp.profit_factor
        eval_.confidence = tp.confidence
        eval_.model_type = tp.model_type

        return eval_

    def _score_component_for_scenario(self, comp, features: SetupFeatures) -> float:
        """Score a single scenario component against available features."""
        score = 0.5  # base

        if comp.type == "bos" and features.has_bos:
            score = 0.8
        elif comp.type == "sweep" and features.has_sweep:
            score = 0.75
        elif comp.type == "ob" and features.has_ob:
            score = 0.7
            # Bonus if OB is close to price
            if features.ob_distance_pct < 1.0:
                score = 0.85
        elif comp.type == "fvg" and features.has_fvg:
            score = 0.65
        elif comp.type == "displacement" and features.has_displacement:
            score = 0.7
        elif comp.type in ("choch",):
            # CHoCH is structural — check if structure trend aligns
            if features.structure_bos_aligned:
                score = 0.7
        elif comp.type in ("equal_high", "equal_low", "old_high", "old_low"):
            # Liquidity levels — always present as targets
            score = 0.6

        return score

    def rank_scenarios(
        self,
        scenarios: list[MarketScenario],
        features: SetupFeatures,
        graph=None,
        phase=None,
    ) -> list[tuple[MarketScenario, ScenarioEvaluation]]:
        """Evaluate and rank scenarios by probability.

        Returns list of (scenario, evaluation) sorted by probability desc.
        """
        scored = []
        for s in scenarios:
            eval_ = self.estimate_scenario(s, features, graph, phase)
            scored.append((s, eval_))

        scored.sort(key=lambda x: x[1].probability, reverse=True)
        return scored


# Singleton
probability_engine = ProbabilityEngine()
