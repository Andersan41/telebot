# Trading Signal Bot — FIXED спецификация (v2.1)

> Исправленная версия `last.md`. Устранены все 7 конфликтов.
> Все изменения отмечены `[FIX]` или `[NEW]`.

---

## 1. ОБЩАЯ АРХИТЕКТУРА

**Язык:** Python 3.11+
**Библиотеки:** python-telegram-bot (v20+), ccxt, pandas, pandas-ta, SQLAlchemy (async), APScheduler, loguru, prometheus-client, aiohttp, aiosqlite

**Шаблон:** Pipeline с singleton-компонентами. Каждый модуль — независимый dataclass-конфиг.

**Структура модулей:**
```
main.py                         # Entry point
config/
  settings.py                   # AppConfig dataclass (все параметры)
  logger.py                     # Логирование (loguru + Telegram sink)
data/
  exchange_client.py            # ccxt OHLCV fetcher (sync в executor)
indicators/
  engine.py                     # pandas-ta расчёт индикаторов
strategy/
  signal_engine.py              # BUY/SELL/NO_SIGNAL решение (13 факторов)
  levels.py                     # Support/Resistance
scheduler/
  tasks.py                      # APScheduler cron jobs
  scanner.py                    # Полный pipeline
  outcome_tracker.py            # SL/TP трекинг
  circuit_breaker.py            # Защита от серии убытков
context/
  fetcher.py                    # Внешние API (F&G, CoinGecko, Binance, RSS)
  analyzer.py                   # ContextSnapshot
  scorer.py                     # ContextVerdict (CONFIRMED/WEAK/CONFLICTED/BLOCKED)
risk/
  market_regime.py              # Режим рынка (тренд/рэндж/компрессия/экспансия)
  volatility_regime.py          # ATR% классификация
  no_trade_zones.py             # Блокирующие условия
  dynamic_risk.py               # Размер позиции
scoring/
  confidence_v2.py              # 10-факторный weighted confidence
liquidity/
  sweep.py                      # Liquidity sweep detection
  order_blocks.py               # Order block detection
  fvg.py                        # Fair Value Gap detection
  candle_quality.py             # Качество свечи
market_structure/
  structure.py                  # BOS/CHoCH/swing points + MTF alignment
  tp_path.py                    # TP path obstacles
  distance_filter.py            # Distance from S/R filter
derivatives/
  btc_correlation.py            # BTC EMA200 + structure (фактор, не gate)
  eth_correlation.py            # ETH impulsive filter
  funding.py                    # Funding rate classification
  open_interest.py              # OI pattern detection
bot/
  handlers.py                   # Telegram command handlers
  admin.py                      # Admin commands
  menu.py                       # Inline keyboard menu
  notifier.py                   # Signal/blocked/error notifications
  rate_limit.py                 # Per-user rate limiter
storage/
  database.py                   # SQLAlchemy async DB (SQLite)
monitoring/
  metrics.py                    # Prometheus metrics
tests/                          # pytest тесты
backtest/                       # Бектестинг
```

---

## 2. ПАЙПЛАЙН СКАНИРОВАНИЯ (scan_symbol)

Полный pipeline для одного `(symbol, timeframe)` в `scheduler/scanner.py`:

```
 1. COOLDOWN CHECK        — DB-персистентный, SIGNAL_COOLDOWN_MINUTES (45 мин)
 2. FETCH OHLCV           — exchange_client.fetch_ohlcv (200 свечей, дроп последней)
 3. CALCULATE INDICATORS  — indicator_engine.calculate (pandas-ta)
 4. DETECT MARKET REGIME  — compression/expansion/trend/range
 5. EARLY LIQUIDITY       — sweeps, order_blocks, structure
 6. SIGNAL ENGINE         — signal_engine.evaluate() → SignalResult (13 факторов)
 7. CONFIRMATION (15m)    — evaluate_confirm() если TF != confirm_tf
 8. S/R LEVELS            — уровни поддержки/сопротивления (1h, 4h)
 9. DISTANCE FILTER       — блок если слишком близко к S/R
10. TP PATH QUALITY       — блок если путь к TP перекрыт
11. STRUCTURE ANALYSIS    — reuse ранних данных
12. LIQUIDITY ANALYSIS    — sweeps, OB, FVG, candle quality
13. MTF ALIGNMENT         — multi-timeframe alignment
14. VOLATILITY REGIME     — classify_volatility
15. CONTEXT ENRICHMENT    — context_engine.get_snapshot()
16. CONTEXT VERDICT GATE  — BLOCKED reject + CONTEXT_MIN_VERDICT
17. NO-TRADE ZONES        — check_no_trade_zones
18. DYNAMIC RISK          — calculate_risk
19. CONFIDENCE V2         — 10-факторный скор
20. FACTOR FINGERPRINT WR — исторический winrate lookup
21. SAVE SIGNAL TO DB     — db.save_signal
22. CREATE OUTCOME        — db.create_outcome
23. SAVE CONTEXT          — db.save_context_snapshot
24. SET COOLDOWN          — db.set_cooldown
25. SEND TO TELEGRAM      — notify_callback
26. PROMETHEUS METRICS    — signals_total.inc()
```

**[FIX] Изменения в pipeline:**
- Убран hard блок BTC/ETH correlation gate (бывшие step 14-15). BTC/ETH теперь факторы внутри signal_engine (W_BTC=10), а не внешние gates.
- No-trade zones больше не проверяет "BTC not aligned" — это дублировало фактор BTC.

---

## 3. SIGNAL ENGINE (strategy/signal_engine.py)

### Внутренний pipeline `evaluate()`:

```
 1. None/NaN guard         — проверка всех critical полей
 2. Regime gate            — compression → deferred (breakout mode)
 3. ADX flat filter        — ADX < 20 (18 для compression) → NO_SIGNAL [FIX]
 4. Leading triggers       — BOS, sweeps, volume delta, OB confirmation
 5. Direction determination — из triggers → EMA/MACD cross → EMA position
 6. Factor strengths       — 13 факторов [-1.0, 1.0] [FIX]
 7. Compression breakout   — strong trigger + ATR×1.2 + vol×1.5 + range break [FIX]
 8. Trigger gate           — trigger_required=true + нет триггера → NO_SIGNAL
 9. Momentum entry mode    — fallback: ST aligned + EMA aligned + ADX>=20 + volume
10. EMA alignment gate     — fast > slow > trend (BUY), reverse (SELL)
11. EMA spread gate        — spread < 0.20% → NO_SIGNAL
12. EMA slope gate         — spread weakening >5% → NO_SIGNAL
13. Build reasons          — score = count(reasons)
14. Min score gate         — score < 2 → NO_SIGNAL [FIX]
15. Candle close confirm   — BUY: close>=60% range, SELL: close<=40% range
16. SL/TP calculation      — ATR-based или BOS-based
```

### [FIX] 13 Factor Strengths (`[-1.0, 1.0]`):

**Базовые 7 факторов (из pandas-ta):**

| Фактор | BUY > 0 | BUY < 0 | Формула |
|--------|---------|---------|---------|
| **Supertrend** | direction==ST → +1.0 | — | иначе -0.5 |
| **EMA** | fast>slow>trend → `min(1.0, spread/1.0%)` | — | иначе -1.0 |
| **MACD** | hist/close*100 * 10, clamp ±1.0 | инверт SELL | если norm<0.03%→0.0; slope check→0.0 |
| **RSI** | ≤28→+1.0, <55→+0.5, <72→0.0, ≥72→-1.0 | ≥72→+1.0, >45→+0.5, >28→0.0, ≤28→-1.0 |
| **Volume** | дельта>15%→`0.3+0.5*(ratio-1)+0.2*(delta/50)` | SELL: -s*0.5 |
| **ADX** | — | — | `(adx - 20) / 30`, min 0.0 [FIX: было 24] |
| **DMI** | `(DMI+ - DMI-) / 50 * 2`, clamp ±1.0 | инверт SELL |

**Добавленные 6 факторов (из модулей анализа):** [NEW]

| Фактор | BUY > 0 | BUY < 0 | Формула |
|--------|---------|---------|---------|
| **BOS** | bullish BOS detected → +1.0 | bearish BOS → -1.0 | 0.0 если нет BOS |
| **Sweep** | sweep в сторону направления → +0.8 | sweep противоход → -0.5 | scaled by sweep strength |
| **OB** | OB подтверждает направление → +0.8 | OB блокирует → -0.5 | 0.0 если нет OB |
| **BTC** | BTC aligned (EMA200+structure) → +0.6 | BTC misaligned → -0.8 | 0.0 если нейтрально |
| **Funding** | negative funding → +0.5 | positive funding → -0.5 | neutral if |rate| < FUNDING_NEUTRAL_ZONE |
| **OI** | OI rising in direction → +0.5 | OI conflicting → -0.5 | scaled by OI delta % |

### [FIX] Weighted Score:

```python
weights = {
    "Supertrend": 5,    # было 0 — теперь участвует в скоринге
    "EMA": 10,
    "MACD": 10,
    "RSI": 5,
    "Volume": 15,
    "ADX": 5,
    "DMI": 5,
    "BOS": 15,
    "Sweep": 10,
    "OB": 10,
    "BTC": 10,
    "Funding": 5,
    "OI": 10,
}
total_weight = 115
weighted_score = sum(factor * weight) / total_weight
```

### SL/TP:
- **SL:** close - ATR * 1.5 (BUY), close + ATR * 1.5 (SELL)
- **TP:** close + ATR * 3.0 (BUY), close - ATR * 3.0 (SELL)
- Если BOS aligned: SL = BOS level * 0.995 (BUY) / 1.005 (SELL)
- **[FIX] ATR fallback:** если ATR is None или ATR < close × 0.001, используется `close × ATR_FALLBACK_PCT / 100`

### [FIX] Verdict (единая шкала):

| Уровень | Signal Engine score | Confidence V2 |
|---------|-------------------|---------------|
| **STRONG** | ≥ 6 | ≥ 65 |
| **MODERATE** | ≥ 4 | ≥ 40 |
| **WEAK** | ≥ 2 | ≥ 20 |
| **VERY WEAK** | < 2 | < 20 |

### Confirmation (15m):
`evaluate_confirm()` — lightweight check: EMA aligned (fast>slow) OR Supertrend aligned.

---

## 4. ALL CONFIG PARAMETERS

### TelegramConfig
| Env | Default |
|-----|---------|
| `TELEGRAM_BOT_TOKEN` | `""` |
| `TELEGRAM_CHANNEL_ID` | `""` |
| `TELEGRAM_ADMIN_IDS` | `[]` |
| `TELEGRAM_ERROR_CHANNEL_ID` | `""` |

### ExchangeConfig
| Env | Default |
|-----|---------|
| `EXCHANGE` | `"binance"` |
| `BINANCE_API_KEY` | `""` |
| `BINANCE_API_SECRET` | `""` |
| `USE_TESTNET` | `false` |
| `MARKET_TYPE` | `"spot"` |

### TradingConfig (индикаторы)
| Env | Default |
|-----|---------|
| `SYMBOLS` | `"BTC/USDT,ETH/USDT,SOL/USDT"` |
| `PRIMARY_TIMEFRAMES` | `"1h,4h"` |
| `CONFIRM_TIMEFRAME` | `"15m"` |
| `CONFIRM_TF_ENABLED` | `true` |
| `EMA_FAST` | `8` |
| `EMA_SLOW` | `21` |
| `EMA_TREND` | `55` |
| `MIN_EMA_SPREAD_PCT` | `0.20` |
| `EMA_SLOPE_CHECK` | `true` |
| `EMA_STRENGTH_CAP` | `1.0` |
| `RSI_PERIOD` | `10` |
| `RSI_OVERBOUGHT` | `72` |
| `RSI_OVERSOLD` | `28` |
| `RSI_BULL_MIN` | `55` |
| `RSI_BEAR_MAX` | `45` |
| `MACD_FAST` | `8` |
| `MACD_SLOW` | `21` |
| `MACD_SIGNAL` | `5` |
| `MIN_MACD_PCT` | `0.03` |
| `MACD_SCORE_MULTIPLIER` | `10` |
| `MACD_SLOPE_CHECK` | `true` |
| `ADX_PERIOD` | `14` |
| `ADX_MIN` | `20` | **[FIX] было 24 — мягче, меньше ложных реджектов** |
| `ADX_STRONG` | `22` | **[FIX] было 25 — раньше включаем трендовый режим** |
| `ADX_STRENGTH_RANGE` | `30` |
| `DMI_NORM_DIVISOR` | `50` |
| `DMI_STRENGTH_MULTIPLIER` | `2` |
| `ATR_PERIOD` | `14` |
| `ATR_MULTIPLIER_SL` | `1.5` |
| `ATR_MULTIPLIER_TP` | `3.0` |
| `ATR_FALLBACK_PCT` | `2.0` | **[FIX] применяется когда ATR=None или ATR < close×0.001** |
| `SUPERTREND_PERIOD` | `10` |
| `SUPERTREND_MULTIPLIER` | `2.5` |
| `VOLUME_FACTOR` | `1.5` |
| `VOLUME_SMA_PERIOD` | `20` |
| `DELTA_BULLISH` | `15` |
| `DELTA_BEARISH` | `-15` |
| `VOLUME_DELTA_NORM` | `50` |
| `CANDLES_LIMIT` | `200` |

### [NEW] CompressionBreakoutConfig
| Env | Default | Назначение |
|-----|---------|-----------|
| `COMPRESSION_BREAKOUT_ATR_MULT` | `1.2` | Мин. рост ATR для breakout |
| `COMPRESSION_BREAKOUT_VOL_MULT` | `1.5` | Мин. рост объёма для breakout |
| `COMPRESSION_BREAKOUT_LOOKBACK` | `20` | Окно для определения диапазона компрессии |

### Filter Toggles (все `true` по умолчанию)
| Env | Назначение |
|-----|-----------|
| `ADX_FILTER_ENABLED` | ADX flat filter |
| `EMA_ALIGNMENT_ENABLED` | EMA alignment gate |
| `EMA_SPREAD_ENABLED` | EMA minimum spread gate |
| `TRIGGER_REQUIRED` | Trigger gate |
| `CANDLE_CLOSE_ENABLED` | Candle close confirmation |
| `MIN_SCORE_ENABLED` | Minimum score gate |
| `COMPRESSION_ENABLED` | Compression breakout mode |

### ScoringConfig (ВЕСА ФАКТОРОВ — ключевой раздел)

**[FIX] Weighted Factor Model (13 факторов, signal_engine, total=115):**
| Env | Default | Назначение |
|-----|---------|-----------|
| `W_SUPERTREND` | `5` | **[FIX] было 0 — теперь участвует** |
| `W_EMA` | `10` | EMA alignment |
| `W_MACD` | `10` | MACD histogram |
| `W_RSI` | `5` | RSI zone |
| `W_VOLUME` | `15` | Volume + delta |
| `W_ADX` | `5` | ADX strength |
| `W_DMI` | `5` | DMI direction |
| `W_BOS` | `15` | Break of Structure |
| `W_SWEEP` | `10` | Liquidity sweep |
| `W_OB` | `10` | Order Block |
| `W_BTC` | `10` | BTC correlation (фактор, не gate) |
| `W_FUNDING` | `5` | Funding rate |
| `W_OI` | `10` | Open Interest |

**Confidence V2 (10 факторов, сумма 100):**
| Env | Default |
|-----|---------|
| `W_HTF_TREND` | `15` |
| `W_STRUCTURE` | `25` |
| `W_LIQUIDITY` | `15` |
| `W_CONF_VOLUME` | `10` |
| `W_BTC_CORR` | `10` |
| `W_CONF_FUNDING` | `5` |
| `W_CONF_OI` | `5` |
| `W_CONF_RSI` | `5` |
| `W_CONF_MACD` | `5` |
| `W_CONF_ADX` | `5` |

**Blending:**
| Env | Default | Назначение |
|-----|---------|-----------|
| `TECH_CONFIDENCE_BLEND` | `0.6` | Вес технических факторов |
| `MARKET_CONFIDENCE_BLEND` | `0.4` | Вес рыночных факторов |
| `HISTORICAL_WR_BLEND` | `0.6` | Вес historical winrate в финале |
| `CONFIDENCE_V2_ENABLED` | `true` | |
| `QUALITY_STRONG_THRESHOLD` | `65` | **[FIX] было 35 — унифицировано с confidence** |
| `QUALITY_MODERATE_THRESHOLD` | `40` | **[FIX] было 20** |
| `CONFIDENCE_STRONG_THRESHOLD` | `65` | **[FIX] было 70** |
| `CONFIDENCE_MODERATE_THRESHOLD` | `40` | **[FIX] было 40 (ок)** |
| `MIN_SCORE_FOR_SIGNAL` | `2` | **[FIX] было 0 — отсекает VERY WEAK** |

### LiquidityConfig
| Env | Default | Назначение |
|-----|---------|-----------|
| `SWEEP_MAX_RECLAIM_CANDLES` | `2` | Max candles for reclaim |
| `SWEEP_MIN_VOLUME_RATIO` | `1.8` | Min volume for sweep |
| `SWEEP_FAST_RECLAIM_CANDLES` | `3` | Fast reclaim window |
| `SWEEP_MIN_WICK_BODY_RATIO` | `2.0` | Min wick/body for sweep |
| `SWEEP_LOOKBACK` | `50` | Lookback for swing points |
| `SWEEP_SWING_WINDOW` | `5` | Swing window |
| `SWEEP_MAX_CHECK_RECLAIM` | `10` | Max reclaim check candles |
| `SWEEP_MAX_CHECK_DISPLACEMENT` | `5` | Max displacement candles |
| `SWEEP_DELTA_ALIGNED_THRESHOLD` | `0.5` | Delta alignment threshold |
| `SWEEP_STRENGTH_FAST_RECLAIM` | `0.3` | Strength increment |
| `SWEEP_STRENGTH_HIGH_VOLUME` | `0.3` | Strength increment |
| `SWEEP_STRENGTH_DELTA_ALIGNED` | `0.2` | Strength increment |
| `SWEEP_STRENGTH_DISPLACEMENT` | `0.2` | Strength increment |
| `OB_MIN_DISPLACEMENT_PCT` | `2.5` | Min displacement % |
| `OB_MIN_DISPLACEMENT_ATR` | `1.5` | Min displacement ATR |
| `OB_MIN_VOLUME_RATIO` | `1.8` | Min volume ratio |
| `OB_MAX_AGE_CANDLES` | `35` | Max OB age |
| `OB_RETEST_REQUIRED` | `false` | Retest required |
| `OB_LOOKBACK` | `100` | OB lookback |
| `OB_SWING_WINDOW` | `5` | Swing window |
| `OB_BOS_LOOKAHEAD` | `20` | BOS lookahead |
| `OB_RETEST_MAX_LOOKAHEAD` | `30` | Retest max lookahead |
| `FVG_MIN_SIZE_PCT` | `0.4` | Min FVG size |
| `FVG_LOOKBACK` | `100` | FVG lookback |
| `CANDLE_DISPLACEMENT_ATR_MULT` | `1.5` | |
| `CANDLE_MIN_BODY_PCT` | `0.6` | Min body % |
| `CANDLE_MAX_WICK_RATIO` | `0.3` | Max wick ratio |

### MarketStructureConfig
| Env | Default |
|-----|---------|
| `DISTANCE_FILTER_MIN_PCT` | `1.2` |
| `MTF_REQUIRED_ALIGNMENT` | `2` |
| `MTF_TIMEFRAMES` | `"1d,4h,1h"` |
| `MTF_ENABLED` | `true` |
| `DISTANCE_FILTER_ENABLED` | `true` |
| `SR_LEVELS_ENABLED` | `true` |
| `TP_PATH_ENABLED` | `false` |
| `STRUCTURE_LOOKBACK` | `50` |
| `STRUCTURE_SWING_WINDOW` | `5` |
| `STRUCTURE_RECENT_COUNT` | `5` |
| `MTF_OHLCV_LIMIT` | `100` |
| `MTF_MIN_CANDLES` | `20` |

### RiskConfig
| Env | Default |
|-----|---------|
| `VOLATILITY_LOW_THRESHOLD` | `0.8` |
| `VOLATILITY_HIGH_THRESHOLD` | `6.0` |
| `VOLATILITY_ATR_PERIOD` | `14` |
| `VOLATILITY_HIGH_MULTIPLIER` | `0.5` |
| `RISK_STRONG_PCT` | `1.0` |
| `RISK_MODERATE_PCT` | `0.5` |
| `RISK_WEAK_TRADE` | `true` | **[FIX] было false — слабые сигналы заходят с 0.25%** |
| `RISK_WEAK_PCT` | `0.25` | **[NEW] размер для WEAK сигналов** |
| `NO_TRADE_MIN_ATR_PCT` | `0.6` |
| `CORRELATION_MISALIGNED_MULTIPLIER` | `0.5` |
| `VOLATILITY_FILTER_ENABLED` | `true` |
| `NO_TRADE_ZONES_ENABLED` | `true` |
| `DYNAMIC_RISK_ENABLED` | `true` |
| `REGIME_TREND_ADX` | `22` | **[FIX] было 25 — синхронизировано с ADX_STRONG** |
| `REGIME_RANGE_ADX` | `18` |
| `REGIME_COMPRESSION_ATR_PCT` | `20` |
| `REGIME_ATR_LOOKBACK` | `100` |
| `REGIME_EMA_SPREAD_WINDOW` | `5` |
| `REGIME_EMA_SPREAD_CHANGE_PCT` | `0.05` |
| `REGIME_RISING_MULTIPLIER` | `1.1` |
| `REGIME_RISING_WINDOW` | `10` |
| `REGIME_FALLBACK_CONFIDENCE` | `0.3` |
| `TP_PATH_BLOCKED_THRESHOLD` | `-20` |
| `TP_PATH_CLEAR_SCORE` | `15` |
| `TP_PATH_OBSTACLE_PENALTY` | `-10` |

### DerivativesConfig
| Env | Default |
|-----|---------|
| `FUNDING_STRONG_THRESHOLD` | `0.0003` |
| `FUNDING_NEUTRAL_ZONE` | `0.0001` |
| `OI_MODERATE_THRESHOLD` | `0.5` |
| `OI_STRONG_THRESHOLD` | `2.0` |
| `OI_LOOKBACK_HOURS` | `24` |
| `BTC_SYMBOL` | `"BTC/USDT"` |
| `BTC_EMA200_TIMEFRAME` | `"4h"` |
| `BTC_CORRELATION_ENABLED` | `true` | **[FIX] больше не hard gate — фактор в signal_engine** |
| `ETH_SYMBOL` | `"ETH/USDT"` |
| `ETH_CORRELATION_SYMBOLS` | `"OP/USDT,ARB/USDT"` |
| `ETH_CORRELATION_ENABLED` | `true` | **[FIX] больше не hard gate — фактор в signal_engine** |

### SupportResistanceConfig
| Env | Default |
|-----|---------|
| `SR_WINDOW` | `10` |
| `SR_MAX_LEVELS` | `5` |
| `SR_CLUSTER_THRESHOLD` | `0.005` |
| `SR_MIN_DISTANCE_PCT` | `1.0` |
| `SR_OHLCV_LIMIT` | `100` |

### Global AppConfig
| Env | Default |
|-----|---------|
| `DATABASE_URL` | `"sqlite+aiosqlite:///./data/signals.db"` |
| `LOG_LEVEL` | `"INFO"` |
| `LOG_FILE` | `"logs/bot.log"` |
| `SIGNAL_COOLDOWN_MINUTES` | `45` |
| `CONTEXT_ENABLED` | `true` |
| `CONTEXT_MIN_VERDICT` | `"MODERATE"` |
| `CONTEXT_BLOCK_ON_BLOCKED` | `true` |
| `SIGNAL_BLOCK_NOTIFY` | `true` |
| `CRYPTOPANIC_API_KEY` | `""` |
| `COINGECKO_SYMBOL_MAP` | `"BTC/USDT:bitcoin,ETH/USDT:ethereum"` |
| `CONTEXT_FETCH_TIMEOUT` | `10` |

### SchedulerConfig
| Env | Default |
|-----|---------|
| `HOURLY_SCAN_MINUTE` | `2` |
| `FOUR_HOUR_SCAN_HOURS` | `"0,4,8,12,16,20"` |
| `FOUR_HOUR_SCAN_MINUTE` | `5` |

### RateLimitConfig
| Env | Default |
|-----|---------|
| `RATE_LIMIT_MAX_RATE` | `5` |
| `RATE_LIMIT_TIME_PERIOD` | `10` |

---

## 5. КОНТЕКСТНЫЙ МОДУЛЬ

### Context Fetcher (`context/fetcher.py`)
| Источник | Метод | Cache TTL |
|----------|-------|-----------|
| Alternative.me | `fetch_fear_greed()` | 3600s |
| CoinGecko | `fetch_coingecko(coin_id)` | нет |
| CoinGecko | `fetch_trending()` | 1800s |
| Binance fapi | `fetch_funding_rate(symbol)` | нет |
| Binance fapi | `fetch_open_interest(symbol)` | per-symbol |
| Binance fapi | `fetch_long_short_ratio(symbol)` | нет |
| CryptoPanic | `fetch_cryptopanic(symbol)` | нет |
| RSS | `fetch_rss_news(symbol)` | 300s |

### Context Scorer (`context/scorer.py`)
**Verdict thresholds:** CONFIRMED ≥ 0.4, WEAK ≥ 0.05, CONFLICTED ≥ -0.1, BLOCKED < -0.1

**Factor weights:**
| Фактор | Вес | BUY логика |
|--------|-----|-----------|
| Fear & Greed | 0.15 | <20→+0.8, >80→-0.8 |
| Funding Rate | 0.25 | negative→+0.9, positive→-0.9 |
| Long/Short Ratio | 0.20 | <0.7→+0.7, >1.2→-0.6 |
| OI Delta | 0.15 | >2%→+0.5, <-2%→-0.3 |
| News Sentiment | 0.15 | direct score |
| Price Trend 7d | 0.10 | >5%→+0.5, <-5%→-0.5 |

### Context Gates:
1. `context_block_on_blocked=true + verdict=BLOCKED` → reject
2. `context_min_verdict=MODERATE` (rank: BLOCKED<CONFLICTED<WEAK<CONFIRMED)

---

## 6. РЕЖИМЫ РЫНКА (market_regime.py)

| Режим | Приоритет | Условие |
|-------|-----------|---------|
| Compression | 1 | ATR percentile < 20% |
| Range | 2 | ADX < 18 |
| Expansion | 3 | ATR rising + volume rising (оба > 1.1x) |
| Trend | 4 | ADX ≥ 22 + EMA spread rising |
| Fallback | 5 | Range |

**[FIX] Trend ADX порог: 25→22 (синхронизировано с ADX_STRONG)**

---

## 7. VOLATILITY REGIME

- **Low:** ATR% < 0.8% → breakout trades disabled
- **Medium:** между порогами → normal
- **High:** ATR% > 6.0% → position size × 0.5

---

## 8. NO-TRADE ZONES

Блокирует сигнал если ANY:
- ATR% < `no_trade_min_atr_pct` (0.6%) → "no momentum"
- Market structure = "ranging" → "no trend"
- TP blocked → "path obstructed"
- OI extreme (extreme_long/extreme_short)

**[FIX] Убрано "BTC not aligned" — этот фактор работает внутри signal_engine (W_BTC=10).**
**[FIX] Убрано дублирование correlation risk — BTC/ETH корреляция влияет на weighted score, а не блокирует сигнал.**

---

## 9. DYNAMIC RISK

- **Strong:** `risk_strong_pct` (1.0%)
- **Moderate:** `risk_moderate_pct` (0.5%)
- **Weak:** `risk_weak_pct` (0.25%) — **[FIX] enabled, trade always allowed**
- `effective_risk = base × vol_multiplier × corr_multiplier`
  - High vol: ×0.5
  - Misaligned BTC/ETH: ×0.5

---

## 10. БАЗА ДАННЫХ

**Таблицы (SQLite, async через SQLAlchemy + aiosqlite):**

### signals
| Колонка | Тип | Описание |
|---------|-----|----------|
| id | Integer PK AUTO | |
| symbol | String(20) INDEX | |
| timeframe | String(10) | |
| signal_type | String(10) | BUY/SELL |
| close_price | Float | |
| sl | Float nullable | |
| tp | Float nullable | |
| score | Integer | |
| reasons | Text nullable | |
| confirmed | Boolean | |
| factor_fingerprint | String(255) INDEX nullable | |
| created_at | DateTime | |
| sent_at | DateTime nullable | |

### signal_outcomes
| Колонка | Тип |
|---------|-----|
| id | Integer PK AUTO |
| signal_id | Integer FK INDEX |
| status | String(20): OPEN/HIT_TP/HIT_SL/EXPIRED |
| closed_at | DateTime nullable |
| close_price | Float nullable |
| pnl_pct | Float nullable |
| checked_at | DateTime |

### context_snapshots
| Колонка | Тип |
|---------|-----|
| id | Integer PK |
| symbol | String(20) INDEX |
| signal_id | Integer FK nullable |
| timestamp | DateTime |
| verdict | String(20) |
| confidence | Float |
| score | Float |
| fear_greed | Integer nullable |
| funding_rate | Float nullable |
| long_short_ratio | Float nullable |
| open_interest_delta | Float nullable |
| news_sentiment | Float nullable |
| raw_json | Text nullable |

### bot_settings
| Колонка | Тип |
|---------|-----|
| key | String(100) PK |
| value | Text |
| updated_at | DateTime |

---

## 11. ТЕЛЕГРАМ КОМАНДЫ

### Пользовательские:
- `/start` — inline menu
- `/help` — помощь
- `/status` — статус бота
- `/lastsignal` — последние 5 сигналов
- `/symbols` — список символов

### Админские (TELEGRAM_ADMIN_IDS):
- `/scan` — ручной скан
- `/settings` — текущие параметры
- `/addsymbol BTC/USDT` — добавить символ
- `/removesymbol BTC/USDT` — удалить символ
- `/listsymbols` — список активных
- `/setparam EMA_FAST 7` — изменить параметр
- `/disable BTC/USDT` — отключить символ
- `/enable BTC/USDT` — включить символ
- `/exportdb` — экспорт БД
- `/stats` — статистика

### Inline Menu:
- "🔍 Анализ токена" → выбор → полный анализ
- "📊 Индикаторы" → выбор → значения
- "📡 Авто-скан всех" → быстрый скан
- "🔇 Signal block" → toggle уведомлений
- "⚙️ Настройки" → фильтры + параметры

---

## 12. ИНДИКАТОРЫ (indicators/engine.py)

Через `pandas_ta`:

| Индикатор | pandas-ta call | Параметры | Поля на выходе |
|-----------|---------------|-----------|---------------|
| EMA | `ta.ema(close, length=)` | 8, 21, 55 | `ema_fast`, `ema_slow`, `ema_trend`, `ema_fast_prev`, `ema_slow_prev` |
| RSI | `ta.rsi(close, length=)` | 10 | `rsi` |
| MACD | `ta.macd(close, fast=, slow=, signal=)` | 8, 21, 5 | `macd`, `macd_signal`, `macd_hist`, `macd_hist_prev` |
| ADX/DMI | `ta.adx(high, low, close, length=)` | 14 | `adx`, `dmi_plus`, `dmi_minus` |
| ATR | `ta.atr(high, low, close, length=)` | 14 | `atr` |
| Supertrend | `ta.supertrend(high, low, close, length=, multiplier=)` | 10, 2.5 | `supertrend`, `supertrend_direction` (±1) |
| Volume SMA | `ta.sma(volume, length=)` | 20 | `volume_sma` |

**Вычисляемые поля:**
- `ema_bullish_cross`: fast_prev ≤ slow_prev AND fast > slow
- `ema_bearish_cross`: fast_prev ≥ slow_prev AND fast < slow
- `volume_above_avg`: volume > volume_sma * volume_factor
- `macd_bullish_cross`: hist_prev < 0 AND hist > 0
- `macd_bearish_cross`: hist_prev > 0 AND hist < 0

---

## 13. EXCHANGE CLIENT

- ccxt sync в `run_in_executor` (Windows compat)
- **Дроп последней свечи:** `df.iloc[:-1]` — никогда не сигналим по незакрытой свече
- Retry: exponential backoff (1s, 2s, 4s) для NetworkError
- Semaphore (1) для ccxt (не thread-safe)
- Timeout: 30s

---

## 14. SCHEDULER

| Job | Cron | TFs |
|-----|------|-----|
| `hourly_scan` | `:02` каждый час | `["1h"]` |
| `4h_scan` | `0,4,8,12,16,20 :05` | `["4h"]` |

Circuit Breaker: 3 consecutive HIT_SL → pause 30 min.
Outcome Tracker: каждые 5 мин проверяет open outcomes.

---

## 15. COOLDOWN

- `SIGNAL_COOLDOWN_MINUTES` = 45 (default)
- Хранится в DB (`bot_settings`, ключ `cooldown:{symbol}:{timeframe}`)
- Персистентный (не сбрасывается при рестарте)
- Per `symbol|timeframe` pair

---

## 16. FACTOR FINGERPRINT

**[FIX] Расширен до 13 факторов:**

`adx_strong|bos_bullish|ema_bullish|funding_pos|liq_bull_sweep|macd_pos|mtf_aligned|ob_bullish|oi_rising|st_bullish|trend_bullish|vol_above|btc_aligned`

Используется для исторического winrate lookup в `db.get_historical_winrate()`.
Blending: `blended = historical_wr * 0.6 + score_confidence * 0.4`

---

## 17. ФОРМАТ СООБЩЕНИЯ В TELEGRAM

```
BUY — ПОКУПКА
Инструмент: BTC/USDT
Таймфрейм: 1H | Подтверждение: 15m
Цена входа: 65432.10
Stop Loss: 64800.00 (-0.97%)
Take Profit: 67200.00 (+2.70%)
R/R: 1:2.8

Технические факторы (6/7):
  BOS бычий (leading trigger) уровень 64850
  Supertrend бычий
  ...

Рыночный контекст:
  ├ Fear & Greed: 45 (Neutral) 😐
  ├ Funding: -0.002% ✅
  ├ Long/Short: 0.89 ✅
  └ Новости: нейтральные 😐

Итог: MODERATE | Уверенность: 65.2%
Quality: moderate
```

**ВАЖНО:** Telegram HTML parse_mode требует `html.escape()` на каждом динамическом значении. Бот делает re-escape при `BadRequest`.

---

## 18. DB FILTER TOGGLES (переопределение через БД)

Ключи в `bot_settings`:
- `filter:toggle:{key}` → bool (см. FILTER_TOGGLE_KEYS в settings.py)
- `filter:param:{key}` → typed value (см. FILTER_PARAM_KEYS)
- `param:{UPPER_NAME}` — legacy формат

Все 22 toggle keys: `adx_filter`, `ema_alignment`, `ema_spread`, `trigger`, `candle_close`, `min_score`, `compression`, `confirm_tf`, `ema_slope`, `macd_slope`, `mtf`, `distance_filter`, `sr_levels`, `tp_path`, `btc_corr`, `eth_corr`, `volatility`, `no_trade_zones`, `dynamic_risk`, `context`, `confidence_v2`, `signal_block`

---

## 19. ВАЖНЫЕ ГОТЧИ (gotchas)

1. **Telegram HTML**: `parse_mode=ParseMode.HTML` требует `html.escape()` на каждом динамическом подстроке — голый `<` (напр. "ADX < 20") крашит парсер Telegram. Делать re-escape на `BadRequest`.

2. **pandas-ta колонки**: Supertrend → `SUPERT_…` / `SUPERTd_…`; ADX → `ADX_…`, `DMP_…`, `DMN_…`. При обновлении pandas-ta проверять префиксы.

3. **exchange_client.fetch_ohlcv дропает последнюю свечу** (`df.iloc[:-1]`) — чтобы не сигналить по открытой свече.

4. **Context fetcher singleton state**: `_fng_cache`, `_trending_cache`, `_rss_cache`, `_last_oi[symbol]`. Тесты должны создавать свежий ContextFetcher, не использовать модульные синглтоны.

5. **`main.py` добавляет корень в `sys.path`** — запуск подмодулей без этого сломает sibling imports.

6. **15m confirmation часто режет 100% сигналов** — на мелком TF редко есть ADX+trigger. Можно ослабить или сделать configurable.

7. **Cooldown в DB** — персистентный, не сбрасывается при рестарте (в отличие от in-memory подхода).

8. **[FIX] Compression breakout использует ATR-based логику** — вместо ADX≥25, проверяет ATR рост ×1.2 + объём ×1.5 + пробой диапазона. Это решает логическую петлю ADX 18-25.

9. **[FIX] ATR fallback** — если ATR невалиден (None или < close×0.001), используется `close × ATR_FALLBACK_PCT / 100`.

---

## 20. MINIMAL .env для запуска

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_ID=
SYMBOLS=BTC/USDT,ETH/USDT
PRIMARY_TIMEFRAMES=1h,4h
BINANCE_API_KEY=
BINANCE_API_SECRET=
```

---

## 21. ЗАПУСК

```bash
pip install -r requirements.txt
python main.py
# Или Docker:
docker-compose build && docker-compose up -d
```

---

## 22. ТЕСТЫ

```bash
pytest -v                          # все
pytest tests/test_signal.py -v     # один файл
pytest tests/test_scanner.py -v
```

`asyncio_mode = auto` в `pytest.ini`; async тесты помечать `@pytest.mark.asyncio`.
Каждый тестовый файл делает `sys.path.insert(0, root)` — нет `pip install -e .`.

---

## 23. ИТОГО: pipeline summary

```
Trigger (cron/:02) → OHLCV fetch (ccxt) → Indicators (pandas-ta)
→ Market Regime → Early Liquidity
→ SignalEngine (13 factors + 10 gates) → 15m Confirmation
→ S/R Levels → Distance Filter → TP Path Quality
→ Structure Analysis → Liquidity Analysis → MTF Alignment
→ Volatility Regime → Context Enrichment
→ Context Verdict Gate → No-Trade Zones → Dynamic Risk
→ Confidence V2 (10 factors) → Factor Fingerprint WR
→ DB Save → Cooldown → Telegram Notification
```

---

## ПРИЛОЖЕНИЕ: Сводка изменений относительно last.md

| # | Конфликт | last.md | last.fixed.md |
|---|----------|---------|--------------|
| 1 | 7 vs 13 факторов | `evaluate()` считает 7, конфиг хранит 13 | 13 факторов в `evaluate()`, все веса активны |
| 2 | Supertrend weight = 0 | `W_SUPERTREND = 0` | `W_SUPERTREND = 5` |
| 3 | ADX compression loop | ADX≥25 для breakout, но ADX<18 в compression | ATR×1.2 + vol×1.5 + range break |
| 4 | MIN_SCORE_FOR_SIGNAL = 0 | `0` | `2` |
| 5 | Двойные пороги | quality 35/20, confidence 70/40 | единые 65/40 |
| 6 | RISK_WEAK_TRADE = false | слабые блокируются | слабые заходят с 0.25% |
| 7 | ATR_FALLBACK без условия | не указано когда | если ATR=None или < close×0.001 |
| — | BTC/ETH gates | hard block | факторы W_BTC=10 |
| — | ADX_MIN / ADX_STRONG | 24 / 25 | 20 / 22 |
| — | REGIME_TREND_ADX | 25 | 22 |
