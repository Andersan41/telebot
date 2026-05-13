# 2.7 scheduler/tasks.py — Планировщик

**Что делает:**
- Использует `AsyncIOScheduler` (timezone=UTC)
- Две cron-задачи:
  1. **1H таймфрейм**: каждый час в `:02` минуты (после закрытия часовой свечи)
  2. **4H таймфрейм**: `0,4,8,12,16,20 * * *` в `:05` минуты
- `max_instances=1, coalesce=True` — не запускает новый, если предыдущий не завершён
- `setup()` — конфигурирует задачи
- `start()` / `stop()` — управление жизненным циклом

**При каких условиях:**
- `start()` — в main.py после настройки
- `stop()` — при shutdown
- Каждая задача вызывает `run_scan_cycle(notify_callback)`

---

# 2.8 scheduler/scanner.py — Цикл сканирования

**Что делает (полный пайплайн):**

**Шаг 1 — Сбор данных:** `exchange_client.fetch_ohlcv(symbol, timeframe)` → `indicator_engine.calculate(df)`

**Шаг 2 — Оценка:** `signal_engine.evaluate(indicator_values)` → SignalResult

**Шаг 3 — Подтверждение на 15M:** Если сигнал есть и confirm_timeframe ≠ primary:
- Загружаем 15M данные для того же символа
- Оцениваем на 15M тот же engine
- Если направление сигнала на 15M **не совпадает** с основным → сигнал отклоняется
- Если совпадает → добавляется причина "✅ Подтверждение на {confirm_tf}", entry_price = close на 15M

**Шаг 4 — Контекстное обогащение (если CONTEXT_ENABLED):**
- Запускается `context_engine.get_snapshot(symbol)` (timeout 10s)
- `context_scorer.score()` → вердикт (CONFIRMED/WEAK/CONFLICTED/BLOCKED)
- Если `CONTEXT_BLOCK_ON_BLOCKED=True` и вердикт BLOCKED → сигнал отклоняется
- Сохраняется снимок в БД (один раз до сохранения сигнала, второй — с signal_id)

**Шаг 5 — Сохранение в БД:** `db.save_signal(...)` → сигнал с логами, SL, TP, score

**Шаг 6 — Cooldown:** Запоминается время последнего сигнала для `{symbol}_{timeframe}`
- Длительность: `SIGNAL_COOLDOWN_MINUTES` (по умолчанию 60)
- Если cooldown активен — `scan_symbol()` возвращает None без проверки

**Шаг 7 — Уведомление:** `notify_callback(result, context_verdict)` → отправка в Telegram

**Масштабирование:**
- `run_scan_cycle()` обходит все символы × все таймфреймы параллельно (`asyncio.gather`)
- Сигналы считаются: `signals_found / total_tasks`

**При каких условиях:**
- Вызывается из `_scan_job()` по расписанию
- Вызывается из `cmd_scan()` (ручной запуск админом)
- Каждый символ × таймфрейм — отдельная корутина
