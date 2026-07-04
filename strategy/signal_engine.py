"""
strategy/signal_engine.py — Data types + SL/TP calculation.

ICT Core: all indicator-based gates removed.
Pattern Engine (pattern_engine.py) is the sole source of trading signals.
"""
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Literal, Optional, Dict, Any

from loguru import logger

from config.settings import config
from indicators.engine import IndicatorValues
from scoring.confidence_v2 import ConfidenceResult


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NO_SIGNAL = "NO_SIGNAL"


@dataclass
class SignalResult:
    signal: SignalType
    symbol: str
    timeframe: str
    close: float
    entry_price: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    reasons: List[str] = field(default_factory=list)
    score: int = 0
    sr_levels: Optional[Dict[str, Dict[str, List[float]]]] = None
    level_warnings: List[str] = field(default_factory=list)
    _context_score: Optional[float] = None
    _max_context_score: float = 1.0
    _confirmed_tf: Optional[str] = None
    _context_items: List[str] = field(default_factory=list)
    _structure_trend: Optional[str] = None
    _structure_bos: Optional[str] = None
    _tp_path_score: int = 0
    _tp_path_blocked: bool = False
    _distance_filter_blocked: bool = False
    _confidence_v2: Optional[ConfidenceResult] = None
    _ema_alignment_info: str = ""
    _rsi_strength: float = 0.0
    _factor_strengths: Dict[str, float] = field(default_factory=dict)
    _weighted_score: float = 0.0
    _has_trigger: bool = False
    _has_leading_trigger: bool = False
    _regime: Optional[str] = None
    _regime_blocked: bool = False
    _sl_source: Optional[Literal["bos", "atr"]] = None
    _swing_highs_1h: List[float] = field(default_factory=list)
    _swing_lows_1h: List[float] = field(default_factory=list)
    _rejection_reason: Optional[str] = None

    @property
    def is_actionable(self) -> bool:
        return self.signal != SignalType.NO_SIGNAL

    @property
    def score_verdict(self) -> str:
        """Quality label from component count (ICT setups)."""
        if self._regime_blocked:
            return "blocked"
        s = self.score
        if s >= 6:
            return "strong"
        elif s >= 4:
            return "moderate"
        else:
            return "weak"

    @property
    def score_verdict_display(self) -> str:
        return {
            "strong": "СИЛЬНЫЙ", "moderate": "УМЕРЕННЫЙ",
            "weak": "СЛАБЫЙ", "blocked": "ЗАБЛОКИРОВАН",
        }.get(self.score_verdict, "СЛАБЫЙ")

    @property
    def confidence_verdict(self) -> str:
        if self._regime_blocked:
            return "ЗАБЛОКИРОВАН"
        if self._confidence_v2 is not None:
            q = self._confidence_v2.quality
            return {"strong": "СИЛЬНЫЙ", "moderate": "УМЕРЕННЫЙ", "weak": "СЛАБЫЙ"}.get(q, "СЛАБЫЙ")
        return self.score_verdict_display

    @property
    def verdict(self) -> str:
        """Backward-compatible alias — used in DB and outcome_tracker."""
        return self.confidence_verdict

    @property
    def confidence(self) -> float:
        if self._confidence_v2 is not None:
            return self._confidence_v2.confidence_pct
        max_score = 7
        tech_pct = self.score / max_score
        if self._context_score is not None:
            market_pct = (self._context_score + 1.0) / 2.0
            blend = config.scoring.tech_confidence_blend
            confidence = (tech_pct * blend) + (market_pct * (1.0 - blend))
        else:
            confidence = tech_pct
        return round(confidence * 100, 1)

    def format_message(self) -> str:
        if self.signal == SignalType.BUY:
            signal_word = "ПОКУПКА"
        elif self.signal == SignalType.SELL:
            signal_word = "ПРОДАЖА"
        else:
            signal_word = ""
        header = f"{self.signal.value} — {signal_word}" if signal_word else self.signal.value
        lines = [
            header,
            f"Инструмент: {self.symbol}",
        ]

        lines.append(f"Таймфрейм: {self.timeframe.upper()}")

        entry = self.entry_price if self.entry_price is not None else self.close
        lines.append(f"Цена входа: <code>{entry}</code>")

        if self.sl is not None:
            sl_pct = (self.sl - entry) / entry * 100 if entry else 0
            lines.append(f"\U0001f534 Stop Loss: <code>{self.sl}</code> ({sl_pct:+.2f}%)")
        if self.tp is not None:
            tp_pct = (self.tp - entry) / entry * 100 if entry else 0
            lines.append(f"\U0001f7e2 Take Profit: <code>{self.tp}</code> ({tp_pct:+.2f}%)")
        if self.sl is not None and self.tp is not None and entry:
            rr = abs(self.tp - entry) / abs(entry - self.sl) if entry != self.sl else 0
            lines.append(f"R/R: 1:{rr:.1f}")

        lines.append(f"\nКомпоненты: {self.score}")

        if self._confidence_v2 is not None:
            quality_map = {"strong": "высокая", "moderate": "средняя", "weak": "низкая"}
            q = quality_map.get(self._confidence_v2.quality, self._confidence_v2.quality)
            lines.append(f"Качество: {q} | Уверенность: {self.confidence:.1f}%")
        else:
            lines.append(f"Уверенность: {self.confidence:.1f}%")
        return "\n".join(lines)


def _calculate_sl_tp(
    ind: IndicatorValues,
    signal: SignalType,
    structure: Any = None,
    entry: Optional[float] = None,
) -> tuple[float, float, Literal["bos", "atr"]]:
    """Calculate SL/TP using BOS level (structural) or ATR (fallback)."""
    cfg = config.trading
    atr = ind.atr if ind.atr and ind.atr > 0 else ind.close * cfg.atr_fallback_pct / 100
    ep = entry if entry is not None else ind.close

    if structure and structure.last_bos:
        bos = structure.last_bos
        if signal == SignalType.BUY and bos.type == "bullish":
            sl = round(bos.level * 0.995, 8)
            tp = round(ep + atr * cfg.atr_multiplier_tp, 8)
            if sl < ep:
                return sl, tp, "bos"
        if signal == SignalType.SELL and bos.type == "bearish":
            sl = round(bos.level * 1.005, 8)
            tp = round(ep - atr * cfg.atr_multiplier_tp, 8)
            if sl > ep:
                return sl, tp, "bos"

    if signal == SignalType.BUY:
        sl = round(ep - atr * cfg.atr_multiplier_sl, 8)
        tp = round(ep + atr * cfg.atr_multiplier_tp, 8)
    else:
        sl = round(ep + atr * cfg.atr_multiplier_sl, 8)
        tp = round(ep - atr * cfg.atr_multiplier_tp, 8)
    return sl, tp, "atr"


# Backward-compatible singleton (used by legacy callers and backtests)
signal_engine = None
