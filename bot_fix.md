ГЛАВНАЯ АРХИТЕКТУРНАЯ ПРОБЛЕМА

Сейчас:

EMA/MACD генерируют сигнал Liquidity только фильтрует

Нужно:

Liquidity/Structure генерируют сигнал EMA/MACD подтверждают сигнал

Это ключевая цель рефакторинга.

ПРАВИЛА ДЛЯ QWEN AGENT
ОБЯЗАТЕЛЬНО
1. Не делать massive rewrite

Каждый этап:

отдельный commit
отдельный patch
отдельный changelog
2. После каждого изменения:

Сделать:

unit tests
smoke tests
regression tests

Проверить:

scanner pipeline
signal generation
telegram formatting
database writes
cooldown system
context scoring
3. Не менять публичные интерфейсы без необходимости

Если меняется dataclass:

сохранить backward compatibility
добавить migration layer
4. Все thresholds вынести в config

Нельзя оставлять:

hardcoded percentages
hardcoded ATR multipliers
hardcoded windows
5. Добавить подробное логирование

Каждый signal должен логировать:

{
  "ema_cross": true,
  "ema_alignment": false,
  "macd_strength": 0.21,
  "delta_pct": 18.4,
  "bos": true,
  "sweep_detected": false
}
ЭТАП 1 — FIX CRITICAL BUGS
PRIORITY: CRITICAL
TASK 1.1 — Удалить дублирование EMA
Файл:

strategy/signal_engine.py

Текущая проблема

Сейчас:

buy_score += 1  # alignment
buy_score += 1  # cross

Это двойной учет одного и того же события.

Что нужно сделать
EMA alignment

Должен стать:

trend filter
state filter
но НЕ scoring factor
Новая логика
BUY
if not ema_bullish_alignment:
    reject BUY

НО:

alignment НЕ дает score
SELL
if not ema_bearish_alignment:
    reject SELL
EMA cross

Остается:

entry trigger
scoring factor
Дополнительно

Добавить:

ema_spread_pct = abs(ema_fast - ema_slow) / close * 100
Добавить минимальный spread
MIN_EMA_SPREAD_PCT = 0.15
Условие
if ema_spread_pct < MIN_EMA_SPREAD_PCT:
    reject signal
Добавить slope
ema_fast > prev_ema_fast

для bullish.

После фикса проверить
количество сигналов
score distribution
количество STRONG verdict
количество false positives
TASK 1.2 — Исправить MACD noise
Файл:

strategy/signal_engine.py scoring/confidence_v2.py

Проблема

Сейчас:

hist > 0

это уже bullish.

Нужно сделать

Нормализацию относительно цены.

Формула

genui{"math_block_widget_always_prefetch_v2":{"content":"MACD_{norm}=\frac{MACD_{hist}}{Price}\times100"}}

Добавить threshold
MIN_MACD_PCT = 0.03
Новая логика
normalized_hist = abs(macd_hist / close) * 100


if normalized_hist < MIN_MACD_PCT:
    macd_signal = neutral
Добавить slope

Bullish:

hist > prev_hist

Bearish:

hist < prev_hist
Добавить acceleration
acceleration = hist - prev_hist

Использовать в confidence.

TASK 1.3 — Реализовать volume delta
Файл:

data/exchange_client.py indicators/engine.py

Проблема

volume_delta_pct всегда None.

Нужно получить

Из Binance futures:

taker_buy_base_asset_volume
Формулы

Buy volume:

buy_volume = taker_buy_volume

Sell volume:

sell_volume = total_volume - buy_volume

Delta:

genui{"math_block_widget_always_prefetch_v2":{"content":"Volume\ Delta=\frac{BuyVolume-SellVolume}{TotalVolume}\times100"}}

Добавить thresholds
DELTA_BULLISH = 15
DELTA_BEARISH = -15
Новая логика volume

Сейчас:

volume gives +1 to BUY and SELL
Нужно

BUY:

volume_above_avg
AND delta_pct > 15

SELL:

volume_above_avg
AND delta_pct < -15
Добавить:
delta divergence
absorption detection
delta weakening

в future TODO.

TASK 1.4 — Исправить RSI boundary
Файл:

strategy/signal_engine.py

Исправить

Было:

30 < rsi <= 50

Нужно:

30 <= rsi <= 50
Дополнительно

Переделать RSI в context factor.

Новый режим RSI
RSI	Интерпретация
<30	oversold reversal
30-50	neutral
50-65	bullish continuation
>70	exhaustion
TASK 1.5 — Исправить MTF alignment
Файл:

market_structure/structure.py

Проблема

Сейчас:

ranging = aligned
Нужно

Range НЕ должен считаться aligned.

Новая логика

BUY aligned:

trend == bullish

SELL aligned:

trend == bearish
Range

Должен:

обрабатываться отдельно
использовать другую стратегию
ЭТАП 2 — REFACTOR SIGNAL ENGINE
PRIORITY: HIGH
TASK 2.1 — Убрать binary scoring
Проблема

Сейчас:

buy_score += 1

Это primitive scoring.

Нужно

Перейти на weighted factor model.

Новая архитектура
TREND
Фактор	Вес
HTF trend	20
EMA trend	10
Supertrend	5
MOMENTUM
Фактор	Вес
MACD slope	10
RSI regime	5
Volume delta	15
STRUCTURE
Фактор	Вес
BOS	15
Sweep reclaim	10
Order Block reaction	10
CONTEXT
Фактор	Вес
BTC correlation	10
Funding	5
OI pattern	10
TASK 2.2 — Добавить factor strength

Вместо:

factor = true/false

Использовать:

factor_strength [-1.0, 1.0]
Пример

MACD:

strength = normalized_hist / threshold
Volume:
strength = delta_pct / 50
TASK 2.3 — Разделить trigger и confirmation
Сейчас

Все индикаторы смешаны.

Нужно
TRIGGER
liquidity sweep
BOS
reclaim
displacement
CONFIRMATION
EMA
MACD
ADX
RSI
ЭТАП 3 — REBUILD LIQUIDITY ENGINE
PRIORITY: HIGH
TASK 3.1 — Исправить Order Blocks
Файл:

liquidity/order_blocks.py

Сейчас

Любой impulsive candle = OB.

Нужно добавить BOS

Bullish OB:

bearish candle
displacement up
break previous swing high
Добавить ATR-normalized displacement

Вместо:

2%

Использовать:

genui{"math_block_widget_always_prefetch_v2":{"content":"Displacement=\frac{MoveSize}{ATR}"}}

Threshold
MIN_OB_DISPLACEMENT_ATR = 1.5
Добавить volume confirmation
volume_ratio > 1.5
Добавить retest validation

OB valid only if:

price revisits zone
reaction occurs
TASK 3.2 — Улучшить sweeps
Файл:

liquidity/sweep.py

Добавить
sweep strength
displacement after sweep
reclaim speed
delta confirmation
wick/body ratio
Sweep scoring
Condition	Score
Fast reclaim	+0.3
High volume	+0.3
Delta aligned	+0.2
Displacement	+0.2
TASK 3.3 — Candle Quality
Файл:

liquidity/candle_quality.py

Сейчас

Анализируется последняя свеча.

Нужно

Анализировать:

sweep candle
OB candle
BOS candle
ЭТАП 4 — ADD MARKET REGIME ENGINE
PRIORITY: HIGH
TASK 4.1 — Создать regime detector
Новый модуль:

risk/market_regime.py

Определять:
Regime	Условия
Trend	ADX > 25 AND EMA spread rising
Range	ADX < 18
Compression	ATR percentile low
Expansion	ATR rising + volume rising
Reversal	sweep + divergence
TASK 4.2 — Strategy switching

Trend regime:

EMA allowed
breakout allowed

Range regime:

EMA entries disabled
use sweeps only

Compression:

wait for expansion

Reversal:

prioritize liquidity grabs
ЭТАП 5 — REBUILD RISK ENGINE
PRIORITY: HIGH
TASK 5.1 — Убрать fixed ATR model
Сейчас
SL = ATR * 1.5
TP = ATR * 3
Нужно
LONG SL
below sweep low
below OB low
below structure low
SHORT SL
above sweep high
above OB high
above structure high
TASK 5.2 — Dynamic TP

TP targets:

liquidity pools
previous highs/lows
FVG fill
HTF resistance/support
RR

Должен быть:

dynamic
structure-based

НЕ fixed.

ЭТАП 6 — IMPROVE CONFIDENCE ENGINE
PRIORITY: MEDIUM
TASK 6.1 — Confidence ≠ score

Сейчас:

confidence = score
Нужно

Confidence должен означать:

historical probability.

Пример

Если historically:

EMA cross + BTC aligned + positive delta

дает:

62% WR

то confidence ≈ 62.

TASK 6.2 — Build factor analytics
Новый модуль:

analytics/factor_stats.py

Логировать

Для каждого сигнала:

{
  "ema_cross": true,
  "macd_positive": true,
  "delta_positive": false,
  "sweep": true,
  "bos": true,
  "result": "HIT_TP"
}
Считать
Factor	Winrate
Sweep	68%
RSI	49%
BTC aligned	64%
Добавить:
expectancy
profit factor
max drawdown
sharpe
ЭТАП 7 — REDUCE LAGGING BEHAVIOR
PRIORITY: MEDIUM
TASK 7.1 — Add leading signals

Приоритет:

Delta
Sweep reclaim
BOS
Displacement
Absorption
EMA/MACD

Должны:

подтверждать
а не инициировать signal.
TASK 7.2 — Entry timing analysis
Новый модуль:

analytics/entry_delay.py

Проверять

Сколько ATR проходит:

ДО сигнала
ПОСЛЕ сигнала
Метрика
entry_efficiency
ЭТАП 8 — BACKTEST & VALIDATION
PRIORITY: CRITICAL
TASK 8.1 — Построить полноценный бэктест
Новый модуль:

backtest/engine.py

Проверять
winrate
expectancy
profit factor
sharpe ratio
max drawdown
avg RR
signal decay
Разделить по regime

Отдельно тестировать:

Regime
Trend
Range
Compression
High volatility
Low volatility
TASK 8.2 — Contribution analysis

Определить:

Какие факторы реально дают edge.

Считать:
Factor	WR	PF	Expectancy
TASK 8.3 — False positive analysis

Проверять:

сколько strong signals → SL
какие факторы чаще дают убыток
какие combinations дают лучший edge
ЭТАП 9 — CLEAN ARCHITECTURE
PRIORITY: MEDIUM
TASK 9.1 — Удалить дублирование форматирования
Файл:

bot/notifier.py scanner.py

Нужно

Один shared formatter.

TASK 9.2 — Centralize config

Все thresholds:

MIN_MACD_PCT
MIN_EMA_SPREAD_PCT
DELTA_THRESHOLD
OB_MIN_DISPLACEMENT

должны быть:

в config
hot-reloadable
documented
TASK 9.3 — Improve logging

Каждый signal должен иметь:

raw factors
normalized factors
weighted factors
reject reasons
regime
context snapshot
ИТОГОВАЯ ЦЕЛЬ АРХИТЕКТУРЫ
БЫЛО
EMA/MACD generate signal
Liquidity filters signal
ДОЛЖНО СТАТЬ
Liquidity + Structure generate signal
EMA/MACD confirm signal
Context validates signal
Regime controls strategy
Risk engine adapts execution
ФИНАЛЬНЫЙ CHECKLIST ДЛЯ QWEN
CRITICAL


HIGH PRIORITY


MEDIUM PRIORITY


ФИНАЛЬНОЕ ТРЕБОВАНИЕ

После каждого этапа:

Сделать regression tests
Сделать before/after metrics
Проверить signal count
Проверить winrate
Проверить false positives
Проверить average RR
Сделать git commit
Обновить CHANGELOG

Нельзя делать следующий этап, если предыдущий не стабилен.

Готово. Я собрал полный master-файл BOT_FIX.md для локального coding-agent на Qwen 3.6.

Документ включает:

все найденные архитектурные проблемы,
критические баги,
пошаговый roadmap исправлений,
конкретные задачи по файлам,
новую целевую архитектуру,
risk/refactor правила,
инструкции по тестированию,
migration strategy,
backtesting roadmap,
factor analytics,
regime engine,
liquidity-first model,
dynamic confidence,
structure-based risk system.

Файл построен как техническое ТЗ для AI-агента, который:

пишет код,
рефакторит,
делает patch-и,
запускает тесты,
постепенно улучшает систему без полного rewrite.