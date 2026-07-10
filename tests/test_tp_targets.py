"""
tests/test_tp_targets.py — Tests for TP by External Liquidity.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from liquidity.external import find_external_liquidity


def _make_df_with_eqh() -> pd.DataFrame:
    """DataFrame with Equal Highs for LONG TP detection."""
    highs = []
    for i in range(110):
        if i == 30:
            highs.append(50500.0)
        elif i == 45:
            highs.append(50500.0)  # EQH: same level at 30 and 45
        elif i == 55:
            highs.append(51000.0)
        elif i == 70:
            highs.append(51000.0)  # EQH: same level at 55 and 70
        else:
            highs.append(50000 + i * 100)  # bigger step to avoid false matches

    return pd.DataFrame({
        "open": [h - 200 for h in highs],
        "high": highs,
        "low": [h - 500 for h in highs],
        "close": [h - 100 for h in highs],
        "volume": [1000] * len(highs),
    })


def _make_df_with_eql() -> pd.DataFrame:
    """DataFrame with Equal Lows for SHORT TP detection."""
    lows = []
    for i in range(110):
        if i == 30:
            lows.append(49500.0)
        elif i == 45:
            lows.append(49500.0)  # EQL: same level at 30 and 45
        elif i == 55:
            lows.append(49000.0)
        elif i == 70:
            lows.append(49000.0)  # EQL: same level at 55 and 70
        else:
            lows.append(50000 - i * 100)  # bigger step to avoid false matches

    return pd.DataFrame({
        "open": [l + 200 for l in lows],
        "high": [l + 500 for l in lows],
        "low": lows,
        "close": [l + 100 for l in lows],
        "volume": [1000] * len(lows),
    })


def _make_df_no_eq() -> pd.DataFrame:
    """No equal highs/lows in the data."""
    return pd.DataFrame({
        "open": [50000 + i * 1000 for i in range(110)],
        "high": [50100 + i * 1000 for i in range(110)],
        "low": [49900 + i * 1000 for i in range(110)],
        "close": [50050 + i * 1000 for i in range(110)],
        "volume": [1000] * 110,
    })


class TestFindExternalLiquidity:
    def test_long_eqh_found(self):
        """EQH found for LONG with valid RR."""
        df = _make_df_with_eqh()
        entry = 45000
        sl_distance = 3000
        tp = find_external_liquidity(df, 'long', entry, sl_distance)
        assert tp is not None, f"Expected TP but got None"
        rr = (tp - entry) / sl_distance
        assert 1.5 <= rr <= 10.0, f"RR={rr} out of range"

    def test_short_eql_found(self):
        """EQL found for SHORT with valid RR."""
        df = _make_df_with_eql()
        entry = 55000
        sl_distance = 3000
        tp = find_external_liquidity(df, 'short', entry, sl_distance)
        assert tp is not None, f"Expected TP but got None"
        rr = (entry - tp) / sl_distance
        assert 1.5 <= rr <= 10.0, f"RR={rr} out of range"

    def test_long_no_eqh(self):
        """No EQH → returns None."""
        df = _make_df_no_eq()
        entry = 50000
        sl_distance = 300
        tp = find_external_liquidity(df, 'long', entry, sl_distance)
        assert tp is None

    def test_short_no_eql(self):
        """No EQL → returns None."""
        df = _make_df_no_eq()
        entry = 50000
        sl_distance = 300
        tp = find_external_liquidity(df, 'short', entry, sl_distance)
        assert tp is None

    def test_long_eqh_below_entry_ignored(self):
        """EQH below entry for LONG → None (wrong side)."""
        df = _make_df_with_eql()  # has EQL below entry
        entry = 51000
        sl_distance = 500
        tp = find_external_liquidity(df, 'long', entry, sl_distance)
        assert tp is None

    def test_short_eql_above_entry_ignored(self):
        """EQL above entry for SHORT → None (wrong side)."""
        df = _make_df_with_eqh()  # has EQH above entry
        entry = 49000
        sl_distance = 500
        tp = find_external_liquidity(df, 'short', entry, sl_distance)
        assert tp is None

    def test_insufficient_data(self):
        """Very short df → None."""
        df = pd.DataFrame({
            "open": [50000] * 5,
            "high": [50100] * 5,
            "low": [49900] * 5,
            "close": [50050] * 5,
            "volume": [1000] * 5,
        })
        tp = find_external_liquidity(df, 'long', 50000, 300)
        assert tp is None
