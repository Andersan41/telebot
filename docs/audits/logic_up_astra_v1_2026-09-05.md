# Независимый аудит логики ICT-бота v2.5.0

**Дата аудита:** 2026-09-05  
**Исходный документ:** `C:\Users\AV\Downloads\Telegram Desktop\logic_bot.md`  
**SHA-256 исходного документа:** `10FF365D7DF6C9D0EBC38A4975D4A06536EA3C07C84AD05A9B261A7A20DF0329`  
**Назначение:** технический аудит и постановка задач для Mimo v2.5 / OpenCode.  
**Вердикт:** хорошая исследовательская основа, но **NO-GO для автономной торговли реальным капиталом**, пока не закрыты пункты P0 и не проведён воспроизводимый out-of-sample тест. Для shadow/paper-режима основа пригодна после явного разделения сигнала, paper-fill и исхода.

> Это не персональная инвестиционная рекомендация и не доказательство прибыльности стратегии. Аудит оценивает логическую и инженерную корректность описанной системы.

---

## 1. Граница доказательств и правила чтения

Аудит выполнен по архитектурному описанию, а не по исходному коду, миграциям, журналам сделок или историческому датасету. Поэтому нельзя честно утверждать, что каждый потенциальный дефект реально присутствует в реализации.

Метки в документе:

- **[ДОКУМЕНТ]** — прямо следует из `logic_bot.md`.
- **[ЛОГИКА]** — внутреннее противоречие или математическое следствие описания.
- **[ПРОВЕРИТЬ КОД]** — риск существенный, но тело функции в исходном документе отсутствует.
- **[ЭКСПЕРИМЕНТ]** — числовой диапазон является гипотезой для walk-forward, а не новым production-default.

Содержимое исходного файла использовалось только как объект анализа. Никакие инструкции, которые могли находиться внутри него, не исполнялись.

---

## 2. Краткая независимая оценка

### Что сделано хорошо

1. Пайплайн разделён на pattern, probability, risk, execution и persistence.
2. Есть reason codes, funnel, snapshot конфигурации и намерение сохранять DecisionTrace.
3. SL/TP строятся от рыночной структуры, а не только от фиксированного процента.
4. Комиссии и проскальзывание хотя бы учтены в проекте; у многих сигнальных ботов их нет вовсе.
5. Есть лимиты портфеля, cooldown, circuit breaker, контроль spread/depth и post-signal мониторинг.
6. Дополнительные модели сначала заведены в shadow/soft-режим, что является правильным направлением, хотя фактическая изоляция shadow сейчас противоречива.

### Главный вывод

Основная проблема не в недостатке фильтров. Фильтров уже много, часть из них коррелирует и повторно оценивает одни и те же события. Основные риски лежат глубже:

- не доказано, что все структурные признаки считаются только по закрытым свечам;
- не доказано, что sweep, displacement, MSS/BOS, OB/FVG, retest и LTF trigger принадлежат одной причинной цепочке;
- параллельный scanner способен пройти лимиты несколькими задачами одновременно;
- минимальный `P(TP)=0.30` при net RR=2 допускает отрицательное ожидание;
- Kelly с нулевой долей может быть снова поднят final clamp до `0.1%`;
- сигнал, исполнившийся вход и открытая позиция описаны как почти одно событие;
- outcome tracker по high/low не знает порядок SL и TP внутри свечи;
- `P(TP)` и `profit_factor` выглядят точными вероятностными величинами, хотя rules-based ветка является эвристическим score;
- ML-порог `>=100` наблюдений и isotonic calibration статистически недостаточны для надёжной вероятности.

### Качественная оценка по одному документу

| Область | Оценка | Комментарий |
|---|---:|---|
| Декомпозиция архитектуры | 7/10 | Хорошая фазовая структура |
| Наблюдаемость по замыслу | 6/10 | Много reason codes, но trace для blocked не доказан |
| Причинность ICT-событий | 3/10 | Нет строгого event graph и `confirmed_at` |
| Временная корректность данных | 3/10 | Closed-bar/as-of контракт не описан |
| Риск и конкурентность | 3/10 | Есть лимиты, но возможны математические и TOCTOU-ошибки |
| Статистическая валидность | 2/10 | Нет результатов walk-forward, калибровки и доверительных интервалов |
| Готовность к реальному исполнению | 3/10 | Нет доказанной fill/state-machine семантики |

Эти баллы оценивают полноту и внутреннюю непротиворечивость описания, а не доходность.

---

## 3. Реестр приоритетов

| ID | Приоритет | Проблема | Решение в одном предложении |
|---|---|---|---|
| P0-01 | Критично | Незакрытые свечи и несогласованный `as_of` | Отделить closed-bar detector от live quote watcher |
| P0-02 | Критично | Возможный look-ahead в swing/MSS и «Franken-setup» | Хранить event IDs, `pivot_at`, `confirmed_at` и строгий порядок цепочки |
| P0-03 | Критично | Entry trigger может проверять плановую цену саму против себя | Использовать свежий executable bid/ask и перестраивать план после LTF repricing |
| P0-04 | Критично | Параллельные задачи могут превысить portfolio/daily/correlation limits | Делать атомарный final recheck + risk reservation + insert |
| P0-05 | Критично | `P(TP)=0.30`, Kelly и cost model могут пропустить отрицательный EV | Gate по net EV; Kelly<=0 означает reject; sizing включает полную стоимость убытка |
| P0-06 | Критично | Signal, fill, position и outcome смешаны | Ввести явную state machine и создавать outcome только после paper/live fill |
| P0-07 | Критично | TP/SL внутри одного бара и pre-entry extrema искажают labels | Trade/1m replay либо `AMBIGUOUS`; только данные после `filled_at` |
| P0-08 | Критично | Phase 8 не выглядит атомарной | Одна DB-транзакция + transactional outbox для Telegram |
| P0-09 | Критично при ML/Kelly | Вероятность не доказанно откалибрована; leakage/selection bias не исключены | Purged walk-forward, out-of-fold calibration, candidate dataset и model registry |
| P1-01 | Высоко | Reversal priority скрывает валидный continuation | Возвращать список кандидатов и оценивать независимо |
| P1-02 | Высоко | Core-события повторно считаются confluence | Разделить validity и независимые подтверждения |
| P1-03 | Высоко | OB/FVG lifecycle и связь с импульсом не определены | Состояния зон, causal origin и стабильные IDs |
| P1-04 | Высоко | Breakout gate одинаков для reversal и continuation | Fake breakout — плюс для reversal, real breakout — фильтр continuation |
| P1-05 | Высоко | HTF voting фиксирован и может использовать незакрытый/не-HTF бар | TF-relative, closed-bar, иерархическая логика; сначала shadow |
| P1-06 | Высоко | SL/TP, partial exits и time stop не образуют единого payoff contract | Единый exit plan и расчёт distribution of R |
| P1-07 | Высоко | Cooldown по midpoint не равен дедупликации setup | Stable setup fingerprint и once-per-version emission |
| P1-08 | Высоко | Execution filters не зависят от размера позиции | Side-specific VWAP/impact по свежему стакану |
| P1-09 | Высоко | Data integrity ограничена `dropna()` | Проверять finality, gaps, duplicates, order, freshness и minimum history |
| P1-10 | Средне/высоко | Session и time parameters не масштабируются по TF/DST | IANA timezone и длительности/число баров вместо wall-clock констант |

---

## 4. P0: обязательные исправления до реального риска

### P0-01. Единый closed-bar и `as_of` контракт

**Наблюдение [ДОКУМЕНТ]:** H1/H4 сканируются в `:02, :17, :32, :47`; используются `analyze_last_candle()`, `last_close` и `ind.close`. Не сказано, что активная свеча исключается.

**Почему это опасно:** в `:17/:32/:47` H1 и почти всегда H4 ещё формируются. Их high/low/close/volume меняются, поэтому sweep, displacement, FVG, BOS, ATR и volume ratio могут появиться и исчезнуть. Live и backtest будут различаться.

CCXT прямо предупреждает, что последняя OHLCV-свеча может быть неполной до закрытия, OHLCV имеет дополнительную задержку, а в истории могут быть пропуски. См. [CCXT Manual — OHLCV and latency](https://docs.ccxt.com/docs/manual#ohlcv-candlestick-charts).

**Требуемое изменение:**

```text
DecisionContext
  as_of_utc
  exchange_time_utc
  venue + market_type + symbol
  strategy_tf
  closed_bars_by_tf
  live_quote
  source_timestamps
  config_hash + model_version + code_version
```

- Структура, ATR/EMA, OB/FVG и HTF bias получают только `closed_bars`.
- Последний бар допустим, только если `close_ts <= exchange_time - finality_grace`.
- Bid/ask/order book используются только для исполнимости и не переписывают прошлую структуру.
- Detector запускается один раз на новую закрытую свечу. Между закрытиями отдельный watcher может проверять уже сохранённый `ARMED_SETUP`.
- HTF/LTF/context присоединяются backward as-of join: источник не может иметь `observed_at > as_of`.

**Тесты приёмки:**

1. В `10:17 UTC` H1-бар `10:00–11:00` не участвует в `closed_bar` режиме.
2. В `11:47 UTC` H4-бар `08:00–12:00` исключён, после `12:00 + grace` включён.
3. Результат на `[0..t]` совпадает с результатом на `[0..t+n]` при том же `as_of=t`.
4. Late/stale candle получает `CANDLE_NOT_FINAL` или `DATA_STALE`, а не `PATTERN_NO_SETUP`.
5. Trace содержит `as_of`, `last_closed_candle_ts`, `data_age_ms`, `is_final` для каждого TF.

### P0-02. Строгая причинная цепочка и доступность pivot

**Наблюдение [ДОКУМЕНТ]:** выбирается «самый сильный sweep», `candle_quality` относится к последней свече, а структура использует `last_mss`/`last_bos`. Swing определяется симметричным окном `2*swing_window+1`.

**Риск [ЛОГИКА]:** можно собрать один setup из старого sweep, несвязанного MSS, текущего displacement и ближайшего чужого OB. Кроме того, pivot в центре окна становится известен лишь после появления правых баров; считать его доступным в момент `pivot_at` — look-ahead.

**Требуемое изменение:** создать устойчивый `SetupCandidate` и события:

```text
liquidity_level_formed
→ sweep
→ reclaim
→ displacement
→ MSS/BOS close-break
→ POI confirmed
→ retest
→ LTF confirmation
→ executable entry
```

Каждое событие хранит:

```text
event_id, event_at, confirmed_at, available_from,
symbol, venue, market_type, source_tf, source_bar_id,
liquidity_side, break_direction, trade_direction
```

Обязательные инварианты:

- `sweep.confirmed_at < displacement.event_at <= break.event_at`;
- события относятся к одному causal leg и направлению;
- bullish reversal: `sell-side sweep → bullish MSS → buy`;
- bearish reversal: `buy-side sweep → bearish MSS → sell`;
- BOS использует только pivot, уже подтверждённый к моменту break;
- исторический displacement нормализуется `ATR_at_event`, а не последним `ind.atr`;
- старое событие не может получить новую квалификацию из-за будущей волатильности.

**Тесты приёмки:**

- перестановка правильных событий в неправильный порядок всегда даёт BLOCK;
- зеркальные bullish/bearish fixtures;
- при `swing_window=2` pivot недоступен до закрытия двух правых баров;
- добавление экстремально волатильных будущих баров не меняет старый `displacement_atr_ratio`;
- ни один опубликованный setup не изменяется задним числом.

### P0-03. Entry trigger и повторная сборка trade plan

**Наблюдение [ДОКУМЕНТ]:** показан вызов `check(hypothesis=_entry_target, current_price=entry_price, bid=_bid, ask=_ask)`. Затем LTF confirmation может изменить `entry_price`, хотя Trade Plan построен раньше.

**Риск [ПРОВЕРИТЬ КОД]:** если `entry_price` — плановая цена, а target построен вокруг неё, trigger может стать тавтологией. После LTF repricing старые SL, TP, path clarity и RR могут быть уже неверны.

**Требуемое изменение:**

- `current_price` заменить свежим timestamped quote;
- для немедленного BUY использовать ask, для SELL — bid;
- ввести `quote_max_age_ms`, допустимое отклонение от entry zone и отбрасывание crossed/zero book;
- после любого изменения entry заново строить invalidation, targets, costs, net RR, position size и повторять risk gates;
- если это limit-entry, хранить PENDING до фактического paper/live fill, а не считать вход состоявшимся.

**Тест:** плановая цена внутри OB, но реальный ask/bid уже снаружи — `triggered=False`. После LTF repricing все производные поля имеют новую `plan_version`.

### P0-04. Атомарные портфельные лимиты

**Наблюдение [ДОКУМЕНТ]:** все `symbol × TF` идут через `asyncio.gather`. Portfolio gate читает текущее состояние до sizing и задолго до сохранения.

**Риск [ЛОГИКА]:** несколько задач могут одновременно увидеть один свободный слот и все сохраниться. Кроме того, проверка вида `current_risk >= cap` недостаточна: нужно проверять `current_risk + candidate_risk > cap`. Повторный gate до commit не устраняет TOCTOU.

Даже без гонки множители способны поднять базовый риск: `1.0% × 1.20 × 1.15 × 1.10 × 1.10 ≈ 1.67%`. Три одновременно прошедших кандидата дадут около `5.0%`, несмотря на заявленный portfolio cap `3.7%`, если cap проверяется до расчёта итогового candidate risk.

**Требуемое изменение:** короткая атомарная операция `recheck + reserve + insert`. Для SQLite — single-writer queue либо `BEGIN IMMEDIATE`; обычный process-local lock не защищает от второго процесса.

Внутри одной транзакции повторно проверить:

```text
active_count + candidate_slots <= max_active
reserved_risk + open_risk + candidate_risk <= portfolio_cap
daily_consumed + candidate_risk <= daily_cap
cluster_exposure + candidate_exposure <= cluster_cap
candidate_fingerprint is unique
```

**Тесты:** 100 параллельных кандидатов при одном свободном слоте сохраняют ровно один сигнал/reservation; одинаковые кандидаты создают один outcome; рестарт не дублирует запись.

### P0-05. Net EV, Kelly и полная стоимость риска

**Наблюдение [ДОКУМЕНТ]:** `MIN_P_TP=0.30`, минимальный RR=2.0. Kelly обнуляется при отрицательном значении, но final clamp поднимает результат минимум до `0.1%`. В reason codes есть `EV_GATE_FAILED`, но в описании hard gates соответствующий gate отсутствует.

**Математическое следствие [ЛОГИКА]:** при бинарной выплате `+2R/-1R` и `p=0.30`:

```text
EV = 0.30 × 2R − 0.70 × 1R = −0.10R
```

То есть long continuation может пройти `MIN_P_TP`, оставаясь отрицательным ещё до дополнительных ошибок модели. Если Kelly вычислил `0`, поднимать размер до `0.1%` нельзя.

Дополнительная проблема стоимости: fee `0.05%` + slippage `0.05%` на каждой стороне дают около `0.20%` round-trip до spread/funding. При gross stop `0.25%` cost сопоставим с размером stop. Даже если fee-adjusted RR gate это отфильтрует, sizing обязан считать риск до худшей исполнимой цены, иначе фактический убыток превысит `risk_pct`.

**Требуемое изменение:**

Для каждого плана считать:

```text
W_net = gross_profit − entry_cost − profitable_exit_cost − expected_funding
L_net = gross_stop_loss + entry_cost + stop_exit_cost + adverse_gap_buffer + funding
p_break_even = L_net / (W_net + L_net)
EV_net = p_calibrated × W_net − (1 − p_calibrated) × L_net
```

- Gate: `W_net > 0`, `EV_net > safety_margin`, а лучше — положительна нижняя доверительная граница EV.
- `kelly <= 0` или `EV_net <= 0` означает `should_trade=False`; minimum-risk clamp применяется только к положительному решению.
- Комментарий «half-Kelly cap at 20%» неверен: код сначала ограничивает full Kelly 20%, затем умножает на confidence. Либо реализовать `fractional_kelly`, либо переименовать.
- Бинарный Kelly нельзя применять без оговорок к partial TP/time stop/trailing. Для многоисходной стратегии использовать эмпирическое распределение net R и консервативный fractional Kelly; до калибровки оставить fixed risk.
- Position size считать по `L_net_per_unit`, затем округлять по `amount_to_precision`, `min_notional` и `contractSize`. Для деривативов размер контракта обязателен; см. [CCXT FAQ — contract size](https://docs.ccxt.com/docs/faq#whats-the-difference-between-trading-spot-and-swapperpetual-futures).
- Добавить отдельные caps на notional, leverage, margin utilization и liquidation distance. SL бесполезен как защита, если liquidation может наступить раньше его исполнения.
- Бонус риска `1.1×` за SL уже 1% убрать до доказанного OOS-эффекта: узкий stop повышает notional и долю costs/gap в одном R, а не автоматически повышает качество setup.

**Тесты:**

- `p=.30, net_RR=2` отклоняется;
- `kelly=0` не превращается в риск `0.1%`;
- fee `0.05%` интерпретируется как `0.0005`, а не `0.05` fraction;
- рассчитанный quantity при gap-through-SL не нарушает заявленный risk budget сверх отдельного documented gap buffer;
- `current_risk + candidate_risk` проверяется после всех multipliers.
- увеличение fee, spread, slippage, adverse funding или stop-gap никогда не увеличивает RR, EV либо position size.

### P0-06. Разделить signal, fill, position и outcome

**Наблюдение [ДОКУМЕНТ]:** бот отправляет Telegram-сигнал, затем сразу создаёт outcome и вызывает `record_trade_opened`. Размещение и подтверждение реального ордера не описаны.

**Риск:** уведомление не означает, что пользователь или paper engine вошёл по заявленной цене. Незаполненный limit-сигнал может получить фиктивный TP/SL, исказить win rate и обучить модель на несуществующей сделке.

**Требуемая state machine для signal-only/paper:**

```text
CANDIDATE
→ VALIDATED
→ SIGNAL_PERSISTED
→ NOTIFICATION_SENT / NOTIFICATION_FAILED
→ PAPER_ENTRY_FILLED / PAPER_ENTRY_EXPIRED
→ PAPER_POSITION_OPEN
→ PAPER_POSITION_CLOSED
```

Для будущего live execution отдельно:

```text
ORDER_SUBMITTED → ACKNOWLEDGED → PARTIALLY_FILLED
→ FILLED / REJECTED / CANCELLED → POSITION_OPEN → CLOSED
```

- Daily risk учитывается после fill; до него существует reservation с TTL.
- Paper/live/signal datasets не смешиваются.
- Market entry моделируется по ask для BUY и bid для SELL плюс impact.
- Limit fill требует touch после `signal_at`; консервативная модель учитывает очередь/ликвидность.

### P0-07. Корректные outcomes и один exit contract

**Наблюдение [ДОКУМЕНТ]:** tracker раз в 300 секунд использует ticker и high/low recent candle; одновременно заявлены один структурный TP и лестница TP1=2R, TP2=3R, TP3=4R, breakeven/trailing/time stop.

**Риски:**

- порядок SL/TP внутри одной свечи неизвестен;
- high/low мог возникнуть до `signal_at` или `filled_at`;
- gap может исполнить stop хуже уровня;
- retry/restart может повторно применить partial close;
- выбранный структурный TP может находиться, например, на 2.3R, а position manager всё равно ожидает 3R/4R;
- `P(TP)` неясно: это TP плана, TP1, полный TP3 или положительный net outcome;
- time stop 100 минут меньше одного H4-бара и не соответствует H1/H4 тезису.

**Требуемое изменение:**

- Один `ExitPlan` является источником правды для probability label, notification, tracker и PnL.
- Каждая ступень имеет `price`, `fraction`, `trigger`, `stop_after`, `event_id`.
- Milestone уникален по `(position_id, event_type, plan_version)` и применяется идемпотентно.
- Использовать trades/1m после `filled_at`; если порядок неразрешим — `AMBIGUOUS_INTRABAR` либо заранее выбранный worst-case, но не оптимистический win.
- Time stop задавать в закрытых барах конкретного TF или по `thesis_expires_at`.
- Flip bias разрешён только по закрытому, causal BOS.

**Тесты:** pre-entry high/low игнорируется; same-bar SL+TP даёт ambiguous/worst-case; повторный запуск не закрывает долю дважды; gap использует худшую доступную цену; restart в каждой точке даёт тот же итоговый PnL.

### P0-08. Атомарная Phase 8 и outbox

**Наблюдение [ДОКУМЕНТ]:** `save_signal → trace.save → audit OK → create_outcome → record_trade_opened → cooldown → Telegram` — последовательные отдельные шаги.

**Риск:** сбой между шагами оставляет сигнал без outcome, риск без cooldown или сохранённый сигнал без уведомления; retry создаёт дубликат.

**Требуемое изменение:** в одной DB-транзакции сохранить candidate terminal state, signal, trace, reservation/ledger, cooldown и outbox event. Telegram отправлять после commit с at-least-once delivery и idempotency key `signal_id`.

Добавить уникальный fingerprint, например:

```text
venue + market_type + strategy_version + symbol + timeframe
+ setup_type + trade_direction + causal_event_ids + decision_candle_ts
```

Fault-injection после каждого DB-шага должна приводить либо к полному commit, либо к полному rollback.

### P0-09. Вероятность, ML и отсутствие утечки

**Наблюдение [ДОКУМЕНТ]:** rules-based score называется `p_tp`; ML включается примерно от 100 samples; expected-return ветка использует isotonic calibration; retrain идёт ежедневно.

**Проблемы:**

1. `50% + бонусы − штрафы` не является измеренной вероятностью. Постоянный `confidence=0.4` не делает score откалиброванным.
2. Mandatory признаки получают бонус повторно: прошедший reversal почти всегда уже имеет sweep+displacement+MSS, а затем получает за них около `+10` пунктов.
3. HTF/structure/MTF, OB gate/OB feature/OB multiplier и regime/ATR частично дублируют информацию.
4. Base rate после 10 исходов крайне шумный; scenario segmentation ещё уменьшает эффективную выборку.
5. Если outcomes есть только у прошедших сигналов, модель обучается на выбранной политикой подвыборке и не умеет оценивать отвергнутые кандидаты.
6. Исторический backtest внешних context features может случайно использовать текущий Fear & Greed/news/OI вместо point-in-time значения.
7. Random K-fold смешает будущее с прошлым и одинаковые рыночные события между train/test.
8. Isotonic calibration на малой выборке легко переобучается. Официальная документация scikit-learn предупреждает, что isotonic обычно требует порядка более 1000 calibration samples; при существенно меньшем объёме предпочтительнее sigmoid или отказ от сложной калибровки. См. [Probability calibration](https://scikit-learn.org/stable/modules/calibration.html).
9. Вероятность должна зависеть от конкретной цели и horizon: один setup не может иметь одну и ту же `P(TP)` для 2R и 8R.
10. Умножение уже откалиброванной ML-вероятности на HTF/OB/Elliott penalties снова разрушает calibration. Все такие факторы должны войти в модель до финальной OOF-калибровки либо пройти отдельную повторную калибровку.

**Требуемое изменение:**

- До доказанной калибровки переименовать rules output в `heuristic_quality_score` и запретить использовать его как Kelly probability.
- Логировать и paper-track все `SetupCandidate`, включая отвергнутые фильтрами, с неизменяемым point-in-time snapshot.
- Явно определить label и horizon: например `net_R_after_exit_policy`, а не неоднозначный `hit_tp`.
- Split только по времени; использовать rolling/expanding walk-forward с gap/embargo не короче максимального horizon сделки. Базовый инструмент scikit-learn для time-ordered split описан в [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html), но purge/embargo для перекрывающихся сделок нужно добавить отдельно.
- Группировать одинаковые рыночные эпизоды и cross-TF сигналы, чтобы они не попадали в разные folds.
- Calibration fit только на out-of-fold predictions; финальный locked holdout не использовать для выбора признаков/порогов.
- Проверять Brier/log loss, calibration curve и calibration intercept/slope. Brier — proper scoring rule для вероятностного прогноза: [scikit-learn Brier score](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.brier_score_loss.html).
- Model artifact хранит training cutoff, feature schema hash, config/code version и OOS metrics; публикация модели атомарна, scan фиксирует одну model version до конца.
- При недостатке данных оставаться в rules/shadow и fixed-risk режиме.
- `profit_factor`, вычисленный из `p` и планового RR, называть `implied_pf`; realized PF считать только по фактическим net outcomes.

**Минимальный критерий допуска ML к sizing:** положительный net EV на нескольких последовательных OOS-окнах, калибровка лучше constant/base-rate baseline, стабильный эффект после costs, доверительный интервал не держится на одном symbol/regime и отсутствуют нарушения temporal tests.

---

## 5. P1: стратегия и параметры

### P1-01. Оценивать reversal и continuation независимо

Сейчас reversal имеет приоритет, continuation — fallback. Если reversal формально найден, но позже заблокирован OB/HTF/risk gate, хороший continuation уже не рассматривается.

`PatternEngine.detect()` должен возвращать `list[SetupCandidate]`. Каждый кандидат проходит собственную политику; затем выбирается лучший по **net expected utility**, а не по порядку `if/else`. В тесте «reversal заблокирован, continuation валиден» continuation должен дойти до результата.

### P1-02. Разделить core validity и independent confluence

`confirmation_score >= 2`, где BOS уже даёт 2, ничего не фильтрует у continuation. Для reversal обязательные sweep/displacement/MSS снова повышают псевдовероятность.

Предлагаемая схема:

```text
core_validity:
  reversal = causal sweep + reclaim + displacement + MSS
  continuation = trend context + pullback + causal BOS

entry_route:
  ob_retest | fvg_retrace | either | market_after_break

independent_confluence:
  session | SMT | relative volume | HTF POI | order-flow confirmation
```

Core не получает второй бонус. Не надо просто менять minimum с 2 на 3: сначала нужно исправить смысл score.

### P1-03. OB/FVG как конечные автоматы, а не booleans

`REQUIRE_OB_RETEST=true`, `REQUIRE_ENTRY_ZONE=false` и возможность setup без OB образуют неясную политику. `ob.retested` и `MITIGATED` также могут конфликтовать.

Вместо комбинации флагов ввести:

```text
ENTRY_ROUTE = ob_retest | fvg_retrace | either | market_after_break

OB:  NEW → TOUCHED → REACTED → MITIGATED/BROKEN/EXPIRED
FVG: NEW → PARTIAL → FILLED/INVALID/EXPIRED
```

- Touch определяется пересечением high/low с зоной, а reaction — направленным закрытием после touch.
- Wick rejection, закрывшийся за пределами зоны, не должен отклоняться только потому, что `last_close` уже не внутри.
- OB строится от origin candle causal displacement leg, вызвавшего MSS/BOS, а не от просто близкого блока в обратном lookback.
- FVG подтверждается после закрытия третьей свечи; missing OHLCV bar не может создать FVG.
- Retest обязан быть после `confirmed_at` зоны и относится к текущему setup.

### P1-04. Breakout Quality должен зависеть от setup type

Для reversal ложный breakout/stop-hunt является частью идеи sweep. Единый hard gate `BREAKOUT_FAKE` способен удалить лучшие reversal.

- Continuation: подтверждать close-through, retention и приемлемый participation.
- Reversal: fake breakout + reclaim считать положительным, если выполнена causal reversal chain.
- Спецправило `body >= 0.5 and score >= 25 => real` фактически позволяет одному body пройти без retention: `+40−15=25`. Это противоречит основному порогу 55.
- Сумма положительных весов равна 105 при заявленном диапазоне 0–100 — нужен clamp и тест границ.
- OI growth сам по себе не показывает направление: его следует интерпретировать вместе с price move/order flow, а не как самостоятельный directional vote.

До переработки разумно оставить `BREAKOUT_QUALITY_HARD_GATE=false`.

### P1-05. HTF bias: relative hierarchy вместо majority vote

Для H4 сигнала H4 не является higher timeframe. Незакрытая W1/D1/H4 свеча также не может участвовать. Равный vote W1/D1/H4 и override W1 голосами D1+H4 больше похожи на horizon ensemble, чем на top-down bias.

Рекомендуется:

- H1 setup: H4/D1/W1 context;
- H4 setup: D1/W1 context;
- continuation: alignment может быть hard/strong soft condition;
- reversal: HTF POI + liquidity raid + LTF MSS важнее уже развернувшихся EMA21/55;
- сначала перевести HTF gate в shadow и сравнить отдельно reversal/continuation;
- EMA, BOS и MTF не давать несколько независимых бонусов за один трендовый факт.

### P1-06. Выбор target и exit policy

В тексте перечислен type bonus, но формула target score показывает только `strength × min(1, RR/3) × path_factor`. Это надо сверить в коде.

Проблема текущей оптимизации: дальняя сильная цель может выиграть score, даже если перед ней есть opposing zone, а затем весь setup будет отвергнут RR gate, хотя другой target был валиден.

Новая последовательность:

1. Получить targets, существовавшие на `as_of` и находящиеся с правильной стороны entry.
2. Для каждого построить полный net-cost ExitPlan.
3. Отфильтровать structural invalidity и неприемлемый net EV.
4. Считать вероятность/время достижения для каждого target.
5. Выбрать лучший expected utility; ближайшую встречную ликвидность использовать как TP1 или path constraint.
6. После LTF repricing повторить расчёт.

### P1-07. Dedup по идентичности setup, не по времени

Разный OB midpoint не гарантирует новый рыночный эпизод; один setup может породить несколько близких OB. Setup без OB, по самому документу, способен обойти `ob_aware` cooldown. Cross-direction half-cooldown может, напротив, заблокировать настоящий reversal после инвалидирования.

Решение:

- stable `setup_fingerprint` из causal event IDs;
- один signal на `setup_version`;
- повтор только при material change: новый confirmed break, новая зона/entry route, изменившийся plan version или явная invalidation предыдущего;
- без OB использовать causal fingerprint, а не молча bypass;
- cross-TF кандидаты одного symbol консолидировать до атомарного portfolio commit.

### P1-08. Execution checks должны зависеть от размера позиции

`$10,000` глубины в пределах `0.5%` не говорит, можно ли исполнить конкретный ордер с предполагаемым slippage `0.05%`. Для BUY важны asks, для SELL — bids.

Нужно симулировать consumption свежего order book:

```text
entry_vwap(candidate_qty)
exit_vwap_or_stress(candidate_qty)
impact_bps
total_cost_bps
snapshot_age_ms
```

Gate должен сравнивать impact с stop distance и estimated edge. Абсолютный threshold оставить лишь emergency floor. Проверить tick/amount precision, min notional и `contractSize`. Spread и depth берутся из одного snapshot непосредственно перед reservation.

### P1-09. Полная data-integrity проверка

`dropna()` может сжать время и сделать несоседние свечи соседними. Требуются:

- строго возрастающие уникальные timestamps;
- ожидаемая сетка интервалов и явные gaps;
- `high >= max(open, close)`, `low <= min(open, close)`, положительные цены/объёмы;
- `isfinite()` для entry, SL, TP, ATR, probability, fees и всех числовых features; `NaN/inf` всегда fail-closed;
- после price/tick rounding повторно проверить `BUY: SL < entry < TP`, `SELL: TP < entry < SL`;
- minimum warm-up больше максимального indicator/structure lookback;
- stale/finality checks;
- различение spot, linear perpetual и inverse perpetual;
- единый price type: trade/last для структуры, documented mark/last/index для stop trigger;
- `since` и `limit` задаются явно, потому что default history у exchange различается;
- пропуск не «лечится» удалением строки при расчёте FVG/swing.

Optional context может fail-open только с `missing=true`, `source`, `observed_at`, `age`. Binance long/short ratio для BingX следует маркировать как cross-venue proxy, а не как данные BingX.

### P1-10. Scheduler, sessions и durable state

- Ограничить `asyncio.gather` semaphore/worker pool; проверить `ccxt.async_support`, rate limiter, timeout и bounded retry.
- Разобрать каждый результат `return_exceptions=True`; exception — `SYSTEM_ERROR`, не отсутствие setup.
- APScheduler: timezone UTC, `max_instances=1`, `coalesce`, `misfire_grace_time`.
- Хранить durable watermark последней обработанной закрытой свечи; restart не должен терять или дублировать бар.
- London/New York рассчитывать через `Europe/London` и `America/New_York`, а не фиксированный UTC; hard session filter пока оставить выключенным.
- Общий 100-minute time stop и 30-minute breaker pause заменить TF-relative duration или числом закрытых баров.
- SQLite: WAL, `busy_timeout`, foreign keys, короткие write transactions, при необходимости writer queue.

### P1-11. «Shadow» должен быть действительно shadow

Документ говорит, что Thesis/Scenario/Hypothesis не влияют на сигнал, но `_thesis_score` и `_thesis_stability` меняют risk multiplier, а `_entry_target` участвует в Entry Trigger. Это материальное влияние.

Варианта два:

1. `shadow=true`: изменение output не меняет pass/fail, entry, SL/TP, risk и notification;
2. `shadow=false`: модуль официально находится в decision path, версионируется, логируется и проходит OOS/ablation test.

### P1-12. Корреляция и фактический риск

Правило «если correlated symbol уже открыт — block» одновременно слишком грубое и уязвимое к гонке. BTC H1, BTC H4 и ETH часто являются одной factor exposure.

Минимально:

- агрегировать risk по base asset, side и correlation cluster;
- учитывать pending reservations, а не только open positions;
- различать усиливающую позицию и хедж;
- считать remaining open risk после partial/BE;
- лимит применять атомарно к marginal cluster risk.

До доказательства независимости нельзя считать три криптосигнала по 1% тремя независимыми рисками.

---

## 6. Аудит конкретных параметров

Числа ниже нельзя менять все одновременно. Сначала исправляется причинность и симуляция, затем каждый параметр исследуется на последовательных OOS-окнах. Выбирать нужно устойчивое плато, а не лучший одиночный point.

| Параметр | Оценка | Рекомендация |
|---|---|---|
| Scan каждые 15 мин для H1/H4 | Сомнительно | Detector только на новом closed bar; watcher можно чаще |
| Sweep lookback 50 / OB 100 | Не универсально по TF | Оставить как discovery window, но отделить короткий setup TTL; задавать per-TF/duration |
| Sweep→MSS causal window 10 | Вероятно слишком широк для части режимов | **[ЭКСПЕРИМЕНТ]** `2, 3, 5` баров; 10 оставить benchmark |
| Half-life 3 | Не доказан | Подбирать только совместно с TTL; логировать raw age, не только decay |
| Reclaim <=2 bars | Логично как старт | **[ЭКСПЕРИМЕНТ]** сравнить 1 и 2, отдельно H1/H4 |
| MSS displacement >=0.2 ATR | Слишком слабый и неясно к какой свече привязан | Единый event; **[ЭКСПЕРИМЕНТ]** body/ATR `0.6, 0.8, 1.0, 1.2`, body/range `0.55, 0.65, 0.75` |
| OB reverse lookback 20 | Семантически слаб | Искать origin candle causal displacement leg; lookback только safety bound |
| Confirmation BOS=2, min=2 | Вырожден у continuation | Перепроектировать validity/confluence; не лечить одним новым порогом |
| Breakout score 55 + override 25 | Внутренне противоречив | Убрать shortcut, разделить setup types, clamp 0..100 |
| Volume ratio 1.2/1.5/2.0 | Зависит от symbol/session | Использовать rolling percentile/z-score по symbol×TF×session; raw ratio сохранить |
| ATR filter 0.3–5% | Один диапазон не переносим между H1/H4 | Rolling quantiles по symbol×TF; аварийные абсолютные bounds оставить отдельно |
| ATR sweet spot 1–3% | Особенно сомнителен для H1 majors | Только OOS per-TF; не давать общий bonus |
| HTF W1/D1/H4 majority | Не top-down в строгом смысле | TF-relative hierarchy; reversal и continuation тестировать отдельно |
| `BASE_RISK_PCT=1%` | Высоко до доказанной калибровки, особенно при коррелированных сигналах | В shadow/paper измерять; если реальный риск уже используется, временный safety ceiling **0.25–0.50% на setup** и **1.0–1.5% на correlation cluster** до прохождения OOS/stress — не «оптимальные» значения |
| `MAX_PORTFOLIO_RISK=3.7%` | Не защищает без prospective atomic check | Проверять marginal risk и correlation clusters; включать costs/gap |
| `MAX_ACTIVE=3`, positions=5 | Семантика неясна | Разделить signals, reservations, filled positions; документировать каждый cap |
| `MIN_RR=2.0` | Может быть разумным только как net RR | Считать after-cost payoff всего ExitPlan; сравнить target-specific EV, не максимизировать RR |
| SL absolute min 0.25% | Costs могут доминировать | Минимум выводить из spread+fee+impact и structural noise, а не одной константы |
| ATR fallback 1.5×ATR | Конфликтует с hard floor 2×ATR | Сделать одну согласованную политику; сейчас fallback — потенциально dead path |
| SL ATR floor 2×ATR | Может уничтожать структурный смысл ICT | Использовать structure invalidation + buffer; **[ЭКСПЕРИМЕНТ]** buffer `0.10–0.30 ATR_at_event`, а не обязательную общую дистанцию 2 ATR |
| Dynamic SL max=`max(5%,2.2×ATR)`, cap 8% | Название `max` двусмысленно; фактически разрешает расширение до 8% | Проверить намерение. Max-distance обычно upper bound; широкий SL допустим только при уменьшении quantity и liquidation check |
| SL `<1%` risk bonus 1.1× | Опасное направление при высоком cost/noise ratio | Убрать до OOS; узкий stop не означает более качественный setup |
| `MIN_P_TP=.30/.40/.50` | Не согласовано единым EV-критерием | Заменить на target-specific `EV_net` и lower-confidence bound; side/setup thresholds — только после доказанного calibration drift |
| Historical base rate от 10 | Слишком шумно | Bayesian shrinkage к глобальному base rate; показывать effective N и interval |
| ML start >=100 | Недостаточно для ~50 features и calibration | Не задавать один magic N; learning curves. Isotonic обычно не использовать при calibration N значительно меньше ~1000 |
| Probability clamp 5–85% | Маскирует, но не исправляет плохую calibration | Clamp только numerical safety; не считать доказательством качества |
| Fixed confidence 0.4/0.8 | Не статистическая confidence | Заменить uncertainty interval/ensemble dispersion/OOS error |
| Spread max 0.15% | Не связан с edge/size | Gate по total cost bps и доле stop/edge; threshold per market |
| Depth $10k в 0.5% | Не связан с candidate notional и 5 bps slippage | Side-specific VWAP на candidate quantity в пределах реального slippage budget |
| Cooldown 45 min × 2 TF | Время не равно новому setup | Stable event fingerprint; TTL в барах/до invalidation |
| Same OB cooldown 1/3 | Может спамить один thesis | Once per setup version; repeat только при material change |
| Cross-direction half cooldown | Может блокировать настоящий flip | Разрешать после подтверждённой invalidation/нового causal chain |
| Circuit breaker 3 SL / 30 min | Не учитывает net R и TF | Rolling realized-R/drawdown breaker, scope symbol/cluster; recovery не короче meaningful TF event |
| Time stop 100 min | Непригоден одновременно H1 и H4 | Bars или `thesis_expires_at`; **[ЭКСПЕРИМЕНТ]** 2/3/5 signal bars |
| Breakeven 1.5R, TP 2/3/4R | Может не совпадать со структурным TP и обучающим label | Единый ExitPlan; параметры тестировать как policy целиком |
| Session UTC 0–7/7–12/12–16/16–21 | Не ICT kill zones и не учитывает DST | IANA zones, event timestamp, отдельные minute windows; hard gate оставить off |
| Premium/Discount off | Разумно оставить off | Не включать по одному PF без sample size, CI и locked OOS |
| Elliott Wave active | Высокая свобода модели | Только shadow до стабильного ablation benefit |

### Исследовательские сетки для risk/exit policy

Это не рекомендации немедленно поставить значения в `.env`. Это небольшие заранее объявленные сетки для nested walk-forward; число комбинаций нужно ограничивать, а целевую функцию и drawdown constraint фиксировать до запуска.

| Область | Кандидаты **[ЭКСПЕРИМЕНТ]** |
|---|---|
| EV safety buffer | `0`, `0.05R`, `0.10R`, `0.15R`; предпочтительно решение по нижней CI net EV |
| Probability margin | `p_break_even + {0, 3, 5, 10}` процентных пунктов вместо отдельных magic thresholds по side |
| Fractional Kelly | `0.10`, `0.20`, `0.25` полного Kelly против fixed-risk baseline; без ненулевого floor |
| Per-setup risk cap | `0.25%`, `0.50%`, `0.75%`, `1.00%` equity |
| Portfolio stressed open risk | `1.5%`, `2.0%`, `2.5%`, `3.0%` |
| Correlation-cluster cap | `0.75%`, `1.0%`, `1.5%` |
| Net minimum RR | `1.5`, `2.0`, `2.5`, `3.0` против чистого target-specific EV gate |
| SL total distance | `1.0`, `1.5`, `2.0 ATR`; генератор fallback обязан совпадать с gate |
| All-in friction / stop | не более `1/3`, `1/5`, `1/8` stop distance |
| Setup expiry/cooldown | `1`, `2`, `3` полностью закрытых setup-TF бара плюс invalidation state |
| Breakeven | `1.0R`, `1.5R`, `2.0R` как часть всей exit policy |
| Trailing | `1.0`, `1.5`, `2.0`, `2.5 ATR` |
| Time stop | `2`, `4`, `6`, `8` закрытых setup bars |
| Cost stress | empirical median/p75/p90 и `1×/1.5×/2×/3×` realized slippage |
| Executable depth coverage | `5×`, `10×`, `20×` candidate notional, одновременно с VWAP impact gate |
| ML promotion checkpoints | learning curves на `500`, `1000`, `2000` effective independent labels; это checkpoints, не автоматический допуск |

Продвигать вариант можно только если улучшение сохраняется в большинстве OOS folds, после realistic costs, не ухудшает tail risk сверх заранее заданного ограничения и не держится на одном symbol/regime.

### Замечание по EMA/RSI/MACD/ADX

В конфигурации есть RSI 10/72/28, MACD 8/21/5 и ADX minimum 26, но в описанном gate path неясно, какие из этих thresholds реально активны, а какие только features/dead config. Mimo должна сделать `config reachability audit`: для каждого параметра найти место чтения, влияние на решение и тест. Неиспользуемые параметры удалить либо явно отметить `feature_only`/`deprecated`; иначе оператор думает, что меняет стратегию, хотя поведение не меняется.

---

## 7. Целевая логика пайплайна

### 7.1 Два контура вместо одного длинного scan

```text
[Closed-bar Detector]
  immutable multi-TF snapshot
  → causal events
  → reversal[] + continuation[]
  → core validity
  → persist ARMED_SETUP with TTL/invalidation

[Entry Watcher]
  fresh quote/order book + closed LTF bars
  → POI touch/reaction
  → LTF confirmation after touch
  → rebuild plan and net costs
  → calibrated EV gate
  → atomic portfolio reservation
  → SIGNAL/PAPER ORDER
```

Такой дизайн позволяет сканировать entry чаще 1h/4h, не пересчитывая историческую структуру по незакрытой свече.

### 7.2 Минимальный псевдокод

```python
ctx = await build_decision_context(as_of=exchange_time())
assert_all_sources_are_point_in_time(ctx)

if new_closed_strategy_bar(ctx):
    events = detect_causal_events(ctx.closed_bars)
    candidates = detect_reversal_candidates(events) + detect_continuation_candidates(events)
    await persist_armed_candidates(candidates)

for candidate in await load_live_armed_candidates(ctx.as_of_utc):
    trigger = evaluate_entry_route(candidate, ctx.closed_ltf_bars, ctx.live_quote)
    if not trigger.confirmed:
        continue

    plan = rebuild_trade_and_exit_plan(candidate, trigger.executable_price, ctx)
    estimate = estimate_outcome_distribution(candidate, plan, ctx.model_version)
    risk = size_from_net_loss(plan, estimate, ctx.portfolio)

    if estimate.net_ev_lower_bound <= 0 or risk.fraction <= 0:
        block("EV_GATE_FAILED")
        continue

    await finalize_candidate_atomically(candidate, plan, estimate, risk)
```

### 7.3 Инварианты базы

1. На один candidate run приходится ровно один terminal status: `PASSED`, `POLICY_BLOCKED`, `NO_SETUP`, `DATA_ERROR`, `SYSTEM_ERROR`, `CANCELLED`.
2. `planned = passed + blocked + no_setup + data_error + system_error + cancelled`.
3. Один `signal_id` не создаёт два outcome, reservation или milestone.
4. Network calls и ML inference не выполняются внутри write transaction.
5. Telegram failure не откатывает сигнал; outbox доставляет его повторно.
6. Trace сохраняется и для blocked/error, а не только для успешного signal.
7. `config_snapshot` строится allowlist-ом и не содержит API keys, Telegram token или DSN.

---

## 8. Правильная проверка прибыльности

До изменения параметров необходимо заморозить `strategy_version` и получить point-in-time replay. Простого общего win rate недостаточно.

### Dataset

- одна строка на независимый `SetupCandidate`, а не на каждый повторный scan;
- все признаки имеют `observed_at` и были доступны на decision time;
- rejected candidates также paper-track, иначе невозможно оценить пользу gates;
- cross-TF дубликаты объединены `market_event_id`;
- label — итоговый `net_R` единого ExitPlan после fees, spread, impact, slippage, funding и gap policy;
- ambiguous outcomes маркируются и анализируются отдельно; нельзя молча считать их wins.

### Validation

1. Expanding/rolling walk-forward по времени.
2. Purge/embargo не меньше максимального срока жизни сделки, чтобы overlapping outcomes не пересекали train/test.
3. Parameter selection только на train/validation.
4. Один final holdout заблокирован до завершения дизайна.
5. Bootstrap/block-bootstrap по временным блокам, а не по отдельным коррелированным сигналам.
6. Отчёт отдельно по `setup_type × side × symbol × TF × regime × session`.
7. Сравнение с простыми baseline: base rate, HTF-only, core-pattern without add-ons.
8. Ablation для каждого фильтра: изменение net expectancy, coverage, drawdown и calibration.

### Метрики допуска

- net expectancy в R/trade с доверительным интервалом;
- realized profit factor с доверительным интервалом — не путать с `implied_pf` из p и RR;
- max drawdown, tail loss, longest loss cluster;
- fill rate и доля expired entries;
- turnover и total costs;
- Brier/log loss/calibration slope/intercept для вероятности;
- stability по последовательным OOS-окнам;
- effective number of independent market events;
- parameter surface: устойчивое плато лучше одиночного максимума.

Нельзя делать вывод «фильтр улучшил PF с 1.28 до 0.91/обратно» без числа сделок, периода, costs, confidence interval и проверки, не использовался ли тот же отрезок для выбора решения.

---

## 9. Пошаговый план для Mimo v2.5

### Этап A — forensic audit без изменения поведения

1. Найти все места чтения последней свечи, отрицательные shifts, centered rolling и HTF joins.
2. Составить карту `config parameter → reader → decision impact`.
3. Проверить формулы fee-adjusted RR, EV, profit factor, Kelly, quantity и units.
4. Проверить transaction boundaries, UNIQUE/FK, cooldown/daily/circuit persistence.
5. Проверить, сохраняется ли trace при каждом раннем `return None`.
6. Добавить characterization tests, фиксирующие текущее поведение до рефакторинга.

### Этап B — temporal correctness

1. Ввести `DecisionContext/as_of` и валидатор OHLCV.
2. Добавить `pivot_at/confirmed_at/available_from`.
3. Реализовать causal `SetupCandidate` и stable event IDs.
4. Разделить closed-bar detector и entry watcher.
5. Повторно строить plan после фактического entry repricing.

### Этап C — state, risk и persistence

1. Ввести signal/paper/live state machine.
2. Реализовать net-cost ExitPlan и EV gate.
3. Исправить Kelly zero/minimum clamp и prospective portfolio limits.
4. Сделать atomic reservation/finalization и outbox.
5. Сделать tracker идемпотентным и устранить intrabar optimism.

### Этап D — стратегия

1. Возвращать оба типа кандидатов.
2. Разделить core validity, entry route и confluence.
3. Формализовать OB/FVG lifecycle.
4. Разделить breakout/HTF policies по setup type.
5. Перейти на event-based dedup и position-size-aware marketability.

### Этап E — ML и параметрические эксперименты

1. Построить point-in-time candidate dataset.
2. Добавить purged walk-forward и locked holdout.
3. Переименовать эвристический `p_tp` либо откалибровать OOF prediction.
4. Включать ML в sizing только после прохождения критериев из раздела 8.
5. Тестировать небольшие заранее объявленные сетки, версионировать каждый эксперимент.

### Правила внесения изменений

- Не менять все thresholds одним commit.
- Текущую логику сохранить как `legacy_v2_5` baseline для replay.
- Каждое изменение поведения получает новую `strategy_version`, migration и reason code.
- Новые numeric values сначала config + shadow report, затем OOS, только потом hard gate.
- Нельзя подавлять исключение как `PATTERN_NO_SETUP`.
- После каждого этапа запускать unit, integration, replay и concurrency tests.

---

## 10. Минимальный обязательный набор тестов

### Temporal и ICT

- `test_only_closed_candles_are_used`
- `test_prefix_invariance_no_future_leakage`
- `test_swing_available_only_after_right_bars`
- `test_event_atr_not_recomputed_from_future_atr`
- `test_sweep_displacement_mss_order_and_direction`
- `test_htf_backward_asof_join`
- `test_ltf_confirmation_occurs_after_poi_touch`
- `test_reversal_rejected_continuation_still_evaluated`
- `test_trade_plan_rebuilt_after_entry_change`

### Risk и persistence

- `test_long_short_mirror_symmetry`
- `test_price_scale_invariance_for_normalized_rules`
- `test_nan_and_inf_fail_closed`
- `test_cost_increase_cannot_improve_ev_or_size`
- `test_negative_ev_is_rejected`
- `test_zero_kelly_is_not_raised_to_min_risk`
- `test_candidate_risk_is_included_in_portfolio_limit`
- `test_atomic_risk_reservation_under_concurrency`
- `test_duplicate_candidate_race_creates_one_signal`
- `test_phase8_fault_injection_rolls_back_or_commits_all`
- `test_outbox_recovers_notification_after_restart`
- `test_config_snapshot_redacts_secrets`

### Execution и outcome

- `test_buy_uses_ask_and_sell_uses_bid`
- `test_stale_or_crossed_book_is_rejected`
- `test_depth_vwap_uses_candidate_quantity_and_correct_side`
- `test_tracker_ignores_pre_entry_extremes`
- `test_same_bar_sl_tp_is_ambiguous_or_worst_case`
- `test_gap_through_stop_uses_adverse_fill`
- `test_partial_exit_is_idempotent_after_restart`
- `test_unfilled_entry_expires_without_outcome_trade`
- `test_contract_size_and_precision_rounding`
- `test_partial_fractions_sum_to_one_and_never_overclose`

### Scheduler и data quality

- gaps, duplicates, out-of-order, stale and incomplete OHLCV;
- retry/rate limit/timeout/malformed response;
- bounded concurrency and no `database is locked` loss;
- scheduled + manual scan share one lock;
- misfire/coalesce/restart watermark;
- London/NY DST boundary tests;
- model atomic swap and fixed version per scan.

---

## 11. Проверка замечаний, уже указанных в исходном документе

| Исходное замечание | Независимая оценка |
|---|---|
| News Filter — заглушка | Верно; optional news должен быть explicit missing, а не ложный neutral |
| BingX long/short отсутствует | Верно; Binance ratio можно использовать только как маркированный proxy |
| Shadow engines не влияют | Неверно по собственному описанию: thesis меняет risk, hypothesis может менять trigger |
| ML от 100 samples | Недостаточно как общее правило, особенно для ~50 features и isotonic calibration |
| Elliott Wave может быть неактивен | Оставить shadow; сначала доказать causal implementation и ablation benefit |
| Premium/Discount ухудшил PF | Оставить off, но вывод без N/CI/locked OOS недоказателен |
| Confirmation minimum 2 | Проблема глубже: core и confluence смешаны; BOS уже автоматически даёт 2 |
| Positions 5 vs active signals 3 | Нужно разделить candidate/reservation/fill/position semantics |
| `ob_aware` без OB обходит cooldown | Верно; лучше event fingerprint, strict fallback — лишь временная мера |
| Kelly не увеличивает выше base | Может быть намеренным cap, но важнее: Kelly<=0 не должен оживать через min clamp |

---

## 12. Внешние технические основания

Использованы только официальные/первичные технические источники:

1. [CCXT Manual: OHLCV, gaps, incomplete current candle and latency](https://docs.ccxt.com/docs/manual#ohlcv-candlestick-charts)
2. [CCXT FAQ: perpetual contracts and `contractSize`](https://docs.ccxt.com/docs/faq#whats-the-difference-between-trading-spot-and-swapperpetual-futures)
3. [scikit-learn: TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)
4. [scikit-learn: probability calibration and isotonic sample-size warning](https://scikit-learn.org/stable/modules/calibration.html)
5. [scikit-learn: Brier score loss](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.brier_score_loss.html)

---

## 13. Итоговое задание для Mimo

Не начинать с подбора новых порогов. Сначала проверить исходный код по пунктам P0-01…P0-09 и подтвердить каждый вывод ссылкой `file:line`, тестом и фактической формулой. Если риск из этого аудита уже устранён в коде, не переписывать модуль — добавить доказательный regression test и отметить пункт как `NOT_REPRODUCED`.

Первая безопасная серия изменений должна дать четыре результата:

1. один immutable point-in-time snapshot и только закрытые структурные свечи;
2. один causal setup с устойчивыми event IDs;
3. один согласованный net-cost Entry/ExitPlan и корректный lifecycle fill/outcome;
4. один атомарный portfolio reservation/commit с идемпотентным audit/outbox.

Только после этого имеет смысл оптимизировать displacement, lookbacks, HTF/session filters, exit ladder или обучать ML. Иначе оптимизация будет подбирать параметры под repaint, гонки и неверные labels.
