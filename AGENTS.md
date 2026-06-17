# AGENTS.md — Trading Signal Bot

## Quick start

```bash
cp .env.example .env # fill in required vars
python -m venv .venv && source .venv/bin/activate # .venv\Scripts\activate on Windows
pip install -r requirements.txt
python main.py
```

Docker: `docker-compose build && docker-compose up -d`

## Tests

```bash
pytest -v # all
pytest tests/test_signal.py -v # one file
```

No `pip install -e .` — every test file does `sys.path.insert(0, root)`. `asyncio_mode = auto`
in `pytest.ini`; use `@pytest.mark.asyncio` on async tests.

## Plan & architecture

`plan/00index.md` is the entry point — full module tree, singletons, and pipeline live in
`plan/01-architecture.md`, `plan/07-scheduler.md`, `plan/11-pipeline.md`. Update those files
when behavior changes, not this one.

## Signal logic

- **4 of 6** conditions required: Supertrend, EMA alignment, EMA cross/pos, RSI, MACD, Volume.
- ADX < `adx_min` (default 20) → flat → `NO_SIGNAL` (hard filter, not a counted criterion).
- Volume contributes to **both** buy and sell score — boosts each equally, so the relative
  margin still decides the winner.
- Confirmation on `CONFIRM_TIMEFRAME` (default `15m`) only when it differs from the primary TF;
  mismatch → reject. `Signal.confirmed` records the real outcome.
- Cooldown per `symbol_timeframe` is `SIGNAL_COOLDOWN_MINUTES` (default 45), in-memory only —
  resets on restart.
- Context gate: `CONTEXT_BLOCK_ON_BLOCKED` rejects BLOCKED; `CONTEXT_MIN_VERDICT` is a rank
  gate (`BLOCKED < CONFLICTED < WEAK < CONFIRMED`). Default `WEAK`. Empty value disables the gate.

## Scheduler

- `scan_all_tfs` (cron `:02, :17, :32, :47`) → `run_scan_cycle()` over all `primary_timeframes`.
- Каждые 15 минут сканируются все таймфреймы (1h, 4h).
- Cooldown 45 мин защищает от дублей.
- `cmd_scan` (admin `/scan`) → `run_scan_cycle()` over all `primary_timeframes`.

## Project-specific gotchas

- **Telegram HTML**: `parse_mode=ParseMode.HTML` requires `html.escape()` on every dynamic
  substring — bare `<` (e.g. `ADX < 20`) crashes Telegram's parser. `_do_full_analysis` re-escapes
  on `BadRequest`.
- **pandas-ta columns**: Supertrend → `SUPERT_…` / `SUPERTd_…`; ADX → `ADX_…`, `DMP_…`, `DMN_…`.
  `indicators/engine.py` resolves them dynamically; verify prefixes on pandas-ta upgrades.
- **`exchange_client.fetch_ohlcv` drops the last candle** (`df.iloc[:-1]`) to avoid signalling
  off an open bar.
- **Context fetcher singleton state**: `_fng_cache`, `_trending_cache`, `_rss_cache`,
  `_last_oi[symbol]`. Tests should instantiate a fresh `ContextFetcher` / `ContextEngine`
  rather than reuse the module-level singletons.
- **`main.py` adds project root to `sys.path`** — running submodules without it will fail
  sibling imports.

## Required `.env`

See `plan/14-env-config.md` for the full list. Minimum:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_ID=
SYMBOLS=BTC/USDT,ETH/USDT
PRIMARY_TIMEFRAMES=1h,4h
BINANCE_API_KEY=
BINANCE_API_SECRET=
```
