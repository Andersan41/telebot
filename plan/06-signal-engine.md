# 2.6 strategy/signal_engine.py — Логика сигналов

**Что делает:**

- `evaluate(indicator_values)` → `SignalResult(BUY/SELL/NO_SIGNAL)`

## Условия и их реальный учёт в score

Декларативно — «8 факторов», в реальном подсчёте `buy_score`/`sell_score`
участвуют все 8. ADX выступает и фильтром, и критерием (≥ 25 → +1 обеим сторонам).
DMI+/DMI- даёт +1 только подходящей стороне.

| # | Фактор          | Где                                       | Влияние на BUY / SELL score                                                           |
|---|-----------------|-------------------------------------------|---------------------------------------------------------------------------------------|
| 1 | Supertrend      | направление                               | bullish → +1 BUY; bearish → +1 SELL                                                   |
| 2 | EMA alignment   | fast><slow><trend                         | bullish_alignment → +1 BUY; bearish → +1 SELL                                         |
| 3 | EMA cross / pos | одна ветка `if/elif/elif/elif`            | bullish cross или fast>slow → +1 BUY; bearish cross или fast<slow → +1 SELL           |
| 4 | RSI             | положение в зоне                          | `rsi_bull_min ≤ rsi < overbought` → +1 BUY; `oversold < rsi ≤ rsi_bear_max` → +1 SELL |
| 5 | MACD            | знак гистограммы (+приоритет пересечения) | `macd_hist > 0` → +1 BUY; `< 0` → +1 SELL                                             |
| 6 | Volume          | `volume > sma × volume_factor`            | **+1 одновременно в BUY и SELL** (нейтральный «усилитель»)                            |
| 7 | ADX strong      | `adx ≥ 25`                                | **+1 обеим сторонам** (сильный тренд, не просто > adx_min)                            |
| 8 | DMI direction   | DMI+ vs DMI-                              | **+1 подходящей стороне** (ассиметричный: buy или sell)                                |

**Максимально достижимый score одной стороны — 8** (все 8 критериев).
Симметричное добавление Volume в оба score никогда не даёт обеим сторонам пройти
порог одновременно — побеждает сторона с большим перевесом.

`format_message()` и view'ы в `bot/menu.py` выводят `({score}/8)`. Звёзды
капятся отдельно: `'⭐' * min(score, 5)` (`signal_engine.py:57`,
`bot/menu.py:307,372`) — при score=8 показывается 5 звёзд из 8.

**Reasons победителя совпадают с score**: ADX и DMI причины уже сидят в
`buy_reasons` / `sell_reasons` (`signal_engine.py:141-155`) — дублирования нет.

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
- «Сила сигнала: ⭐⭐⭐ (score/8)»

**При каких условиях вызывается:**

- Должен быть получен валидный `IndicatorValues` от `indicator_engine.calculate()`
