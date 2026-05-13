# 3. Полный пайплайн сигнала (пошагово)

```
APScheduler cron tick (:02 или :05)
  │
  ├── run_scan_cycle(notify_callback)
  │     │
  │     ├── [Параллельно] scan_symbol(symbol, tf, callback) для каждого symbol × timeframe
  │     │     │
  │     │     ├── 1. Проверка cooldown (60 мин) → если активен, возврат None
  │     │     │
  │     │     ├── 2. fetch_ohlcv() → indicator_engine.calculate() → IndicatorValues
  │     │     │     Если None → возврат None
  │     │     │
  │     │     ├── 3. signal_engine.evaluate() → SignalResult
  │     │     │     Если NO_SIGNAL → возврат None
  │     │     │
  │     │     ├── 4. Подтверждение на 15M
  │     │     │     │  fetch_ohlcv(15m) → evaluate()
  │     │     │     ├── Сигнал не совпадает → отмена, возврат None
  │     │     │     └── Сигнал совпадает → entry_price, причина
  │     │     │
  │     │     ├── 5. Контекстное обогащение
  │     │     │     │  context_engine.get_snapshot(symbol) → ContextSnapshot
  │     │     │     │  context_scorer.score(signal_direction, snapshot) → ContextVerdict
  │     │     │     │  Сохранение snapshot в БД (без signal_id)
  │     │     │     ├── Вердикт BLOCKED + CONTEXT_BLOCK_ON_BLOCKED → отмена
  │     │     │     └── Иначе → вердикт в уведомлении
  │     │     │
  │     │     ├── 6. db.save_signal() → сохранение сигнала
  │     │     │
  │     │     ├── 7. Сохранение snapshot с signal_id (если контекст был)
  │     │     │
  │     │     ├── 8. Установка cooldown
  │     │     │
  │     │     └── 9. notify_callback(result, context_verdict) → send_signal()
  │     │
  │     └── Логирование: "Signals found: X/Y"
```
