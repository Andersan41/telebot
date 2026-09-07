# Audits & Logic Documentation History

> Хронология аудитов и документации логики бота.

## Текущие файлы (корень проекта)

| Файл | Дата | Описание |
|------|------|----------|
| `logic_bot_1.1.md` | 2026-09-07 | **АКТИВНАЯ ВЕРСИЯ** — полная карта логики с исправлениями по аудиту Astra (A06–A22) |
| `logic_bot_v1.0.md` | 2026-09-07 | Оригинальная версия v1.0 (до исправлений) |

## Архив аудитов (`docs/audits/`)

| Файл | Дата | Автор | Описание |
|------|------|-------|----------|
| `deep_audit_astra_2026-09-07.md` | 2026-09-07 | Astra (старшая модель) | Глубокий аудит: 22 находки (A01–A22), P0/P1/P2, формальные доказательства, предложения контрактов |
| `logic_up_astra_v1_2026-09-05.md` | 2026-09-05 | Astra (v1) | Первый независимый аудит: NO-GO для реальной торговли, P0/P1 находки |
| `improvement_plan_v2.1_2026-09-04.md` | 2026-09-04 | MiMo | План улучшений v2.1: синтез трёх оценок, 5 фаз |
| `logic_v3_status_2026-09-04.md` | 2026-09-04 | MiMo | Статус v3: Phase 0-1 выполнены, live data collection |
| `logic_v1_2026-09-03.md` | 2026-09-03 | MiMo | Первая версия документации логики |
| `architecture_audit_2026-08-27.md` | 2026-08-27 | MiMo | Полная инвентаризация архитектуры v2.5.0 |
| `architecture_audit_2026-07-27.md` | 2026-07-27 | MiMo | Первоначальная инвентаризация v2.4.0 |

## Линия исправлений (code changes)

| Дата | Found By | IDs | Суть |
|------|----------|-----|------|
| 2026-09-07 | Astra | A08 | `expected_rr` и `profit_factor` — неверные формулы (вероятность дважды) |
| 2026-09-07 | Astra | A09 | EV gate отсутствует в fixed mode |
| 2026-09-07 | Astra | A10 | Min-notional: неверная размерность (quantity vs notional) |
| 2026-09-07 | Astra | A13 | TradeEngine TP ↔ PositionManager partial close не связаны (ExitPlan) |
| 2026-09-07 | Astra | A15 | PnL/trailing/BE — docstrings long-only, BE buffer < costs |
| 2026-09-07 | Astra | A12 | Shadow engines влияют на sizing — переименованы в analytical overlays |
| 2026-09-07 | Astra | A22 | Trace фильтрует 35/53 features — добавлен полный вектор |
| 2026-09-07 | Astra | A06 | HTF neutral: single-TF conviction классифицировался как NEUTRAL |
