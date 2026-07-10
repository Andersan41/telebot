import sys
from pathlib import Path
from dataclasses import dataclass

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.market_thesis_engine import (
    LiquidityNode, LiquidityGraph, NodeStateMachine, NodeTransition,
    NODE_STATE_CREATED, NODE_STATE_ACTIVE, NODE_STATE_TESTED,
    NODE_STATE_MITIGATED, NODE_STATE_BROKEN, NODE_STATE_STALE,
    TERMINAL_STATES, _node_state_machine,
)


class TestNodeStateMachine:
    """Tests for the 6-state NodeStateMachine."""

    def test_valid_transitions(self):
        sm = NodeStateMachine()
        assert sm.can_transition(NODE_STATE_CREATED, NODE_STATE_ACTIVE)
        assert sm.can_transition(NODE_STATE_ACTIVE, NODE_STATE_TESTED)
        assert sm.can_transition(NODE_STATE_ACTIVE, NODE_STATE_MITIGATED)
        assert sm.can_transition(NODE_STATE_ACTIVE, NODE_STATE_BROKEN)
        assert sm.can_transition(NODE_STATE_ACTIVE, NODE_STATE_STALE)
        assert sm.can_transition(NODE_STATE_TESTED, NODE_STATE_MITIGATED)
        assert sm.can_transition(NODE_STATE_TESTED, NODE_STATE_BROKEN)

    def test_invalid_transitions(self):
        sm = NodeStateMachine()
        assert not sm.can_transition(NODE_STATE_MITIGATED, NODE_STATE_ACTIVE)
        assert not sm.can_transition(NODE_STATE_BROKEN, NODE_STATE_ACTIVE)
        assert not sm.can_transition(NODE_STATE_STALE, NODE_STATE_ACTIVE)
        assert not sm.can_transition(NODE_STATE_CREATED, NODE_STATE_MITIGATED)
        assert not sm.can_transition(NODE_STATE_TESTED, NODE_STATE_CREATED)

    def test_terminal_states_have_no_transitions(self):
        sm = NodeStateMachine()
        for state in TERMINAL_STATES:
            assert sm.VALID_TRANSITIONS[state] == []

    def test_transition_records_history(self):
        node = LiquidityNode(type="ob", price=100.0)
        node.state = NODE_STATE_CREATED

        sm = NodeStateMachine()
        result = sm.transition(node, NODE_STATE_ACTIVE, bar=1, reason="init")

        assert result is True
        assert node.state == NODE_STATE_ACTIVE
        assert len(node.transition_history) == 1
        assert node.transition_history[0].old == NODE_STATE_CREATED
        assert node.transition_history[0].new == NODE_STATE_ACTIVE
        assert node.transition_history[0].bar == 1

    def test_transition_rejects_invalid(self):
        node = LiquidityNode(type="ob", price=100.0)
        node.state = NODE_STATE_MITIGATED

        sm = NodeStateMachine()
        result = sm.transition(node, NODE_STATE_ACTIVE, bar=1)

        assert result is False
        assert node.state == NODE_STATE_MITIGATED


class TestLiquidityNode:
    """Tests for LiquidityNode with new state system."""

    def test_default_state_is_created(self):
        node = LiquidityNode(type="ob", price=100.0)
        assert node.state == NODE_STATE_CREATED

    def test_is_alive_for_active_states(self):
        for state in [NODE_STATE_CREATED, NODE_STATE_ACTIVE, NODE_STATE_TESTED]:
            node = LiquidityNode(type="ob", price=100.0, state=state)
            assert node.is_alive, f"Expected alive for state={state}"

    def test_is_not_alive_for_terminal_states(self):
        for state in TERMINAL_STATES:
            node = LiquidityNode(type="ob", price=100.0, state=state)
            assert not node.is_alive, f"Expected not alive for state={state}"

    def test_transition_to_uses_state_machine(self):
        node = LiquidityNode(type="ob", price=100.0, state=NODE_STATE_CREATED)
        node.transition_to(NODE_STATE_ACTIVE, current_bar=5, reason="test")

        assert node.state == NODE_STATE_ACTIVE
        assert len(node.transition_history) == 1
        assert node.transition_history[0].reason == "test"

    def test_times_tested_counter(self):
        node = LiquidityNode(type="ob", price=100.0)
        assert node.times_tested == 0


class TestLiquidityGraphStateTransitions:
    """Tests for LiquidityGraph._check_state_transitions."""

    def test_created_to_active_on_update(self):
        graph = LiquidityGraph()
        node = LiquidityNode(type="ob", price=100.0, state=NODE_STATE_CREATED)
        graph.add_node(node)

        graph.update_on_candle(
            {"open": 99, "high": 101, "low": 98, "close": 100, "volume": 1000},
            current_price=100.0,
            new_bar=True,
        )

        assert node.state == NODE_STATE_ACTIVE

    def test_ob_tested_on_wick(self):
        graph = LiquidityGraph()

        @dataclass
        class MockOB:
            type: str = "bullish"
            mitigated: bool = False

        node = LiquidityNode(
            type="ob", price=100.0, state=NODE_STATE_ACTIVE,
            source=MockOB(),
        )
        graph.add_node(node)

        # Wick down to OB price
        graph.update_on_candle(
            {"open": 102, "high": 103, "low": 99.5, "close": 102, "volume": 1000},
            current_price=102.0,
            new_bar=True,
        )

        assert node.state == NODE_STATE_TESTED

    def test_ob_mitigated_on_close_through(self):
        graph = LiquidityGraph()

        @dataclass
        class MockOB:
            type: str = "bullish"

        node = LiquidityNode(
            type="ob", price=100.0, state=NODE_STATE_TESTED,
            source=MockOB(),
        )
        graph.add_node(node)

        # Close below OB midpoint
        graph.update_on_candle(
            {"open": 101, "high": 102, "low": 98, "close": 99, "volume": 1000},
            current_price=99.0,
            new_bar=True,
        )

        assert node.state == NODE_STATE_MITIGATED

    def test_equal_high_broken_on_sweep(self):
        graph = LiquidityGraph()
        node = LiquidityNode(
            type="equal_high", price=100.0, state=NODE_STATE_ACTIVE,
        )
        graph.add_node(node)

        # High goes above equal_high
        graph.update_on_candle(
            {"open": 99, "high": 101, "low": 98, "close": 99.5, "volume": 1000},
            current_price=99.5,
            new_bar=True,
        )

        assert node.state == NODE_STATE_BROKEN
