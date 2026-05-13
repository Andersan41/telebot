# 2.7 scheduler/tasks.py — Планировщик

**Что делает:**

- Использует `AsyncIOScheduler` (timezone=UTC)
- Регистрирует две cron-задачи (см. ниже)
- `max_instances=1, coalesce=True` — не запускает новый, если предыдущий не завершён
- `setup()` — конфигурирует задачи; `start()` / `stop()` — управление жизненным циклом

**Cron-задачи:**

| id            | Расписание                     | timeframes | Что делает                                                                  |
|---------------|--------------------------------|------------|-----------------------------------------------------------------------------|
| `hourly_scan` | `minute=2` (каждый час в :02)  | `["1h"]`   | `run_scan_cycle(notify, timeframes=["1h"])` — только 1H                     |
| `4h_scan`     | `hour=0,4,8,12,16,20 minute=5` | `["4h"]`   | `run_scan_cycle(notify, timeframes=["4h"])` — только 4H                     |

Каждый джоб передаёт в `_scan_job` свой список таймфреймов через
`kwargs={"timeframes": [...]}`. `run_scan_cycle` обходит `symbols × tfs`. При
ручном вызове из `cmd_scan` `timeframes=None` → берутся `primary_timeframes`
целиком.

**При каких условиях:**

- `start()` — в main.py после настройки
- `stop()` — при shutdown

---

# 2.8 scheduler/scanner.py — Цикл сканирования

**Что делает (полный пайплайн):**

**Шаг 1 — Cooldown:** проверка `_last_signal_time[{symbol}_{timeframe}]`. Если
дельта < `SIGNAL_COOLDOWN_MINUTES` — возврат `None`.

**Шаг 2 — Сбор данных:** `exchange_client.fetch_ohlcv()` →
`indicator_engine.calculate()` → `IndicatorValues`. При None — возврат.

**Шаг 3 — Оценка:** `signal_engine.evaluate(ind)`. Если `NO_SIGNAL` — возврат.

**Шаг 4 — Подтверждение на 15M:** только если `confirm_timeframe != timeframe`:

- Загружаем 15M, оцениваем тем же engine.
- Если направление 15M **не совпадает** с основным → сигнал отклоняется.
- Если совпадает → `entry_price = close на 15M`, в `reasons` пишется
  «✅ Подтверждение на {confirm_tf}», `confirmed_on_lower_tf = True`.
- Если 15M-данные не получились — подтверждение пропускается с warning,
  `entry_price = result.close`, `confirmed_on_lower_tf = False`.

⚠️ Подтверждение работает **только** в scanner. В меню (`_do_full_analysis`)
сигнал считается без 15M — выводимая «оценка» может отличаться от того, что
прислал бы scheduler.

**Шаг 5 — Контекстное обогащение (если `CONTEXT_ENABLED`):**

- `await asyncio.wait_for(context_engine.get_snapshot(symbol), timeout=10.0)`
- `context_scorer.score()` → `ContextVerdict`
- Если `CONTEXT_BLOCK_ON_BLOCKED=True` и вердикт `BLOCKED` → отмена сигнала.
- Если фактический `verdict` ниже `CONTEXT_MIN_VERDICT` (по рангу
  `BLOCKED<CONFLICTED<WEAK<CONFIRMED`) → отмена сигнала.
- Снимок контекста сохраняется в БД **дважды**: до `save_signal` (с `signal_id=None`)
  и после (с реальным `signal_id`). Дубль фиксируется намеренно — для журналов.

**Шаг 6 — Сохранение в БД:** `db.save_signal(..., confirmed=confirmed_on_lower_tf)`.

**Шаг 7 — Cooldown:** `_set_cooldown(symbol, timeframe)` — фиксируется в
`_last_signal_time` (in-memory, без персистентности — после рестарта обнуляется).

**Шаг 8 — Уведомление:** `result.entry_price = entry_price`;
`await notify_callback(result, context_verdict)`.

**Масштабирование:**

- `run_scan_cycle(notify, timeframes=None)` обходит все символы × переданные TF
  параллельно (`asyncio.gather`).
- Сигналы считаются: `signals_found / total_tasks`.

**При каких условиях:**

- Вызывается из `_scan_job()` по расписанию (со своим списком TF).
- Вызывается из `cmd_scan()` (ручной запуск админом, без явного списка TF).
- Каждый символ × таймфрейм — отдельная корутина.
