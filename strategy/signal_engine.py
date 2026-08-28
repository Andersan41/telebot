"""
strategy/signal_engine.py — Data types + SL/TP calculation.

ICT Core: all indicator-based gates removed.
Pattern Engine (pattern_engine.py) is the sole source of trading signals.
"""
import math
import html
import re
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
    tp_source: str = ""  # external_liquidity | opposing_ob | active_fvg | swing | atr
    _swing_highs_1h: List[float] = field(default_factory=list)
    _swing_lows_1h: List[float] = field(default_factory=list)
    _rejection_reason: Optional[str] = None

    # Phase 2 — HTF Bias V2 + Premium/Discount
    _htf_result: Optional[Any] = None  # HTFBiasResult
    _zone_type: Optional[str] = None   # "premium" / "discount" / "equilibrium"
    _fib_level: Optional[float] = None
    _zone_quality_multiplier: float = 1.0

    # Elliott Wave (soft feature)
    _wave_confidence: float = 0.0
    _wave_label: str = ""
    _wave_conflict: bool = False
    _wave_conflict_details: str = ""  # detailed conflict explanation
    _wave_alt_label: str = ""  # alternative count label for conflict explanation
    _wave_direction: str = ""  # "bullish" / "bearish" / ""
    _wave_target: float = 0.0  # expected price target from wave analysis
    _wave_current: str = ""    # current wave label(s), e.g. "3" or "A-B"

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
        return round(min(confidence, 1.0) * 100, 1)

    def format_message(self) -> str:
        if self.signal == SignalType.BUY:
            signal_word = "ПОКУПКА"
        elif self.signal == SignalType.SELL:
            signal_word = "ПРОДАЖА"
        else:
            signal_word = ""
        header = f"{self.signal.value} — {signal_word}" if signal_word else self.signal.value
        emoji = "\U0001f7e2" if self.signal == SignalType.BUY else "\U0001f534" if self.signal == SignalType.SELL else "\u26aa"
        lines = [
            f"{emoji} {header} — {self.symbol}",
        ]

        # HTF Context (Phase 2)
        if self._htf_result is not None:
            hr = self._htf_result
            strength_label = hr.strength.value.upper() if hasattr(hr.strength, 'value') else str(hr.strength)
            tf_checks = []
            if hr.weekly_bias != 'neutral':
                tf_checks.append(f"W1{'\u2713' if hr.weekly_bias == hr.direction else '\u2717'}")
            if hr.daily_bias != 'neutral':
                tf_checks.append(f"D1{'\u2713' if hr.daily_bias == hr.direction else '\u2717'}")
            if hr.h4_bias != 'neutral':
                tf_checks.append(f"H4{'\u2713' if hr.h4_bias == hr.direction else '\u2717'}")
            tf_str = " ".join(tf_checks) if tf_checks else "neutral"
            lines.append(f"HTF Context: {strength_label} {hr.direction.upper()} ({tf_str})")

        # Zone info (Phase 2)
        if self._zone_type is not None:
            zone_upper = self._zone_type.upper()
            fib_str = f" (fib {self._fib_level:.2f})" if self._fib_level is not None else ""
            lines.append(f"Zone: {zone_upper}{fib_str}")

        lines.append(f"Таймфрейм: {self.timeframe.upper()}")

        entry = self.entry_price if self.entry_price is not None else self.close
        lines.append(f"Entry: <code>{_fmt_price(entry)}</code>")

        if self.sl is not None:
            sl_pct = (self.sl - entry) / entry * 100 if entry else 0
            lines.append(f"SL: <code>{_fmt_price(self.sl)}</code> ({sl_pct:+.2f}%)")
        if self.tp is not None:
            tp_pct = (self.tp - entry) / entry * 100 if entry else 0
            lines.append(f"TP: <code>{_fmt_price(self.tp)}</code> ({tp_pct:+.2f}%)")
        if self.sl is not None and self.tp is not None and entry:
            rr = abs(self.tp - entry) / abs(entry - self.sl) if entry != self.sl else 0
            lines.append(f"RR: 1:{rr:.1f}")

        # Zone quality multiplier
        if self._zone_quality_multiplier != 1.0:
            lines.append(f"Zone Quality: {self._zone_quality_multiplier:.1f}x ({self._zone_type or 'neutral'} entry)")

        if self._confidence_v2 is not None:
            quality_map = {"strong": "высокая", "moderate": "средняя", "weak": "низкая"}
            q = quality_map.get(self._confidence_v2.quality, self._confidence_v2.quality)
            lines.append(f"Confidence: {self.confidence:.0f}/100")
        else:
            lines.append(f"Confidence: {self.confidence:.0f}/100")
        # Elliott Wave
        if self._wave_confidence >= 0.4:
            direction_icon = "🟢" if self._wave_direction == "bullish" else "🔴" if self._wave_direction == "bearish" else "⚪"
            direction_text = "бычий" if self._wave_direction == "bullish" else "медвежий" if self._wave_direction == "bearish" else "неопределён"
            highlighted_label = _highlight_wave(self._wave_label, self._wave_current)
            wave_line = f"🌊 Волна: {highlighted_label} {direction_icon} {direction_text} ({self._wave_confidence:.0%})"
            if self._wave_target > 0:
                wave_line += f" → целевая {_fmt_price(self._wave_target)}"
            if self._wave_conflict:
                details = self._wave_conflict_details or "Разные варианты указывают разное направление"
                wave_line += f"\n⚠️ конфликт: {details}"
            lines.append(wave_line)
        return "\n".join(lines)


def _fmt_price(value) -> str:
    """Format price: strip trailing zeros (1.350000 → 1.35, 0.0001130 → 0.000113)."""
    if value is None:
        return ""
    s = f"{value:.10f}".rstrip("0").rstrip(".")
    return s


def _highlight_wave(label: str, current: str) -> str:
    """Highlight current wave in label with bold HTML.
    E.g. label='impulse (1-2-3-4-5)', current='3' → 'impulse (1-2-<b>3</b>-4-5)'
    """
    if not current or "(" not in label:
        return html.escape(label)
    m = re.search(r'\(([^)]+)\)', label)
    if not m:
        return html.escape(label)
    prefix = label[:m.start()]
    waves_str = m.group(1)
    suffix = label[m.end():]
    waves = waves_str.split("-")
    # Build highlighted version
    highlighted = []
    cur_set = set(current.split("-"))
    for w in waves:
        if w in cur_set:
            highlighted.append(f"<b>{html.escape(w)}</b>")
        else:
            highlighted.append(html.escape(w))
    return html.escape(prefix) + "(" + "-".join(highlighted) + ")" + html.escape(suffix)


def _calculate_sl_tp(
    ind: IndicatorValues,
    signal: SignalType,
    structure: Any = None,
    entry: Optional[float] = None,
    timeframe: Optional[str] = None,
    order_blocks: Optional[list] = None,
    sweeps: Optional[list] = None,
    fvgs: Optional[list] = None,
    df: Any = None,
) -> tuple[float, float, Literal["ob", "fractal", "bos", "atr"]]:
    """Calculate SL/TP using ICT priority chain: OB > Fractal > BOS > ATR.

    SL Priority:
        1. Order Block zone (OB.low for BUY, OB.high for SELL + buffer)
        2. Fractal/Swing Point (swing_low for BUY, swing_high for SELL + buffer)
        3. BOS level (bos.level * 0.995/1.005)
        4. ATR fallback (entry ± ATR * multiplier)

    TP Priority:
        1. Opposing Order Block (nearest bearish OB for BUY, bullish for SELL)
        2. Active FVG (bearish FVG.bottom for BUY, bullish FVG.top for SELL)
        3. Swing structure (nearest swing_high for BUY, swing_low for SELL)
        4. ATR fallback (entry ± ATR * multiplier)
    """
    cfg = config.trading
    atr = ind.atr if ind.atr and ind.atr > 0 else ind.close * cfg.atr_fallback_pct / 100
    ep = entry if entry is not None else ind.close
    buffer_pct = cfg.stop_hunt_buffer_pct / 100  # convert % to decimal
    max_ob_dist = cfg.max_ob_distance_pct / 100

    # Per-TF ATR multiplier overrides
    atr_sl = cfg.atr_multiplier_sl
    atr_tp = cfg.atr_multiplier_tp
    if timeframe and cfg.atr_multipliers_per_tf:
        tf_override = cfg.atr_multipliers_per_tf.get(timeframe, {})
        if "sl" in tf_override:
            atr_sl = float(tf_override["sl"])
        if "tp" in tf_override:
            atr_tp = float(tf_override["tp"])

    # ═══ SL Priority Chain ═══

    sl = None
    sl_source = "atr"

    # 1. Order Block — SL behind the OB zone
    if order_blocks and signal == SignalType.BUY:
        # For BUY: find nearest bullish OB below entry
        candidates = [
            ob for ob in order_blocks
            if ob.type == "bullish" and ob.low < ep
            and (ep - ob.low) / ep <= max_ob_dist
        ]
        if candidates:
            # Pick the one closest to entry (highest low)
            best_ob = max(candidates, key=lambda ob: ob.low)
            sl = round(best_ob.low * (1 - buffer_pct), 8)
            sl_source = "ob"
    elif order_blocks and signal == SignalType.SELL:
        # For SELL: find nearest bearish OB above entry
        candidates = [
            ob for ob in order_blocks
            if ob.type == "bearish" and ob.high > ep
            and (ob.high - ep) / ep <= max_ob_dist
        ]
        if candidates:
            best_ob = min(candidates, key=lambda ob: ob.high)
            sl = round(best_ob.high * (1 + buffer_pct), 8)
            sl_source = "ob"

    # 2. Fractal / Swing Point — SL behind the最近的 fractal
    if sl is None and structure:
        swing_lows = getattr(structure, "recent_lows", []) or []
        swing_highs = getattr(structure, "recent_highs", []) or []

        if signal == SignalType.BUY and swing_lows:
            # Find nearest swing low below entry
            valid_lows = [p for p in swing_lows if p < ep]
            if valid_lows:
                best_low = max(valid_lows)  # closest to entry
                sl = round(best_low * (1 - buffer_pct), 8)
                sl_source = "fractal"
        elif signal == SignalType.SELL and swing_highs:
            # Find nearest swing high above entry
            valid_highs = [p for p in swing_highs if p > ep]
            if valid_highs:
                best_high = min(valid_highs)  # closest to entry
                sl = round(best_high * (1 + buffer_pct), 8)
                sl_source = "fractal"

    # 3. BOS level — SL behind the BOS
    if sl is None and structure and structure.last_bos:
        bos = structure.last_bos
        if signal == SignalType.BUY and bos.type == "bullish":
            candidate_sl = round(bos.level * (1 - buffer_pct), 8)
            if candidate_sl < ep:
                sl = candidate_sl
                sl_source = "bos"
        elif signal == SignalType.SELL and bos.type == "bearish":
            candidate_sl = round(bos.level * (1 + buffer_pct), 8)
            if candidate_sl > ep:
                sl = candidate_sl
                sl_source = "bos"

    # 4. ATR fallback
    if sl is None:
        if signal == SignalType.BUY:
            sl = round(ep - atr * atr_sl, 8)
        else:
            sl = round(ep + atr * atr_sl, 8)
        sl_source = "atr"

    # ═══ TP Priority Chain ═══

    tp = None
    tp_source = "atr"
    min_tp_distance = atr * 1.5  # Minimum TP distance = 1.5 ATR

    # 1. External Liquidity (EQH/EQL)
    sl_dist = abs(ep - sl) if sl else atr * atr_sl
    if signal == SignalType.BUY:
        from liquidity.external import find_external_liquidity
        ext_tp = find_external_liquidity(df, 'long', ep, sl_dist) if df is not None else None
        if ext_tp is not None:
            tp = round(ext_tp, 8)
            tp_source = "external_liquidity"
    elif signal == SignalType.SELL:
        from liquidity.external import find_external_liquidity
        ext_tp = find_external_liquidity(df, 'short', ep, sl_dist) if df is not None else None
        if ext_tp is not None:
            tp = round(ext_tp, 8)
            tp_source = "external_liquidity"

    # 2. Opposing Order Block — TP at the OB zone
    if tp is None and order_blocks and signal == SignalType.BUY:
        targets = [
            ob for ob in order_blocks
            if ob.type == "bearish" and ob.high > ep + min_tp_distance
        ]
        if targets:
            best_target = min(targets, key=lambda ob: ob.high)
            tp = round(best_target.midpoint, 8)
            tp_source = "ob"
    elif tp is None and order_blocks and signal == SignalType.SELL:
        targets = [
            ob for ob in order_blocks
            if ob.type == "bullish" and ob.low < ep - min_tp_distance
        ]
        if targets:
            best_target = max(targets, key=lambda ob: ob.low)
            tp = round(best_target.midpoint, 8)
            tp_source = "ob"

    # 3. Active FVG — TP at the FVG boundary
    if tp is None and fvgs:
        if signal == SignalType.BUY:
            fvg_targets = [
                fvg for fvg in fvgs
                if fvg.type == "bearish" and not fvg.filled and fvg.bottom > ep + min_tp_distance
            ]
            if fvg_targets:
                best_fvg = min(fvg_targets, key=lambda f: f.bottom)
                tp = round(best_fvg.bottom, 8)
                tp_source = "fvg"
        elif signal == SignalType.SELL:
            fvg_targets = [
                fvg for fvg in fvgs
                if fvg.type == "bullish" and not fvg.filled and fvg.top < ep - min_tp_distance
            ]
            if fvg_targets:
                best_fvg = max(fvg_targets, key=lambda f: f.top)
                tp = round(best_fvg.top, 8)
                tp_source = "fvg"

    # 4. Swing structure — TP at the opposing swing point
    if tp is None and structure:
        swing_highs = getattr(structure, "recent_highs", []) or []
        swing_lows = getattr(structure, "recent_lows", []) or []

        if signal == SignalType.BUY and swing_highs:
            valid_highs = [p for p in swing_highs if p > ep + min_tp_distance]
            if valid_highs:
                tp = round(min(valid_highs), 8)
                tp_source = "fractal"
        elif signal == SignalType.SELL and swing_lows:
            valid_lows = [p for p in swing_lows if p < ep - min_tp_distance]
            if valid_lows:
                tp = round(max(valid_lows), 8)
                tp_source = "fractal"

    # 5. ATR fallback
    if tp is None:
        if signal == SignalType.BUY:
            tp = round(ep + atr * atr_tp, 8)
        else:
            tp = round(ep - atr * atr_tp, 8)
        tp_source = "atr"

    # ═══ Validation ═══

    # Ensure SL is on the correct side of entry
    if signal == SignalType.BUY and sl >= ep:
        sl = round(ep - atr * atr_sl, 8)
        sl_source = "atr"
    elif signal == SignalType.SELL and sl <= ep:
        sl = round(ep + atr * atr_sl, 8)
        sl_source = "atr"

    # Ensure TP is on the correct side of entry
    if signal == SignalType.BUY and tp <= ep:
        tp = round(ep + atr * atr_tp, 8)
        tp_source = "atr"
    elif signal == SignalType.SELL and tp >= ep:
        tp = round(ep - atr * atr_tp, 8)
        tp_source = "atr"

    return sl, tp, sl_source


# Backward-compatible singleton (used by legacy callers and backtests)
signal_engine = None
