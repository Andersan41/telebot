# Plan 17 — Scenario Engine & Decision Intelligence (v2)

**Status:** Draft
**Date:** 2026-07-06 (revised)
**Depends on:** plan/16-decision-intelligence.md (telemetry), current v2 pipeline

## Problem Statement

Текущая архитектура строит ОДНУ гипотезу и сразу принимает решение. ICT-трейдер мыслит сценариями: "рынок пытается сделать X, но может также Y или Z".

Ключевые принципы пересмотра:
- **Scenario — это "карта"**, а не "путешествие". Карта не меняется. Оценка карты — меняется.
- **TradeThesis — это "путешествие по карте"**. Живёт, развивается, завершается.
- **Probability Engine** выдаёт оценку. **WeightManager** корректирует. ML и логика остаются независимыми.
- **Per-Symbol Weights** — преждевременно без 300–500 закрытых сценариев на символ.

---

## Architecture Overview

```
Current:
  Pattern Engine → Feature Builder → Probability Engine → Risk Engine → Signal

Target:
  Market Phase Engine → Scenario Engine → Probability Engine → Risk Engine → Trade Thesis
         │                    │                  │
         │                    │                  ├── P(Scenario A) = 68%  ← ScenarioEvaluation
         │                    │                  ├── P(Scenario B) = 24%
         │                    │                  └── P(Scenario C) = 8%
         │                    │
         │                    ├── Scenario A (immutable "map")
         │                    ├── Scenario B
         │                    └── Scenario C
         │
         ├── Market Phase (Accumulation / Distribution / Trend / ...)
         │
         └── LiquidityGraph with Node State Machine (6 states)
```

---

## Stage 1: Market Phase Engine

**Цель:** Определить текущий фазу рынка ДО построения сценариев. Один и тот же Bullish OB работает по-разному в Expansion и Distribution.

### 1.1 Market Phases

```python
class MarketPhase(Enum):
    """Текущая фаза рынка."""
    ACCUMULATION = "accumulation"     # боковик, накопление позиций
    DISTRIBUTION = "distribution"     # боковик, распределение
    EXPANSION = "expansion"           # сильное направленное движение
    TREND_UP = "trend_up"             # восходящий тренд
    TREND_DOWN = "trend_down"         # нисходящий тренд
    MITIGATION = "mitigation"         # откат, возврат к уровню
    COMPRESSION = "compression"       # сужение диапазона (предшествует расширению)
    REVERSAL = "reversal"             # разворот


@dataclass
class PhaseAssessment:
    """Оценка фазы рынка."""
    phase: MarketPhase
    confidence: float           # 0..1
    duration_bars: int          # сколько свечей в этой фазе
    sub_phases: list[MarketPhase]  # возможные подфазы (compression → expansion)

    # Метрики, на основе которых определена фаза
    adx: float = 0.0
    atr_ratio: float = 0.0     # ATR текущий / ATR средний
    range_pct: float = 0.0     # ширина диапазона за N свечей
    volume_trend: float = 0.0  # тренд объёма
    displacement_freq: int = 0 # частота displacement свечей
```

### 1.2 Phase Detection Logic

```python
class MarketPhaseEngine:
    """Определяет фазу рынка по индикаторам и структуре."""

    def assess(self, df: pd.DataFrame, indicators: IndicatorSet, structure: MarketStructure) -> PhaseAssessment:
        """
        Алгоритм:
        1. ADX > 25 + направленная EMA → Trend
        2. ADX < 20 + узкий диапазон → Compression
        3. ATR растёт + displacement свечи → Expansion
        4. ADX 20-25 + боковик → Accumulation/Distribution
        5. BOS/CHoCH после тренда → Reversal
        6. Откат к OB/FVG после расширения → Mitigation
        """
        adx = indicators.adx or 0
        atr_current = indicators.atr or 0
        atr_avg = self._avg_atr(df, period=50)
        atr_ratio = atr_current / atr_avg if atr_avg > 0 else 1.0

        # Определение фазы
        if adx > 25:
            if structure.last_bos and structure.last_bos.direction == "up":
                return PhaseAssessment(MarketPhase.TREND_UP, confidence=0.8, ...)
            else:
                return PhaseAssessment(MarketPhase.TREND_DOWN, confidence=0.8, ...)

        if adx < 18 and atr_ratio < 0.8:
            return PhaseAssessment(MarketPhase.COMPRESSION, confidence=0.7, ...)

        if atr_ratio > 1.3 and displacement_count >= 2:
            return PhaseAssessment(MarketPhase.EXPANSION, confidence=0.75, ...)

        # ... etc
```

### 1.3 Phase → Scenario Modifier

Фаза не блокирует сценарии — она **модифицирует** их оценку:

```python
PHASE_MODIFIERS = {
    # фаза: {тип_сценария: множитель}
    MarketPhase.EXPANSION: {
        "sweep_bos_ob": 1.2,   # sweep → BOS → OB работает лучше в расширении
        "choch_ob": 0.8,       # CHoCH → OB хуже работает в сильном тренде
    },
    MarketPhase.COMPRESSION: {
        "sweep_bos_ob": 1.0,   # нормально
        "choch_ob": 1.1,       # CHoCH может дать хороший breakout
    },
    MarketPhase.MITIGATION: {
        "ob_retest": 1.3,      # retest OB — лучший сценарий в фазе mitigation
        "sweep_bos_ob": 0.9,
    },
    MarketPhase.DISTRIBUTION: {
        "sweep_bos_ob": 0.7,   # бычьи сценарии хуже в distribution
        "bearish_choch": 1.2,  # медвежьи — лучше
    },
}
```

### 1.4 Changes Required

| File | Change |
|------|--------|
| `strategy/market_phase_engine.py` | **NEW** — MarketPhaseEngine, MarketPhase, PhaseAssessment |
| `strategy/scenario_engine.py` | Принимает PhaseAssessment, применяет модификаторы |
| `strategy/probability_engine.py` | Учитывает фазу при оценке |
| `tests/test_market_phase.py` | **NEW** |

---

## Stage 2: Node State Machine (Simplified)

**Цель:** Каждый LiquidityNode имеет жизненный цикл из 6 состояний.

### 2.1 States

| State | Описание |
|-------|----------|
| `created` | Нода только что обнаружена |
| `active` | Нода активна, цена не касалась |
| `tested` | Цена коснулась уровня (retest) |
| `mitigated` | Уровень mitigated (OB съеден, FVG заполнен) |
| `broken` | Уровень сломан (цена прошла сквозь) |
| `stale` | Устарела (age > порога) |

```
created → active → tested → mitigated
                  → broken
                  → stale
```

**Без** `partially_mitigated`, `reactivated`, `invalidated`, `completed`, `swept`, `filled`. Шесть состояний — достаточно.

### 2.2 Implementation

```python
class NodeStateMachine:
    TRANSITIONS = {
        "created":  ["active", "stale"],
        "active":   ["tested", "mitigated", "broken", "stale"],
        "tested":   ["mitigated", "broken", "stale"],
        "mitigated": [],
        "broken":   [],
        "stale":    [],
    }

    def transition(self, node: LiquidityNode, new_state: str, bar: int, reason: str = "") -> bool:
        if new_state not in self.TRANSITIONS.get(node.state, []):
            return False
        old = node.state
        node.state = new_state
        node.last_updated = bar
        node.transition_history.append(NodeTransition(old=old, new=new_state, bar=bar, reason=reason))
        return True
```

### 2.3 Node Metadata

```python
@dataclass
class NodeTransition:
    old: str
    new: str
    bar: int
    reason: str

# В LiquidityNode:
transition_history: list[NodeTransition] = field(default_factory=list)
times_tested: int = 0
age_bars: int = 0
```

### 2.4 Price-Based Detection (on each candle)

```python
def detect_state_transitions(graph: LiquidityGraph, candle: dict, bar: int):
    sm = NodeStateMachine()
    for node in graph.alive_nodes():
        if node.type == "ob":
            if node.low <= candle["low"] <= node.high:
                sm.transition(node, "tested", bar, "wick into OB")
            if candle["close"] < node.low or candle["close"] > node.high:
                sm.transition(node, "broken", bar, "close outside OB")
        elif node.type == "fvg":
            if candle["low"] <= node.high and candle["high"] >= node.low:
                sm.transition(node, "mitigated", bar, "FVG filled")
        elif node.type in ("swing_high", "equal_high"):
            if candle["high"] > node.price:
                sm.transition(node, "broken", bar, "sweep above")
        elif node.type in ("swing_low", "equal_low"):
            if candle["low"] < node.price:
                sm.transition(node, "broken", bar, "sweep below")
```

### 2.5 Changes Required

| File | Change |
|------|--------|
| `strategy/market_thesis_engine.py` | Replace current state constants with 6-state system, add `NodeStateMachine`, `NodeTransition` |
| `strategy/market_thesis_engine.py` | Add `detect_state_transitions()` in `update_on_candle()` |
| `tests/test_node_state.py` | **NEW** |

---

## Stage 3: Scenario Engine

**Цель:** Генерировать конкурирующие сценарии. Scenario — иммутабельная "карта". Оценка — отдельный объект.

### 3.1 Scenario (Immutable)

```python
@dataclass(frozen=True)
class MarketScenario:
    """Рыночный сценарий — иммутабельная "карта"."""
    id: str
    direction: Literal["buy", "sell"]
    name: str                              # "Sweep + BOS + OB + FVG"
    description: str

    # Components (ordered sequence of expected events)
    components: tuple[ScenarioComponent, ...]  # tuple, не list — immutable

    # Path (immutable price levels)
    entry_zone: tuple[float, float]       # (low, high)
    invalidation_price: float             # SL
    target_price: float                   # TP
    rr_ratio: float

    # Metadata
    market_phase: Optional[str] = None    # фаза рынка на момент создания
    created_at_bar: int = 0

    # НЕТ: probability, confidence, status — это оценка, а не свойство сценария


@dataclass(frozen=True)
class ScenarioComponent:
    """Один шаг в сценарии — immutable."""
    id: str
    type: str          # "sweep", "bos", "ob", "fvg", "external_liq", "choch"
    description: str
    node_id: Optional[str] = None
    price_level: Optional[float] = None
    is_critical: bool = True
```

### 3.2 ScenarioEvaluation (Mutable)

```python
@dataclass
class ScenarioEvaluation:
    """Оценка сценария — Mutable. Меняется при каждом обновлении."""
    scenario_id: str

    probability: float = 0.0       # P(scenario) — 0..1
    confidence: float = 0.0        # насколько уверены в оценке
    expected_rr: float = 0.0
    profit_factor: float = 0.0

    # Компонентные оценки
    component_scores: dict[str, float] = field(default_factory=dict)

    # Модель
    model_type: str = "rules"      # "rules" / "xgboost"
    model_version: str = "1.0"

    # Timestamp
    evaluated_at_bar: int = 0

    @property
    def quality_label(self) -> str:
        if self.probability >= 0.65:
            return "strong"
        elif self.probability >= 0.50:
            return "moderate"
        return "weak"
```

### 3.3 ScenarioEngine

```python
class ScenarioEngine:
    """Генерирует конкурирующие рыночные сценарии."""

    def detect_scenarios(
        self,
        graph: LiquidityGraph,
        structure: MarketStructure,
        phase: PhaseAssessment,
        direction: Optional[str] = None,
    ) -> list[MarketScenario]:
        """
        1. Собрать активные компоненты из графа
        2. Сгенерировать варианты (buy + sell)
        3. Для каждого: построить путь, определить entry/SL/TP
        4. Отсортировать по количеству компонентов и качеству

        НЕ оценивает probability — это задача ProbabilityEngine.
        """
        scenarios = []

        if direction in (None, "buy"):
            scenarios.extend(self._build_buy_scenarios(graph, structure, phase))
        if direction in (None, "sell"):
            scenarios.extend(self._build_sell_scenarios(graph, structure, phase))

        # Сортировка по количеству компонентов (больше компонентов = лучше проработанный)
        scenarios.sort(key=lambda s: len(s.components), reverse=True)

        return scenarios

    def _build_buy_scenarios(self, graph, structure, phase) -> list[MarketScenario]:
        """Build bullish scenarios from active graph nodes."""
        alive = graph.alive_nodes()
        sweeps = [n for n in alive if n.type == "sweep" and n.is_bullish]
        boses = [n for n in alive if n.type == "bos" and n.is_bullish]
        obs = [n for n in alive if n.type == "ob" and n.is_bullish]
        fvgs = [n for n in alive if n.type == "fvg" and n.is_bullish]
        chochs = [n for n in alive if n.type == "choch" and n.is_bullish]

        scenarios = []

        # Pattern: Sweep → BOS → OB → FVG → External
        for sweep in sweeps:
            for bos in boses:
                if bos.created_at <= sweep.created_at:
                    continue
                for ob in obs:
                    if ob.created_at <= bos.created_at:
                        continue
                    for fvg in fvgs:
                        nodes = [sweep, bos, ob, fvg]
                        scenarios.append(self._compose("buy", "Sweep+BOS+OB+FVG", nodes, phase))

        # Pattern: Sweep → BOS → OB (without FVG)
        for sweep in sweeps:
            for bos in boses:
                if bos.created_at <= sweep.created_at:
                    continue
                for ob in obs:
                    if ob.created_at <= bos.created_at:
                        continue
                    scenarios.append(self._compose("buy", "Sweep+BOS+OB", [sweep, bos, ob], phase))

        # Pattern: CHoCH → OB
        for choch in chochs:
            for ob in obs:
                if ob.created_at <= choch.created_at:
                    continue
                scenarios.append(self._compose("buy", "CHoCH+OB", [choch, ob], phase))

        # Pattern: OB Retest (tested node → retest)
        for ob in obs:
            if ob.state == "tested":
                scenarios.append(self._compose("buy", "OB Retest", [ob], phase))

        return scenarios

    def _compose(self, direction, name, nodes, phase) -> MarketScenario:
        components = tuple(
            ScenarioComponent(
                id=f"{name}_{i}",
                type=n.type,
                description=f"{n.type} @ {n.price:.4f}",
                node_id=f"{n.type}_{n.price:.6f}",
                price_level=n.price,
                is_critical=(i < 2),
            )
            for i, n in enumerate(nodes)
        )

        entry = self._compute_entry(nodes, direction)
        sl = self._compute_invalidation(nodes, direction)
        tp = self._compute_target(nodes, direction)
        rr = abs(tp - entry) / abs(entry - sl) if sl and tp and entry else 0

        return MarketScenario(
            id=f"{direction}_{name}_{nodes[0].price:.4f}",
            direction=direction,
            name=name,
            description=f"{direction.upper()}: " + " → ".join(c.description for c in components),
            components=components,
            entry_zone=(entry * 0.999, entry * 1.001) if entry else (0, 0),
            invalidation_price=sl or 0,
            target_price=tp or 0,
            rr_ratio=rr,
            market_phase=phase.phase.value if phase else None,
        )
```

### 3.4 Changes Required

| File | Change |
|------|--------|
| `strategy/scenario_engine.py` | **NEW** — ScenarioEngine, MarketScenario (frozen), ScenarioComponent (frozen), ScenarioEvaluation |
| `strategy/market_thesis_engine.py` | Убрать `detect_scenarios()` из MarketThesisEngine (перенести в ScenarioEngine) |
| `tests/test_scenario_engine.py` | **NEW** |

---

## Stage 4: Trade Thesis Lifecycle

**Цель:** Тезис живёт между сканами. Единственный объект с жизненным циклом.

### 4.1 Thesis States

```
forming → observed → confirmed → activated → executing → closed
    ↓         ↓          ↓           ↓          ↓
  expired   expired    failed      failed     failed
```

| State | Описание |
|-------|----------|
| `forming` | Тезис формируется (сценарии конкурируют) |
| `observed` | Тезис сформирован, наблюдаем |
| `confirmed` | Все критические компоненты подтверждены |
| `activated` | Цена вошла в entry zone |
| `executing` | Сделка активна |
| `closed` | Позиция закрыта (win/loss/breakeven) |
| `failed` | Тезис не реализовался |
| `expired` | Устарел без активации |

### 4.2 TradeThesis

```python
@dataclass
class TradeThesis:
    """Торговый тезис — единственный объект с lifecycle."""
    id: str
    symbol: str
    timeframe: str

    # Core
    scenario: MarketScenario
    evaluation: ScenarioEvaluation    # отдельный объект оценки
    direction: str

    # Lifecycle
    status: str = "forming"
    created_at: datetime = field(default_factory=datetime.utcnow)
    observed_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    activated_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None

    # Trade parameters (from scenario)
    entry_zone: Optional[tuple] = None
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    rr_ratio: float = 0.0

    # Tracking
    current_price: float = 0.0
    update_count: int = 0
    last_update_bar: int = 0
    history: list[ThesisSnapshot] = field(default_factory=list)

    # Performance
    pnl_pct: Optional[float] = None
    outcome: Optional[str] = None  # "win" / "loss" / "breakeven"
    hold_bars: int = 0

    @property
    def is_active(self) -> bool:
        return self.status not in ("closed", "failed", "expired")

    @property
    def is_tradeable(self) -> bool:
        return self.status in ("confirmed", "activated") and self.evaluation.probability >= 0.5

    @property
    def age_bars(self) -> int:
        return self.update_count


@dataclass
class ThesisSnapshot:
    bar: int
    price: float
    probability: float
    status: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
```

### 4.3 TradeThesisManager

```python
class TradeThesisManager:
    def __init__(self, max_theses: int = 50):
        self.theses: dict[str, TradeThesis] = {}
        self.max_theses = max_theses

    def update(
        self,
        symbol: str,
        timeframe: str,
        scenarios: list[MarketScenario],
        evaluations: list[ScenarioEvaluation],
        bar: int,
        price: float,
    ):
        key = f"{symbol}_{timeframe}"
        existing = self.theses.get(key)

        if existing and existing.is_active:
            self._update_existing(existing, scenarios, evaluations, bar, price)
        else:
            self._create_new(key, symbol, timeframe, scenarios, evaluations, bar, price)

    def _update_existing(self, thesis, scenarios, evaluations, bar, price):
        # Обновить evaluation если сценарий тот же
        for s, e in zip(scenarios, evaluations):
            if s.id == thesis.scenario.id:
                thesis.evaluation = e
                break

        thesis.current_price = price
        thesis.update_count += 1
        thesis.last_update_bar = bar

        # Transition: confirmed → activated (price в entry zone)
        if thesis.status == "confirmed" and thesis.entry_zone:
            low, high = thesis.entry_zone
            if low <= price <= high:
                thesis.status = "activated"
                thesis.activated_at = datetime.utcnow()

        # Transition: activated → failed (SL hit)
        if thesis.status in ("activated", "executing") and thesis.sl_price:
            if (thesis.direction == "buy" and price <= thesis.sl_price) or \
               (thesis.direction == "sell" and price >= thesis.sl_price):
                thesis.status = "failed"
                thesis.failed_at = datetime.utcnow()

        # Transition: forming → expired
        if thesis.status == "forming" and thesis.update_count > 20:
            thesis.status = "expired"

        # Snapshot
        thesis.history.append(ThesisSnapshot(
            bar=bar, price=price,
            probability=thesis.evaluation.probability,
            status=thesis.status,
        ))

    def _create_new(self, key, symbol, timeframe, scenarios, evaluations, bar, price):
        if not scenarios:
            return
        best = scenarios[0]
        best_eval = evaluations[0] if evaluations else ScenarioEvaluation(scenario_id=best.id)

        if best_eval.probability < 0.5:
            return

        thesis = TradeThesis(
            id=f"{key}_{bar}",
            symbol=symbol,
            timeframe=timeframe,
            scenario=best,
            evaluation=best_eval,
            direction=best.direction,
            status="observed",
            entry_zone=best.entry_zone,
            sl_price=best.invalidation_price,
            tp_price=best.target_price,
            rr_ratio=best.rr_ratio,
            current_price=price,
            observed_at=datetime.utcnow(),
        )
        thesis.history.append(ThesisSnapshot(bar=bar, price=price, probability=best_eval.probability, status="observed"))
        self.theses[key] = thesis

    def get_active(self, symbol: Optional[str] = None) -> list[TradeThesis]:
        result = [t for t in self.theses.values() if t.is_active]
        if symbol:
            result = [t for t in result if t.symbol == symbol]
        return result
```

### 4.4 Changes Required

| File | Change |
|------|--------|
| `strategy/trade_thesis.py` | **NEW** — TradeThesis, ThesisSnapshot, TradeThesisManager |
| `scheduler/scanner.py` | интеграция TradeThesisManager |
| `storage/database.py` | таблица `trade_theses` |
| `tests/test_trade_thesis.py` | **NEW** |

---

## Stage 5: Probability Engine

**Цель:** Оценивает P(scenario). Не знает про веса символов. Выдаёт оценку — WeightManager корректирует.

### 5.1 Refactored Interface

```python
class ProbabilityEngine:
    """Оценивает P(scenario). Не знает про SymbolWeights."""

    def estimate_scenario(
        self,
        scenario: MarketScenario,
        features: SetupFeatures,
        graph: LiquidityGraph,
        phase: PhaseAssessment,
    ) -> ScenarioEvaluation:
        """
        1. Оценить каждый компонент
        2. Вычислить базовую вероятность
        3. Учесть фазу рынка
        4. Confidence
        """
        eval_ = ScenarioEvaluation(scenario_id=scenario.id)

        # Component scores
        for comp in scenario.components:
            node = graph.get_node(comp.node_id) if comp.node_id else None
            if node:
                eval_.component_scores[comp.id] = self._score_component(comp, node, features)

        # Base probability
        base_p = self._compute_base_probability(eval_.component_scores, scenario, features)

        # Phase modifier
        if scenario.market_phase:
            modifier = PHASE_MODIFIERS.get(MarketPhase(scenario.market_phase), {}).get(scenario.name, 1.0)
            base_p *= modifier

        # Clamp
        eval_.probability = max(0.1, min(0.85, base_p))
        eval_.expected_rr = scenario.rr_ratio
        eval_.profit_factor = self._estimate_pf(eval_.probability, scenario.rr_ratio)
        eval_.confidence = self._compute_confidence(eval_.component_scores, features)

        return eval_

    def rank_scenarios(
        self,
        scenarios: list[MarketScenario],
        features: SetupFeatures,
        graph: LiquidityGraph,
        phase: PhaseAssessment,
    ) -> list[tuple[MarketScenario, ScenarioEvaluation]]:
        """Оценить и отсортировать сценарии."""
        scored = []
        for s in scenarios:
            eval_ = self.estimate_scenario(s, features, graph, phase)
            scored.append((s, eval_))

        scored.sort(key=lambda x: x[1].probability, reverse=True)
        return scored
```

### 5.2 WeightManager (Separate Layer)

```python
class WeightManager:
    """Корректирует оценки Probability Engine на основе кумулятивной статистики.

    Не встраивается в Probability Engine — работает как отдельный слой.
    Probability выдаёт оценку → WeightManager корректирует.
    """

    def adjust(self, evaluation: ScenarioEvaluation, symbol: str, regime: str) -> ScenarioEvaluation:
        """Скорректировать оценку на основе статистики."""
        # Пока — заглушка (Per-Symbol Weights отложены)
        return evaluation

    # Когда будет достаточно данных:
    # def adjust(self, evaluation, symbol, regime):
    #     stats = self.scenario_memory.get_stats(symbol, evaluation.scenario_name)
    #     if stats and stats.sample_count >= 300:
    #         adjustment = stats.winrate * stats.avg_rr
    #         evaluation.probability *= adjustment
    #     return evaluation
```

### 5.3 ML Training (Deferred — after 100+ scenarios)

```python
class ScenarioMLTrainer:
    """Обучение ML модели для P(scenario)."""
    def build_dataset(self) -> pd.DataFrame:
        """Из trade_theses + decision_traces."""
        pass
    def train(self, X, y):
        """XGBoost classifier."""
        pass
```

### 5.4 Changes Required

| File | Change |
|------|--------|
| `strategy/probability_engine.py` | Рефакторинг: `estimate_scenario()`, `rank_scenarios()`, убрать SymbolWeights из параметров |
| `strategy/weight_manager.py` | **NEW** — WeightManager (заглушка, пока Per-Symbol Weights отложены) |
| `tests/test_probability_v2.py` | **NEW** |

---

## Stage 6: Scenario Memory

**Цель:** Хранить статистику по типам сценариев, а не просто по сделкам.

### 6.1 Scenario Stats

```python
@dataclass
class ScenarioStats:
    """Статистика по конкретному типу сценария."""
    scenario_name: str       # "Sweep+BOS+OB"
    symbol: str

    total_seen: int = 0          # сколько раз встречали
    total_activated: int = 0     # сколько раз активировали (вход в сделку)
    total_wins: int = 0
    total_losses: int = 0

    avg_rr: float = 0.0
    avg_hold_bars: float = 0.0

    @property
    def winrate(self) -> float:
        closed = self.total_wins + self.total_losses
        return self.total_wins / closed if closed > 0 else 0.0

    @property
    def expectancy(self) -> float:
        """Expectancy в R."""
        closed = self.total_wins + self.total_losses
        if closed == 0:
            return 0.0
        return (self.winrate * self.avg_rr) - (1 - self.winrate)

    @property
    def profit_factor(self) -> float:
        # Упрощённый PF
        return self.avg_rr * self.winrate / (1 - self.winrate) if self.winrate < 1.0 else float('inf')
```

### 6.2 ScenarioMemory

```python
class ScenarioMemory:
    """Хранит и запрашивает статистику по сценариям."""

    def __init__(self):
        self.stats: dict[str, ScenarioStats] = {}  # "symbol:scenario_name" -> ScenarioStats

    def record_outcome(self, symbol: str, scenario_name: str, outcome: str, rr: float, hold_bars: int):
        """Записать исход сценария."""
        key = f"{symbol}:{scenario_name}"
        if key not in self.stats:
            self.stats[key] = ScenarioStats(scenario_name=scenario_name, symbol=symbol)

        stats = self.stats[key]
        stats.total_activated += 1
        if outcome in ("win", "loss"):
            stats.total_seen += 1
            if outcome == "win":
                stats.total_wins += 1
            else:
                stats.total_losses += 1
            # Rolling average
            n = stats.total_seen
            stats.avg_rr = ((stats.avg_rr * (n - 1)) + rr) / n
            stats.avg_hold_bars = ((stats.avg_hold_bars * (n - 1)) + hold_bars) / n

    def get_stats(self, symbol: str, scenario_name: str) -> Optional[ScenarioStats]:
        key = f"{symbol}:{scenario_name}"
        return self.stats.get(key)
```

### 6.3 Integration

- `ScenarioMemory` — синглтон
- После закрытия сделки: `memory.record_outcome(symbol, scenario_name, outcome, rr, hold_bars)`
- WeightManager запрашивает `memory.get_stats()` для корректировки оценок
- Статистика хранится в БД (`scenario_stats` таблица)

### 6.4 Changes Required

| File | Change |
|------|--------|
| `strategy/scenario_memory.py` | **NEW** — ScenarioStats, ScenarioMemory |
| `storage/database.py` | таблица `scenario_stats` |
| `scheduler/scanner.py` | запись исходов после закрытия сделки |
| `tests/test_scenario_memory.py` | **NEW** |

---

## Stage 7: Transition Probability Interface

**Цель:** Заложить интерфейс для замены эвристических переходов на ML в будущем.

### 7.1 Interface

```python
class TransitionModel(ABC):
    """Интерфейс для оценки вероятности перехода между нодами."""

    @abstractmethod
    def predict_transition(
        self,
        source: LiquidityNode,
        target: LiquidityNode,
        context: dict,
    ) -> float:
        """Вероятность перехода source → target. 0..1."""
        ...


class HeuristicTransitionModel(TransitionModel):
    """Эвристические правила (текущая логика)."""

    TRANSITION_RULES = {
        ("sweep", "bos"): 0.7,
        ("bos", "ob"): 0.6,
        ("ob", "fvg"): 0.5,
        ("displacement", "fvg"): 0.65,
        ("sweep", "ob"): 0.4,
    }

    def predict_transition(self, source, target, context) -> float:
        return self.TRANSITION_RULES.get((source.type, target.type), 0.3)


class MLTransitionModel(TransitionModel):
    """ML-модель (будущее)."""

    def __init__(self, model_path: str = "models/transition_model.pkl"):
        self.model = None
        # self._load(model_path)

    def predict_transition(self, source, target, context) -> float:
        if self.model is None:
            return 0.3  # fallback
        # features = [source.type, target.type, source.age, ...]
        # return self.model.predict_proba(features)
        return 0.3
```

### 7.2 Integration

- `HeuristicTransitionModel` используется по умолчанию
- `MLTransitionModel` подключается когда модель обучена
- `LiquidityGraph._infer_edges()` использует `TransitionModel.predict_transition()` вместо хардкода

### 7.3 Changes Required

| File | Change |
|------|--------|
| `strategy/transition_model.py` | **NEW** — TransitionModel, HeuristicTransitionModel, MLTransitionModel |
| `strategy/market_thesis_engine.py` | `_infer_edges()` использует TransitionModel |
| `tests/test_transition_model.py` | **NEW** |

---

## Stage 8: Per-Symbol Weights (DEFERRED)

**Статус:** Отложено до накопления 300–500 закрытых сценариев на символ.

**Причина:** Текущий объём данных (17 сделок) — шум. Адаптивные веса будут переобучены на малых данных.

**Когда будет готово:** После Stage 6 (Scenario Memory) накопит достаточно статистики.

---

## Stage 9: Telegram (DEFERRED)

**Статус:** Отложено.

**Причина:** Показывать три сценария пользователю рано. Отправлять только лучший сценарий. Остальные — в DecisionTrace / Shadow Mode / логи.

---

## Implementation Order

| # | Stage | Complexity | Dependencies |
|---|-------|------------|--------------|
| 1 | Market Phase Engine | Medium | None |
| 2 | Node State Machine (6 states) | Low | None |
| 3 | Scenario Engine (immutable + evaluation) | High | #1, #2 |
| 4 | Trade Thesis Lifecycle | High | #3 |
| 5 | Probability Engine refactor | High | #3 |
| 6 | Scenario Memory | Medium | #4 |
| 7 | Transition Probability Interface | Low | #2 |
| 8 | Per-Symbol Weights | Medium | #6 (300+ scenarios) |
| 9 | Telegram update | Low | #4 |

**Параллельно:** #1 и #2 можно делать одновременно. #7 независим от #3–#6.

---

## Architecture Summary

```
Data Flow:

  OHLCV + Indicators
        │
  Market Phase Engine ──────────────── PhaseAssessment
        │
  LiquidityGraph (Node State Machine: 6 states)
        │
  Scenario Engine ──────────────────── MarketScenario[] (immutable)
        │
  Probability Engine ──────────────── ScenarioEvaluation[] (mutable)
        │
  WeightManager ───────────────────── ScenarioEvaluation[] (adjusted)
        │
  Trade Thesis Manager ────────────── TradeThesis (lifecycle)
        │
  Risk Engine ──────────────────────── RiskDecision
        │
  Signal (best scenario only)
        │
  Scenario Memory ──────────────────── ScenarioStats (per type, per symbol)
```

---

## Files Summary

| File | Action |
|------|--------|
| `strategy/market_phase_engine.py` | **NEW** |
| `strategy/market_thesis_engine.py` | Refactor: 6-state NodeStateMachine, remove `detect_scenarios()` |
| `strategy/scenario_engine.py` | **NEW** — MarketScenario (frozen), ScenarioComponent (frozen), ScenarioEvaluation, ScenarioEngine |
| `strategy/trade_thesis.py` | **NEW** — TradeThesis, ThesisSnapshot, TradeThesisManager |
| `strategy/probability_engine.py` | Refactor: `estimate_scenario()`, `rank_scenarios()`, remove SymbolWeights dependency |
| `strategy/weight_manager.py` | **NEW** — WeightManager (stub) |
| `strategy/scenario_memory.py` | **NEW** — ScenarioStats, ScenarioMemory |
| `strategy/transition_model.py` | **NEW** — TransitionModel, HeuristicTransitionModel, MLTransitionModel |
| `scheduler/scanner.py` | Integrate full pipeline |
| `storage/database.py` | Tables: trade_theses, scenario_stats |
| `tests/test_market_phase.py` | **NEW** |
| `tests/test_node_state.py` | **NEW** |
| `tests/test_scenario_engine.py` | **NEW** |
| `tests/test_trade_thesis.py` | **NEW** |
| `tests/test_probability_v2.py` | **NEW** |
| `tests/test_scenario_memory.py` | **NEW** |
| `tests/test_transition_model.py` | **NEW** |
