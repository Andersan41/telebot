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
