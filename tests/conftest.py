import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_ohlcv():
    np.random.seed(42)
    n = 200
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = np.random.randn(n).cumsum() + 100
    df = pd.DataFrame(
        {
            "open": close + np.random.randn(n) * 0.5,
            "high": close + np.abs(np.random.randn(n)) * 2,
            "low": close - np.abs(np.random.randn(n)) * 2,
            "close": close,
            "volume": np.random.rand(n) * 1000 + 500,
        },
        index=idx,
    )
    df.index.name = "timestamp"
    return df
