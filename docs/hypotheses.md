# hypotheses.md — Зафиксированные изменения конфигурации

> Каждое изменение параметра или логики фиксируется здесь до запуска live-сбора.
> Формат: дата, что изменено, почему, impact (если известен).

---

## H-001: sl_absolute_min_pct 0.8% → 0.25%

- **Дата:** до 2026-09-04
- **Что:** `config/settings.py:657` — runtime default изменён с 0.8 на 0.25
- **Почему:** Значение 0.8% существовало только как parameter default в `RiskEngine.__init__`, который всегда перезаписывается `from_config()`. Runtime default = 0.25%. Исправление — приведение документации в соответствие с реальностью.
- **Impact:** Уменьшил минимальный SL с 0.8% до 0.25%, что расширило диапазон допустимых SL на волатильных инструментах.

## H-002: volatility_max_atr_percent 8.0% → 5.0%

- **Дата:** до 2026-09-04
- **Что:** `config/settings.py:218` — runtime default = 5.0%, документация утверждала 8.0%
- **Почему:** Legacy значение в документации не соответствовало коду. Исправлено в logic.md, logic_3.md, logic_up2.1.md.
- **Impact:** При ATR > 5% сигнал блокируется volatility-фильтром. Ранее (при 8%) пропускались инструменты с ATR 5-8%.

## H-003: Displacement detection — body → range (candle_quality.py)

- **Дата:** 2026-09-05
- **Что:** `liquidity/candle_quality.py:104,179` — `is_displacement = body > atr * mult` → `is_displacement = range_val > atr * mult`
- **Почему:** Двойной стандарт: `structure.py:181` использовал high-low для same-candle displacement, а `candle_quality.py` — body (close-open). Это объясняло为什么 `has_displacement = 1%` у detected сигналов.
- **Impact:** Ожидаемый рост `has_displacement` с ~1% до ~5-10%. Больше reversal-сигналов пройдёт displacement gate. MSS threshold (0.2 ATR) не затронут — использует свою метрику.
- **Риск:** +3.0 component_edge в Probability Engine для каждого пропущенного reversal. Может увеличить количество ложных сигналов.

## H-004: A1 SL dead zone — relax min_sl_from_atr

- **Дата:** 2026-09-05
- **Что:** `risk/engine.py:205-213` — при `min_sl_from_atr > dynamic_sl_max` → `min_sl_from_atr = dynamic_sl_max` + warning log
- **Причина:** При ATR 4-5% min SL (2×ATR = 8-10%) превышал max SL (cap 8%) → dead zone. Ранее: с ATR > 2.5% (старый cap 5%),現在: только ATR 4-5% (узкая полоса).
- **Impact:** Сигналы с ATR 4-5% входят с широким SL (8%) и маленьким размером позиции. При ATR > 5% volatility filter блокирует раньше.

## H-005: Entry Trigger независим от Decision Engine

- **Дата:** 2026-09-05
- **Что:** `strategy/entry_trigger.py` + `scheduler/scanner.py:1544-1590` — Entry Trigger работает без Hypothesis, используя SimpleEntryTarget fallback
- **Причина:** При `_liq_graph=None` → `_decision=None` → Entry Trigger пропускался → сигнал без проверки зоны входа.
- **Impact:** Все сигналы теперь проходят проверку entry zone, независимо от наличия Hypothesis.

## H-006: Displacement baseline measurement (post H-003 fix)

- **Дата:** 2026-09-05
- **Что:** Запуск `measure_rejection_rate.py` на 500 свечей (1h) для 4 инструментов после фикса H-003 (body → range).
- **Результаты:**

| Symbol | Detected | Rejected | has_displacement | has_ob | has_fvg | has_bos | has_sweep | has_mss | reversal | continuation |
|--------|----------|----------|------------------|--------|---------|---------|-----------|---------|----------|--------------|
| BTC/USDT | 209 (49.9%) | 210 (50.1%) | 10 (4.8%) | 1 (0.5%) | 66 (31.6%) | 150 (71.8%) | 59 (28.2%) | 59 (28.2%) | 59 (28.2%) | 150 (71.8%) |
| ETH/USDT | 229 (54.7%) | 190 (45.3%) | 6 (2.6%) | 0 (0.0%) | 36 (15.7%) | 158 (69.0%) | 71 (31.0%) | 71 (31.0%) | 71 (31.0%) | 158 (69.0%) |
| SOL/USDT | 155 (37.0%) | 264 (63.0%) | 6 (3.9%) | 9 (5.8%) | 70 (45.2%) | 124 (80.0%) | 31 (20.0%) | 31 (20.0%) | 31 (20.0%) | 124 (80.0%) |
| DOGE/USDT | 165 (39.4%) | 254 (60.6%) | 1 (0.6%) | 1 (0.6%) | 85 (51.5%) | 150 (90.9%) | 15 (9.1%) | 15 (9.1%) | 15 (9.1%) | 150 (90.9%) |

- **Ключевые выводы:**
  1. **Displacement rate остаётся низким (0.6-4.8%)** даже после фикса body→range. Range (high-low) не сильно больше body на типичных свечах — фикс корректен, но не критичен.
  2. **Dominant rejection: "reversal: no MSS (strong CHoCH)"** — 45-63% всех баров. CHoCH детектируется sweep'ом, но MSS (Market Structure Shift) не подтверждается.
  3. **Confirmation score < 2** = sweep count — потому что sweep = MSS для reversal.
  4. **Continuation доминирует** (69-91% detected) — primarily BOS-based.
  5. **OB detection крайне низкий** (0-5.8%) — Order Block детекция не находит OB на типичных свечах.

## H-007: Score gate — убрать hardcoded floor=5, вернуться к конфигу

- **Дата:** 2026-09-15
- **Что:** `scheduler/scanner.py:592` — `max(_min_score, 5)` → `_min_score`. CONFIG_VERSION 4→5.
- **Причина:** Hardcoded floor=5 делал score gate невосприимчивым к конфигу `MIN_SCORE_FOR_SIGNAL=2`. Continuation сетапы (max 4 компонента) блокировались на 100%. За 3 дня — 0 сигналов (104 entered, 72 blocked by score_gate).
- **Impact:** Continuation сетапы с score >= 2 теперь проходят. Risk engine downstream фильтрует по R:R, Kelly, portfolio limits.
- **Risk:** Больше сигналов низкого качества. При сборе данных — анализ winrate по score для data-driven порога.

## H-008: HTF POI — BOS requirement, mitigation filter, dynamic proximity

- **Дата:** 2026-09-15
- **Что:** `strategy/htf_poi.py` — три изменения:
  1. `require_bos=False` → `require_bos=True` для HTF OB (SMC: OB должен быть у основания импульса, сломавшего структуру)
  2. Пропуск `ob.retested=True` (mitigated zones) и `fvg.filled=True` (>70% penetration)
  3. Proximity: фиксированные 2% → `max(1.0%, zone_width * 1.5)` (динамически привязан к ширине зоны)
  4. Confidence bonus +0.15 для OB с BOS
- **Причина:** Старая реализация отклонялась от SMC теории: OB без BOS, митигированные зоны считались валидными, фиксированный proximity не учитывал ширину зоны.
- **Impact:** Меньше HTF POI детектится (фильтрация митигации + BOS), но те что проходят — качественнее. SL placement через HTF POI будет точнее.
- **Risk:** Слишком строгая фильтрация HTF POI может вернуть SL по умолчанию (invalidation/swing) для большинства сигналов.

## H-009: Sweep-only reversals — soft MSS gate

- **Дата:** 2026-09-16
- **Что:** `strategy/pattern_engine.py:346-358` — `_try_reversal` теперь возвращает `detected=True` даже без MSS (has_mss=False). `scheduler/scanner.py:641-650` — MSS gate стал SOFT (log only, не блокирует).
- **Причина:** pattern_engine блокировал 50/104 сетапов как "reversal: no MSS (strong CHoCH)". Sweep сам по себе уже POI в SMC — MSS подтверждает силу, но не обязателен для входа.
- **Impact:** ~50 reversal сетапов в ciclo теперь доходят до confirmation_score и risk engine. MSS влияет на confidence/quality, но не блокирует.
- **Risk:** Больше слабых reversal сигналов. Risk engine downstream фильтрует по R:R.

## H-010: Trend component для continuation сетапов

- **Дата:** 2026-09-16
- **Что:** `strategy/pattern_engine.py:572-591` — `_build_components` добавляет "Trend" для continuation если `structure_trend in (bullish, bearish)`. Continuation BOS-only теперь score=2 (Trend+BOS) вместо 1 (BOS).
- **Причина:** BOS-only continuations (score=1) блокировались score_gate (min=2). Trend alignment — обязательный компонент continuation по теории (trend + BOS).
- **Impact:** BOS-only continuations проходят score_gate. Больше continuation сигналов для сбора данных.
- **Risk:** Trend не добавляет информативности — это констатация факта, а не подтверждение.

## H-011: Sweep min_wick_beyond_level 0.1% → 0.02%

- **Дата:** 2026-09-16
- **Что:** `config/settings.py:257` — `sweep_min_wick_beyond_level` снижен с 0.1% до 0.02% (от цены). Env: `SWEEP_MIN_WICK_BEYOND_LEVEL`.
- **Причина:** Диагностика показала что 91/104 сетапов не детектятся потому что sweep-ы отбрасываются false-sweep фильтром: `wick_pct < 0.1%` (0.005%–0.086% — нормальные свипы). Фильтр был слишком строгий для таймфреймов 1h/4h.
- **Impact:** ~80+ reversal сетапов теперь проходят false-sweep фильтр и детектятся. Больше данных для ML probability engine.
- **Risk:** Некоторые "слабые" свипы (менее 0.02% фитиля) пройдут. Downstream: MSS/confirmation/risk engine фильтруют качество.

## H-012: REVERSAL_REQUIRE_DISPLACEMENT false

- **Дата:** 2026-09-16
- **Что:** `.env` — `REVERSAL_REQUIRE_DISPLACEMENT=false`. Дефолт был `true`.
- **Причина:** Диагностика показала что 9/104 сетапов детектятся как reversal (Sweep+MSS=True), но `has_displacement=False` на ТЕКУЩЕЙ свече → блок. MSS уже подтвердил displacement historical. Проверка текущей свечи — избыточна.
- **Impact:** 9 reversal сетапов теперь проходят displacement gate. Суммарно с H-011: ~90+ сетапов в pipeline вместо 0.
- **Risk:** Меньше фильтрации качества. Risk engine downstream фильтрует по R:R/SL bounds.

## H-013: Confirmation Score — setup-type aware (sweep/MSS for reversal)

- **Дата:** 2026-09-18
- **Что:** `strategy/pattern_engine.py:104-114` — confirmation_score теперь setup-type aware:
  - Reversal: `sweep(2) + MSS(1) + FVG(1) + OB(1)` (вместо BOS-only)
  - Continuation: `BOS(2) + FVG(1) + OB(1)` (без изменений)
  - `scheduler/scanner.py:710` — обновлено описание reason для audit логов.
  - CONFIG_VERSION 8→9.
- **Причина:** Старая формула `BOS(2)+FVG(1)+OB(1)` блокировала 100% reversal сетапов без FVG/OB. Reversal не имеет BOS (он использует sweep+MSS), поэтому confirmation_score=0 всегда. За сутки: 40 кандидатов/цикл блокировались этим гейтом, 0 сигналов. Sweep для reversal — аналог BOS для continuation (trigger event).
- **Impact:** Reversal с sweep проходит confirmation_score (score=2+). Reversal с sweep+MSS (score=3) — ещё лучше. Continuation без изменений (BOS=2→score≥2). Ожидаемый рост прохождения confirmation_score с ~0% до ~70% для reversal.
- **Risk:** Reversal без MSS (sweep-only, score=2) теперь проходит — слабые сетапы. Downstream: risk engine фильтрует по R:R/SL/Kelly. Если false positive вырастут — поднять min_score до 3 или вернуть MSS как requirement.

## H-014: Volatility max ATR 5%→8% + sweep_min_wick 0.02%→0.01%

- **Дата:** 2026-09-18
- **Что:**
  1. `config/settings.py:220` — `volatility_max_atr_percent` default 5.0→8.0
  2. `config/settings.py:257` — `sweep_min_wick_beyond_level` default 0.02→0.01
  3. CONFIG_VERSION 9→10
- **Причина:** Во время ралли (18 сентября) воронка: 150 entered, sent=0. pattern_engine=134 (89%), htf_bias=8, volatility_filter=5, entry_trigger=2. Volatility filter блокировал 5 кандидатов с ATR 5.6-7.3% — во время ралли волатильность выше нормы. Sweep REJECTED: wick 0.005-0.019% < 0.02% — false-sweep фильтр слишком строгий для 1h/4h.
- **Impact:** Volatility filter пропускает кандидатов с ATR до 8% (COTI 7.3%, ARB 6%, STG 5.7% теперь проходят). Sweep filter: wick >= 0.01% проходит (0.005-0.019% sweep'ы теперь детектятся). Ожидаемый рост прохождения pattern_engine + volatility на 10-15%.
- **Risk:** Более волатильные инструменты с ATR 5-8% будут давать сигналы с широким SL. Risk engine downstream фильтрует по R:R/SL bounds. Sweep 0.01% — sangat kecil, mungkin false positives. Monitor winrate.

## H-015: Wave detection — tighter filters for 4h timeframe

- **Дата:** 2026-09-18
- **Что:**
  1. `elliott_wave/analysis.py:153` — `detect_swings(left_bars=2, right_bars=2)` → `(left_bars=3, right_bars=3)` (окно 7 свечей вместо 5)
  2. `elliott_wave/analysis.py:162` — добавлен `min_bars=3` фильтр: минимальное расстояние между pivot points = 3 свечи
  3. `config/settings.py:611` — `min_swing_atr` default 0.5→1.5 (1.5 ATR minimum amplitude)
- **Причина:** На 4h таймфрейме волны отображались в пределах 11 часов (2-3 свечи), что слишком мелко для осмысленного Elliott Wave анализа. `min_swing_atr=0.5` был слишком низким, `left_bars=2/right_bars=2` находил слишком много шумовых swing points.
- **Impact:** Pivot points теперь дальше друг от друга (минимум 3 свечи = 12ч на 4h). ATR-фильтр 1.5x отсеивает мелкие свипы. Результат — более крупные, значимые волны на графике.
- **Risk:** Слишком строгие фильтры могут пропускать валидные волны. Если confidence падает — понизить min_bars до 2 или min_swing_atr до 1.0.


## H-016: Sweep-only dead-end rescue (Option B) + ATR entry proximity

- **Дата:** 2026-09-24
- **Что:**
  1. `strategy/pattern_engine.py` — rescue: оба пути (reversal/continuation) отклонены + есть валидный sweep без MSS → слабый reversal, направление от `sweep_type` (bullish→buy, bearish→sell). Guard M2: спасать только при наличии зоны (`has_ob or has_fvg`), иначе reject `reversal: sweep-only dead-end without zone (no MSS)` (reason code `sweep_dead_end_no_zone`, ветка маппинга в scanner идёт ПЕРВОЙ, т.к. причина содержит и "no MSS").
  2. Причина отказа при обоюдном фейле теперь комбинированная: `"{reversal_rejection} + {continuation_rejection}"` — мотивы обеих ветвей больше не маскируются.
  3. `strategy/probability_engine.py` — sweep edge в reversal: `+3.0` только при `has_mss`, иначе `+1.5` (слабый триггер).
  4. `scheduler/scanner.py` — mss_gate: убран двойной `trace.passed` (SOFT-ветка логировалась и как PASS); SOFT учитывается в `penalties`; telemetry `rescued_sweep_only=1` на pattern PASS (funnel detail + audit `meta`); `_CONFIG_VERSION` 11→12.
  5. Phase 2 — ATR-проксимити: `resolve_proximity_pct = max(ENTRY_PROXIMITY_PCT, atr_pct * ENTRY_PROXIMITY_ATR_MULT)` (`strategy/entry_trigger.py`), применено в обеих точках EntryTrigger (Phase 1.6 и Phase 4.5). Дефолты 0.3 / 0.5. Новые env-ключи `ENTRY_PROXIMITY_PCT`, `ENTRY_PROXIMITY_ATR_MULT` в `.env` и `.env.example`; ключи добавлены в `build_config_snapshot()`.
- **Причина:** Живая воронка 2026-09-24 18:19: `entered=150, sent=0`; `pattern_engine=95` (63%), исторически 5982x `"reversal: sweep only (no MSS)"` — sweep-триггер есть, MSS отсутствует, оба пути мертвы (H-009 задокументирован, но не реализован). `entry_trigger=19` — фиксированный 0.3% при ATR 1-4%.
- **Impact:** Ожидание: часть класса sweep-only со зоной OB/FVG проходит pattern_engine (rescued); калибровка по офлайн-реплею 7д — сдвиг воронки. `sent>0` может остаться 0 из-за `MIN_P_TP_REVERSAL=0.50` при сниженном edge +1.5 — это ОК, важен сдвиг воронки и телеметрия rescued. ATR-проксимити: BTC 1h (ATR~1%) → 0.5% вместо 0.3%; альты (ATR~4%) → 2%.
- **Risk:** Приток слабых reversal-сигналов. Защита: guard (только со зоной), reduced sweep edge, `MIN_P_TP_REVERSAL=0.50`, risk engine downstream. Мониторинг: доля `rescued_sweep_only=1` в audit meta, доля rescued среди отправленных, winrate rescued-когорты. Откат: revert rescue-блока в `pattern_engine.detect()` + `ENTRY_PROXIMITY_ATR_MULT=0` (проксимити вырождается в legacy floor).
- **Тесты:** `tests/test_new_pipeline.py` (rescue/guard/merge/continuation-priority + bare-sweep edge), `tests/test_entry_trigger.py` (TestResolveProximityPct), `tests/test_scanner.py` (mss_gate SOFT reachable).

## H-017: daily_limits — единицы daily_pnl: price % → capital %

- **Дата:** 2026-10-01
- **Что:**
  1. `scheduler/outcome_tracker.py` — новый хелпер `_capital_pnl_pct(net_price_pct, entry, sl, risk_pct)`; все 3 вызова `daily_limits.record_trade_closed()` теперь передают capital PnL % вместо price move %. Формула: `capital% = (net_price% / sl_distance%) × risk_pct` (R-множитель × риск на сделку). Fallback при нечитаемом SL — ±1R (`config.risk_engine.base_risk_pct`). Пороги `PROFIT_TARGET_DAILY_PCT=10` / `MAX_DRAWDOWN_DAILY_PCT=10` НЕ менялись.
  2. `risk/daily_limits.py` — docstring `record_trade_closed` зафиксировал единицы.
- **Причина:** Живой баг единиц: NEAR 25.09 +11.01% price-движение записалось как `daily_pnl=+11.01%` и уже на 13:17 триггернуло `daily profit target reached (10.0%)` — дальше 6,450 блокировок за день (в т.ч. 2,046 `daily trades limit` и 599 `consecutive losses` как каскад). Threshold — доля капитала, а записывался % движения цены (не совпадают: при SL 4.6% и risk 1% +11% price = +2.4R = +2.4% капитала).
- **Impact:** Дневной profit-target/drawdown реально отражают капитал; NEAR-сценарий перестанет блокировать весь день. Ранее накопленный `daily_pnl` (in-memory, сбрасывается при рестарте) обнуляется сам.
- **Risk:** Если `signal.sl` отсутствует — fallback ±1R может быть неточен (на практике SL обязателен risk engine'ом). Стало консервативнее: дневной профит достигается медленнее (капитал-метод даёт меньше «плюсов» при сильных price-движениях малорисковых сделок).

## H-018: PAUSED_TIMEFRAMES=1h — пауза 1h таймфрейма

- **Дата:** 2026-10-01
- **Что:**
  1. `config/settings.py` — новый `TradingConfig.paused_timeframes` (env `PAUSED_TIMEFRAMES`, default пусто); добавлен в `build_config_snapshot()`.
  2. `scheduler/scanner.py:run_scan_cycle` и `scheduler/shadow.py:run_shadow_cycle` — фильтр paused TF из списка (явно переданный `timeframes` тоже фильтруется: пауза = пауза).
  3. `.env` — `PAUSED_TIMEFRAMES=1h` (вторичный TF остаётся 4h); `.env.example` — пустой дефолт с комментарием.
- **Причина:** v12-результаты (24–30.09): 4h — 5TP/1SL (хорошо), **1h — 2TP/7SL, −0.49R/сделка**; BUY-v12 в целом 1/7. Недостаточно данных, чтобы решить «1h сломан» или «проскачка», но достаточно, чтобы не копить убытки. Снимается вручную (убрать из env) после ~100 закрытых сделок.
- **Impact:** Скан-цикл 15 мин обходит 1h полностью (снижение нагрузки примерно вдвое); все воронки/аудит по 1h замирают до снятия паузы. 4h продолжает собирать статистику.
- **Risk:** Пропуск 1h-сигналов, которые оказались бы прибыльными; A/B по 1h-параметрам невозможен до снятия. Снятие = удалить `PAUSED_TIMEFRAMES` из `.env` + рестарт.

## H-019: shadow outcome resolver — разрешение теневых outcome в signal_audit_log

- **Дата:** 2026-10-01
- **Что:**
  1. `scheduler/scanner.py` — `_audit_log` получил kwargs `hyp_entry/hyp_sl/hyp_tp/hyp_rr/hyp_ptp/synthetic_plan`; новый хелпер `_hyp_plan()`. Колонки hypothetical_* + `synthetic_plan=1` теперь пишутся на всех blocked-гейтах с полным планом: min_p_tp, risk_engine, entry_trigger, execution_filter, depth_check, correlated_entry, portfolio_risk (TOCTOU), daily_limits (pre-reserve), portfolio_admission. Раньше hyp-данные жили только в строке `meta`, колонки были NULL → `get_unresolved_audits()` их не видел.
  2. Новый `scheduler/audit_resolver.py` — цикл (env `AUDIT_RESOLVER_*`, дефолт 30 мин / batch 300 / max age 14д / expire 7д): группирует unresolved по (symbol, tf), качает OHLCV после `ts_event`, симулирует first-touch SL-приоритетом (как `scripts/virtual_outcomes.py`, входной бар пропускается), пишет `outcome` (HIT_TP/HIT_SL/EXPIRED), `outcome_r`, `mae_r ≤ 0 ≤ mfe_r`, `resolved_at`. Зарегистрирован в `main.py`.
  3. `storage/database.py` — `get_unresolved_audits(limit, max_age_days)` (oldest-first); комментарий колонки `outcome` → HIT_TP/HIT_SL/EXPIRED.
  4. `scripts/backfill_audit_hyp.py` — одноразовый перенос hyp_* из meta в колонки для исторических строк (≤14д, только с direction).
  5. `_CONFIG_VERSION` 12→13.
- **Причина:** Без разрешённых outcome теневые кандидаты нечем сравнивать — A/B по `MIN_P_TP` 30% vs 50% (и любой порог, блокирующий после появления плана) был невозможен: `signal_audit_log.outcome` пуст в 100% строк, `update_audit_outcome` не вызывался ниоткуда.
- **Impact:** Появляется counterfactual-датасет: что было бы с каждым заблокированным кандидатом. Сопоставление «отклонённые vs отправленные» по outcome_r. Нагрузка: ≤1 запроса OHLCV на (symbol,tf) за цикл, батч ограничен.
- **Risk:** Симуляция консервативна (SL-first в пределах бара — реальный порядок внутри бара неизвестен); не учитывает частичные закрытия/BE/trailing (гипотетическая сделка идёт до первого касания SL/TP). EXPIRED после 7 дней без касания. Старше 14 дней не разрешаются.

## H-020: STG/USDT убран из SYMBOLS

- **Дата:** 2026-10-01
- **Что:** `.env` — `SYMBOLS`: удалён `STG/USDT`.
- **Причина:** Каждый scan-цикл падал в WARNING `"STG/USDT not on swap exchange"` (биржа не листингует символ) — мусор в логах и бесполезный скан одного символа каждые 15 минут.
- **Impact:** −1 символ из скана; WARNING исчезает. Динамические символы из БД не затронуты.
- **Risk:** Минимальный (симвел и так не сканировался).

## H-021: positions — метрики закрытия pnl_usdt/pnl_percent/actual_rr/expected_rr

- **Дата:** 2026-10-01
- **Что:**
  1. `storage/position_store.py` — `close_position()` принял опциональные `pnl_usdt/pnl_percent/actual_rr/expected_rr` и пишет их в одноимённые колонки.
  2. `scheduler/outcome_tracker.py` — хелпер `_position_close_metrics()` на всех 4 сайтах закрытия (mgmt-close, HIT_TP, HIT_SL, EXPIRED): `pnl_percent` = net price % (те же единицы, что `signal_outcomes.pnl_pct`), `pnl_usdt` = % × entry × quantity, `actual_rr` = gross R к ОРИГИНАЛЬНОМУ `signal.sl` (не к мутировавшему `positions.stop_loss`), `expected_rr` = |tp−entry|/|entry−sl|.
  3. `scripts/backfill_position_metrics.py` — одноразовый перенос для 15 уже закрытых строк (15/15 джойнят signals+outcomes).
- **Причина:** Колонки существовали, но были NULL во всех 15 закрытых строках — веб/аналитика по позициям не имела ни PnL, ни RR.
- **Impact:** Дашборд и ad-hoc SQL по `positions` получают заполненные метрики; новые закрытия пишутся автоматически.
- **Risk:** `quantity` физически всегда 1.0 (реальный размер не сохраняется) → `pnl_usdt` трактуется как PnL на 1 единицу базы, не на реальный объём. RR к оригинальному SL может отличаться от «мгновенного» RR закрытия по мутировавшему SL — это осознанный выбор (R-лестница считается от первоначального риска).
