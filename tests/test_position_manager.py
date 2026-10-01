"""
tests/test_position_manager.py — Регрессия: R-лесенка (2R/3R/4R) должна
считаться от НАЧАЛЬНОГО risk, а не от текущего SL.

Реальный инцидент (signal_id=8, NEAR/USDT 1h, 25.09.2026):
breakeven на 1.5R перенёс SL на entry → risk = 0 → target_price(2R/3R/4R)
стали равны entry → весь лесеночный лист закрылся одной свечей по рынку
с reason=TP3_FULL и уведомлением «✅ Тейк Профит», хотя signal.tp
(5.2328) достигнут не был (MFE 11.65% < 14.76% до TP).
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk.position_manager import (
    ManagedPosition,
    check_partial_closes,
    manage_position,
)

ENTRY = 4.577
SL = 4.24202861
TP = 5.23277113
RISK = ENTRY - SL


def _buy(**kw) -> ManagedPosition:
    defaults = dict(
        symbol="NEAR/USDT",
        direction="BUY",
        entry_price=ENTRY,
        stop_loss=SL,
        take_profit=TP,
        entry_time=datetime(2026, 9, 24, 23, 5, 28, tzinfo=timezone.utc),
    )
    defaults.update(kw)
    return ManagedPosition(**defaults)


def _cycle(pos, high, low, close):
    return manage_position(
        pos,
        candle_high=high,
        candle_low=low,
        candle_close=close,
        atr=0.05,
        current_time=datetime(2026, 9, 25, 13, 0, tzinfo=timezone.utc),
    )


class TestLadderRisk:
    def test_initial_risk_taken_from_construction_sl(self):
        pos = _buy()
        assert pos.initial_risk == pytest.approx(RISK)

    def test_targets_survive_breakeven(self):
        """SL на entry (risk = 0) не должен схлопывать R-цели в entry."""
        pos = _buy()
        assert pos.target_price(2.0) == pytest.approx(ENTRY + 2 * RISK)

        pos.stop_loss = ENTRY  # breakeven
        assert pos.risk == 0.0

        assert pos.target_price(2.0) == pytest.approx(ENTRY + 2 * RISK)
        assert pos.target_price(3.0) == pytest.approx(ENTRY + 3 * RISK)
        assert pos.target_price(4.0) == pytest.approx(ENTRY + 4 * RISK)

    def test_sell_ladder_mirror(self):
        pos = _buy(direction="SELL", stop_loss=4.9, take_profit=4.0)
        short_risk = 4.9 - ENTRY
        assert pos.initial_risk == pytest.approx(short_risk)

        pos.stop_loss = ENTRY  # breakeven
        assert pos.risk == 0.0
        assert pos.target_price(2.0) == pytest.approx(ENTRY - 2 * short_risk)

    def test_ladder_skipped_without_reference_risk(self):
        pos = _buy(stop_loss=ENTRY)
        assert pos.initial_risk == 0.0
        assert check_partial_closes(pos, candle_high=10.0, candle_low=1.0) == []


class TestBreakevenThenLadder:
    def test_no_spurious_close_after_breakeven(self):
        """NEAR-инцидент: после BE цена ниже 2R — позиция должна остаться открытой."""
        pos = _buy()

        # Свеча 1.5R: срабатывает breakeven, SL → entry
        r1 = _cycle(pos, high=5.091, low=4.99, close=5.085)
        assert r1["breakeven"] is True
        assert r1["close"] is False
        assert pos.breakeven_moved is True
        pos.stop_loss = r1["new_sl"]
        assert pos.stop_loss == ENTRY

        # Следующая свеча: цена 5.091 < 2R (5.247) — закрытия быть не должно
        r2 = _cycle(pos, high=5.091, low=5.02, close=5.091)
        assert r2["close"] is False
        assert r2["reason"] == ""
        assert r2["partial_closes"] == []
        assert pos.remaining_percent == 100.0

    def test_partial_close_fires_at_real_2r(self):
        pos = _buy()
        target_2r = ENTRY + 2 * RISK

        r = _cycle(pos, high=target_2r + 0.01, low=ENTRY, close=target_2r)
        assert r["close"] is False
        assert [a["rr"] for a in r["partial_closes"]] == [2.0]
        assert pos.remaining_percent == 75.0
        assert pos.breakeven_moved is True

    def test_close_all_at_4r_reports_tp3_full(self):
        pos = _buy()
        target_4r = ENTRY + 4 * RISK

        r = _cycle(pos, high=target_4r + 0.01, low=ENTRY, close=target_4r)
        assert r["close"] is True
        assert r["reason"] == "TP3_FULL"
        assert pos.remaining_percent == 0.0
