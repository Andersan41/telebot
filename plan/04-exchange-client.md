# 2.4 data/exchange_client.py — Клиент биржи

**Что делает:**
- `connect()` — создаёт ccxt асинхронный exchange через `getattr(ccxt, config.exchange.name)`
  (имя биржи берётся из env `EXCHANGE`, дефолт `binance`). Опции: `enableRateLimit=True`,
  `defaultType=spot` (`exchange_client.py:22-23`). Для futures-OHLCV нужно менять
  `defaultType` — см. F2 в `plan/improvements/F2-futures-ohlcv.md`.
- `close()` — закрывает соединение
- `fetch_ohlcv(symbol, timeframe, limit)` — получает OHLCV, конвертирует в pd.DataFrame с колонками `timestamp, open, high, low, close, volume`
  - timestamp → datetime UTC (index)
  - dropna, astype(float)
  - **Удаляет последнюю (незакрытую) свечу** (`df.iloc[:-1]`)
  - Обрабатывает `ccxt.NetworkError`, `ccxt.ExchangeError`, общие исключения
  - Возвращает `None` при ошибке или пустых данных
- `fetch_all_symbols(timeframe, limit)` — запускает `fetch_ohlcv` для всех символов параллельно
  через `asyncio.gather(..., return_exceptions=True)`. Per-symbol исключения отфильтровываются:
  упавшие символы молча исключаются из результата.
  - Возвращает `dict[symbol → DataFrame]`; при тотальном провале — пустой dict (не `None`)

**При каких условиях:**
- `connect()` — на старте main.py
- `close()` — при shutdown
- `fetch_ohlcv()` — вызывается scheduler/scanner и menu при анализе
