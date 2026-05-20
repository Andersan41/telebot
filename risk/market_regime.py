"""
risk/market_regime.py — Market regime detection

Regimes:
- Trend: ADX > REGIME_TREND_ADX AND EMA spread rising
- Range: ADX < REGIME_RANGE_ADX
- Compression: ATR percentile < REGIME_COMPRESSION_ATR_PCT
- Expansion: ATR rising + volume rising
- Reversal: Sweep + divergence (future)

Uses historical ATR values to compute percentile ranking and EMA spread trends
to determine the current market regime.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional

from config.settings import config


@dataclass
class MarketRegime:
    regime: Literal["trend", "range", "compression", "expansion", "reversal"]
    confidence: float  # 0-1
    adx: float
    atr_percentile: float
    ema_spread_trend: Literal["rising", "falling", "stable"]


class RegimeDetector:
    """Detects market regime from indicator values and historical data.

    Args:
        adx: current ADX value
        atr_history: list of recent ATR values (oldest first), used for percentile
        ema_spread_history: list of recent EMA spread values (oldest first)
        volume_history: list of recent volume values (oldest first)
        current_atr: current ATR value
        current_volume: current volume value
    """

    def __init__(
        self,
        adx: float,
        atr_history: List[float],
        ema_spread_history: List[float],
        volume_history: Optional[List[float]] = None,
        current_atr: Optional[float] = None,
        current_volume: Optional[float] = None,
    ):
        self.adx = adx
        self.atr_history = atr_history
        self.ema_spread_history = ema_spread_history
        self.volume_history = volume_history or []
        self.current_atr = current_atr
        self.current_volume = current_volume

    def detect(self) -> MarketRegime:
        """Detect the current market regime.

        Priority order (first match wins):
        1. Compression — ATR percentile < threshold
        2. Range — ADX < threshold
        3. Expansion — ATR rising + volume rising
        4. Trend — ADX > threshold AND EMA spread rising
        5. Default: range (fallback)
        """
        atr_pct = self._atr_percentile()
        ema_spread_trend = self._ema_spread_trend()
        adx = self.adx

        regime_cfg = config.risk

        # Compression: ATR percentile < threshold
        if atr_pct < regime_cfg.regime_compression_atr_pct:
            confidence = self._compression_confidence(atr_pct)
            return MarketRegime(
                regime="compression",
                confidence=confidence,
                adx=adx,
                atr_percentile=atr_pct,
                ema_spread_trend=ema_spread_trend,
            )

        # Range: ADX < threshold
        if adx < regime_cfg.regime_range_adx:
            confidence = self._range_confidence(adx)
            return MarketRegime(
                regime="range",
                confidence=confidence,
                adx=adx,
                atr_percentile=atr_pct,
                ema_spread_trend=ema_spread_trend,
            )

        # Expansion: ATR rising + volume rising
        if self._is_expansion():
            confidence = self._expansion_confidence()
            return MarketRegime(
                regime="expansion",
                confidence=confidence,
                adx=adx,
                atr_percentile=atr_pct,
                ema_spread_trend=ema_spread_trend,
            )

        # Trend: ADX > threshold AND EMA spread rising
        if adx >= regime_cfg.regime_trend_adx and ema_spread_trend == "rising":
            confidence = self._trend_confidence(adx, ema_spread_trend)
            return MarketRegime(
                regime="trend",
                confidence=confidence,
                adx=adx,
                atr_percentile=atr_pct,
                ema_spread_trend=ema_spread_trend,
            )

        # Fallback: range
        return MarketRegime(
            regime="range",
            confidence=config.risk.regime_fallback_confidence,
            adx=adx,
            atr_percentile=atr_pct,
            ema_spread_trend=ema_spread_trend,
        )

    def _atr_percentile(self) -> float:
        """Compute ATR percentile rank within the lookback window."""
        if not self.atr_history or self.current_atr is None:
            return 50.0

        values = sorted(self.atr_history)
        n = len(values)
        rank = 0
        for v in values:
            if v <= self.current_atr:
                rank += 1
        return (rank / n) * 100.0

    def _ema_spread_trend(self) -> Literal["rising", "falling", "stable"]:
        """Determine if EMA spread is rising, falling, or stable."""
        if len(self.ema_spread_history) < 2:
            return "stable"

        window = config.risk.regime_ema_spread_window
        recent = self.ema_spread_history[-window:]
        if len(recent) < 2:
            return "stable"

        first_half = recent[: len(recent) // 2]
        second_half = recent[len(recent) // 2 :]

        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)

        if avg_first == 0:
            return "stable"

        change_pct = (avg_second - avg_first) / avg_first
        threshold = config.risk.regime_ema_spread_change_pct

        if change_pct > threshold:
            return "rising"
        elif change_pct < -threshold:
            return "falling"
        return "stable"

    def _is_expansion(self) -> bool:
        """Check if ATR and volume are both rising."""
        atr_rising = self._atr_rising()
        volume_rising = self._volume_rising()
        return atr_rising and volume_rising

    def _atr_rising(self) -> bool:
        """Check if current ATR is above the recent average."""
        if not self.atr_history or self.current_atr is None:
            return False
        window = config.risk.regime_rising_window
        mult = config.risk.regime_rising_multiplier
        recent_avg = sum(self.atr_history[-window:]) / min(len(self.atr_history), window)
        return self.current_atr > recent_avg * mult

    def _volume_rising(self) -> bool:
        """Check if current volume is above the recent average."""
        if not self.volume_history or self.current_volume is None:
            return False
        window = config.risk.regime_rising_window
        mult = config.risk.regime_rising_multiplier
        recent_avg = sum(self.volume_history[-window:]) / min(len(self.volume_history), window)
        return self.current_volume > recent_avg * mult

    def _compression_confidence(self, atr_pct: float) -> float:
        """Confidence for compression regime — higher when ATR percentile is lower."""
        threshold = config.risk.regime_compression_atr_pct
        if threshold <= 0:
            return 0.5
        return max(0.0, min(1.0, 1.0 - (atr_pct / threshold)))

    def _range_confidence(self, adx: float) -> float:
        """Confidence for range regime — higher when ADX is lower."""
        threshold = config.risk.regime_range_adx
        if threshold <= 0:
            return 0.5
        return max(0.0, min(1.0, 1.0 - (adx / threshold)))

    def _expansion_confidence(self) -> float:
        """Confidence for expansion regime — based on ATR and volume strength."""
        window = config.risk.regime_rising_window
        atr_score = 0.5
        vol_score = 0.5

        if self.atr_history and self.current_atr is not None:
            recent_avg = sum(self.atr_history[-window:]) / min(len(self.atr_history), window)
            if recent_avg > 0:
                atr_score = min(1.0, self.current_atr / recent_avg)

        if self.volume_history and self.current_volume is not None:
            recent_avg = sum(self.volume_history[-window:]) / min(len(self.volume_history), window)
            if recent_avg > 0:
                vol_score = min(1.0, self.current_volume / recent_avg)

        return (atr_score + vol_score) / 2.0

    def _trend_confidence(self, adx: float, ema_trend: str) -> float:
        """Confidence for trend regime — based on ADX strength and EMA trend."""
        adx_score = min(1.0, (adx - config.risk.regime_trend_adx) / 30.0)
        ema_score = 1.0 if ema_trend == "rising" else 0.5
        return (adx_score + ema_score) / 2.0
