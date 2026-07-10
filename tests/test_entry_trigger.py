"""
tests/test_entry_trigger.py — Tests for Entry Trigger.

Covers:
    - Price proximity check
    - Spread check
    - Direction-specific logic
"""
import sys
from pathlib import Path

import pytest

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from strategy.hypothesis import Hypothesis
from strategy.entry_trigger import EntryTrigger, TriggerResult


# ── Helpers ────────────────────────────────────────────────────────

def _make_h(direction="buy", entry_price=100.0):
    return Hypothesis(
        id="h1",
        direction=direction,
        narrative_type="test",
        name="test",
        description="test",
        quality=50.0,
        confidence=0.5,
        decay_factor=0.5,
        entry_price=entry_price,
        invalidation_price=98.0,
        target_price=105.0,
        rr_ratio=2.5,
    )


# ── Tests ──────────────────────────────────────────────────────────

class TestEntryTrigger:
    def test_buy_at_entry(self):
        trigger = EntryTrigger()
        h = _make_h(direction="buy", entry_price=100.0)
        result = trigger.check(h, current_price=100.0)
        assert result.triggered is True

    def test_buy_below_entry(self):
        trigger = EntryTrigger()
        h = _make_h(direction="buy", entry_price=100.0)
        result = trigger.check(h, current_price=99.5)
        assert result.triggered is True

    def test_buy_too_far_above(self):
        trigger = EntryTrigger(entry_proximity_pct=0.5)
        h = _make_h(direction="buy", entry_price=100.0)
        # Price 1% above entry (beyond 0.5% threshold)
        result = trigger.check(h, current_price=101.0)
        assert result.triggered is False
        assert "too far above" in result.reason

    def test_sell_at_entry(self):
        trigger = EntryTrigger()
        h = _make_h(direction="sell", entry_price=100.0)
        result = trigger.check(h, current_price=100.0)
        assert result.triggered is True

    def test_sell_above_entry(self):
        trigger = EntryTrigger()
        h = _make_h(direction="sell", entry_price=100.0)
        result = trigger.check(h, current_price=100.5)
        assert result.triggered is True

    def test_sell_too_far_below(self):
        trigger = EntryTrigger(entry_proximity_pct=0.5)
        h = _make_h(direction="sell", entry_price=100.0)
        # Price 1% below entry (beyond 0.5% threshold)
        result = trigger.check(h, current_price=99.0)
        assert result.triggered is False
        assert "too far below" in result.reason

    def test_spread_check_pass(self):
        trigger = EntryTrigger(max_spread_pct=0.2)
        h = _make_h(direction="buy", entry_price=100.0)
        result = trigger.check(h, current_price=100.0, bid=99.95, ask=100.05)
        assert result.triggered is True
        assert result.spread_pct == pytest.approx(0.1, abs=0.01)

    def test_spread_check_fail(self):
        trigger = EntryTrigger(max_spread_pct=0.05)
        h = _make_h(direction="buy", entry_price=100.0)
        result = trigger.check(h, current_price=100.0, bid=99.90, ask=100.10)
        assert result.triggered is False
        assert "spread" in result.reason

    def test_no_entry_price(self):
        trigger = EntryTrigger()
        h = _make_h(direction="buy", entry_price=0.0)
        result = trigger.check(h, current_price=100.0)
        assert result.triggered is False
        assert result.reason == "no_entry_price"

    def test_no_bid_ask_no_spread_check(self):
        trigger = EntryTrigger(max_spread_pct=0.01)
        h = _make_h(direction="buy", entry_price=100.0)
        # No bid/ask provided — spread check should pass
        result = trigger.check(h, current_price=100.0)
        assert result.triggered is True

    def test_result_has_entry_price(self):
        trigger = EntryTrigger()
        h = _make_h(direction="buy", entry_price=100.0)
        result = trigger.check(h, current_price=100.0)
        assert result.entry_price == 100.0
