# План восстановления работоспособности бота

## Текущие проблемы

### 1. Python 3.14.4 — слишком новый
Установлен Python 3.14.4. Большинство библиотек из `requirements.txt` не имеют wheels для этой версии и не могут собраться из исходников.

### 2. Зависимости не установлены
Из 12 пакетов установлены только:
- `python-telegram-bot==20.7` ✅
- `python-dotenv` ✅

Не установлены:
- `ccxt` — нет доступа к бирже
- `aiosqlite`, `sqlalchemy` — нет БД
- `apscheduler` — нет планировщика
- `loguru` — нет логирования
- `pandas-ta` — нет индикаторов
- `aiohttp` — нет HTTP-клиента
- `pandas==2.1.4`, `numpy==1.26.2` — не могут собраться (нет C-компилятора MSVC)

### 3. Ошибка компиляции
При `pip install` numpy/pandas падают с:
```
ERROR: Unknown compiler(s): [['icl'], ['cl'], ['cc'], ['gcc'], ...]
```
Требуется Visual Studio Build Tools (C++ компилятор).

### 4. Конфликт библиотек: `pandas_ta` vs `ta`
Код использует `import pandas_ta as ta`, но в системе установлена `ta==0.11.0` (другая библиотека).

### 5. API-ключи в открытом доступе
Файл `.env` содержит реальные ключи Binance и Telegram токен, которые попали в репозиторий.

### 6. `pandas-ta==0.3.14b` удалён с PyPI
Старая версия `pandas-ta==0.3.14b` больше не существует на PyPI. Новая версия `0.4.71b0` требует Python >=3.12 и numpy >=2.2.6, что конфликтует с `pandas==2.1.4` (numpy<2).

## Выполнено

### ✅ Шаг 1: Установлен Python 3.12.9
Вместо Python 3.11 (из плана). Причина: `pandas-ta>=0.4.0` требует Python >=3.12.

### ✅ Шаг 2: Обновлён requirements.txt
- `pandas==2.1.4` → `pandas>=2.2.0`
- `numpy==1.26.2` → `numpy>=2.2.6`
- `pandas-ta==0.3.14b` → `pandas-ta>=0.4.0`

Фактически установлено:
- pandas 3.0.3, numpy 2.2.6, pandas-ta 0.4.71b0

### ✅ Шаг 3: Создан venv с Python 3.12 и установлены зависимости
`pip install --only-binary :all: -r requirements.txt` выполнен успешно.

### ✅ Шаг 4: Исправлена совместимость с новой pandas-ta
В `indicators/engine.py` — исправлен парсинг столбцов ADX/DMI (добавилась колонка `ADXR_14_2` в новой pandas-ta, что сдвинуло индексы).

### ✅ Шаг 5: Протестировано
- Импорты всех модулей — OK
- Инициализация БД — OK
- Подключение к бирже — OK
- Расчёт индикаторов (RSI, ADX, ATR, Supertrend, MACD, EMA) — OK
- Оценка сигналов (BUY/SELL/NO_SIGNAL) — OK
- Сохранение/чтение из БД — OK

## Осталось сделать

### ✅ Шаг 6: Удалить реальные ключи из `.env`
- Реальные ключи заменены на заглушки в `.env`
- Создан `.env.example` с теми же заглушками
- Написаны и запущены тесты (39 шт., все проходят):
  - `tests/test_config.py` — проверка `.env`, `.env.example`, отсутствия секретов
  - `tests/test_indicators.py` — Supertrend, ADX/DMI, MACD, Engine
  - `tests/test_signal.py` — 7 критериев, BUY/SELL/NO_SIGNAL, SL/TP
  - `tests/test_database.py` — init, save/read, CRUD

### ✅ Шаг 7: Запустить бота (выполнено)
- `main.py` запущен — бот стартовал: DB init, exchange client, Telegram handlers, scheduler — все этапы пройдены
- Написаны тесты для оставшихся модулей (69 шт., все проходят):
  - `tests/test_exchange_client.py` — connect, fetch_ohlcv, fetch_all_symbols, close, ошибки сети
  - `tests/test_scanner.py` — cooldown, scan_symbol (полный цикл, пустые данные, неподтверждённый сигнал), run_scan_cycle
  - `tests/test_notifier.py` — send_signal, send_error_alert, get_bot singleton
  - `tests/test_main.py` — валидация токена, пустой токен, полный startup sequence (с mocked зависимостями)
