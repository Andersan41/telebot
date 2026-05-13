# F2. Поддержка futures для OHLCV

> **Статус**: 🔴 не сделано
> **Приоритет**: 🟢 low — новая функциональность для futures-стратегий.
> **Зависимости**: нет.

**Цель**: сейчас ccxt-клиент создан с `defaultType=spot` (`data/exchange_client.py:23`).
Для futures-стратегий нужен либо отдельный инстанс, либо переключаемый флаг.

**Файлы и точные места**:

| Файл                              | Что делать                                       |
|-----------------------------------|--------------------------------------------------|
| `config/settings.py:21-27`        | добавить поле `market_type` в `ExchangeConfig`   |
| `data/exchange_client.py:16-25`   | пробросить `defaultType` из конфига              |
| `.env.example`                    | добавить `MARKET_TYPE=spot`                      |
| `plan/14-env-config.md`           | задокументировать переменную                     |

**Пошагово**:

1. В `config/settings.py` в `@dataclass class ExchangeConfig` (строки 21-27) добавь поле:
   ```python
   market_type: str = os.getenv("MARKET_TYPE", "spot")  # spot | future
   ```
2. В `data/exchange_client.py:16-25` (метод `connect`) измени строку 23:
   ```python
   "options": {"defaultType": config.exchange.market_type},
   ```
3. В `.env.example` добавь:
   ```
   # Тип рынка для OHLCV (spot | future).
   # ⚠️ Funding rate / OI / L-S всегда читаются с fapi.binance.com независимо от этой настройки.
   MARKET_TYPE=spot
   ```
4. В `plan/14-env-config.md` под секцией `EXCHANGE` добавь строку про `MARKET_TYPE`.

**Edge cases**:

- Не все символы из `SYMBOLS` существуют на futures — `fetch_ohlcv` вернёт `None`, ничего
  страшного. В логах будет `Exchange error`.
- Funding rate / OI / Long-Short — это всегда USDT-M futures независимо от `MARKET_TYPE`
  (см. `context/fetcher.py:138, 165, 199` — там захардкожен `fapi.binance.com`).
  Это **намеренно** — спот-контекст для них бессмысленен. Не путай пользователя.
- ccxt при `defaultType=future` шлёт запросы на другой эндпоинт (`fapi`), цены будут отличаться
  от спот-цен. Это ожидаемо и нормально для futures-стратегий.

**Готовность**:

- С `MARKET_TYPE=spot` (default) — ничего не сломалось, `pytest -v` зелёный.
- С `MARKET_TYPE=future` — на старте лог `Exchange client created: binance`,
  `fetch_ohlcv` возвращает данные. Sanity:
  `python -c "import asyncio; from data.exchange_client import exchange_client; \
   async def main(): \
       await exchange_client.connect(); \
       df = await exchange_client.fetch_ohlcv('BTC/USDT', '1h', 5); \
       print(df); \
       await exchange_client.close(); \
   asyncio.run(main())"`.
