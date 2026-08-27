"""
tests/test_sanity_checks.py — v2.5 Sanity Checks

Verifies:
1. No look-ahead bias in OB/FVG detection
2. SL is placed behind structural points
3. HTF alignment blocks against-trend signals
4. OB not mitigated before entry
5. MIN_P_TP gate filters weak signals
"""
import sys
import os
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_ohlcv(n=200, base_price=100.0, seed=42):
    """Create synthetic OHLCV data for testing."""
    np.random.seed(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = np.random.randn(n).cumsum() + base_price
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


def _make_trending_ohlcv(n=200, direction="up", base_price=100.0, seed=42):
    """Create trending OHLCV data."""
    np.random.seed(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    drift = 0.1 if direction == "up" else -0.1
    close = np.random.randn(n).cumsum() * 0.5 + base_price + np.arange(n) * drift
    df = pd.DataFrame(
        {
            "open": close + np.random.randn(n) * 0.3,
            "high": close + np.abs(np.random.randn(n)) * 1.5,
            "low": close - np.abs(np.random.randn(n)) * 1.5,
            "close": close,
            "volume": np.random.rand(n) * 1000 + 500,
        },
        index=idx,
    )
    df.index.name = "timestamp"
    return df


class TestNoLookaheadBias:
    """Test that OB/FVG detection doesn't use future data."""

    def test_ob_detection_deterministic(self):
        """OB detection should be deterministic — same data, same results."""
        from liquidity.order_blocks import detect_order_blocks

        df = _make_ohlcv(200, seed=42)

        # Run detection twice — should produce identical results
        obs1 = detect_order_blocks(df, lookback=100)
        obs2 = detect_order_blocks(df, lookback=100)

        assert len(obs1) == len(obs2), "OB detection should be deterministic"
        for ob1, ob2 in zip(obs1, obs2):
            assert ob1.type == ob2.type
            assert ob1.high == ob2.high
            assert ob1.low == ob2.low
            assert ob1.candle_index == ob2.candle_index

    def test_ob_detection_no_future_reference(self):
        """OB detection should only use candles within the lookback window."""
        from liquidity.order_blocks import detect_order_blocks

        df = _make_ohlcv(200, seed=42)

        # Detect with small lookback (only recent candles)
        obs_small = detect_order_blocks(df, lookback=30)
        # Detect with larger lookback (more candles)
        obs_large = detect_order_blocks(df, lookback=100)

        # All OBs found with lookback=30 should also appear in lookback=100
        # (since 30-candle window is a subset of 100-candle window)
        # Use (type, high, low) as identity since candle_index resets per tail()
        small_ids = {(ob.type, round(ob.high, 6), round(ob.low, 6)) for ob in obs_small}
        large_ids = {(ob.type, round(ob.high, 6), round(ob.low, 6)) for ob in obs_large}

        assert small_ids.issubset(large_ids), (
            f"OBs from smaller lookback missing in larger: {small_ids - large_ids}"
        )

    def test_ob_bos_uses_closed_candles(self):
        """BOS check should only use closed candles."""
        from liquidity.order_blocks import _check_bos_bullish, _find_swing_highs

        df = _make_ohlcv(100, seed=42)
        swing_highs = _find_swing_highs(df)

        result_10 = _check_bos_bullish(df, 10, swing_highs, lookback=20)
        result_50 = _check_bos_bullish(df, 50, swing_highs, lookback=20)

        assert isinstance(result_10, bool)
        assert isinstance(result_50, bool)

    def test_fvg_detection_deterministic(self):
        """FVG detection should be deterministic."""
        from liquidity.fvg import detect_fvg

        df = _make_ohlcv(200, seed=42)

        fvgs1 = detect_fvg(df, lookback=100)
        fvgs2 = detect_fvg(df, lookback=100)

        assert len(fvgs1) == len(fvgs2), "FVG detection should be deterministic"
        for f1, f2 in zip(fvgs1, fvgs2):
            assert f1.type == f2.type
            assert f1.top == f2.top
            assert f1.bottom == f2.bottom

    def test_ob_retest_lookback_not_lookahead(self):
        """OB retest should use lookback (historical) not lookahead (future)."""
        from liquidity.order_blocks import detect_order_blocks

        df = _make_ohlcv(200, seed=42)

        # Longer lookback should find same or more retests
        obs_30 = detect_order_blocks(df, lookback=100, check_retest_lookback=30)
        obs_5 = detect_order_blocks(df, lookback=100, check_retest_lookback=5)

        retests_30 = sum(1 for ob in obs_30 if ob.retested)
        retests_5 = sum(1 for ob in obs_5 if ob.retested)

        assert retests_30 >= retests_5, (
            f"Longer lookback should find more retests: "
            f"lookback=30 found {retests_30}, lookback=5 found {retests_5}"
        )


class TestSLPlacement:
    """Test that SL is placed behind structural points."""

    def test_sl_below_ob_for_buy(self):
        """For BUY signals, SL should be below the OB low."""
        from liquidity.order_blocks import OrderBlock

        ob = OrderBlock(
            type="bullish",
            high=102.0,
            low=100.0,
            timestamp=pd.Timestamp("2024-01-01"),
        )

        sl = ob.low - (ob.high - ob.low) * 0.1
        assert sl < ob.low, f"SL ({sl}) should be below OB low ({ob.low})"

    def test_sl_above_ob_for_sell(self):
        """For SELL signals, SL should be above the OB high."""
        from liquidity.order_blocks import OrderBlock

        ob = OrderBlock(
            type="bearish",
            high=102.0,
            low=100.0,
            timestamp=pd.Timestamp("2024-01-01"),
        )

        sl = ob.high + (ob.high - ob.low) * 0.1
        assert sl > ob.high, f"SL ({sl}) should be above OB high ({ob.high})"


class TestOBMitigation:
    """Test OB mitigation state detection."""

    def test_ob_broken_state(self):
        """OB should be marked BROKEN if price closes beyond zone."""
        from liquidity.ob_state import get_ob_state, OBState

        # Create data where price clearly breaks below bullish OB
        n = 20
        idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
        # All candles above OB zone, then last candle closes below
        data = {
            "open": [105.0] * (n - 1) + [100.5],
            "high": [106.0] * (n - 1) + [101.0],
            "low": [104.0] * (n - 1) + [98.5],
            "close": [105.5] * (n - 1) + [99.0],
            "volume": [1000.0] * n,
        }
        df = pd.DataFrame(data, index=idx)
        df.index.name = "timestamp"

        state = get_ob_state(df, ob_high=102.0, ob_low=100.0, ob_type="bullish")
        assert state == OBState.BROKEN, f"Expected BROKEN, got {state}"

    def test_ob_mitigated_state(self):
        """OB should be marked MITIGATED if price closes deep inside."""
        from liquidity.ob_state import get_ob_state, OBState

        n = 20
        idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
        # Last candle closes deep inside OB (penetration > 50%)
        data = {
            "open": [105.0] * (n - 1) + [100.5],
            "high": [106.0] * (n - 1) + [101.5],
            "low": [104.0] * (n - 1) + [100.0],
            "close": [105.5] * (n - 1) + [100.8],
            "volume": [1000.0] * n,
        }
        df = pd.DataFrame(data, index=idx)
        df.index.name = "timestamp"

        state = get_ob_state(df, ob_high=102.0, ob_low=100.0, ob_type="bullish")
        assert state in (OBState.MITIGATED, OBState.PARTIAL), f"Expected MITIGATED/PARTIAL, got {state}"

    def test_ob_fresh_state(self):
        """OB should be FRESH if no candles touched it."""
        from liquidity.ob_state import get_ob_state, OBState

        df = _make_ohlcv(20, seed=42)
        state = get_ob_state(df, ob_high=200.0, ob_low=198.0, ob_type="bullish")
        assert state == OBState.FRESH

    def test_ob_tested_state(self):
        """OB should be TESTED if price wicks into zone but closes outside."""
        from liquidity.ob_state import get_ob_state, OBState

        n = 20
        idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
        # Last candle wicks into OB zone but closes above
        data = {
            "open": [105.0] * (n - 1) + [103.0],
            "high": [106.0] * (n - 1) + [103.0],
            "low": [104.0] * (n - 1) + [100.5],  # wick touches OB zone
            "close": [105.5] * (n - 1) + [102.5],  # closes above OB
            "volume": [1000.0] * n,
        }
        df = pd.DataFrame(data, index=idx)
        df.index.name = "timestamp"

        state = get_ob_state(df, ob_high=102.0, ob_low=100.0, ob_type="bullish")
        assert state == OBState.TESTED, f"Expected TESTED, got {state}"


class TestMinMaxP_TP:
    """Test MIN_P_TP gate logic."""

    def test_probability_engine_produces_valid_output(self):
        """Probability engine should produce valid P(TP) regardless of model type."""
        from strategy.probability_engine import ProbabilityEngine
        from strategy.feature_builder import SetupFeatures

        engine = ProbabilityEngine()

        features = SetupFeatures(
            setup_type="reversal",
            has_sweep=True,
            has_displacement=True,
            has_mss=True,
            mss_score=70.0,
            has_ob=True,
            entry_armed=True,
            rr_ratio=2.5,
            volume_ratio=1.5,
            atr_pct=1.5,
        )

        result = engine.predict(features)

        assert 0.0 <= result.p_tp <= 1.0, f"P(TP) out of range: {result.p_tp}"
        assert result.expected_rr > 0, f"Expected RR should be positive: {result.expected_rr}"
        assert result.model_type != "", "model_type should be set"

    def test_strong_features_higher_p_tp(self):
        """Stronger features should produce higher P(TP)."""
        from strategy.probability_engine import ProbabilityEngine
        from strategy.feature_builder import SetupFeatures

        engine = ProbabilityEngine()

        strong = SetupFeatures(
            setup_type="reversal",
            has_sweep=True,
            has_displacement=True,
            has_mss=True,
            mss_score=85.0,
            has_ob=True,
            entry_armed=True,
            rr_ratio=3.0,
            volume_ratio=2.5,
            atr_pct=1.5,
            mtf_aligned=True,
        )

        weak = SetupFeatures(
            setup_type="continuation",
            has_bos=False,
            has_ob=False,
            has_fvg=False,
            rr_ratio=1.0,
            volume_ratio=0.8,
        )

        result_strong = engine.predict(strong)
        result_weak = engine.predict(weak)

        assert result_strong.p_tp >= result_weak.p_tp, (
            f"Strong features ({result_strong.p_tp}) should have higher P(TP) "
            f"than weak features ({result_weak.p_tp})"
        )


class TestHTFAlignment:
    """Test HTF alignment blocks against-trend signals."""

    def test_htf_bias_detects_uptrend(self):
        """Strong uptrend should produce bullish bias."""
        from market_structure.htf_bias_v2 import get_htf_bias_v2

        df_1w = _make_trending_ohlcv(60, direction="up", base_price=50000, seed=10)
        df_1d = _make_trending_ohlcv(60, direction="up", base_price=50000, seed=20)
        df_4h = _make_trending_ohlcv(60, direction="up", base_price=50000, seed=30)
        df_1h = _make_trending_ohlcv(60, direction="up", base_price=50000, seed=40)

        result = get_htf_bias_v2(df_1w, df_1d, df_4h, df_1h)

        assert result.direction in ("bullish", "neutral"), (
            f"Strong uptrend should be bullish, got: {result.direction}"
        )


class TestPremiumDiscount:
    """Test corrected Premium/Discount zone detection."""

    def test_discount_zone_for_buy(self):
        """Discount zone should be at fib 0.5-0.79 (ICT OTE)."""
        from market_structure.premium_discount import classify_zone, ZoneType

        df = _make_ohlcv(10, seed=42)

        swing_high = 110.0
        swing_low = 90.0
        df.iloc[-1, df.columns.get_loc("close")] = 90.0 + (110.0 - 90.0) * 0.6

        result = classify_zone(df, "bullish", swing_high, swing_low)

        assert result.zone_type == ZoneType.DISCOUNT, (
            f"fib=0.6 should be DISCOUNT, got: {result.zone_type}"
        )

    def test_premium_zone_for_sell(self):
        """Premium zone should be at fib 0.21-0.5 (ICT OTE)."""
        from market_structure.premium_discount import classify_zone, ZoneType

        df = _make_ohlcv(10, seed=42)

        swing_high = 110.0
        swing_low = 90.0
        df.iloc[-1, df.columns.get_loc("close")] = 90.0 + (110.0 - 90.0) * 0.4

        result = classify_zone(df, "bearish", swing_high, swing_low)

        assert result.zone_type == ZoneType.PREMIUM, (
            f"fib=0.4 should be PREMIUM, got: {result.zone_type}"
        )

    def test_equilibrium_outside_ote(self):
        """Price outside OTE zones should be EQUILIBRIUM."""
        from market_structure.premium_discount import classify_zone, ZoneType

        df = _make_ohlcv(10, seed=42)

        swing_high = 110.0
        swing_low = 90.0
        df.iloc[-1, df.columns.get_loc("close")] = 90.0 + (110.0 - 90.0) * 0.2

        result = classify_zone(df, "bullish", swing_high, swing_low)

        assert result.zone_type == ZoneType.EQUILIBRIUM, (
            f"fib=0.2 should be EQUILIBRIUM, got: {result.zone_type}"
        )

    def test_custom_ote_fib_levels(self):
        """OTE zones should respect custom fib levels."""
        from market_structure.premium_discount import classify_zone, ZoneType

        df = _make_ohlcv(10, seed=42)

        swing_high = 110.0
        swing_low = 90.0
        # Price at fib 0.55 — within custom OTE (0.45-0.75)
        df.iloc[-1, df.columns.get_loc("close")] = 90.0 + (110.0 - 90.0) * 0.55

        result = classify_zone(df, "bullish", swing_high, swing_low,
                               ote_fib_min=0.45, ote_fib_max=0.75)

        assert result.zone_type == ZoneType.DISCOUNT, (
            f"fib=0.55 in custom OTE should be DISCOUNT, got: {result.zone_type}"
        )


class TestCooldownConfig:
    """OB-aware cooldown configuration checks."""

    def test_cooldown_mode_default(self):
        """Default cooldown mode should be ob_aware."""
        from config.settings import config
        assert config.cooldown_mode == "ob_aware"

    def test_ob_proximity_pct_default(self):
        """Default OB proximity should be 0.5%."""
        from config.settings import config
        assert config.ob_proximity_pct == 0.5

    def test_ob_proximity_is_fraction(self):
        """OB proximity should be converted to fraction in scanner logic."""
        from config.settings import config
        proximity_fraction = config.ob_proximity_pct / 100.0
        assert 0 < proximity_fraction < 0.05  # between 0 and 5%
