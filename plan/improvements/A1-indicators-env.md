# A1. Параметры индикаторов через `.env`

> **Статус**: 🔴 не сделано
> **Приоритет**: 🟠 high — эксплуатационная гибкость, сейчас изменение параметра требует правки кода.
> **Зависимости**: нет. Зависимая задача: [F4.1 `/setparam`](F4-admin-commands.md) опирается на A1.

**Цель**: убрать жёстко зашитые числа из `TradingConfig` dataclass и сделать настройку
индикаторов возможной без правки кода (сейчас изменение, например, `ema_fast=9` требует
редактировать `config/settings.py`).

**Файлы и точные места**:

| Файл                         | Что делать                                                                 |
|------------------------------|----------------------------------------------------------------------------|
| `config/settings.py:29-61`   | переписать поля `TradingConfig` на чтение из env                           |
| `.env.example`               | добавить 20 строк под заголовком `# Indicator parameters (defaults shown)` |
| `plan/14-env-config.md`      | добавить таблицу `Indicator parameters` (var, default, type)               |
| `tests/test_config.py`       | дополнить тестами через `monkeypatch.setenv` + `importlib.reload`          |

**Предусловия (проверь до старта)**:

- В `config/settings.py:4` уже есть `import os`. Добавлять не надо.
- `load_dotenv()` вызывается на строке 9 — env-переменные читаются автоматически.
- `config = AppConfig()` (строка 97) создаёт `TradingConfig` через `field(default_factory=...)`.
  Это значит: `default_factory` зовётся при создании `AppConfig()`, env читается тогда же. OK.
- Для **примитивных** полей (`int`, `float`) `field(default_factory=...)` **не нужен** —
  используй прямое присваивание `ema_fast: int = int(os.getenv(...))`.
  `field(default_factory=...)` нужен только для mutable-дефолтов вроде `List`/`Dict`.

**Пошагово**:

1. Открой `config/settings.py:29-61`.
2. Замени каждое из 20 числовых полей на чтение из `os.getenv(...)` с дефолтом
   (передавай строку, кастуй явно — `int(...)` или `float(...)`):
   ```python
   ema_fast: int = int(os.getenv("EMA_FAST", "9"))
   ema_slow: int = int(os.getenv("EMA_SLOW", "21"))
   ema_trend: int = int(os.getenv("EMA_TREND", "50"))
   rsi_period: int = int(os.getenv("RSI_PERIOD", "14"))
   rsi_overbought: float = float(os.getenv("RSI_OVERBOUGHT", "70"))
   rsi_oversold: float = float(os.getenv("RSI_OVERSOLD", "30"))
   rsi_bull_min: float = float(os.getenv("RSI_BULL_MIN", "50"))
   rsi_bear_max: float = float(os.getenv("RSI_BEAR_MAX", "50"))
   macd_fast: int = int(os.getenv("MACD_FAST", "12"))
   macd_slow: int = int(os.getenv("MACD_SLOW", "26"))
   macd_signal: int = int(os.getenv("MACD_SIGNAL", "9"))
   adx_period: int = int(os.getenv("ADX_PERIOD", "14"))
   adx_min: float = float(os.getenv("ADX_MIN", "20"))
   atr_period: int = int(os.getenv("ATR_PERIOD", "14"))
   atr_multiplier_sl: float = float(os.getenv("ATR_MULTIPLIER_SL", "1.5"))
   atr_multiplier_tp: float = float(os.getenv("ATR_MULTIPLIER_TP", "3.0"))
   supertrend_period: int = int(os.getenv("SUPERTREND_PERIOD", "10"))
   supertrend_multiplier: float = float(os.getenv("SUPERTREND_MULTIPLIER", "3.0"))
   volume_factor: float = float(os.getenv("VOLUME_FACTOR", "1.2"))
   candles_limit: int = int(os.getenv("CANDLES_LIMIT", "200"))
   ```
   Поля `symbols`, `primary_timeframes`, `confirm_timeframe` (строки 31-37) **не трогай** —
   они уже читают env.
3. В `.env.example` добавь блок (значения = текущие дефолты):
   ```
   # Indicator parameters (defaults shown)
   EMA_FAST=9
   EMA_SLOW=21
   EMA_TREND=50
   RSI_PERIOD=14
   RSI_OVERBOUGHT=70
   RSI_OVERSOLD=30
   RSI_BULL_MIN=50
   RSI_BEAR_MAX=50
   MACD_FAST=12
   MACD_SLOW=26
   MACD_SIGNAL=9
   ADX_PERIOD=14
   ADX_MIN=20
   ATR_PERIOD=14
   ATR_MULTIPLIER_SL=1.5
   ATR_MULTIPLIER_TP=3.0
   SUPERTREND_PERIOD=10
   SUPERTREND_MULTIPLIER=3.0
   VOLUME_FACTOR=1.2
   CANDLES_LIMIT=200
   ```
4. В `plan/14-env-config.md` добавь таблицу под заголовком `## Indicator parameters`
   с колонками `Переменная | Дефолт | Тип | Описание` (20 строк).
5. В `tests/test_config.py` (файл уже существует — дополняй, не пересоздавай) добавь:
   ```python
   import importlib
   import pytest


   def test_ema_fast_from_env(monkeypatch):
       monkeypatch.setenv("EMA_FAST", "5")
       import config.settings as settings
       importlib.reload(settings)
       assert settings.config.trading.ema_fast == 5


   def test_atr_multiplier_from_env(monkeypatch):
       monkeypatch.setenv("ATR_MULTIPLIER_SL", "2.5")
       import config.settings as settings
       importlib.reload(settings)
       assert settings.config.trading.atr_multiplier_sl == 2.5


   def test_defaults_when_env_missing(monkeypatch):
       monkeypatch.delenv("EMA_FAST", raising=False)
       import config.settings as settings
       importlib.reload(settings)
       assert settings.config.trading.ema_fast == 9
   ```
   ⚠️ После теста `importlib.reload` другие модули, импортировавшие `config`, увидят
   старую копию. Если в одном файле есть тесты, читающие `config`, добавь
   `importlib.reload(settings)` без monkeypatch в фикстуру `autouse=True` для
   возврата к дефолтам.

**Edge cases**:

- Пустая строка в env (`EMA_FAST=`): `int("")` → `ValueError` на старте. Не лови — это
  конфигурационная ошибка, пусть упадёт.
- Нечисловое значение (`EMA_FAST=abc`): `ValueError`. То же — не лови.
- Бессмысленное сочетание (`RSI_BULL_MIN=80`, `RSI_OVERBOUGHT=70`): код отработает,
  просто условие RSI никогда не сработает. Валидацию **не добавляй** — это user error.

**Готовность**:

- `pytest tests/test_config.py -v` зелёный.
- `pytest -v` целиком зелёный (регрессии не появились).
- В `bot/menu.py:_format_settings` (строка 205) меню «⚙️ Настройки» показывает новые
  значения корректно — никаких правок там не нужно (читает `config.trading.*`).
