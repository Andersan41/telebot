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
