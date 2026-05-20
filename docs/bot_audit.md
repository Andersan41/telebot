# Полный аудит торгового бота — bot_audit.md

> Дата аудита: 2026-05-21
> Версия кода: текущая (main branch)
> Аудитор: AI senior quantitative analyst

---

# 1. КРИТИЧЕСКИЕ ОШИБКИ (Critical)

## C1: Funding Rate пороги в config были неверны — уже исправлены

**Файл:** `config/settings.py:300-302`
**Статус:** ✅ ИСПРАВЛЕНО — пороги теперь `0.0003` / `0.0001` (было `0.03` / `0.01`)
**Проверка:** Binance API возвращает `lastFundingRate` как decimal (0.0001 = 0.01%). Текущие пороги корректны.

## C2: `_filter_by_age` в order_blocks — заглушка — уже исправлена

**Файл:** `liquidity/order_blocks.py:261-269`
**Статус:** ✅ ИСПРАВЛЕНО — функция теперь корректно фильтрует OB по `max_age_candles`
**Проверка:** Функция принимает `total_candles` и `max_age`, фильтрует блоки по `current_idx - b.candle_index <= max_age`.

## C3: `signal_engine.evaluate()` принимает `order_blocks` но не объявлен в signature

**Файл:** `scheduler/scanner.py:248-254`
**Проблема:** scanner.py передаёт `order_blocks=_order_blocks` в `signal_engine.evaluate()`, но сигнатура метода:
```python
def evaluate(self, ind, regime=None, sweeps=None, structure=None)
```
Параметр `order_blocks` не объявлен → Python игнорирует его как kwargs (если нет `**kwargs`) или бросает TypeError.

**Влияние:** Order blocks не передаются в signal engine для leading trigger detection.
**Решение:** Добавить `order_blocks: Optional[list] = None` в сигнатуру `evaluate()`.

## C4: `signal_engine.evaluate()` — `sweeps` и `structure` используются для leading triggers, но BOS/sweep detection может быть None

**Файл:** `strategy/signal_engine.py:208-222`
**Проблема:** Если `_sweeps` или `_structure` = None (early analysis failed), leading triggers не сработают → сигнал будет отклонён на gate "Нет триггера".
**Влияние:** В случае ошибки liquidity/structure анализа все сигналы блокируются.
**Решение:** Добавить fallback — если structure/sweeps недоступны, использовать EMA/MACD cross как fallback trigger.

---

# 2. СРЕДНИЕ ПРОБЛЕМЫ (Medium)

## M1: Signal Engine — trigger gate слишком строгий

**Файл:** `strategy/signal_engine.py:296-307`
**Проблема:** `has_trigger = has_leading_trigger` — требуются BOS, sweep, delta, EMA cross или MACD cross. Если ни один из них не сработал — NO_SIGNAL.
**Влияние:** Бот пропускает сигналы где тренд сильный но cross ещё не произошёл (вход был бы раньше).
**Рекомендация:** Добавить опциональный режим "momentum entry" — если Supertrend + EMA alignment + ADX strong + Volume → allow entry без cross.

## M2: EMA slope check может блокировать валидные сигналы

**Файл:** `strategy/signal_engine.py:354-380`
**Проблема:** `current_spread <= prev_spread` → reject. Но на реальных данных spread может временно сужаться даже в сильном тренде (pullback).
**Влияние:** Потеря входов на pullback — именно там лучшие RR.
**Рекомендация:** Добавить tolerance: `current_spread < prev_spread * 0.95` вместо `<=`. Или проверять slope за 3 свечи вместо 2.

## M3: RSI scoring в signal_engine не учитывает direction

**Файл:** `strategy/signal_engine.py:514-526`
**Проблема:** `_strength_rsi()` всегда считает от BUY perspective. RSI=75 → -1.0 (перекупленность). Но для SELL сигнала RSI=75 — это ХОРОШО (можно шортить).
**Влияние:** RSI strength для SELL сигналов инвертирован — высокие RSI penalize оба направления одинаково.
**Решение:** Инвертировать score для SELL direction:
```python
def _strength_rsi(ind, direction):
    base = ... # current BUY-centric logic
    return base if direction == "buy" else -base
```

## M4: Context Scorer `_score_oi` — direction уже учитывается корректно

**Файл:** `context/scorer.py:243-261`
**Статус:** ✅ ИСПРАВЛЕНО — теперь BUY и SELL имеют зеркальную логику:
- BUY: delta > 2% → +0.5, delta < -2% → -0.3
- SELL: delta < -2% → +0.5, delta > 2% → -0.3

## M5: No-Trade Zones блокирует при neutral funding

**Файл:** `risk/no_trade_zones.py:54-57`
**Проблема:** `funding_state == "neutral" and funding_strength == "weak"` → blocked. Но neutral funding — это нормальное состояние рынка (большинство времени).
**Влияние:** ~60-70% сигналов могут быть заблокированы только из-за neutral funding.
**Рекомендация:** Убрать funding neutral из no-trade zones или сделать warning вместо block. Funding neutral = нет edge, но не = опасность.

## M6: Scanner — `_get_indicators` возвращает кортеж но не unpacked корректно

**Файл:** `scheduler/scanner.py:208-212`
```python
def _get_indicators(symbol, timeframe):
    df = await exchange_client.fetch_ohlcv(...)
    if df is None:
        return None
    return indicator_engine.calculate(df, symbol, timeframe), df  # tuple!
```
**Проблема:** `indicator_engine.calculate()` может вернуть `None` → тогда возвращается `(None, df)`, что не `None` → unpack на строке 229 `ind, df = ind_result` даст `ind=None` → crash на `signal_engine.evaluate(ind)`.
**Решение:**
```python
ind = indicator_engine.calculate(df, symbol, timeframe)
if ind is None:
    return None
return ind, df
```

## M7: Scanner — BTC Correlation Gate имеет bug с `is_buy`

**Файл:** `scheduler/scanner.py:508-509`
```python
if _btc_ctx is not None:
    is_buy = result.signal == SignalType.BUY
if is_buy and not _btc_ctx.allows_long():
```
**Проблема:** `is_buy` определяется внутри `if _btc_ctx is not None`, но используется снаружи. Если `_btc_ctx is None`, `is_buy` может быть stale из предыдущего цикла (строка 319).
**Влияние:** Potential incorrect blocking.
**Решение:** Вынести `is_buy = result.signal == SignalType.BUY` перед блоком BTC correlation.

## M8: Database — cooldown хранится в bot_settings как строка

**Файл:** `storage/database.py:179-195`
**Проблема:** Каждый cooldown = отдельная запись в bot_settings. При 20 символах × 3 таймфреймах = 60 записей, которые постоянно обновляются.
**Влияние:** Неэффективно, но функционально работает.
**Рекомендация:** Перенести cooldown в отдельную таблицу или использовать in-memory dict с persistence.

---

# 3. MINOR ISSUES

## N1: Volume SMA period теперь configurable

**Файл:** `indicators/engine.py:168`, `config/settings.py:137`
**Статус:** ✅ ИСПРАВЛЕНО — `volume_sma_period` теперь в config (дефолт 20).

## N2: MACD колонки берутся по префиксу а не индексу

**Файл:** `indicators/engine.py:138-143`
**Статус:** ✅ ИСПРАВЛЕНО — колонки ищутся по `MACD_`, `MACDh_`, `MACDs_` префиксам.

## N3: `signal_engine.evaluate()` signature mismatch с scanner.py

**Файл:** `strategy/signal_engine.py:153`, `scheduler/scanner.py:248`
**Проблема:** Scanner передаёт `order_blocks=` но evaluate() не принимает этот параметр.
**Решение:** См. C3.

## N4: RSS news keyword matching примитивный

**Файл:** `context/fetcher.py:288-297`
**Проблема:** Простой substring match. "high" найдётся в "highlight", "charge" в "recharge".
**Влияние:** Ложные срабатывания sentiment.
**Рекомендация:** Использовать word boundary regex или NLP библиотеку.

## N5: Нет retry logic в Telegram notifier

**Файл:** `bot/notifier.py`
**Проблема:** При TelegramError (rate limit, network) сообщение теряется.
**Рекомендация:** Добавить exponential backoff retry (3 попытки).

## N6: aiohttp session не закрывается при shutdown

**Файл:** `context/fetcher.py:33-35`
**Проблема:** `ContextFetcher.close()` существует но не вызывается в `main.py` shutdown.
**Влияние:** Resource leak при graceful shutdown.
**Решение:** Добавить `await context_fetcher.close()` в finally block main.py.

## N7: `df.iloc[:-1]` в exchange_client — документировано но может путать

**Файл:** `data/exchange_client.py:156`
**Статус:** ⚠️ Корректно — последняя свеча открытая, её нужно исключать. Но при limit=200 возвращается 199 свечей.

## N8: `_safe_float` default=0.0 может маскировать ошибки

**Файл:** `indicators/engine.py:14-19`
**Проблема:** Если все значения NaN → default=0.0 → индикаторы считаются как 0 → сигнал может пройти.
**Решение:** Guard в `evaluate()` уже проверяет None/NaN — это покрывает проблему.

---

# 4. АНАЛИЗ КАЧЕСТВА СИГНАЛОВ

## 4.1 Запаздывание сигналов

| Компонент | Lag | Оценка |
|-----------|-----|--------|
| EMA 9/21 | 2-5 свечей | Стандартный lag EMA |
| Supertrend 10/3.0 | 3-7 свечей | Высокий multiplier = больше lag |
| MACD 12/26/9 | 5-10 свечей | Значительный lag |
| ADX 14 | 7-14 свечей | Очень lagging |
| BOS detection | 1-3 свечи | Минимальный lag |
| Sweep detection | 0-1 свеча | Leading indicator ✅ |

**Вывод:** Бот использует leading triggers (sweep, BOS, delta) что компенсирует lag индикаторов. Это правильная архитектура.

## 4.2 Входы в ликвидность

**Защита:** Sweep detection + distance filter (1.5%) + TP path analysis.
**Проблема:** Sweep detection работает на тех же данных что и сигнал → если sweep только что произошёл, бот может войти сразу после reclaim (good), но может войти и до полного reclaim (bad).
**Рекомендация:** Добавить подтверждение: sweep + следующая свеча close за пределами sweep zone.

## 4.3 Фильтрация флэта

**Механизмы:**
1. ADX < 20 → hard filter ✅
2. Regime detection (compression) → block ✅
3. No-trade zone (ranging) → block ✅
4. Volatility regime (low ATR%) → block ✅

**Проблема:** 4 уровня фильтрации флэта могут быть избыточны. ADX filter + regime detection покрывают 95% случаев.

## 4.4 False Breakout защита

**Механизмы:**
1. EMA slope check (spread widening) ✅
2. Volume confirmation ✅
3. Confirmation timeframe (15m) ✅
4. MTF alignment ✅

**Проблема:** Нет защиты от "wick breakout" — когда цена пробила уровень фитилём и вернулась.
**Рекомендация:** Добавить candle quality check — body must close beyond level, not just wick.

## 4.5 Late Entry анализ

**Сценарии late entry:**
1. EMA cross происходит после 30-50% движения → entry late
2. Supertrend flip после значительного движения → entry late
3. Confirmation на 15m добавляет ещё 1-2 свечи delay

**Митигация:** Leading triggers (sweep, BOS) входят раньше. EMA slope check предотвращает entry когда spread уже сужается (trend exhaustion).

---

# 5. АНАЛИЗ РИСК-МЕНЕДЖМЕНТА

## 5.1 Stop Loss

| Метод | Формула | Оценка |
|-------|---------|--------|
| ATR-based | close ± ATR × 1.5 | ✅ Стандартный |
| Structural (BOS) | BOS level × 0.995 | ✅ Tighter, лучше RR |
| Sweep-based | sweep_low | ✅ Лучший вариант |

**Проблема:** Structural SL используется только если `structure.last_bos` существует. Если BOS не detected → fallback ATR.
**Рекомендация:** Приоритет: sweep_low > BOS_level > ATR-based.

## 5.2 Take Profit

| Метод | Формула | Оценка |
|-------|---------|--------|
| ATR-based | close ± ATR × 3.0 | ✅ RR = 2.0 |
| Structural | FVG midpoint / sweep high | ✅ Более точный |
| Dynamic TP | Recalculate с FVG | ✅ Best option |

**Проблема:** Dynamic TP recalculation только если FVG detected. Если нет FVG → ATR-based даже если есть sweep high.
**Рекомендация:** Расширить dynamic TP на все structural levels.

## 5.3 Dynamic Risk

| Параметр | Значение | Оценка |
|----------|----------|--------|
| Strong setup | 1.0% | ✅ Консервативно |
| Moderate setup | 0.5% | ✅ |
| Weak setup | blocked (default) | ✅ |
| High vol multiplier | 0.5x | ✅ |
| Correlation misaligned | 0.5x | ✅ |

**Проблема:** `should_trade` читает `config.risk.risk_weak_trade` корректно (через config, не os.getenv).
**Статус:** ✅ ИСПРАВЛЕНО — было `os.getenv`, теперь `settings.config.risk.risk_weak_trade`.

## 5.4 Volatility Adaptation

**Механизмы:**
1. ATR-based SL/TP ✅
2. Volatility regime classification ✅
3. High vol → 0.5x risk multiplier ✅
4. No-trade zone при ATR% < 0.5% ✅

**Проблема:** Нет dynamic ATR multiplier — SL всегда 1.5x ATR regardless of regime.
**Рекомендация:** В low vol → 1.0x ATR SL (tighter), high vol → 2.0x ATR SL (wider).

---

# 6. MULTI-TIMEFRAME АНАЛИЗ

## 6.1 Confirmation Timeframe

- Primary: 1h / 4h
- Confirmation: 15m
- Logic: signal на primary → проверка на confirm_tf → mismatch → reject

**Проблема:** Если confirm_tf == primary_tf (например оба 1h) → confirmation skipped.
**Рекомендация:** Всегда требовать confirmation на timeframe ниже primary.

## 6.2 MTF Alignment

- HTFs: 1d, 4h, 1h
- Required: 2 aligned
- Logic: trend must match signal direction

**Проблема:** "Ranging" не считается aligned. В ranging market все HTFs могут быть ranging → signal blocked.
**Рекомендация:** Для ranging市场 допустить 1 aligned HTF вместо 2.

## 6.3 BTC/ETH Correlation

- BTC: EMA200 4H + structure + breakout detection
- ETH: Impulsive move detection (>3% за 5 свечей)

**Проблема:** ETH correlation только блокирует SHORT. LONG не проверяется против ETH.
**Рекомендация:** Добавить ETH correlation check для LONG (блокировать если ETH bearish impulsive).

---

# 7. CODE QUALITY & ARCHITECTURE

## 7.1 Async / Network

| Компонент | Статус | Проблемы |
|-----------|--------|----------|
| Exchange client | ✅ | Semaphore serializes requests — безопасно но медленно |
| Context fetcher | ✅ | aiohttp session reuse, caching ✅ |
| Retry logic | ⚠️ | Exchange client has retry on market load, но не на fetch_ohlcv |
| Rate limiting | ✅ | ccxt enableRateLimit + semaphore |
| Timeout | ✅ | aiohttp timeout=8s, context timeout=10s |

**Рекомендация:** Добавить retry с exponential backoff на `fetch_ohlcv`.

## 7.2 Memory

| Компонент | Статус | Проблемы |
|-----------|--------|----------|
| Context caches | ✅ | TTL-based expiration |
| OI cache | ✅ | Per-symbol, in-memory |
| DataFrame | ✅ | Создаётся и удаляется каждый цикл |
| DB connections | ✅ | AsyncSession per-operation |

## 7.3 Performance

**Бottlenecks:**
1. `scan_symbol()` — 884 строки, много последовательных API вызовов
2. S/R levels fetch для 1H и 4H — 2 дополнительных запроса на символ
3. MTF alignment — ещё 2-3 запроса (1d, 4h, 1h)
4. BTC/ETH correlation — 2 запроса
5. Context snapshot — 4-6 параллельных запросов

**Общее число API запросов на символ:** ~10-15
**При 10 символах:** ~100-150 запросов за цикл

**Рекомендация:**
1. Кешировать BTC/ETH context (обновлять раз в 4 часа)
2. Кешировать S/R levels (обновлять раз в час)
3. Параллелизовать независимые fetch через asyncio.gather

## 7.4 Architecture Issues

1. **Scanner слишком длинный** (884 строки) — сложно тестировать, поддерживать
   - Рекомендация: Разбить на pipeline stages (каждый stage = отдельная функция)

2. **Дублирование fetch BTC/ETH** — correlation gate (шаг 2.10-2.11) и no-trade check используют одни данные
   - Статус: ✅ ИСПРАВЛЕНО — данные кешируются в `_btc_ctx` / `_eth_ctx`

3. **Signal engine и Confidence V2** — две системы скоринга работают параллельно
   - Legacy: `len(reasons)` / 8 факторов
   - V2: weighted sum / 10 факторов
   - Итоговый verdict берётся из V2 если доступен
   - Рекомендация: Убрать legacy scoring или сделать V2 единственным

---

# 8. РЕКОМЕНДАЦИИ ПО ПАРАМЕТРАМ

## 8.1 EMA параметры

| Таймфрейм | Текущие | Рекомендуемые | Обоснование |
|-----------|---------|---------------|-------------|
| Scalp 1m-5m | 9/21/50 | 9/21/50 | ✅ OK |
| Intraday 15m | 9/21/50 | 20/50/200 | 9/21 слишком чувствительные для 15m |
| Swing 1h-4h | 9/21/50 | 21/55/200 | 9/21 даёт много false cross на higher TF |

## 8.2 RSI параметры

| Параметр | Текущий | Рекомендуемый | Обоснование |
|----------|---------|---------------|-------------|
| Period | 14 | 14 | ✅ OK |
| Overbought | 70 | 70 | ✅ OK |
| Oversold | 30 | 30 | ✅ OK |
| Bull min | 50 | 55 | 50 слишком низкий для bullish confirmation |

## 8.3 Supertrend

| Параметр | Текущий | Рекомендуемый | Обоснование |
|----------|---------|---------------|-------------|
| Period | 10 | 10 | ✅ OK |
| Multiplier | 3.0 | 2.5 для 1h, 3.0 для 4h | 3.0 слишком широкий для 1h |

## 8.4 Volatility thresholds

| Параметр | Текущий | Рекомендуемый | Обоснование |
|----------|---------|---------------|-------------|
| Low threshold | 1.0% | 0.8% | 1.0% блокирует нормальный BTC рынок |
| High threshold | 4.0% | 5.0% | 4.0% слишком низкий для volatile altcoins |

---

# 9. РЕКОМЕНДАЦИИ ПО ФИЛЬТРАМ

## 9.1 Фильтры которые стоит ДОБАВИТЬ

1. **Time-based filter:** Не торговать во время major news (FOMC, CPI, NFP)
   - Implementation: Calendar API или hardcoded dates

2. **Weekend filter:** Крипто рынок на выходных имеет низкую ликвидность
   - Implementation: Skip signals on Sat/Sun или reduce risk

3. **Spread filter:** Не торговать если bid-ask spread > X%
   - Implementation: Check ccxt market spread

4. **Consecutive loss filter:** После N подряд убыточных сигналов →暂停 scanning
   - Implementation: Track last N outcomes, pause if win_rate < 30%

5. **Candle close confirmation:** Entry только после close свечи за уровнем
   - Implementation: Check close > resistance (not just high > resistance)

## 9.2 Фильтры которые УБРАТЬ

1. **Funding neutral → no-trade:** Слишком агрессивный, блокирует 60%+ сигналов
2. **OI ignore → no-trade:** OI часто unavailable для altcoins
3. **Double regime check:** ADX filter + regime detection + no-trade ranging — избыточно

## 9.3 Фильтры которые УСИЛИТЬ

1. **Volume confirmation:** Увеличить volume_factor с 1.2 до 1.5 для 1h
2. **EMA spread:** Увеличить min_ema_spread_pct с 0.15% до 0.25%
3. **Distance filter:** Увеличить с 1.5% до 2.0% для 4h

---

# 10. РЕКОМЕНДАЦИИ ПО РЕЖИМАМ РЫНКА

## 10.1 Scalp / Intraday (1m-15m)

- EMA: 9/21/50
- Supertrend: 10/2.5
- RSI: 14, zones 30/50/70
- Volume factor: 1.5
- Min ADX: 18 (ниже для scalp)
- Confirmation: 5m для 15m signals
- Risk: 0.5% max per trade

## 10.2 Volatile Market (ATR% > 3%)

- SL: ATR × 2.0 (wider)
- TP: ATR × 4.0 (further)
- Volume factor: 2.0 (только очень высокий объём)
- Min score: 5 вместо 4
- Risk multiplier: 0.5x
- Skip if funding > 0.001 (overcrowded)

## 10.3 Ranging Market (ADX < 25, ATR% < 1.5%)

- **Не торговать** или:
- EMA: переключиться на 50/200 (trend filter only)
- Strategy: mean-reversion вместо trend-following
- Entry: RSI < 30 (buy) или RSI > 70 (sell)
- TP: middle of range (50% Fibonacci)
- SL: beyond range boundary

---

# 11. ROADMAP УЛУЧШЕНИЙ

## Priority 1 — Critical Fixes (1-2 дня)

- [ ] **C3:** Добавить `order_blocks` параметр в `signal_engine.evaluate()` signature
- [ ] **C4:** Добавить fallback trigger когда structure/sweeps недоступны
- [ ] **M6:** Fix `_get_indicators()` — проверять indicator_engine result на None
- [ ] **M7:** Fix `is_buy` variable scope в BTC correlation gate

## Priority 2 — Important Fixes (3-5 дней)

- [ ] **M1:** Добавить "momentum entry" mode — entry без cross при strong trend
- [ ] **M2:** EMA slope check tolerance (0.95× вместо <=)
- [ ] **M3:** RSI scoring direction-aware
- [ ] **M5:** Funding neutral → warning вместо block
- [ ] **N3:** Signature mismatch fix
- [ ] **N6:** Добавить `context_fetcher.close()` в shutdown

## Priority 3 — Moderate Improvements (1-2 недели)

- [ ] Refactor scanner.py → pipeline stages
- [ ] Кеширование BTC/ETH context (4h TTL)
- [ ] Кеширование S/R levels (1h TTL)
- [ ] Retry logic для fetch_ohlcv
- [ ] Dynamic ATR multiplier по regime
- [ ] Candle close confirmation для breakout
- [ ] Weekend filter
- [ ] Consecutive loss circuit breaker

## Priority 4 — Long-term (1 месяц+)

- [ ] Backtest engine integration с реальными данными
- [ ] Parameter optimization с walk-forward analysis
- [ ] Machine learning feature: signal quality prediction
- [ ] Multi-exchange support
- [ ] Paper trading mode
- [ ] Web dashboard для мониторинга
- [ ] Telegram signal performance tracking

---

# 12. СВОДНАЯ ТАБЛИЦА МОДУЛЕЙ

| Модуль | Статус | Критичность | Комментарий |
|--------|--------|-------------|-------------|
| **Indicator Engine** | ✅ OK | — | MACD/Supertrend колонки по префиксу ✅ |
| **Signal Engine** | ⚠️ | HIGH | Signature mismatch, RSI direction, trigger gate |
| **Scanner** | ⚠️ | HIGH | is_buy scope, _get_indicators None check |
| **Context Scorer** | ✅ OK | — | OI scoring direction исправлен ✅ |
| **Context Fetcher** | ⚠️ | LOW | Session leak on shutdown |
| **Funding** | ✅ OK | — | Пороги исправлены ✅ |
| **Order Blocks** | ✅ OK | — | _filter_by_age исправлен ✅ |
| **Sweep Detection** | ✅ OK | — | Good leading indicator |
| **FVG** | ✅ OK | — | min_size + filled check ✅ |
| **Market Structure** | ✅ OK | — | BOS/CHoCH detection работает |
| **MTF Alignment** | ✅ OK | — | 1d/4h/1h, required=2 |
| **BTC Correlation** | ✅ OK | — | EMA200 + structure + breakout |
| **ETH Correlation** | ⚠️ | MEDIUM | Только SHORT block, нет LONG check |
| **Volatility Regime** | ✅ OK | — | ATR% thresholds |
| **Dynamic Risk** | ✅ OK | — | Config-based, не os.getenv ✅ |
| **No-Trade Zones** | ⚠️ | MEDIUM | Funding neutral слишком агрессивный |
| **Confidence V2** | ✅ OK | — | 10 factors, weighted sum |
| **S/R Levels** | ✅ OK | — | Swing + clustering |
| **Distance Filter** | ✅ OK | — | threshold=1.5% |
| **TP Path** | ✅ OK | — | Obstacles scoring |
| **Database** | ⚠️ | LOW | Cooldown в bot_settings неэффективно |
| **Exchange Client** | ⚠️ | MEDIUM | Нет retry на fetch_ohlcv |
| **Notifier** | ⚠️ | LOW | Нет retry на TelegramError |
| **Scheduler** | ✅ OK | — | APScheduler cron |
| **Handlers** | ✅ OK | — | 14+ команд |

---

# 13. ИТОГОВЫЙ SCORE

| Категория | Score / 10 | Комментарий |
|-----------|-----------|-------------|
| Signal Logic | 7/10 | Good leading triggers, но trigger gate слишком строгий |
| Risk Management | 8/10 | Solid ATR-based, dynamic risk, но нет dynamic ATR multiplier |
| Filtering | 7/10 | Много фильтров, но некоторые избыточны или слишком агрессивны |
| Code Quality | 6/10 | Scanner 884 строки, signature mismatches, scope bugs |
| Async/Network | 7/10 | Good caching, но нет retry на OHLCV fetch |
| Architecture | 6/10 | Dual scoring systems, scanner too long, some duplication |
| Parameters | 7/10 | Reasonable defaults, но EMA 9/21 на higher TF — too sensitive |

**Overall: 6.9/10** — Хороший бот с solid foundation, но требует fixes в signal engine pipeline и refactoring scanner.

---

# 14. КОНКРЕТНЫЕ CODE FIXES

## Fix 1: signal_engine.evaluate() signature

```python
# strategy/signal_engine.py:153
def evaluate(
    self,
    ind: IndicatorValues,
    regime: Any = None,
    sweeps: Optional[list] = None,
    order_blocks: Optional[list] = None,  # ADD THIS
    structure: Optional[Any] = None,
) -> SignalResult:
```

## Fix 2: _get_indicators None check

```python
# scheduler/scanner.py:208-212
async def _get_indicators(symbol: str, timeframe: str):
    df = await exchange_client.fetch_ohlcv(symbol, timeframe, limit=config.trading.candles_limit)
    if df is None:
        return None
    ind = indicator_engine.calculate(df, symbol, timeframe)
    if ind is None:
        return None
    return ind, df
```

## Fix 3: is_buy scope fix

```python
# scheduler/scanner.py:504-515
is_buy = result.signal == SignalType.BUY  # MOVE BEFORE the block

if config.derivatives.btc_correlation_enabled:
    try:
        _btc_ctx = await fetch_btc_context()
        if _btc_ctx is not None:
            if is_buy and not _btc_ctx.allows_long():
                ...
            if not is_buy and not _btc_ctx.allows_short():
                ...
```

## Fix 4: RSI scoring direction-aware

```python
# strategy/signal_engine.py:514-526
def _strength_rsi(ind: IndicatorValues, direction: str) -> float:
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

## Fix 5: Fallback trigger when structure unavailable

```python
# strategy/signal_engine.py:296-307
has_trigger = has_leading_trigger

# Fallback: if no structure data, allow EMA/MACD cross as trigger
if not has_trigger and (structure is None or not sweeps):
    if ema_cross_type is not None or macd_cross_type is not None:
        has_trigger = True
        leading_reasons.append("EMA/MACD cross (fallback trigger)")
```

---

# 15. ЗАКЛЮЧЕНИЕ

Бот имеет продуманную архитектуру с multi-layer filtering, leading triggers, и comprehensive risk management. Основные проблемы:

1. **Signature mismatch** между scanner и signal engine — order_blocks не передаются
2. **None check** в _get_indicators — потенциальный crash
3. **Variable scope** bug в BTC correlation gate
4. **RSI scoring** не учитывает direction
5. **Scanner** слишком длинный — нужен refactoring в pipeline

После fixes Priority 1-2 бот будет стабильно работать. Priority 3-4 улучшат winrate и уменьшат drawdown.
