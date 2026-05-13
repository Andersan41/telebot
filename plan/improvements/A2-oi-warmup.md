# A2. OI delta переживает рестарт

> **Статус**: 🔴 не сделано
> **Приоритет**: 🟡 medium — улучшает качество сигналов с самого первого скана.
> **Зависимости**: нет. Связано с [A3](A3-oi-scoring-direction.md) (OI scoring) и
> [T2](T2-tests.md) (тест по этой задаче).

**Цель**: сейчас при старте процесса первая дельта = 0.0, потому что `_last_oi` пустой
(см. `context/fetcher.py:26`). Подтянуть последние 2 точки из исторического эндпоинта Binance,
чтобы первая дельта была осмысленной.

**Файлы и точные места**:

| Файл                         | Что делать                                      |
|------------------------------|-------------------------------------------------|
| `context/fetcher.py:155-189` | дополнить `fetch_open_interest` warm-up-логикой |
| `tests/test_context.py`      | добавить тест на дельту при warm-up             |

**Эндпоинт**:

```
GET https://fapi.binance.com/futures/data/openInterestHist
    ?symbol=BTCUSDT&period=5m&limit=2
```

Ответ — JSON-массив с двумя элементами; берём `[-2]["sumOpenInterest"]` как «previous».
Пример: `[{"symbol":"BTCUSDT","sumOpenInterest":"82345.12","timestamp":1700000000000}, {...}]`.

**Пошагово**:

1. В `context/fetcher.py:155-189` (метод `fetch_open_interest`) **перед** строкой
   `current = float(data.get("openInterest", 0))` (строка 171) добавь условный warm-up:
   ```python
   # Warm-up: при первом запросе для символа подтянем предыдущее значение
   # из исторического эндпоинта, чтобы delta уже на первом скане была осмысленной.
   if symbol not in self._last_oi:
       try:
           hist_url = (
               f"https://fapi.binance.com/futures/data/openInterestHist"
               f"?symbol={binance_symbol}&period=5m&limit=2"
           )
           async with session.get(hist_url) as hist_resp:
               if hist_resp.status == 200:
                   hist = await hist_resp.json()
                   if isinstance(hist, list) and len(hist) >= 2:
                       self._last_oi[symbol] = float(hist[-2]["sumOpenInterest"])
                       logger.debug(f"OI warm-up {symbol}: prev={self._last_oi[symbol]}")
       except Exception as e:
           logger.warning(f"OI warm-up failed for {symbol}: {e}")
   ```
2. **Не меняй** строки 171-177 (`current = ...`, `previous = self._last_oi.get(symbol)`,
   расчёт `delta_pct`, `self._last_oi[symbol] = current`). После шага 1
   `self._last_oi[symbol]` уже будет проставлен → дальнейший код посчитает дельту относительно
   него и сразу же перезапишет на текущее.
3. **Не вызывай warm-up каждый раз** — условие `if symbol not in self._last_oi` гарантирует,
   что он отработает один раз за процесс.

**Контракт**: возвращаемый dict **не меняется**:
`{open_interest: float, open_interest_delta: float, timestamp: datetime}`.

**Edge cases**:

- `openInterestHist` лимитирован (300 req/5min на public). Один раз за символ за процесс — OK.
- Эндпоинт вернул `< 2` точек или пустой массив → пропусти warm-up,
  оставь `delta_pct = 0.0` (фолбэк к старому поведению).
- Сеть упала на warm-up → `try/except` ловит, лог `WARNING`, не пробрасывай. Главный запрос
  на `/fapi/v1/openInterest` ниже должен отработать независимо.
- Символ редкий и hist возвращает 404 → status != 200 → warm-up пропускается, `delta_pct = 0.0`.

**Тест** (`tests/test_context.py`, в `TestContextFetcher`):

```python
import pytest
from aioresponses import aioresponses


@pytest.mark.asyncio
async def test_oi_warmup_uses_historical(monkeypatch):
    from context.fetcher import ContextFetcher
    fetcher = ContextFetcher()
    with aioresponses() as m:
        m.get(
            "https://fapi.binance.com/futures/data/openInterestHist"
            "?symbol=BTCUSDT&period=5m&limit=2",
            payload=[
                {"symbol": "BTCUSDT", "sumOpenInterest": "100.0", "timestamp": 1},
                {"symbol": "BTCUSDT", "sumOpenInterest": "120.0", "timestamp": 2},
            ],
        )
        m.get(
            "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT",
            payload={"openInterest": "110.0", "symbol": "BTCUSDT", "time": 3000},
        )
        result = await fetcher.fetch_open_interest("BTC/USDT")
        await fetcher.close()
    # warm-up взял previous = 100.0 (hist[-2]); текущее 110.0; delta = +10%
    assert result is not None
    assert result["open_interest"] == 110.0
    assert abs(result["open_interest_delta"] - 10.0) < 1e-6
```

**Готовность**:

- `pytest tests/test_context.py -v` — новый тест зелёный, старые не сломались.
- Ручная проверка: запусти бот, при первом скане в логах должна быть строка
  `OI BTC/USDT: <число> (Δ +X.XX%)` где `X.XX != 0.00`.
- Sanity check вручную:
  `curl 'https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=5m&limit=2'`.
