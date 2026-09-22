# bot_fix_v1.3.md — Senior model audit

## Date: 2026-09-19
## Auditor: GPT-6 (Codex), independent parallel code review
## Branch: feat/htf-bias-v2-premium-discount
## Config version: 10 (значение в исходниках; runtime не подтверждён)

Исходный репозиторий: https://github.com/Andersan41/telebot. Проверенный commit: `24d3ef0c82bcebcf0c52222cf1c7a4f1e132491a`. Отчёт подготовлен в отдельном форке https://github.com/vaemavalec/telebot, ветка `codex/senior-review-v1.3`. Номера строк относятся к исходному commit. Это аудит с инструкциями для mimo: предлагаемые изменения production-кода не применены.

---

## I. Executive summary

Нулевой поток сигналов нельзя объяснять только строгостью параметров. В `RiskEngine.evaluate()` подтверждён `NameError`: аргумент называется `entry_price`, но проверка геометрии использует `entry`. Любой кандидат, дошедший до этой проверки с допустимым портфелем и положительными ценами, завершает расчёт исключением. Одновременно `PatternEngine` возвращает разворот без MSS как `detected=True, direction=None`: продолжение уже не проверяется, а результат превращается в общий `no valid setup`. Ещё одна ошибка — несогласованная семантика направления sweep при классификации MSS. Эти дефекты нужно исправлять до экспериментов с порогами.

Данные задания не соответствуют одному неизменному запуску проверенного кода. `components_count` и `confirmation_score` — разные величины. При текущем `detect()` любой успешный reversal содержит минимум Sweep+MSS, а continuation — Trend+BOS; следовательно, `score_too_low` при фактическом пороге 2 здесь недостижим. Кроме того, фильтр читает `config.trading.min_score_for_signal`, хотя настройка находится в `config.scoring`. Исполняемых вызовов `TIME_OF_DAY_BLOCKED` в ветке нет. Семидневную агрегированную таблицу нельзя автоматически приписывать HEAD или config v10; необходимы отдельные интервалы, runtime-версия и первичные записи.

Устранение ошибок восстановит возможность прохода конвейера, но не доказывает появление 2–5 качественных сигналов в неделю и не даёт гарантии отсутствия ложных сигналов. Для оценки нужен последовательный replay на закрытых свечах с одинаковыми данными и всеми последующими фильтрами. Три исправления из раздела «Fixes applied» v1.2 проверены и не повторяются как открытые проблемы: источник `reclaim_bars` в `classify_choch`, удаление SL-cap 8%, удаление `block_neutral_htf`.

### Прямые ответы на вопросы задания

**1. Score gate.** Сейчас `components_count = len(components_found)`. Reversal: по 1 за Sweep, Displacement, MSS; continuation: по 1 за Trend и BOS. Обоим добавляются OB, FVG, EntryArmed, каждый по 1. Это счётчик, а не взвешенная оценка; EntryArmed частично повторяет наличие/близость зоны. «BOS-only continuation = 1» относится к старой логике: в HEAD это Trend+BOS = 2. Текущая формула `confirmation_score = 2*has_bos + has_fvg + has_ob`, одинаковая для обоих типов; ни Sweep, ни MSS, ни Trend не добавляют баллов. Поэтому reversal Sweep+MSS имеет confirmation=0, с одной зоной =1, с OB+FVG =2. Текст сообщения scanner о Sweep=2/MSS=1 не является реализацией. Рекомендация: оставить `MIN_SCORE_FOR_SIGNAL=2`, исправить чтение настройки, восстановить и измерить согласованную логику confirmation. Снижение до 1 не устраняет причины нуля.

**2. Time of day / сервер.** В HEAD код выключен комментариями; другой активный writer этого reason code не найден. Обычный маршрут `main.py → TaskScheduler → run_scan_cycle → scan_symbol_v2`; наличие `core_v2.py` само по себе не означает второй запущенный scanner. Пользователь подтвердил, что сервер принадлежит товарищу и доступа к нему нет. Поэтому соответствие живого процесса репозиторию **не проверено**, а не «подтверждено» и не «опровергнуто». Ни форк, ни локальный clone не дают доступа к runtime. Ниже приложена воспроизводимая процедура проверки для владельца.

**3. Pattern thresholds.** `no valid setup` здесь не доказывает отсутствие рыночной формации: это также результат ошибочного `detected=True` без направления. При отсутствии пригодного sweep пробуется continuation: нужны structure, trend != ranging, BOS, корректное сравнение BOS с предшествующим swing и совпадение BOS/trend. При наличии sweep без MSS текущий код до continuation не доходит. `max_causal_bars=10` — 10 часов на 1h и 40 часов на 4h, а не 10 минут; этот аргумент сейчас задаётся значением по умолчанию в `classify_choch`, не переменной `.env`. Значение 0.2 — порог MSS displacement/ATR, а не порог `CandleQuality.is_displacement`: последний использует range/ATR и по умолчанию множитель 1.5. Scanner при `reversal_require_displacement=True` дополнительно требует displacement последней свечи; это отдельное условие. Без распределений причин по setup/timeframe пороги нельзя объявить чрезмерными. Сначала исправить причинную привязку, затем сравнить на replay 10/15/20 баров и альтернативную политику displacement, не меняя live-конфиг сразу.

**4. Каскад и реалистичный объём.** Сумма десяти приведённых stage-счётчиков = 73 019, остаток до 77 253 = 4 234. Таблица неполна либо использует иной знаменатель; причины и стадии — разные группировки одних и тех же событий, складывать их нельзя. Уже 16 084 отказа на score доказывали бы, что часть кандидатов прошла pattern, если строки принадлежат одной последовательной воронке: «pattern пропускает 0%» не следует из нуля отправок. Расчёт `77 253 × 0.30 × 0.80 × 0.90 × 0.95 = 15 852.3156` — арифметика с произвольными условными вероятностями, не прогноз. После снятия раннего фильтра распределение на поздних меняется; его неизвестные результаты нельзя считать PASS.

Повторное сканирование 1h/4h каждые 15 минут многократно оценивает одну закрытую свечу. Нужно различать попытку сканирования, строку audit, уникальный сетап, сохранённый сигнал и успешную Telegram-доставку. Даже 77 253 уникальных попытки не означают столько торговых возможностей. При неизменном default `max_trades_per_day=5` и одном непрерывно работающем экземпляре грубый потолок допуска — 35 открытий за семь UTC-суток, а не 15 тысяч; лимиты портфеля, дедупликация и качество дополнительно его уменьшают. Это условная граница по коду, не измеренная пропускная способность сервера. До исправления B-001 успешный проход текущего RiskEngine для валидных кандидатов равен нулю.

**5. A–F.** Приоритет: **F** (падение RiskEngine, корректность учёта и соответствие runtime) → **C** (происхождение статистики, выполняется параллельно) → **D** (семантика/привязка sweep и MSS, без повторения v1.2) → **F** (confirmation/config/entry-target defects) → **E** (исследование двух разных displacement-проверок) → **B** (настройка временного окна по replay) → **A** (2→1 пока отклонить). Потенциальный рост числа сигналов не равен доказанному росту их качества.

### Границы проверки

Прочитаны обязательные файлы задания и связанные детекторы, торговый план, entry trigger, scheduler, тесты, audit storage, конфигурация и история Git. В clone нет `.env` с runtime-настройками; tracked `signals.db` имеет размер 0 байт и не содержит таблиц. Binance Futures/150 символов — сведения из задания, не проверенная live-конфигурация: default exchange в `config/settings.py` — `bingx`. Не запрашивались биржевые ключи, не отправлялись сигналы, не выполнялся rollout. Severity CRITICAL используется для воспроизведённых падений/некорректных торговых связей; MEDIUM — для подтверждённых дефектов с неизмеренной долей потерь. Процент HIGH (>5% потерь сигналов по шаблону) без достоверного replay не присваивается по одному размеру агрегата.

---

## II. Findings


---

### B-001 — Undefined entry crashes all otherwise-eligible risk evaluations — Severity: CRITICAL

**File:** `risk/engine.py`; caller `scheduler/scanner.py`
**Lines:** `risk/engine.py:153-161`; `scheduler/scanner.py:1816-1827,2313-2320`
**Current behavior:** `evaluate()` receives `entry_price` but its geometry check reads undefined `entry`. Any candidate passing the existing portfolio limits and positive-price check raises `NameError`, rather than returning a `RiskDecision`. `run_scan_cycle()` collects the exception with `asyncio.gather(..., return_exceptions=True)` and logs it; neither a signal nor a risk audit row is created for this candidate.
**Expected behavior:** Evaluate BUY/SELL geometry using the supplied `entry_price`, reject invalid geometry, and continue to the unchanged net-RR/SL/EV checks for valid geometry.
**Why it matters:** This is a deterministic final blocker in the reviewed source. It can produce zero signals even if all quality gates are relaxed. It does not prove that this source version ran for the entire supplied historical week. v1.2 mentions this exception as a known test failure but did not include it among fixes applied; it remains reportable.

**Evidence:**
```python
        _is_buy_geo = sl < entry and tp > entry
        _is_sell_geo = sl > entry and tp < entry
        if not _is_buy_geo and not _is_sell_geo:
            return RiskDecision(
                should_trade=False,
                rejection_reason=f"GEOMETRY_INVALID: SL={sl:.4f}, entry={entry:.4f}, TP={tp:.4f} — no valid direction (need SL<entry<TP or TP<entry<SL)",
            )
```

**Fix:** Replace exactly the whole geometry block at lines 153–161, retaining method indentation:
```python
        # Validate the geometry against the supplied entry price.
        _is_buy_geo = sl < entry_price < tp
        _is_sell_geo = tp < entry_price < sl
        if not _is_buy_geo and not _is_sell_geo:
            return RiskDecision(
                should_trade=False,
                rejection_reason=(
                    f"GEOMETRY_INVALID: SL={sl:.4f}, entry={entry_price:.4f}, "
                    f"TP={tp:.4f} — need SL<entry<TP or TP<entry<SL"
                ),
            )
```

**Verification:** The original source was executed: `NameError: name 'entry' is not defined`. The replacement compiled and passed in-memory tests: BUY entry=100, SL=98, TP=110; SELL entry=100, SL=102, TP=90; both with P(TP)=0.65, ATR=0.8, empty portfolio. Invalid geometry entry=100, SL=98, TP=90 returns `GEOMETRY_INVALID` without raising. Add the following regression to `tests/test_new_pipeline.py` (standalone imports may be deduplicated with existing imports):
```python
import pytest

from config.settings import config
from risk.engine import PortfolioState, RiskEngine
from strategy.feature_builder import SetupFeatures
from strategy.probability_engine import TradeProbability


@pytest.mark.parametrize(
    "sl,tp,allowed",
    [(98.0, 110.0, True), (102.0, 90.0, True), (98.0, 90.0, False)],
)
def test_risk_geometry_uses_entry_price(monkeypatch, sl, tp, allowed):
    monkeypatch.setattr(config.trading, "exchange_fee_pct", 0.05)
    monkeypatch.setattr(config.trading, "slippage_pct", 0.05)
    monkeypatch.setattr(config, "risk_mode", "fixed")
    result = RiskEngine().evaluate(
        features=SetupFeatures(atr_pct=0.8),
        probability=TradeProbability(0.65, 3.0, 2.0, 0.8, "rules"),
        portfolio=PortfolioState(),
        entry_price=100.0,
        sl=sl,
        tp=tp,
        atr=0.8,
    )
    assert result.should_trade is allowed
    if not allowed:
        assert "GEOMETRY_INVALID" in result.rejection_reason
```

---

### B-002 — Valid sweep without MSS suppresses independent continuation — Severity: MEDIUM

**File:** `strategy/pattern_engine.py`
**Lines:** strategy/pattern_engine.py:181-225, 326, 346-362.
**Current behavior:** `_try_reversal` sets direction=None, and without MSS returns detected=True. `detect` then skips continuation and ultimately returns detected=False/no valid setup. Adding one valid sweep to an otherwise valid continuation turns it into no setup. This is not the v1.2 reclaim association fix.
**Expected behavior:** Failed reversal allows independent valid continuation; preserve effective rejection of unconfirmed sweep-only reversal for safety.
**Why it matters:** The presence of an unrelated sweep removes an otherwise eligible continuation. The loss share requires replay.

**Evidence:**
```python
if not has_mss:
    # Soft: sweep without MSS is still a reversal idea, just weaker.
    # MSS becomes a quality signal downstream, not a hard gate.
    return ICTSetup(
        detected=True,
        direction=direction,
        setup_type="reversal",
        has_sweep=has_sweep, sweep_type=sweep_type,
        sweep_strength=sweep_strength,
        sweep_reclaim_candles=sweep_reclaim,
        has_displacement=has_displacement,
        displacement_body_pct=disp_body,
        displacement_atr_ratio=disp_atr,
        has_mss=False,
        sweep_price=_sweep_price, sweep_candle_timestamp=_sweep_ts,
        rejection_reason="reversal: sweep only (no MSS)",
    )
```
**Fix:** Replace the full `if not has_mss` block in `_try_reversal` (346-362), indented inside the method, with:
```python
if not has_mss:
    return ICTSetup(
        detected=False,
        direction=None,
        setup_type="reversal",
        has_sweep=has_sweep,
        sweep_type=sweep_type,
        sweep_strength=sweep_strength,
        sweep_reclaim_candles=sweep_reclaim,
        has_displacement=has_displacement,
        displacement_body_pct=disp_body,
        displacement_atr_ratio=disp_atr,
        has_mss=False,
        sweep_price=_sweep_price,
        sweep_candle_timestamp=_sweep_ts,
        rejection_reason="reversal: no MSS (unconfirmed sweep)",
    )
```
**Verification:** Valid bullish StructureState+BOS with no sweep returns continuation; adding a valid bullish or bearish SweepEvent but no MSS must still return continuation, with sweep_failed_reversal=True. Sweep/no MSS/no BOS must be detected=False and include `no MSS` reason. Existing H-009 describes intended sweep-only admission, but that behavior is broken today: do not silently implement it while fixing fallback. Document this conservative choice; introducing actual sweep-only signals is a separate A/B hypothesis. Loss percentage cannot be inferred from funnel counts.

---

### B-003 — MSS matches wrong sweep direction and later pairs unrelated events — Severity: CRITICAL

**File:** `market_structure/structure.py`, `strategy/pattern_engine.py`, `liquidity/sweep.py`
**Lines:** market_structure/structure.py:145-164; strategy/pattern_engine.py:280-299,330-344,234-242; liquidity/sweep.py:157-200.
**Current behavior:** Detector names a sweep bullish when price pierces a low and closes above it; bearish pierces high and closes below. Classifier nevertheless matches the opposite type. PatternEngine independently takes strongest sweep of any direction/time, so a buy reversal may carry a bearish sweep after its MSS with delta silently clamped to 0. Entry zones use first valid sweep rather than either selected event. This is independent of fixed v1.2 reclaim parameter association.
**Expected behavior:** The classifier and pattern engine must use one identical, valid, same-direction, causal sweep, and bind reversal zones to that event.
**Why it matters:** A signal can combine opposite directions and reversed event order; such a causal chain is invalid regardless of signal volume.

**Evidence:**
```python
# Find matching sweep (OPPOSITE direction, within causal window)
matching_sweep = None
bars_since = 999

for s in sweeps:
    if not s.is_valid:
        continue
    # Sweep direction must OPPOSE CHoCH direction
    # Bullish CHoCH = structure shifts up AFTER bearish sweep (sell-side grab)
    # Bearish CHoCH = structure shifts down AFTER bullish sweep (buy-side grab)
    sweep_dir = "buy" if s.type == "bullish" else "sell"
    choch_dir = "buy" if choch.type == "bullish" else "sell"
    if sweep_dir == choch_dir:
        continue

    # Check causal window
    if choch.candle_index >= 0 and s.candle_index >= 0:
        delta = choch.candle_index - s.candle_index
    else:
        delta = 0  # unknown index, assume close
    if 0 <= delta <= max_causal_bars:
        if matching_sweep is None or delta < bars_since:
            matching_sweep = s
            bars_since = delta

# Reclaim bars from the ACTUAL matching sweep, not externally passed
```
**Fix:** Apply all five edits atomically, together with B-002 and B-004 timestamp correction.

1. Append these fields to CHoCH (after mss_score); existing constructor positional order remains intact:
```python
sweep_candle_index: Optional[int] = None
sweep_level: Optional[float] = None
```
2. Replace classifier block from `# Find matching sweep` through the end of `for s in sweeps` (141-164), retaining following reclaim handling:
```python
matching_sweep = None
bars_since = 999
choch.sweep_candle_index = None
choch.sweep_level = None
for s in sweeps:
    if not s.is_valid or s.type != choch.type:
        continue
    passes, _ = s.passes_false_sweep_filters(atr=s.atr, pool_age_bars=s.pool_age_bars)
    if not passes:
        continue
    if choch.candle_index < 0 or s.candle_index < 0:
        continue
    delta = choch.candle_index - s.candle_index
    if 0 <= delta <= max_causal_bars:
        if matching_sweep is None or delta < bars_since or (
            delta == bars_since and s.strength > matching_sweep.strength
        ):
            matching_sweep = s
            bars_since = delta
if matching_sweep is not None:
    choch.sweep_candle_index = matching_sweep.candle_index
    choch.sweep_level = matching_sweep.swept_level
```
3. Replace ONLY `valid_sweeps = [s for s in sweeps if s.is_valid]` in `_try_reversal` (280) with this block. Keep existing false-filter loop and field extraction afterwards:
```python
valid_sweeps = [s for s in sweeps if s.is_valid]
candidate_mss = structure.last_mss if structure is not None else None
if candidate_mss is not None:
    matched_index = getattr(candidate_mss, "sweep_candle_index", None)
    matched_level = getattr(candidate_mss, "sweep_level", None)
    valid_sweeps = [
        s for s in valid_sweeps
        if matched_index is not None
        and matched_level is not None
        and s.type == candidate_mss.type
        and s.candle_index == matched_index
        and s.swept_level == matched_level
        and s.candle_index <= candidate_mss.candle_index
    ]
```
4. Replace the whole timestamp extraction block in detect (234-242), inclusively from `# Extract sweep timestamp` through the existing `self._detect_entry_zones(...)` call. Do not retain the original call. Use:
```python
_sweep_ts = setup.sweep_candle_timestamp if setup.is_reversal else None
self._detect_entry_zones(
    setup, order_blocks, fvgs, direction, current_price, _sweep_ts
)
```
The old optional sweep_timestamp argument may remain for call compatibility but must not override the actual classified event. Continuations must not be timestamp-filtered by an unrelated failed-reversal sweep.

5. Replace `sweep_to_mss = max(0, mss.candle_index - sweep_candle_index)` with:
```python
sweep_to_mss = mss.candle_index - sweep_candle_index
```
**Verification:** Real SweepEvent: bullish CHoCH+bullish sweep within window becomes MSS; opposite-only remains weak; mirror for bearish. Multiple sweeps: nearest eligible causal sweep selected, ties highest strength, false-filter failures excluded, future sweeps excluded. PatternEngine must use the exact stored (index,level), and no reference means it must not synthesize reversal. OB/FVG before matched sweep excluded; after allowed; failed unrelated sweep cannot filter continuation zones. Update TestMSSClassification fixtures (currently incorrectly assert opposite semantic direction); use real SweepEvent or add real false-filter interface/atr/pool_age to mocks. Update MockCHoCH fields and setup fixtures to reflect actual classifier association. This is false-signal correctness, not a quantified signal-volume claim.

---

### B-004 — Latest valid sweep is marked invalid and timestamps lose market date — Severity: CRITICAL

**File:** `liquidity/sweep.py`
**Lines:** liquidity/sweep.py:141,163,168-170,192-194,227-240.
**Current behavior:** Detection requires close reclaimed on the sweep candle, but reclaim functions begin at next bar; on the newest closed candle no next bar exists, so reclaim=10 and is_valid=False. Independently `reset_index(drop=True)` turns a market timestamp into offset seconds after 1970, invalidating chronological OB/FVG constraints and chart/audit data.
**Expected behavior:** Same-candle reclaim is zero elapsed bars; event timestamps preserve the original market datetime index.
**Why it matters:** The newest reclaimed sweep is lost; incorrect historical timestamps can admit entry zones from before the actual event.

**Evidence:**
```python
# detect_sweeps: separate exact source lines
data = df.tail(lookback).reset_index(drop=True)
ts = _to_datetime(data.index[i])

def _count_candles_to_reclaim_bullish(df: pd.DataFrame, sweep_index: int, level: float, max_check: int = 10) -> int:
    """Count candles until price reclaims above level after a bullish sweep."""
    for j in range(sweep_index + 1, min(sweep_index + max_check + 1, len(df))):
        if df["close"].iloc[j] > level:
            return j - sweep_index
    return max_check

```
**Fix:**

1. Replace `data = df.tail(lookback).reset_index(drop=True)` with:
```python
data = df.tail(lookback)
```
All numerical accesses in this function/helpers use iloc; swing detector indices remain positional.

2. Replace both full reclaim helper functions, keeping names/signatures:
```python
def _count_candles_to_reclaim_bullish(
    df: pd.DataFrame, sweep_index: int, level: float, max_check: int = 10
) -> int:
    """Elapsed bars until a close above the pool; zero is same-bar reclaim."""
    for j in range(sweep_index, min(sweep_index + max_check + 1, len(df))):
        if df["close"].iloc[j] > level:
            return j - sweep_index
    return max_check + 1


def _count_candles_to_reclaim_bearish(
    df: pd.DataFrame, sweep_index: int, level: float, max_check: int = 10
) -> int:
    """Elapsed bars until a close below the pool; zero is same-bar reclaim."""
    for j in range(sweep_index, min(sweep_index + max_check + 1, len(df))):
        if df["close"].iloc[j] < level:
            return j - sweep_index
    return max_check + 1
```
**Verification:** Synthetic six-bar frame in real reproduction gives one last-bar bullish sweep; expected reclaim=0/is_valid=True/timestamp exact dataframe last index (2026), not reclaim=10/1970. Mirror bearish test; zero-based elapsed-bar convention explicit; helper future reclaim counts still j-index, no reclaim returns sentinel >max_check. Existing tests expecting latest sweep invalid or minimum reclaim1 must be corrected. Run temporal zone regression with selected event from B-003. Timestamp part is false-signal correctness; reclaim part has unquantified volume effect. This does not duplicate v1.2 fix (that changed which sweep provided reclaim; here the sweep's own measurement is wrong).

---

### B-005 — Later candle displacement promotes historical CHoCH — Severity: CRITICAL

**File:** `market_structure/structure.py`, `scheduler/scanner.py`
**Lines:** structure.py:174-193; scanner.py:526-535.
**Current behavior:** Scanner passes most recent candle body/ATR to classify_choch for a potentially much older CHoCH; classifier only increases that value from its causal [sweep,CHoCH] interval. A later unrelated impulse makes a historical weak pattern an MSS.
**Expected behavior:** When causal OHLCV is available, only that interval determines displacement for this CHoCH.
**Why it matters:** A subsequent unrelated candle can manufacture MSS confirmation for an earlier setup, creating incorrect signals.

**Evidence:**
```python
if max_disp > displacement_atr:
    displacement_atr = max_disp
    choch.displacement_score = displacement_atr
```
**Fix:** Inside the existing `if df is not None and atr_value > 0 ...` measurement block, replace the quoted three-line block (191-193) with these two lines at the indentation of the former `if`:
```python
displacement_atr = max_disp
choch.displacement_score = displacement_atr
```
When an actual causal OHLCV interval is available, it is authoritative even if smaller. Explicit displacement_atr remains supported for callers with no frame. This bounded fix does not redefine directional-body vs range methodology; that is separate research.
**Verification:** Frame candles in sweep3→CHoCH5 have body=.01 with ATR=1; last candle9 body=2; caller displacement_atr=2. Before strength=mss and displacement_score=2; after score=.01 and weak. Repeat with a genuine .5 body inside [3,5], expect MSS under current .2 rule. Use same-direction sweep after B-003, opposite-direction only when reproducing pre-fix source.

---

### B-006 — Score gate reads wrong config group — Severity: MEDIUM

**File:** `scheduler/scanner.py`, `config/settings.py`
**Lines:** scheduler/scanner.py:584; settings.py:465-477,884.
**Current behavior:** Config field declared under ScoringConfig, environment and persisted override both write config.scoring; scanner reads config.trading with fallback2. It silently ignores administrator changes in both tightening and loosening directions.
**Expected behavior:** Read the configured threshold from config.scoring and preserve the recommended value 2.
**Why it matters:** Both stricter and looser administrator thresholds are silently ignored; reading the correct field may activate a previously ignored stored override.

**Evidence:**
```python
_min_score = getattr(config.trading, 'min_score_for_signal', 2)
```
**Fix:** Replace with:
```python
_min_score = config.scoring.min_score_for_signal
```
**Verification:** Setting `config.scoring.min_score_for_signal = 3` must block `components_count=2`; setting that same field to 2 permits it. Never replace the `config.scoring` group itself with a number. `config.trading` need not have that field. Restore fixture values after tests. Keep deployed recommendation2; audit actual DB/env setting before code deploy because this fix makes a previously ignored stored value effective. Bump config version when changing effective threshold; record hypothesis. The current fallback2 also strengthens the conclusion that historical score<2 rows do not match this checkout's detector invariants.

---

### B-007 — Confirmation formula disagrees with scanner's stated reversal formula — Severity: MEDIUM

**File:** `strategy/pattern_engine.py`, `scheduler/scanner.py`
**Lines:** pattern_engine.py:103-114; scanner.py:700-714.
**Current behavior:** Both score gates pass a bare Trend+BOS continuation; a Sweep+MSS reversal has components=2 but confirmation=0 and requires simultaneous OB+FVG to reach 2. The scanner rejection message claims Sweep=2,MSS=1, but property gives them 0.
**Expected behavior:** Use an explicitly validated per-setup confirmation formula; the proposed formula below matches the scanner message and requires shadow/replay before live.
**Why it matters:** This is a second, different quality gate: decreasing the component count threshold cannot repair its reversal-specific behavior.

**Evidence:**
```python
@property
def confirmation_score(self) -> int:
    """Weighted confirmation score (TZ §6.4): BOS=2, FVG=1, OB=1.
    Minimum score for entry: 2."""
    score = 0
    if self.has_bos:
        score += 2
    if self.has_fvg:
        score += 1
    if self.has_ob:
        score += 1
    return score
```
**Fix:** Replace the full confirmation_score property (indent inside ICTSetup):
```python
@property
def confirmation_score(self) -> int:
    """Reversal: Sweep=2, MSS=1; continuation: BOS=2; OB/FVG=1 each."""
    if self.is_reversal:
        score = 2 * int(self.has_sweep) + int(self.has_mss)
    else:
        score = 2 * int(self.has_bos)
    return score + int(self.has_fvg) + int(self.has_ob)
```
**Verification:** Parameterized scores: continuation BOS=2, BOS+OB=3; reversal Sweep+MSS=3, plus OB or FVG=4, both=5. Run after B-002/B-003/B-004/B-005 corrections; do not independently turn on unconfirmed sweep-only admission. This formula change is an explicit strategy change matching scanner's declared formula; it must be evaluated by paired historical replay/shadow before live. Proven blocked population includes any reversal without both zones, but its >5% live share is not established.

---

### B-008 — Entry gate creates an unintended approximately 1% ATR cap — Severity: MEDIUM

**File:** `strategy/trade_engine.py`; `scheduler/scanner.py`; `strategy/entry_trigger.py`
**Lines:** `trade_engine.py:256-261`; `scanner.py:1169-1190`; `entry_trigger.py:118-142`
**Current behavior:** Each scan creates a synthetic entry zone centered on the current candle close, with half-width 0.3 ATR. The scanner chooses its lower edge for BUY or upper edge for SELL and demands that the same close be within 0.3% of that edge. The target moves with every new close. Algebra gives an implicit maximum ATR/close of 0.997009% for BUY and 1.003009% for SELL, even though the explicit volatility gate allows 0.3–8%. With close=100 and ATR=2 both directions are rejected before risk evaluation. This gate has no dependency on the actual structural OB/FVG zone.
**Expected behavior:** When a detected OB/FVG zone exists, use the closest point of that actual zone. Accept a price inside the zone or within the configured proximity on either side. Preserve the existing optional-zone policy for setups without a zone: earlier `require_entry_zone` remains authoritative. Preserve the spread check. Do not change the generic one-sided `EntryTrigger.check()` contract or existing callers.
**Why it matters:** A deterministic extra volatility filter can reject valid structural entries across both directions. Its historical contribution cannot be separated from the 1,090 reported entry-trigger rejections without run-level records, because the scanner has another later trigger gate. MEDIUM follows the requested severity definition: greater-than-5% total loss is not established. Changing structural entry behavior requires historical replay/shadow comparison before deploying as a signal-volume expansion.

**Evidence:**
```python
            entry_zone=(entry - atr * 0.3, entry + atr * 0.3),
```
```python
        _entry_zone_low, _entry_zone_high = trade_plan.entry_zone if trade_plan.entry_zone else (0.0, 0.0)
        if setup.direction == "buy" and _entry_zone_low > 0:
            _target_entry = _entry_zone_low  # pullback to lower bound
        elif setup.direction == "sell" and _entry_zone_high > 0:
            _target_entry = _entry_zone_high  # pullback to upper bound
        else:
            _target_entry = entry_price  # fallback: current price
```

**Fix:** Add this method to `EntryTrigger` in `strategy/entry_trigger.py`, after `__init__` and before `check`. It uses the selected structural zone fields already populated by `PatternEngine._detect_entry_zones`. This is a complete method; no new module-level imports are needed.
```python
    def check_setup_zone(self, setup, current_price, bid=None, ask=None):
        """Check proximity to detected OB/FVG zones without inventing ATR targets."""
        from math import isfinite

        if not isfinite(current_price) or current_price <= 0:
            return TriggerResult(triggered=False, reason="invalid_current_price")
        if setup.direction not in ("buy", "sell"):
            return TriggerResult(triggered=False, reason="invalid_direction")

        zones = []
        if setup.has_ob:
            zones.append((setup.ob_low_price, setup.ob_high_price))
        if setup.has_fvg:
            zones.append((setup.fvg_bottom_price, setup.fvg_top_price))
        for low, high in zones:
            if not all(isfinite(value) and value > 0 for value in (low, high)) or low > high:
                return TriggerResult(triggered=False, reason="invalid_setup_entry_zone")

        # No structural zone: retain the existing optional-entry-zone policy.
        # scan_symbol_v2 has already enforced require_entry_zone upstream.
        target_price = current_price
        if zones:
            target_price = min(
                (min(max(current_price, low), high) for low, high in zones),
                key=lambda price: abs(current_price - price) / price,
            )
            distance_pct = abs(current_price - target_price) / target_price * 100
            if distance_pct > self.entry_proximity_pct:
                return TriggerResult(
                    triggered=False,
                    entry_price=target_price,
                    reason=(
                        f"price outside setup entry zone: {distance_pct:.3f}% "
                        f"> {self.entry_proximity_pct}%"
                    ),
                )

        return self.check(
            SimpleEntryTarget(direction=setup.direction, entry_price=target_price),
            current_price=current_price,
            bid=bid,
            ask=ask,
        )
```

In `scan_symbol_v2`, replace the entire first trigger-construction block, lines 1172–1190 (from its import through the `_entry_trigger.check(...)` call), with:
```python
        from strategy.entry_trigger import EntryTrigger

        _entry_trigger = EntryTrigger(
            entry_proximity_pct=getattr(config, 'entry_proximity_pct', 0.3),
            max_spread_pct=getattr(config, 'max_entry_spread_pct', 0.1),
        )
        _trigger_result = _entry_trigger.check_setup_zone(
            setup=setup,
            current_price=ind.close,
            bid=getattr(ind, 'bid', None),
            ask=getattr(ind, 'ask', None),
        )
        _target_entry = _trigger_result.entry_price
```

Keep the following existing `if not _trigger_result.triggered:` rejection/audit block unchanged, as well as its PASS block. Do not modify the generic `check()` method or TradeEngine's entry zone in this bounded fix. The synthetic trade-plan zone is simply no longer used to authorize entry.

**Verification:** The original ATR=2%, close=100 code blocks both BUY at target 99.4 and SELL at target 100.6. The proposed method compiled and passed 14 checks across BUY/SELL: inside actual OB, outside above, outside below, wide spread, invalid zone, optional no-zone fallback, and FVG. Add to `tests/test_entry_trigger.py`:
```python
from strategy.pattern_engine import ICTSetup


@pytest.mark.parametrize("direction", ["buy", "sell"])
def test_structural_entry_zone_has_no_synthetic_atr_cap(direction):
    trigger = EntryTrigger()
    setup = ICTSetup(
        detected=True,
        direction=direction,
        has_ob=True,
        ob_low_price=99.8,
        ob_high_price=100.2,
    )
    assert trigger.check_setup_zone(setup, 100.0).triggered
    assert not trigger.check_setup_zone(setup, 102.0).triggered
    assert not trigger.check_setup_zone(setup, 98.0).triggered
    assert not trigger.check_setup_zone(setup, 100.0, bid=99.0, ask=101.0).triggered
    setup.ob_low_price = 0.0
    assert not trigger.check_setup_zone(setup, 100.0).triggered
    setup.has_ob = False
    assert trigger.check_setup_zone(setup, 100.0).triggered
    setup.has_fvg = True
    setup.fvg_bottom_price = 99.8
    setup.fvg_top_price = 100.2
    assert trigger.check_setup_zone(setup, 100.0).triggered
```

Also add an integration regression with a valid setup inside an actual structural zone and `ind.atr / ind.close = 0.02`: first entry trigger passes, while downstream net RR, SL, P(TP), live spread and second-entry checks still execute. A genuine structural zone more than 0.3% away must still block. Add explicit boundary cases exactly at and immediately outside the configured proximity. No quantitative signal increase can be inferred from this synthetic test alone.

---

### B-009 — Deployment provenance and mixed historical cohorts (UNCERTAIN) — Severity: MEDIUM

**File:** `scheduler/scanner.py`, `.github/workflows/deploy.yml`, diagnostic new file `scripts/audit_runtime_evidence.py`.
**Lines:** scanner 93, 454–470, 2242–2246; deployment workflow.
**Current behavior:** `_CONFIG_VERSION` is a manually assigned integer, not a build identity or effective configuration hash. The time-of-day block has no executable caller in this checkout. The supplied seven-day report includes 4,003 `time_of_day_blocked` and 12,179 `mss_none`, but no per-event deployment SHA or per-version time partition is supplied. These numbers cannot be attributed to HEAD or to the post-fix version.
**Expected behavior:** owner compares actual deployed artifact hashes against the reviewed commit and exports the same time interval grouped by configuration version, stage, and reason before changing thresholds.
**Why it matters:** otherwise stale first-rejection counts drive changes to gates that are already disabled or unreachable in current code. Deployment drift remains a hypothesis, not a confirmed live bug.

**Evidence:**
```python
_CONFIG_VERSION = 10  # v10: volatility_max_atr=8%, sweep_min_wick=0.01% (H-014)

        # 0.4c Time-of-Day Gate — DISABLED (needs more live data to validate)
        # try:
        #     _current_hour = datetime.now(timezone.utc).hour
        #     _blocked_hours_str = getattr(config.trading, 'blocked_hours', '9,11,12,16')
        #     _blocked_hours = [int(h.strip()) for h in _blocked_hours_str.split(',') if h.strip()]
        #     if _current_hour in _blocked_hours:
        #         reason = f"blocked hour {_current_hour}:00 UTC (0% WR in live data)"
        #         _current_funnel.log_gate(symbol, timeframe, "time_of_day", "BLOCKED", reason)
        #         trace.blocked("time_of_day", reason)
        #         trace.set_version(VERSION, build_config_snapshot())
        #         await trace.save(db)
        #         await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
        #                          "time_of_day", TIME_OF_DAY_BLOCKED, False,
        #                          direction="unknown")
        #         return None
        # except Exception:
        #     pass
```

The above excerpts are exact; they are separate source locations. `git grep` found this reason only in its declaration, import and commented block. The first tracked introduction, `002fc3d` on September 16, already has the block commented. Therefore git history does NOT demonstrate a tracked version that generated the 4,003 rows. Uncommitted deployments, untracked versions, imported historical rows or a different reporting source remain possible.

Normal routing is `main.main()` → `scheduler.tasks.TaskScheduler._scan_job()` → `scheduler.scanner.run_scan_cycle()` → `scan_symbol_v2()`. Admin `/scan` calls the same cycle. `scan_core_v2()` and `run_shadow_cycle()` have no callers in the tracked startup/scheduler code; their existence is not proof of parallel scheduling. The current web UI source does not contain the quoted `Scan Engine / Total Entries` report, so that report's implementation is not established here.

Read-only GitHub metadata, observed 2026-09-19:

| Commit | Tests workflow | Deploy workflow |
|---|---|---|
| `24d3ef0` | [failure](https://github.com/Andersan41/telebot/actions/runs/35438359576) | [skipped](https://github.com/Andersan41/telebot/actions/runs/35438369738) |
| `4922764` (v1.2 fixes) | [failure](https://github.com/Andersan41/telebot/actions/runs/35438057516) | [skipped](https://github.com/Andersan41/telebot/actions/runs/35438066438) |

For HEAD, the job API reports `Install deps: failure` and `Run tests: skipped`; this is NOT evidence of pytest failures. Run logs returned HTTP 403 (repository admin permission required), so the exact dependency-install error is unknown. The `deploy` workflow only builds and pushes GHCR images; it contains no actual server rollout. Manual deployment is possible and remains unverified. Dockerfile copies code into an image; compose mounts only data/logs, so changing host source and restarting an old image would not update the code.

**Fix:** Add the following standalone stdlib-only diagnostic as `scripts/audit_runtime_evidence.py`. It imports no bot modules, reads no secret values, does not initialize or modify the DB, and makes no network requests. Run it on the reviewed checkout and, by the server owner, inside the actual bot container/code directory using explicit UTC start/end timestamps and the real SQLite path. Compare SHA256 per file; git HEAD alone does not detect dirty copied files. It prints only a whitelist of numeric environment/DB settings, not `.env`, tokens, channel IDs, DB URLs, process command lines or entire settings tables. Environment shown belongs to the diagnostic process; it is explicitly NOT asserted to equal the running bot's in-memory config. Optional Linux `--pid` records process cwd/executable without reading its arguments/environment. No safe external Python import can reconstruct the live singleton or prove that on-disk files were loaded before the latest restart.

```python
from __future__ import annotations

import argparse
import ast
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess


FILES = (
    "main.py", "scheduler/tasks.py", "scheduler/scanner.py",
    "strategy/pattern_engine.py", "market_structure/structure.py",
    "risk/engine.py", "config/settings.py", "storage/audit_reasons.py",
    "liquidity/sweep.py", "liquidity/candle_quality.py",
    "strategy/trade_engine.py", "strategy/entry_trigger.py",
)
SAFE_ENV = (
    "MIN_SCORE_FOR_SIGNAL", "MIN_P_TP", "MIN_P_TP_SHORT",
    "MIN_P_TP_REVERSAL", "MAX_TRADES_PER_DAY", "MAX_ACTIVE_SIGNALS",
    "MAX_POSITIONS_TOTAL", "VOLATILITY_MIN_ATR_PERCENT",
    "VOLATILITY_MAX_ATR_PERCENT", "SWEEP_MIN_WICK_BEYOND_LEVEL",
)
SAFE_DB_KEYS = (
    "filter:param:min_score_for_signal", "param:MIN_SCORE_FOR_SIGNAL",
    "filter:param:min_p_tp", "param:MIN_P_TP",
)


def utc_arg(value: str) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp must include UTC offset")
    return stamp.astimezone(timezone.utc)


def safe_number(value):
    if value is None:
        return None
    try:
        number = float(value)
        if not (-1e9 <= number <= 1e9):
            return "INVALID_OR_NONFINITE"
        return number
    except (TypeError, ValueError):
        return "INVALID_NONNUMERIC"


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only audit evidence")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--since", type=utc_arg)
    parser.add_argument("--until", type=utc_arg)
    parser.add_argument("--pid", type=int)
    args = parser.parse_args()
    if args.db is not None and (args.since is None or args.until is None):
        parser.error("--db requires both --since and --until")
    if args.db is None and (args.since is not None or args.until is not None):
        parser.error("--since and --until require --db")
    if args.db is not None and args.until <= args.since:
        parser.error("--until must be later than --since")
    root = args.root.resolve(strict=True)
    database = args.db.resolve(strict=True) if args.db is not None else None
    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "database": str(database) if database is not None else None,
        "since_inclusive": args.since.isoformat() if args.since is not None else None,
        "until_exclusive": args.until.isoformat() if args.until is not None else None,
        "live_loaded_code_verified": False,
        "file_sha256": {},
        "diagnostic_process_environment_only": {
            key: safe_number(os.getenv(key)) for key in SAFE_ENV
        },
    }
    for name in FILES:
        file = root / name
        report["file_sha256"][name] = (
            hashlib.sha256(file.read_bytes()).hexdigest()
            if file.is_file() else "MISSING"
        )
    scanner = root / "scheduler/scanner.py"
    if scanner.is_file():
        tree = ast.parse(scanner.read_text(encoding="utf-8-sig"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "_CONFIG_VERSION"
                for target in node.targets
            ):
                if isinstance(node.value, ast.Constant):
                    report["source_config_version"] = node.value.value
    try:
        revision = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        report["git_head"] = (
            revision.stdout.strip() if revision.returncode == 0 else "UNAVAILABLE"
        )
    except (OSError, subprocess.TimeoutExpired):
        report["git_head"] = "UNAVAILABLE"
    if args.pid is not None:
        if args.pid <= 0:
            parser.error("--pid must be positive")
        report["process"] = {"pid": args.pid}
        for name in ("cwd", "exe"):
            try:
                report["process"][name] = os.readlink(f"/proc/{args.pid}/{name}")
            except OSError:
                report["process"][name] = "UNAVAILABLE"
    if database is None:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return
    window = (args.since.isoformat(), args.until.isoformat())
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        report["audit_by_day_version_stage_reason"] = [dict(row) for row in conn.execute(
            """SELECT date(ts_event) AS utc_day, config_version, scan_mode,
                      stage, reason_code, passed, COUNT(*) AS row_count,
                      MIN(ts_event) AS first_event, MAX(ts_event) AS last_event
               FROM signal_audit_log
               WHERE julianday(ts_event) >= julianday(?)
                 AND julianday(ts_event) < julianday(?)
               GROUP BY date(ts_event), config_version, scan_mode,
                        stage, reason_code, passed
               ORDER BY utc_day, config_version, scan_mode, stage, reason_code, passed""",
            window,
        )]
        report["audit_totals"] = dict(conn.execute(
            """SELECT COUNT(*) AS audit_rows,
                      SUM(CASE WHEN passed = 0 THEN 1 ELSE 0 END) AS blocked_rows,
                      SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END) AS passed_rows
               FROM signal_audit_log
               WHERE julianday(ts_event) >= julianday(?)
                 AND julianday(ts_event) < julianday(?)""",
            window,
        ).fetchone())
        keys = ",".join("?" for _ in SAFE_DB_KEYS)
        report["whitelisted_db_overrides"] = {
            row["key"]: safe_number(row["value"])
            for row in conn.execute(
                f"SELECT key, value FROM bot_settings WHERE key IN ({keys})",
                SAFE_DB_KEYS,
            )
        }
        report["stored_signals_not_delivery_receipts"] = dict(conn.execute(
            """SELECT COUNT(*) AS saved_signals,
                      SUM(CASE WHEN telegram_sent_at IS NOT NULL THEN 1 ELSE 0 END)
                          AS with_telegram_timestamp
               FROM signals
               WHERE julianday(created_at) >= julianday(?)
                 AND julianday(created_at) < julianday(?)""",
            window,
        ).fetchone())
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
```

**Verification:** on a temporary synthetic SQLite file with the three current tables, seed two versions, multiple stages and rows exactly at both time bounds. Confirm UTC lower bound inclusive, upper bound exclusive, config versions kept separate, summing grouped counts equals `audit_rows`, and invalid/non-whitelisted settings never expose values. Confirm a missing DB path raises instead of creating a new DB. On live evidence, compare source hashes to audited checkout and owner-confirmed process restart/image digest; demand that fresh post-restart rows cannot emit a reason whose only call is commented out. If they do, actual code/reporting provenance remains unresolved. Do not automatically edit `blocked_hours`, lower scores, re-enable the gate, restart or deploy.

`--db` is optional: `python scripts/audit_runtime_evidence.py --root .` generates reference fingerprints from an ordinary clone. Supplying `--db` requires both explicit UTC `--since` and `--until`; no default live DB path is guessed. Example owner-only invocation inside the real runtime directory: `python scripts/audit_runtime_evidence.py --root . --db /app/data/signals.db --since 2026-09-19T00:00:00Z --until 2026-09-20T00:00:00Z` (replace path/time interval with the actual values, this is not executed by the auditor).

Local validation completed: syntax parsing, root-only fingerprint without any DB, exact UTC date boundaries, per-version grouping, numeric whitelist masking, unchanged SQLite SHA256, and refusal to create a missing database all PASS. Standalone script copied identically to workspace `audit_runtime_evidence.py`; verification harness is `validate_funnel_diagnostic.py` outside the repository. Validation used only a synthetic temporary database, not server data.

---

## III. Summary table

| ID | Title | Severity | File | Status |
|----|-------|----------|------|--------|
| B-001 | Undefined entry crashes risk evaluation | CRITICAL | risk/engine.py | OPEN; reproduced, fix checked in memory |
| B-002 | Sweep without MSS suppresses continuation | MEDIUM | strategy/pattern_engine.py | OPEN; reproduced, conservative fix checked |
| B-003 | Wrong sweep direction and event association | CRITICAL | market_structure/structure.py; strategy/pattern_engine.py | OPEN; apply association edits together |
| B-004 | Same-candle reclaim and lost timestamps | CRITICAL | liquidity/sweep.py | OPEN; timestamp/reclaim checks passed in memory |
| B-005 | Noncausal displacement promotes old CHoCH | CRITICAL | market_structure/structure.py | OPEN; causal-window check passed in memory |
| B-006 | Score threshold read from wrong config group | MEDIUM | scheduler/scanner.py | OPEN; confirm persisted value before rollout |
| B-007 | Reversal confirmation formula mismatch | MEDIUM | strategy/pattern_engine.py | OPEN; proposed policy needs replay/shadow |
| B-008 | Moving entry target creates implicit ATR cap | MEDIUM | scheduler/scanner.py; strategy/entry_trigger.py | OPEN; proposed zone policy needs replay/shadow |
| B-009 | Runtime/report provenance (UNCERTAIN) | MEDIUM | scheduler/scanner.py; scripts/audit_runtime_evidence.py | DIAGNOSTIC READY; live evidence unavailable |

Ни один OPEN здесь не означает уже внедрённое исправление. Слово «passed» в статусе относится к локальной проверке предложенной замены, а не к тестам всего репозитория или работе сервера.

---

## IV. Priority order

Числовую величину `signal_volume_impact × confidence` нельзя вычислить без сопоставимых исходных событий; ниже качественный порядок с доказанным механизмом влияния.

1. **B-001 — RiskEngine crash.** Достоверный конечный блокиратор каждого подходящего кандидата. Исправление не ослабляет ни один фильтр риска.
2. **B-009 — Runtime provenance**, параллельно с локальными исправлениями. Без этого нельзя переносить недельные проценты на новую реализацию и измерить эффект.
3. **B-002 + B-003 + B-004 + B-005 — причинная корректность паттернов.** Выполнять и проверять связанной серией до увеличения допуска reversal. B-002 сохраняет запрет фактически не работавших sweep-only разворотов и восстанавливает независимый continuation. B-003–B-005 устраняют неверные связи между событиями.
4. **B-006 — корректный config path.** Простое исправление, но сначала сверить DB/env: ранее игнорируемое значение начнёт действовать. Рекомендуемое эффективное значение остаётся 2.
5. **B-007 — confirmation по типу сетапа.** Сначала paired replay/shadow после причинных исправлений; сообщить разницу в уникальных сетапах, финальных допусках и исходах. Не выдавать увеличение промежуточных PASS за улучшение качества.
6. **B-008 — структурная цель входа.** Сначала paired replay/shadow с реальными OB/FVG; проверить оба entry-trigger этапа, спред и неизменённые SL/RR ограничения.
7. **E/B из задания — исследования displacement/window.** Только после новой чистой базы. A (min score 2→1) сейчас не внедрять.

---

## V. Config recommendations

«Current» означает исходник проверенного commit, если не сказано иначе. Runtime товарища не измерен.

| Param | Current | Recommended | Reason |
|-------|---------|-------------|--------|
| min_score_for_signal | config.scoring=2; scanner читает отсутствующее trading-поле и fallback 2 | 2 через config.scoring | Успешные текущие сетапы уже имеют ≥2 компонента; снижение не лечит ноль |
| confirmation minimum | hardcoded 2 | 2; формулу B-007 сначала replay/shadow | Разные определения score нельзя лечить одним общим порогом |
| max_causal_bars | 10, аргумент classify_choch | 10 baseline; 15/20 только отдельные replay arms | 10h/40h, качество временной привязки важнее расширения окна |
| MSS displacement_atr threshold | hardcoded 0.2 | 0.2 baseline после B-005 | Нельзя компенсировать ошибочную причинность снижением порога |
| CANDLE_DISPLACEMENT_ATR_MULT | 1.5, проверка range > ATR×mult | 1.5 baseline | Это другая метрика относительно MSS; не путать с 0.2 |
| REVERSAL_REQUIRE_DISPLACEMENT | true | true baseline; причинный impulse-vs-current-bar вариант отдельно shadow | Выключение расширяет класс сигналов; сначала измерить потери валидных ретестов |
| VOLATILITY_MIN_ATR_PERCENT / MAX | 0.3 / 8.0 | без изменений | B-008 устраняет непреднамеренную дополнительную проверку, а не расширяет явные границы |
| SWEEP_MIN_WICK_BEYOND_LEVEL | 0.01% | без изменений | Сначала исправить измерения sweep, не ослаблять фильтры |
| HTF_BIAS_V2 | true | true | В этом аудите нет новых данных для отключения |
| PREMIUM_DISCOUNT | false | false | Нет новых данных для включения |
| MIN_P_TP / SHORT / REVERSAL | 0.30 / 0.40 / 0.50 | без изменений | Рост паттернов не является калибровкой вероятностей |
| RISK_ENGINE_MIN_RR | 2.5 после fee/slippage | без изменений | Восстановить выполнение имеющейся защиты |
| SL limits / ATR floor | v1.2 dynamic max; floor fallback 2×ATR | не откатывать v1.2; новых послаблений нет | Не повторять уже исправленный cap 8% |
| MAX_TRADES_PER_DAY | 5 | без изменений | 2–5 качественных сигналов/неделю не требуют увеличивать дневной лимит |
| _CONFIG_VERSION / VERSION | 10 / 2.5.0 | новые значения при реальном внедрении | Отдельная версия для изменившейся логики; audit-only commit их не меняет |

Не добавлять несуществующие `.env`-параметры для `max_causal_bars` или confirmation threshold без отдельного кода чтения, валидации и теста. Время суток остаётся отключённым; изменение `blocked_hours` в текущем коде ничего не исправит.

---

## VI. Questions for the team

1. Владелец сервера: какой **реально загруженный** commit/image digest работал в каждом интервале недели и после v1.2? Нужны перезапуск/время запуска процесса, хэши файлов, источник отчёта и агрегат из B-009. Доступ не предоставлен; ответ не подменяется состоянием GitHub Actions.
2. Какой источник данных сформировал «77 253 Total Entries / 0 Signals Sent»? Дайте определение entry и delivery. Если используются terminal audit rows, счётчик не включает все завершившиеся исключением попытки. `pipeline/OK` записывается до outcome/Telegram, а `sent_at` присваивается при сохранении: это не квитанция доставки.
3. Подтверждает ли команда намерение H-009 разрешать sweep-only reversal? B-002 намеренно сохраняет текущий фактический запрет без MSS, восстанавливая continuation. Не менять `detected=False` обратно на True и не добавлять направление sweep ради увеличения статистики без отдельного исследования.
4. Принимается ли для исследования declared-формула B-007 (Sweep=2, MSS=1)? Она убирает фактическое требование одновременных OB+FVG у reversal. Это осознанный выбор стратегии, поэтому не выдавать его за безопасный чисто технический рефакторинг.
5. Кто проверяет контракт атомарного резервирования портфеля и дневного бюджета перед live-расширением? Этот аудит не сертифицирует его: `RiskEngine` проверяет текущую сумму, а не текущую+новую; поздняя «atomic» проверка scanner содержит раздельные `await`; `_dl_pre_actual` не используется; вызываемого при rollback `daily_limits.release_trade` нет. Эти наблюдения — **отдельный release prerequisite**, не готовое указание mimo добавить один неатомарный if. Нужна отдельная задача на единый transaction/reservation contract с конкурентными тестами, rollback при save/trace/outcome failure и единым фактически зарезервированным размером риска. Не применять частичный «фикс» вызовом отсутствующего release_trade. Не считать B-001 разрешением повышать объём live-сигналов до этой проверки.

---

## VII. Implementation notes for mimo

### Что делать в репозитории

1. Сверить исходный commit с указанным SHA. Предлагаемые замены относятся именно к нему; не применять номера строк к другой версии вслепую.
2. B-001 и B-006 — небольшие технические исправления для отдельного commit с целевыми тестами. Для B-006 сначала проверить effective setting, поскольку код начнёт уважать сохранённый override.
3. B-002/B-003/B-004/B-005 — связанная серия исправлений измерения/сопоставления. Особенно не разделять пять внутренних edits B-003: classifier и consumer должны использовать одни поля ссылки на sweep. B-004 исправляет собственное измерение reclaim, а не повторяет v1.2 выбор matching_sweep.
4. B-007 и B-008 — реализовать в экспериментальной ветке, проверить регрессии, затем paired replay/shadow. Сами snippets готовы к копированию, но это не инструкция сразу менять live-политику. Не делать снижение min_score вместе с ними.
5. B-009 — диагностический скрипт приложен уже в этом audit commit; его можно запускать локально без доступа к бирже. Серверную часть выполняет владелец. Отсутствие live-доступа не останавливает остальные работы и не разрешает выдумывать результат серверной проверки.
6. В implementation commit обновить `plan/01-architecture.md`, `plan/07-scheduler.md`, `plan/11-pipeline.md` в затронутых местах и записать новые H-entries в `docs/hypotheses.md` до сбора live-результатов. H-013/H-014 из задания не найдены в текущем журнале, который заканчивается H-010: сначала восстановить историю, не назначать номера с коллизиями.
7. При реальном внедрении bump `_CONFIG_VERSION` и `VERSION`, зафиксировать SHA и effective non-secret config. Каждый experimental arm получает отдельную идентичность. Не менять эти значения в одном лишь audit-документе.

### Тесты и воспроизводимость

Проверка исходной ветки, Python **3.12.14**, Windows, isolated venv; numpy **2.2.6**, pandas **3.0.1**, pandas-ta **0.4.71b0**. Установка обычной командой не разрешила `pandas-ta>=0.4.0`; для локального аудита использовано `pip install --pre -r requirements.txt -r requirements-dev.txt`. Production requirements не изменены. Это не точное воспроизведение Python3.11 CI/Docker; CI dependency-install failure рассматривается отдельно и не подменяется локальным pytest результатом.

Выполнено:

```bash
python -m pytest tests/test_new_pipeline.py tests/test_market_structure.py tests/test_risk.py tests/test_entry_trigger.py tests/test_liquidity.py tests/test_scanner.py tests/test_config.py -q --tb=short
```

Результат: **353 passed, 32 failed, 8 xfailed**. Не весь test suite. Failures включают воспроизведённый `entry` NameError, `MockSweep` без актуального метода/полей, устаревшие assertions features/probability, scanner/config fixtures без локальной БД и ожидание настоящей `.env`. Они перечисляются как baseline, а не как 32 доказанных production-дефекта. Не вставлять реальные Telegram/Binance credentials ради зелёных unit tests.

Изменить/добавить проверки:

| Test file | Обязательные сценарии |
|---|---|
| tests/test_new_pipeline.py | B-001 buy/sell/invalid geometry; fallback с sweep/no MSS; confirmation по setup type; threshold из config.scoring; реальные SweepEvent/CHoCH поля |
| tests/test_market_structure.py | одно направление sweep/CHoCH; future/opposite/false-filter events исключены; exact event reference; displacement только causal interval |
| tests/test_liquidity.py | latest closed sweep с reclaim=0; оба направления; timestamp исходного индекса; отсутствие reclaim даёт sentinel |
| tests/test_entry_trigger.py | B-008 внутри OB/FVG, обе стороны вне зоны, границы допуска, malformed zones, spread, optional no-zone policy |
| tests/test_scanner.py | обе entry-проверки; isolated async DB/моки; score setting2/3; RuntimeError не маскируется как отсутствие сетапа |
| tests/test_config.py | env fixtures через monkeypatch; не зависеть от пользовательской `.env`; stored override читается из правильного раздела |

При исправлении fixtures `MockSweep` нельзя просто заставить любой false-filter возвращать True и считать это интеграционным покрытием: использовать настоящий `SweepEvent` либо отдельные unit doubles и интеграционные случаи с реальным фильтром. Старые tests с противоположным направлением sweep переписать в соответствии с фактической семантикой detector. Не убирать проверки risk/portfolio ради зелёного baseline.

Дополнительно выполнены проверки предложенных замен **только в памяти**, без изменения исходников: B-001 BUY/SELL/invalid geometry; B-002 fallback; B-003 обе стороны и идентичность события; B-004 timestamp/reclaim; B-005 causal displacement; B-007 score; B-008 14 сценариев входа. Python-сниппеты проверены синтаксически в контексте метода. Это подтверждает конкретные исправления, но не равнозначно успешному полному suite после будущего внедрения.

Приложен read-only воспроизводитель текущих дефектов:

```bash
python fix/review_v1_3_checks.py
```

Ожидаемые исходные наблюдения сохранены в `fix/review_v1_3_observations.json`: NameError, score config mismatch, reversal confirmation0/1, continuation2, suppressed fallback, inverted sweep/MSS, reclaim10, synthetic ATR2%-entry rejection. Скрипт печатает наблюдения; exit0 означает только успешное выполнение диагностики, не исправность бота. После внедрения значения должны измениться согласно Verification каждого finding.

Локальная исходная fingerprint-проверка без БД:

```bash
python scripts/audit_runtime_evidence.py --root .
```

Для владельца сервера, из фактического контейнера/каталога приложения, с реальными путями и интервалом (пример интервала, не подтверждённые даты исходной выгрузки):

```bash
python scripts/audit_runtime_evidence.py --root . --db data/signals.db --since 2026-09-12T00:00:00Z --until 2026-09-19T00:00:00Z
```

Диагностический скрипт проверен на синтетической SQLite: inclusive/exclusive границы, отдельные config_version, сумма групп=total, скрытие нечисловых значений, отсутствие изменения hash БД, отказ создавать отсутствующую БД. Хэши файлов сравнивать для одинаковых байтов/line endings; при Windows CRLF против Linux LF сначала использовать чистый checkout с одинаковой политикой окончаний строк. Fingerprint на диске не доказывает, что работающий Python-процесс загрузил эти же байты до последнего изменения файлов.

### Как измерять эффект

Для каждой пары `(symbol, timeframe, closed_candle_timestamp)` использовать только данные, доступные на этот момент; дописанные позднее свечи не должны менять исторический результат. Зафиксировать отдельный setup/event identity, execution price, fee/slippage, версию кода/config. Сравнить baseline и каждый arm на **одинаковом** массиве, исполнив весь scanner-путь с portfolio/dedup/daily state и обоими entry gates. Отдельно вывести passed-pattern, passed-confirmation, final risk-approved, уникальные сохранённые сигналы и Telegram delivery. На первой отказавшей проверке поздние gates остаются NOT_EVALUATED, а не PASS.

Сначала технические причинные исправления, затем по одному policy change B-007/B-008, затем displacement/window. Оценивать не только частоту, но и net PnL/expectancy, drawdown, SL hit rate и объём выборки на отложенном периоде. Не объединять 1h и 4h или повторные 15-минутные попытки в независимые сделки. Для семи полных UTC-дней при default5/day условная граница35; произвольное rolling7d окно может пересекать восемь UTC-дат (до40), а перезапуски/несколько экземпляров нарушают такую простую границу. Прогноз 2–5 **качественных** сигналов в неделю пока не подтверждён данными.
