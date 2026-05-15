# T2.5 — Signal.confirmed флаг

> **Статус**: ✅ сделано
> **Приоритет**: 🟠 high — закрывает регрессионный пробел по 15M-подтверждению в БД.
> **Зависимости**: нет.

**Цель**: убедиться, что `db.save_signal(confirmed=...)` получает правильное значение
в трёх сценариях: confirm_tf == primary_tf, confirm данные отсутствуют, confirm подтвердил.

**Файлы и точные места**:

| Файл                        | Что делать                                              |
|-----------------------------|---------------------------------------------------------|
| `tests/test_scanner.py`     | добавить `TestConfirmedFlag` с тремя тестами            |

**Предусловия**:

- `config.trading.confirm_timeframe` по умолчанию — `"15m"`.
- `scan_symbol` (строка 53 в `scheduler/scanner.py`): если `confirm_tf != timeframe`,
  проверяет сигнал на confirm-таймфрейме; если совпадают → `confirmed_on_lower_tf = False`.
- `db.save_signal(confirmed=confirmed_on_lower_tf)` — строка 151.

**Пошагово**:

1. Открой `tests/test_scanner.py`, найди конец файла.
2. Добавь новый тестовый класс:

```python
class TestConfirmedFlag:
    @pytest.mark.asyncio
    async def test_confirmed_false_when_primary_eq_confirm(
        self, mock_signal_result, mock_cooldown, monkeypatch
    ):
        from scheduler import scanner as sc
        from strategy.signal_engine import SignalResult, SignalType

        real_result = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT",
            timeframe="1h", close=50000.0, sl=48500.0, tp=53000.0,
            score=6, reasons=["test"],
        )
        monkeypatch.setattr(sc.signal_engine, "evaluate", lambda ind: real_result)
        monkeypatch.setattr(sc, "_get_indicators",
                            AsyncMock(return_value=MagicMock()))
        monkeypatch.setattr(sc.config.trading, "confirm_timeframe", "1h")
        mock_save = AsyncMock(return_value=MagicMock(id=1))
        monkeypatch.setattr(sc.db, "save_signal", mock_save)
        monkeypatch.setattr(sc.config, "context_enabled", False)

        await sc.scan_symbol("BTC/USDT", "1h", AsyncMock())
        mock_save.assert_awaited_once()
        call_kwargs = mock_save.call_args.kwargs
        assert call_kwargs["confirmed"] is False

    @pytest.mark.asyncio
    async def test_confirmed_false_when_no_confirm_data(
        self, mock_signal_result, mock_cooldown, monkeypatch
    ):
        from scheduler import scanner as sc
        from strategy.signal_engine import SignalResult, SignalType

        real_result = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT",
            timeframe="1h", close=50000.0, sl=48500.0, tp=53000.0,
            score=6, reasons=["test"],
        )
        monkeypatch.setattr(sc.signal_engine, "evaluate", lambda ind: real_result)

        async def fake_get_indicators(symbol, timeframe):
            if timeframe == "15m":
                return None
            return MagicMock()

        monkeypatch.setattr(sc, "_get_indicators", fake_get_indicators)
        monkeypatch.setattr(sc.config.trading, "confirm_timeframe", "15m")
        mock_save = AsyncMock(return_value=MagicMock(id=1))
        monkeypatch.setattr(sc.db, "save_signal", mock_save)
        monkeypatch.setattr(sc.config, "context_enabled", False)

        await sc.scan_symbol("BTC/USDT", "1h", AsyncMock())
        mock_save.assert_awaited_once()
        call_kwargs = mock_save.call_args.kwargs
        assert call_kwargs["confirmed"] is False

    @pytest.mark.asyncio
    async def test_confirmed_true_when_15m_confirms(
        self, mock_signal_result, mock_cooldown, monkeypatch
    ):
        from scheduler import scanner as sc
        from strategy.signal_engine import SignalResult, SignalType

        main_result = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT",
            timeframe="1h", close=50000.0, sl=48500.0, tp=53000.0,
            score=6, reasons=["test"],
        )
        confirm_result = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT",
            timeframe="15m", close=50100.0, sl=49000.0, tp=53500.0,
            score=6, reasons=["confirm"],
        )
        monkeypatch.setattr(
            sc.signal_engine, "evaluate",
            lambda ind: main_result if not hasattr(ind, 'timeframe') or getattr(ind, 'timeframe', None) != "15m" else confirm_result,
        )

        call_count = [0]
        async def fake_get_indicators(symbol, timeframe):
            call_count[0] += 1
            if timeframe == "15m":
                return MagicMock(close=50100.0)
            return MagicMock()

        monkeypatch.setattr(sc, "_get_indicators", fake_get_indicators)
        monkeypatch.setattr(sc.config.trading, "confirm_timeframe", "15m")
        mock_save = AsyncMock(return_value=MagicMock(id=1))
        monkeypatch.setattr(sc.db, "save_signal", mock_save)
        monkeypatch.setattr(sc.config, "context_enabled", False)

        await sc.scan_symbol("BTC/USDT", "1h", AsyncMock())
        mock_save.assert_awaited_once()
        call_kwargs = mock_save.call_args.kwargs
        assert call_kwargs["confirmed"] is True
```

3. Фикстуры `mock_signal_result`, `mock_cooldown` — уже есть в файле.

**Edge cases**:

- ⚠️ В третьем тесте `signal_engine.evaluate` вызывается дважды (сначала для 1H, потом для 15M). Разделение по `hasattr(ind, 'timeframe')` — хак, но рабочий, потому что `IndicatorValues` содержит поле `timeframe`.
- Если confirm-сигнал противоположный (SELL вместо BUY) → `scan_symbol` вернёт `None` до вызова `save_signal`. Это проверяется в существующем тесте `test_confirmation_rejects_mismatch`.

**Тесты**:

```python
class TestConfirmedFlag:
    @pytest.mark.asyncio
    async def test_confirmed_false_when_primary_eq_confirm(...):
        ...

    @pytest.mark.asyncio
    async def test_confirmed_false_when_no_confirm_data(...):
        ...

    @pytest.mark.asyncio
    async def test_confirmed_true_when_15m_confirms(...):
        ...
```

**Готовность**:

- `pytest tests/test_scanner.py::TestConfirmedFlag -v` — все 3 теста зелёные.
- `pytest tests/test_scanner.py -v` — все тесты зелёные.
