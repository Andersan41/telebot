# 📋 План исправлений бота — Оглавление

> Разбит на 4 этапа по приоритету. Выполнять последовательно.

---

## Этапы

| Этап | Файл | Содержимое | Приоритет | Статус |
|------|------|------------|-----------|--------|
| 1 | `phase1_critical_bugs.md` | Баги #1–3: Funding пороги, OB age filter, scanner порядок | 🔴 Критический | ✅ |
| 2 | `phase2_important_issues.md` | Баги #4–6: EMA дублирование, OI direction, MACD columns | ⚠️ Важная | ✅ |
| 3 | `phase3_moderate_issues.md` | Баги #7–8: Volume SMA config, Dynamic Risk config | ⚠️ Умеренная | ✅ |
| 4 | `phase4_improvements.md` | Рекомендации #9–13: retry, warm-up, RSS, кэш, рефакторинг | 💡 Улучшение | ✅ |

---

## Рекомендуемый порядок

**Неделя 1:** Этапы 1–2 (критические + важные баги)  
**Неделя 2:** Этап 3 (умеренные проблемы)  
**Неделя 3+:** Этап 4 (улучшения по приоритету)

---

## Сводная таблица всех исправлений

| # | Файл | Проблема | Приоритет | Этап | Статус |
|---|------|----------|-----------|------|--------|
| 1 | `derivatives/funding.py` | Пороги 0.03/0.01 вместо 0.0003/0.0001 | 🔴 | 1 | ✅ |
| 2 | `liquidity/order_blocks.py` | `_filter_by_age` — заглушка | 🔴 | 1 | ✅ |
| 3 | `scheduler/scanner.py` | `context_verdict` = None при no-trade check | 🔴 | 1 | ✅ |
| 4 | `strategy/signal_engine.py` | EMA дублирование (3 фактора из 8) | ⚠️ | 2 | ✅ |
| 5 | `context/scorer.py` | `_score_oi` игнорирует direction | ⚠️ | 2 | ✅ |
| 6 | `indicators/engine.py` | MACD по индексам вместо имён | ⚠️ | 2 | ✅ |
| 7 | `indicators/engine.py`, `liquidity/sweep.py` | Volume SMA period захаркожен | ⚠️ | 3 | ✅ |
| 8 | `risk/dynamic_risk.py` | `os.getenv` вместо config | ⚠️ | 3 | ✅ |
| 9 | `bot/notifier.py` | Нет retry при TelegramError | 💡 | 4 | ✅ |
| 10 | `context/fetcher.py` | OI warm-up не помечается | 💡 | 4 | ✅ |
| 11 | `context/scorer.py` | RSS keyword matching примитивный | 💡 | 4 | ✅ |
| 12 | `scheduler/scanner.py` | BTC/ETH fetch дважды | 💡 | 4 | ✅ |
| 13 | `scheduler/scanner.py` | scan_symbol 685 строк | 💡 | 4 | 🔴 |
