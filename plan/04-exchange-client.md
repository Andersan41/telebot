# 2.4 data/exchange_client.py — Клиент биржи

**Что делает:**
- `connect()` — создаёт ccxt асинхронный exchange (Binance spot)
- `close()` — закрывает соединение
- `fetch_ohlcv(symbol, timeframe, limit)` — получает OHLCV, конвертирует в pd.DataFrame с колонками `timestamp, open, high, low, close, volume`
  - timestamp → datetime UTC (index)
  - dropna, astype(float)
  - **Удаляет последнюю (незакрытую) свечу** (`df.iloc[:-1]`)
  - Обрабатывает `ccxt.NetworkError`, `ccxt.ExchangeError`, общие исключения
- `fetch_all_symbols(timeframe, limit)` — запускает `fetch_ohlcv` для всех символов параллельно через `asyncio.gather`
  - Возвращает `dict[symbol → DataFrame]`

**При каких условиях:**
- `connect()` — на старте main.py
- `close()` — при shutdown
- `fetch_ohlcv()` — вызывается scheduler/scanner и menu при анализе
- Возвращает `None` при ошибке или пустых данных
