# T2.4 — Funding rate парсинг отрицательного значения

> **Статус**: ✅ сделано
> **Приоритет**: 🟠 high — закрывает регрессионный пробел по funding rate API.
> **Зависимости**: нет.

**Цель**: убедиться, что `ContextFetcher.fetch_funding_rate` корректно парсит
отрицательные значения funding rate (шорт-трейдеры платят лонг).

**Файлы и точные места**:

| Файл                        | Что делать                                              |
|-----------------------------|---------------------------------------------------------|
| `tests/test_context.py`     | добавить `test_funding_rate_parses_negative` в `TestContextFetcher` |

**Предусловия**:

- `aioresponses` уже задействован в проекте.
- `fetch_funding_rate` (строка 128 в `context/fetcher.py`) парсит `lastFundingRate` из JSON.

**Пошагово**:

1. Открой `tests/test_context.py`, найди класс `TestContextFetcher` (строка ~245).
2. Добавь новый тестовый метод:

```python
@pytest.mark.asyncio
async def test_funding_rate_parses_negative(self, fetcher, aioresponses):
    url = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
    aioresponses.get(url, payload={"lastFundingRate": "-0.0042"})
    result = await fetcher.fetch_funding_rate("BTC/USDT")
    await fetcher.close()
    assert result == pytest.approx(-0.0042)
```

3. `fetcher` — уже есть как фикстура на строке ~247.

**Edge cases**:

- ⚠️ Binance возвращает `lastFundingRate` как строку (например `"-0.0042"`), а не число. Код делает `float(...)`, но если API вернёт `null` — будет `TypeError`. Убедись, что заглушка `aioresponses` возвращает строку.
- Положительное значение (`"0.0001"`) — проверь отдельно, если нужно.

**Тесты**:

```python
@pytest.mark.asyncio
async def test_funding_rate_parses_negative(self, fetcher, aioresponses):
    # ... код выше ...
```

**Готовность**:

- `pytest tests/test_context.py::TestContextFetcher::test_funding_rate_parses_negative -v` — зелёный.
- `pytest tests/test_context.py -v` — все тесты зелёные.
