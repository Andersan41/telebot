# T2.3 — MIN_VERDICT гейт в scan_symbol

> **Статус**: ✅ сделано
> **Приоритет**: 🟠 high — закрывает регрессионный пробел по ранговому гейту контекста.
> **Зависимости**: нет.

**Цель**: убедиться, что `scan_symbol` блокирует сигнал, если контекстный вердикт
ниже настроенного `CONTEXT_MIN_VERDICT`.

**Файлы и точные места**:

| Файл                        | Что делать                                              |
|-----------------------------|---------------------------------------------------------|
| `tests/test_scanner.py`     | добавить `TestMinVerdictGate` с двумя тестами           |

**Предусловия**:

- `_VERDICT_RANK = {"BLOCKED": 0, "CONFLICTED": 1, "WEAK": 2, "CONFIRMED": 3}` — порядок вердиктов.
- `_verdict_passes_min` (строка 21) сравнивает фактический вердикт с `config.context_min_verdict`.
- `context_min_verdict` по умолчанию — `"WEAK"`.

**Пошагово**:

1. Открой `tests/test_scanner.py`, найди конец файла.
2. Добавь новый тестовый класс:

```python
class TestMinVerdictGate:
    @pytest.mark.asyncio
    async def test_scan_blocks_on_below_min_verdict(
        self, mock_signal_result, mock_cooldown, monkeypatch
    ):
        from scheduler import scanner as sc
        from context.scorer import ContextVerdict

        fake_result = MagicMock(
            is_actionable=True,
            signal=MagicMock(value="BUY"),
            reasons=[],
            close=100.0,
        )
        monkeypatch.setattr(sc.signal_engine, "evaluate", lambda ind: fake_result)
        monkeypatch.setattr(
            sc, "_get_indicators",
            AsyncMock(return_value=MagicMock()),
        )
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

    @pytest.mark.asyncio
    async def test_scan_passes_when_verdict_meets_min(
        self, mock_signal_result, mock_cooldown, monkeypatch
    ):
        from scheduler import scanner as sc
        from context.scorer import ContextVerdict
        from strategy.signal_engine import SignalResult, SignalType

        real_result = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT",
            timeframe="1h", close=50000.0, sl=48500.0, tp=53000.0,
            score=6, reasons=["test"],
        )
        monkeypatch.setattr(sc.signal_engine, "evaluate", lambda ind: real_result)
        monkeypatch.setattr(
            sc, "_get_indicators",
            AsyncMock(return_value=MagicMock()),
        )
        monkeypatch.setattr(
            sc.context_scorer, "score",
            lambda direction, snap: ContextVerdict(
                verdict="WEAK", confidence=0.15, score=0.15,
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
        assert result is not None
        cb.assert_awaited()
```

3. Фикстуры `mock_signal_result`, `mock_cooldown` — уже есть в файле.

**Edge cases**:

- ⚠️ `mock_signal_result` возвращает `SignalResult` с `signal=SignalType.BUY`. В первом тесте контекст `CONFLICTED` < `WEAK` → сигнал должен заблокироваться.
- Во втором тесте контекст `WEAK` == `WEAK` → сигнал должен пройти.
- `context_min_verdict = ""` (пустая строка) → гейт отключён, `_verdict_passes_min` возвращает `True`.

**Тесты**:

```python
class TestMinVerdictGate:
    @pytest.mark.asyncio
    async def test_scan_blocks_on_below_min_verdict(...):
        ...

    @pytest.mark.asyncio
    async def test_scan_passes_when_verdict_meets_min(...):
        ...
```

**Готовность**:

- `pytest tests/test_scanner.py::TestMinVerdictGate -v` — оба теста зелёные.
- `pytest tests/test_scanner.py -v` — все тесты зелёные.
