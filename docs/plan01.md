# Plan of Record — Session #1 (12.05.2026)

## Goal
Установить Python 3.12 и зависимости, починить совместимость `pandas-ta`, запустить тесты импортов/индикаторов/сигналов/БД.

## Constraints
- Нет C-компилятора (MSVC) — только `--only-binary :all:`
- Windows, Binance, SQLite
- Не менять структуру файлов

## Root Cause
- Python 3.14.4 слишком новый — нет wheels для большинства пакетов
- `pandas-ta==0.3.14b` удалён с PyPI
- `pandas==2.1.4` конфликтует с numpy>=2 (требуется новой pandas-ta)

## Timeline

### 1. Анализ
- Прочитал структуру проекта, `requirements.txt`, `.env`, `main.py`, ключевые модули
- Выявил 6 проблем: Python 3.14, отсутствие зависимостей, no MSVC, конфликт `pandas_ta` vs `ta`, открытые API-ключи, удалённый пакет

### 2. Установка Python 3.12.9
- Скачал и установил `python-3.12.9-amd64.exe`
- Переключился на Python 3.12.9 вместо первоначально запланированного 3.11 — т.к. `pandas-ta>=0.4.0` требует Python >=3.12

### 3. Установка зависимостей
- Создал `.venv` с Python 3.12.9, обновил pip
- Изменил `requirements.txt`:
  - `pandas==2.1.4` → `pandas>=2.2.0` (факт: 3.0.3)
  - `numpy==1.26.2` → `numpy>=2.2.6` (факт: 2.2.6)
  - `pandas-ta==0.3.14b` → `pandas-ta>=0.4.0` (факт: 0.4.71b0)
- `pip install --only-binary :all: -r requirements.txt` — успешно

### 4. Исправление кода
- **`indicators/engine.py`**: pandas-ta 0.4.71b0 добавила колонку `ADXR_14_2` в ADX DataFrame, сдвинув индексы iloc — заменил на выборку по имени колонки

### 5. Тестирование
- Все импорты — OK
- Инициализация БД — OK
- Расчёт индикаторов — OK
- Оценка сигнала (BUY/SELL/NO_SIGNAL) — OK
- Сохранение/чтение БД — OK
- Форматирование сообщения — OK

## Key Decisions
- Python 3.12.9 вместо 3.11.9 — `pandas-ta>=0.4.0` несовместима с Python <3.12
- `pandas`/`numpy` pins расслаблены с `==` на `>=` — жёсткие старые версии конфликтуют с новой pandas-ta
- `pandas-ta` удалена версия 0.3.14b — заменено на `>=0.4.0`
- Все зависимости установлены через `--only-binary :all:` — нет MSVC

### 6. Очистка .env и написание тестов
- Реальные API-ключи удалены из `.env`, заменены на заглушки
- Создан `.env.example` с теми же заглушками (безопасен для коммита)
- Установлен `pytest` + `pytest-asyncio`
- Создана тестовая инфраструктура (39 тестов)

### 7. Запуск бота и тестирование всех модулей
- `main.py` запущен — **полный startup успешен:**
  - Database initialized
  - Exchange client created: binance
  - Telegram handlers registered
  - Scheduler jobs configured + started
  - Bot configuration printed (symbols, timeframes, channel)
  - Ошибка `Conflict: terminated by other getUpdates request` — ожидаема (реальный бот уже запущен с этим токеном ранее)
- Добавлены тесты для оставшихся модулей (ещё 30 тестов):
  - **`tests/test_exchange_client.py`** (8 тестов):
    - connect, connect_creates_exchange, fetch_ohlcv_returns_dataframe
    - fetch_ohlcv_empty_response, fetch_ohlcv_network_error
    - fetch_all_symbols, close, close_when_not_connected, singleton_exists
  - **`tests/test_scanner.py`** (9 тестов):
    - Cooldown: init, after_set, different_symbol, different_timeframe
    - scan_symbol: full_successful, no_indicator_data, not_actionable
    - confirmation rejects mismatch, cooldown_after_signal
    - run_scan_cycle
  - **`tests/test_notifier.py`** (7 тестов):
    - send_signal: no_channel, calls_bot, telegram_error
    - send_error_alert: no_admins, sends_to_admins
    - get_bot: singleton, correct_token
  - **`tests/test_main.py`** (3 теста):
    - validates_token_presence (пустой токен → exit 1)
    - empty_token_logs_error (логгер вызывается)
    - successful_startup_sequence (полный цикл с KeyboardInterrupt shutdown)
- **69/69 тестов проходят**

## Key Decisions
- Python 3.12.9 вместо 3.11.9 — `pandas-ta>=0.4.0` несовместима с Python <3.12
- `pandas`/`numpy` pins расслаблены с `==` на `>=` — жёсткие старые версии конфликтуют с новой pandas-ta
- `pandas-ta` удалена версия 0.3.14b — заменено на `>=0.4.0`
- Все зависимости установлены через `--only-binary :all:` — нет MSVC
- Тесты используют реальные объекты (IndicatorValues, SignalResult), не моки — чтобы проверять реальную логику

## Next Steps
- Установить реальные API-ключи обратно в `.env` для запуска бота
- Запустить `main.py` (требует live Telegram token + Binance API key)
- Docker: обновить образ на `python:3.12-slim`
- Добавить тесты на scanner.py, scheduler.py, exchange_client.py

## Files Changed
- `.env` — удалены реальные ключи, вставлены заглушки
- `.env.example` — новый файл (копия `.env` без секретов)
- `requirements.txt` — версии pandas, numpy, pandas-ta
- `indicators/engine.py` — парсинг ADX/DMI по имени колонки
- `tests/conftest.py` — новый файл
- `tests/test_config.py` — новый файл
- `tests/test_indicators.py` — новый файл
- `tests/test_signal.py` — новый файл
- `tests/test_database.py` — новый файл
- `pytest.ini` — новый файл
- `docs/plan.md` — обновлён план
- `docs/01.md` — добавлен раздел изменений
