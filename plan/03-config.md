# 2.2 config/settings.py — Конфигурация

**Что делает:**
- Загружает `.env` через `python-dotenv`
- Маппит переменные окружения в dataclasses: `TelegramConfig`, `ExchangeConfig`, `TradingConfig`, `AppConfig`
- `AppConfig` — обёртка со всеми конфигами + database_url, log_level, signal_cooldown_minutes
- Предоставляет синглтон `config = AppConfig()`
- Парсит `COINGECKO_SYMBOL_MAP` (строка вида `BTC/USDT:bitcoin,ETH/USDT:ethereum`) в словарь

**Настраиваемые параметры:**
- Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`, `TELEGRAM_ADMIN_IDS`
- Exchange: `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `USE_TESTNET`, `EXCHANGE`
- Trading: `SYMBOLS`, `PRIMARY_TIMEFRAMES`, `CONFIRM_TIMEFRAME`
- Индикаторы: `ema_fast/slow/trend`, `rsi_period/overbought/oversold/bull_min/bear_max`, `macd_fast/slow/signal`, `adx_period/min`, `atr_period/multiplier_sl/multiplier_tp`, `supertrend_period/multiplier`, `volume_factor`, `candles_limit`
- Context: `CONTEXT_ENABLED`, `CONTEXT_MIN_VERDICT`, `CONTEXT_BLOCK_ON_BLOCKED`, `CRYPTOPANIC_API_KEY`, `COINGECKO_SYMBOL_MAP`
- Прочее: `DATABASE_URL`, `LOG_LEVEL`, `LOG_FILE`, `SIGNAL_COOLDOWN_MINUTES`

**При каких условиях:**
- На старте при импорте `config.settings`
- Если не заданы обязательные переменные — используются дефолты (токен будет пустым → main.py упадёт)

---

# 2.3 config/logger.py — Логирование

**Что делает:**
- Настраивает loguru: цветной вывод в консоль + файл с ротацией и сжатием
- Формат: `timestamp | level | module:line - message`

**При каких условиях:**
- Выполняется при импорте (нет явного вызова)
