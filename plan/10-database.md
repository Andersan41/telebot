# 2.13 storage/database.py — База данных

**Что делает:**

- SQLAlchemy 2.0 async engine (aiosqlite)
- **3 таблицы:**

1. **`signals`**:
    - id (PK), symbol, timeframe, signal_type (BUY/SELL), close_price
    - sl, tp, score, reasons (Text, \n-joined)
    - confirmed (bool), created_at, sent_at

2. **`bot_settings`**:
    - key (PK), value (Text), updated_at

3. **`context_snapshots`**:
    - id (PK), symbol (indexed), signal_id (FK → signals.id, nullable)
    - timestamp, verdict, confidence, score
    - fear_greed, funding_rate, long_short_ratio, open_interest_delta, news_sentiment
    - raw_json (Text)

**Методы:**

- `save_signal()` — сохраняет сигнал, возвращает модель с id. **`sent_at`
  ставится `datetime.now(timezone.utc)` безусловно при создании
  (`database.py:99`)** — отдельного признака «сохранён, но ещё не отправлен»
  у строки нет; колонка фиксирует время записи, а не реальной отправки в TG.
- `get_last_signal(symbol, timeframe)` — последний сигнал по паре
- `get_recent_signals(limit)` — N последних
- `get_setting(key, default)` / `set_setting(key, value)` — настройки
- `save_context_snapshot()` — сохраняет снимок контекста

**При каких условиях:**

- `Database.__init__` создаёт каталог `./data/` при первом импорте модуля
  (так что путь по умолчанию `sqlite+aiosqlite:///./data/signals.db` работает
  «из коробки»).
- `init()` — при старте main.py (создание таблиц).
- Остальные — вызовы из scanner.py и handlers.py.

`scanner.scan_symbol` передаёт `confirmed=True` только если 15M-подтверждение
действительно прошло. При `confirm_timeframe == primary_timeframe` или при
недоступности 15M-данных в БД пишется `confirmed=False`.

## Storage gap для CoinGecko-полей контекста

`ContextSnapshotModel` (`database.py:42`) хранит из контекста только
`fear_greed`, `funding_rate`, `long_short_ratio`, `open_interest_delta`,
`news_sentiment` + полный JSON в `raw_json`. Отдельных колонок для
`price_change_24h/7d`, `total_volume`, `market_cap_rank` (CoinGecko) **нет**.
Если эти поля нужны для последующего анализа в SQL — придётся либо парсить
`raw_json`, либо добавить колонки и миграцию.
