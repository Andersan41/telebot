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
