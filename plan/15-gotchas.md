# 7. Известные особенности (gotchas)

## Indicator / signal layer

1. **Последняя свеча удаляется** (`df.iloc[:-1]`) перед расчётом индикаторов —
   защищает от ложных сигналов на ещё открытой свече.
2. **ADX < `adx_min`** — безусловный фильтр флэта: `NO_SIGNAL` без анализа остальных условий.
3. **Score 4/6** — минимальный порог. Реально `buy_score` / `sell_score` считают
   5 уникальных условий + Volume (попадает в оба score). Максимум каждой
   стороны — 6.
4. **Volume — нейтральный усилитель**: добавляется и в BUY-, и в SELL-список
   одновременно. Никогда не пропускает обе стороны через порог, но влияет
   только на перевес.
5. **15M-подтверждение** работает **только в scanner**. Меню `_do_full_analysis`
   показывает сигнал без 15M-фильтра — результат может расходиться с тем, что
   реально опубликовал бы scheduler.

## Cooldown / scheduler

6. **Cooldown 60 мин** хранится `in-memory` (`_last_signal_time: dict`) — после
   рестарта бота cooldown обнуляется. Ключ: `symbol_timeframe`, у каждого ТФ
   свой счётчик.
7. **Cron-джобы** теперь параметризованы: `hourly_scan` сканирует только `["1h"]`,
   `4h_scan` — только `["4h"]`. `run_scan_cycle` принимает `timeframes`
   аргументом, при `cmd_scan` без аргумента — берутся все `primary_timeframes`.

## Context module

8. **Funding Rate** идёт прямым HTTP-запросом на `fapi/v1/premiumIndex` (поле
   `lastFundingRate`). Это публичный futures-эндпойнт, не зависит от ccxt
   spot-инстанса.
9. **OI delta** считается в `fetcher.fetch_open_interest` относительно
   предыдущего наблюдения per-symbol (in-memory). На первом запросе после старта
   процесса дельта = 0.0 — это намеренно, нет истории.
10. **CONTEXT_MIN_VERDICT** работает как ранговый гейт
    (`BLOCKED < CONFLICTED < WEAK < CONFIRMED`). Пустая строка или неизвестное
    значение → гейт отключён. По умолчанию `WEAK` — CONFLICTED-сигналы
    отсекаются вместе с BLOCKED.
11. **News sentiment** аккумулируется в локальный список после `asyncio.gather`
    и сворачивается в средневзвешенный по количеству статей score. Порядок
    завершения CryptoPanic и RSS на итог больше не влияет.
12. **RSS без API-ключа** работает всегда; CryptoPanic — только с ключом.
13. **OI/L-S/Funding** идут на `fapi.binance.com` напрямую через aiohttp.
    `defaultType=spot` относится только к ccxt-клиенту OHLCV.

## Конфиг / БД / прочее

14. **Параметры индикаторов** жёстко заданы в `TradingConfig` dataclass и **не
    управляются через .env**. Изменение требует правки кода.
15. **`Signal.confirmed`** теперь отражает реальный результат 15M-фильтра
    (`True` только если 15M подтвердил сигнал, иначе `False`).
16. **Контекстный snapshot пишется дважды**: до `save_signal` (signal_id=None)
    и после (с id). Это намеренный журнал, не баг. Обе записи происходят
    **только если сигнал прошёл** BLOCKED / `CONTEXT_MIN_VERDICT` (`scanner.py:111-123`
    делает `return None` до сейва). При таймауте контекста (`asyncio.TimeoutError`,
    `scanner.py:129`) сейвов нет вообще — `context_verdict` остаётся `None`.
17. **`Database.__init__`** автоматически создаёт `./data/` (для SQLite).
18. **Только spot-рынок** для OHLCV: ccxt-клиент создан с
    `options={"defaultType": "spot"}`. OI/L-S/Funding берутся отдельно по HTTP.
19. **Graceful shutdown** в `main.py`: `scheduler.stop()` → `exchange_client.close()`
    → `app.updater.stop()` (если запущен) → `app.stop()` → `app.shutdown()`.
20. **`drop_pending_updates=True`** в polling — pending update'ы при старте
    игнорируются (например, накопленные команды).
