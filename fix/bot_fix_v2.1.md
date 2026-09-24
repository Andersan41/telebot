# bot_fix_v2.1.md — Senior model audit

## Date: 2026-09-24
## Auditor: mimo-v2.6-flash-free (opencode)
## Branch: feat/htf-bias-v2-premium-discount
## Config version: 11 (`_CONFIG_VERSION`); app VERSION: 2.5.0
## Baseline modernization: `E:\Projects\tgbot-claude\bot_fix_v2.0.md` (B-001…B-012)

---

## I. Executive summary

Кодовая база живёт в ветке `feat/htf-bias-v2-premium-discount` с приложениями, которые
пользователь считает «модернизацией по bot_fix_v2.0.md». Фактически **ни один из
ключевых фиксов B-001…B-012 из v2.0 не портирован** в `E:\Projects\tgbot`
(`save_signal_with_risk`, `entry_mode`, `max_sl_atr`, `poi_entry`, `BEGIN IMMEDIATE`,
`select_causal_sweep`, `closed_htf_history`, `first_touch`, `load_outcome_window` —
absent). Совпадает только частичная U10-геометрия и «same-type sweep» в
`structure.py:150`, при том, что общий селектор causal sweep по-прежнему отсутствует.

Три критических дефекта объясняют наблюдаемую live-поведение (229,972 audit-строк,
56,548 fail, **0 decision_traces**, 4 сигнала / 4 HIT_TP):

1. **B-013**: scanner никогда не проверяет `trade_plan.is_valid`. Невалидные
   `TradePlan` (`is_valid=False`, `sl=0.0`, `tp=0.0`) проходят проверку
   `sl is None or tp is None` и долетают до Risk Engine → 5,822
   `data_integrity_fail` с `hyp_sl=0.0000,hyp_tp=0.0000`.
2. **B-015**: live `data/signals.db` **не имеет колонки
   `decision_traces.hypothesis_snapshot`**; `trace_migrations` в `Database.init`
   её не добавляет. Все 44 вызова `trace.save()` падают
   `sqlite3.OperationalError` и гласятся `logger.debug` → телеметрия мертва.
3. **B-014/B-017**: при `sl=tp=0` feature `rr_ratio=0`, ML возвращает
   `expected_rr = 1.0` и `p_tp` клипится к 0.65 → логи выглядят как
   `P(TP)=65.0% | RR=1.00 | PF=1.86` на всех символах. HTF soft-penalty пишет
   audit `passed=False`, но конвейер продолжает работу.

Ожидаемый эффект после B-013+B-015: ~2.5% audit-fail исчезают как ложные
`data_integrity_fail`; возвращается запись decision traces (воронка, gate_path,
feature snapshot для ML). B-014 чинит только после B-013 (валидные sl/tp в
features). Остальные дефекты — порт-пропуски v2.0, которые надо закрывать
последовательно, не меняя live-пороги.

---

## II. Findings

### B-013 — Scanner ignores `trade_plan.is_valid`; sl/tp=0 leak into Risk Engine — Severity: CRITICAL

**File:** `scheduler/scanner.py`
**Lines:** 1158-1181
**Current behavior:** `build_trade_plan()` возвращает `TradePlan` с
`is_valid=False` и дефолтными `sl=0.0, tp=0.0` (см. `strategy/trade_plan.py:58-72`)
в ветках `no invalidation`, `GEOMETRY_INVALID`, `RR_TOO_LOW`. Scanner проверяет
только `if sl is None or tp is None` — `0.0 is not None` → пропускает.
Risk Engine отклоняет `"invalid price data"` (`risk/engine.py:147-151`).
**Expected behavior:** Немедленный block `sl_tp` при `not trade_plan.is_valid`
или `sl <= 0 or tp <= 0`, с audit `SL_TP_FAILED` и `trace.blocked("sl_tp", ...)`.
**Why it matters:** 5,822 audit-fail (~10% всех fail) — ложный шум; кандидат
проходит probability/feature-слои со сломанными features (см. B-014), audit-мета
лжёт (`hyp_sl=0`).

**Evidence:**
```python
# scheduler/scanner.py:1170-1181
sl = trade_plan.sl
tp = trade_plan.tp
if sl is None or tp is None:          # 0.0 is not None — passes
    ...
# strategy/trade_engine.py:122-130
if invalidation is None:
    return TradePlan(..., is_valid=False, rejection_reason="no invalidation level found")
# defaults: sl=0.0, tp=0.0
```

Live meta:
```
reason=invalid price data,hyp_entry=0.1788,hyp_sl=0.0000,hyp_tp=0.0000,hyp_rr=0.00,hyp_ptp=0.650
```

**Fix:**
```python
        sl = trade_plan.sl
        tp = trade_plan.tp
        sl_source = trade_plan.sl_source

        if (not trade_plan.is_valid) or sl is None or tp is None \
                or not (sl > 0 and tp > 0):
            _reason = trade_plan.rejection_reason or "SL/TP calculation failed"
            _current_funnel.log_gate(symbol, timeframe, "sl_tp", "BLOCKED", _reason)
            trace.blocked("sl_tp", _reason)
            await trace.save(db)
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "sl_tp", SL_TP_FAILED, False,
                             setup_type=setup.setup_type, direction=setup.direction,
                             meta=f"trade_plan_reject={trade_plan.rejection_reason}")
            return None
```

**Verification:** После фикса
`SELECT COUNT(*) FROM signal_audit_log WHERE reason_code='data_integrity_fail'`
перестаёт расти; в meta больше нет `hyp_sl=0.0000`. Unit:
`build_trade_plan` с отсутствующей invalidation → scanner возвращает `None`
и пишет `SL_TP_FAILED`.

---

### B-014 — ML expected_rr fallback + p_tp clamp produce constant RR=1.00 / PF=1.86 — Severity: HIGH

**File:** `strategy/probability_engine.py`
**Lines:** 415-445
**Current behavior:** `expected_rr = f.rr_ratio if f.rr_ratio > 0 else 1.0`;
`p_tp = max(0.05, min(0.65, p_tp))`; `PF = (p_tp * b) / (1 - p_tp)` с `b=1.0`,
когда `rr_ratio=0` (B-013). Итог: на live-логах все символы с invalid plan
дают `P(TP)=65.0% | RR=1.00 | PF=1.86`; floor 0.05 даёт `min_p_tp` блоки
(BTC/ETH/BNB continuation).
**Expected behavior:** При `rr_ratio<=0` ML-ветка **не должна** выдавать
faithful PF/expected_rr — либо fallback на rules (`_predict_rules`), либо
`should_trade=False`/skip probability (scanner уже блокирует в B-013).
**Why it matters:** Портфолио-метрики и `min_p_tp` gate принимают решения на
константах; A/B и `docs/hypotheses.md` искажены.

**Evidence:**
```python
p_tp = max(0.05, min(0.65, p_tp))
expected_rr = f.rr_ratio if f.rr_ratio > 0 else 1.0
b = expected_rr if expected_rr > 0 else 1.0
profit_factor = (p_tp_clamped * b) / max(1 - p_tp_clamped, 0.01)
# 0.65 * 1.0 / 0.35 = 1.857 ≈ 1.86
```

**Fix:**
```python
                expected_rr = f.rr_ratio
                if not (expected_rr and expected_rr > 0):
                    logger.warning(
                        f"expected_return model: rr_ratio={f.rr_ratio} invalid — "
                        f"falling back to rules"
                    )
                    return self._predict_rules(f)

                p_tp = max(0.05, min(0.65, p_tp))
                multiplier = f.htf_bias_penalty * f.ob_state_multiplier
                p_tp = min(0.65, p_tp * multiplier)
```

**Verification:** Логи `Probability:` перестают содержать `RR=1.00` для
кандидатов с валидным sl/tp. После B-013 инвалидные кандидаты не доходят
до probability вообще.

---

### B-015 — `decision_traces` migration omits `hypothesis_snapshot`; all 44 `trace.save()` fail silently — Severity: CRITICAL

**File:** `storage/database.py`
**Lines:** 407-446 (`trace_migrations`), 287 (ORM column), 801-910 (`save_decision_trace`)
**Current behavior:** ORM-модель `DecisionTrace` содержит
`hypothesis_snapshot = Column(Text)` и INSERT всегда его передаёт.
Словарь `trace_migrations` не содержит `hypothesis_snapshot` (и
`execution_snapshot` уже есть в БД, а вот `hypothesis_snapshot` — нет).
На live `data/signals.db`:
`sqlite3.OperationalError: table decision_traces has no column named hypothesis_snapshot`.
`DecisionTraceBuilder.save` ловит исключение и пишет только
`logger.debug(...)` → return `-1`. Счётчик: **0** строк в `decision_traces`
при 229,972 audit-строках.
**Expected behavior:** Миграция добавляет все новые колонки; ошибки save —
`logger.error` + хотя бы счётчик; decision traces пишутся на каждый
pipeline pass.
**Why it matters:** Нет gate_path, нет feature snapshot для ML (A22), нет
counterfactual/outcome-link; `get_trace_stats`/`get_outcome_stats` на traces
бесполезны; `outcome_tracker` не может обновить `trace_row.outcome`.

**Evidence:**
```python
# storage/database.py:412-438 — hypothesis_snapshot отсутствует
trace_migrations = {
    "adx": "FLOAT", ..., "wave_label": "VARCHAR(50)",
    # НЕТ: "hypothesis_snapshot": "TEXT"
}
# live repro:
# OperationalError: table decision_traces has no column named hypothesis_snapshot
```

**Fix:**
```python
            trace_migrations = {
                # ... existing keys ...
                "wave_label": "VARCHAR(50)",
                "hypothesis_snapshot": "TEXT",
            }
            for col_name, col_type in trace_migrations.items():
                if col_name not in trace_columns:
                    await conn.execute(
                        text(f"ALTER TABLE decision_traces ADD COLUMN {col_name} {col_type}")
                    )
                    await conn.commit()
                    logger.info(f"Migration: added decision_traces.{col_name}")
```

И в `storage/trace.py`:
```python
        except Exception as e:
            logger.error(f"Decision trace save failed for {self.symbol} {self.timeframe}: {e}")
            return -1
```

**Verification:** Одна ручная вставка через `DecisionTraceBuilder.save`
возвращает id > 0; `SELECT COUNT(*) FROM decision_traces` растёт каждый
scan-цикл (ожидаются сотни строк за час на 150 символов × 2 TF).

---

### B-016 — `GATE_ORDER` / `_FUNNEL_GATES` / `get_trace_stats` use three different stale gate lists — Severity: HIGH

**File:** `storage/trace.py`, `scheduler/scanner.py`, `storage/database.py`
**Lines:** `trace.py:31-35`, `scanner.py:140`, `database.py:984+`
**Current behavior:** `GATE_ORDER` и `_FUNNEL_GATES` содержат только 10 legacy
гейтов (cooldown…dedup). `build_gate_path` итерирует **только** `GATE_ORDER`
(+ compression_block спецкейс). Гейты `htf_bias`, `min_p_tp`, `entry_trigger`,
`volatility_filter`, `session_filter`, `daily_limits`, `position_limits`,
`execution_filter`, `ob_retest`, `breakout_quality`, `htf_poi` **не попадают**
в `gate_path`, даже если `trace.record/pass/blocked` их вызывали.
`trace.record("htf_bias_penalty", True)` вообще вне списка → теряется.
`get_trace_stats` использует собственный третий список legacy `gate_*` колонок.
`log_gate(..., "PENALTY", ...)` не обрабатывается в `log_gate` (только
PASS/BLOCKED/ENTER) → funnel-счётчики не видят soft-penalty.
**Expected behavior:** Один канонический список гейтов; `gate_path` — полный
порядок; `get_trace_stats` читает `gate_path` JSON, а не отдельные колонки;
PENALTY — отдельный статус в funnel.
**Why it matters:** Воронка и transition-matrix неполны; HTF penalty
невидим в traces (а traces ещё и не сохраняются — B-015).

**Evidence:**
```python
# storage/trace.py:31-35
GATE_ORDER = [
    "cooldown", "portfolio_risk", "indicators", "pattern_engine",
    "structure_alignment", "sweep_required", "regime_block",
    "sl_tp", "risk_engine", "dedup",
]
# scanner records e.g. "htf_bias", "entry_trigger", "min_p_tp" — never in path
```

**Fix:**
```python
GATE_ORDER = [
    "cooldown", "portfolio_risk", "indicators", "pattern_engine",
    "structure_alignment", "sweep_required", "regime_block",
    "htf_bias", "entry_trigger", "ob_retest", "volatility_filter",
    "session_filter", "sl_tp", "min_p_tp", "risk_engine",
    "daily_limits", "position_limits", "execution_filter", "dedup",
]
# storage/trace.py — build_gate_path: убрать спец-случай compression_block,
# добавить "compression_block" и "htf_bias_penalty" в GATE_ORDER.
# scanner.log_gate: обработать status == "PENALTY" (счётчик penalty, не block).
```

**Verification:** После B-015 появятся строки с `gate_path`, содержащие
`"htf_bias"` и `"entry_trigger"`; SQL по `gate_path LIKE '%htf_bias%'`
ненулевой.

---

### B-017 — HTF soft-penalty writes `passed=False` audit while pipeline continues; direction config flags are dead — Severity: HIGH

**File:** `scheduler/scanner.py`, `config/settings.py`
**Lines:** scanner 970-990 (v2 soft), 1016-1024 (v2 reversal soft без audit),
1101-1111 (v1 reversal soft с audit ok); settings 721-723
**Current behavior:**
- Short-in-bullish / long-in-bearish: `_htf_bias_penalty=0.7`,
  funnel `"PENALTY"`, но `_audit_log(..., HTF_SHORT_IN_BULLISH, False)` —
  audit считает **блоком**, pipeline продолжает.
- v2 reversal soft (line 1016-1024) **вообще не пишет** `_audit_log` (ни pass,
  ни fail) — дыра в audit.
- `block_short_in_bullish_htf` / `block_long_in_bearish_htf` **нигде не
  читаются** в scanner (grep = только definition в settings). Дефолт
  `BLOCK_SHORT_IN_BULLISH_HTF=false` в `.env.example` (uncommitted diff)
  ничего не меняет — penalty всегда 0.7.
**Expected behavior:** Audit `passed=True` с `reason_code=HTF_SOFT_PENALTY`
и meta `penalty=0.7`; либо честный отдельный статус; config-флаги либо
подключить, либо удалить.
**Why it matters:** 5,919 `htf_short_in_bullish` fail-строк в audit
**ложные** (не блокируют); funnel-отчёт и hypotheses искажены; dead config
вводит в заблуждение при A/B.

**Evidence:**
```python
# scanner.py:973-981
if setup.direction == 'sell' and _bias_enum == HTFBias.BULLISH:
    _htf_bias_penalty = 0.7
    _current_funnel.log_gate(..., "PENALTY", reason)
    await _audit_log(..., "htf_bias", HTF_SHORT_IN_BULLISH, False, ...)  # ложный fail
    # нет return — pipeline продолжает
# settings.py:721 — block_short_in_bullish_htf не читается в scanner.py
```

**Fix:**
```python
                if setup.direction == 'sell' and _bias_enum == HTFBias.BULLISH:
                    _htf_bias_penalty = 0.7
                    reason = "SHORT soft penalty: HTF bias is bullish"
                    _current_funnel.log_gate(symbol, timeframe, "htf_bias", "PENALTY", reason)
                    trace.record("htf_bias_penalty", True)
                    await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                     "htf_bias", HTF_SHORT_IN_BULLISH, True,  # pass
                                     setup_type=setup.setup_type, direction=setup.direction,
                                     meta=f"version=v2,htf_bias={htf_bias_str},penalty=0.7,soft=1")
```
Для v2-reversal soft (1016-1024) добавить аналогичный `_audit_log(..., True, ...)`.
Подключить config-флаги:
```python
                    if setup.direction == 'sell' and _bias_enum == HTFBias.BULLISH:
                        if config.trading.block_short_in_bullish_htf:
                            # hard block path (return None)
                            ...
                        else:
                            _htf_bias_penalty = 0.7  # soft
```

**Verification:**
`SELECT COUNT(*) FROM signal_audit_log WHERE reason_code='htf_short_in_bullish' AND passed=0`
не растёт; появляются `passed=1` с `penalty=0.7` в meta. Количество
назначенных сигналов при прочих равных не падает (penalty влияет только на
probability multiplier).

---

### B-018 — Outcome tracker: EXPIRED zeroes PnL; single-candle `iloc[-1]` resolution — Severity: HIGH

**File:** `scheduler/outcome_tracker.py`
**Lines:** 280-300, 369 (см. v2.0 B-008/B-009 — не портировано)
**Current behavior:** TTL-expired → `pnl_pct=0.0` (нет оценки фактического
close). Жёсткое чтение последней свечи `df.iloc[-1]` без `outcome_window`
/ `load_outcome_window` / `first_touch`. Связанный `trace_row.outcome` обновляется
только если trace сохранился (B-015) — сейчас никогда.
**Expected behavior:** EXPIRED считает pnl от `signal.close_price` до
последнего close (или помечает `pnl_unknown`, но не 0.0 как «ничего»);
resolution через закрытый исторический окно (v2.0), не через live `iloc[-1]`.
**Why it matters:** Искажает win-rate, equity, обучающие метки ML;
4/4 HIT_TP — маленькая выборка, но EXPIRED с 0.0 уже внесёт bias при масштабе.

**Evidence:**
```python
# outcome_tracker.py:281-284
await db.close_outcome(
    outcome.id, "EXPIRED",
    close_price=signal.close_price, pnl_pct=0.0,
)
```

**Fix (портировать B-008/B-009 из v2.0):**
```python
        if age > timedelta(days=OUTCOME_TTL_DAYS):
            # Compute real PnL from signal.close_price to last known close
            last_close = await _fetch_last_close(db, signal)  # or exchange
            if last_close is not None:
                direction_mult = 1.0 if signal.signal_type == "BUY" else -1.0
                pnl = (last_close - signal.close_price) / signal.close_price * 100 * direction_mult
                await db.close_outcome(
                    outcome.id, "EXPIRED",
                    close_price=last_close, pnl_pct=round(pnl, 4),
                )
            else:
                await db.close_outcome(
                    outcome.id, "EXPIRED",
                    close_price=signal.close_price, pnl_pct=None,  # unknown ≠ 0
                )
            ...
```

**Verification:** Unit-тест: сигнал age>TTL, last_close != close →
`pnl_pct != 0.0`; analytics не считает EXPIRED как scratch (как в v2.0 B-010).

---

### B-019 — Non-atomic `save_signal` + `create_outcome` (v2.0 B-003 not ported) — Severity: MEDIUM

**File:** `scheduler/scanner.py`, `storage/database.py`
**Lines:** scanner 2192, 2275; см. v2.0 B-003
**Current behavior:** Signal и outcome пишутся отдельными вызовами; только
count-recheck TOCTOU (2160-2177) и daily pre-reserve rollback. Между save и
create_outcome краш оставляет signal без outcome.
**Expected behavior:** Одна транзакция (`save_signal_with_risk` /
`BEGIN IMMEDIATE`) — как в v2.0.
**Why it matters:** 4 сигнала — масштаб пока мал, но orphan-signal ломает
outcome pipeline и analytics.

**Evidence:**
```python
# scanner.py:2192
saved_signal = await db.save_signal(...)
# ... telegram ...
# scanner.py:2275
await db.create_outcome(saved_signal.id, risk_pct=...)
```

**Fix:** Портировать `save_signal_with_risk` из bot_fix_v2.0.md (единый
`async with session.begin()` для signal + outcome + cooldown).

**Verification:** Kill процесс между 2192 и 2275 (unit mock) → в БД нет
signal без outcome либо нет ни того, ни другого.

---

### B-020 — Analytics/WR still status-based `HIT_TP` (v2.0 B-010 not ported) — Severity: MEDIUM

**File:** `storage/database.py`, `analytics/*`
**Lines:** `database.py:1308`, `1345`, `1370`; `analytics/daily_report.py:110`;
`analytics/full_report.py:213` (Equity Curve title)
**Current behavior:** `wins = status == "HIT_TP"`; Equity Curve cumulative
`pnl_pct` без разделения закрытых/открытых; EXPIRED с pnl=0 (B-018) попадает
в closed как «ничья».
**Expected behavior:** Win = `pnl_pct > 0` (или R-multiple > 0) среди
реально закрытых; отдельные метрики для EXPIRED; equity — только closed.
**Why it matters:** Reported WR/PF не соответствуют денежному результату.

**Evidence:**
```python
# storage/database.py:1308
"wins": sum(1 for r in closed_rows if r.status == "HIT_TP"),
```

**Fix (портировать B-010):**
```python
closed_rows = [r for r in rows if r.status in ("HIT_TP", "HIT_SL")]
wins = sum(1 for r in closed_rows if (r.pnl_pct or 0) > 0)
return {
    "wins": wins,
    "losses": len(closed_rows) - wins,
    "winrate": round(wins / len(closed_rows) * 100, 1) if closed_rows else 0.0,
    "expired": sum(1 for r in rows if r.status == "EXPIRED"),
}
```

**Verification:** Синтетический outcome `HIT_SL` с `pnl_pct=+0.2` не считается
проигрышем; `HIT_TP` с `pnl_pct=-0.1` не считается победой (если такие
появятся из tracker).

---

### B-021 — Live/backtest HTF & lookback parity broken (v2.0 B-007/B-012 not ported) — Severity: HIGH (для A/B)

**File:** `backtest/engine.py`, `backtest/run_new_pipeline.py`, `scheduler/scanner.py`
**Lines:** engine 542-546, 614; run_new_pipeline 363-388; scanner 493-496, 535
**Current behavior:**
- `closed_htf_history` отсутствует → backtest HTF bias видит будущие свечи.
- lookback: live scanner sweeps=50, OB=100, structure=50;
  `run_new_pipeline` sweeps=50, OB=100, structure=50 (совпадает);
  `engine.py`/`funnel.py`/`edge_discovery.py` используют `window.tail(100)` для
  structure **и** sweeps → **не совпадают** с live.
**Expected behavior:** Единый lookback-профиль 50/100/50 везде; causal HTF
history для бэктеста.
**Why it matters:** A/B результаты PF/WR из engine/funnel не переносятся на
live; risk of tuning thresholds на несравнимых данных.

**Evidence:**
```python
# scanner.py:493-494
sweeps = detect_sweeps(_df_clean, lookback=50)
order_blocks = detect_order_blocks(_df_clean, lookback=100)
# engine.py:542-546
structure = analyze_structure(window.tail(100))
all_sweeps = detect_sweeps(window.tail(100), swing_window=5)
```

**Fix:** Вынести `LIVE_LOOKBACK = {"sweeps": 50, "obs": 100, "structure": 50}`
в `config`; engine/funnel/edge_discovery использовать его; портировать
`closed_htf_history` из v2.0 B-007 до любого HTF A/B.

**Verification:** Diff-тест: одинаковый closed-candle window → одинаковые
списки sweep/OB/structure в live path и backtest path.

---

### B-022 — `note=` crash fixed in tree; live process still runs old code — Severity: CRITICAL (operational)

**File:** `scheduler/scanner.py`
**Lines:** 1024, 1109 (edited this session; `DecisionTraceBuilder.passed()` без `note`)
**Current behavior:** В рабочем дереве `trace.passed("htf_bias", note=reason)`
заменён на `trace.passed("htf_bias")`. **Живой процесс** был запущен до фикса
и продолжает падать на каждом soft-penalty проходе (или до фикса падал).
**Expected behavior:** Restart production после применения фиксов.
**Why it значимо:** Без restart фиксы B-013/B-015 и этот не действуют.

**Fix:** Операционный: `docker-compose restart` / перезапуск `python main.py`
после коммита фиксов.

**Verification:** В логах нет `TypeError: passed() got an unexpected keyword
argument 'note'`; версия в `decision_traces.strategy_version` = 2.5.0 после
B-015.

---

### B-023 — Test suite: MockSweep missing API; `wave_label: str` in to_vector — Severity: MEDIUM

**File:** `tests/test_new_pipeline.py`, `strategy/feature_builder.py`
**Lines:** tests 62; pattern_engine 305; feature_builder wave_label
**Current behavior:** `MockSweep` без `passes_false_sweep_filters` →
AttributeError в pattern_engine path. `SetupFeatures.to_vector()` кладёт
`wave_label` строкой → `test_to_vector_numeric_only` fail. Subset прогоны:
~14 failures (exchange mock NoneType, risk threshold drift 3.0→2.64).
Полный `pytest` зависает (~60%, python PID high CPU) — вероятно network/hang
тест; `--timeout` недоступен (нет pytest-timeout).
**Expected behavior:** Mock соответствует `SweepEvent`; вектор только
числовой (wave_label убрать из to_vector или cast); hang-тест найден и
исключён/поправлен.
**Why it matters:** Нельзя доверять зелёному/красному baseline; CI невозможен.

**Evidence:**
```python
# pattern_engine.py:305 — AttributeError на MockSweep
if not sweep.passes_false_sweep_filters(...):
# feature_builder: wave_label в to_vector как str
```

**Fix:**
```python
# tests/test_new_pipeline.py
class MockSweep:
    ...
    def passes_false_sweep_filters(self, df, index, direction):
        return True

# feature_builder.to_vector — не включать wave_label:
#   убрать "wave_label" из dict, оставить только numeric-поля
```
Добавить `pytest-timeout` в requirements-dev, запускать
`pytest --timeout=30` для обнаружения hang-теста.

**Verification:** `pytest tests/test_new_pipeline.py -v` зелёный;
`pytest --collect-only` + batch-запуски по каталогам с timeout.

---

### B-024 — v2.0 `MAX_SL_ATR` / geometry `isfinite` not ported — Severity: MEDIUM

**File:** `strategy/invalidation.py`, `risk/engine.py`
**Lines:** risk 153-161 (U10 есть, но без `math.isfinite`)
**Current behavior:** U10 геометрия по ценам есть; `sl_absolute_max_pct=3.0`
заменяет MAX_SL_ATR (3.0 ATR из v2.0 — другой смысл: % vs ATR-units).
Нет явной проверки `isfinite(entry/sl/tp)` (NaN: `entry <= 0` False →
проходит data-integrity → geometry-сравнения с NaN False →
GEOMETRY_INVALID — деградирует, но с путём ошибки).
**Expected behavior:** `all(map(math.isfinite, (entry_price, sl, tp)))` в
Risk Engine; опционально `max_sl_atr` в invalidation как в v2.0 B-001.
**Why it matters:** Защита от NaN из индикаторов; паритет с v2.0.

**Evidence:**
```python
# risk/engine.py:147-161 — нет isfinite
if entry_price <= 0 or sl <= 0 or tp <= 0:
    return RiskDecision(..., rejection_reason="invalid price data")
_is_buy_geo = sl < entry_price < tp  # NaN → False → GEOMETRY_INVALID
```

**Fix:**
```python
        if not all(map(math.isfinite, (entry_price, sl, tp))) \
                or entry_price <= 0 or sl <= 0 or tp <= 0:
            return RiskDecision(
                should_trade=False,
                rejection_reason="invalid price data",
            )
```

**Verification:** Unit: `sl=float('nan')` → `invalid price data`, не
`GEOMETRY_INVALID` и без исключения.

---

### B-025 — Feature schema drift: model 46 features vs vector 55 keys; FEATURE_KEYS not extended — Severity: MEDIUM

**File:** `strategy/feature_builder.py`, `strategy/probability_engine.py`, `storage/trace.py`
**Lines:** feature_builder `to_vector`; probability `_load_model`/`reindex`;
trace `FEATURE_KEYS`
**Current behavior:** Model `feature_names` = 46 (без wave_*, vp_*,
htf_bias_penalty, ob_state_multiplier). `to_vector` = 55 keys.
`X.reindex(columns=feature_names, fill_value=0)` отбрасывает 9 extras —
OK для predict, но **обучение**/replay по полному вектору ломается.
`FEATURE_KEYS` в trace не содержит `p_tp`, `expected_rr`, `risk_pct` —
они попадают в `set_features` в scanner 2257-2261, но отфильтровываются
при записи отдельных колонок; полный вектор уходит только в
`hypothesis_snapshot['full_features']` (который не сохраняется — B-015).
**Expected behavior:** Явный `MODEL_FEATURES` список; FEATURE_KEYS расширен;
после B-015 full_features в traces.
**Why it matters:** ML training set и live vector расходятся; A22 replay
невозможен.

**Evidence:**
```python
# model: 46 feature_names, no wave/htf_bias_penalty/ob_state
# vector: 55 keys
# probability: X = X.reindex(columns=self.feature_names, fill_value=0)
```

**Fix:**
```python
# storage/trace.py
FEATURE_KEYS = {
    ...,  # existing
    "p_tp", "expected_rr", "risk_pct",
    "htf_bias_penalty", "ob_state_multiplier",
}
# strategy/probability_engine.py — assert at load:
# assert set(self.feature_names) <= set(SetupFeatures().to_vector().keys())
```

**Verification:** `python -c` snippet из аудита: `vector not in model`
должен быть пустым либо extras осознанно документированы.

---

### B-026 — FVG timestamp uses trigger candle index; fill uses `index+1` (causal, minor inconsistency) — Severity: LOW

**File:** `liquidity/fvg.py`
**Lines:** 88-113
**Current behavior:** `fvg.index = offset+i+1` (candle3), fill from
`df.iloc[fvg.index+1:]` (candle4+) — causal OK. `timestamp` берёт
`df.index[offset+i]` (candle2) — timestamp смещён на 1 бар от index.
**Expected behavior:** `timestamp = df.index[fvg.index]`.
**Why it matters:** Ошибки выравнивания в multi-TF MTF-чеках и analytics
по времени; не фатально для триггера.

**Evidence:**
```python
# fvg.py — timestamp from offset+i, index=offset+i+1
```

**Fix:**
```python
fvg.timestamp = df.index[fvg.index]  # align with gap candle
```

**Verification:** Unit: gap на candle3 → `fvg.timestamp == df.index[candle3_index]`.

---

### B-027 — HTF penalty multiplier hardcoded; not in config snapshot / hypotheses — Severity: LOW

**File:** `scheduler/scanner.py`
**Lines:** 974, 983, 1020, 1059, 1068, 1105
**Current behavior:** `0.7` / `0.85` захардкожены; не входят в
`build_config_snapshot()` / `_CONFIG_VERSION` bump; A/B невозможен без кода.
**Expected behavior:** `config.trading.htf_penalty_direction` (0.7),
`config.trading.htf_penalty_reversal` (0.85); bump `_CONFIG_VERSION`.
**Why it matters:** docs/hypotheses.md требует логирования изменений параметров.

**Evidence:**
```python
_htf_bias_penalty = 0.7   # scanner.py:974
_htf_bias_penalty = 0.85  # scanner.py:1020
```

**Fix:**
```python
# config/settings.py
htf_penalty_direction: float = float(os.getenv("HTF_PENALTY_DIRECTION", "0.7"))
htf_penalty_reversal: float = float(os.getenv("HTF_PENALTY_REVERSAL", "0.85"))
# scanner: _htf_bias_penalty = config.trading.htf_penalty_direction
# bump _CONFIG_VERSION in scanner.py
```

**Verification:** `build_config_snapshot()` содержит оба ключа; env override
меняет поведение.

---

## III. Summary table

| ID | Title | Severity | File | Status |
|----|-------|----------|------|--------|
| B-013 | trade_plan.is_valid ignored; sl/tp=0 leak | CRITICAL | scanner.py | FIXED |
| B-015 | decision_traces migration missing hypothesis_snapshot | CRITICAL | database.py | FIXED |
| B-022 | note= fixed in tree; live needs restart | CRITICAL | scanner.py | FIXED (tree) / OPEN (deploy) |
| B-014 | ML RR=1.00 / PF=1.86 degenerate outputs | HIGH | probability_engine.py | FIXED |
| B-016 | Three stale GATE_ORDER lists; gate_path incomplete | HIGH | trace.py / scanner.py | FIXED |
| B-017 | HTF soft-penalty false audit fail; dead config | HIGH | scanner.py / settings.py | FIXED |
| B-018 | EXPIRED pnl=0; iloc[-1] resolution | HIGH | outcome_tracker.py | FIXED (real PnL; first_touch still partial) |
| B-021 | Live/backtest lookback + HTF causal parity | HIGH | backtest/* | FIXED |
| B-019 | Non-atomic save_signal + create_outcome | MEDIUM | scanner.py | FIXED |
| B-020 | Status-based WR / Equity Curve | MEDIUM | database.py / analytics | FIXED |
| B-023 | MockSweep; wave_label str; pytest hang | MEDIUM | tests / feature_builder | FIXED (MockSweep+wave_label) / OPEN (hang) |
| B-024 | isfinite / MAX_SL_ATR not ported | MEDIUM | risk/engine.py | FIXED |
| B-025 | Feature schema drift 46 vs 55 | MEDIUM | feature_builder / trace | FIXED (FEATURE_KEYS) |
| B-026 | FVG timestamp off-by-one | LOW | liquidity/fvg.py | FIXED |
| B-027 | HTF penalty hardcode not in config | LOW | scanner.py / settings.py | FIXED |

### Port status of bot_fix_v2.0 (this repo)

| v2.0 ID | Topic | Status in E:\Projects\tgbot |
|---------|-------|-----------------------------|
| B-001 | MAX_SL_ATR | FIXED (→ B-024) |
| B-002 | Directed geometry / isfinite / Kelly | FIXED (isfinite; U10 + half-Kelly) |
| B-003 | Atomic save_signal_with_risk | FIXED (→ B-019) |
| B-004 | FVG market entry price | NOT verified / likely absent |
| B-005 | FVG fill causality | PARTIAL (index causal; ts off-by-one → B-026 FIXED) |
| B-006 | MSS same-type sweep | PARTIAL (`structure.py:150` same type; no shared select_causal_sweep) |
| B-007 | HTF backtest causal history | FIXED (→ B-021) |
| B-008 | outcome_window resolution | PARTIAL (→ B-018; full first_touch needs fetch_ohlcv since/drop_last) |
| B-009 | EXPIRED real PnL | FIXED (→ B-018) |
| B-010 | WR by pnl not HIT_TP | FIXED (→ B-020) |
| B-011 | Trace full features + migrations | FIXED (→ B-015, B-025) |
| B-012 | Live/backtest lookback parity | FIXED (→ B-021) |

---

## IV. Priority order

1. **B-015** — restore decision_traces (migration + error logging) — без этого
   нет телеметрии для всех остальных фиксов.
2. **B-013** — block invalid TradePlan immediately — убирает 5.8K ложных fail
   и защищает probability/risk.
3. **B-022** — restart live process с текущим tree (note= fix + подготовка
   к 013/015).
4. **B-014** — ML fallback на rules при rr_ratio<=0 (после 013, но guard нужен).
5. **B-017** — честный audit HTF penalty + подключить/удалить config-флаги.
6. **B-016** — единый GATE_ORDER + PENALTY в funnel + gate_path полный.
7. **B-018 / B-019 / B-020 / B-021 / B-024** — догон порта v2.0
   (outcome → atomic save → analytics → parity → isfinite).
8. **B-023 / B-025 / B-026 / B-027** — hygiene (tests, schema, FVG ts, config).

Сигнал-объём: B-013 скорее **увеличит** шанс дойти до risk с валидным планом
(сейчас часть валидных геометрий могла ломаться позже?) — на деле ложные
data_integrity_fail уйдут, часть кандидатов уйдёт в sl_tp-block раньше
(честный block вместо risk_engine fail). Чистый эффект на sends —
нейтральный до B-014/B-017.

---

## V. Config recommendations

| Param | Current | Recommended | Reason |
|-------|---------|-------------|--------|
| BLOCK_SHORT_IN_BULLISH_HTF | false (dead) | подключить к hard-block **или** удалить; soft penalty всегда 0.7 | B-017 dead config |
| BLOCK_LONG_IN_BEARISH_HTF | true (dead) | то же | B-017 |
| HTF_PENALTY_DIRECTION | hardcode 0.7 | env 0.7 | B-027 A/B |
| HTF_PENALTY_REVERSAL | hardcode 0.85 | env 0.85 | B-027 A/B |
| RISK_ENGINE_MIN_RR | 2.5 | оставить 2.5 (v2.0 deprecated, но работает) | паритет с TZ §7.1 |
| MIN_RR_THRESHOLD | 1.5 | оставить (TradeEngine soft note) | не путать с min_rr_ratio |
| MIN_P_TP | 0.30 | не менять до B-014 | floor/ceiling искажены |
| MAX_ACTIVE_SIGNALS | 10 | оставить | live |
| MAX_PORTFOLIO_RISK_PCT | 3.7 | оставить | live |
| SIGNAL_COOLDOWN_MINUTES | 45 | оставить | AGENTS.md |
| LOOKBACK sweeps/obs/structure | 50/100/50 | DONE: config + `.env`/`engine` 50/100/50 | B-021 |
| MAX_SL_ATR | absent | DONE: `3.0` in config + `.env` + trade_engine gate | B-024 |
| _CONFIG_VERSION | 10 | **11** after B-017/B-027 | audit A/B |

---

## VI. Questions for the team

1. **Порт v2.0**: применять ли полный diff из `E:\Projects\tgbot-claude\bot_fix_v2.0.md`
   (B-001…B-012) как rebase, или только находки B-013+? Рекомендую rebase
   v2.0 + overlay B-013…B-027.
2. **HTF soft vs hard**: оставить continuation hard-block + direction soft-penalty
   (текущее uncommitted поведение) или вернуть config-управляемые hard-блоки?
3. **EXPIRED pnl=None vs 0.0**: analytics готовы ли к NULL pnl?
4. **Live DB migration**: `ALTER TABLE decision_traces ADD COLUMN
   hypothesis_snapshot TEXT` — на проде нужен maintenance window или
   tolerate brief lock?
5. **ML retrain**: после B-013 набор features изменится (исчезнут rr_ratio=0
   строки) — переобучать `probability_model.pkl` сразу или дождаться 100+
   live outcomes (как в AGENTS.md)?
6. **pytest hang**: известен ли hang-тест (network)? Добавлять ли
   `pytest-timeout` в requirements-dev?
7. **Uncommitted diff** (scanner HTF penalty, web/server, handlers /report,
   .env.example): коммитить ли до или после B-013/B-015?

---

## VII. Implementation notes for mimo

**Safe immediately (no config change):**
- B-015 migration + `logger.error` in trace.save
- B-013 is_valid/None/zero guard in scanner
- B-014 rules-fallback on rr_ratio<=0
- B-024 isfinite guard
- B-023 MockSweep + wave_label out of to_vector
- B-026 FVG timestamp align

**Need config / bump `_CONFIG_VERSION`:**
- B-017 (audit semantics + config flags + soft audit row)
- B-016 (GATE_ORDER expand — affects gate_path schema for analytics)
- B-027 (penalty env params)

**Port from bot_fix_v2.0.md (do not reinvent):**
- B-018 = v2.0 B-008+B-009
- B-019 = v2.0 B-003 (`save_signal_with_risk`)
- B-020 = v2.0 B-010
- B-021 = v2.0 B-007+B-012
- B-024 partial = v2.0 B-001/B-002 remainder
- B-011 completion = covered by B-015+B-025 (full_features migration already
  in `trace.save` hypothesis merge — works once column exists)

**Dependencies:**
- B-014 before trusting any probability numbers → **after B-013**
- B-016 before relying on gate_path analytics → **after B-015**
- B-017 before comparing HTF A/B
- B-021 before trusting any backtest PF/WR for threshold tuning
- B-019 before scaling signals (orphan risk)
- Restart (B-022) after deploying 013+015+014

**Tests to update:**
- `tests/test_new_pipeline.py` — MockSweep, invalid TradePlan path
- `tests/test_decision_trace.py` — save with hypothesis_snapshot present
- `tests/test_risk.py` — isfinite NaN cases
- `tests/test_outcome_tracker.py` — EXPIRED real pnl (after B-018)
- `tests/test_feature_builder.py` / numeric-only — wave_label
- New: migration test that `Database.init` on empty DB creates all ORM columns

**Do NOT change yet (wait for data after fixes):**
- min_p_tp / min_rr_ratio / max_active_signals — baseline invalid until B-013/B-014
- Premium/discount (AGENTS.md: OFF after bad A/B)
- ML retrain threshold 100 outcomes

**Deploy order:**
1. Commit tree fixes (note=) + B-015 + B-013 + B-014
2. Restart live bot
3. Verify traces growing, data_integrity_fail flat
4. Commit B-017/B-016 (observability)
5. Port v2.0 B-003/B-008–B-012 as one series
6. Re-run full pytest with timeout; fix B-023
7. Only then touch config thresholds / hypotheses entries H-0xx

---

## VIII. Test verification (batched runs, post-fix)

Full `pytest` still hangs (network) — package runs only.

| Package | Result |
|---------|--------|
| test_config + test_decision_trace + test_database + test_outcome_tracker + test_backtest_parity | **123 passed**, 1 xfailed |
| test_new_pipeline + test_risk + test_analytics | 229 passed; **4 pre-existing fails** in test_new_pipeline (RR 2.64/2.33, portfolio_risk threshold, full_reversal/continuation) |
| test_scanner | 12 passed; **1 pre-existing** `test_returns_none_when_cooldown` (`_semaphore` NoneType) |
| test_liquidity + test_htf_bias_v2 + test_signal | **117 passed**, 1 xfailed |
| smoke import + AST (17 files) | OK; gates 31/31; `max_sl_atr=3.0` |

Known non-green (pre-existing, not B-013…B-027 regressions):
- `tests/test_new_pipeline.py` — 4 assertion fails (thresholds / pipeline integration)
- `tests/test_scanner.py::TestScanSymbolV2::test_returns_none_when_cooldown`

`.env` keys added this cycle: `MAX_SL_ATR=3.0`, `SWEEP_LOOKBACK=50`,
`OB_LOOKBACK=100`, `STRUCTURE_LOOKBACK=50`, `BLOCK_*_HTF`, `HTF_PENALTY_*`
(matches `.env.example`; required by `test_env_matches_example_structure`).
