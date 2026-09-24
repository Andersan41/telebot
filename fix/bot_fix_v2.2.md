# bot_fix_v2.2.md — Restore signal flow (H-016)

## Date: 2026-09-24
## Branch: feat/htf-bias-v2-premium-discount
## Config version: 12 (`_CONFIG_VERSION`); app VERSION: 2.5.0
## Hypothesis: H-016 (`docs/hypotheses.md`)
## Baseline: `fix/bot_fix_v2.1.md` (B-013:B-027)

---

## I. Problem

Живая воронка 2026-09-24 18:19: `entered=150, sent=0`.

- `pattern_engine=95` (63%), исторически 5982× `"reversal: sweep only (no MSS)"` —
  sweep-триггер есть, MSS (CHoCH) нет, оба пути (`_try_reversal` + `_try_continuation`)
  отклонены → детект мёртв. H-009 описывал soft MSS gate, но `detect()` возвращал
  `detected=False` до всякого гейта (`pattern_engine.py`), soft-gate `mss_gate` в
  `scanner.py` был недостижим и логировался дважды при проходе.
- `entry_trigger=19` — фиксированный `entry_proximity_pct=0.3%` при ATR 1–4%.

## II. Fixes

### B-028 — Sweep-only dead-end rescue (Option B + guard M2) — Phase 1

**Files:** `strategy/pattern_engine.py`, `storage/audit_reasons.py`, `scheduler/scanner.py`

- `detect()`: если оба пути отклонены и есть валидный sweep без MSS → слабый reversal,
  направление от `sweep_type` (bullish→buy, bearish→sell), `rescued_sweep_only=True`.
- **Guard:** rescue только при `has_ob or has_fvg` после `_detect_entry_zones`, иначе
  reject `reversal: sweep-only dead-end without zone (no MSS)` → reason code
  `SWEEP_DEAD_END_NO_ZONE` (ветка маппинга ПЕРВОЙ в `scanner.py`, т.к. содержит и "no MSS").
- **Reason-merge (1.1):** при обоюдном фейле причина комбинируется:
  `"{reversal_rejection} + {continuation_rejection}"` — мотивы обеих ветвей не маскируются.
- **Telemetry (1.2b):** `rescued_sweep_only=1` в funnel detail + audit `meta` на
  `pattern_engine: PASS`, INFO-лог `[RESCUED]`.
- **Probability (1.7):** sweep edge в reversal `+3.0` только при `has_mss`, иначе `+1.5`
  (`strategy/probability_engine.py`).
- `_CONFIG_VERSION` 11→12 (A/B атрибуция audit-записей).

### B-029 — ATR-relative entry proximity — Phase 2

**Files:** `strategy/entry_trigger.py`, `config/settings.py`, `scheduler/scanner.py`,
`.env`, `.env.example`

- `resolve_proximity_pct(base, atr_pct, mult) = max(base, atr_pct * mult)`.
- Применено в ОБЕИХ точках: Phase 1.6 и Phase 4.5 `scan_symbol_v2` (раньше точка 4.5
  вообще использовала дефолт `EntryTrigger()`).
- Env: `ENTRY_PROXIMITY_PCT=0.3` (floor), `ENTRY_PROXIMITY_ATR_MULT=0.5`;
  добавлены в `.env.example` и `build_config_snapshot()`.
- Ожидание: BTC 1h (ATR≈1%) → 0.5%, альты (ATR≈4%) → 2% вместо 0.3%.

### B-030 — mss_gate double `trace.passed` + SOFT telemetry — Phase 1

**File:** `scheduler/scanner.py`

- Было: SOFT-ветка вызывала `trace.passed("mss_gate")` + безусловный `trace.passed`
  ниже → двойная запись и PASS-лог даже для sweep-only.
- Стало: `if/else` — SOFT логируется один раз и учитывается в `penalties`
  (новый статус `"SOFT"` в `_FunnelCounter.log_gate`), PASS только при `has_mss`.

## III. Verification

- `tests/test_new_pipeline.py`: rescue с зоной (buy/sell), guard без зоны,
  continuation-приоритет, reason-merge, bare-sweep edge < MSS edge.
- `tests/test_entry_trigger.py`: `TestResolveProximityPct` (floor / ATR-доминирование / 0).
- `tests/test_scanner.py`: `test_h016_rescued_reversal_passes_mss_gate_soft` —
  rescued reversal проходит pattern/sweep/displacement, mss_gate SOFT (penalties), не BLOCKED.
- Пакетные прогоны: `test_scanner+test_entry_trigger+test_config` (74 passed),
  `test_signal+test_database+test_risk+test_htf_bias_v2+test_breakout_quality+test_liquidity`
  (262 passed), `test_new_pipeline` (только 4 ранее известных pre-existing фейла RiskEngine).
- Pre-existing (не связаны с правкой, подтверждено на чистом HEAD): `test_new_pipeline` ×4,
  `test_scanner::test_returns_none_when_cooldown`, `test_sanity_checks` ×4, `test_scoring` ×6.

## IV. Offline replay 7д (1h, 500 candles ≈18d, BTC+ETH)

Файлы: `reports/h016_replay_before.txt` / `reports/h016_replay_after.txt`
(`scripts/measure_rejection_rate.py`, паттерн-уровень, 419 баров после warmup).

| | BEFORE | AFTER |
|---|---|---|
| BTC detected | 167 (39.9%) | 167 (39.9%) |
| BTC sweep-only reject | 245× `reversal: sweep only (no MSS)` | 245× `sweep-only dead-end without zone (no MSS)` → `sweep_dead_end_no_zone` |
| BTC masked reasons | 7× `continuation: no BOS` | 7× `reversal: no sweep + continuation: no BOS` (reason-merge) |
| ETH detected | 204 (48.7%) | **213 (50.8%) — +9 rescued** |
| ETH sweep-only reject | 211 | 202 dead-end-no-zone + 9 спасены (`rescued_sweep_only`, 4.2% detected) |

**Выводы калибровки:**
1. Rescue работает: ETH +9 детектов — все со зоной (guard пропустил), BTC 0 —
   ни одного пост-sweep OB/FVG зона не найдена → guard отклонил все 245.
2. Guard — доминант: 245/252 BTC и 202/206 ETH sweep-only отклоняются по
   `sweep_dead_end_no_zone`. Основной сдвиг на этом этапе — **разделение причин**
   (5982-класс перестал быть однообразным `mss_none`, теперь видна доля без зоны).
3. Reason-merge подтверждён (комбинированные причины вместо маскировки).
4. `sent>0` на реплее НЕ оценивается (скрипт паттерн-уровня); фазовый сдвиг
   `entry_trigger` ожидается в live от Phase 2 (ATR-проксимити).
5. Мониторинг после рестарта: доля `sweep_dead_end_no_zone`, `rescued_sweep_only=1`
   в audit meta, доля rescued среди `pattern_engine: PASS`, блоки `entry_trigger`.
6. Откат: revert rescue-блока в `pattern_engine.detect()`; `ENTRY_PROXIMITY_ATR_MULT=0`
   вырождает проксимити в legacy floor 0.3%.
