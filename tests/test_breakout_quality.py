"""
tests/test_breakout_quality.py — Tests for AMD-sweep vs real-breakout classifier.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from liquidity.breakout_quality import classify_breakout


def make_df(n_range, last, prev=None):
    """Build an OHLCV df: `n_range` flat candles then a final breakout candle."""
    idx = pd.date_range("2024-01-01", periods=n_range + 1, freq="1h")
    row_base = {"high": 105.0, "low": 95.0, "close": 100.0, "open": 100.0, "volume": 100.0}
    rows = [dict(row_base) for _ in range(n_range)]
    rows.append(last)
    return pd.DataFrame(rows, index=idx)


def test_amd_fake_break_bullish():
    """Wick pierces far above the range high, close just barely beyond → fake (AMD)."""
    last = {"open": 100.0, "high": 115.0, "low": 104.9, "close": 105.2, "volume": 120.0}
    res = classify_breakout(make_df(50, last), direction="buy", atr=2.0,
                            oi_change_pct=-1.0, lookback=42)
    # boundary = max high of settled (~105) so close barely beyond, body portion tiny
    assert res.verdict == "fake" or res.verdict == "ambiguous"
    assert res.body_pct < 0.5


def test_real_breakout_bullish():
    """Strong close beyond range high, volume + OI confirm → real."""
    last = {"open": 106.0, "high": 118.0, "low": 104.0, "close": 114.0, "volume": 400.0}
    res = classify_breakout(make_df(50, last), direction="buy", atr=3.0,
                            oi_change_pct=5.0, lookback=40)
    assert res.verdict == "real"


def test_real_breakdown_sell():
    """Strong close below range low → real sell breakout."""
    last = {"open": 94.0, "high": 96.0, "low": 82.0, "close": 86.0, "volume": 400.0}
    res = classify_breakout(make_df(50, last), direction="sell", atr=3.0,
                            oi_change_pct=-5.0, lookback=40)
    assert res.verdict == "real"


def test_amd_fake_header_back_inside_bullish():
    """Wick pierced far above the range high, but close returned INSIDE the range →
    an AMD stop-hunt / fake breakout in the buy direction."""
    last = {"open": 100.0, "high": 118.0, "low": 96.0, "close": 101.0, "volume": 400.0}
    res = classify_breakout(make_df(50, last), direction="buy", atr=3.0,
                            oi_change_pct=-2.0, lookback=40)
    assert res.verdict == "fake"
    assert res.close_past_boundary is False


def test_no_breakout_ambiguous():
    """Close still inside range → ambiguous, no piercing."""
    last = {"open": 100.0, "high": 104.0, "low": 96.0, "close": 99.0, "volume": 100.0}
    res = classify_breakout(make_df(50, last), direction="buy", atr=2.0,
                            oi_change_pct=1.0, lookback=40)
    assert res.verdict == "ambiguous"


def test_invalid_direction():
    res = classify_breakout(None, direction="sideways", atr=1.0)
    assert res.verdict == "ambiguous"


def test_too_short_df():
    res = classify_breakout(make_df(3, {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100}),
                            direction="buy", atr=1.0, lookback=40)
    assert res.verdict == "ambiguous"