# 2.6 strategy/signal_engine.py — Логика сигналов

**Что делает:**
- `evaluate(indicator_values)` → `SignalResult(BUY/SELL/NO_SIGNAL)`

**7 критериев для BUY:**
1. Supertrend восходящий
2. EMA alignment бычье (fast > slow > trend)
3. EMA fast > slow (или пересечение снизу вверх)
4. RSI в зоне силы (50–70)
5. MACD гистограмма положительная (или пересечение вверх)
6. ADX >= 20 (сильный тренд) — **глобальный фильтр, без него NO_SIGNAL**
7. Объём выше среднего

**7 критериев для SELL:**
1. Supertrend нисходящий
2. EMA alignment медвежье (fast < slow < trend)
3. EMA fast < slow (или пересечение сверху вниз)
4. RSI в зоне слабости (30–50)
5. MACD гистограмма отрицательная (или пересечение вниз)
6. ADX >= 20
7. Объём выше среднего

**Логика принятия решения:**
- ADX < 20 → NO_SIGNAL (флэт, игнорируем)
- BUY_score >= 4 И BUY_score > SELL_score → BUY
- SELL_score >= 4 И SELL_score > BUY_score → SELL
- Иначе → NO_SIGNAL

**SL/TP расчёт (через ATR):**
- BUY: SL = close - ATR × 1.5, TP = close + ATR × 3.0
- SELL: SL = close + ATR × 1.5, TP = close - ATR × 3.0
- Округляется до 8 знаков

**Форматирование сообщения:**
- `format_message()` → HTML для Telegram:
  - Эмодзи + тип сигнала (🟢 BUY / 🔴 SELL)
  - Инструмент, таймфрейм, цена
  - Entry price, SL, TP, R/R (risk/reward)
  - Список причин (каждое совпавшее условие)
  - Сила сигнала: ⭐ (score/7)

**При каких условиях:**
- Должен быть получен валидный `IndicatorValues` от `indicator_engine.calculate()`
