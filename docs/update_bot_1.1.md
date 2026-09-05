# План доработки бота v1.1

## Контекст

Текущее состояние: Phase 0 (аудит-инфраструктура) закоммичена (`dce8b07`). Бот генерирует сигналы, но имеет ряд пробелов в аудите, логике и архитектуре, которые необходимо закрыть перед началом live/paper сбора данных.

Источники: наш коммит, proposed plan (3 этапа), logic_up.md (независимый аудит), исследования кодовой базы.

---

## Этап 1: Аудит + безопасные правки (без изменения логики)

**Цель:** каждый blocked gate имеет правильный reason_code, мёртвый код удалён, breakout clamp, документация.

**Время:** ~2 часа

---

### 1.1 Удалить EV_GATE_FAILED

**Файл:** `storage/audit_reasons.py`
**Проблема:** `EV_GATE_FAILED = "ev_gate_failed"` определён, но нигде не импортируется и не используется. EV-гейта в `risk/engine.py` не существует.
**Действие:** Удалить строку.
**Риск:** Нулевой — мёртвый код.

---

### 1.2 Добавить аудит в data integrity gate

**Файл:** `scheduler/scanner.py`
**Проблема:** Гейт OHLCV/indicators блокирует сигнал, но не вызывает `_audit_log()`. `DATA_INTEGRITY_FAIL` импортирован, но мёртв.
**Действие:** Добавить `_audit_log(..., DATA_INTEGRITY_FAIL, False)` после `trace.save(db)`.

---

### 1.3 Расширить диспатч Risk Engine

**Файл:** `scheduler/scanner.py`
**Проблема:** 8 sub-gates в `risk/engine.py`, scanner маппит только 4. Остальные попадают в `SL_TOO_WIDE`.
**Действие:** Добавить ветки: `max_active_signals → PORTFOLIO_MAX_ACTIVE`, `portfolio_risk_limit → PORTFOLIO_MAX_RISK`, `invalid_price_data → DATA_INTEGRITY_FAIL`, `zero_risk_distance → DATA_INTEGRITY_FAIL`.

---

### 1.4 Добавить HTF version tag

**Файл:** `scheduler/scanner.py` (8 audit-вызовов в HTF bias блоках)
**Проблема:** V1 и V2 используют одинаковые reason codes, неразличимы в логах.
**Действие:** Добавить `meta=f"version=v2,..."` / `meta=f"version=v1,..."`.

---

### 1.5 Добавить аудит в correlation gate

**Файл:** `scheduler/scanner.py`
**Проблема:** Гейт мёртвый (`config.trading.correlated_symbols` не определён), но `CORRELATION_BLOCKED` не используется.
**Действие:** Добавить `_audit_log(..., CORRELATION_BLOCKED, False)` в блок gate.

---

### 1.6 Clamp breakout quality score

**Файл:** `liquidity/breakout_quality.py`
**Проблема:** Score может превысить 100 (сумма весов = 105).
**Действие:** `score = max(0.0, min(score - penalty, 100.0))`. Не повышать `breakout_quality_hard_gate` до True.

---

### 1.7 Документация config_version

**Файлы:** `scheduler/scanner.py`, `AGENTS.md`
**Действие:** Добавить комментарий-правило к `_CONFIG_VERSION` и запись в AGENTS.md.

---

### 1.8 Confirmation score meta

**Файл:** `scheduler/scanner.py`
**Статус:** Уже реализовано в коммите `dce8b07`. Проверить корректность.

---

### 1.9 Прогон тестов

**Ожидаемый результат:** 146 passed, 7 xfailed, 0 failed.

---

## Этап 2: Исправления логики

**Цель:** устранить TOCTOU, Kelly zero, atomicity, signal/fill, shadow isolation, min_notional.

**Время:** ~3-4 часа

---

### 2.1 Kelly zero → reject

**Файл:** `risk/engine.py`
**Проблема:** `kelly <= 0` → `risk_pct = 0.0` → `max(min_risk_pct, 0.0)` → 0.1%. Сделка с отрицательным EV проходит.
**Действие:** После расчёта kelly: `if kelly <= 0 and _risk_mode != 'fixed': return RiskDecision(should_trade=False, ...)`.

---

### 2.2 Portfolio TOCTOU: атомарный recheck

**Файлы:** `scheduler/scanner.py`, `storage/database.py`
**Проблема:** Проверка limits и сохранение сигнала разделены ~1700 строк. Coroutine может превысить лимиты.
**Действие:** Метод `try_reserve_signal()` в БД с атомарной проверкой + резервированием.

---

### 2.3 Daily limits: атомарность

**Файл:** `risk/daily_limits.py`
**Проблема:** `can_open_trade()` и `record_trade_opened()` — разные вызовы.
**Действие:** Объединить в `try_open_trade()`.

---

### 2.4 Signal/fill разделение (paper mode)

**Файл:** `scheduler/scanner.py`
**Проблема:** `create_outcome()` сразу после `save_signal()` — до фактического fill.
**Действие:** State machine: `SIGNAL_PERSISTED → PAPER_ENTRY_FILLED → PAPER_POSITION_OPEN → PAPER_POSITION_CLOSED`.

---

### 2.5 Phase 8: atomic save

**Файл:** `scheduler/scanner.py`
**Проблема:** 7 отдельных DB-транзакций. Сбой между шагами → неполные данные.
**Действие:** Обернуть save_signal + trace + audit + outcome + cooldown в одну транзакцию. Telegram после commit.

---

### 2.6 Reversal priority: independent eval

**Файлы:** `scheduler/scanner.py`, `strategy/pattern_engine.py`
**Проблема:** Reversal имеет приоритет. Если заблокирован — continuation не рассматривается.
**Действие:** `detect()` возвращает `[reversal_candidate, continuation_candidate]`. Каждый проходит gates независимо.

---

### 2.7 Shadow ≠ shadow: явный flag

**Файл:** `scheduler/scanner.py`, `config/settings.py`
**Проблема:** `config.shadow_mode` определён, но нигде не читается. Thesis/hypothesis реально влияют на sizing.
**Действие:** Если `shadow_mode=True`: `_thesis_score=0.0`, `_thesis_stability=0.0`, `_entry_target=SimpleEntryTarget`.

---

### 2.8 min_notional guard

**Файлы:** `risk/engine.py`, `storage/audit_reasons.py`, `scheduler/scanner.py`
**Проблема:** Не проверяется минимальный notional биржи.
**Действие:** `position_size_usdt < min_notional → reject`. Новый код `POSITION_SIZE_BELOW_MIN`.

---

### 2.9 Скрипт ежедневного отчёта

**Файл:** `scripts/daily_reason_report.py` (новый)
**Действие:** SQL query по `signal_audit_log`, GROUP BY reason_code.

---

### 2.10 Тесты

Новые тесты для 2.1-2.8 + regression.

---

## Этап 3: Сбор данных + synthetic plan

**Цель:** сбор candidate dataset + hypothetical outcomes.

**Время:** 2-3 часа + непрерывный сбор

---

### 3.1 Synthetic plan (a): генерация гипотетического плана

**Действие:** Для каждого BLOCKED сигнала: вычислить hypothetical entry/SL/TP/RR/P(TP) и записать в `signal_audit_log.hypothetical_*`.

---

### 3.2 Candidate dataset: rejected tracking

**Действие:** Таблица `signal_candidates` дляrejected candidates с feature snapshot + blocked_gate.

---

### 3.3 Point-in-time snapshots

**Действие:** Добавить `as_of_utc`, `is_final`, `data_age_ms` в `signal_audit_log`.

---

### 3.4 Synthetic plan (b): forward-walk outcome

**Статус:** Отдельная задача после 1-2 недель сбора.

---

## Этап 4: Дополнения (после сбора)

| Шаг | Описание | Effort |
|-----|----------|--------|
| 4.1 | Config reachability audit | 1-2 ч |
| 4.2 | OB/FVG lifecycle (P1-03) | 2-3 ч |
| 4.3 | Breakout per setup type (P1-04) | 1-2 ч |
| 4.4 | Exit policy (P1-06) | 3-4 ч |
| 4.5 | Position-size-aware execution (P1-08) | 2-3 ч |
| 4.6 | ML calibration plan (P0-09) | 1-2 дн |

---

## Сводная таблица

| Этап | Шаг | Effort | Blocks start? |
|------|-----|--------|---------------|
| 1 | 1.1-1.9 | ~2 ч | Нет |
| 2 | 2.1-2.10 | ~3-4 ч | Да (2.10) |
| 3 | 3.1-3.3 | ~3 ч | Нет (параллельно) |
| 3 | 3.4 | 1-2 дн | Нет (после сбора) |
| 4 | 4.1-4.6 | 1-2 нед | Нет |

**Критический путь:** 1 → 2 (2.1-2.5) → 3 (3.1-3.3) → старт сбора
**Total pre-start:** ~7-8 часов
