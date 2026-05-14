# T2. Тесты на свежие правки

> **Статус**: ✅ сделано
> **Приоритет**: 🟠 high — закрывает регрессионные пробелы по уже внесённым изменениям.
> **Зависимости**: тест №1 (OI delta) идеально работает после [A2](A2-oi-warmup.md);
> без A2 нужно адаптировать ассерт (см. ⚠️ внутри).

**Цель**: покрыть тестами правки, уже принятые в этой/прошлых сессиях, и закрыть пробелы.

**Файлы**: `tests/test_context.py`, `tests/test_scanner.py`.

**Предусловия**:

- `aioresponses` уже задействован в проекте (см. другие тесты в `tests/test_context.py`).
- Все тесты — async, требуют `@pytest.mark.asyncio` и `pytest-asyncio` в зависимостях.

**Подзадачи (каждая — отдельный тест)**:

1. **OI delta — стандартный путь** (`tests/test_context.py::TestContextFetcher`):
   ```python
   @pytest.mark.asyncio
   async def test_oi_delta_between_calls():
       from context.fetcher import ContextFetcher
       fetcher = ContextFetcher()
       url = "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT"
       hist_url = (
           "https://fapi.binance.com/futures/data/openInterestHist"
           "?symbol=BTCUSDT&period=5m&limit=2"
       )
       with aioresponses() as m:
           # Первый вызов: warm-up через hist (см. A2) + текущее значение
           m.get(hist_url, payload=[
               {"sumOpenInterest": "100.0", "timestamp": 1},
               {"sumOpenInterest": "100.0", "timestamp": 2},
           ])
           m.get(url, payload={"openInterest": "100.0", "time": 1000})
           # Второй вызов: hist уже не дёргается (symbol in _last_oi)
           m.get(url, payload={"openInterest": "120.0", "time": 2000})

           first = await fetcher.fetch_open_interest("BTC/USDT")
           second = await fetcher.fetch_open_interest("BTC/USDT")
           await fetcher.close()

       assert first["open_interest"] == 100.0
       assert second["open_interest"] == 120.0
       assert abs(second["open_interest_delta"] - 20.0) < 1e-6
   ```
   ⚠️ Если **A2 не сделан** — убери `m.get(hist_url, ...)` и ожидай `first["open_interest_delta"] == 0.0`.

2. **News aggregation** (`tests/test_context.py::TestContextEngine`): проверить взвешенное
   усреднение CryptoPanic + RSS:
   ```python
   @pytest.mark.asyncio
   async def test_news_sentiment_aggregation(monkeypatch):
       from context.analyzer import context_engine

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
       # Заглушить остальные источники, чтобы не лезть в сеть
       for fn in ["fetch_fear_greed", "fetch_coingecko", "fetch_trending",
                  "fetch_funding_rate", "fetch_open_interest",
                  "fetch_long_short_ratio"]:
           monkeypatch.setattr(
               f"context.analyzer.context_fetcher.{fn}",
               lambda *a, **kw: _async_none(),
           )

       snap = await context_engine.get_snapshot("BTC/USDT")
       # weighted: (-0.5*10 + 0.3*5) / 15 = -0.2333...
       assert abs(snap.news_sentiment_score - (-7 / 30)) < 1e-3
   ```
   `_async_none()` — хелпер, возвращающий awaitable `None`:
   ```python
   async def _async_none():
       return None
   ```
   ⚠️ Точные имена `fetch_*` сверь по `context/analyzer.py`. Возможно у вас агрегация
   уже считает по-другому — ассерт настрой под фактическую формулу из кода.

3. **MIN_VERDICT гейт** (`tests/test_scanner.py::TestScanSymbol`):
   ```python
   @pytest.mark.asyncio
   async def test_scan_blocks_on_below_min_verdict(monkeypatch):
       from scheduler import scanner as sc
       from context.scorer import ContextVerdict

       # Сигнал actionable
       fake_result = MagicMock(is_actionable=True, signal=MagicMock(value="BUY"),
                               reasons=[], close=100.0)
       monkeypatch.setattr(sc.signal_engine, "evaluate", lambda ind: fake_result)
       monkeypatch.setattr(sc, "_get_indicators",
                           AsyncMock(return_value=MagicMock()))
       # Контекст: CONFLICTED < WEAK
       monkeypatch.setattr(
           sc.context_scorer, "score",
           lambda direction, snap: ContextVerdict(
               verdict="CONFLICTED", confidence=0.05, score=0.0,
           ),
       )
       monkeypatch.setattr(
           sc.context_engine, "get_snapshot",
           AsyncMock(return_value=MagicMock()),
       )
       monkeypatch.setattr(sc.config, "context_min_verdict", "WEAK")
       monkeypatch.setattr(sc.config, "context_enabled", True)

       cb = AsyncMock()
       result = await sc.scan_symbol("BTC/USDT", "1h", cb)
       assert result is None
       cb.assert_not_awaited()
   ```

4. **Funding rate** (`tests/test_context.py::TestContextFetcher`):
   ```python
   @pytest.mark.asyncio
   async def test_funding_rate_parses_negative():
       from context.fetcher import ContextFetcher
       fetcher = ContextFetcher()
       url = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
       with aioresponses() as m:
           m.get(url, payload={"lastFundingRate": "-0.0042"})
           result = await fetcher.fetch_funding_rate("BTC/USDT")
           await fetcher.close()
       assert result == pytest.approx(-0.0042)
   ```

5. **`Signal.confirmed`** (`tests/test_scanner.py::TestConfirmedFlag`):
   - Случай 1: `confirm_tf == primary_tf` → `db.save_signal(confirmed=False)`.
   - Случай 2: 15M-данные `None` → `db.save_signal(confirmed=False)`.
   - Случай 3: 15M подтверждает → `db.save_signal(confirmed=True)`.

   Шаблон:
   ```python
   @pytest.mark.asyncio
   async def test_confirmed_flag_when_primary_eq_confirm(monkeypatch):
       from scheduler import scanner as sc
       monkeypatch.setattr(sc.config.trading, "confirm_timeframe", "1h")
       # ... setup actionable signal ...
       mock_save = AsyncMock(return_value=MagicMock(id=1))
       monkeypatch.setattr(sc.db, "save_signal", mock_save)
       monkeypatch.setattr(sc.config, "context_enabled", False)
       await sc.scan_symbol("BTC/USDT", "1h", AsyncMock())
       mock_save.assert_awaited_once()
       assert mock_save.call_args.kwargs["confirmed"] is False
   ```

**Готовность**:

- `pytest tests/test_context.py tests/test_scanner.py -v` — все тесты зелёные.
- Покрытие свежих фич не оставлено пробелом (визуально проверить
  `pytest --collect-only | grep -E 'news_sentiment|min_verdict|funding|confirmed'`).
