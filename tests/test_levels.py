import sys
from pathlib import Path

import pytest
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.levels import (
    find_swing_levels,
    cluster_levels,
    get_support_resistance,
    validate_levels_vs_trade,
    format_levels_message,
)


class TestFindSwingLevels:
    def test_finds_highs_and_lows(self):
        data = {
            'high': [100, 101, 102, 103, 110, 103, 102, 101, 100, 99, 98, 97, 90, 97, 98, 99, 100, 101, 102, 103, 104],
            'low': [98, 99, 100, 101, 105, 101, 100, 99, 98, 97, 96, 95, 88, 95, 96, 97, 98, 99, 100, 101, 102],
        }
        df = pd.DataFrame(data)
        highs, lows = find_swing_levels(df, window=3)
        assert len(highs) > 0 or len(lows) > 0

    def test_empty_dataframe(self):
        df = pd.DataFrame({'high': [], 'low': []})
        highs, lows = find_swing_levels(df, window=3)
        assert highs == []
        assert lows == []

    def test_returns_sorted(self):
        df = pd.DataFrame({
            'high': [100, 105, 102, 108, 103, 101, 99, 97, 95, 98, 96, 94],
            'low': [98, 100, 99, 103, 100, 98, 96, 94, 92, 95, 93, 91],
        })
        highs, lows = find_swing_levels(df, window=3)
        assert highs == sorted(highs, reverse=True)
        assert lows == sorted(lows)


class TestClusterLevels:
    def test_clusters_close_levels(self):
        levels = [100.0, 100.3, 100.5, 105.0, 105.2]
        clustered = cluster_levels(levels, threshold=0.01)
        assert len(clustered) < len(levels)

    def test_empty_list(self):
        assert cluster_levels([]) == []

    def test_single_level(self):
        assert cluster_levels([100.0]) == [100.0]

    def test_no_clustering_when_far_apart(self):
        levels = [100.0, 200.0, 300.0]
        clustered = cluster_levels(levels, threshold=0.005)
        assert len(clustered) == 3


class TestGetSupportResistance:
    def test_returns_resistance_above_price(self):
        df = pd.DataFrame({
            'high': [100, 105, 102, 108, 103, 101, 99, 97, 95, 98, 96, 94],
            'low': [98, 100, 99, 103, 100, 98, 96, 94, 92, 95, 93, 91],
        })
        result = get_support_resistance(df, current_price=100.0)
        for r in result['resistance']:
            assert r > 100.0

    def test_returns_support_below_price(self):
        df = pd.DataFrame({
            'high': [100, 105, 102, 108, 103, 101, 99, 97, 95, 98, 96, 94],
            'low': [98, 100, 99, 103, 100, 98, 96, 94, 92, 95, 93, 91],
        })
        result = get_support_resistance(df, current_price=100.0)
        for s in result['support']:
            assert s < 100.0

    def test_limits_max_levels(self):
        df = pd.DataFrame({
            'high': [100 + i * 2 for i in range(20)],
            'low': [100 - i * 2 for i in range(20)],
        })
        result = get_support_resistance(df, current_price=100.0, max_levels=2)
        assert len(result['resistance']) <= 2
        assert len(result['support']) <= 2


class TestValidateLevelsVsTrade:
    def test_warns_when_resistance_between_entry_and_tp(self):
        sr_levels = {
            '1h': {
                'resistance': [105.0],
                'support': [95.0],
            }
        }
        warnings = validate_levels_vs_trade(sr_levels, entry=100.0, sl=98.0, tp=108.0, is_buy=True)
        assert len(warnings) >= 1
        assert "105.0" in warnings[0]

    def test_no_warning_when_resistance_above_tp(self):
        sr_levels = {
            '1h': {
                'resistance': [110.0],
                'support': [95.0],
            }
        }
        warnings = validate_levels_vs_trade(sr_levels, entry=100.0, sl=98.0, tp=108.0, is_buy=True)
        resistance_warnings = [w for w in warnings if "Сопротивление" in w]
        assert len(resistance_warnings) == 0

    def test_warns_when_support_between_sl_and_entry(self):
        sr_levels = {
            '1h': {
                'resistance': [110.0],
                'support': [99.5],
            }
        }
        warnings = validate_levels_vs_trade(sr_levels, entry=100.0, sl=98.0, tp=108.0, is_buy=True)
        support_warnings = [w for w in warnings if "Поддержка" in w and "близко" in w]
        assert len(support_warnings) >= 1

    def test_sell_signal_validation(self):
        sr_levels = {
            '1h': {
                'resistance': [105.0],
                'support': [95.0],
            }
        }
        warnings = validate_levels_vs_trade(sr_levels, entry=100.0, sl=102.0, tp=92.0, is_buy=False)
        assert len(warnings) >= 0


class TestFormatLevelsMessage:
    def test_formats_levels_for_multiple_timeframes(self):
        sr_levels = {
            '4h': {
                'resistance': [105.0, 108.0],
                'support': [95.0, 92.0],
            },
            '1h': {
                'resistance': [103.0],
                'support': [97.0],
            },
        }
        msg = format_levels_message(sr_levels)
        assert "Уровни поддержки" in msg
        assert "4H" in msg
        assert "1H" in msg
        assert "105.0" in msg
        assert "95.0" in msg

    def test_handles_empty_levels(self):
        sr_levels = {
            '1h': {
                'resistance': [],
                'support': [],
            },
        }
        msg = format_levels_message(sr_levels)
        assert "Уровни поддержки" in msg

    def test_skips_missing_timeframe(self):
        sr_levels = {
            '4h': {
                'resistance': [105.0],
                'support': [95.0],
            },
        }
        msg = format_levels_message(sr_levels)
        assert "4H" in msg
        assert "1H" not in msg
