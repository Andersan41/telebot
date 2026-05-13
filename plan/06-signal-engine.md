# 2.6 strategy/signal_engine.py — Логика сигналов

**Что делает:**

- `evaluate(indicator_values)` → `SignalResult(BUY/SELL/NO_SIGNAL)`

## Условия и их реальный учёт в score

Декларативно — «7 факторов», но в реальном подсчёте `buy_score`/`sell_score`
участвуют 5 уникальных условий + объём (нейтрально, добавляется в оба списка).
ADX выступает не критерием, а жёстким фильтром.

| # | Фактор          | Где                                       | Влияние на BUY / SELL score                                                           |
|---|-----------------|-------------------------------------------|---------------------------------------------------------------------------------------|
| 1 | Supertrend      | направление                               | bullish → +1 BUY; bearish → +1 SELL                                                   |
| 2 | EMA alignment   | fast><slow><trend                         | bullish_alignment → +1 BUY; bearish → +1 SELL                                         |
| 3 | EMA cross / pos | одна ветка `if/elif/elif/elif`            | bullish cross или fast>slow → +1 BUY; bearish cross или fast<slow → +1 SELL           |
| 4 | RSI             | положение в зоне                          | `rsi_bull_min ≤ rsi < overbought` → +1 BUY; `oversold < rsi ≤ rsi_bear_max` → +1 SELL |
| 5 | MACD            | знак гистограммы (+приоритет пересечения) | `macd_hist > 0` → +1 BUY; `< 0` → +1 SELL                                             |
| 6 | Volume          | `volume > sma × volume_factor`            | **+1 одновременно в BUY и SELL** (нейтральный «усилитель»)                            |
| – | ADX             | `adx >= adx_min`                          | **фильтр**: если ниже — `NO_SIGNAL` сразу; иначе только добавляется в `reasons`       |
| – | DMI+/DMI-       | сравнение                                 | только в `reasons`, в score не идёт                                                   |

**Максимально достижимый score одной стороны — 6** (все 5 уникальных + Volume).
Симметричное добавление Volume в оба score никогда не даёт обеим сторонам пройти
порог одновременно — побеждает сторона с большим перевесом.

`format_message()` и view'ы в `bot/menu.py` выводят `({score}/6)`. Звёзды
капятся отдельно: `'⭐' * min(score, 5)` (`signal_engine.py:57`,
`bot/menu.py:289,354`) — при score=6 показывается 5 звёзд из 6.

**Reasons победителя содержат больше пунктов, чем score**: `adx_reason` и
`dmi_reason` всегда добавляются в `reasons` выигравшей стороны
(`signal_engine.py:155, 168`) независимо от того, поддерживают они её
направление или нет. Это видно в Telegram-сообщении как 2 «лишних» строки
по сравнению с числом баллов.

## Логика принятия решения

- `ADX < adx_min` → NO_SIGNAL (флэт, игнорируем)
- `buy_score >= 4` И `buy_score > sell_score` → BUY
- `sell_score >= 4` И `sell_score > buy_score` → SELL
- Иначе → NO_SIGNAL

## SL/TP (через ATR)

- BUY:  SL = `close − ATR × atr_multiplier_sl` (1.5), TP = `close + ATR × atr_multiplier_tp` (3.0)
- SELL: SL = `close + ATR × atr_multiplier_sl`, TP = `close − ATR × atr_multiplier_tp`
- Округление до 8 знаков

## Форматирование сообщения

`format_message()` → HTML для Telegram:

- Эмодзи + тип сигнала (🟢 BUY / 🔴 SELL)
- Инструмент, таймфрейм, цена
- Entry price (если есть), SL, TP, R/R
- Список причин (все совпавшие условия)
- «Сила сигнала: ⭐⭐⭐ (score/6)»

**При каких условиях вызывается:**

- Должен быть получен валидный `IndicatorValues` от `indicator_engine.calculate()`
