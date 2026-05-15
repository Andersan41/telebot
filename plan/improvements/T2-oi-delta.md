# T2.1 — OI delta между вызовами

> **Статус**: ✅ сделано
> **Приоритет**: 🟠 high — закрывает регрессионный пробел по OI warm-up (A2).
> **Зависимости**: нет.

**Цель**: убедиться, что `ContextFetcher.fetch_open_interest` корректно кэширует
последнее значение OI per-symbol и считает % дельту между вызовами.

**Файлы и точные места**:

| Файл                        | Что делать                                         |
|-----------------------------|----------------------------------------------------|
| `tests/test_context.py`     | добавить `test_oi_delta_between_calls` в `TestContextFetcher` |

**Предусловия**:

- `aioresponses` уже задействован в проекте (см. другие тесты в `tests/test_context.py`).
- T2.1 — часть более широкой задачи T2, но полностью автономен.

**Пошагово**:

1. Открой `tests/test_context.py`, найди класс `TestContextFetcher` (строка ~245).
2. Добавь новый тестовый метод:

```python
@pytest.mark.asyncio
async def test_oi_delta_between_calls(self, fetcher, aioresponses):
    hist_url = (
        "https://fapi.binance.com/futures/data/openInterestHist"
        "?symbol=BTCUSDT&period=5m&limit=2"
    )
    oi_url = "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT"
    aioresponses.get(hist_url, payload=[
        {"sumOpenInterest": "100.0", "timestamp": 1},
        {"sumOpenInterest": "100.0", "timestamp": 2},
    ])
    aioresponses.get(oi_url, payload={"openInterest": "100.0", "time": 1000})
    aioresponses.get(oi_url, payload={"openInterest": "120.0", "time": 2000})

    first = await fetcher.fetch_open_interest("BTC/USDT")
    second = await fetcher.fetch_open_interest("BTC/USDT")
    await fetcher.close()

    assert first["open_interest"] == 100.0
    assert second["open_interest"] == 120.0
    assert abs(second["open_interest_delta"] - 20.0) < 1e-6
```

3. `fetcher` — уже есть как фикстура на строке ~247.

**Edge cases**:

- ⚠️ Если A2 (warm-up) не сделан — `hist_url` заглушка не вызовется, и `first["open_interest_delta"]` будет `0.0`. В этом случае адаптируй ассерт: `assert first["open_interest_delta"] == 0.0`.
- Второй вызов `fetch_open_interest` **не должен** дергать `hist_url` — символ уже в `_last_oi`.

**Тесты**:

```python
@pytest.mark.asyncio
async def test_oi_delta_between_calls(self, fetcher, aioresponses):
    # ... код выше ...
```

**Готовность**:

- `pytest tests/test_context.py::TestContextFetcher::test_oi_delta_between_calls -v` — зелёный.
- `pytest tests/test_context.py -v` — все тесты зелёные.
