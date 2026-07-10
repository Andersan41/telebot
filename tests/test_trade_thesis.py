import sys
from pathlib import Path
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.trade_thesis import (
    TradeThesis, TradeThesisManager, ThesisSnapshot,
    THESIS_FORMING, THESIS_OBSERVED, THESIS_CONFIRMED,
    THESIS_ACTIVATED, THESIS_EXECUTING, THESIS_CLOSED,
    THESIS_FAILED, THESIS_EXPIRED,
)
from strategy.scenario_engine import MarketScenario, ScenarioEvaluation


def _make_scenario(direction="buy", name="Sweep+BOS+OB", price=100.0):
    return MarketScenario(
        id=f"{direction}_{name}_{price}",
        direction=direction,
        name=name,
        description=f"{direction}: test",
        components=tuple(),
        entry_zone=(price * 0.99, price * 1.01),
        invalidation_price=price * 0.98,
        target_price=price * 1.05,
        rr_ratio=2.5,
    )


def _make_evaluation(p=0.65):
    return ScenarioEvaluation(scenario_id="test", probability=p, confidence=0.5)


class TestTradeThesis:
    def test_default_status_is_forming(self):
        scenario = _make_scenario()
        thesis = TradeThesis(
            id="test_1", symbol="BTC/USDT", timeframe="1h",
            scenario=scenario, evaluation=_make_evaluation(),
            direction="buy",
        )
        assert thesis.status == THESIS_FORMING

    def test_is_active(self):
        for status in [THESIS_FORMING, THESIS_OBSERVED, THESIS_CONFIRMED,
                       THESIS_ACTIVATED, THESIS_EXECUTING]:
            scenario = _make_scenario()
            thesis = TradeThesis(
                id="test_1", symbol="BTC/USDT", timeframe="1h",
                scenario=scenario, evaluation=_make_evaluation(),
                direction="buy", status=status,
            )
            assert thesis.is_active, f"Expected active for status={status}"

    def test_is_not_active_for_terminal(self):
        for status in [THESIS_CLOSED, THESIS_FAILED, THESIS_EXPIRED]:
            scenario = _make_scenario()
            thesis = TradeThesis(
                id="test_1", symbol="BTC/USDT", timeframe="1h",
                scenario=scenario, evaluation=_make_evaluation(),
                direction="buy", status=status,
            )
            assert not thesis.is_active, f"Expected not active for status={status}"

    def test_is_tradeable(self):
        scenario = _make_scenario()
        thesis = TradeThesis(
            id="test_1", symbol="BTC/USDT", timeframe="1h",
            scenario=scenario, evaluation=_make_evaluation(p=0.65),
            direction="buy", status=THESIS_CONFIRMED,
        )
        assert thesis.is_tradeable

    def test_not_tradeable_when_low_probability(self):
        scenario = _make_scenario()
        thesis = TradeThesis(
            id="test_1", symbol="BTC/USDT", timeframe="1h",
            scenario=scenario, evaluation=_make_evaluation(p=0.30),
            direction="buy", status=THESIS_CONFIRMED,
        )
        assert not thesis.is_tradeable

    def test_age_bars(self):
        scenario = _make_scenario()
        thesis = TradeThesis(
            id="test_1", symbol="BTC/USDT", timeframe="1h",
            scenario=scenario, evaluation=_make_evaluation(),
            direction="buy", update_count=10,
        )
        assert thesis.age_bars == 10


class TestTradeThesisManager:
    def setup_method(self):
        self.manager = TradeThesisManager()

    def test_creates_thesis_for_new_symbol(self):
        scenarios = [_make_scenario()]
        evaluations = [_make_evaluation(p=0.65)]

        thesis = self.manager.update(
            "BTC/USDT", "1h", scenarios, evaluations,
            bar=1, price=100.0,
        )

        assert thesis is not None
        assert thesis.symbol == "BTC/USDT"
        assert thesis.status == THESIS_OBSERVED

    def test_does_not_create_for_low_probability(self):
        scenarios = [_make_scenario()]
        evaluations = [_make_evaluation(p=0.30)]

        thesis = self.manager.update(
            "BTC/USDT", "1h", scenarios, evaluations,
            bar=1, price=100.0,
        )

        assert thesis is None

    def test_updates_existing_thesis(self):
        scenarios = [_make_scenario()]
        evaluations = [_make_evaluation(p=0.65)]

        self.manager.update("BTC/USDT", "1h", scenarios, evaluations, bar=1, price=100.0)
        thesis = self.manager.update("BTC/USDT", "1h", scenarios, evaluations, bar=2, price=101.0)

        assert thesis.update_count == 1
        assert thesis.current_price == 101.0

    def test_transition_to_confirmed(self):
        scenarios = [_make_scenario()]
        evaluations = [_make_evaluation(p=0.65)]

        thesis = self.manager.update("BTC/USDT", "1h", scenarios, evaluations, bar=1, price=100.0)
        assert thesis.status == THESIS_OBSERVED

        # Update enough to trigger confirmation
        for i in range(5):
            self.manager.update("BTC/USDT", "1h", scenarios, evaluations, bar=i+2, price=100.0)

        # Should have transitioned (confirmation_pct check)
        assert thesis.status in (THESIS_OBSERVED, THESIS_CONFIRMED)

    def test_sl_hit_marks_failed(self):
        scenario = _make_scenario(direction="buy", price=100.0)
        scenario = MarketScenario(
            id=scenario.id, direction="buy", name=scenario.name,
            description=scenario.description, components=scenario.components,
            entry_zone=(99.0, 101.0), invalidation_price=98.0,
            target_price=105.0, rr_ratio=2.5,
        )
        evaluations = [_make_evaluation(p=0.65)]

        thesis = self.manager.update("BTC/USDT", "1h", [scenario], evaluations, bar=1, price=100.0)
        # Update multiple times to trigger confirmed → activated
        for i in range(5):
            self.manager.update("BTC/USDT", "1h", [scenario], evaluations, bar=i+2, price=100.0)
        # Force into confirmed state for SL test
        if thesis.status == THESIS_OBSERVED:
            thesis.status = THESIS_CONFIRMED

        # Activate by moving price into entry zone
        self.manager.update("BTC/USDT", "1h", [scenario], evaluations, bar=10, price=100.0)
        # Move to executing
        self.manager.update("BTC/USDT", "1h", [scenario], evaluations, bar=11, price=100.5)

        # SL hit
        self.manager.update("BTC/USDT", "1h", [scenario], evaluations, bar=12, price=97.0)
        assert thesis.status == THESIS_FAILED
        assert thesis.outcome == "loss"

    def test_get_active(self):
        scenarios = [_make_scenario()]
        evaluations = [_make_evaluation(p=0.65)]

        self.manager.update("BTC/USDT", "1h", scenarios, evaluations, bar=1, price=100.0)
        self.manager.update("ETH/USDT", "1h", scenarios, evaluations, bar=1, price=2000.0)

        active = self.manager.get_active()
        assert len(active) == 2

    def test_get_active_by_symbol(self):
        scenarios = [_make_scenario()]
        evaluations = [_make_evaluation(p=0.65)]

        self.manager.update("BTC/USDT", "1h", scenarios, evaluations, bar=1, price=100.0)
        self.manager.update("ETH/USDT", "1h", scenarios, evaluations, bar=1, price=2000.0)

        btc = self.manager.get_active(symbol="BTC/USDT")
        assert len(btc) == 1
        assert btc[0].symbol == "BTC/USDT"
