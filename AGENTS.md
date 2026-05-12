# AGENTS.md — Trading Signal Bot

## Quick start
```bash
cp .env.example .env   # fill in TELEGRAM_BOT_TOKEN, BINANCE_API_KEY/SECRET
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
python main.py
```
Or Docker: `docker-compose up -d`

## Tests
```bash
pytest -v              # all
pytest tests/test_signal.py -v   # single file
```
No `pip install -e .` — every test file does `sys.path.insert(0, root)` at the top.
Tests use `pytest.mark.asyncio` with `asyncio_mode = auto` (pytest.ini).

## Architecture
```
main.py                 # entrypoint: async event loop, starts bot + scheduler
config/settings.py      # .env → dataclass config (singleton: config)
config/logger.py        # loguru setup (called at import time)
data/exchange_client.py # ccxt async → OHLCV DataFrame (singleton: exchange_client)
indicators/engine.py    # pandas-ta: EMA, RSI, MACD, ADX, ATR, Supertrend (singleton: indicator_engine)
strategy/signal_engine.py  # BUY/SELL/NO_SIGNAL logic, SL/TP calc (singleton: signal_engine)
scheduler/scanner.py    # scan symbols × timeframes, confirm on 15m, cooldown (asyncio.gather)
scheduler/tasks.py      # APScheduler: hourly + 4h cron jobs
bot/handlers.py         # Telegram command handlers + menu callbacks
bot/menu.py             # inline keyboard navigation
bot/notifier.py         # send signals to Telegram channel
storage/database.py     # SQLAlchemy async → SQLite (singleton: db)
```

## Key patterns
- **Singletons everywhere**: `config`, `exchange_client`, `indicator_engine`, `signal_engine`, `db`
- **Config**: all via `.env` + dataclasses in `config/settings.py`
- **Logging**: loguru, configured by importing `import config.logger` (done in main.py)
- **Async**: all I/O is async (ccxt, aiosqlite, telegram-bot v20)
- **Signal logic**: 4 of 7 conditions required; ADX < 20 = flat = no signal; 15m confirmation required

## Gotchas
- **Telegram HTML**: when sending with `parse_mode=ParseMode.HTML`, escape `<` and `>` in dynamic text with `html.escape()` or `&lt;`/`&gt;`. Telegram's parser will crash on bare `<` in plain text (e.g. "ADX < 20").
- **pandas-ta column naming**: Supertrend columns start with `SUPERT_` (value) and `SUPERTd_` (direction); ADX columns start with `ADX_`, `DMP_`, `DMN_`. The engine handles this dynamically.
- **`exchange_client.fetch_ohlcv` drops the last candle** (unresolved) before returning.
- **`main.py` adds root to `sys.path`** — don't run files from subdirectories without this.
- **`.gitignore` excludes `.env`, `data/*.db`, `logs/*.log`** — these are created at runtime.
