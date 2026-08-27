# Elliott Wave Module — техническое задание для реализации

**Статус:** к реализации
**Исполнитель:** автономный агент (mimo, opencode)
**Контекст:** интеграция в существующий ICT-бот (см. `audit_bot.md`)
**Дата:** 2026-08-27

---

## 0. Обязательные правила для агента (прочитать первым)

1. **НЕ добавлять волновой анализ как hard-gate** в `scanner.py`. Это soft-feature. Ни один существующий ICT-гейт (sweep, MSS, BOS, OB retest, HTF bias) не должен блокироваться или пропускаться на основании волнового счёта. Волновой модуль **только читает** данные и пишет свой результат в `SetupFeatures` / `DecisionTrace` — он не имеет права вызывать `BLOCK`.
2. **НЕ трогать существующую бизнес-логику ICT** (`pattern_engine.py`, `liquidity/*`, `market_structure/structure.py`) кроме одного целевого рефакторинга — вынесения swing detection в общий модуль (см. Этап 0). Это разрешено явно, потому что дублирование уже зафиксировано как баг в аудите.
3. **Всегда сначала пишется unit-тест, потом код.** Каждый модуль ниже имеет свой файл тестов, который должен быть создан до реализации функции (TDD). Не переходить к следующему этапу, пока тесты предыдущего не зелёные.
4. **Никаких магических чисел без `.env`-параметра.** Все пороги (глубина отката, ATR-фильтр шума, min bars между swing-точками) должны быть параметрами в `config/settings.py`, с дефолтами, указанными в этом файле.
5. **Волновой счёт всегда возвращает confidence [0.0–1.0] и минимум 1, максимум 3 альтернативных счёта** (primary + до 2 alt). Никогда не возвращать единственный "точный" счёт без confidence — это противоречит природе волнового анализа и введёт ложную уверенность в `ProbabilityEngine`.
6. **Не делать репэйнт незакрытых свечей.** Используется тот же паттерн, что уже есть в `exchange_client.py:305` (`df.iloc[:-1]`) — волновой модуль работает только с закрытыми барами.
7. По завершении каждого этапа — прогнать полный `pytest`, убедиться, что существующие тесты (`test_new_pipeline.py`, `test_liquidity.py` и т.д.) не сломаны.

---

## 1. Цель

Добавить модуль расчёта волнового анализа Эллиотта (Elliott Wave), который:

- переиспользует единую (унифицированную) точку определения swing/fractal-точек;
- строит текущий волновой счёт (primary + альтернативы) на нескольких таймфреймах;
- отдаёт результат как **soft feature** в `FeatureBuilder` → `ProbabilityEngine` (не блокирующий гейт);
- визуализируется в `web/server.py` дашборде как оверлей для ручной проверки конфликтов ICT-сигнала с волновой структурой;
- пишет диагностику в `DecisionTrace` для последующего офлайн-анализа (даёт ли учёт волн прирост winrate).

---

## 2. Термины и жёсткие правила (кодифицировать буквально)

Волна нумеруется внутри **сегмента** — последовательности swing-точек между двумя разворотами старшего порядка. Для алгоритмической разметки используем **строгие правила** Эллиотта как hard-constraints самого алгоритма (не гейты бота, а условия валидности волнового счёта):

### 2.1 Импульс (5 волн, направление тренда)

- **Правило 1 (обязательное):** волна 2 не откатывается более чем на 100% волны 1 (не заходит за начальную точку волны 1).
- **Правило 2 (обязательное):** волна 3 не является самой короткой среди волн 1, 3, 5 (по цене, `abs(price_end - price_start)`).
- **Правило 3 (обязательное):** волна 4 не заходит в ценовую территорию волны 1 (`wave4.low > wave1.high` для бычьего импульса; кроме diagonal-паттернов — см. 2.3, для MVP diagonal не реализуем, помечаем как `pattern_type=unknown`).
- **Guideline (не hard, влияет только на confidence):** alternation между волной 2 и волной 4 (разная форма/глубина отката).
- **Guideline:** волна 5 ≈ волна 1 (±) или связана через Fibonacci extension (0.618 / 1.0 / 1.618 от волны 1, измеряется от конца волны 3 или волны 4 согласно правилу extension/failure).

### 2.2 Коррекция (3 волны, против тренда)

- MVP реализует только **zigzag (A-B-C)**: волна B не превышает 100% волны A (ретрейс), волна C обычно ≥ волны A.
- Flat и triangle — **out of scope MVP**, зарезервировать enum-значение `pattern_type` для будущего расширения, но не реализовывать сейчас.

### 2.3 Diagonal (клин)

Out of scope MVP. Зарезервировать в структуре данных, не реализовывать логику распознавания.

### 2.4 Степень (Degree)

Волновой счёт строится независимо на каждом из существующих таймфреймов бота (`PRIMARY_TIMEFRAMES=1h,4h` + HTF `1d`). Разные ТФ **не сливаются в один счёт** — каждый ТФ даёт свой независимый `WaveCount` с собственной confidence. Кросс-ТФ согласованность (совпадает ли направление на 1h и 4h) — отдельная **soft feature** `wave_htf_alignment: bool`, не более.

---

## 3. Архитектура решения

```
market_structure/
  swing_detector.py        <- НОВЫЙ, Этап 0 (унификация)
  elliott_wave.py           <- НОВЫЙ, Этап 2 (основной алгоритм)
  wave_types.py              <- НОВЫЙ, Этап 1 (dataclasses/enum)
  htf_bias.py                (без изменений)
  htf_bias_v2.py              (без изменений)
  structure.py               (правится: swing-детекция переезжает в swing_detector.py)

liquidity/
  sweep.py                   (правится: использует swing_detector.py вместо своего strict 2-neighbor)
  order_blocks.py            (правится: использует swing_detector.py вместо своего window=5)
  fvg.py                      (без изменений)

strategy/
  feature_builder.py         (правится: добавляются wave_* фичи)
  probability_engine.py      (правится: добавляется soft-вес wave_confidence)

web/
  server.py                  (правится: новый REST-эндпоинт + SVG/JSON оверлей волн)

storage/
  database.py                 (правится: добавляются колонки wave_* в decision_traces)

config/
  settings.py                 (правится: добавляются WAVE_* параметры)

tests/
  test_swing_detector.py     <- НОВЫЙ
  test_elliott_wave.py       <- НОВЫЙ
  test_wave_features.py      <- НОВЫЙ
```

---

## 4. Этап 0 — Унификация swing detection (ПРЕДВАРИТЕЛЬНОЕ УСЛОВИЕ)

Это блокирующий этап. Без него волновой алгоритм будет получать несогласованные точки от разных участков кода.

### 4.1 Проблема (зафиксировано в аудите)

- `liquidity/sweep.py` — strict 2-neighbor (сосед слева и справа ниже/выше)
- `liquidity/order_blocks.py` — rolling window=5 (max/min в окне)

Это два разных определения "swing point" в одной кодовой базе.

### 4.2 Решение

Создать `market_structure/swing_detector.py` с единой функцией:

```python
# market_structure/swing_detector.py

from dataclasses import dataclass
from enum import Enum
import pandas as pd

class SwingType(Enum):
    HIGH = "high"
    LOW = "low"

@dataclass(frozen=True)
class SwingPoint:
    index: int           # позиция в df (int, не timestamp)
    timestamp: pd.Timestamp
    price: float
    swing_type: SwingType
    strength: int         # кол-во баров подтверждения с каждой стороны (см. ниже)


def detect_swings(
    df: pd.DataFrame,
    left_bars: int = 2,
    right_bars: int = 2,
    price_col_high: str = "high",
    price_col_low: str = "low",
) -> list[SwingPoint]:
    """
    Единая функция определения swing-точек (fractal-логика Билла Вильямса,
    обобщённая на произвольное кол-во баров слева/справа).

    Точка i является SwingType.HIGH, если high[i] > high[i-left_bars:i]
    и high[i] > high[i+1:i+right_bars+1] (строго).
    Аналогично для LOW с price_col_low.

    left_bars/right_bars=2 воспроизводит классический 5-баровый фрактал Вильямса.
    left_bars/right_bars=5 воспроизводит текущее поведение order_blocks.py (для
    обратной совместимости на переходный период, см. 4.4).

    ВАЖНО: функция должна работать ТОЛЬКО на df, где последняя (незакрытая)
    свеча уже удалена вызывающим кодом (как это уже делает exchange_client.py:305).
    Не делать df.iloc[:-1] внутри этой функции — это ответственность вызывающего.
    """
    ...


def filter_significant_swings(
    swings: list[SwingPoint],
    df: pd.DataFrame,
    min_atr_multiple: float = 0.5,
    atr_col: str = "atr",
) -> list[SwingPoint]:
    """
    Фильтрует незначимые swing-точки (шум) — оставляет только точки, где
    амплитуда движения от предыдущей swing-точки того же/противоположного
    типа >= min_atr_multiple * ATR на момент точки.

    Это нужно, чтобы волновой алгоритм не пытался размечать волны на
    полуторасвечных зигзагах.
    """
    ...
```

### 4.3 Конфиг (`config/settings.py`)

```python
SWING_LEFT_BARS: int = int(os.getenv("SWING_LEFT_BARS", 2))
SWING_RIGHT_BARS: int = int(os.getenv("SWING_RIGHT_BARS", 2))
SWING_MIN_ATR_MULTIPLE: float = float(os.getenv("SWING_MIN_ATR_MULTIPLE", 0.5))
```

### 4.4 Миграция существующего кода

- `sweep.py`: заменить внутреннюю strict 2-neighbor логику на вызов `detect_swings(df, left_bars=2, right_bars=2)`. Прогнать `test_liquidity.py` — если тесты завязаны на конкретные числовые фикстуры, ожидаемые значения не должны измениться (2-neighbor и left=2/right=2 эквивалентны), но перепроверить построчно.
- `order_blocks.py`: заменить window=5 логику на `detect_swings(df, left_bars=5, right_bars=5)` — **это осознанно НЕ унифицирует параметры между sweep.py и order_blocks.py**, потому что они решают разные задачи (sweep ищет более "быстрые" развороты, OB — более крупные структурные). Унифицируется только **реализация**, не обязательно **параметры**. Задокументировать это явно в docstring обоих файлов, чтобы не было соблазна "довести унификацию до конца" неправильно.
- Добавить regression-тест `test_swing_detector.py`, сравнивающий вывод новой функции со старыми реализациями на исторических фикстурах (если такие фикстуры уже есть в `test_liquidity.py`).

**Критерий готовности этапа 0:** `pytest tests/test_liquidity.py tests/test_swing_detector.py` — всё зелёное, дублирование `_to_datetime` заодно тоже устранить (вынести в `market_structure/swing_detector.py` или отдельный `utils/time_utils.py`), т.к. это тот же рефакторинг по месту.

---

## 5. Этап 1 — Типы данных (`market_structure/wave_types.py`)

```python
from dataclasses import dataclass, field
from enum import Enum

class WaveLabel(Enum):
    W1 = "1"; W2 = "2"; W3 = "3"; W4 = "4"; W5 = "5"
    WA = "A"; WB = "B"; WC = "C"
    UNKNOWN = "unknown"

class WaveDegree(Enum):
    # используем нейтральные ярлыки степени вместо классических
    # (Grand Supercycle...Subminuette), т.к. бот работает на 1h/4h/1d —
    # абсолютная классика Эллиотта тут не имеет практического смысла
    HTF = "htf"      # соответствует 1d
    PRIMARY = "primary"  # соответствует 4h
    MINOR = "minor"      # соответствует 1h

class PatternType(Enum):
    IMPULSE = "impulse"
    ZIGZAG = "zigzag"
    DIAGONAL = "diagonal"   # reserved, not implemented in MVP
    FLAT = "flat"            # reserved, not implemented in MVP
    TRIANGLE = "triangle"    # reserved, not implemented in MVP
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class WaveSegment:
    label: WaveLabel
    start_index: int
    end_index: int
    start_price: float
    end_price: float
    start_timestamp: "pd.Timestamp"
    end_timestamp: "pd.Timestamp"

    @property
    def length(self) -> float:
        return abs(self.end_price - self.start_price)

    @property
    def direction(self) -> int:
        return 1 if self.end_price > self.start_price else -1

@dataclass(frozen=True)
class WaveCount:
    pattern_type: PatternType
    degree: WaveDegree
    segments: list[WaveSegment]
    confidence: float               # 0.0-1.0
    is_valid: bool                  # прошёл ли hard-rules (2.1)
    violated_rules: list[str] = field(default_factory=list)
    fib_targets: dict[str, float] = field(default_factory=dict)  # напр. {"wave5_0.618": 43120.5}
    current_wave: WaveLabel = WaveLabel.UNKNOWN  # какая волна сейчас формируется (последний открытый сегмент)

@dataclass(frozen=True)
class WaveAnalysisResult:
    symbol: str
    timeframe: str
    primary_count: WaveCount | None
    alternate_counts: list[WaveCount]   # максимум 2, отсортированы по confidence убыв.
    computed_at: "pd.Timestamp"
```

---

## 6. Этап 2 — Алгоритм разметки (`market_structure/elliott_wave.py`)

### 6.1 Публичный интерфейс

```python
def analyze_waves(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    degree: WaveDegree,
    max_lookback_bars: int = 300,
) -> WaveAnalysisResult:
    """
    Точка входа. Возвращает WaveAnalysisResult с primary_count и
    до 2 alternate_counts. Никогда не бросает исключение наружу —
    при любой внутренней ошибке возвращает WaveAnalysisResult с
    primary_count=None (вызывающий код должен это обрабатывать как
    "волновой анализ недоступен", НЕ как BLOCK).
    """
```

### 6.2 Алгоритм пошагово (детерминированный, без "на глаз")

Это ключевая часть — агент должен реализовать ИМЕННО эту последовательность шагов, без отступлений:

1. **Получить swing-точки** через `swing_detector.detect_swings()` + `filter_significant_swings()` (параметры — `SWING_LEFT_BARS`/`SWING_RIGHT_BARS`/`SWING_MIN_ATR_MULTIPLE` из конфига, degree-специфичные — см. 6.3).
2. **Построить список кандидатов-сегментов**: каждая пара последовательных swing-точек разного типа (HIGH→LOW или LOW→HIGH) — это один потенциальный "leg" (нога).
3. **Sliding window по 5 последовательным ногам** (для impulse) — для каждого окна из 5 ног, начинающегося на каждой найденной swing-точке:
   a. Присвоить метки 1-2-3-4-5 по порядку.
   b. Проверить hard rules (2.1, правила 1-3). Если хоть одно нарушено — `is_valid=False`, это НЕ отбрасывается сразу, а сохраняется как кандидат с `violated_rules` (нужно для диагностики), но не участвует в топ-3 отборе.
4. **Sliding window по 3 ногам** (для zigzag A-B-C) — аналогично, с правилами 2.2.
5. **Скоринг валидных кандидатов** (только `is_valid=True`) для расчёта `confidence`:
   - Fibonacci-соответствие волны 3 к волне 1 (лучше, если в диапазоне 1.618±0.15 или 2.618±0.2) — вес 0.3
   - Fibonacci-соответствие волны 2 к волне 1 (0.5 или 0.618 ретрейс, ±0.1) — вес 0.2
   - Соответствие волны 4 к волне 3 (0.236/0.382/0.5 ретрейс, ±0.1) — вес 0.2
   - Alternation между волной 2 и 4 (эвристика: разное кол-во баров в сегменте ±30%) — вес 0.15
   - Кол-во подтверждающих баров у крайних swing-точек (`strength` из `SwingPoint`) — вес 0.15
   - Итоговый `confidence = сумма взвешенных компонент`, clamp [0.0, 1.0]
6. **Определить `current_wave`**: последний сегмент кандидата, у которого `end_index` — это последняя известная swing-точка (т.е. волна, которая **ещё формируется**, а не последняя завершённая).
7. **Отобрать top-3** валидных кандидата по `confidence` (impulse и zigzag конкурируют в общем пуле) → `primary_count` = топ-1, `alternate_counts` = топ-2 и топ-3 (если есть).
8. **Рассчитать `fib_targets`** для primary_count: если текущая волна — 3, посчитать проекции для завершения 3 и старта 4; если текущая волна — 5, посчитать проекции завершения импульса (потенциальный разворот) — записать как `dict[str, float]` с понятными ключами (`"wave3_end_1.618"`, `"wave5_end_1.0"` и т.п.).
9. Если ни один кандидат не прошёл hard rules — вернуть `primary_count=None`, `alternate_counts=[]`, залогировать через `loguru` на уровне `DEBUG` (не `WARNING`/`ERROR` — отсутствие валидного счёта это нормальная ситуация, а не ошибка).

### 6.3 Degree-специфичные параметры swing-детекции

| Degree | Timeframe | left_bars/right_bars | min_atr_multiple |
|---|---|---|---|
| HTF | 1d | 3 | 0.8 |
| PRIMARY | 4h | 2 | 0.6 |
| MINOR | 1h | 2 | 0.4 |

Вынести в `.env`:
```python
WAVE_SWING_PARAMS = {
    "htf": {"left_bars": 3, "right_bars": 3, "min_atr_multiple": 0.8},
    "primary": {"left_bars": 2, "right_bars": 2, "min_atr_multiple": 0.6},
    "minor": {"left_bars": 2, "right_bars": 2, "min_atr_multiple": 0.4},
}
```
(можно хардкодить как dict в settings.py — не обязательно per-key env var, так как это структура, а не скаляр; но значения должны быть в одном месте, не разбросаны по коду).

### 6.4 Производительность

`max_lookback_bars=300` — ограничение, чтобы sliding window по всем комбинациям не давал комбинаторного взрыва на длинной истории. При `CANDLES_LIMIT=200` (уже стоит в конфиге, п.2.2 аудита) это ограничение почти всегда no-op, но должно быть явным параметром на случай будущего увеличения лимита свечей.

---

## 7. Этап 3 — Интеграция в `FeatureBuilder`

В `strategy/feature_builder.py` добавить (не изменяя существующие ~40 фич, только добавление):

```python
# Новые soft-фичи (не влияют на гейты!)
"wave_pattern_type": str,        # "impulse" | "zigzag" | "unknown"
"wave_current_label": str,        # "1".."5" | "A".."C" | "unknown"
"wave_confidence": float,         # 0.0-1.0
"wave_is_valid": bool,
"wave_htf_alignment": bool,       # совпадает ли направление между degree=htf и degree=primary
"wave_conflict_with_ict": bool,   # см. 7.1
"wave_target_fib_nearest": float | None,  # ближайший fib target к текущей цене
```

Вызов `analyze_waves()` — три раза (htf/primary/minor) для символа, кэшировать результат так же, как уже кэшируется контекст (`CONTEXT_CACHE_TTL_SECONDS`, п.8.1 аудита) — добавить `WAVE_CACHE_TTL_SECONDS` (дефолт 900, т.к. волны на 1h не имеет смысла пересчитывать каждые 15 минут заново без новой закрытой свечи).

### 7.1 Определение `wave_conflict_with_ict`

Флаг `True`, если одновременно:
- ICT-сигнал направления BUY, а `wave_current_label` в primary_count равен `"3"` или `"5"` для **медвежьего** impulse (т.е. ICT предполагает разворот вверх ровно там, где волновой счёт говорит "мы всё ещё внутри падающего импульса")
- ИЛИ ICT-сигнал направления SELL при аналогичной зеркальной ситуации для бычьего impulse

Этот флаг **не блокирует сигнал**. Он только пишется в `DecisionTrace` и отображается в Telegram-сообщении (см. Этап 5) и на дашборде.

---

## 8. Этап 4 — Интеграция в `ProbabilityEngine`

В `strategy/probability_engine.py`, там где уже есть веса компонент (аудит п.7.2: "Веса компонент (3.0, 4.0, 1.5...)"), добавить **новый компонент с малым весом** (не доминирующий):

```python
WAVE_CONFIDENCE_WEIGHT = float(os.getenv("WAVE_CONFIDENCE_WEIGHT", 1.0))  # для сравнения: существующие веса 1.5-4.0
WAVE_CONFLICT_PENALTY = float(os.getenv("WAVE_CONFLICT_PENALTY", 0.85))  # множитель, не hard block — по аналогии с htf_bias_penalty=0.85 (scanner.py)
```

Правило: если `wave_conflict_with_ict=True` — итоговый P(TP) домножается на `WAVE_CONFLICT_PENALTY` (как мягкий штраф, аналогично существующему паттерну `htf_bias_penalty` в scanner.py:466-477). Если `wave_confidence` низкий (`< 0.4`) — компонент не учитывается вовсе (не штраф и не бонус, нейтрально), потому что низкая confidence означает "волновой анализ не даёт полезного сигнала здесь", а не "волновой анализ говорит против сделки".

**Важно:** это изменение затрагивает существующую формулу скоринга. Перед мержем — прогнать `test_new_pipeline.py` и убедиться, что дефолтный `WAVE_CONFIDENCE_WEIGHT` не сдвигает исторические P(TP) больше чем на условные 2-3 п.п. на бэктест-выборке (если бэктест недоступен — хотя бы прогнать на последних N сохранённых `decision_traces` из БД и сравнить старые/новые P(TP) оффлайн-скриптом, не мержить вслепую).

---

## 9. Этап 5 — DecisionTrace и Telegram

### 9.1 `storage/database.py`

Добавить колонки в таблицу `decision_traces` (миграция через существующий `PRAGMA table_info` подход, п.10.4 аудита — учитывая, что это SQLite-specific, задокументировать это же ограничение и здесь, не создавать новых миграционных проблем):

```
wave_pattern_type TEXT
wave_current_label TEXT
wave_confidence REAL
wave_conflict_with_ict INTEGER  -- boolean as 0/1
wave_degree_alignment INTEGER
```

### 9.2 Telegram-сообщение (`signal_engine.py:format_message`)

Добавить одну необязательную строку в существующий шаблон (только если `wave_confidence >= 0.4`, иначе не засорять сообщение):

```
Wave: {pattern_type} волна {current_label} (conf {confidence}%){conflict_marker}
```
где `conflict_marker` = ` ⚠️ конфликт с ICT-структурой`, если `wave_conflict_with_ict=True`, иначе пусто.

---

## 10. Этап 6 — Web-дашборд

В `web/server.py` (учесть, что он сейчас без auth — п.10.4/7.3 аудита; **не решать проблему auth в рамках этой задачи**, это отдельный тикет, но не увеличивать площадь атаки сверх необходимого: новый эндпоинт read-only, GET, без побочных эффектов):

```
GET /api/waves/{symbol}/{timeframe}
```
Возвращает JSON `WaveAnalysisResult` (primary + alternates), включая координаты сегментов для отрисовки на фронтенде поверх свечного графика.

Фронтенд (там, где уже рисуется график — уточнить у существующего фронтенд-кода `web/`, если есть React/canvas-компонент): нарисовать primary_count сплошной линией с подписями 1-2-3-4-5/A-B-C, alternate_counts — пунктиром более бледным цветом. При наведении на волну — тултип с `confidence` и `violated_rules` (для primary_count это всегда пустой список, но полезно для отладки, если решите показывать invalid-кандидатов тоже).

---

## 11. Конфигурация — полный список новых параметров `.env`

```bash
# Swing detection (унификация)
SWING_LEFT_BARS=2
SWING_RIGHT_BARS=2
SWING_MIN_ATR_MULTIPLE=0.5

# Elliott Wave module
WAVE_ANALYSIS_ENABLED=true
WAVE_CACHE_TTL_SECONDS=900
WAVE_MAX_LOOKBACK_BARS=300
WAVE_CONFIDENCE_WEIGHT=1.0
WAVE_CONFLICT_PENALTY=0.85
WAVE_MIN_CONFIDENCE_TO_DISPLAY=0.4
```

`WAVE_ANALYSIS_ENABLED=false` должен полностью отключать: вызов `analyze_waves()`, добавление wave_* фич (со значениями по умолчанию/None), строку в Telegram, и эндпоинт дашборда должен возвращать `503` с понятным сообщением — а не падать с исключением.

---

## 12. Порядок реализации (для агента, строго последовательно)

1. Этап 0: `swing_detector.py` + миграция `sweep.py`/`order_blocks.py` + тесты. **Стоп, пока тесты не зелёные.**
2. Этап 1: `wave_types.py` (только структуры данных, без логики) + базовые тесты создания объектов.
3. Этап 2: `elliott_wave.py` — сначала написать `test_elliott_wave.py` с фикстурами (минимум: 1 датасет с чистым 5-волновым импульсом, 1 с невалидной волной 3 самой короткой — должен вернуть `is_valid=False`, 1 с волной 2 заходящей за 100% — то же самое, 1 с чистым zigzag ABC). Затем реализовать `analyze_waves()` до прохождения тестов.
4. Этап 3: `feature_builder.py` — добавить wave_* фичи, тесты на то, что при `WAVE_ANALYSIS_ENABLED=false` фичи не считаются (падают в None/default) и pipeline не падает.
5. Этап 4: `probability_engine.py` — добавить весовой компонент, offline-сравнение P(TP) до/после на исторических traces из БД (см. 8, предупреждение про 2-3 п.п.).
6. Этап 5: `database.py` миграция + `signal_engine.py` шаблон сообщения.
7. Этап 6: `web/server.py` эндпоинт + фронтенд-оверлей.
8. Финально: полный `pytest`, ручной прогон `scan_symbol_v2()` на тестовом символе в dry-run, проверить в логах, что при `WAVE_ANALYSIS_ENABLED=true` гейты ICT по-прежнему отрабатывают идентично (diff двух прогонов с флагом true/false на одних и тех же исторических данных — количество и содержание сигналов ДОЛЖНО совпадать, различаться может только наличие wave_* полей и текст Telegram-сообщения).

---

## 13. Definition of Done

- [ ] Все тесты зелёные (`pytest`), включая новые и уже существующие
- [ ] `WAVE_ANALYSIS_ENABLED=false` не меняет поведение существующего pipeline ни на бит (verified by diff)
- [ ] Волновой модуль никогда не бросает необработанное исключение наружу в `scanner.py`
- [ ] Ни один существующий ICT-гейт не читает и не зависит от wave_* фич
- [ ] `.env.example` обновлён новыми параметрами с комментариями
- [ ] `AGENTS.md` (если используется в проекте, судя по ссылкам в аудите) дополнен разделом про Elliott Wave module с пометкой "soft feature, non-blocking"
- [ ] Дашборд отдаёт 503 при `WAVE_ANALYSIS_ENABLED=false`, а не 500
- [ ] Offline-сравнение P(TP) до/после интеграции в `ProbabilityEngine` задокументировано (даже если решение — оставить `WAVE_CONFIDENCE_WEIGHT=0` до накопления статистики)

---

## 14. Явные ограничения MVP (не реализовывать сейчас)

- Flat, Triangle, Diagonal паттерны — только enum-заглушки
- Классические степени волн (Grand Supercycle и т.д.) — не используются, только 3 плоских degree (htf/primary/minor)
- Автоматический hard-block на основании волнового конфликта — **никогда**, если явно не будет отдельного ТЗ после накопления статистики (см. п.8 предыдущего обсуждения — "только после набора статистики решать, стоит ли превращать это в гейт")
- Мультитаймфреймовое "склеивание" одного счёта в единую иерархию степеней (то, что в классике называется "wave of higher degree contains wave of lower degree" с формальной привязкой) — не реализуется, три degree считаются независимо
