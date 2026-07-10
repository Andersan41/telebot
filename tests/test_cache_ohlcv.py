"""Tests for backtest/cache_ohlcv.py — DatetimeIndex preservation and time overlap."""
from __future__ import annotations

import os
import sys
from datetime import timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.cache_ohlcv import (
    load_cached,
    save_cached,
    validate_time_overlap,
    _cache_path,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(start: str, periods: int, freq: str = "1h") -> pd.DataFrame:
    """Create a synthetic OHLCV DataFrame with DatetimeIndex."""
    idx = pd.date_range(start, periods=periods, freq=freq, tz=timezone.utc)
    import random
    random.seed(42)
    data = {
        "open": [100.0 + random.uniform(-5, 5) for _ in range(periods)],
        "high": [105.0 + random.uniform(0, 5) for _ in range(periods)],
        "low": [95.0 + random.uniform(-5, 0) for _ in range(periods)],
        "close": [100.0 + random.uniform(-5, 5) for _ in range(periods)],
        "volume": [1000.0 + random.uniform(-100, 100) for _ in range(periods)],
    }
    return pd.DataFrame(data, index=idx)


def _make_bad_ohlcv(periods: int) -> pd.DataFrame:
    """Create OHLCV DataFrame with integer RangeIndex (no DatetimeIndex)."""
    data = {
        "open": [100.0] * periods,
        "high": [105.0] * periods,
        "low": [95.0] * periods,
        "close": [100.0] * periods,
        "volume": [1000.0] * periods,
    }
    return pd.DataFrame(data, index=range(periods))


# ---------------------------------------------------------------------------
# save_cached / load_cached round-trip
# ---------------------------------------------------------------------------

class TestSaveLoadRoundTrip:
    def test_preserves_datetime_index(self, tmp_path, monkeypatch):
        """save_cached must preserve DatetimeIndex through parquet round-trip."""
        monkeypatch.setattr("backtest.cache_ohlcv.CACHE_DIR", tmp_path)
        df = _make_ohlcv("2025-01-01", 100)
        save_cached("TEST/USDT", "1h", 100, df)

        loaded = load_cached("TEST/USDT", "1h", 100)
        assert loaded is not None
        assert isinstance(loaded.index, pd.DatetimeIndex)
        assert loaded.index[0] == df.index[0]
        assert loaded.index[-1] == df.index[-1]
        assert len(loaded) == 100

    def test_load_rejects_non_datetime_index(self, tmp_path, monkeypatch):
        """load_cached raises ValueError when index is not DatetimeIndex."""
        monkeypatch.setattr("backtest.cache_ohlcv.CACHE_DIR", tmp_path)
        df_bad = _make_bad_ohlcv(100)
        path = _cache_path("TEST/USDT", "1h", 100)
        tmp_path.mkdir(parents=True, exist_ok=True)
        df_bad.to_parquet(path, index=True)  # saves with RangeIndex

        with pytest.raises(ValueError, match="DatetimeIndex"):
            load_cached("TEST/USDT", "1h", 100)

    def test_load_returns_none_when_not_cached(self, tmp_path, monkeypatch):
        """load_cached returns None when file does not exist."""
        monkeypatch.setattr("backtest.cache_ohlcv.CACHE_DIR", tmp_path)
        assert load_cached("NONEXISTENT/USDT", "1h", 100) is None


# ---------------------------------------------------------------------------
# validate_time_overlap
# ---------------------------------------------------------------------------

class TestValidateTimeOverlap:
    def test_passes_when_aligned(self):
        """No error when 1h and 15m data fully overlap."""
        df_1h = _make_ohlcv("2025-01-01", 100, "1h")
        # 15m data covers the same range
        start = df_1h.index[0]
        end = df_1h.index[-1]
        df_15m = _make_ohlcv("2025-01-01", 400, "15min")
        # Trim 15m to same range
        df_15m = df_15m[(df_15m.index >= start) & (df_15m.index <= end)]
        validate_time_overlap(df_1h, df_15m)

    def test_fails_when_no_overlap(self):
        """Raises ValueError when 15m data starts after 1h data ends."""
        df_1h = _make_ohlcv("2025-01-01", 100, "1h")
        df_15m = _make_ohlcv("2026-06-01", 400, "15min")
        with pytest.raises(ValueError, match="No temporal overlap"):
            validate_time_overlap(df_1h, df_15m)

    def test_fails_when_overlap_below_threshold(self):
        """Raises ValueError when overlap < 90%."""
        df_1h = _make_ohlcv("2025-01-01", 100, "1h")
        # 15m data starts halfway through 1h range
        mid = df_1h.index[50]
        df_15m = _make_ohlcv(str(mid), 200, "15min")
        with pytest.raises(ValueError, match="below threshold"):
            validate_time_overlap(df_1h, df_15m)

    def test_rejects_non_datetime_index(self):
        """Raises ValueError when either DataFrame lacks DatetimeIndex."""
        df_bad = _make_bad_ohlcv(100)
        df_good = _make_ohlcv("2025-01-01", 100, "1h")
        with pytest.raises(ValueError, match="DatetimeIndex"):
            validate_time_overlap(df_bad, df_good)


# ---------------------------------------------------------------------------
# Time alignment test (simulates real 1h/15m cache scenario)
# ---------------------------------------------------------------------------

class TestTimeAlignment:
    def test_15m_first_last_within_1h_range(self, tmp_path, monkeypatch):
        """Load 1h and 15m data, verify 15m timestamps fall within 1h range.

        This test should FAIL on old cache files (index=False) and PASS after fix.
        """
        monkeypatch.setattr("backtest.cache_ohlcv.CACHE_DIR", tmp_path)

        # Simulate realistic data: same time range, different granularities
        df_1h = _make_ohlcv("2025-01-01", 3900, "1h")
        df_15m = _make_ohlcv("2025-01-01", 15552, "15min")

        save_cached("TEST/USDT", "1h", 3900, df_1h)
        save_cached("TEST/USDT", "15m", 15552, df_15m)

        loaded_1h = load_cached("TEST/USDT", "1h", 3900)
        loaded_15m = load_cached("TEST/USDT", "15m", 15552)

        assert loaded_1h is not None and loaded_15m is not None
        assert isinstance(loaded_1h.index, pd.DatetimeIndex)
        assert isinstance(loaded_15m.index, pd.DatetimeIndex)

        h_first, h_last = loaded_1h.index.min(), loaded_1h.index.max()
        m_first, m_last = loaded_15m.index.min(), loaded_15m.index.max()

        # 15m first timestamp must be >= 1h first timestamp
        assert m_first >= h_first, (
            f"15m starts at {m_first} which is before 1h start {h_first}"
        )
        # 15m last timestamp must be <= 1h last timestamp
        assert m_last <= h_last, (
            f"15m ends at {m_last} which is after 1h end {h_last}"
        )

        # Overlap validation must pass
        validate_time_overlap(loaded_1h, loaded_15m)
