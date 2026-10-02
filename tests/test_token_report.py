"""tests/test_token_report.py — Token Analysis engine (levels, strategies, verdict).

Covers:
- _merge_and_filter: nearest-first sorting (regression: supports were sorted
  farthest-first → S1 $1000 / S2 $1500 / S3 $2000 at price $2699)
- round numbers as fallback filler only, structure levels preferred
- _generate_strategies: numeric fields + clean price formatting
- _determine_recommendation: votes 1H+4H, TF-conflict reason, strategy link
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from analytics.token_levels import PRIO_OB, PRIO_ROUND, PRIO_SWING, _merge_and_filter
from analytics.token_report import (
    IndicatorSnapshot,
    TokenReport,
    _determine_recommendation,
    _fmt_px,
    _generate_strategies,
)


# ─── Levels ────────────────────────────────────────────────────────

def test_supports_returned_nearest_first():
    """Regression: support sort was reversed (farthest first)."""
    price = 2699.0
    cands = [
        (1000.0, PRIO_ROUND),
        (1500.0, PRIO_ROUND),
        (2400.0, PRIO_ROUND),
        (2600.0, PRIO_ROUND),
        (2650.0, PRIO_OB),
    ]
    out = _merge_and_filter(cands, price, "support")
    assert out[0] == 2650.0   # nearest structure level first
    assert out[1] == 2600.0
    assert 1000.0 not in out  # farthest round number never wins


def test_resistances_returned_nearest_first():
    price = 2699.0
    cands = [(2721.0, PRIO_SWING), (2800.0, PRIO_ROUND), (3500.0, PRIO_ROUND)]
    out = _merge_and_filter(cands, price, "resistance")
    assert out == [2721.0, 2800.0, 3500.0]


def test_round_numbers_are_fallback_only():
    """Structure level wins even when a round number is closer."""
    price = 2699.0
    cands = [
        (2660.0, PRIO_ROUND),  # nearer, but round
        (2650.0, PRIO_OB),     # farther, but structure
        (2550.0, PRIO_ROUND),
    ]
    out = _merge_and_filter(cands, price, "support")
    assert out[0] == 2650.0


def test_min_distance_filter():
    price = 2699.0
    cands = [(2695.0, PRIO_OB), (2600.0, PRIO_OB)]  # 2695 is 0.15% away
    out = _merge_and_filter(cands, price, "support")
    assert 2695.0 not in out
    assert out == [2600.0]


def test_dedupe_keeps_higher_priority_source():
    price = 2699.0
    cands = [
        (2650.0, PRIO_ROUND),  # same level as OB, but round priority
        (2651.0, PRIO_OB),     # within 0.5% of 2650
    ]
    out = _merge_and_filter(cands, price, "support")
    # round sorted first by distance, OB deduped against it — but structure
    # list is filtered before filler, so only the OB survives as structure
    assert out == [2651.0]


# ─── Price formatting ──────────────────────────────────────────────

def test_fmt_px_precision():
    assert _fmt_px(2639.4185) == "$2,639"
    assert _fmt_px(2721.0) == "$2,721"
    assert _fmt_px(154.2) == "$154.2"
    assert _fmt_px(1.834) == "$1.83"
    assert _fmt_px(0.00012345) == "$0.00012345"
    assert _fmt_px(0) == "-"


# ─── Strategies ────────────────────────────────────────────────────

def _ind(rsi=50, macd="Neutral", ema="Neutral", st=0):
    return IndicatorSnapshot(
        rsi=rsi,
        rsi_signal="Neutral",
        macd_signal=macd,
        ema_signal=ema,
        supertrend_direction=st,
        supertrend_signal="Bullish" if st == 1 else "Bearish",
    )


def test_breakout_strategy_numeric_fields():
    report = TokenReport(
        symbol="ETH/USDT",
        price=2699.0,
        indicators_1h=_ind(rsi=50),
        resistance_1h=[2721.0],
        support_1h=[2600.0],
    )
    strategies = _generate_strategies(report)
    types = [s.type for s in strategies]
    assert "long_breakout" in types

    s = next(x for x in strategies if x.type == "long_breakout")
    assert s.entry_price == 2721.0
    assert s.sl_price == 2721.0 * 0.97
    assert s.tp1_price == 2699.0 * 1.05
    assert s.stop_loss == "$2,639"          # no 4-decimal noise
    assert s.tp1 == "$2,834"                # 2699*1.05 = 2833.95
    assert s.rr1 and s.rr1 > 0
    assert s.rr2 and s.rr2 > s.rr1


def test_wait_strategy_when_no_setup():
    report = TokenReport(symbol="ETH/USDT", price=2699.0, indicators_1h=_ind(rsi=50))
    strategies = _generate_strategies(report)
    assert len(strategies) == 1
    assert strategies[0].type == "wait"
    assert strategies[0].entry_price is None


# ─── Recommendation ────────────────────────────────────────────────

def test_verdict_long_on_bullish_both_tfs():
    report = TokenReport(
        symbol="ETH/USDT",
        price=2699.0,
        indicators_1h=_ind(rsi=32, macd="Growth", ema="Aligned Up", st=1),
        indicators_4h=_ind(rsi=38, macd="Growth", ema="Aligned Up", st=1),
    )
    rec, reason, votes = _determine_recommendation(report)
    assert rec == "LONG"
    assert votes["bull"] > votes["bear"]
    assert votes["total"] > 0
    assert reason  # non-empty one-liner


def test_verdict_short_on_bearish_both_tfs():
    report = TokenReport(
        symbol="ETH/USDT",
        price=2699.0,
        indicators_1h=_ind(rsi=70, macd="Decline", ema="Aligned Down", st=-1),
        indicators_4h=_ind(rsi=68, macd="Decline", ema="Aligned Down", st=-1),
    )
    rec, reason, votes = _determine_recommendation(report)
    assert rec == "SHORT"
    assert votes["bear"] > votes["bull"]


def test_verdict_wait_on_tf_conflict():
    report = TokenReport(
        symbol="ETH/USDT",
        price=2699.0,
        indicators_1h=_ind(rsi=50, st=1),
        indicators_4h=_ind(rsi=50, st=-1),
    )
    rec, reason, votes = _determine_recommendation(report)
    assert rec == "WAIT"
    assert "расходятся" in reason


def test_verdict_reason_links_active_strategy():
    report = TokenReport(
        symbol="ETH/USDT",
        price=2699.0,
        indicators_1h=_ind(rsi=50),
        resistance_1h=[2721.0],
        support_1h=[2600.0],
    )
    report.strategies = _generate_strategies(report)
    rec, reason, votes = _determine_recommendation(report)
    assert rec == "WAIT"
    assert "ждём пробоя $2,721" in reason


def test_verdict_without_indicators():
    report = TokenReport(symbol="ETH/USDT", price=2699.0)
    rec, reason, votes = _determine_recommendation(report)
    assert rec == "WAIT"
    assert reason == "Недостаточно данных"
    assert votes["total"] == 0


def test_fear_greed_70_counts_as_bearish_factor():
    report = TokenReport(
        symbol="ETH/USDT",
        price=2699.0,
        indicators_1h=_ind(rsi=50),
        fear_greed=74,
        fear_greed_label="Greed",
    )
    rec, reason, votes = _determine_recommendation(report)
    assert votes["bear"] >= 1


# ─── API ───────────────────────────────────────────────────────────

def _full_report() -> TokenReport:
    report = TokenReport(
        symbol="ETH/USDT",
        price=2699.0,
        indicators_1h=_ind(rsi=32, macd="Growth", ema="Aligned Up", st=1),
        indicators_4h=_ind(rsi=38, macd="Growth", ema="Aligned Up", st=1),
        resistance_1h=[2721.0, 2800.0],
        support_1h=[2600.0, 2500.0],
    )
    report.strategies = _generate_strategies(report)
    from analytics.token_report import _generate_observations
    report.observations = _generate_observations(report)
    (report.recommendation, report.recommendation_reason,
     report.recommendation_votes) = _determine_recommendation(report)
    return report


class TestTokenReportApi:
    @pytest.fixture()
    async def client(self):
        from aiohttp.test_utils import TestClient, TestServer
        from web.server import create_app

        tc = TestClient(TestServer(create_app()))
        await tc.start_server()
        yield tc
        await tc.close()

    @pytest.mark.asyncio
    async def test_symbol_with_slash_matches_route(self, client, monkeypatch):
        """Regression: {symbol} without :.* 404ed on "ETH/USDT" input."""
        import analytics.token_report as tr_mod
        from unittest.mock import AsyncMock
        from web import server

        server._TOKEN_REPORT_CACHE.clear()
        monkeypatch.setattr(tr_mod, "generate_token_report", AsyncMock(return_value=_full_report()))

        resp = await client.get("/api/token-report/ETH/USDT")
        assert resp.status == 200
        data = await resp.json()

        assert data["symbol"] == "ETH/USDT"
        assert data["recommendation"] in ("LONG", "SHORT", "WAIT")
        assert data["rec_votes"]["total"] > 0
        assert data["change_30d"] is None  # missing data stays null, not 0.0
        assert data["strategies"]
        s = data["strategies"][0]
        assert s["entry_price"] is not None
        assert s["sl_price"] is not None
        assert s["rr1"] is not None

        # Second request served from the 60s cache — no recompute
        resp2 = await client.get("/api/token-report/ETH/USDT")
        assert resp2.status == 200
        assert tr_mod.generate_token_report.await_count == 1

    @pytest.mark.asyncio
    async def test_symbol_without_slash_matches_route(self, client, monkeypatch):
        import analytics.token_report as tr_mod
        from web import server
        from unittest.mock import AsyncMock

        server._TOKEN_REPORT_CACHE.clear()
        report = _full_report()
        report.symbol = "BTC/USDT"
        monkeypatch.setattr(tr_mod, "generate_token_report", AsyncMock(return_value=report))

        resp = await client.get("/api/token-report/BTC")
        assert resp.status == 200
        data = await resp.json()
        assert data["symbol"] == "BTC/USDT"  # server appends /USDT
