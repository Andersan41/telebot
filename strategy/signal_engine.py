"""
strategy/signal_engine.py — Логика принятия решения BUY / SELL / NO_SIGNAL
"""
import html
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict
from loguru import logger
from config.settings import config
from indicators.engine import IndicatorValues


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
    score: int = 0          # Количество совпавших условий
    sr_levels: Optional[Dict[str, Dict[str, List[float]]]] = None
    level_warnings: List[str] = field(default_factory=list)
    _context_score: Optional[float] = None  # -1.0 to 1.0 from context scorer
    _max_context_score: float = 1.0
    _confirmed_tf: Optional[str] = None  # таймфрейм подтверждения
    _context_items: List[str] = field(default_factory=list)  # элементы контекста

    @property
    def is_actionable(self) -> bool:
        return self.signal != SignalType.NO_SIGNAL

    @property
    def verdict(self) -> str:
        confidence = self.confidence
        if confidence >= 75:
            return "STRONG"
        elif confidence >= 55:
            return "MODERATE"
        elif confidence >= 35:
            return "WEAK"
        else:
            return "VERY WEAK"

    @property
    def confidence(self) -> float:
        tech_pct = self.score / 8.0
        if self._context_score is not None:
            market_pct = (self._context_score + 1.0) / 2.0
            confidence = (tech_pct * 0.6) + (market_pct * 0.4)
        else:
            confidence = tech_pct
        return round(confidence * 100, 1)

    def format_message(self) -> str:
        from strategy.levels import format_levels_message

        emoji = "🟢" if self.signal == SignalType.BUY else "🔴"
        signal_word = "ПОКУПКА" if self.signal == SignalType.BUY else "ПРОДАЖА"
        lines = [
            f"{emoji} <b>{self.signal.value} — {signal_word}</b>",
            f"📊 <b>Инструмент:</b> {self.symbol}",
        ]

        # Таймфрейм с подтверждением
        tf_line = f"⏱ <b>Таймфрейм:</b> {self.timeframe.upper()}"
        if self._confirmed_tf:
            tf_line += f" | Подтверждение: {self._confirmed_tf} ✅"
        lines.append(tf_line)

        # Цена входа
        entry = self.entry_price or self.close
        lines.append(f"💰 <b>Цена входа:</b> {entry:.4f}")

        # SL/TP с процентами
        if self.sl:
            sl_pct = (self.sl - entry) / entry * 100
            lines.append(f"🛑 <b>Stop Loss:</b> {self.sl:.4f} ({sl_pct:+.2f}%)")
        if self.tp:
            tp_pct = (self.tp - entry) / entry * 100
            lines.append(f"🎯 <b>Take Profit:</b> {self.tp:.4f} ({tp_pct:+.2f}%)")
        if self.sl and self.tp:
            rr = abs(self.tp - entry) / abs(entry - self.sl)
            lines.append(f"⚖️ <b>R/R:</b> 1:{rr:.1f}")

        # Уровни S/R
        if self.sr_levels:
            lines.append(format_levels_message(self.sr_levels))

        # Технические факторы
        if self.reasons:
            lines.append(f"\n📋 <b>Технические факторы ({self.score}/8):</b>")
            for r in self.reasons:
                lines.append(f"  ✅ {html.escape(r)}")

        # Рыночный контекст
        if self._context_items:
            lines.append(f"\n📊 <b>Рыночный контекст:</b>")
            for item in self._context_items:
                lines.append(f"  {item}")

        # Предупреждения
        all_warnings = list(self.level_warnings)
        if self._context_items:
            ctx_warnings = [i for i in self._context_items if i.startswith("⚠️")]
            all_warnings.extend([i.replace("⚠️ ", "") for i in ctx_warnings])
        if all_warnings:
            lines.append(f"\n⚠️ <b>Предупреждения:</b>")
            for w in all_warnings:
                lines.append(f"  • {html.escape(w)}")

        # Итог
        lines.append(f"\n💪 <b>Итог:</b> {self.verdict} | Уверенность: {self.confidence:.1f}%")
        return "\n".join(lines)


class SignalEngine:
    """
    Логика:
    - BUY:  Supertrend ↑ + EMA fast > slow + RSI > 50 + MACD бычий + ADX > 20 + объём ↑
    - SELL: Supertrend ↓ + EMA fast < slow + RSI < 50 + MACD медвежий + ADX > 20 + объём ↑
    - Фильтры: ADX < 20 = флэт → игнорируем
    """

    def evaluate(self, ind: IndicatorValues) -> SignalResult:
        cfg = config.trading

        # === Фильтр флэта ===
        if not ind.trend_is_strong:
            return SignalResult(
                signal=SignalType.NO_SIGNAL,
                symbol=ind.symbol,
                timeframe=ind.timeframe,
                close=ind.close,
                reasons=[f"ADX={ind.adx:.1f} < {cfg.adx_min} (флэт, сигналы игнорируются)"],
            )

        buy_reasons = []
        sell_reasons = []

        # --- Supertrend ---
        if ind.supertrend_bullish:
            buy_reasons.append(f"Supertrend: восходящий тренд")
        elif ind.supertrend_bearish:
            sell_reasons.append(f"Supertrend: нисходящий тренд")

        # --- EMA расположение ---
        if ind.ema_bullish_alignment:
            buy_reasons.append(f"EMA выравнивание: {cfg.ema_fast}>{cfg.ema_slow}>{cfg.ema_trend} (бычье)")
        elif ind.ema_bearish_alignment:
            sell_reasons.append(f"EMA выравнивание: {cfg.ema_fast}<{cfg.ema_slow}<{cfg.ema_trend} (медвежье)")

        # --- EMA пересечение (триггер) ---
        if ind.ema_bullish_cross:
            buy_reasons.append(f"EMA{cfg.ema_fast} пересекла EMA{cfg.ema_slow} снизу вверх")
        elif ind.ema_bearish_cross:
            sell_reasons.append(f"EMA{cfg.ema_fast} пересекла EMA{cfg.ema_slow} сверху вниз")
        elif ind.ema_fast > ind.ema_slow:
            buy_reasons.append(f"EMA{cfg.ema_fast} > EMA{cfg.ema_slow}")
        elif ind.ema_fast < ind.ema_slow:
            sell_reasons.append(f"EMA{cfg.ema_fast} < EMA{cfg.ema_slow}")

        # --- RSI ---
        if cfg.rsi_bull_min <= ind.rsi < cfg.rsi_overbought:
            buy_reasons.append(f"RSI={ind.rsi:.1f} (зона силы, не перекуплен)")
        elif cfg.rsi_oversold < ind.rsi <= cfg.rsi_bear_max:
            sell_reasons.append(f"RSI={ind.rsi:.1f} (зона слабости, не перепродан)")

        # --- MACD ---
        if ind.macd_hist > 0:
            if ind.macd_bullish_cross:
                buy_reasons.append("MACD: пересечение вверх (бычий сигнал)")
            else:
                buy_reasons.append(f"MACD гистограмма положительная ({ind.macd_hist:.4f})")
        elif ind.macd_hist < 0:
            if ind.macd_bearish_cross:
                sell_reasons.append("MACD: пересечение вниз (медвежий сигнал)")
            else:
                sell_reasons.append(f"MACD гистограмма отрицательная ({ind.macd_hist:.4f})")

        # --- Объём ---
        if ind.volume_above_avg:
            vol_ratio = ind.volume / ind.volume_sma
            if ind.volume_delta_pct is not None:
                delta = ind.volume_delta_pct
                if delta > 0:
                    direction = f"Delta: +{delta:.0f}% (покупки)"
                    vol_emoji = "✅"
                else:
                    direction = f"Delta: {delta:.0f}% (продажи)"
                    vol_emoji = "✅"
            else:
                direction = "Направление: н/д"
                vol_emoji = "⚠️"
            vol_reason = f"Объём: {vol_ratio:.1f}x | {direction} {vol_emoji}"
            buy_reasons.append(vol_reason)
            sell_reasons.append(vol_reason)

        # --- ADX strong trend (≥ 25 — реальный «сильный» тренд, не просто > adx_min) ---
        if ind.adx >= 25.0:
            adx_strong_reason = f"ADX={ind.adx:.1f} (strong trend ≥ 25)"
            buy_reasons.append(adx_strong_reason)
            sell_reasons.append(adx_strong_reason)

        # --- DMI direction match (ассиметричный — даёт +1 только подходящей стороне) ---
        if ind.dmi_plus > ind.dmi_minus:
            buy_reasons.append(
                f"DMI+ > DMI- (+{ind.dmi_plus - ind.dmi_minus:.1f})"
            )
        else:
            sell_reasons.append(
                f"DMI- > DMI+ (+{ind.dmi_minus - ind.dmi_plus:.1f})"
            )

        # === Принятие решения ===
        buy_score = len(buy_reasons)
        sell_score = len(sell_reasons)

        # Минимальный порог — 4 из 6 возможных условий
        min_score = 4

        if buy_score >= min_score and buy_score > sell_score:
            sl, tp = self._calculate_sl_tp(ind, SignalType.BUY)
            return SignalResult(
                signal=SignalType.BUY,
                symbol=ind.symbol,
                timeframe=ind.timeframe,
                close=ind.close,
                sl=sl,
                tp=tp,
                reasons=buy_reasons,
                score=buy_score,
            )

        elif sell_score >= min_score and sell_score > buy_score:
            sl, tp = self._calculate_sl_tp(ind, SignalType.SELL)
            return SignalResult(
                signal=SignalType.SELL,
                symbol=ind.symbol,
                timeframe=ind.timeframe,
                close=ind.close,
                sl=sl,
                tp=tp,
                reasons=sell_reasons,
                score=sell_score,
            )

        return SignalResult(
            signal=SignalType.NO_SIGNAL,
            symbol=ind.symbol,
            timeframe=ind.timeframe,
            close=ind.close,
            reasons=[f"Недостаточно условий (BUY:{buy_score}, SELL:{sell_score}, нужно {min_score})"],
        )

    def _calculate_sl_tp(self, ind: IndicatorValues, signal: SignalType):
        """Расчёт SL и TP на основе ATR"""
        cfg = config.trading
        atr = ind.atr
        if signal == SignalType.BUY:
            sl = round(ind.close - atr * cfg.atr_multiplier_sl, 8)
            tp = round(ind.close + atr * cfg.atr_multiplier_tp, 8)
        else:
            sl = round(ind.close + atr * cfg.atr_multiplier_sl, 8)
            tp = round(ind.close - atr * cfg.atr_multiplier_tp, 8)
        return sl, tp


signal_engine = SignalEngine()
