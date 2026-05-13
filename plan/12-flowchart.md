# 4. Блок-схема принятия решения (Signal Engine)

```
IndicatorValues
  │
  ├── ADX < adx_min (20)?
  │     └── YES → NO_SIGNAL ("Флэт, игнорируется")
  │
  ├── Накопление buy_reasons / sell_reasons:
  │     1. Supertrend bullish/bearish
  │     2. EMA alignment (fast><slow><trend)
  │     3. EMA cross или fast vs slow (одна из веток)
  │     4. RSI в зоне силы / слабости
  │     5. MACD hist > 0 или < 0
  │     6. Volume above avg  → +1 И в BUY, И в SELL (нейтральный)
  │
  │  Примечание: ADX и DMI добавляются в reasons,
  │  но в score не учитываются — макс. buy_score = sell_score = 6.
  │
  ├── buy_score >= 4 И buy_score > sell_score → BUY + SL/TP (ATR)
  ├── sell_score >= 4 И sell_score > buy_score → SELL + SL/TP (ATR)
  └── Иначе → NO_SIGNAL
```
