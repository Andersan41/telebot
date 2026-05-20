"""
strategy/signal_engine.py — Логика принятия решения BUY / SELL / NO_SIGNAL (Update 5)

Weighted factor model with trigger → confirmation → verdict pipeline.
"""
import html
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any

from loguru import logger

from config.settings import config
from indicators.engine import IndicatorValues
from scoring.confidence_v2 import ConfidenceResult, FactorScore


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

    @property
    def is_actionable(self) -> bool:
        return self.signal != SignalType.NO_SIGNAL

    @property
    def verdict(self) -> str:
        if self._regime_blocked:
            return "BLOCKED"
        if self._confidence_v2 is not None:
            q = self._confidence_v2.quality
            return {"strong": "STRONG", "moderate": "MODERATE", "weak": "WEAK"}.get(q, "WEAK")
        s = self.score
        if s >= 6:
            return "STRONG"
        elif s >= 4:
            return "MODERATE"
        elif s >= 2:
            return "WEAK"
        else:
            return "VERY WEAK"

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
        from strategy.levels import format_levels_message

        signal_word = "ПОКУПКА" if self.signal == SignalType.BUY else "ПРОДАЖА"
        lines = [
            f"{self.signal.value} — {signal_word}",
            f"Инструмент: {self.symbol}",
        ]

        tf_line = f"Таймфрейм: {self.timeframe.upper()}"
        if self._confirmed_tf:
            tf_line += f" | Подтверждение: {self._confirmed_tf}"
        lines.append(tf_line)

        entry = self.entry_price if self.entry_price is not None else self.close
        lines.append(f"Цена входа: {entry}")

        if self.sl is not None:
            sl_pct = (self.sl - entry) / entry * 100 if entry else 0
            lines.append(f"Stop Loss: {self.sl} ({sl_pct:+.2f}%)")
        if self.tp is not None:
            tp_pct = (self.tp - entry) / entry * 100 if entry else 0
            lines.append(f"Take Profit: {self.tp} ({tp_pct:+.2f}%)")
        if self.sl is not None and self.tp is not None and entry:
            rr = abs(self.tp - entry) / abs(entry - self.sl) if entry != self.sl else 0
            lines.append(f"R/R: 1:{rr:.1f}")

        if self.sr_levels:
            lines.append(format_levels_message(self.sr_levels))

        if self.reasons:
            lines.append(f"\nТехнические факторы ({self.score}/7):")
            for r in self.reasons:
                lines.append(f"  {html.escape(r)}")

        if self._context_items:
            lines.append(f"\nРыночный контекст:")
            for item in self._context_items:
                lines.append(f"  {item}")

        all_warnings = list(self.level_warnings)
        if self._context_items:
            ctx_warnings = [i for i in self._context_items if i.startswith("⚠️")]
            all_warnings.extend([i.replace("⚠️ ", "") for i in ctx_warnings])
        if all_warnings:
            lines.append(f"\nПредупреждения:")
            for w in all_warnings:
                lines.append(f"  {html.escape(w)}")

        if self._regime is not None:
            status = "BLOCKED" if self._regime_blocked else ""
            regime_display = f"{self._regime.capitalize()} {status}".strip()
            lines.append(f"\nRegime: {regime_display}")

        lines.append(f"\nИтог: {self.verdict} | Уверенность: {self.confidence:.1f}%")
        if self._confidence_v2 is not None:
            lines.append(f"Quality: {self._confidence_v2.quality}")
        return "\n".join(lines)


class SignalEngine:
    def evaluate(
        self,
        ind: IndicatorValues,
        regime: Any = None,
        sweeps: Optional[list] = None,
        structure: Optional[Any] = None,
    ) -> SignalResult:
        cfg = config.trading
        regime_name = regime.regime if regime else None

        # --- None/NaN guard ---
        critical = {
            "rsi": ind.rsi, "adx": ind.adx,
            "ema_fast": ind.ema_fast, "ema_slow": ind.ema_slow,
            "ema_trend": ind.ema_trend, "macd_hist": ind.macd_hist,
            "dmi_plus": ind.dmi_plus, "dmi_minus": ind.dmi_minus,
            "volume": ind.volume, "volume_sma": ind.volume_sma,
            "atr": ind.atr, "close": ind.close,
        }
        none_fields = []
        for name, val in critical.items():
            if val is None:
                none_fields.append(name)
            elif isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                none_fields.append(name)
        if none_fields:
            return SignalResult(
                signal=SignalType.NO_SIGNAL,
                symbol=ind.symbol, timeframe=ind.timeframe, close=ind.close,
                reasons=[f"Incomplete (None/NaN: {', '.join(none_fields)})"],
                _regime=regime_name,
            )

        # --- Regime gate ---
        if regime_name == "compression":
            return SignalResult(
                signal=SignalType.NO_SIGNAL,
                symbol=ind.symbol, timeframe=ind.timeframe, close=ind.close,
                reasons=["Compression regime — все сигналы заблокированы, ждём expansion"],
                _regime=regime_name, _regime_blocked=True,
            )

        # --- ADX flat filter ---
        if ind.adx < cfg.adx_min:
            return SignalResult(
                signal=SignalType.NO_SIGNAL,
                symbol=ind.symbol, timeframe=ind.timeframe, close=ind.close,
                reasons=[f"ADX={ind.adx:.1f} < {cfg.adx_min} (флэт, сигналы игнорируются)"],
                _regime=regime_name,
            )

        # --- Leading triggers ---
        has_leading_trigger = False
        leading_reasons: List[str] = []

        if structure and structure.last_bos:
            bos = structure.last_bos
            if bos.type == "bullish":
                has_leading_trigger = True
                leading_reasons.append(f"BOS бычий (leading trigger) уровень {bos.level}")
            elif bos.type == "bearish":
                has_leading_trigger = True
                leading_reasons.append(f"BOS медвежий (leading trigger) уровень {bos.level}")

        if sweeps:
            for sw in sweeps:
                if getattr(sw, "is_valid", False):
                    has_leading_trigger = True
                    leading_reasons.append(f"Sweep {sw.type} (leading trigger) уровень {sw.swept_level}")
                    break

        vol_above_avg = ind.volume > ind.volume_sma * cfg.volume_factor
        if ind.volume_delta_pct is not None and vol_above_avg:
            delta = ind.volume_delta_pct
            if delta > cfg.delta_bullish:
                has_leading_trigger = True
                leading_reasons.append(f"Delta: +{delta:.0f}% (покупки доминируют, leading trigger)")
            elif delta < cfg.delta_bearish:
                has_leading_trigger = True
                leading_reasons.append(f"Delta: {delta:.0f}% (продажи доминируют, leading trigger)")

        # --- Lagging triggers (confirmation only, not standalone triggers) ---
        ema_cross_type = None
        if ind.ema_bullish_cross:
            ema_cross_type = "bullish"
        elif ind.ema_bearish_cross:
            ema_cross_type = "bearish"

        macd_cross_type = None
        macd_significant = False
        if ind.close > 0:
            macd_norm = abs(ind.macd_hist / ind.close) * 100
            if macd_norm >= cfg.min_macd_pct:
                macd_significant = True
                if ind.macd_hist > 0 and ind.macd_hist_prev <= 0:
                    macd_cross_type = "bullish"
                elif ind.macd_hist < 0 and ind.macd_hist_prev >= 0:
                    macd_cross_type = "bearish"

        # --- Determine direction (before trigger gate, for factor strengths) ---
        direction = None
        if has_leading_trigger:
            for r in leading_reasons:
                if "бычий" in r.lower() or "покупки" in r.lower():
                    direction = "buy"
                    break
                elif "медвежий" in r.lower() or "продажи" in r.lower():
                    direction = "sell"
                    break
        if direction is None:
            if ema_cross_type == "bullish" or macd_cross_type == "bullish":
                direction = "buy"
            elif ema_cross_type == "bearish" or macd_cross_type == "bearish":
                direction = "sell"
        if direction is None:
            direction = "buy" if ind.ema_fast > ind.ema_slow else "sell"

        # --- Compute factor strengths (before trigger gate) ---
        st_str = _strength_supertrend(ind, direction)
        ema_str = _strength_ema(ind, direction)
        macd_str = _strength_macd(ind, direction)
        rsi_str = _strength_rsi(ind, direction)
        vol_str = _strength_volume(ind, direction)
        adx_str = _strength_adx(ind)
        dmi_str = _strength_dmi(ind, direction)

        weights = _get_weights()
        total_weight = sum(weights.values())
        weighted_score = sum(
            {"Supertrend": st_str, "EMA": ema_str, "MACD": macd_str,
             "RSI": rsi_str, "Volume": vol_str, "ADX": adx_str, "DMI": dmi_str}[name]
            * weights[name]
            for name in weights
        )

        factor_strengths = {
            "Supertrend": st_str, "EMA": ema_str, "MACD": macd_str,
            "RSI": rsi_str, "Volume": vol_str, "ADX": adx_str, "DMI": dmi_str,
            "BUY": weighted_score / total_weight if total_weight else 0.0,
            "SELL": -weighted_score / total_weight if total_weight else 0.0,
        }

        # Trigger gate: leading trigger required
        has_trigger = has_leading_trigger

        if not has_trigger:
            return SignalResult(
                signal=SignalType.NO_SIGNAL,
                symbol=ind.symbol, timeframe=ind.timeframe, close=ind.close,
                reasons=["Нет триггера (нет cross/sweep/BOS/delta)"],
                _has_trigger=False, _has_leading_trigger=has_leading_trigger,
                _regime=regime_name,
                _factor_strengths=factor_strengths, _weighted_score=weighted_score,
                _rsi_strength=rsi_str,
            )

        # --- EMA alignment gate ---
        ema_aligned = False
        ema_spread_pct = 0.0
        if direction == "buy":
            if ind.ema_fast > ind.ema_slow > ind.ema_trend:
                ema_aligned = True
                ema_spread_pct = (ind.ema_fast - ind.ema_slow) / ind.ema_slow * 100
        else:
            if ind.ema_fast < ind.ema_slow < ind.ema_trend:
                ema_aligned = True
                ema_spread_pct = (ind.ema_slow - ind.ema_fast) / ind.ema_fast * 100

        min_spread = cfg.min_ema_spread_pct
        ema_alignment_info = ""

        if not ema_aligned:
            if direction == "buy":
                ema_alignment_info = f"BUY: fast={ind.ema_fast} slow={ind.ema_slow} trend={ind.ema_trend}"
            else:
                ema_alignment_info = f"SELL: fast={ind.ema_fast} slow={ind.ema_slow} trend={ind.ema_trend}"
            return SignalResult(
                signal=SignalType.NO_SIGNAL,
                symbol=ind.symbol, timeframe=ind.timeframe, close=ind.close,
                reasons=["EMA alignment не пройден"],
                _ema_alignment_info=ema_alignment_info,
                _factor_strengths=factor_strengths, _weighted_score=weighted_score,
                _rsi_strength=rsi_str,
                _has_trigger=has_trigger, _has_leading_trigger=has_leading_trigger,
                _regime=regime_name,
            )

        # EMA spread check
        if ema_spread_pct < min_spread:
            return SignalResult(
                signal=SignalType.NO_SIGNAL,
                symbol=ind.symbol, timeframe=ind.timeframe, close=ind.close,
                reasons=[f"EMA spread недостаточно широкий: {ema_spread_pct:.2f}% < {min_spread:.2f}%"],
                _ema_alignment_info="",
                _factor_strengths=factor_strengths, _weighted_score=weighted_score,
                _rsi_strength=rsi_str,
                _has_trigger=has_trigger, _has_leading_trigger=has_leading_trigger,
                _regime=regime_name,
            )

        # EMA slope check: spread must be widening
        if cfg.ema_slope_check:
            current_spread = ind.ema_fast - ind.ema_slow
            prev_spread = ind.ema_fast_prev - ind.ema_slow_prev
            if direction == "buy":
                if current_spread <= prev_spread:
                    return SignalResult(
                        signal=SignalType.NO_SIGNAL,
                        symbol=ind.symbol, timeframe=ind.timeframe, close=ind.close,
                        reasons=["EMA spread не расширяется для BUY"],
                        _ema_alignment_info=f"spread={ema_spread_pct:.2f}%",
                        _factor_strengths=factor_strengths, _weighted_score=weighted_score,
                        _rsi_strength=rsi_str,
                        _has_trigger=has_trigger, _has_leading_trigger=has_leading_trigger,
                        _regime=regime_name,
                    )
            else:
                if current_spread >= prev_spread:
                    return SignalResult(
                        signal=SignalType.NO_SIGNAL,
                        symbol=ind.symbol, timeframe=ind.timeframe, close=ind.close,
                        reasons=["EMA spread не расширяется для SELL"],
                        _ema_alignment_info=f"spread={ema_spread_pct:.2f}%",
                        _factor_strengths=factor_strengths, _weighted_score=weighted_score,
                        _rsi_strength=rsi_str,
                        _has_trigger=has_trigger, _has_leading_trigger=has_leading_trigger,
                        _regime=regime_name,
                    )

        ema_alignment_info = f"spread={ema_spread_pct:.2f}%"

        # --- Build reasons ---
        reasons: List[str] = []
        reasons.extend(leading_reasons)

        if abs(st_str) > 0.5:
            reasons.append(f"Supertrend {'бычий' if st_str > 0 else 'медвежий'}")

        if ema_aligned and ema_cross_type is not None:
            dir_word = "снизу вверх" if ema_cross_type == "bullish" else "сверху вниз"
            reasons.append(f"EMA{cfg.ema_fast} пересекла EMA{cfg.ema_slow} {dir_word}")

        if macd_significant:
            macd_norm = abs(ind.macd_hist / ind.close) * 100 if ind.close > 0 else 0
            dir_word = "бычий" if ind.macd_hist > 0 else "медвежий"
            reasons.append(f"MACD {dir_word} (norm={macd_norm:.2f}%)")

        if ind.rsi < 30:
            reasons.append(f"RSI={ind.rsi:.1f} — перепроданность, возможен отскок (покупки)")
        elif 30 <= ind.rsi < 50:
            reasons.append(f"RSI={ind.rsi:.1f} — нейтральная→бычья зона")
        elif ind.rsi >= 70:
            reasons.append(f"RSI={ind.rsi:.1f} — перекупленность, возможен разворот (продажи)")
        elif ind.rsi > 65:
            reasons.append(f"RSI={ind.rsi:.1f} — нейтральная→медвежья зона")

        if ind.adx >= cfg.adx_strong:
            reasons.append(f"ADX={ind.adx:.1f} (strong trend ≥ {cfg.adx_strong})")

        if vol_above_avg and ind.volume_delta_pct is not None:
            delta = ind.volume_delta_pct
            if delta > cfg.delta_bullish:
                reasons.append(f"Delta: +{delta:.0f}% (покупки доминируют)")
            elif delta < cfg.delta_bearish:
                reasons.append(f"Delta: {delta:.0f}% (продажи доминируют)")

        if ind.dmi_plus > ind.dmi_minus:
            reasons.append(f"DMI+ > DMI- (+{ind.dmi_plus - ind.dmi_minus:.1f})")
        else:
            reasons.append(f"DMI- > DMI+ (+{ind.dmi_minus - ind.dmi_plus:.1f})")

        score = len(reasons)
        min_score = config.scoring.min_score_for_signal

        if score < min_score:
            return SignalResult(
                signal=SignalType.NO_SIGNAL,
                symbol=ind.symbol, timeframe=ind.timeframe, close=ind.close,
                reasons=reasons, score=score,
                _factor_strengths=factor_strengths, _weighted_score=weighted_score,
                _rsi_strength=rsi_str, _ema_alignment_info=ema_alignment_info,
                _has_trigger=has_trigger, _has_leading_trigger=has_leading_trigger,
                _regime=regime_name,
            )

        signal_type = SignalType.BUY if direction == "buy" else SignalType.SELL
        sl, tp = _calculate_sl_tp(ind, signal_type, structure)

        # Confidence V2 — 7 factors
        conf_v2 = None
        try:
            conf_v2 = ConfidenceResult(
                factors=[
                    FactorScore.make("Supertrend", 15, st_str),
                    FactorScore.make("EMA", 15, ema_str),
                    FactorScore.make("MACD", 10, macd_str),
                    FactorScore.make("RSI", 10, rsi_str),
                    FactorScore.make("Volume", 15, vol_str),
                    FactorScore.make("ADX", 10, adx_str),
                    FactorScore.make("DMI", 10, dmi_str),
                ],
                total_score=round(weighted_score, 2),
                quality="strong" if score >= 6 else "moderate" if score >= 4 else "weak",
                recommendation=signal_type.value,
            )
        except Exception:
            pass

        return SignalResult(
            signal=signal_type,
            symbol=ind.symbol, timeframe=ind.timeframe, close=ind.close,
            sl=sl, tp=tp, reasons=reasons, score=score,
            entry_price=sl if signal_type == SignalType.BUY else tp,
            _factor_strengths=factor_strengths, _weighted_score=weighted_score,
            _rsi_strength=rsi_str, _ema_alignment_info=ema_alignment_info,
            _has_trigger=has_trigger, _has_leading_trigger=has_leading_trigger,
            _confidence_v2=conf_v2, _regime=regime_name, _regime_blocked=False,
            _structure_trend=structure.trend if structure else None,
            _structure_bos=structure.last_bos.type if structure and structure.last_bos else None,
        )


def _get_weights() -> Dict[str, int]:
    s = config.scoring
    return {
        "Supertrend": s.w_supertrend, "EMA": s.w_ema,
        "MACD": s.w_macd, "RSI": s.w_rsi,
        "Volume": s.w_volume, "ADX": s.w_adx, "DMI": s.w_dmi,
    }


def _strength_supertrend(ind: IndicatorValues, direction: str) -> float:
    if direction == "buy" and ind.supertrend_direction == 1:
        return 1.0
    if direction == "sell" and ind.supertrend_direction == -1:
        return 1.0
    return -0.5


def _strength_ema(ind: IndicatorValues, direction: str) -> float:
    if direction == "buy" and ind.ema_fast > ind.ema_slow > ind.ema_trend:
        spread = (ind.ema_fast - ind.ema_slow) / ind.ema_slow * 100
        return min(1.0, spread / config.trading.ema_strength_cap)
    if direction == "sell" and ind.ema_fast < ind.ema_slow < ind.ema_trend:
        spread = (ind.ema_slow - ind.ema_fast) / ind.ema_fast * 100
        return -min(1.0, spread / config.trading.ema_strength_cap)
    return -1.0


def _strength_macd(ind: IndicatorValues, direction: str) -> float:
    if ind.close <= 0:
        return 0.0
    norm = abs(ind.macd_hist / ind.close) * 100
    if norm < config.trading.min_macd_pct:
        return 0.0
    raw = (ind.macd_hist / ind.close * 100) * config.trading.macd_score_multiplier
    if direction == "sell":
        raw = -raw
    return max(-1.0, min(1.0, raw))


def _strength_rsi(ind: IndicatorValues, direction: str) -> float:
    rsi = ind.rsi
    # Always from BUY perspective: positive = supports BUY, negative = supports SELL
    if rsi < 30:
        return 1.0
    elif rsi < 50:
        return 0.5
    elif rsi < 65:
        return 0.0
    elif rsi < 70:
        return -0.5
    else:
        return -1.0


def _strength_volume(ind: IndicatorValues, direction: str) -> float:
    vol_above = ind.volume > ind.volume_sma * config.trading.volume_factor
    if not vol_above:
        return -0.3
    if ind.volume_delta_pct is not None:
        delta = ind.volume_delta_pct
        vol_ratio = ind.volume / ind.volume_sma if ind.volume_sma > 0 else 1.0
        if delta > config.trading.delta_bullish:
            s = min(1.0, 0.3 + 0.5 * (vol_ratio - 1.0) + 0.2 * (delta / config.trading.volume_delta_norm))
            return s if direction == "buy" else -s * 0.5
        elif delta < config.trading.delta_bearish:
            s = min(1.0, 0.3 + 0.5 * (vol_ratio - 1.0) + 0.2 * (abs(delta) / config.trading.volume_delta_norm))
            return s if direction == "sell" else -s * 0.5
    return 0.3


def _strength_adx(ind: IndicatorValues) -> float:
    adx_min = config.trading.adx_min
    if ind.adx < adx_min:
        return 0.0
    strength = (ind.adx - adx_min) / config.trading.adx_strength_range
    return max(-1.0, min(1.0, strength))


def _strength_dmi(ind: IndicatorValues, direction: str) -> float:
    diff = ind.dmi_plus - ind.dmi_minus
    raw = (diff / config.trading.dmi_norm_divisor) * config.trading.dmi_strength_multiplier
    if direction == "sell":
        raw = -raw
    return max(-1.0, min(1.0, raw))


def _calculate_sl_tp(
    ind: IndicatorValues, signal: SignalType, structure: Optional[Any] = None
):
    cfg = config.trading
    atr = ind.atr if ind.atr > 0 else ind.close * cfg.atr_fallback_pct / 100

    if structure and structure.last_bos:
        bos = structure.last_bos
        if signal == SignalType.BUY and bos.type == "bullish":
            sl = round(bos.level * 0.995, 8)
            tp = round(ind.close + atr * cfg.atr_multiplier_tp, 8)
            return sl, tp
        if signal == SignalType.SELL and bos.type == "bearish":
            sl = round(bos.level * 1.005, 8)
            tp = round(ind.close - atr * cfg.atr_multiplier_tp, 8)
            return sl, tp

    if signal == SignalType.BUY:
        sl = round(ind.close - atr * cfg.atr_multiplier_sl, 8)
        tp = round(ind.close + atr * cfg.atr_multiplier_tp, 8)
    else:
        sl = round(ind.close + atr * cfg.atr_multiplier_sl, 8)
        tp = round(ind.close - atr * cfg.atr_multiplier_tp, 8)
    return sl, tp


signal_engine = SignalEngine()
