"""
strategy/signal_engine.py — Логика принятия решения BUY / SELL / NO_SIGNAL
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
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
    sl: Optional[float] = None
    tp: Optional[float] = None
    reasons: List[str] = field(default_factory=list)
    score: int = 0          # Количество совпавших условий

    @property
    def is_actionable(self) -> bool:
        return self.signal != SignalType.NO_SIGNAL

    def format_message(self) -> str:
        emoji = "🟢" if self.signal == SignalType.BUY else "🔴"
        signal_word = "ПОКУПКА" if self.signal == SignalType.BUY else "ПРОДАЖА"
        lines = [
            f"{emoji} <b>{self.signal.value} — {signal_word}</b>",
            f"📊 <b>Инструмент:</b> {self.symbol}",
            f"⏱ <b>Таймфрейм:</b> {self.timeframe}",
            f"💰 <b>Цена:</b> {self.close:.4f}",
        ]
        if self.sl:
            lines.append(f"🛑 <b>Stop Loss:</b> {self.sl:.4f}")
        if self.tp:
            lines.append(f"🎯 <b>Take Profit:</b> {self.tp:.4f}")
        if self.sl and self.tp:
            rr = abs(self.tp - self.close) / abs(self.close - self.sl)
            lines.append(f"⚖️ <b>R/R:</b> 1:{rr:.1f}")
        if self.reasons:
            lines.append(f"\n📋 <b>Причины:</b>")
            for r in self.reasons:
                lines.append(f"  • {r}")
        lines.append(f"\n💪 <b>Сила сигнала:</b> {'⭐' * min(self.score, 5)} ({self.score}/7)")
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

        # --- ADX (общий для обоих) ---
        adx_reason = f"ADX={ind.adx:.1f} (сильный тренд)"
        dmi_reason = (
            f"DMI+={ind.dmi_plus:.1f} > DMI-={ind.dmi_minus:.1f}"
            if ind.dmi_plus > ind.dmi_minus
            else f"DMI-={ind.dmi_minus:.1f} > DMI+={ind.dmi_plus:.1f}"
        )

        # --- Объём ---
        if ind.volume_above_avg:
            vol_reason = f"Объём выше среднего ({ind.volume / ind.volume_sma:.1f}x)"
            buy_reasons.append(vol_reason)
            sell_reasons.append(vol_reason)

        # === Принятие решения ===
        buy_score = len(buy_reasons)
        sell_score = len(sell_reasons)

        # Минимальный порог — 4 из 7 возможных условий
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
                reasons=buy_reasons + [adx_reason, dmi_reason],
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
                reasons=sell_reasons + [adx_reason, dmi_reason],
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
