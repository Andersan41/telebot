"""
Tests for the v13 fixes (H-017..H-021):
- capital-units conversion for daily limits (H-017)
- paused timeframes filter (H-018)
- audit hyp plan + shadow outcome simulation (H-019)
- position close metrics (H-021)
"""
import importlib.util
import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── H-017: capital PnL units ──────────────────────────────────────────

class TestCapitalPnlPct:
    def test_conversion_uses_sl_distance(self):
        from scheduler.outcome_tracker import _capital_pnl_pct
        # entry=100, sl=95 → 5% risk distance; +10% price = +2R; risk 1% → +2% capital
        assert _capital_pnl_pct(10.0, 100.0, 95.0, 1.0) == pytest.approx(2.0)

    def test_conversion_sell_side_sl_above_entry(self):
        from scheduler.outcome_tracker import _capital_pnl_pct
        # SELL: entry=100, sl=105 → 5% distance; -5% price = -1R; risk 0.5% → -0.5%
        assert _capital_pnl_pct(-5.0, 100.0, 105.0, 0.5) == pytest.approx(-0.5)

    def test_conversion_scales_with_risk_pct(self):
        from scheduler.outcome_tracker import _capital_pnl_pct
        # 2R at risk 0.5% → 1.0% capital
        assert _capital_pnl_pct(10.0, 100.0, 95.0, 0.5) == pytest.approx(1.0)

    def test_missing_risk_falls_back_to_base(self):
        from scheduler.outcome_tracker import _capital_pnl_pct
        from config.settings import config
        # risk_pct=0 → base_risk_pct (default 1.0)
        result = _capital_pnl_pct(5.0, 100.0, 95.0, 0.0)
        assert result == pytest.approx(5.0 / 5.0 * config.risk_engine.base_risk_pct)

    def test_missing_sl_falls_back_to_one_r(self):
        from scheduler.outcome_tracker import _capital_pnl_pct
        assert _capital_pnl_pct(11.0, 100.0, None, 1.0) == pytest.approx(1.0)
        assert _capital_pnl_pct(-11.0, 100.0, None, 1.0) == pytest.approx(-1.0)
        assert _capital_pnl_pct(0.0, 100.0, None, 1.0) == 0.0

    def test_zero_sl_distance_falls_back_to_one_r(self):
        from scheduler.outcome_tracker import _capital_pnl_pct
        # sl == entry → division guard
        assert _capital_pnl_pct(3.0, 100.0, 100.0, 1.0) == pytest.approx(1.0)

    def test_near_style_price_move_does_not_trip_profit_target(self):
        """Regression: NEAR +11.01% price (SL dist 7.3%) must not hit +10% capital."""
        from scheduler.outcome_tracker import _capital_pnl_pct
        from risk.daily_limits import DailyLimitsTracker

        capital_pnl = _capital_pnl_pct(11.01, 4.577, 4.242, 1.0)
        assert capital_pnl < 10.0  # ~+7.7% at best, not 11%

        tracker = DailyLimitsTracker()
        tracker.record_trade_closed(capital_pnl, was_loss=False, risk_pct=1.0)
        allowed, _, reason = tracker.can_open_trade(1.0)
        assert allowed, f"profit target must not trigger: {reason}"
        assert tracker.get_state().daily_pnl_pct == pytest.approx(capital_pnl)

    def test_large_capital_loss_trips_drawdown(self):
        from risk.daily_limits import DailyLimitsTracker
        tracker = DailyLimitsTracker()
        tracker.record_trade_closed(-10.5, was_loss=True, risk_pct=1.0)
        allowed, _, reason = tracker.can_open_trade(1.0)
        assert not allowed
        assert "drawdown" in reason


# ── H-018: paused timeframes ─────────────────────────────────────────

class TestPausedTimeframes:
    # filter_paused_timeframes() reads scheduler.scanner.config — patch THAT
    # object (earlier tests reload config.settings, so `from config.settings
    # import config` may hand back a different instance than the scanner uses).
    @staticmethod
    def _scanner_config():
        import scheduler.scanner as scanner_mod
        return scanner_mod.config

    def test_paused_tf_dropped(self, monkeypatch):
        from scheduler.scanner import filter_paused_timeframes
        monkeypatch.setattr(self._scanner_config().trading, "paused_timeframes", ["1h"])
        assert filter_paused_timeframes(["1h", "4h"]) == ["4h"]

    def test_no_pause_keeps_all(self, monkeypatch):
        from scheduler.scanner import filter_paused_timeframes
        monkeypatch.setattr(self._scanner_config().trading, "paused_timeframes", [])
        assert filter_paused_timeframes(["1h", "4h", "15m"]) == ["1h", "4h", "15m"]

    def test_all_paused_returns_empty(self, monkeypatch):
        from scheduler.scanner import filter_paused_timeframes
        monkeypatch.setattr(self._scanner_config().trading, "paused_timeframes", ["1h", "4h"])
        assert filter_paused_timeframes(["1h", "4h"]) == []

    def test_config_parses_env(self):
        from config.settings import TradingConfig
        # .env sets PAUSED_TIMEFRAMES=1h — dataclass default_factory reads env
        # at construction; construct with explicit env to stay independent.
        import os
        old = os.environ.get("PAUSED_TIMEFRAMES")
        os.environ["PAUSED_TIMEFRAMES"] = "1h,15m"
        try:
            assert TradingConfig().paused_timeframes == ["1h", "15m"]
        finally:
            if old is None:
                del os.environ["PAUSED_TIMEFRAMES"]
            else:
                os.environ["PAUSED_TIMEFRAMES"] = old

    def test_empty_env_is_empty_list(self):
        import os
        from config.settings import TradingConfig
        old = os.environ.get("PAUSED_TIMEFRAMES")
        os.environ["PAUSED_TIMEFRAMES"] = ""
        try:
            assert TradingConfig().paused_timeframes == []
        finally:
            if old is None:
                del os.environ["PAUSED_TIMEFRAMES"]
            else:
                os.environ["PAUSED_TIMEFRAMES"] = old


# ── H-019: audit hyp plan + shadow simulation ────────────────────────

class TestHypPlan:
    def test_plan_kwargs_and_synthetic_flag(self):
        from scheduler.scanner import _hyp_plan
        plan = _hyp_plan(100.0, 95.0, 115.0, p_tp=0.42)
        assert plan["hyp_entry"] == 100.0
        assert plan["hyp_sl"] == 95.0
        assert plan["hyp_tp"] == 115.0
        assert plan["hyp_rr"] == pytest.approx(3.0)  # 15 / 5
        assert plan["hyp_ptp"] == 0.42
        assert plan["synthetic_plan"] is True

    def test_explicit_rr_wins(self):
        from scheduler.scanner import _hyp_plan
        plan = _hyp_plan(100.0, 95.0, 115.0, p_tp=0.42, rr=2.5)
        assert plan["hyp_rr"] == pytest.approx(2.5)

    def test_zero_risk_guard(self):
        from scheduler.scanner import _hyp_plan
        plan = _hyp_plan(100.0, 100.0, 110.0)
        assert plan["hyp_rr"] == 0.0


def _mk_bars(pairs, start=None):
    """pairs: (offset_hours, high, low, close) from ts_event."""
    base = start or datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    return [
        (base + timedelta(hours=h), hi, lo, cl) for h, hi, lo, cl in pairs
    ]


class TestSimulateOutcome:
    TS = datetime(2026, 10, 1, 0, 30, tzinfo=timezone.utc)  # mid-bar → entry bar skipped
    NOW = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)

    def test_buy_sl_hit(self):
        from scheduler.audit_resolver import simulate_outcome
        bars = _mk_bars([(1, 101, 94.5, 95)])  # low 94.5 <= sl 95
        result = simulate_outcome("buy", 100.0, 95.0, 115.0, self.TS, bars, self.NOW)
        assert result is not None
        outcome, outcome_r, mae_r, mfe_r = result
        assert outcome == "HIT_SL"
        assert outcome_r == pytest.approx(-1.0)
        assert mae_r < 0
        assert mfe_r > 0  # high 101 → +0.2R before SL

    def test_buy_tp_hit(self):
        from scheduler.audit_resolver import simulate_outcome
        bars = _mk_bars([(1, 116, 99, 115.5)])
        outcome, outcome_r, _, _ = simulate_outcome(
            "buy", 100.0, 95.0, 115.0, self.TS, bars, self.NOW
        )
        assert outcome == "HIT_TP"
        assert outcome_r == pytest.approx(3.0)  # 15 / 5

    def test_sell_sl_hit(self):
        from scheduler.audit_resolver import simulate_outcome
        bars = _mk_bars([(1, 106, 104, 105)])  # high >= sl 105
        outcome, outcome_r, _, _ = simulate_outcome(
            "sell", 100.0, 105.0, 85.0, self.TS, bars, self.NOW
        )
        assert outcome == "HIT_SL"
        assert outcome_r == pytest.approx(-1.0)

    def test_sell_tp_hit(self):
        from scheduler.audit_resolver import simulate_outcome
        bars = _mk_bars([(1, 101, 84, 84.5)])  # low <= tp 85
        outcome, outcome_r, _, _ = simulate_outcome(
            "sell", 100.0, 105.0, 85.0, self.TS, bars, self.NOW
        )
        assert outcome == "HIT_TP"
        assert outcome_r == pytest.approx(3.0)  # 15 / 5

    def test_entry_bar_skipped(self):
        from scheduler.audit_resolver import simulate_outcome
        # bar containing ts_event already breached SL — must be ignored
        bars = _mk_bars([(0, 101, 90, 100.5), (1, 102, 99, 101)])
        now = self.TS + timedelta(days=1)  # < expire window → open, not EXPIRED
        result = simulate_outcome("buy", 100.0, 95.0, 115.0, self.TS, bars, now)
        assert result is None  # no touch after entry bar

    def test_sl_priority_within_bar(self):
        from scheduler.audit_resolver import simulate_outcome
        # both SL and TP inside one bar → conservative SL
        bars = _mk_bars([(1, 116, 94, 110)])
        outcome, *_ = simulate_outcome("buy", 100.0, 95.0, 115.0, self.TS, bars, self.NOW)
        assert outcome == "HIT_SL"

    def test_expired_after_window(self):
        from scheduler.audit_resolver import simulate_outcome
        bars = _mk_bars([(1, 104, 99, 102), (2, 105, 98.5, 103)])
        ts = datetime(2026, 10, 1, 0, 30, tzinfo=timezone.utc)
        now = ts + timedelta(days=8)  # > AUDIT_RESOLVER_EXPIRE_DAYS (7)
        outcome, outcome_r, mae_r, mfe_r = simulate_outcome(
            "buy", 100.0, 95.0, 115.0, ts, bars, now
        )
        assert outcome == "EXPIRED"
        assert mae_r < 0 and mfe_r >= 0
        # no adverse excursion below entry → mae stays 0
        assert mae_r == 0.0 or mae_r < 0

    def test_no_touch_within_window_stays_open(self):
        from scheduler.audit_resolver import simulate_outcome
        bars = _mk_bars([(1, 104, 99, 102)])
        now = self.TS + timedelta(days=3)  # < 7d expire
        assert simulate_outcome("buy", 100.0, 95.0, 115.0, self.TS, bars, now) is None

    def test_no_bars_after_entry_returns_none(self):
        from scheduler.audit_resolver import simulate_outcome
        bars = _mk_bars([(0, 101, 99, 100)])
        assert simulate_outcome("buy", 100.0, 95.0, 115.0, self.TS, bars, self.NOW) is None

    def test_invalid_plan_returns_none(self):
        from scheduler.audit_resolver import simulate_outcome
        bars = _mk_bars([(1, 101, 99, 100)])
        assert simulate_outcome("buy", 0.0, 95.0, 115.0, self.TS, bars, self.NOW) is None
        assert simulate_outcome("buy", 100.0, 100.0, 115.0, self.TS, bars, self.NOW) is None
        assert simulate_outcome("", 100.0, 95.0, 115.0, self.TS, bars, self.NOW) is None

    def test_ambiguous_missing_direction_returns_none(self):
        from scheduler.audit_resolver import simulate_outcome
        bars = _mk_bars([(1, 101, 99, 100)])
        assert simulate_outcome(None, 100.0, 95.0, 115.0, self.TS, bars, self.NOW) is None


class TestBackfillMetaParse:
    def _load(self):
        path = Path(__file__).resolve().parent.parent / "scripts" / "backfill_audit_hyp.py"
        spec = importlib.util.spec_from_file_location("backfill_audit_hyp", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_parse_real_meta_format(self):
        mod = self._load()
        meta = ("p_tp=0.455,threshold=0.500,hyp_entry=0.3392,hyp_sl=0.3364,"
                "hyp_tp=0.3511,hyp_rr=4.20,hyp_ptp=0.455")
        vals = mod.parse_meta(meta)
        assert vals is not None
        assert vals["hypothetical_entry"] == pytest.approx(0.3392)
        assert vals["hypothetical_sl"] == pytest.approx(0.3364)
        assert vals["hypothetical_tp"] == pytest.approx(0.3511)
        assert vals["hypothetical_rr"] == pytest.approx(4.20)
        assert vals["hypothetical_p_tp"] == pytest.approx(0.455)

    def test_incomplete_meta_returns_none(self):
        mod = self._load()
        assert mod.parse_meta("reason=no plan here") is None
        assert mod.parse_meta("hyp_entry=1.0,hyp_sl=2.0") is None
        assert mod.parse_meta("") is None
        assert mod.parse_meta(None) is None


# ── H-021: position close metrics ────────────────────────────────────

class _FakeSignal:
    def __init__(self, signal_type, entry, sl, tp):
        self.signal_type = signal_type
        self.close_price = entry
        self.sl = sl
        self.tp = tp


class TestPositionCloseMetrics:
    def test_buy_metrics(self):
        from scheduler.outcome_tracker import _position_close_metrics
        sig = _FakeSignal("BUY", 100.0, 95.0, 115.0)
        m = _position_close_metrics(sig, 115.0, 14.0, quantity=2.0)
        assert m["pnl_percent"] == pytest.approx(14.0)
        assert m["pnl_usdt"] == pytest.approx(14.0 / 100 * 100.0 * 2.0)
        assert m["actual_rr"] == pytest.approx(3.0)      # +15 / risk 5
        assert m["expected_rr"] == pytest.approx(3.0)    # |115-100| / 5

    def test_sell_metrics(self):
        from scheduler.outcome_tracker import _position_close_metrics
        sig = _FakeSignal("SELL", 100.0, 105.0, 85.0)
        m = _position_close_metrics(sig, 95.0, 5.0)
        assert m["actual_rr"] == pytest.approx(1.0)      # (100-95) / 5
        assert m["expected_rr"] == pytest.approx(3.0)    # |85-100| / 5

    def test_actual_rr_uses_original_sl(self):
        from scheduler.outcome_tracker import _position_close_metrics
        # signal.sl is the ORIGINAL level (positions.stop_loss may be BE-moved)
        sig = _FakeSignal("BUY", 100.0, 95.0, 115.0)
        m = _position_close_metrics(sig, 100.0, -0.4)  # exit at breakeven
        assert m["actual_rr"] == pytest.approx(0.0)

    def test_missing_sl_omits_rr(self):
        from scheduler.outcome_tracker import _position_close_metrics
        sig = _FakeSignal("BUY", 100.0, None, 115.0)
        m = _position_close_metrics(sig, 110.0, 10.0)
        assert "actual_rr" not in m
        assert "expected_rr" not in m
        assert m["pnl_percent"] == pytest.approx(10.0)

    def test_close_position_accepts_metrics(self):
        import inspect
        from storage.position_store import close_position
        params = inspect.signature(close_position).parameters
        for name in ("pnl_usdt", "pnl_percent", "actual_rr", "expected_rr"):
            assert name in params
