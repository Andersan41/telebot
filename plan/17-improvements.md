# 9. Возможные улучшения и накопленный долг

## Недавно исправлено (см. git log)

- ✅ Funding rate — переведён на прямой HTTP `fapi/v1/premiumIndex`.
- ✅ OI delta — % изменение per-symbol через in-memory `_last_oi`.
- ✅ `CONTEXT_MIN_VERDICT` — ранговый гейт в `scanner.scan_symbol`.
- ✅ `signal_engine.format_message` — знаменатель `/6`.
- ✅ Дубль cron-джобов — `_scan_job` параметризован, 1H/4H разнесены.
- ✅ Race на `news_sentiment_score` — аккумуляция CryptoPanic+RSS после `asyncio.gather`.
- ✅ `db.save_signal(confirmed=…)` — отражает реальный результат 15M-фильтра.
- ✅ Архитектурные тесты — `tests/test_architecture.py` (плановый пункт 01).

---

## Не сделано — бэклог задач

Каждая задача — **самодостаточная спецификация** в отдельном файле под `plan/improvements/`.
Перед началом работы исполнитель должен прочитать соответствующий раздел плана (`plan/0X-…md`)
и упомянутые участки кода. **Не меняй ничего за пределами «Файлы» без отдельного согласования.**

### Архитектура

| #  | Файл                                                             | Кратко                                                              |
|----|------------------------------------------------------------------|---------------------------------------------------------------------|
| A1 | [A1-indicators-env.md](improvements/A1-indicators-env.md)        | Параметры индикаторов из `.env`, не из захардкоженных значений      |
| A2 | [A2-oi-warmup.md](improvements/A2-oi-warmup.md)                  | OI delta переживает рестарт (warm-up из исторического эндпоинта)    |
| A3 | [A3-oi-scoring-direction.md](improvements/A3-oi-scoring-direction.md) | OI-шкала в scorer'е перестаёт игнорировать `direction`         |
| A5 | [A5-confirm-in-menu.md](improvements/A5-confirm-in-menu.md)      | 15M-подтверждение в меню `_do_full_analysis`                        |
| A6 | [A6-score-formula.md](improvements/A6-score-formula.md)          | Score: ADX/DMI как реальные критерии, max=8 (опционально)           |

### Тесты / DX

| #  | Файл                                                             | Кратко                                                              |
|----|------------------------------------------------------------------|---------------------------------------------------------------------|
| T1 | [T1-github-actions.md](improvements/T1-github-actions.md)        | CI на GitHub Actions                                                |
| T2 | [T2-tests.md](improvements/T2-tests.md)                          | Тесты на свежие правки (OI, news, MIN_VERDICT, funding, confirmed)  |
| T3 | [T3-ops-tickets.md](improvements/T3-ops-tickets.md)              | Mini-тикеты: CI/CD, error sink, rate limiting, Prometheus           |

### Функциональность

| #  | Файл                                                             | Кратко                                                              |
|----|------------------------------------------------------------------|---------------------------------------------------------------------|
| F1 | [F1-signal-outcome.md](improvements/F1-signal-outcome.md)        | SL/PnL трекинг (`SignalOutcome`, `/stats`)                          |
| F2 | [F2-futures-ohlcv.md](improvements/F2-futures-ohlcv.md)          | Поддержка futures для OHLCV (`MARKET_TYPE`)                         |
| F3 | [F3-dynamic-symbols.md](improvements/F3-dynamic-symbols.md)      | Динамическое управление символами (`/addsymbol`, `/removesymbol`)   |
| F4 | [F4-admin-commands.md](improvements/F4-admin-commands.md)        | Admin-команды: `/setparam`, `/disable`/`/enable`, `/exportdb`       |

---

## Шпаргалка по приоритетам

| Приоритет   | Задачи             | Почему                                  |
|-------------|--------------------|-----------------------------------------|
| 🟠 high     | T1, T2         | Эксплуатационная гибкость + регрессии   |
| 🟡 medium   | A3, A5         | Качество сигналов и UX                  |
| 🟢 low      | A6, T3, F1–F4      | Новая функциональность, не баги         |
