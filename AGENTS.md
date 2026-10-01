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

## Signal logic (new pipeline — scan_symbol_v2)

**Architecture:** Pattern Engine → Feature Builder → Probability Engine → Risk Engine

- **Layer 1 — Pattern Engine** (`strategy/pattern_engine.py`): Pure ICT pattern detection.
  Setup = trigger (BOS or sweep) + confirmation (OB or FVG). No indicators, no scoring.
- **Layer 2 — Feature Builder** (`strategy/feature_builder.py`): Collects ~35 raw features
  into a flat vector (ICT pattern, market structure, volume, indicators, MTF, context, risk).
  No scoring, no blocking — just data.
- **Layer 3 — Probability Engine** (`strategy/probability_engine.py`): Estimates P(TP),
  expected RR, profit factor. Rules-based fallback; ML (XGBoost/RandomForest) replaces
  rules once 100+ historical outcomes are collected.
- **Layer 4 — Risk Engine** (`risk/engine.py`): Capital protection only. Hard gates:
  R:R minimum, SL absolute limits, portfolio risk, max active signals. Position sizing
  via Kelly criterion with volatility adjustment.

**Old pipeline** (`scan_symbol`) still exists for backward compatibility.
`run_scan_cycle()` calls `scan_symbol_v2()`.

- Cooldown per `symbol_timeframe` is `SIGNAL_COOLDOWN_MINUTES` (default 45), in-memory only —
  resets on restart.
- Context never blocks: `ContextScore` provides a score [-1, 1] for the Probability Engine.
- BTC/ETH correlation removed as gates — become secondary features.
- 15m confirmation TF removed entirely.
- **Audit logging**: Every BLOCKED/PASS gate in `scan_symbol_v2` writes to `signal_audit_log`
  with structured `reason_code` (50+ codes in `storage/audit_reasons.py`). 35 audit calls
  cover all pipeline gates. `features_snapshot` stores JSON feature vector at signal time.
  `config_version` tracks config changes. `docs/hypotheses.md` tracks all parameter changes.
- **HTF Bias V2** is ON by default (`config.htf_bias_v2 = True`). A/B validated:
  PF 1.10→1.28, WR 29.6%→31.1%, PnL x2.1 on 90d/1h BTC+ETH.
  Blocks buy continuations against bearish HTF bias (W1→D1→H4→H1 EMA).
- **Premium/Discount zones** are OFF (`config.premium_discount = False`). A/B showed
  they hurt performance (PF 1.28→0.91). Revisit after 500+ live trades with v2.
- **Breakout Quality** (`liquidity/breakout_quality.py`) distinguishes AMD stop-hunt from a
  real breakout: close beyond the settled range boundary + body portion + volume + OI
  vs. a wick-pierce fake break. Soft gate by default (`breakout_quality_hard_gate=False`,
  shadow log only). Wired in `scan_symbol_v2` Phase 1.41; OI via
  `context_fetcher.fetch_open_interest`. Config: `BREAKOUT_QUALITY_*`.
- **HTF POI** (`strategy/htf_poi.py`): Multi-timeframe Points of Interest.
  Detects OB/FVG on D1, H4, W1 and checks proximity to current price.
  If price near HTF POI → SL anchored to HTF structure level for better RR.
  Integrated in `scan_symbol_v2` Phase 1.5; SL override in `TradeEngine.build_trade_plan()`.
- **Sweep-only rescue (H-016)** (`strategy/pattern_engine.py`): sweep без MSS, когда
  continuation тоже отклонён → слабый reversal (направление от `sweep_type`),
  ТОЛЬКО при наличии OB/FVG зоны (guard), иначе `sweep_dead_end_no_zone`.
  Sweep edge в probability: +3.0 с MSS, +1.5 без. `_CONFIG_VERSION=12`.
  Обоюдный фейл логирует комбинированную причину `"{reversal} + {continuation}"`.
- **ATR entry proximity (H-016)**: `resolve_proximity_pct = max(ENTRY_PROXIMITY_PCT,
  atr_pct * ENTRY_PROXIMITY_ATR_MULT)` — применяется в обеих точках EntryTrigger
  (Phase 1.6 и 4.5). Env: `ENTRY_PROXIMITY_PCT=0.3`, `ENTRY_PROXIMITY_ATR_MULT=0.5`.

## Hypotheses tracking

`docs/hypotheses.md` — every parameter change or config drift is logged as a hypothesis entry
(H-001, H-002, ...) before live data collection. Baseline measurements from
`scripts/measure_rejection_rate.py` record current pipeline behavior for comparison.

Key baselines (post H-003 fix, 500 candles 1h):
- Displacement rate: 0.6–4.8% (low, not a major filter)
- Dominant rejection: "reversal: no MSS (strong CHoCH)" — 45–63%
- Continuation dominates detected setups (69–91%)
- OB detection extremely low (0–5.8%)

## Scheduler

- `scan_all_tfs` (cron `:02, :17, :32, :47`) → `run_scan_cycle()` over all `primary_timeframes`.
- Каждые 15 минут сканируются все таймфреймы (1h, 4h).
- `PAUSED_TIMEFRAMES` (env, H-018) исключает TF из scan/shadow циклов — сейчас `1h`
  (v12 1h: 2TP/7SL, review после ~100 закрытых сделок).
- Cooldown 45 мин защищает от дублей.
- `cmd_scan` (admin `/scan`) → `run_scan_cycle()` over all `primary_timeframes`.
- `price_alert_loop` (`scheduler/price_alerts.py`, каждые `PRICE_ALERT_CHECK_SECONDS=15`)
  → веб-алерты на цену (вкладка Alerts): касание уровня → `send_price_alert` админу в
  личку, one-shot гашение. Тесты (`tests/test_price_alerts.py`) берут `db` через прокси —
  `test_architecture.py::test_db_singleton` удаляет `storage.database` из `sys.modules`
  и статический import на уровне модуля отвязался бы от нового синглтона.
- `audit_resolver_loop` (`scheduler/audit_resolver.py`, каждые `AUDIT_RESOLVER_INTERVAL_SECONDS=1800`)
  → теневые outcome в `signal_audit_log`: blocked-кандидаты с полным планом
  (`hyp_entry/sl/tp` + `synthetic_plan=1`, пишутся через `scanner._hyp_plan`) симулируются
  first-touch (SL-приоритет в баре, входной бар пропускается) → `outcome` (HIT_TP/HIT_SL/
  EXPIRED), `outcome_r`, `mae_r ≤ 0 ≤ mfe_r`. Основа A/B по порогам (min_p_tp и т.п.).
  Бэклог: `scripts/backfill_audit_hyp.py` (гипотетика из meta → колонки).

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
- **`config_version`**: Bump `_CONFIG_VERSION` in `scheduler/scanner.py` when any config
  threshold changes (e.g. min_rr_ratio, volatility limits, SL bounds, max_active_signals).
  Audit logs use this to distinguish signals under different configs for A/B analysis.
- **daily_limits PnL is CAPITAL %, not price %** (H-017): `record_trade_closed()` expects
  equity-% — callers convert via `outcome_tracker._capital_pnl_pct()` (R × risk_pct).
  Passing raw price move % falsely trips `PROFIT_TARGET_DAILY_PCT` (NEAR 25.09: +11%
  price → 6,450 blocks/day). Thresholds `MAX_DRAWDOWN_DAILY_PCT` / `PROFIT_TARGET_DAILY_PCT`
  are capital %.
- **`positions` close metrics use the ORIGINAL SL**: `actual_rr`/`expected_rr` are computed
  from `signal.sl` (never from `positions.stop_loss` — it mutates on BE/trailing, e.g. NEAR
  SL 4.242 → 4.577). `quantity` is physically always 1.0, so `pnl_usdt` is per-1-unit, not
  per-real-size. Backfill for old rows: `scripts/backfill_position_metrics.py`.
- **Single-instance lock is an OS byte-range lock, not a PID check** (`main.py:acquire_lock`):
  `msvcrt.locking` (Windows) / `fcntl.flock` (POSIX) on `.trading_bot.lock` at offset 1024,
  held by an open fd until exit — the kernel releases it if the process dies, so a stale
  file with a dead PID never blocks a restart. The file is gitignored (was tracked: a
  `git checkout` could resurrect a foreign PID) and is never deleted on exit (unlink would
  race inode identities). Path is overridable via `TRADING_BOT_LOCK_FILE` — tests must set
  it, otherwise running `tests/test_main.py` locks/releases the real file of the live bot.
  Note: instances started before this change hold no OS lock, so the guard cannot see them.
- **Position R-ladder is measured from `ManagedPosition.initial_risk`** (entry → original SL),
  never from the live SL: breakeven sets SL = entry, so live risk is 0 and the old formula
  collapsed 2R/3R/4R targets to the entry price — the whole ladder fired in one bar as
  `TP3_FULL` ("✅ Тейк Профит") while `signal.tp` was never touched (NEAR/USDT 1h
  signal_id=8, 25.09.2026; 5 such rows in `positions`). Telegram labels for `TP*_FULL`
  now show the R-level; `_normalize_close_reason` still maps them to `HIT_TP` for stats.
- **SQLite runs in WAL with `busy_timeout=30s`**: `Database.init()` sets `journal_mode=WAL`
  once (persistent), `configure_sqlite_engine()` sets `busy_timeout`/`synchronous` per
  connection, and `save_decision_trace` / `create_audit_entry` retry on `database is locked`
  (`retry_on_db_lock`, `DB_LOCK_RETRY_*` env). A scan cycle is ~150 parallel tasks writing
  hundreds of rows — never add a DB write path that opens its own engine, and copy the DB
  with the sqlite backup API (as `/exportdb` does), never `shutil.copy` (misses `-wal`).
  Ad-hoc analytics scripts reading `data/signals.db` should pass `timeout=` to
  `sqlite3.connect`.

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
