# FINAL MASTER FIX DOCUMENT FOR QWEN3 3.6 — CRYPTO BOT

Версия: FINAL PRODUCTION EDITION

Основано на:
- bot_audit.md
- check.md
- bot_fix2.md
- bot_fixes_for_qwen3.md
- production review comments
- async/performance review

ЦЕЛЬ:
- исправить production-critical ошибки;
- стабилизировать async/network слой;
- улучшить signal quality;
- уменьшить false signals;
- уменьшить late entries;
- снизить API overload;
- повысить production stability;
- подготовить бота к стабильной long-runtime работе.

---

# ROLE FOR QWEN3

Ты — senior Python architect, senior async engineer,
senior quantitative crypto developer и production reliability engineer.

НЕ ДЕЛАТЬ:
- rewrite всей архитектуры;
- удаление risk-management;
- полную смену стратегии;
- mock fixes;
- pseudo-code;
- blocking I/O;
- агрессивный refactor до стабилизации.

ДЕЛАТЬ:
- production-safe fixes;
- async-safe implementation;
- None-safe code;
- retry-safe networking;
- gradual signal quality improvements;
- сохранить текущую архитектуру.

---

# GLOBAL RULES

1. Перед изменением функции — читать её полностью.
2. После каждого FIX:
   - проверять syntax;
   - запускать тест;
   - проверять scanner logs.
3. После каждого блока:
   - объяснить что было сломано;
   - как исправлено;
   - как протестировать;
   - side effects;
   - влияние на signal quality.
4. Не удалять существующий risk-management.
5. Не ломать async pipeline.
6. Все fixes должны быть:
   - async-safe;
   - None-safe;
   - NaN-safe;
   - retry-safe.
7. Не делать massive refactor до стабилизации ядра.

---

# PRIORITY 1 — CRITICAL PRODUCTION FIXES

## FIX C3 — evaluate() signature mismatch

Файл:
strategy/signal_engine.py

ПРОБЛЕМА:
scanner.py передаёт:

```python
order_blocks=_order_blocks
```

но evaluate() не принимает order_blocks.

Это вызывает:
- silent logic corruption;
- partial trigger failures;
- возможный TypeError;
- order blocks не участвуют в signal logic.

ИСПРАВЛЕНИЕ:

```python
# FIX C3

def evaluate(
    self,
    ind: IndicatorValues,
    regime: Any = None,
    sweeps: Optional[list] = None,
    order_blocks: Optional[list] = None,
    structure: Optional[Any] = None,
) -> SignalResult:
```

---

## FIX C4 — fallback trigger

Файл:
strategy/signal_engine.py

ПРОБЛЕМА:
Если sweeps/structure unavailable,
все сигналы блокируются.

ИСПРАВЛЕНИЕ:

```python
# FIX C4

has_trigger = has_leading_trigger

if not has_trigger and (structure is None or not sweeps):
    if ema_cross_type is not None or macd_cross_type is not None:
        has_trigger = True
        leading_reasons.append(
            "EMA/MACD cross (fallback trigger — structure unavailable)"
        )
```

---

## FIX M6 — indicator None crash

Файл:
scheduler/scanner.py

ИСПРАВЛЕНИЕ:

```python
# FIX M6

async def _get_indicators(symbol: str, timeframe: str):

    df = await exchange_client.fetch_ohlcv(
        symbol,
        timeframe,
        limit=config.trading.candles_limit,
    )

    if df is None:
        logger.warning(f"OHLCV unavailable for {symbol} {timeframe}")
        return None

    if df.empty:
        logger.warning(f"Empty dataframe for {symbol} {timeframe}")
        return None

    ind = indicator_engine.calculate(df, symbol, timeframe)

    if ind is None:
        logger.warning(
            f"Indicator calculation failed for {symbol} {timeframe}"
        )
        return None

    return ind, df
```

---

## FIX M7 — is_buy stale scope bug

Файл:
scheduler/scanner.py

ИСПРАВЛЕНИЕ:

```python
# FIX M7

is_buy = result.signal == SignalType.BUY

if config.derivatives.btc_correlation_enabled:

    try:
        _btc_ctx = await fetch_btc_context()

        if _btc_ctx is not None:

            if is_buy and not _btc_ctx.allows_long():
                logger.debug("BTC context blocks LONG")
                return

            if not is_buy and not _btc_ctx.allows_short():
                logger.debug("BTC context blocks SHORT")
                return

    except Exception as e:
        logger.warning(f"BTC correlation check failed: {e}")
```

---

# PRIORITY 2 — SIGNAL QUALITY FIXES

## FIX M3 — RSI direction-aware scoring

```python
# FIX M3

def _strength_rsi(
    ind: IndicatorValues,
    direction: str,
) -> float:

    rsi = ind.rsi

    if rsi < 30:
        base = 1.0
    elif rsi < 50:
        base = 0.5
    elif rsi < 65:
        base = 0.0
    elif rsi < 70:
        base = -0.5
    else:
        base = -1.0

    return base if direction == "buy" else -base
```

---

## FIX M2 — EMA slope tolerance

```python
# FIX M2

EMA_SLOPE_TOLERANCE = 0.95

if current_spread < prev_spread * EMA_SLOPE_TOLERANCE:
    return reject("EMA slope weakening (>5%)")
```

---

## FIX M1 — momentum entry mode

```python
# FIX M1

MOMENTUM_ENTRY_ENABLED = True
```

Добавить momentum entry:
- Supertrend alignment;
- EMA alignment;
- ADX > 25;
- volume confirmation.

---

## FIX M5 — neutral funding filter

Neutral funding не должен блокировать trade.

Заменить block на logger.debug().

---

# PRIORITY 3 — ASYNC / NETWORK / PERFORMANCE

## FIX A3 — asyncio.gather batching

КРИТИЧЕСКИЙ PERFORMANCE FIX.

Использовать:

```python
results = await asyncio.gather(
    fetch_ohlcv(...),
    fetch_funding(...),
    fetch_open_interest(...),
    fetch_liquidity(...),
    return_exceptions=True,
)
```

ОБЯЗАТЕЛЬНО:
- semaphore;
- rate limiting;
- graceful exception handling.

---

## FIX N1 — universal retry layer

Использовать:
- retries=3
- delay=0.5
- backoff=2

НЕ использовать long retry chains.

---

## FIX N2 — aiohttp shutdown leak

Добавить:

```python
await context_fetcher.close()
```

в graceful shutdown.

---

## FIX N3 — Windows asyncio compatibility

```python
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(
        asyncio.WindowsSelectorEventLoopPolicy()
    )
```

---

## FIX N4 — aiohttp version pinning

requirements.txt:

```text
aiohttp==3.9.5
```

Удалить:

```text
aiohappyeyeballs
```

---

## FIX A2 — BTC/ETH context caching

Использовать:

```python
BTC_CTX_TTL = 60 * 60
```

НЕ использовать 4h TTL.

---

## FIX E1 — ETH correlation filter

Добавить ETH directional filter:
- ETH bearish → block LONG;
- ETH bullish → block SHORT.

---

# PRIORITY 4 — SIGNAL IMPROVEMENTS

## FIX S3 — candle close confirmation

Использовать candle close confirmation,
не wick breakout.

---

## Telegram retry

Добавить retry для Telegram notifier.

---

## Circuit breaker

Добавить pause после серии losses.

---

# PARAMETER OPTIMIZATION

EMA:

15m:
- current: 9/21/50
- recommended: 20/50/200

1h:
- current: 9/21/50
- recommended: 21/55/200

4h:
- current: 9/21/50
- recommended: 21/55/200

SUPER TREND:
- multiplier 1h:
  3.0 -> 2.5

RSI:
- bull_min:
  50 -> 55

ATR:
- low threshold:
  1.0% -> 0.8%

- high threshold:
  4.0% -> 5.0%

VOLUME:
- volume_factor:
  1.2 -> 1.5

---

# PRODUCTION EXECUTION ORDER

DAY 1–2:
1. FIX C3
2. FIX M6
3. FIX M7
4. FIX C4

DAY 3–7:
5. FIX M3
6. FIX M2
7. FIX M1
8. FIX M5
9. FIX N2
10. FIX N1
11. FIX A3

WEEK 2:
12. FIX N3
13. FIX N4
14. FIX S3
15. FIX A2
16. FIX E1
17. Telegram retry
18. Circuit breaker

---

# SCANNER REFACTOR

НЕ ДЕЛАТЬ ДО СТАБИЛИЗАЦИИ.

Рекомендуемая структура:

scheduler/
  scanner.py
  pipeline/
    fetch_stage.py
    analysis_stage.py
    signal_stage.py
    filter_stage.py
    risk_stage.py

---

# FINAL GOAL

После исправлений бот должен:

- стабильно работать async;
- переживать network failures;
- не пад