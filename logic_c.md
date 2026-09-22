# Независимый аудит логики ICT-бота по КОДУ (v2.5.0) — logic_up.md

**Дата:** 2026-09-08
**Объект:** архив `telebot-feat-htf-bias-v2-premium-discount` (ветка `feat/htf-bias-v2-premium-discount`, `config/settings.py: VERSION = "2.5.0"`).
**Метод:** чтение исходников и сверка утверждений документации/комментариев с фактическим кодом. Никаких прогонов, БД, логов и `.env` в архиве нет — все выводы о поведении помечены как `[код]` (доказано чтением кода), `[док]` (взято из отчётов в репо) или `[гипотеза]` (требует прогона).
**Предыдущий аудит** (документный, от 2026-09-05) сохранён как `logic_up_prev.md`; сверка с ним — в разделе 6. Этот файл его ЗАМЕНЯЕТ как рабочее задание.

**Для mimo v2.5 (OpenCode):** каждая находка оформлена карточкой `Где / Что сейчас / Почему ошибка / Доказательство / Исправление / Проверка`. Номера строк — из этого архива. Раздел 7 — порядок внедрения, раздел 8 — обязательные тесты, раздел 9 — машиночитаемый список задач.

---

## 0. Правила работы для mimo (прочитать до правок)

1. **Сначала инструментирование, потом поведение.** Задачи фазы A (раздел 7) не меняют торговую логику — они делают её измеримой. Без них любая правка параметров недоказуема.
2. **Одна правка — один тест, который падает ДО и проходит ПОСЛЕ.** Тесты писать путём, которым идёт живой пайплайн (`scan_symbol_v2`, а не голая функция), где это возможно; где нельзя (нужны сеть/БД) — на вырезанной функции с подставными данными той же ФОРМЫ, что живые (DataFrame с `DatetimeIndex`, длиной больше lookback).
3. **Не «чинить» параметры без A/B на v2-бэктесте.** Все существующие отчёты (`docs/reports/*`, `docs/score.md`) описывают LEGACY-движок (см. P0-9). Их цифры нельзя переносить на v2.
4. **Каждое изменение гейта/порога → bump `_CONFIG_VERSION` в `scheduler/scanner.py:90` и добавление ключа в `build_config_snapshot()`** (см. P1-13), иначе трассы разных версий неразличимы.
5. **Флаги.** Новое поведение — за флагом с дефолтом «как сейчас», кроме исправлений явных багов (P0-1, P0-2, P0-3, P0-5, P0-6), где старое поведение сохранять нечего.
6. **Не трогать в этом заходе:** legacy `strategy/signal_engine.py`, `backtest/engine.py` (они про старый движок), Telegram-слой, web.

---

## 1. Краткая независимая оценка

Архитектура v2 (Pattern Engine → Feature Builder → Probability Engine → Risk Engine + набор жёстких гейтов) — разумная и в целом соответствует ICT-логике «sweep → displacement → MSS → OB/FVG retest → target на ликвидности». Но фактическая реализация расходится с замыслом в нескольких местах так, что **сегодняшний поток сигналов определяется не стратегией, а побочными эффектами кода**:

1. **Индексы и временные метки в детекторах живут в разных системах координат** (`reset_index` в sweep/OB/FVG). Из-за этого: временная привязка OB/FVG к свипу не работает, возраст OB в сканере завышен на ~100 свечей, «temporal binding» в `find_ob_for_sweep` мёртв. Это самый вероятный корень низкого `has_ob` (0–5.8% по H-006) и части отказов «OB too old». — **P0-1**
2. **Медвежий BOS проверяется по самому СТАРОМУ swing low, бычий — по самому НОВОМУ.** Направленная асимметрия валидности OB для шортов. — **P0-2**
3. **`as_of_utc`, `data_age_ms`, `entry_candle_open` всегда `None`** — код ищет колонку `timestamp`, а она в индексе. Аудит-лог слеп по времени, защита «не оценивать outcome на свече входа» не работает. — **P0-3**
4. **Live-оценка исходов оптимистична (TP раньше SL в одной свече), бэктест — пессимистичен (SL раньше TP).** Плюс time-stop выключен, TTL 7 дней → `EXPIRED` с PnL 0, а закрытия менеджера позиций (`FLIP_BIAS`/`SWEEP_BREACH`) переписываются в `HIT_TP`/`HIT_SL` по знаку PnL. Статистика и метки для ML смешивают разные события. — **P0-4**
5. **Phase 8: сигнал и outcome сохраняются ДО проверки дневных лимитов и не откатываются при блокировке** (комментарий обещает откат). Появляются «сироты», которые считаются в лимитах позиций и статистике. — **P0-5**
6. **Лимиты позиций по направлению никогда не срабатывают** (`o.signal` не существует на объекте outcome). — **P0-6**
7. **HTF-контекст не доезжает до Probability Engine в live** (`htf_alignment_score`/`premium_discount_score` не передаются, `htf_bias_penalty` всегда 1.0), а в v2-бэктесте передаётся → live и backtest считают разные P(TP). — **P0-7**
8. **Entry trigger — пустая операция** (`current_price = entry_price`). — **P0-8**
9. **Доказательной базы для v2 нет:** `backtest/engine.py` прогоняет legacy `signal_engine`; v2-раннер `run_new_pipeline.py` не содержит половины live-гейтов. — **P0-9**
10. «Shadow»-движки (Market Thesis, Decision, Market Phase на заглушках) **влияют на размер позиции и entry-target**, а граф ликвидности получает `new_bar=True` четыре раза за одну 1h-свечу (сканы каждые 15 минут). — **P1-7, P1-8**
11. Три разных минимума RR (1.5 / 2.0 / 2.5 в ТЗ), выбор TP по приближённому SL (1.5 ATR), а не по реальному; `sl_min_atr_multiplier = 2.0` в Risk Engine противоречит структурному SL и создаёт «мёртвую зону» при ATR ≥ 2.5%. — **P1-4, P1-5**
12. Rules-P(TP) — это аддитивный скор с неподтверждёнными множителями (FRESH OB ×1.25, `expected_rr × 1.1`), на который навешаны пороги 0.30/0.40/0.50 как на калиброванную вероятность. — **P1-6**

**Вердикт:** до исправления P0-1…P0-9 бот нельзя оценивать по результатам — цифры, которые он произведёт, не будут отражать стратегию. После фазы A/B (раздел 7) нужен честный v2-бэктест с теми же гейтами, что в live, и только по нему — калибровка параметров.

---

## 2. Пайплайн как он есть (карта для навигации)

`scheduler/tasks.py:26-28` — cron `minute="2,17,32,47"` (UTC) → `run_scan_cycle` для ВСЕХ `primary_timeframes` (`1h,4h`) сразу (`scanner.py:2168-2202`, `asyncio.gather` по symbol×TF под `_scan_lock`).

`scan_symbol_v2` (`scheduler/scanner.py`):
- Phase 0: cooldown (`_is_cooldown_active`, в `ob_aware` всегда False, :185-192) → portfolio risk (:272-295) → daily limits (:296) → position limits (:360-376) → индикаторы → `_as_of_utc` (:400-410) → volatility gate (:412-425).
- Phase 1: `detect_sweeps(lookback=50)`, `detect_order_blocks(lookback=100)`, `analyze_last_candle`, `detect_fvg(lookback=100)` (:445-448); для каждого валидного свипа `find_ob_for_sweep(lookback=20)` (:453-482); `_reclaim = _valid_sw[0].reclaim_candles` (:489-491); `analyze_structure(lookback=50, …)` (:493-499); `pattern_engine.detect(...)` (:505-512).
- Гейты: reversal (sweep+MSS), continuation (BOS), entry zone (soft, флаг off), confirmation score, breakout quality (soft; hard off, :696-716), **OB retest (hard, :728-832)**, session (off, :835), HTF POI (:847-862), **HTF bias v2 (hard, :871-985)**, premium/discount (off).
- Trade Engine (`strategy/trade_engine.py`) → `entry_price = ind.close` (:1108) → LTF confirm только в `multi_tf` (:1110-1116).
- Shadow: Market Phase (:1185-1200), Market Thesis/LiquidityGraph (:1221-1330), Hypothesis/Decision (:1330-1444), Scenario Engine.
- Phase 2: MTF (`required_alignment=1` для reversal, :1505), context (10s timeout), OB state multiplier, `feature_builder.build(...)` (:1559-1580).
- Phase 3: `probability_engine.predict` → `min_p_tp` gate (:1663-1687).
- Phase 4: `risk_engine.evaluate(... scenario_score=_thesis_score, scenario_stability=_thesis_stability, mss_quality=setup.mss_score)` (:1700-1760).
- Phase 4.5: entry trigger (:1762-1800). Phase 6: dedup (:1858-1935). Phase 7: spread/depth/TOCTOU/`save_signal` (:1940-2090). Phase 8: `create_outcome` → `daily_limits.try_open_trade` → `_set_cooldown` → notify (:2120-2145).

Данные: `data/exchange_client.py:347-357` — `timestamp` становится **индексом** DataFrame, последняя (формирующаяся) свеча отбрасывается (`iloc[:-1]`).

---

## 3. P0 — дефекты, которые меняют результат (исправлять первыми)

### P0-1 · Две системы координат в детекторах: относительные индексы и «1970-е» timestamps

- **Где:**
  - `liquidity/sweep.py:141` `data = df.tail(lookback).reset_index(drop=True)`; `:163` `ts = _to_datetime(data.index[i])`; `:285-289` `_to_datetime(int) → datetime.fromtimestamp(i, utc)`.
  - `liquidity/order_blocks.py:100` `data = df.tail(lookback).reset_index(drop=True)`; `:137-138, :167-168` `timestamp=ts, candle_index=i` (относительный i); `:352-356` тот же `_to_datetime`.
  - `liquidity/fvg.py:61` тот же `reset_index`; `:90,:103,:140`.
  - `liquidity/order_blocks.py:219-225` `find_ob_for_sweep`: `for i in range(sweep_index-1, ...)`; `ts = _to_datetime(data.index[i]); if ts < sweep_timestamp: break` — здесь `data` = `_df_clean` (реальные timestamps 2026), а `sweep_timestamp` = `SweepEvent.timestamp` = 1970-01-01 + i секунд.
  - `strategy/pattern_engine.py:497-527` `_detect_entry_zones`: `if ob.timestamp < sweep_timestamp: continue` (и то же для FVG).
  - `scheduler/scanner.py:741` `_ob_age = len(_df_clean) - _nearest_ob.candle_index - 1`.
- **Что сейчас `[код]`:**
  1. `SweepEvent.timestamp`, `OrderBlock.timestamp`, `FVG.timestamp` = `1970-01-01T00:00:0i` (i — позиция внутри `tail(N)`), потому что после `reset_index(drop=True)` индекс — целое.
  2. `SweepEvent.candle_index = offset + i` — АБСОЛЮТНЫЙ (правильно). `OrderBlock.candle_index = i` — ОТНОСИТЕЛЬНЫЙ к `tail(100)`. `CHoCH/BOS.candle_index` в `market_structure/structure.py:242-258` — абсолютный (`offset + i`, без reset).
  3. `find_ob_for_sweep`: сравнение `2026 < 1970` всегда False → guard никогда не срабатывает; функция сканирует назад без временной привязки. (Если бы timestamps были настоящими, guard сработал бы на ПЕРВОЙ итерации — свеча перед свипом всегда старше — и функция всегда возвращала бы `None`. То есть контракт «OB не раньше свипа» противоречит самому циклу «ищем OB ДО свипа».)
  4. `pattern_engine._detect_entry_zones`: сравнивает «1970 + i_sweep(0..49)» с «1970 + i_ob(0..99)» — два разных отсчёта (tail(50) vs tail(100)); OB из `find_ob_for_sweep` имеют настоящие 2026-timestamps и проходят всегда. Временная привязка фактически случайна.
  5. Сканер считает возраст OB от полного `_df_clean` (~199 строк при `candles_limit=200` и `iloc[:-1]`), а `candle_index` — от `tail(100)`. `_filter_by_age` внутри `detect_order_blocks` оставляет OB с `99 - i <= 35` → `i >= 64` → в сканере `_ob_age = 199 - i - 1 ∈ [99, 134]` → **любой не-retested OB из `detect_order_blocks` блокируется «OB too old» (`_max_age=35`)**. OB, пришедшие из `find_ob_for_sweep`, имеют абсолютный индекс и проходят проверку возраста — но они `has_bos=False` → `is_valid=False` (см. P1-2), поэтому в `_relevant_obs` не попадают вовсе.
- **Почему ошибка:** одно поле `candle_index` означает разное в двух модулях; timestamps не являются временем. Любая логика «после/до/возраст» на этих полях недостоверна.
- **Влияние:** прямое — на `has_ob` (docs/hypotheses.md H-006: 0–5.8%), на долю отказов `OB too old`, на entry zones, на дедуп по OB (`ob_midpoint` берётся от «первого валидного» OB). Косвенное — на все документы, где по этим полям делались выводы.
- **Исправление (для mimo):**
  1. В `detect_sweeps`, `detect_order_blocks`, `detect_fvg`: не терять исходный индекс. Вариант: `data = df.tail(lookback)` (без reset), `offset = len(df) - len(data)`, позиционный доступ через `.iloc`, `candle_index = offset + i`, `timestamp = data.index[i]` (реальная метка). Аналог уже сделан в `sweep.py:145-146` для `candle_index` — распространить на timestamp и на OB/FVG.
  2. `_filter_by_age`: принимать `total_candles=len(df)` (не `len(data)`) или считать возраст по абсолютному индексу.
  3. `find_ob_for_sweep`: убрать `break` по timestamp; вместо этого ограничить поиск окном `[sweep_index - lookback, sweep_index - 1]` и вернуть OB с абсолютным индексом и реальным timestamp. Контракт в докстринге переписать: «OB формируется ДО свипа, в пределах lookback».
  4. `pattern_engine._detect_entry_zones`: заменить сравнение timestamps на сравнение абсолютных `candle_index` (`ob.candle_index >= sweep_candle_index` — если требуется «OB после свипа», это вопрос стратегии; см. P1-2: у sweep-OB по ICT блок ДО импульса, т.е. до/на свипе). Решение зафиксировать явно флагом `ENTRY_ZONE_TEMPORAL_MODE = "after_sweep" | "any"`.
  5. `scanner.py:741`: считать `_ob_age = (len(_df_clean) - 1) - _nearest_ob.candle_index` только после того, как `candle_index` стал абсолютным; добавить `assert 0 <= _ob_age < len(_df_clean)` (в тесте).
- **Проверка:** тест на DataFrame длиной 199 с `DatetimeIndex`: (a) у всех событий `timestamp.year == index.year`; (b) `candle_index` OB/FVG/sweep/CHoCH ссылаются на одну и ту же свечу при сверке `df.index[candle_index] == event.timestamp`; (c) возраст OB, стоящего 5 свечей назад, равен 5 в сканерной формуле; (d) подсадка: вернуть `reset_index(drop=True)` → тест красный.
- **Риск регрессии:** после починки резко изменится доля `has_ob` и отказов `ob_retest` — это ожидаемо; сравнивать воронку до/после (фаза A инструментирования).

### P0-2 · Асимметрия BOS: медвежий OB требует пробоя САМОГО СТАРОГО swing low

- **Где:** `liquidity/order_blocks.py:285` `prev_swing_high = max(relevant_highs, key=index)` (последний swing high) vs `:301` `prev_swing_low = min(relevant_lows, key=index)` (**первый**, самый старый swing low в окне).
- **Что сейчас `[код]`:** для бычьего OB BOS = пробой последнего swing high (ICT-корректно). Для медвежьего — пробой самого старого swing low в 100-свечном окне, что при нисходящей структуре почти всегда далеко ниже → `has_bos=False` → `is_valid=False` → медвежьих валидных OB почти нет.
- **Доказательство:** код; `tests/test_liquidity.py` импортирует `_check_bos_bearish`, но кейс с двумя swing low, где пробит только последний, отсутствует (grep пуст).
- **Исправление:** `max(relevant_lows, key=lambda s: s["index"])`.
- **Проверка:** тест: два swing low (старый 100, новый 105), цена после OB падает до 104 → ожидается `True`; на текущем коде — `False`.
- **Влияние:** шорт-сигналы (уже под порогом `min_p_tp_short=0.40` и `block_short_in_bullish_htf`) дополнительно режутся на уровне OB. После фикса ожидать рост числа медвежьих OB — проверить воронку.

### P0-3 · `timestamp` ищется в колонках, а живёт в индексе → `as_of_utc`, `data_age_ms`, `entry_candle_open` всегда `None`

- **Где:** `data/exchange_client.py:347-349` (`set_index("timestamp")`), `:357` (`iloc[:-1]`); `scheduler/scanner.py:403` `if ... 'timestamp' in df.columns` (всегда False); `:1942-1948` `df.iloc[-1].get("timestamp")` (Series из OHLCV → `None`).
- **Что сейчас `[код]`:** `_as_of_utc`/`_data_age_ms` во всех `_audit_log(...)` = `None`; `entry_candle_open` в `save_signal` = `None`. В `scheduler/outcome_tracker.py` защита «пропустить, если текущая свеча = свеча входа» опирается на `entry_candle_open` (тесты `tests/test_outcome_tracker.py:41-52` подставляют его вручную, т.е. живой путь не покрыт).
- **Почему ошибка:** нет point-in-time контракта: нельзя доказать, на какой закрытой свече принято решение, и нельзя отличить «сигнал на свече T» от «повторный скан той же свечи».
- **Исправление:**
  1. Ввести в `exchange_client.fetch_ohlcv` явный контракт: DataFrame с `DatetimeIndex(name="timestamp", tz=UTC)`, последняя строка — последняя ЗАКРЫТАЯ свеча. Документировать в докстринге.
  2. В сканере: `_as_of_utc = df.index[-1].to_pydatetime()` (открытие последней закрытой свечи) и `_bar_close_utc = _as_of_utc + tf_delta`; `data_age_ms = now - _bar_close_utc`. `entry_candle_open = df.index[-1]`.
  3. Добавить «bar guard» (см. P1-8): не оценивать один и тот же `(symbol, tf, df.index[-1])` дважды.
- **Проверка:** unit-тест с подставным `fetch_ohlcv` → в `_audit_log` и `save_signal` попадают ненулевые `as_of_utc`/`entry_candle_open`, равные `df.index[-1]`; подсадка `'timestamp' in df.columns` → тест красный.

### P0-4 · Исходы: TP-first в live против SL-first в бэктесте; time-stop выключен; перезапись причин закрытия

- **Где:** `scheduler/outcome_tracker.py:511-525` (`hit_tp` вычисляется и обрабатывается раньше `hit_sl`); `:31-48` `_TIME_STOP_BY_TF` определён, `:627` «Time Stop — PAUSED»; `:273-280` TTL `OUTCOME_TTL_DAYS` (7) → `EXPIRED` с `pnl_pct=0.0`; `:241-259` `_normalize_close_reason` → `FLIP_BIAS`/`SWEEP_BREACH` становятся `HIT_TP`/`HIT_SL` по знаку PnL; `:362-366` high/low берутся у ПОСЛЕДНЕЙ ЗАКРЫТОЙ свечи (`fetch_ohlcv(limit=2)` после `iloc[:-1]` — одна закрытая свеча), а `current_price` — тикер.
  Бэктест: `backtest/engine.py:497-516` и `backtest/run_new_pipeline.py:131-145` — **сначала SL, потом TP**.
- **Что сейчас `[код]`:** если одна свеча касается и SL, и TP, live засчитывает TP, бэктест — SL. Time-stop не действует: сделка живёт до TP/SL или 7 дней (на 1h это 168 баров, на 4h — 42), после чего `EXPIRED` с PnL 0 независимо от фактического P&L на момент истечения. Метки ML (`ml/config.py:25` `MAX_BARS=12`) описывают другой объект, чем live-outcome. Закрытия менеджера позиций переименовываются в TP/SL → статистика WR и `scenario_memory` содержат события, не являющиеся касанием барьеров.
- **Почему ошибка:** (а) систематическое завышение live-WR относительно бэктеста и относительно честной оценки; (б) три разных определения «исхода» (live, backtest, ML-label) → сравнивать нечего; (в) TTL-`EXPIRED` с PnL 0 скрывает реальный результат.
- **Исправление:**
  1. Единая функция `resolve_bar_exit(direction, sl, tp, bar_high, bar_low, policy)` в отдельном модуле, используемая и трекером, и обоими бэктестами. `policy="pessimistic"` (SL-first) по умолчанию; опционально `"ltf"` — дорешивать по свечам меньшего TF.
  2. Включить time-stop: `hold_bars >= MAX_BARS_BY_TF` (согласовать с `ml/config.MAX_BARS`, т.е. 12 баров) → закрытие по текущей цене с `close_reason="TIME_STOP"` и реальным PnL; `EXPIRED` по TTL оставить только как аварийный случай и тоже с реальным PnL.
  3. Хранить `close_reason_raw` отдельной колонкой; в статистику/ML брать только барьерные исходы (`HIT_TP`/`HIT_SL`/`TIME_STOP`), а закрытия менеджера позиций считать отдельной категорией.
  4. `hold_bars` считать по числу закрытых свечей от `entry_candle_open` (после P0-3), а не по wall-clock.
- **Проверка:** тест на свечу, касающуюся обоих барьеров → live и backtest дают одинаковый исход; тест на time-stop; тест, что `FLIP_BIAS` не превращается в `HIT_TP`.

### P0-5 · Phase 8: сигнал и outcome сохраняются до проверки дневных лимитов и не откатываются

- **Где:** `scheduler/scanner.py:2120-2139`: `create_outcome(saved_signal.id)` → `daily_limits.try_open_trade(...)` → при `not _dl_allowed`: `return None` (без удаления signal/outcome; комментарий «If either fails, we roll back both» не соответствует коду). `save_signal` уже выполнен на Phase 7 (`:2054`).
- **Что сейчас `[код]`:** при срабатывании дневного лимита в БД остаются «сирота»-сигнал и открытый outcome: он попадает в `get_open_outcomes()` (лимит `max_positions_total`, `:366-373`), в трекер исходов, в статистику и в `dedup` (последний сигнал по symbol/tf). Кроме того, `daily_limits.can_open_trade` уже проверяется в Phase 0 (`:296`), т.е. вторая проверка «после факта» ловит только гонку между параллельными задачами `gather` — и именно в этой гонке оставляет мусор.
- **Исправление:**
  1. Перенести `try_open_trade` (резервацию риска) ПЕРЕД `save_signal`; при отказе — не сохранять ничего. Резервацию делать под `asyncio.Lock` (задачи параллельны).
  2. Если сохранение/notify упало после резервации — вызвать `daily_limits.release(risk)` (добавить метод) и удалить/пометить сигнал `status="aborted"`.
  3. Идемпотентность: уникальный индекс `(symbol, timeframe, entry_candle_open, direction)` в `signals` (после P0-3) — защита от дублей при повторном скане той же свечи.
- **Проверка:** тест: два параллельных `scan_symbol_v2` при остатке лимита на одну сделку → в БД ровно один сигнал и один outcome; подсадка «вернуть порядок как сейчас» → два outcome.

### P0-6 · Лимиты позиций по направлению никогда не работают

- **Где:** `scheduler/scanner.py:368-371` `hasattr(o, 'signal') and o.signal and o.signal.direction == "BUY"`; в `storage/database.py` `relationship(` для outcome→signal не определён (grep пуст), у `Signal` поле называется `signal_type` (см. `outcome_tracker.py:512`), а не `direction`.
- **Что сейчас `[код]`:** `_long_positions = _short_positions = 0` всегда → `max_positions_long/short` (3/3) мертвы; действует только `max_positions_total` (5), в который входят и сироты из P0-5.
- **Исправление:** `db.get_open_outcomes_with_signals()` (join по `signal_id`), считать по `signal.signal_type`; добавить корреляционный лимит по базовому активу (BTC/ETH/…) как часть той же выборки.
- **Проверка:** тест: 3 открытых BUY-outcome → четвёртый BUY блокируется `position_limits`, SELL проходит.

### P0-7 · HTF-контекст не попадает в Probability Engine (live), но попадает в бэктест

- **Где:** `scheduler/scanner.py:1559-1580` — `feature_builder.build(...)` без `htf_alignment_score`, `premium_discount_score`, `sr_levels`; `:862` `_htf_bias_penalty = 1.0` — единственное присваивание (grep), значение никогда не меняется; `strategy/feature_builder.py:119-120` (поля `None`), `:217-218` (в `to_dict()` `None → 0.5`); `strategy/probability_engine.py:311-318` множители применяются только при `is not None` → в live не применяются; `backtest/run_new_pipeline.py:520-521` — передаёт `htf_alignment_score=htf_score, premium_discount_score=pd_score`.
- **Что сейчас `[код]`:** в live rules-P(TP) не знает о HTF ничего, кроме того, что противонаправленные сетапы уже заблокированы hard-gate'ом (P1-10). Для ML-модели признаки `htf_alignment_score=0.5`, `premium_discount_score=0.5`, `htf_bias_penalty=1.0` — константы. В бэктесте те же признаки заполнены → `p_tp` ниже (множитель `0.5+0.5·score`), гейт `min_p_tp` режет иначе → **бэктест и live не сравнимы по построению**.
- **Исправление:**
  1. В сканере после HTF bias v2 вычислять `htf_alignment_score ∈ [0,1]` из `HTFBiasResult` (например `strength`: strong→1.0, moderate→0.75, weak→0.6, neutral→0.5, против→0.0 — но «против» уже блокируется) и передавать в `build(...)`. Аналогично `premium_discount_score` (модуль есть, флаг off — либо считать всегда как признак, либо не передавать нигде, включая бэктест).
  2. `htf_bias_penalty`: либо удалить признак (мёртв), либо вычислять (0.8 при слабом противоречии, если hard-gate отключён).
  3. Убрать из `to_dict()` подмену `None→0.5` для ML или сделать её явным признаком `htf_known ∈ {0,1}`.
- **Проверка:** тест путём человека (`scan_symbol_v2` с подставными HTF-данными): `features.htf_alignment_score is not None`; тест паритета: одинаковые входы → одинаковый `p_tp` у сканера и `run_new_pipeline`.

### P0-8 · Entry trigger — пустая операция

- **Где:** `scheduler/scanner.py:1762-1780`: `_entry_target = SimpleEntryTarget(direction, entry_price)`; `entry_trigger.check(hypothesis=_entry_target, current_price=entry_price, ...)`; `strategy/entry_trigger.py:68-69, 105-128` — проверка близости 0.3% к `entry` и спреда ≤ 0.1%.
- **Что сейчас `[код]`:** расстояние цена–вход всегда 0 → срабатывает всегда; единственный реальный эффект — второй спред-фильтр (0.1%) вдобавок к `max_spread_percent=0.15` в Phase 7. Причём `_entry_target` существует только когда shadow-`DecisionEngine` вернул `trade=True` (`:1762`), т.е. гейт зависит от «теневого» движка.
- **Исправление:** `current_price` брать из тикера (`last`/mid), `entry` — из плана (`ind.close` последней закрытой свечи). Определить политику входа явно: (a) «вход по рынку, если цена в пределах X% от close» или (b) «лимитный вход в зону OB/FVG» (тогда trigger должен проверять, что цена ВНУТРИ зоны, а не около close). Убрать зависимость от `_decision`.
- **Проверка:** тест: цена ушла на 1% от close → блок; в пределах 0.3% → проход.

### P0-9 · Доказательная база относится к legacy-движку; v2-бэктест не равен live

- **Где:** `backtest/engine.py:46, :589` — `signal_engine.evaluate(...)` (legacy EMA/RSI/MACD скоринг), структура/свипы/OB считаются, но решение принимает legacy-скор; все отчёты `docs/reports/*` (report_v3: baseline WR 30.3%, PF 0.46; `docs/score.md`: Score=5 WR 60.6%, expansion 62%) — про него. `logic_up2.1.md §0.5` это уже фиксировал («96.8% — legacy статистика»).
  `backtest/run_new_pipeline.py` (v2): HTF bias **v1** (`get_htf_bias`, :45, :423), нет OB-retest gate, breakout quality, session, ob_aware dedup, entry trigger, execution filters, thesis/decision sizing; `COOLDOWN_BARS=3`, `MAX_TRADE_DURATION=72`, дефолт `--timeframe 4h`, символы `BTC/ETH/ZRO`; передаёт HTF/PD-score (P0-7); выход SL-first (P0-4).
- **Почему ошибка:** любые выводы вида «regime edge», «Score=5», «structural SL хуже ATR» получены на другом движке; для текущего пайплайна нет ни одного воспроизводимого числа.
- **Исправление:**
  1. Вынести из `scan_symbol_v2` чистую функцию `evaluate_candidate(window_df, htf_frames, ticker_snapshot, cfg) -> CandidateDecision` без I/O (детекторы → гейты → план → признаки → P(TP) → risk). Сканер и бэктест зовут ЕЁ. Shadow-движки — за флагом и по умолчанию не влияют (P1-7).
  2. `run_new_pipeline` использует `evaluate_candidate` + `resolve_bar_exit` (P0-4) + тот же `build_config_snapshot`.
  3. Тест паритета: одинаковый `window_df` → одинаковые `trace.gates` у сканера (с подставным I/O) и у бэктеста.
- **Проверка:** после этого — прогон на ≥ 20 символах × {1h, 4h} × ≥ 180 дней с воронкой отказов по гейтам; только его цифры считать доказательством.

---

## 4. P1 — логические и параметрические перекосы

### P1-1 · Детекция свипов

- **Где:** `liquidity/sweep.py:125-207`, `:47-54`, `:56-105`, `:109-111`.
- **Факты `[код]`:**
  - Событие создаётся для КАЖДОГО прошлого swing-уровня, который свеча «проколола и закрылась обратно» (вложенные циклы `:160-207`): одна свеча может дать N событий с одинаковыми полями; дедупа нет.
  - Параметр `swing_window` игнорируется — свинги считаются `detect_swings(left_bars=2, right_bars=2, strict=True)` (`:151-154`); при этом бэктест зовёт `detect_sweeps(..., swing_window=5)`, `detect_order_blocks` использует 5/5 non-strict, `structure.py` — окно 5 с `==max`. Три модуля — три определения swing point.
  - `is_valid` = `reclaim_candles <= liquidity.sweep_max_reclaim_candles (2)` (`:53`; объём — только в `strength`). Счётчик реклейма ограничен 10 (иначе 10).
  - Ложные фильтры (`:74-96`): `sweep_max_body_beyond_level` на самом деле измеряет ВИК за уровнем; `sweep_min_body_size` измеряет полный диапазон свечи; поля `atr` и `pool_age_bars` никогда не заполняются (`:47-48` дефолт 0) → ATR-фильтр и фильтр возраста пула **никогда не срабатывают** (`if atr > 0`, `pool_age_bars > max` при 0).
  - Сканер берёт `_reclaim = _valid_sw[0]` (`scanner.py:491`) — самый СТАРЫЙ валидный свип в окне (события в хронологическом порядке), тогда как Pattern Engine выбирает «самый сильный, при равенстве — самый свежий» (`pattern_engine.py:281-289`). MSS-классификация и сетап могут ссылаться на разные свипы.
- **Рекомендации:**
  1. Дедуп: для свечи оставлять один свип на направление — по ближайшему к цене уровню (или по самому «свежему» пулу) + список всех снятых уровней в поле `swept_levels`.
  2. Единый `detect_swings` с параметром из конфига (`liquidity.sweep_swing_window`, сейчас мёртв) — один и тот же во всех трёх модулях.
  3. Заполнять `atr` и `pool_age_bars` при детекции (ATR из `_calc_atr`, возраст = `i - swing.index`); переименовать фильтры по смыслу (`wick_beyond_level_atr`, `range_pct`).
  4. `_reclaim` брать у того же свипа, который выбрал Pattern Engine (вернуть выбранный свип из `detect` или передавать `reclaim` через `ICTSetup`).
- **Проверка:** таблица проб (свеча, снявшая 3 старых уровня → 1 событие; пул возрастом 150 баров → отбраковка; свеча с большим телом за уровнем → отбраковка).

### P1-2 · Детекция Order Block'ов

- **Где:** `liquidity/order_blocks.py:115-190`, `:39-53` (`is_valid`), `:191-260` (`find_ob_for_sweep`, `has_bos=False`), `strategy/pattern_engine.py:497-510`.
- **Факты `[код]`:**
  - Displacement оценивается ТОЛЬКО по закрытию следующей свечи (`next_move_pct`, `:128, :158`) и требует ≥ `ob_min_displacement_pct` (2.5%) — для BTC/ETH 1h (типичный ATR 0.4–1%) это редкое событие; ICT-displacement — это нога из нескольких свечей (уже так сделано в `structure.py:176-186` для MSS).
  - `is_valid` требует `has_bos` И `displacement_atr ≥ 1.5` И `volume_ratio ≥ 1.8`. OB из `find_ob_for_sweep` создаются с `has_bos=False` (`:241, :257`) → **никогда не валидны** → не попадают ни в `has_ob`, ни в OB-retest gate. Т.е. «OB для свипа» существует в коде, но в решении не участвует.
  - `_detect_entry_zones` берёт ПЕРВЫЙ валидный OB нужного направления в порядке списка и `break` (`:510`) — это самый старый OB, а не ближайший/свежий.
  - Retest помечается любым касанием зоны позже (`_check_retest_*`), после чего OB в сканере освобождается от проверки возраста (`scanner.py:743`).
- **Рекомендации:**
  1. Displacement для OB измерять как в MSS: максимальное тело/диапазон в ноге из ≤ N свечей после OB, в ATR; порог 1.5 ATR оставить, `ob_min_displacement_pct` перевести в soft-признак.
  2. Sweep-OB: валидировать не через `has_bos`, а через связку с MSS (свип → OB → CHoCH) — это и есть ICT-модель reversal-входа; завести отдельный `validity_source ∈ {bos, mss}`.
  3. В entry zones выбирать OB по правилу (ближайший к цене выше/ниже, не пробитый), а не первый в списке.
  4. `ob_max_age_candles=35` на 1h = 1.5 дня: разумно для 1h, для 4h (6 дней) — проверить на данных; сделать TF-зависимым.
- **Проверка:** после P0-1/P0-2 снять воронку `has_ob` по TF; ожидать двузначные проценты. Тест: OB со свипом и последующим CHoCH → `is_valid`.

### P1-3 · MSS/CHoCH: семантика и задержка

- **Где:** `market_structure/structure.py:318-392`, `:145-230`, `:84-121`; `scheduler/scanner.py:493-499`.
- **Факты `[код]`:**
  - «CHoCH» = новый swing high выше предыдущего при медвежьем/смешанном тренде (и симметрично). Это не пробой закрытием, а факт формирования более высокого свинга; событие датируется индексом самого свинга (`candle_index=curr_h.candle_index`), который подтверждается только через `swing_window=5` свечей → структурный сигнал становится известен с задержкой ≥ 5 баров после экстремума (на 4h — ≥ 20 часов).
  - В одной итерации могут сработать и бычья, и медвежья ветки → `last_choch` перезаписывается последней.
  - MSS = валидный противонаправленный свип в окне ≤ 10 баров до CHoCH (`max_causal_bars=10`) + displacement ≥ 0.2 ATR (снижено с 0.5 фиксом 2026-09-04, `:202-207`) + `reclaim ≤ 2`. Порог 0.2 ATR при измерении «максимальным телом в ноге» — это почти любая нога; порог фактически снят.
  - `htf_aligned` в `calc_mss_score` никогда не передаётся (`analyze_structure(..., htf_aligned=False)` по умолчанию; сканер не передаёт) → `mss_score ≤ 80`, бонус `mss_score >= 70` в P(TP) достижим только при идеальных остальных компонентах.
- **Рекомендации:**
  1. Зафиксировать определение CHoCH/MSS в терминах ЗАКРЫТИЯ: закрытие за последним противоположным swing (структурный пробой), дата = свеча пробоя. Сохранить текущую «свинговую» версию под флагом для сравнения.
  2. Передавать `htf_aligned` из HTF bias v2 (после P0-7 это одно значение на сетап).
  3. Порог displacement для MSS: измерять относительно ATR ноги и держать ≥ 0.5–1.0 ATR как SOFT-признак с логом распределения; hard-порог 0.2 сейчас не отсекает ничего — это надо показать гистограммой в фазе A.
- **Проверка:** таблица проб на синтетике: sweep→CHoCH через 3 бара → MSS; через 15 баров → нет; отсутствие свипа → нет.

### P1-4 · Выбор цели и RR: три порога и приближённый SL

- **Где:** `strategy/trade_engine.py:294-340` (`type_bonus`, `min_distance = 1 ATR`, `sl_dist = abs(entry - (current_price - atr*1.5))` — приближение), `:230` (`best = max(score)`), `:242` (`min_rr_threshold=1.5` только аннотация); `strategy/trade_plan.py:30-35` (`score = strength × min(1, rr/3) × path`); `risk/engine.py:162-183` (RR нетто с учётом 0.1% round-trip, `min_rr_ratio=2.0` hard); `config/settings.py:654-655` (комментарий: ТЗ §7.1 требует 2.5).
- **Факты `[код]`:** цель выбирается по RR, посчитанному от условного SL 1.5 ATR, а не от реального SL (invalidation ± буферы, P1-5). Скор насыщается при RR ≥ 3, поэтому все цели дальше 4.5 ATR равноценны и решает `type_bonus` (old_high 2.0 > equal 1.8 > OB 1.5 > FVG 1.2 > swept 0.5 — числа без обоснования). Затем Risk Engine пересчитывает RR по реальному SL и может отклонить сетап, хотя более близкая цель с RR ≥ 2 существовала.
- **Рекомендации:**
  1. Передавать реальный `sl` в `_find_targets` и считать RR по нему; выбор цели: «ближайшая цель с чистым путём и RR_net ≥ min_rr», с приоритетом внешней ликвидности только при равном RR-классе. Альтернатива для исследования: `argmax P(reach|distance) × RR`.
  2. Один минимум RR в одном месте (`risk_engine.min_rr_ratio`); `trading.min_rr_threshold` удалить или сделать алиасом; решение 2.0 vs 2.5 принять по v2-бэктесту (фаза C), а не по комментарию.
  3. Логировать в трассу все кандидаты целей с их RR — для последующей калибровки бонусов.

### P1-5 · SL: буферы, ATR-пол и потерянный `sl_source`

- **Где:** `strategy/trade_engine.py:133` (`sl_buffer = 0.35 ATR`), `:162-166` (safety push: `+0.15 ATR + spread + tick` за экстремум текущей свечи), `:186-201` (HTF POI override) и `:266` (`sl_source=invalidation.type` — локальная `sl_source="htf_poi_…"` теряется); `strategy/htf_poi.py:180, :196-207` (override только РАСШИРЯЕТ SL; докстринг говорит «tighter» — неверно); `risk/engine.py:186-222` (`sl_absolute_min_pct=0.25`, `dynamic_sl_max = min(max(5%, 2.2·ATR%), 8%)`, `sl_min_atr_multiplier=2.0` hard); `strategy/invalidation.py` (приоритет: sweep extreme → OB boundary → swing → BOS → 1.5 ATR, `min_distance_pct=0.5`).
- **Факты `[код]`:** структурный SL получает +0.35 ATR (+0.15 ATR при push) → часто ≈ 0.5 ATR за структурой; затем Risk Engine требует SL ≥ 2×ATR — это уже не структурный стоп, а ATR-стоп с «косметикой». При ATR% ≥ 2.5 минимум (2×ATR) превышает `dynamic_sl_max` → сетапы отклоняются как «SL too tight» и «SL too wide» одновременно (`logic_up2.1.md §0.7` это уже показал). `docs/score.md` («ATR ≈ BOS ≈ Structural по WR») — legacy-данные, для v2 не аргумент.
- **Рекомендации:**
  1. `sl_min_atr_multiplier` → soft-признак (`sl_atr_ratio` уже в фичах) или 1.0; hard-минимум оставить только абсолютный (0.25%) и «за экстремум свечи входа».
  2. Записывать `sl_source` из локальной переменной (`trade_engine.py:196` → `:266`), иначе статистика по источникам SL не различает HTF POI.
  3. Починить комментарий/логику `get_htf_sl_level`: решить, нужен ли override только «шире» (защита от преждевременного выбивания) — тогда переименовать; или «структурно ближе» — тогда логика обратная.
  4. Буферы 0.35/0.15 ATR — вынести в конфиг и проверить на v2-бэктесте распределение «сколько SL выбито виком в пределах буфера».

### P1-6 · Rules-P(TP): скор, а не вероятность

- **Где:** `strategy/probability_engine.py:170-177` (база 50 или `scenario_memory` winrate при ≥ 10 закрытий), `:180-214` (regime edges), `:217-298` (component/structure/volume/mtf/session/atr/ctx), `:311-340` (множители `htf/pd` — мертвы в live, `htf_bias_penalty=1.0`, `ob_state_multiplier`: FRESH ×1.25 / BROKEN → отказ), `:341` `expected_rr = rr × wr × 1.1`, `:340` clamp 20–85; `liquidity/ob_state.py:40-45`.
- **Факты `[код]`:** «P(TP)» = 50 + сумма рукописных надбавок (≤ ~+20) × множители; порог `min_p_tp_reversal=0.50` проходится почти любым reversal с MSS (50+3+3+4 = 60 ещё до объёма/MTF), а `min_p_tp_short=0.40` — практически всегда. Реальную фильтрацию дают hard-гейты, а не вероятность. `scenario_memory` после 10 закрытий подменяет базу winrate'ом — при 10 наблюдениях это шум (95% ДИ ±30 п.п.), и он создаёт петлю: плохая серия → база < 50 → reversal режется порогом 0.50 → выборка не растёт. Множитель FRESH ×1.25 и коэффициент 1.1 в `expected_rr` ничем не подтверждены. Regime edges (reversal лучше в range, хуже в expansion) опираются на legacy-цифры (`docs/score.md`).
- **Рекомендации:**
  1. Переименовать rules-выход в `quality_score` и логировать; пороги `min_p_tp*` применять к нему как к скору, значения выбрать по квантилям v2-бэктеста (фаза C).
  2. Убрать `× 1.1` в `expected_rr`; `ob_state_multiplier` ограничить сверху 1.0 (штрафы оставить).
  3. `scenario_memory` в базу — не раньше 30–50 закрытых исходов и со сглаживанием (Laplace/Beta prior).
  4. Ежедневный отчёт: Brier score / надёжность (reliability) для `p_tp` по закрытым исходам — без этого «P(TP)» останется словом.

### P1-7 · «Shadow» не является shadow

- **Где:** `scheduler/scanner.py:1221-1330` (`_thesis_score`, `_thesis_stability`), `:1712-1713` → `risk_engine.evaluate(scenario_score=…, scenario_stability=…)`; `risk/engine.py:258-273` (×[0.6,1.2] и ×[0.7,1.15]); `:1428-1444, :1762-1780` (`_decision.hypothesis` → entry target); `:1185-1200` (`MarketPhaseEngine.assess(... ema_fast_prev=0.0, ema_slow_prev=0.0, volume_ratio=1.0, range_pct=0.0, bars_in_range=20)`); `strategy/market_phase_engine.py:347` (`range_pct < 2.0` при 0.0 всегда истинно); `:1251-1253` `_liq_graph.update_on_candle(_candle_data, entry_price, new_bar=True)` при каждом скане.
- **Факты `[код]`:** размер позиции зависит от Market Thesis (диапазон ×0.42…×1.38 суммарно), entry trigger — от Decision Engine, а Market Phase получает заглушки вместо предыдущих EMA/диапазона/объёма. Граф ликвидности инкрементирует `current_bar` на каждом 15-минутном скане → на 1h 4 «бара» за бар, на 4h — 16; возраст узлов/decay/стабильность искажены.
- **Рекомендации:**
  1. `shadow_mode=True` (дефолт) → `scenario_score=0, scenario_stability=0` в Risk Engine и никакого `_entry_target` от Decision; результаты shadow-движков только в трассу.
  2. `update_on_candle(new_bar=…)` вызывать один раз на закрытую свечу (`df.index[-1]` изменился), иначе `new_bar=False`.
  3. Для Market Phase считать реальные `ema_*_prev`, `range_pct`, `volume_ratio`, `bars_in_range` из `df` или не вызывать вовсе до готовности.
- **Проверка:** тест: два скана подряд на одной свече → `graph.current_bar` не растёт; при `shadow_mode=True` `risk_pct` не зависит от `_thesis_score`.

### P1-8 · Планировщик и дедуп

- **Где:** `scheduler/tasks.py:26-28`, `config/settings.py:539` (`scan_minutes="2,17,32,47"`), `scheduler/scanner.py:185-192` (ранний cooldown мёртв в `ob_aware`), `:1858-1935` (cooldown = `max(45, tf_min × 2.0)` → 120 мин для 1h, 480 для 4h; разные OB → полный bypass; тот же OB → `cooldown // 3`; противоположное направление → половина), `config/settings.py:745-752`.
- **Факты `[код]`:** одна и та же закрытая свеча 1h оценивается 4 раза, 4h — 16 раз; различия между прогонами — тикер, HTF-данные, состояние shadow-графа (P1-7) и БД. Дедуп ob_aware может выпустить сигнал по тому же OB через 40 мин на 1h (160 на 4h), а по «другому OB» (> 0.5% от прошлого midpoint) — немедленно. Сигналы противоположного направления на той же свече допустимы через половину cooldown.
- **Рекомендации:**
  1. Bar guard: таблица/кэш `last_evaluated_bar[(symbol, tf)]`; повторно свечу не оценивать. Cron: для 1h — `:02`, для 4h — `:02` каждого 4-го часа (или один тик в 15 мин, но с guard'ом).
  2. Дедуп по идентичности сетапа: ключ `(symbol, tf, direction, setup_type, swept_level|ob_id)`; cooldown как страховка, а не основной механизм. `ob_proximity_pct=0.5` — сравнивать OB по `candle_index`/id после P0-1, а не по близости midpoint.
  3. Удалить мёртвый ранний cooldown либо сделать его честным (не зависящим от режима).

### P1-9 · OB-retest gate

- **Где:** `scheduler/scanner.py:728-832`; `liquidity/ob_state.py:224-270`; `config/settings.py:158` (`max_ob_distance_pct=3.0`), `.env.example:33-38`.
- **Факты `[код]`:** `get_ob_state` смотрит последние 10 свечей и возвращает состояние ПЕРВОЙ коснувшейся (старая «TESTED» скрывает более поздний «BROKEN»). Подтверждение — engulfing/pin-bar на текущей закрытой свече; «не касалось, но ближе 3%» → «OB not retested» (блок); т.е. гейт пропускает только «цена внутри OB или OB уже ретестили» + паттерн свечи. Вместе с P0-1(d) и P1-2 это объясняет, почему reversal-сигналы редки.
- **Рекомендации:** сканировать состояние по всем свечам после формирования OB в хронологическом порядке (последнее состояние — истина); при `retested` не снимать проверку возраста, а требовать, чтобы ретест был свежим (≤ N баров); подтверждающую свечу считать soft-признаком (`confirmation_candle ∈ {engulf, pin, none}`) и проверить её вклад на v2-бэктесте.

### P1-10 · HTF bias v2

- **Где:** `market_structure/htf_bias_v2.py:57-80, :95-130`; `scheduler/scanner.py:847-848, :871-875` (`limit=60` для 1d/4h/1w/1h), `:878-985`.
- **Факты `[код]`:** EMA55 считается по 60 свечам (у EMA нет «правильного» значения без разгона ≥ 3×span ≈ 165 баров); `confidence = spread×10` (на W1 при спреде ≥ 10% всегда 100); голосование W1/D1/H4 равными весами → H4-сетап против W1 блокируется; NEUTRAL проходит без штрафа; в P(TP) контекст не участвует (P0-7). Блокировка одинакова для reversal и continuation, хотя reversal по ICT — это как раз игра против локального (H4/D1) тренда в сторону HTF (W1) или наоборот; текущая схема не различает «уровень», на котором происходит разворот.
- **Рекомендации:** `limit ≥ 200` для EMA (или кэш HTF-данных); вес голосов по близости к торговому TF (для 1h: H4 > D1 > W1); для reversal требовать выравнивание с ТФ на одну-две ступени выше, для continuation — со всеми; экспортировать `htf_alignment_score` в признаки (P0-7).

### P1-11 · Breakout quality

- **Где:** `liquidity/breakout_quality.py:76, :97-117, :151-188`; `scheduler/scanner.py:696-716`; `config/settings.py:727-735`.
- **Факты `[код]`:** verdict `"fake"` = «вик за границу диапазона, закрытие внутри» = определение свипа. Hard-gate (сейчас off) заблокировал бы именно reversal-сетапы; в soft-режиме результат только пишется в трассу; `breakout_quality_min_score=45` в решении не участвует. Комментарий в коде: min-score gate «убивает ~99% сигналов».
- **Рекомендации:** не включать hard-gate; использовать verdict как признак с направлением («fake» для reversal — положительный признак, для continuation — отрицательный). Проверить вклад на v2-бэктесте.

### P1-12 · ML-ветка

- **Где:** `ml/config.py:18` (`TIMEFRAME="4h"`), `:25` (`MAX_BARS=12`), `:22` (`structural`); `ml/train_model.py:159-215` (XGBRegressor на expected return; изотоническая калибровка на ТОМ ЖЕ test-split, по которому оценивается качество); `ml/auto_retrain.py:24-30, :68-74` (только `*_4h.parquet`, `MIN_SAMPLES=100`); `strategy/probability_engine.py:71-101` (модель загружается один раз при создании синглтона; в `auto_retrain` перезагрузки нет — grep пуст).
- **Факты `[код]`:** модель обучается на 4h, применяется на любом TF (1h включительно); признаки `htf_alignment_score/premium_discount_score/htf_bias_penalty` константны в обучении и в live (P0-7); `EXPIRED` = 0R при `MAX_BARS=12`, а live-исходы — TTL 7 дней (P0-4); калибровка на тесте даёт оптимистичную оценку; переобученная модель вступает в силу только после рестарта.
- **Рекомендации:** модель на TF или признак `timeframe`; калибровка на отдельном фолде (или walk-forward: train → calib → test с эмбарго); `probability_engine.reload_model()` после успешного retrain; включать ML только при подтверждённом OOS-преимуществе над rules-скором (`ml/validate_oos.py` есть — сделать его гейтом деплоя модели).

### P1-13 · Дрейф конфигурации и мёртвые ручки

| Что | Где | Факт `[код]` | Что сделать |
|---|---|---|---|
| `WaveConfig.enabled` | `settings.py:601-605` | дефолт `"true"`, комментарий — «default off» | привести дефолт/комментарий к одному; волны — только признак |
| `PatternEngineConfig.ob_proximity_pct` (2.0) | `settings.py:629`, `pattern_engine.py:577` `PatternEngine()` | никогда не инжектится; `PATTERN_OB_PROXIMITY_PCT` мёртв | `PatternEngine(ob_proximity_pct=config.pattern_engine.ob_proximity_pct)` |
| `AppConfig.ob_proximity_pct` (0.5) | `settings.py:752` | другое понятие (дедуп OB), то же имя | переименовать в `dedup_ob_proximity_pct` |
| `session_hard_gate` | `settings.py:715` `false` vs `.env.example:41` `true` | поведение зависит от `.env`, которого в архиве нет | зафиксировать в трассе через snapshot |
| `confirm_timeframe` | `settings.py:76` `5m` vs `.env.example:25` `15m`; используется только в `multi_tf` | в `single_tf` мёртв | не трогать; отметить в README |
| `build_config_snapshot()` | `settings.py:1020-1074` | нет `min_p_tp*`, `require_ob_retest`, `htf_bias_v2`, `block_*`, cooldown, `sl_min_atr_multiplier`, `min_rr_ratio`, `ob_max_age` | добавить все v2-ручки; `_CONFIG_VERSION` считать хэшем snapshot'а |
| `liquidity.sweep_lookback/ob_lookback/ob_bos_lookback/sweep_swing_window/sweep_max_check_reclaim` | `settings.py` (LiquidityConfig) | сканер и модули используют литералы 50/100/20/2/10 | либо использовать, либо удалить из конфига |
| `sl_absolute_min_pct` | `settings.py:657` `0.25` vs документы `0.8` | см. `logic_up2.1.md §0.7` | документы привести к коду |
| `min_rr_ratio` | `settings.py:654-655` | 2.0 при комментарии «ТЗ 2.5» | решение по бэктесту, комментарий убрать |
| README | `README.md:18, 91-103` | описывает EMA/RSI/MACD-стратегию | переписать под v2 |
| `plan/00index.md` | упоминается в `AGENTS.md`, в архиве отсутствует (есть `plan/15,16,17,pipeline.md`) | ссылки битые | обновить AGENTS.md |

### P1-14 · Прочее (низкий приоритет, но зафиксировать)

- `risk/engine.py:238-249` Kelly-путь: `kelly ≤ 0.2`, `× confidence (0.4 у rules)`, затем `min(kelly, base)` → Kelly-режим никогда не превышает базовый риск; при `risk_mode=fixed` не используется. Оставить, но не считать Kelly работающим.
- `scheduler/outcome_tracker.py:362-366` — high/low берутся у последней ЗАКРЫТОЙ свечи (после `iloc[:-1]`), формирующаяся свеча видна только через тикер: касание барьера виком внутри текущей свечи между тиками фиксируется с задержкой до закрытия свечи (это допустимо, если политика выхода — по закрытым свечам; зафиксировать явно).
- Execution filters (`max_spread 0.15%`, depth $10k в ±0.5%) — для BTC/ETH/SOL тривиальны; зависимости от размера позиции нет (см. `logic_up_prev.md P1-08`).
- `scheduler/scanner.py:1505` MTF `required_alignment=1` для reversal — фактически «хотя бы один из 1d/4h/1h согласен», что почти всегда так; признак малоинформативен.

---

## 5. Аудит параметров (значения по умолчанию из кода; `.env` в архиве нет)

Вердикты: **OK** — обоснован/безвреден; **СОМН** — сомнителен, проверить на v2-бэктесте; **МЁРТВ** — не влияет на поведение; **КОНФЛ** — конфликтует с другим параметром/кодом.

| Параметр | Значение | Где | Вердикт | Комментарий / рекомендация |
|---|---|---|---|---|
| `primary_timeframes` | `1h,4h` | settings | OK | но скан каждые 15 мин без bar-guard (P1-8) |
| `scan_minutes` | `2,17,32,47` | settings:539 | СОМН | 4×/16× оценок одной свечи; нужен guard |
| `candles_limit` | 200 | settings | OK | но `_ob_age` считается от 199 при OB-индексах от tail(100) (P0-1) |
| `liquidity.sweep_max_reclaim_candles` | 2 | settings | СОМН | единственный критерий валидности свипа; на 4h «2 свечи» = 8 часов — жёстко; TF-зависимость |
| `liquidity.sweep_min_volume_ratio` | 1.8 | settings | МЁРТВ (для валидности) | только в `strength`; порог не обоснован |
| `liquidity.sweep_swing_window` | 5 | settings | МЁРТВ | детектор свипов использует 2/2 strict |
| `liquidity.sweep_max_body_beyond_level` (0.3 ATR) / `sweep_min_wick_beyond_level` (0.1%) / `sweep_min_body_size` (0.05%) / `sweep_max_pool_age_bars` (100) | — | settings, sweep.py:74-101 | КОНФЛ/МЁРТВ | первый и четвёртый никогда не срабатывают (atr=0, pool_age=0); второй/третий измеряют не то, что называют |
| `liquidity.ob_min_displacement_pct` | 2.5% | settings | СОМН | по ОДНОЙ следующей свече; на 1h практически исключает OB |
| `liquidity.ob_min_displacement_atr` | 1.5 | settings | OK | но измерение по одной свече (P1-2) |
| `liquidity.ob_min_volume_ratio` | 1.8 | settings | СОМН | объём следующей свечи; проверить распределение |
| `liquidity.ob_max_age_candles` | 35 | settings | КОНФЛ | из-за P0-1 в сканере фактически блокирует все не-retested OB |
| `liquidity.ob_retest_required` | false | settings | OK | retest проверяет отдельный hard-gate |
| `liquidity.fvg_min_size_pct` | 0.4% | settings | СОМН | на 1h BTC это крупный FVG; TF-зависимость |
| `liquidity.candle_displacement_atr_mult` | 1.5 | settings | OK | измеряется по диапазону (не телу) — согласовано с structure |
| `market_structure.structure_lookback/swing_window` | 50/5 | settings | СОМН | CHoCH с задержкой 5 баров (P1-3) |
| `mtf_required_alignment` | 2 (reversal → 1) | settings/scanner:1505 | СОМН | признак почти всегда истинен для reversal |
| `probability.min_p_tp / _short / _reversal` | 0.30 / 0.40 / 0.50 | settings:643-647 | СОМН | пороги на некалиброванный скор (P1-6) |
| `probability.min_samples_for_ml` | 100 | settings | СОМН | для XGB + калибровки мало; 300+ |
| `risk_engine.min_rr_ratio` | 2.0 (нетто) | settings:655 | СОМН | 1.5 в trade_engine — аннотация; 2.5 — ТЗ; выбрать одно |
| `risk_engine.sl_absolute_min_pct` | 0.25% | settings:657 | OK | документы говорят 0.8 — обновить документы |
| `risk_engine.sl_absolute_max_pct` | 5% (динамически до 8%) | settings/engine:194-198 | OK | |
| `sl_min_atr_multiplier` | 2.0 (только дефолт конструктора; в RiskEngineConfig поля нет → `getattr(rc, …, 2.0)`) | engine.py:73, :97 | КОНФЛ | противоречит структурному SL; мёртвая зона при ATR% ≥ 2.5 |
| `base_risk_pct / min / max` | 1.0 / 0.1 / 2.0 | settings | OK | но множители shadow (P1-7) |
| `risk.max_positions_total/long/short` | 5 / 3 / 3 | settings | КОНФЛ | long/short мертвы (P0-6) |
| `risk.max_daily_risk_pct / trades / consecutive_losses / dd` | 6% / 5 / 3 / 10% | settings | OK | проверка после save (P0-5) |
| `risk.correlation_multiplier` | 0.5 | settings | НЕ ПРОВЕРЕНО | применение в сканере не прослежено |
| `regime: adx_trend 25 / range 20 / compression atr-pct 20` | — | settings | СОМН | regime edges в P(TP) на legacy-данных |
| `htf_bias_v2`, `block_short_in_bullish_htf`, `block_long_in_bearish_htf` | true | settings:706-711 | СОМН | hard-block без soft-score; EMA на 60 свечах |
| `premium_discount` | false | settings | МЁРТВ | и при включении в P(TP) не попадает (P0-7) |
| `require_entry_zone` | false | settings | OK | |
| `reversal_require_displacement` | true | settings | СОМН | комментарий в pattern_engine: displacement «informational — not a gate»; сверить |
| `require_ob_retest` | true | settings:713 | КОНФЛ | вместе с P0-1/P1-2 — основной «убийца» reversal |
| `session_hard_gate` | false (env-example: true) | settings:715 | КОНФЛ | зафиксировать в snapshot |
| `breakout_quality_hard_gate` | false | settings:729 | OK (оставить off) | см. P1-11 |
| `breakout_quality_min_score` | 45 | settings:733 | МЁРТВ | не участвует в решении |
| `signal_cooldown_minutes / tf_multiplier / mode` | 45 / 2.0 / ob_aware | settings:745-752 | СОМН | см. P1-8 |
| `ob_proximity_pct` (AppConfig) | 0.5 | settings:752 | КОНФЛ | коллизия имён с PatternEngineConfig (2.0) |
| `max_ob_distance_pct` | 3.0 | settings:158 | СОМН | используется в OB-gate как «слишком далеко» |
| `max_active_signals / max_portfolio_risk_pct` | 3 / 3.7 | settings:772-774 | OK | |
| `context_enabled`, timeout 10s | true | settings | OK | soft |
| `trading.max_spread_percent / min_depth_0_5_percent / max_slippage` | 0.15% / $10k / 0.1% | settings | OK | тривиальны для мажоров |
| `outcome TTL` | 7 дней | outcome_tracker | КОНФЛ | vs `MAX_BARS=12` в ML (P0-4) |
| `_TIME_STOP_BY_TF` | 1h: 1200 мин, 4h: 5760 | outcome_tracker:31-48 | МЁРТВ | «PAUSED» |
| `entry_trigger proximity / spread` | 0.3% / 0.1% | entry_trigger:68-69 | МЁРТВ (proximity) | current_price = entry (P0-8) |
| `ml TIMEFRAME / MAX_BARS / MIN_SAMPLES / EMBARGO` | 4h / 12 / 100 / 5 | ml/config | СОМН | см. P1-12 |
| `trade_engine`: `sl_buffer 0.35 ATR`, `push 0.15 ATR`, `min TP 1 ATR`, `type_bonus` | литералы | trade_engine.py | СОМН | вынести в конфиг, проверить |
| Legacy: EMA/RSI/MACD/ADX-фильтры, `block_compression_regime`, `volume_factor` | — | settings | МЁРТВ для v2 | участвуют только в legacy-движке и snapshot'е |

---

## 6. Сверка с предыдущим аудитом (`logic_up_prev.md`, документный)

| Пункт prev | Статус по коду | Ссылка здесь |
|---|---|---|
| P0-01 единый closed-bar / `as_of` контракт | **ПОДТВЕРЖДЁН** — `as_of_utc` всегда None | P0-3, P1-8 |
| P0-02 строгая причинная цепочка, доступность pivot | **ЧАСТИЧНО** — причинность sweep→CHoCH есть (окно 10), но индексы/timestamps детекторов несогласованы, CHoCH с задержкой 5 баров | P0-1, P1-3 |
| P0-03 entry trigger и пересборка плана | **ПОДТВЕРЖДЁН** — trigger no-op | P0-8 |
| P0-04 атомарные портфельные лимиты | **ПОДТВЕРЖДЁН** — лимиты по направлению мертвы, резервация после save | P0-5, P0-6 |
| P0-05 net EV, Kelly, полная стоимость | **ЧАСТИЧНО** — RR нетто с 0.1% есть; Kelly фактически ≤ base; `×1.1` в expected_rr | P1-6, P1-14 |
| P0-06 разделить signal/fill/position/outcome | **ПОДТВЕРЖДЁН как архитектурный долг** — outcome = сигнал, менеджер позиций внутри трекера | P0-4 |
| P0-07 корректные outcomes, один exit contract | **ПОДТВЕРЖДЁН** — TP-first vs SL-first, time-stop off, перезапись причин | P0-4 |
| P0-08 атомарная Phase 8 / outbox | **ПОДТВЕРЖДЁН** | P0-5 |
| P0-09 вероятность/ML без утечки | **ЧАСТИЧНО** — эмбарго есть; калибровка на test-split; TF-несоответствие; константные признаки | P1-12, P0-7 |
| P1-01 независимая оценка reversal/continuation | **НЕ ВОСПРОИЗВЕДЕНО как баг** — оба типа пробуются; смешивается только текст причины отказа | — |
| P1-02 core validity vs confluence | **ПОДТВЕРЖДЁН** — `has_ob` требует `has_bos` и т.д. | P1-2 |
| P1-03 OB/FVG как автоматы состояний | **ЧАСТИЧНО** — `ob_state` есть, но зависит от порядка касаний | P1-9 |
| P1-04 breakout quality по типу сетапа | **ПОДТВЕРЖДЁН** | P1-11 |
| P1-05 HTF: иерархия вместо majority vote | **ПОДТВЕРЖДЁН** | P1-10 |
| P1-06 выбор target и exit policy | **ПОДТВЕРЖДЁН** | P1-4, P0-4 |
| P1-07 дедуп по идентичности сетапа | **ПОДТВЕРЖДЁН** | P1-8 |
| P1-08 execution checks vs размер | **НЕ ПРОВЕРЕНО** (размера в USD в этих проверках нет) | P1-14 |
| P1-09 data integrity | **ЧАСТИЧНО** — `dropna` и отбрасывание формирующейся свечи есть; проверка пропусков в свечах не найдена | P0-3 |
| P1-10 scheduler/sessions/durable state | **ПОДТВЕРЖДЁН** | P1-8 |
| P1-11 shadow должен быть shadow | **ПОДТВЕРЖДЁН** | P1-7 |
| P1-12 корреляция / фактический риск | **ЧАСТИЧНО** — `correlation_multiplier` есть, применение не прослежено | — |

Из `logic_up2.1.md`: «MSS fixes applied 2026-09-04» (порог 0.2 ATR, `max_causal_bars=10`, same-candle по диапазону) — **в коде есть** (`structure.py:129, :176-186, :202-207`). «funnel.py сломан» — не перепроверялось. «sl_absolute_min_pct 0.25» — подтверждено.

**Новое относительно обоих предыдущих документов:** P0-1 (системы координат), P0-2 (асимметрия BOS), P0-7 (HTF-контекст не доезжает / расходится с бэктестом), P0-9 (v2-бэктест ≠ live), мёртвые ложные фильтры свипов (P1-1), `_reclaim` от самого старого свипа (P1-1), `sl_source` теряется (P1-5), граф `new_bar=True` на каждом скане (P1-7), отсутствие перезагрузки модели после retrain (P1-12).

---

## 7. План внедрения для mimo v2.5

**Фаза A — измеримость, без изменения торгового поведения (1–2 дня).**
1. P0-3: контракт DataFrame, `as_of_utc`, `entry_candle_open`, bar guard (только логирование повторных оценок, без блокировки).
2. P1-13: `build_config_snapshot` со всеми v2-ручками; `_CONFIG_VERSION` = хэш snapshot'а.
3. Воронка отказов по гейтам с сохранением в БД (уже есть `_current_funnel` — добавить персист) + гистограммы: `_ob_age`, `displacement_atr` у MSS, `p_tp` у rules, RR у кандидатов целей.
4. Тесты из раздела 8 (группа A).

**Фаза B — исправление доказанных багов (2–3 дня).** Порядок: P0-1 → P0-2 → P0-6 → P0-5 → P0-4 → P0-8 → P0-7 → P1-7 (shadow off) → P1-8 (bar guard блокирующий). Каждая правка — свой тест + сравнение воронки до/после на одном и том же наборе свечей (кэш OHLCV есть: `backtest/cache_ohlcv.py`).

**Фаза C — паритет и бэктест v2 (3–5 дней).** P0-9: `evaluate_candidate` + `resolve_bar_exit`, тест паритета, прогон ≥ 20 символов × {1h,4h} × ≥ 180 дней с воронкой. Только после этого — решения по P1-1…P1-6, P1-9…P1-11 через A/B на этом бэктесте (по одной гипотезе за раз, с сохранением preset'ов как в `report_v3`).

**Фаза D — калибровка (после ≥ 300 закрытых барьерных исходов live или OOS-окна бэктеста).** Пороги `min_p_tp*`, `min_rr_ratio`, буферы SL, `ob_max_age`, `sweep_max_reclaim` по TF; ML — только при OOS-преимуществе.

**Критерий готовности каждой фазы:** все тесты зелёные; для B — воронка отказов изменилась ОЖИДАЕМО (и это записано в PR); для C — паритет сканер/бэктест байт-в-байт по трассе гейтов на одном окне.

---

## 8. Обязательные тесты (имена условные, положить рядом с существующими)

Группа A (падают на текущем коде):
- `test_detectors_absolute_index_and_real_timestamps` — sweep/OB/FVG/CHoCH на df длиной 199: `df.index[event.candle_index] == event.timestamp`, `timestamp.year == 2026` (P0-1).
- `test_scanner_ob_age_matches_position` — OB на 5 свечей назад → `_ob_age == 5` (P0-1d).
- `test_bos_bearish_uses_latest_swing_low` (P0-2).
- `test_as_of_and_entry_candle_open_are_set` — путём `scan_symbol_v2` с подставным клиентом (P0-3).
- `test_direction_position_limits_enforced` (P0-6).
- `test_daily_limit_block_leaves_no_orphans` — параллельные задачи (P0-5).
- `test_bar_exit_policy_same_for_tracker_and_backtest` — свеча, касающаяся SL и TP (P0-4).
- `test_time_stop_closes_with_real_pnl` (P0-4).
- `test_close_reason_raw_preserved` — `FLIP_BIAS` не становится `HIT_TP` (P0-4).
- `test_htf_alignment_reaches_features` — `features.htf_alignment_score is not None` (P0-7).
- `test_entry_trigger_uses_ticker_price` (P0-8).
- `test_shadow_engines_do_not_change_risk` — при `shadow_mode=True` `risk_pct` не зависит от `_thesis_score` (P1-7).
- `test_graph_new_bar_once_per_candle` (P1-7).
- `test_same_bar_not_evaluated_twice` (P1-8).

Группа B (сторожа против регресса, зелёные после правок):
- `test_find_ob_for_sweep_returns_ob_before_sweep_within_lookback`.
- `test_sweep_dedup_one_event_per_direction_per_candle`; `test_false_sweep_filters_actually_run` (atr/pool_age заполнены; подсадка «atr=0» → фильтр не срабатывает → тест красный).
- `test_sl_source_records_htf_poi`.
- `test_target_rr_uses_real_sl`.
- `test_config_snapshot_contains_v2_keys` (реестр ключей + подсадка «убрали ключ» → красный).
- `test_backtest_parity_gate_trace` (фаза C).

---

## 9. Машиночитаемый список задач

```yaml
- id: P0-1
  title: Единая система координат детекторов (absolute candle_index + real timestamps)
  files: [liquidity/sweep.py, liquidity/order_blocks.py, liquidity/fvg.py, strategy/pattern_engine.py, scheduler/scanner.py]
  lines: {sweep: "141,163,285-296", order_blocks: "100,137-138,167-168,219-225,341-349,352-363", fvg: "61,90,103,140", pattern_engine: "497-527", scanner: "741"}
  change: "убрать reset_index(drop=True) или хранить offset; candle_index = offset+i везде; timestamp = df.index[abs_idx]; find_ob_for_sweep без break по timestamp; entry-zones сравнивать по candle_index; _ob_age по абсолютному индексу"
  tests: [test_detectors_absolute_index_and_real_timestamps, test_scanner_ob_age_matches_position, test_find_ob_for_sweep_returns_ob_before_sweep_within_lookback]
- id: P0-2
  title: _check_bos_bearish должен брать последний swing low
  files: [liquidity/order_blocks.py]
  lines: {order_blocks: "301"}
  change: "min(...) -> max(relevant_lows, key=index)"
  tests: [test_bos_bearish_uses_latest_swing_low]
- id: P0-3
  title: as_of_utc / data_age_ms / entry_candle_open из индекса DataFrame
  files: [scheduler/scanner.py, data/exchange_client.py]
  lines: {scanner: "400-410,1942-1948", exchange_client: "347-357"}
  change: "_as_of_utc = df.index[-1]; entry_candle_open = df.index[-1]; документировать контракт индекса"
  tests: [test_as_of_and_entry_candle_open_are_set]
- id: P0-4
  title: Единый exit-контракт (SL-first), time-stop, сырые причины закрытия
  files: [scheduler/outcome_tracker.py, backtest/engine.py, backtest/run_new_pipeline.py, ml/config.py]
  lines: {outcome_tracker: "31-48,241-259,273-280,362-366,511-525,627"}
  change: "resolve_bar_exit(); включить time-stop = MAX_BARS_BY_TF; close_reason_raw; EXPIRED с реальным PnL; hold_bars по свечам"
  tests: [test_bar_exit_policy_same_for_tracker_and_backtest, test_time_stop_closes_with_real_pnl, test_close_reason_raw_preserved]
- id: P0-5
  title: Резервация дневного лимита до save_signal, откат при отказе
  files: [scheduler/scanner.py, risk/daily_limits.py, storage/database.py]
  lines: {scanner: "2054,2120-2139", daily_limits: "111-135"}
  change: "try_open_trade под Lock перед save; release() при сбое; уникальный индекс signals(symbol,timeframe,entry_candle_open,direction)"
  tests: [test_daily_limit_block_leaves_no_orphans]
- id: P0-6
  title: Лимиты позиций по направлению через join с signals
  files: [scheduler/scanner.py, storage/database.py]
  lines: {scanner: "360-376"}
  change: "get_open_outcomes_with_signals(); считать по signal.signal_type"
  tests: [test_direction_position_limits_enforced]
- id: P0-7
  title: HTF/PD-контекст в признаки live; паритет с run_new_pipeline
  files: [scheduler/scanner.py, strategy/feature_builder.py, strategy/probability_engine.py, backtest/run_new_pipeline.py]
  lines: {scanner: "862,1559-1580", feature_builder: "217-218", probability_engine: "311-318", run_new_pipeline: "520-521"}
  change: "htf_alignment_score из HTFBiasResult; решить судьбу premium_discount_score и htf_bias_penalty; убрать None->0.5 или добавить htf_known"
  tests: [test_htf_alignment_reaches_features]
- id: P0-8
  title: Entry trigger по цене тикера и явной политике входа
  files: [scheduler/scanner.py, strategy/entry_trigger.py]
  lines: {scanner: "1762-1800", entry_trigger: "68-69,105-128"}
  tests: [test_entry_trigger_uses_ticker_price]
- id: P0-9
  title: evaluate_candidate() общий для сканера и бэктеста; v2-бэктест с теми же гейтами
  files: [scheduler/scanner.py, backtest/run_new_pipeline.py, tests/test_backtest_parity.py]
  tests: [test_backtest_parity_gate_trace]
- id: P1-7
  title: shadow_mode действительно shadow; new_bar один раз на свечу; реальные входы Market Phase
  files: [scheduler/scanner.py, risk/engine.py]
  lines: {scanner: "1185-1200,1251-1253,1712-1713,1762", engine: "258-273"}
  tests: [test_shadow_engines_do_not_change_risk, test_graph_new_bar_once_per_candle]
- id: P1-8
  title: bar guard + дедуп по идентичности сетапа
  files: [scheduler/scanner.py, scheduler/tasks.py]
  lines: {scanner: "185-192,1858-1935", tasks: "26-28"}
  tests: [test_same_bar_not_evaluated_twice]
- id: P1-13
  title: Snapshot всех v2-ручек; инжект PatternEngineConfig; переименование ob_proximity_pct
  files: [config/settings.py, strategy/pattern_engine.py, scheduler/scanner.py]
  lines: {settings: "605,629,715,752,1020-1074", pattern_engine: "577", scanner: "90"}
  tests: [test_config_snapshot_contains_v2_keys]
- id: P1-1
  title: Свипы: дедуп, единый swing detector, живые ложные фильтры, один свип для MSS и сетапа
  files: [liquidity/sweep.py, scheduler/scanner.py, strategy/pattern_engine.py]
  after: [P0-1, P0-9]
- id: P1-2
  title: OB: displacement по ноге, валидность sweep-OB через MSS, выбор ближайшего OB
  files: [liquidity/order_blocks.py, strategy/pattern_engine.py]
  after: [P0-1, P0-2, P0-9]
- id: P1-3
  title: CHoCH/MSS по закрытию, htf_aligned в mss_score
  files: [market_structure/structure.py, scheduler/scanner.py]
  after: [P0-9]
- id: P1-4
  title: Цели по реальному SL, один min_rr
  files: [strategy/trade_engine.py, strategy/trade_plan.py, risk/engine.py, config/settings.py]
  after: [P0-9]
- id: P1-5
  title: SL: sl_min_atr_multiplier -> soft, sl_source, htf_poi семантика, буферы в конфиг
  files: [risk/engine.py, strategy/trade_engine.py, strategy/htf_poi.py]
  after: [P0-9]
- id: P1-6
  title: Rules-скор вместо "P(TP)", калибровочная метрика в отчёте
  files: [strategy/probability_engine.py, analytics/daily_report.py]
  after: [P0-4, P0-9]
- id: P1-9
  title: OB-retest gate: состояние по последнему касанию, свежесть ретеста, подтверждение как признак
  files: [liquidity/ob_state.py, scheduler/scanner.py]
  after: [P0-1]
- id: P1-10
  title: HTF bias: limit>=200, веса по близости TF, экспорт score
  files: [market_structure/htf_bias_v2.py, scheduler/scanner.py]
  after: [P0-7]
- id: P1-11
  title: Breakout quality как направленный признак
  files: [liquidity/breakout_quality.py, scheduler/scanner.py]
- id: P1-12
  title: ML: TF-признак/модели по TF, калибровка на отдельном фолде, reload после retrain
  files: [ml/config.py, ml/train_model.py, ml/auto_retrain.py, strategy/probability_engine.py]
```

---

## 10. Что не проверено и границы аудита

- `.env`, БД, логи и живые прогоны отсутствуют — реальные значения ручек (`SESSION_HARD_GATE`, `SYMBOLS`, ключи) неизвестны; поведение описано по дефолтам кода и `.env.example`.
- `risk.correlation_multiplier`, `news_filter`, `derivatives`-контекст, `web/`, Telegram-уведомления, `analytics/daily_report.py` — не разбирались.
- `backtest/funnel.py`, `backtest/run_r6.py`, `edge_discovery.py` — не перепроверялись (см. `logic_up2.1.md` о funnel).
- Все количественные ожидания (рост `has_ob`, доля отказов `ob_retest`, распределение `p_tp`) — `[гипотеза]` до фазы A/C.
