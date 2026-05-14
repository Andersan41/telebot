# 6. Конфигурация .env (полный список)

```env
# Обязательные
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_ID=
SYMBOLS=BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT,XRP/USDT
PRIMARY_TIMEFRAMES=1h,4h
BINANCE_API_KEY=
BINANCE_API_SECRET=

# Опциональные
EXCHANGE=binance
USE_TESTNET=false
TELEGRAM_ADMIN_IDS=123456789
CONFIRM_TIMEFRAME=15m
DATABASE_URL=sqlite+aiosqlite:///./data/signals.db
LOG_LEVEL=INFO
LOG_FILE=logs/bot.log
SIGNAL_COOLDOWN_MINUTES=60

# Контекстный модуль
CONTEXT_ENABLED=true
CONTEXT_MIN_VERDICT=WEAK
CONTEXT_BLOCK_ON_BLOCKED=true
CRYPTOPANIC_API_KEY=
COINGECKO_SYMBOL_MAP=BTC/USDT:bitcoin,ETH/USDT:ethereum,SOL/USDT:solana,BNB/USDT:binance-coin,XRP/USDT:ripple
```

## Indicator parameters

| Переменная              | Дефолт | Тип   | Описание                              |
|-------------------------|--------|-------|---------------------------------------|
| EMA_FAST                | 9      | int   | Быстрая EMA                           |
| EMA_SLOW                | 21     | int   | Медленная EMA                         |
| EMA_TREND               | 50     | int   | Трендовая EMA                         |
| RSI_PERIOD              | 14     | int   | Период RSI                            |
| RSI_OVERBOUGHT          | 70     | float | Зона перекупленности RSI              |
| RSI_OVERSOLD            | 30     | float | Зона перепроданности RSI              |
| RSI_BULL_MIN            | 50     | float | Минимальный RSI для BUY               |
| RSI_BEAR_MAX            | 50     | float | Максимальный RSI для SELL             |
| MACD_FAST               | 12     | int   | Быстрая MACD                          |
| MACD_SLOW               | 26     | int   | Медленная MACD                          |
| MACD_SIGNAL             | 9      | int   | Signal line MACD                      |
| ADX_PERIOD              | 14     | int   | Период ADX                            |
| ADX_MIN                 | 20     | float | Минимальный ADX (фильтр флэта)        |
| ATR_PERIOD              | 14     | int   | Период ATR                            |
| ATR_MULTIPLIER_SL       | 1.5    | float | Множитель для Stop Loss               |
| ATR_MULTIPLIER_TP       | 3.0    | float | Множитель для Take Profit             |
| SUPERTREND_PERIOD       | 10     | int   | Период Supertrend                     |
| SUPERTREND_MULTIPLIER   | 3.0    | float | Множитель Supertrend                  |
| VOLUME_FACTOR           | 1.2    | float | Мультпликатор для фильтра объёма      |
| CANDLES_LIMIT           | 200    | int   | Количество свечей для загрузки        |
