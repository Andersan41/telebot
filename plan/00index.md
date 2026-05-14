# Индекс плана модернизации Trading Signal Bot

## Легенда статусов

- ✅ **сделано** — пункт реализован в коде и описан в плановом файле.
- 🔴 **не сделано** — пункт пока не реализован (либо реализован частично и не соответствует
  описанию в плановом файле).

## Структура

| #  | Файл                                                   | Раздел                  | Статус | Описание                                     |
|----|--------------------------------------------------------|-------------------------|--------|----------------------------------------------|
| 01 | [01-architecture.md](01-architecture.md)               | Архитектура             | ✅      | Общая схема, ключевые принципы               |
| 02 | [02-main.md](02-main.md)                               | main.py                 | 🔴     | Точка входа, жизненный цикл                  |
| 03 | [03-config.md](03-config.md)                           | config/                 | 🔴     | Настройки, логирование                       |
| 04 | [04-exchange-client.md](04-exchange-client.md)         | data/exchange_client.py | 🔴     | Клиент биржи, OHLCV                          |
| 05 | [05-indicators.md](05-indicators.md)                   | indicators/engine.py    | 🔴     | Расчёт индикаторов                           |
| 06 | [06-signal-engine.md](06-signal-engine.md)             | strategy/signal_engine  | 🔴     | Логика сигналов, SL/TP (score 6, не 7)       |
| 07 | [07-scheduler.md](07-scheduler.md)                     | scheduler/              | 🔴     | Планировщик и сканер                         |
| 08 | [08-context.md](08-context.md)                         | context/                | 🔴     | Контекст: F&G/CG/funding/OI/L-S/news         |
| 09 | [09-bot.md](09-bot.md)                                 | bot/                    | 🔴     | Обработчики, меню, уведомления               |
| 10 | [10-database.md](10-database.md)                       | storage/database.py     | 🔴     | База данных                                  |
| 11 | [11-pipeline.md](11-pipeline.md)                       | Полный пайплайн         | 🔴     | Пошаговый цикл сигнала                       |
| 12 | [12-flowchart.md](12-flowchart.md)                     | Блок-схема              | 🔴     | Decision flowchart                           |
| 13 | [13-telegram-formatting.md](13-telegram-formatting.md) | TG-форматирование       | 🔴     | HTML, экранирование                          |
| 14 | [14-env-config.md](14-env-config.md)                   | .env                    | 🔴     | Полный список переменных                     |
| 15 | [15-gotchas.md](15-gotchas.md)                         | Gotchas                 | 🔴     | Известные баги и подводные камни             |
| 16 | [16-commands.md](16-commands.md)                       | Команды Telegram        | 🔴     | Полный список команд                         |
| 17 | [17-improvements.md](17-improvements.md)               | Улучшения / долг        | 🔴     | Индекс задач; спецификации в `improvements/` |

## Спецификации задач из бэклога (раздел 17)

Каждая задача — отдельный файл в `plan/improvements/`. Можно передавать любому исполнителю
по одному файлу, контекст самодостаточен.

| #  | Файл                                                                               | Приоритет   |
|----|------------------------------------------------------------------------------------|-------------|
| A1 | [improvements/A1-indicators-env.md](improvements/A1-indicators-env.md)             | ✅ 🟠 high     |
| A2 | [improvements/A2-oi-warmup.md](improvements/A2-oi-warmup.md)                       | ✅ 🟡 medium   |
| A3 | [improvements/A3-oi-scoring-direction.md](improvements/A3-oi-scoring-direction.md) | 🟡 medium   |
| A4 | [improvements/A4-cooldown-db.md](improvements/A4-cooldown-db.md)                   | ✅ 🔴 critical |
| A5 | [improvements/A5-confirm-in-menu.md](improvements/A5-confirm-in-menu.md)           | 🟡 medium   |
| A6 | [improvements/A6-score-formula.md](improvements/A6-score-formula.md)               | 🟢 low      |
| T1 | [improvements/T1-github-actions.md](improvements/T1-github-actions.md)             | ✅ 🟠 high     |
| T2 | [improvements/T2-tests.md](improvements/T2-tests.md)                               | ✅ 🟠 high     |
| T3 | [improvements/T3-ops-tickets.md](improvements/T3-ops-tickets.md)                   | 🟢 low      |
| F1 | [improvements/F1-signal-outcome.md](improvements/F1-signal-outcome.md)             | 🟢 low      |
| F2 | [improvements/F2-futures-ohlcv.md](improvements/F2-futures-ohlcv.md)               | 🟢 low      |
| F3 | [improvements/F3-dynamic-symbols.md](improvements/F3-dynamic-symbols.md)           | 🟢 low      |
| F4 | [improvements/F4-admin-commands.md](improvements/F4-admin-commands.md)             | 🟢 low      |

## Сопутствующие документы вне `plan/`

- `AGENTS.md` — краткая инструкция по архитектуре/тестам/gotchas для AI-агентов.
- `CONTEXT_ENRICHMENT_PLAN.md` — расширенный design-doc контекстного модуля.
- `tests/` — pytest, включая `test_architecture.py` (smoke-проверка структуры).
- `README.md` — пользовательская инструкция запуска.
