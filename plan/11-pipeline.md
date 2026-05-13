# 3. Полный пайплайн сигнала (пошагово)

```
APScheduler cron tick
  ├── hourly_scan   →  _scan_job(timeframes=["1h"])
  └── 4h_scan       →  _scan_job(timeframes=["4h"])
  │
  ├── run_scan_cycle(notify_callback, timeframes)
  │     │
  │     ├── [Параллельно] scan_symbol(symbol, tf, callback)
  │     │                 для каждого symbol × tf из аргумента
  │     │     │
  │     │     ├── 1. Cooldown по {symbol}_{timeframe} → активен? → None
  │     │     │
  │     │     ├── 2. fetch_ohlcv() → indicator_engine.calculate() → IndicatorValues
  │     │     │     None → возврат
  │     │     │
  │     │     ├── 3. signal_engine.evaluate() → SignalResult
  │     │     │     NO_SIGNAL → возврат
  │     │     │
  │     │     ├── 4. Подтверждение на 15M  (только если confirm_tf != tf)
  │     │     │     fetch_ohlcv(15m) → evaluate()
  │     │     │     direction несовпадает → отмена, возврат None
  │     │     │     совпадает → entry_price = close(15m), +reason,
  │     │     │                  confirmed_on_lower_tf = True
  │     │     │     данных 15M нет → подтверждение пропущено (warning),
  │     │     │                       confirmed_on_lower_tf = False
  │     │     │
  │     │     ├── 5. Контекстное обогащение  (только если CONTEXT_ENABLED)
  │     │     │     get_snapshot(symbol)   (timeout 10 s)
  │     │     │     context_scorer.score(signal_direction, snapshot) → verdict
  │     │     │     save_context_snapshot(signal_id=None)  ← первая запись
  │     │     │     verdict == BLOCKED И CONTEXT_BLOCK_ON_BLOCKED → отмена
  │     │     │     rank(verdict) < rank(CONTEXT_MIN_VERDICT)     → отмена
  │     │     │
  │     │     ├── 6. db.save_signal(confirmed=confirmed_on_lower_tf)
  │     │     │
  │     │     ├── 7. save_context_snapshot(signal_id=...)  ← вторая запись
  │     │     │
  │     │     ├── 8. _set_cooldown()  ← in-memory, не выживает рестарт
  │     │     │
  │     │     └── 9. notify_callback(result, context_verdict) → send_signal()
  │     │
  │     └── Логирование: "Signals found: X/Y"
```

При ручном вызове `cmd_scan()` параметр `timeframes` не передаётся —
сканируются все `primary_timeframes`.

Ранг вердиктов: `BLOCKED < CONFLICTED < WEAK < CONFIRMED`. Пустой
`CONTEXT_MIN_VERDICT` (или неизвестное значение) отключает гейт.
