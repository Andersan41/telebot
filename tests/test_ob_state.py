"""
tests/test_ob_state.py — Tests for OB/FVG Mitigation State.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from liquidity.ob_state import OBState, get_ob_state, get_ob_multiplier


def _make_df_fresh() -> pd.DataFrame:
    """Price has never touched the OB zone (60000-60200)."""
    return pd.DataFrame({
        "open": [61000] * 50,
        "high": [61500] * 50,
        "low": [60500] * 50,
        "close": [61200] * 50,
        "volume": [1000] * 50,
    })


def _make_df_tested() -> pd.DataFrame:
    """Price wicked into OB zone but closed outside."""
    data = {
        "open": [61000] * 45 + [60100],
        "high": [61500] * 45 + [60200],
        "low": [60500] * 45 + [59900],
        "close": [61200] * 45 + [60900],
        "volume": [1000] * 46,
    }
    return pd.DataFrame(data)


def _make_df_partial() -> pd.DataFrame:
    """Price closed inside OB zone but penetration < 50% (close near midpoint)."""
    data = {
        "open": [61000] * 45 + [60100],
        "high": [61500] * 45 + [60250],
        "low": [60500] * 45 + [59950],
        "close": [61200] * 45 + [60100],  # midpoint of 60000-60200
        "volume": [1000] * 46,
    }
    return pd.DataFrame(data)


def _make_df_mitigated() -> pd.DataFrame:
    """Price closed deep inside OB zone (penetration > 50%)."""
    data = {
        "open": [61000] * 45 + [60000],
        "high": [61500] * 45 + [60150],
        "low": [60500] * 45 + [59900],
        "close": [61200] * 45 + [60050],  # close near low edge of 60000-60200
        "volume": [1000] * 46,
    }
    return pd.DataFrame(data)


class TestGetOBState:
    def test_fresh_ob(self):
        """Price never touched zone → FRESH."""
        df = _make_df_fresh()
        state = get_ob_state(df, 60200, 60000)
        assert state == OBState.FRESH

    def test_tested_ob(self):
        """Wick only → TESTED."""
        df = _make_df_tested()
        state = get_ob_state(df, 60200, 60000)
        assert state == OBState.TESTED

    def test_partial_mitigated(self):
        """Close inside, penetration < 50% → PARTIAL."""
        df = _make_df_partial()
        state = get_ob_state(df, 60200, 60000)
        assert state == OBState.PARTIAL

    def test_mitigated(self):
        """Close inside, penetration > 50% → MITIGATED."""
        df = _make_df_mitigated()
        state = get_ob_state(df, 60200, 60000)
        assert state == OBState.MITIGATED


class TestGetOBMultiplier:
    def test_fresh_multiplier(self):
        assert get_ob_multiplier(OBState.FRESH) == 1.2

    def test_tested_multiplier(self):
        assert get_ob_multiplier(OBState.TESTED) == 1.0

    def test_partial_multiplier(self):
        assert get_ob_multiplier(OBState.PARTIAL) == 0.8

    def test_mitigated_multiplier(self):
        assert get_ob_multiplier(OBState.MITIGATED) == 0.6

    def test_broken_multiplier(self):
        assert get_ob_multiplier(OBState.BROKEN) == 0.0
