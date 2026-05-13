# 4. Блок-схема принятия решения (Signal Engine)

```
IndicatorValues
  │
  ├── ADX < 20?
  │     └── YES → NO_SIGNAL ("Флэт, игнорируется")
  │
  ├── Supertrend bullish?
  ├── EMA alignment bullish?
  ├── EMA fast > slow?
  ├── RSI 50-70?
  ├── MACD hist > 0?
  └── Volume above avg?
        │
        ├── BUY_score >= 4 И BUY > SELL → BUY + SL/TP (ATR)
        ├── SELL_score >= 4 И SELL > BUY → SELL + SL/TP (ATR)
        └── Иначе → NO_SIGNAL
```
