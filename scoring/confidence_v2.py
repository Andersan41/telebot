"""
scoring/confidence_v2.py — Confidence Engine V2 with weighted factor scoring.

Weight distribution (total 100):
  HTF Trend: 15, Structure: 25, Liquidity: 15, Volume: 10,
  BTC correlation: 10, Funding: 5, OI: 5, RSI: 5, MACD: 5, ADX: 5.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from config.settings import config


@dataclass
class FactorScore:
    name: str
    weight: int
    raw_score: float  # -1.0 to 1.0
    weighted_score: float  # raw * weight / 100

    @classmethod
    def make(cls, name: str, weight: int, raw: float) -> "FactorScore":
        return cls(name=name, weight=weight, raw_score=raw, weighted_score=raw * weight)


@dataclass
class ConfidenceResult:
    factors: list[FactorScore]
    total_score: float  # -100 to 100
    quality: Literal["strong", "moderate", "weak"]
    recommendation: Literal["BUY", "SELL", "NO_SIGNAL"]

    @property
    def confidence_pct(self) -> float:
        return abs(self.total_score)


# --- Weights — read from config at runtime (hot-reload safe) ---

def _get_conf_weights():
    """Return current confidence V2 weights from config."""
    s = config.scoring
    return {
        "htf_trend": s.w_htf_trend, "structure": s.w_structure,
        "liquidity": s.w_liquidity, "volume": s.w_conf_volume,
        "btc_corr": s.w_btc_corr, "funding": s.w_conf_funding,
        "oi": s.w_conf_oi, "rsi": s.w_conf_rsi,
        "macd": s.w_conf_macd, "adx": s.w_conf_adx,
    }


def _quality_label(total: float, strong_thr: float, moderate_thr: float) -> str:
    if abs(total) >= strong_thr:
        return "strong"
    elif abs(total) >= moderate_thr:
        return "moderate"
    return "weak"


class ConfidenceEngineV2:
    """Computes weighted confidence from individual factor scores.

    When historical_winrate is provided (Task 6.1), confidence is blended:
      confidence = historical_wr * 0.6 + score_confidence * 0.4
    This makes confidence reflect actual historical probability, not just
    the current factor score.
    """

    def compute(
        self,
        direction: Literal["BUY", "SELL", "NO_SIGNAL"],
        *,
        htf_trend_score: float = 0.0,
        structure_score: float = 0.0,
        liquidity_score: float = 0.0,
        volume_score: float = 0.0,
        btc_corr_score: float = 0.0,
        funding_score: float = 0.0,
        oi_score: float = 0.0,
        rsi_score: float = 0.0,
        macd_score: float = 0.0,
        adx_score: float = 0.0,
        historical_winrate: Optional[float] = None,
    ) -> ConfidenceResult:
        w = _get_conf_weights()
        factors: list[FactorScore] = [
            FactorScore.make("HTF Trend", w["htf_trend"], htf_trend_score),
            FactorScore.make("Structure", w["structure"], structure_score),
            FactorScore.make("Liquidity", w["liquidity"], liquidity_score),
            FactorScore.make("Volume", w["volume"], volume_score),
            FactorScore.make("BTC correlation", w["btc_corr"], btc_corr_score),
            FactorScore.make("Funding", w["funding"], funding_score),
            FactorScore.make("OI", w["oi"], oi_score),
            FactorScore.make("RSI", w["rsi"], rsi_score),
            FactorScore.make("MACD", w["macd"], macd_score),
            FactorScore.make("ADX", w["adx"], adx_score),
        ]

        total = sum(f.weighted_score for f in factors)
        # Clamp to [-100, 100]
        total = max(-100.0, min(100.0, total))

        strong_thr = config.scoring.confidence_strong_threshold
        moderate_thr = config.scoring.confidence_moderate_threshold

        # Task 6.1: blend historical winrate with score-based confidence
        score_confidence = abs(total)
        if historical_winrate is not None:
            # Blend: configurable historical WR, rest is current score
            blend_wr = config.scoring.historical_wr_blend
            blended = historical_winrate * blend_wr + score_confidence * (1.0 - blend_wr)
            total = blended if direction in ("BUY", "SELL") else total
            # Re-evaluate quality based on blended confidence
            quality = _quality_label(total, strong_thr, moderate_thr)
        else:
            quality = _quality_label(total, strong_thr, moderate_thr)

        return ConfidenceResult(
            factors=factors,
            total_score=round(total, 2),
            quality=quality,  # type: ignore[arg-type]
            recommendation=direction,
        )


# --- Helper: compute individual factor scores from raw data ---

def score_htf_trend(mtf_aligned: bool, mtf_count: int, required: int = 2) -> float:
    """Score HTF trend alignment.  mtf_aligned means >= required HTFs agree."""
    if mtf_aligned:
        return 0.8 + 0.2 * min(mtf_count - required, 1)
    return -0.5


def score_structure(trend: Optional[str], bos: Optional[str], direction: str) -> float:
    """Score market structure (trend + BOS)."""
    if trend is None:
        return 0.0
    bullish = trend == "bullish"
    bearish = trend == "bearish"
    bos_bull = bos == "bullish"
    bos_bear = bos == "bearish"

    if direction == "BUY":
        if bullish and bos_bull:
            return 1.0
        elif bullish:
            return 0.6
        elif bearish and bos_bear:
            return -0.8
        elif bearish:
            return -0.4
        return 0.0
    else:  # SELL
        if bearish and bos_bear:
            return 1.0
        elif bearish:
            return 0.6
        elif bullish and bos_bull:
            return -0.8
        elif bullish:
            return -0.4
        return 0.0


def score_liquidity(
    bullish_sweeps: int = 0,
    bearish_sweeps: int = 0,
    has_bullish_ob: bool = False,
    has_bearish_ob: bool = False,
    has_bullish_fvg: bool = False,
    has_bearish_fvg: bool = False,
) -> float:
    """Score liquidity context.  Positive = bullish, negative = bearish."""
    score = 0.0
    # Sweeps: bullish sweep supports LONG, bearish sweep supports SHORT
    score += 0.3 * min(bullish_sweeps, 2)
    score -= 0.3 * min(bearish_sweeps, 2)
    # Order blocks
    if has_bullish_ob:
        score += 0.2
    if has_bearish_ob:
        score -= 0.2
    # FVGs
    if has_bullish_fvg:
        score += 0.15
    if has_bearish_fvg:
        score -= 0.15
    return max(-1.0, min(1.0, score))


def score_volume(volume_above: bool, volume_ratio: float = 1.0) -> float:
    """Score volume.  Above-average volume gives positive score."""
    if not volume_above:
        return -0.3
    return min(0.8, 0.3 + 0.5 * (volume_ratio - 1.0))


def score_btc_correlation(allows: bool, strong: bool = False) -> float:
    """Score BTC correlation gate."""
    if allows and strong:
        return 0.8
    elif allows:
        return 0.4
    return -0.8


def score_funding_from_state(state: str, strength: str, direction: str) -> float:
    """Score funding using classified state/strength."""
    if state == "neutral" or strength == "weak":
        return 0.0
    supports = (direction == "BUY" and state == "bullish") or \
               (direction == "SELL" and state == "bearish")
    return 0.8 if (supports and strength == "strong") else \
           0.4 if supports else \
           -0.8 if (not supports and strength == "strong") else -0.4


def score_oi_from_state(pattern: str, significance: str, direction: str) -> float:
    """Score OI using classified pattern/significance."""
    if significance == "ignore":
        return 0.0
    bull_patterns = {"bullish_cont", "short_squeeze"}
    bear_patterns = {"long_squeeze"}
    if direction == "BUY":
        if pattern in bull_patterns:
            return 0.8 if significance == "strong" else 0.4
        elif pattern in bear_patterns:
            return -0.8 if significance == "strong" else -0.4
    else:  # SELL
        if pattern in bear_patterns:
            return 0.8 if significance == "strong" else 0.4
        elif pattern in bull_patterns:
            return -0.8 if significance == "strong" else -0.4
    return 0.0


def score_rsi(rsi: float, direction: str, overbought: float = 70, oversold: float = 30,
              bull_min: float = 50, bear_max: float = 50) -> float:
    """Score RSI.  Normalised from current value relative to direction."""
    if direction == "BUY":
        if rsi >= overbought:
            return -0.8  # overbought — bad for LONG
        elif rsi >= bull_min:
            return 0.5 + 0.3 * (1 - (rsi - bull_min) / (overbought - bull_min))
        elif rsi > oversold:
            return 0.0
        else:
            return 0.6  # oversold bounce potential
    else:  # SELL
        if rsi <= oversold:
            return -0.8  # oversold — bad for SHORT
        elif rsi <= bear_max:
            return 0.5 + 0.3 * (1 - (bear_max - rsi) / (bear_max - oversold))
        elif rsi < overbought:
            return 0.0
        else:
            return 0.6  # overbought reversal potential


def score_macd(macd_hist: float, price: float, direction: str) -> float:
    """Score MACD histogram normalised by price.

    Uses MIN_MACD_PCT threshold from config to filter out noise.
    Values below the threshold return 0.0 (neutral).
    """
    from config.settings import config

    if price <= 0:
        return 0.0
    norm = abs(macd_hist / price) * 100  # percentage
    if norm < config.trading.min_macd_pct:
        return 0.0  # noise — neutral
    if direction == "BUY":
        return max(-1.0, min(1.0, (macd_hist / price * 100) * 10))
    else:
        return max(-1.0, min(1.0, -(macd_hist / price * 100) * 10))


def score_adx(adx: float, dmi_plus: float, dmi_minus: float, direction: str,
              adx_min: float = 20) -> float:
    """Score ADX + DMI.  ADX measures trend strength, DMI direction."""
    if adx < adx_min:
        return -0.5  # flat market
    strength = min(1.0, (adx - adx_min) / 30.0)  # 20→0, 50→1
    if direction == "BUY":
        dmi_dir = (dmi_plus - dmi_minus) / 50.0
        return strength * max(0.0, dmi_dir) * 2
    else:
        dmi_dir = (dmi_minus - dmi_plus) / 50.0
        return strength * max(0.0, dmi_dir) * 2


# Singleton
confidence_engine_v2 = ConfidenceEngineV2()
