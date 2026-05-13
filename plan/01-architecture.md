# 1. Архитектура (общая схема)

```
main.py (точка входа, async event loop)
 ├── config/         (.env → dataclass singleton, loguru)
 ├── data/           (ccxt async → OHLCV DataFrame)
 ├── indicators/     (pandas-ta: 6 индикаторов)
 ├── strategy/       (7 критериев → BUY/SELL/NO_SIGNAL)
 ├── scheduler/      (APScheduler cron + scanner цикл)
 ├── context/        (внешние источники: F&G, CoinGecko, Binance, новости)
 ├── bot/            (Telegram: команды, меню, нотификации)
 └── storage/        (SQLAlchemy async → SQLite)
```

### Ключевые принципы

- Все компоненты — синглтоны (один instance на весь процесс)
- Полностью асинхронный (asyncio, ccxt async, aiosqlite)
- `.env` → dataclass Config (читается при импорте `config/settings.py`)
- Цикл обработки: **Fetch → Calculate → Evaluate → Confirm → Enrich → Save → Notify**

### Сопутствующее

- `tests/` содержит pytest-набор: `test_architecture.py`, `test_signal.py`,
  `test_indicators.py`, `test_scanner.py`, `test_context.py`, `test_database.py`,
  `test_exchange_client.py`, `test_notifier.py`, `test_main.py`, `test_config.py`.
- В корне есть `AGENTS.md` (быстрый бриф для AI-агентов) и
  `CONTEXT_ENRICHMENT_PLAN.md` (исходный design контекстного модуля).
