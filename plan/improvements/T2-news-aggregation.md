# T2.2 — News sentiment aggregation

> **Статус**: ✅ сделано
> **Приоритет**: 🟠 high — закрывает регрессионный пробел по взвешенному усреднению news.
> **Зависимости**: нет.

**Цель**: убедиться, что `ContextEngine.get_snapshot` корректно агрегирует
sentiment от CryptoPanic и RSS в один `news_sentiment_score`, взвешенный по количеству статей.

**Файлы и точные места**:

| Файл                        | Что делать                                              |
|-----------------------------|---------------------------------------------------------|
| `tests/test_context.py`     | добавить `test_news_sentiment_aggregation` в `TestContextEngine` |

**Предусловия**:

- `monkeypatch` — встроенная фикстура pytest.
- `context.analyzer.context_fetcher` — модуль, в котором живут `fetch_cryptopanic` и `fetch_rss_news`.
- Формула агрегации из `context/analyzer.py:94-97`:
  ```python
  total_count = sum(c for _, c in news_collected) or 1
  snapshot.news_sentiment_score = sum(s * c for s, c in news_collected) / total_count
  ```

**Пошагово**:

1. Открой `tests/test_context.py`, найди класс `TestContextEngine` (строка ~473).
2. Добавь новый тестовый метод:

```python
@pytest.mark.asyncio
async def test_news_sentiment_aggregation(self, engine, monkeypatch):
    async def _async_none(*args, **kwargs):
        return None

    async def fake_cp(symbol):
        return {"score": -0.5, "count": 10, "positive": 2, "negative": 7}

    async def fake_rss(symbol):
        return {"score": 0.3, "count": 5, "positive": 4, "negative": 1}

    monkeypatch.setattr(
        "context.analyzer.context_fetcher.fetch_cryptopanic", fake_cp
    )
    monkeypatch.setattr(
        "context.analyzer.context_fetcher.fetch_rss_news", fake_rss
    )
    for fn in ["fetch_fear_greed", "fetch_coingecko", "fetch_trending",
               "fetch_funding_rate", "fetch_open_interest",
               "fetch_long_short_ratio"]:
        monkeypatch.setattr(
            f"context.analyzer.context_fetcher.{fn}",
            _async_none,
        )
    monkeypatch.setattr("context.analyzer.config.cryptopanic_api_key", "test_key")

    snap = await engine.get_snapshot("BTC/USDT")
    # weighted: (-0.5*10 + 0.3*5) / 15 = -0.2333...
    assert abs(snap.news_sentiment_score - (-7 / 30)) < 1e-3
```

3. `engine` — уже есть как фикстура на строке ~476.

**Edge cases**:

- ⚠️ Если CryptoPanic API key пустой — `fetch_cryptopanic` не вызовется, в `news_collected` будет только RSS. Ассерт сломается — настрой под фактическую формулу.
- Точные имена `fetch_*` сверь по `context/analyzer.py`. Если агрегация уже считает по-другому — адаптируй ассерт.

**Тесты**:

```python
@pytest.mark.asyncio
async def test_news_sentiment_aggregation(self, engine, monkeypatch):
    # ... код выше ...
```

**Готовность**:

- `pytest tests/test_context.py::TestContextEngine::test_news_sentiment_aggregation -v` — зелёный.
- `pytest tests/test_context.py -v` — все тесты зелёные.
