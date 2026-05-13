# 2.5 indicators/engine.py — Расчёт индикаторов

**Что делает:**

- `calculate(df, symbol, timeframe)` → `IndicatorValues` для последней закрытой свечи
- Рассчитывает через pandas-ta:
    1. **EMA** — 9/21/50 (`ema_fast`, `ema_slow`, `ema_trend`) + prev значения для пересечения
    2. **RSI** — период 14
    3. **MACD** — 12/26/9 (macd, signal, histogram) + prev histogram для пересечения
    4. **ADX + DMI** — период 14 (adx, dmi_plus, dmi_minus)
    5. **ATR** — период 14
    6. **Volume SMA** — длина **20 захардкожена** прямо в `engine.py:155`
       (`ta.sma(df["volume"], length=20)`), а не из `TradingConfig`
    7. **Supertrend** — 10/3.0 (значение + направление: 1 = up, -1 = down).
       При отсутствии направления (например, недостаточно данных) `supertrend_dir`
       возвращается как `0` (`engine.py:209`) — это не bullish и не bearish,
       а нейтральное «неизвестно».

- Вычисляемые свойства `IndicatorValues`:
    - `ema_bullish_cross` — fast пересекла slow снизу вверх
    - `ema_bearish_cross` — fast пересекла slow сверху вниз
    - `ema_bullish_alignment` — fast > slow > trend
    - `ema_bearish_alignment` — fast < slow < trend
    - `macd_bullish_cross` — гистограмма перешла с отрицательной на положительную
    - `macd_bearish_cross` — гистограмма перешла с положительной на отрицательную
    - `volume_above_avg` — объём > SMA × volume_factor (1.2)
    - `trend_is_strong` — ADX >= adx_min (20)
    - `supertrend_bullish` / `supertrend_bearish`

**При каких условиях:**

- Данных должно быть >= `candles_limit // 2` (100 свечей)
- После расчёта удаляются строки с NaN по `ema_fast, ema_slow, rsi, adx, atr`
- Если чистых данных < 2 → возвращает None
- Все периоды (`ema_fast`, `rsi_period`, `adx_period`, …) и пороги
  (`rsi_bull_min`, `adx_min`, `volume_factor`, …) **жёстко заданы** в
  `TradingConfig` dataclass и **не управляются через .env** — изменение
  требует правки `config/settings.py`. Исключение: `volume_sma=20` (не в
  `TradingConfig`, зашит в `engine.py:155`). См.
  [`plan/improvements/A1-indicators-env.md`](improvements/A1-indicators-env.md).
