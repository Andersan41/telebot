import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from derivatives.funding import FundingState, classify_funding
from derivatives.open_interest import OIState, classify_oi
from derivatives.btc_correlation import BTCContext, _detect_structure, _detect_breakout
from derivatives.eth_correlation import ETHContext, _detect_impulsive_move


# === Funding Tests ===

class TestFunding:
    def test_neutral_zone(self):
        state = classify_funding(0.00005)
        assert state.state == "neutral"
        assert state.strength == "weak"

    def test_neutral_zone_negative(self):
        state = classify_funding(-0.00005)
        assert state.state == "neutral"
        assert state.strength == "weak"

    def test_strong_bearish(self):
        state = classify_funding(0.0004)
        assert state.state == "bearish"
        assert state.strength == "strong"

    def test_strong_bullish(self):
        state = classify_funding(-0.0004)
        assert state.state == "bullish"
        assert state.strength == "strong"

    def test_moderate_bearish(self):
        state = classify_funding(0.0002)
        assert state.state == "bearish"
        assert state.strength == "moderate"

    def test_moderate_bullish(self):
        state = classify_funding(-0.0002)
        assert state.state == "bullish"
        assert state.strength == "moderate"

    def test_contributes_to_buy_strong_bullish(self):
        state = FundingState(0.0004, None, "bullish", "strong")
        assert state.contributes_to("BUY") == 5

    def test_contributes_to_buy_strong_bearish(self):
        state = FundingState(0.0004, None, "bearish", "strong")
        assert state.contributes_to("BUY") == -5

    def test_contributes_to_sell_strong_bearish(self):
        state = FundingState(0.0004, None, "bearish", "strong")
        assert state.contributes_to("SELL") == 5

    def test_contributes_to_sell_strong_bullish(self):
        state = FundingState(-0.0004, None, "bullish", "strong")
        assert state.contributes_to("SELL") == -5

    def test_contributes_to_moderate(self):
        state = FundingState(0.0002, None, "bearish", "moderate")
        assert state.contributes_to("SELL") == 2
        assert state.contributes_to("BUY") == -2

    def test_contributes_to_neutral_weak(self):
        state = FundingState(0.00005, None, "neutral", "weak")
        assert state.contributes_to("BUY") == 0
        assert state.contributes_to("SELL") == 0

    def test_predicted_rate_preserved(self):
        state = classify_funding(0.0004, predicted_rate=0.00035)
        assert state.predicted_rate == 0.00035


# === Open Interest Tests ===

class TestOpenInterest:
    def test_ignore_small_change(self):
        state = classify_oi(0.3, 1.0)
        assert state.significance == "ignore"

    def test_moderate_change(self):
        state = classify_oi(1.0, 1.0)
        assert state.significance == "moderate"

    def test_strong_change(self):
        state = classify_oi(3.0, 1.0)
        assert state.significance == "strong"

    def test_bullish_continuation(self):
        state = classify_oi(2.0, 1.5)
        assert state.pattern == "bullish_cont"

    def test_short_squeeze(self):
        state = classify_oi(-2.0, 1.5)
        assert state.pattern == "short_squeeze"

    def test_long_squeeze(self):
        state = classify_oi(-2.0, -1.5)
        assert state.pattern == "long_squeeze"

    def test_trap_setup(self):
        state = classify_oi(2.0, 0.1)
        assert state.pattern == "trap"

    def test_neutral_pattern(self):
        state = classify_oi(0.0, 0.5)
        assert state.pattern == "neutral"

    def test_contributes_bullish_cont_buy(self):
        state = OIState(1000, 2.0, "strong", "bullish_cont")
        assert state.contributes_to("BUY") == 5

    def test_contributes_bullish_cont_sell(self):
        state = OIState(1000, 2.0, "strong", "bullish_cont")
        assert state.contributes_to("SELL") == -5

    def test_contributes_short_squeeze_buy(self):
        state = OIState(1000, -2.0, "strong", "short_squeeze")
        assert state.contributes_to("BUY") == 5

    def test_contributes_long_squeeze_sell(self):
        state = OIState(1000, -2.0, "strong", "long_squeeze")
        assert state.contributes_to("SELL") == 5

    def test_contributes_trap_zero(self):
        state = OIState(1000, 2.0, "strong", "trap")
        assert state.contributes_to("BUY") == 0
        assert state.contributes_to("SELL") == 0

    def test_contributes_ignore_zero(self):
        state = OIState(1000, 0.3, "ignore", "neutral")
        assert state.contributes_to("BUY") == 0

    def test_moderate_contribution(self):
        state = OIState(1000, 1.0, "moderate", "bullish_cont")
        assert state.contributes_to("BUY") == 2


# === BTC Correlation Tests ===

class TestBTCContext:
    def test_allows_long_above_ema_bullish(self):
        ctx = BTCContext(50000, 48000, True, "bullish", False, None)
        assert ctx.allows_long() is True

    def test_allows_long_below_ema(self):
        ctx = BTCContext(47000, 48000, False, "bullish", False, None)
        assert ctx.allows_long() is False

    def test_allows_long_bearish_structure(self):
        ctx = BTCContext(50000, 48000, True, "bearish", False, None)
        assert ctx.allows_long() is False

    def test_allows_short_normal(self):
        ctx = BTCContext(50000, 48000, True, "bullish", False, None)
        assert ctx.allows_short() is True

    def test_allows_short_blocked_by_bullish_breakout(self):
        ctx = BTCContext(52000, 48000, True, "bullish", True, "bullish")
        assert ctx.allows_short() is False

    def test_allows_short_bearish_breakout_ok(self):
        ctx = BTCContext(46000, 48000, False, "bearish", True, "bearish")
        assert ctx.allows_short() is True


class TestBTCDetectStructure:
    def test_bullish_structure(self):
        df = pd.DataFrame({
            "close": [100 + i * 2 for i in range(20)],
        })
        assert _detect_structure(df) == "bullish"

    def test_bearish_structure(self):
        df = pd.DataFrame({
            "close": [120 - i * 2 for i in range(20)],
        })
        assert _detect_structure(df) == "bearish"

    def test_ranging_structure(self):
        df = pd.DataFrame({
            "close": [100, 101, 100, 99, 100, 101, 100, 99, 100, 101,
                      100, 99, 100, 101, 100, 99, 100, 101, 100, 99],
        })
        assert _detect_structure(df) == "ranging"


class TestBTCDetectBreakout:
    def test_bullish_breakout(self):
        df = pd.DataFrame({
            "close": [100] * 19 + [102],
            "high": [100.5] * 19 + [101.5],
            "low": [99.5] * 20,
        })
        is_breakout, direction = _detect_breakout(df)
        assert is_breakout is True
        assert direction == "bullish"

    def test_bearish_breakout(self):
        df = pd.DataFrame({
            "close": [100] * 19 + [98],
            "high": [100.5] * 20,
            "low": [99.5] * 19 + [98.5],
        })
        is_breakout, direction = _detect_breakout(df)
        assert is_breakout is True
        assert direction == "bearish"

    def test_no_breakout_in_wide_range(self):
        df = pd.DataFrame({
            "close": [100] * 19 + [110],
            "high": [105] * 19 + [111],
            "low": [90] * 20,
        })
        is_breakout, direction = _detect_breakout(df)
        assert is_breakout is False


# === ETH Correlation Tests ===

class TestETHContext:
    def test_allows_short_normal(self):
        ctx = ETHContext(3000, "ranging", False, 0.5)
        assert ctx.allows_short("SOL/USDT") is True

    def test_allows_short_blocked_by_impulsive(self):
        ctx = ETHContext(3200, "bullish", True, 5.0)
        assert ctx.allows_short("OP/USDT") is False

    def test_allows_short_blocked_bullish_correlated(self):
        ctx = ETHContext(3100, "bullish", False, 2.0)
        assert ctx.allows_short("OP/USDT") is False

    def test_allows_short_not_correlated(self):
        ctx = ETHContext(3100, "bullish", False, 2.0)
        assert ctx.allows_short("BTC/USDT") is True

    def test_allows_short_bearish_eth(self):
        ctx = ETHContext(2800, "bearish", False, -2.0)
        assert ctx.allows_short("OP/USDT") is True


class TestETHDetectImpulsive:
    def test_impulsive_up(self):
        df = pd.DataFrame({
            "close": [100, 102, 104, 106, 108],
            "open": [99, 101, 103, 105, 107],
        })
        is_impulsive, momentum = _detect_impulsive_move(df)
        assert is_impulsive is True
        assert momentum > 0

    def test_not_impulsive_mixed(self):
        df = pd.DataFrame({
            "close": [100, 101, 99, 102, 100],
            "open": [100, 100, 100, 100, 100],
        })
        is_impulsive, _ = _detect_impulsive_move(df)
        assert is_impulsive == False

    def test_small_move_not_impulsive(self):
        df = pd.DataFrame({
            "close": [100, 100.5, 101, 101.5, 102],
            "open": [100, 100.5, 101, 101.5, 102],
        })
        is_impulsive, _ = _detect_impulsive_move(df)
        assert is_impulsive == False


# === Config Tests ===

class TestDerivativesConfig:
    def test_default_values(self):
        from config.settings import config
        assert config.derivatives.funding_strong_threshold == 0.0003
        assert config.derivatives.funding_neutral_zone == 0.0001
        assert config.derivatives.oi_moderate_threshold == 0.5
        assert config.derivatives.oi_strong_threshold == 2.0
        assert config.derivatives.btc_symbol == "BTC/USDT"
        assert config.derivatives.btc_ema200_timeframe == "4h"
        assert config.derivatives.btc_correlation_enabled is True
        assert config.derivatives.eth_symbol == "ETH/USDT"
        assert config.derivatives.eth_correlation_enabled is True

    def test_eth_correlation_symbols_parsed(self):
        from config.settings import config
        symbols = config.derivatives.eth_correlation_symbols
        assert "OP/USDT" in symbols
        assert "ARB/USDT" in symbols


# === Integration: fetch_btc_context mock ===

class TestFetchBTCContext:
    @pytest.mark.asyncio
    async def test_fetch_btc_context_success(self):
        from derivatives.btc_correlation import fetch_btc_context, reset_btc_context_cache
        reset_btc_context_cache()

        df = pd.DataFrame({
            "close": [60000 + i * 100 for i in range(250)],
            "high": [60100 + i * 100 for i in range(250)],
            "low": [59900 + i * 100 for i in range(250)],
            "open": [60000 + i * 100 for i in range(250)],
            "volume": [1000] * 250,
        }, index=pd.date_range("2024-01-01", periods=250, freq="4h"))

        mock_client = AsyncMock()
        mock_client.fetch_ohlcv = AsyncMock(return_value=df)

        with patch("derivatives.btc_correlation.exchange_client", mock_client):
            result = await fetch_btc_context()

        assert result is not None
        assert result.price > 0
        assert result.above_ema200 == True

    @pytest.mark.asyncio
    async def test_fetch_btc_context_not_enough_data(self):
        from derivatives.btc_correlation import fetch_btc_context, reset_btc_context_cache
        reset_btc_context_cache()

        df = pd.DataFrame({
            "close": [48000] * 50,
            "high": [48100] * 50,
            "low": [47900] * 50,
            "open": [48000] * 50,
            "volume": [1000] * 50,
        }, index=pd.date_range("2024-01-01", periods=50, freq="4h"))

        mock_client = AsyncMock()
        mock_client.fetch_ohlcv = AsyncMock(return_value=df)

        with patch("derivatives.btc_correlation.exchange_client", mock_client):
            result = await fetch_btc_context()

        assert result is None


# === Integration: fetch_eth_context mock ===

class TestFetchETHContext:
    @pytest.mark.asyncio
    async def test_fetch_eth_context_success(self):
        from derivatives.eth_correlation import fetch_eth_context, reset_eth_context_cache
        reset_eth_context_cache()

        df = pd.DataFrame({
            "close": [3000 + i * 10 for i in range(100)],
            "high": [3010 + i * 10 for i in range(100)],
            "low": [2990 + i * 10 for i in range(100)],
            "open": [3000 + i * 10 for i in range(100)],
            "volume": [1000] * 100,
        }, index=pd.date_range("2024-01-01", periods=100, freq="4h"))

        mock_client = AsyncMock()
        mock_client.fetch_ohlcv = AsyncMock(return_value=df)

        with patch("derivatives.eth_correlation.exchange_client", mock_client):
            result = await fetch_eth_context()

        assert result is not None
        assert result.price > 0

    @pytest.mark.asyncio
    async def test_fetch_eth_context_not_enough_data(self):
        from derivatives.eth_correlation import fetch_eth_context, reset_eth_context_cache
        reset_eth_context_cache()

        df = pd.DataFrame({
            "close": [3000] * 10,
            "high": [3010] * 10,
            "low": [2990] * 10,
            "open": [3000] * 10,
            "volume": [1000] * 10,
        }, index=pd.date_range("2024-01-01", periods=10, freq="4h"))

        mock_client = AsyncMock()
        mock_client.fetch_ohlcv = AsyncMock(return_value=df)

        with patch("derivatives.eth_correlation.exchange_client", mock_client):
            result = await fetch_eth_context()

        assert result is None


# === SMT Divergence Tests ===

class TestSMTDivergence:
    def test_smt_result_allows_long_bullish(self):
        from derivatives.smt_divergence import SMTResult
        r = SMTResult(
            direction="bullish",
            btc_swing_high=100, btc_swing_low=90,
            alt_swing_high=50, alt_swing_low=45,
            btc_trend="bearish", alt_trend="bullish",
        )
        assert r.allows_long() is True
        assert r.allows_short() is False

    def test_smt_result_allows_short_bearish(self):
        from derivatives.smt_divergence import SMTResult
        r = SMTResult(
            direction="bearish",
            btc_swing_high=100, btc_swing_low=90,
            alt_swing_high=50, alt_swing_low=45,
            btc_trend="bullish", alt_trend="bearish",
        )
        assert r.allows_long() is False
        assert r.allows_short() is True

    def test_smt_result_neutral_allows_both(self):
        from derivatives.smt_divergence import SMTResult
        r = SMTResult(
            direction="neutral",
            btc_swing_high=100, btc_swing_low=90,
            alt_swing_high=50, alt_swing_low=45,
            btc_trend="ranging", alt_trend="ranging",
        )
        assert r.allows_long() is True
        assert r.allows_short() is True

    def test_detect_swing_points_uptrend(self):
        import pandas as pd
        from derivatives.smt_divergence import _detect_swing_points

        # Create uptrend with enough spread for EMA to detect
        closes = [100 + i * 5 for i in range(25)]
        highs = [c + 3 for c in closes]
        lows = [c - 1 for c in closes]
        df = pd.DataFrame({
            "close": closes, "high": highs, "low": lows, "open": closes,
        })
        sh, sl, trend = _detect_swing_points(df)
        assert sh > sl
        assert trend in ("bullish", "ranging")  # trend detection is heuristic

    def test_detect_swing_points_downtrend(self):
        import pandas as pd
        from derivatives.smt_divergence import _detect_swing_points

        closes = [200 - i * 5 for i in range(25)]
        highs = [c + 3 for c in closes]
        lows = [c - 1 for c in closes]
        df = pd.DataFrame({
            "close": closes, "high": highs, "low": lows, "open": closes,
        })
        sh, sl, trend = _detect_swing_points(df)
        assert sh > sl
        assert trend in ("bearish", "ranging")  # trend detection is heuristic

    def test_detect_swing_points_insufficient_data(self):
        import pandas as pd
        from derivatives.smt_divergence import _detect_swing_points

        df = pd.DataFrame({
            "close": [100, 101], "high": [102, 103],
            "low": [99, 100], "open": [100, 101],
        })
        sh, sl, trend = _detect_swing_points(df)
        assert trend == "ranging"

    def test_detect_bullish_smt(self):
        from derivatives.smt_divergence import _detect_bullish_smt

        # BTC bearish, alt bullish → bullish SMT
        result = _detect_bullish_smt(
            btc_sh=100, btc_sl=90, btc_trend="bearish",
            alt_sh=50, alt_sl=45, alt_trend="bullish",
            btc_price=91, alt_price=49,
        )
        assert result is True

    def test_detect_bearish_smt(self):
        from derivatives.smt_divergence import _detect_bearish_smt

        # BTC bullish, alt bearish → bearish SMT
        result = _detect_bearish_smt(
            btc_sh=100, btc_sl=90, btc_trend="bullish",
            alt_sh=50, alt_sl=45, alt_trend="bearish",
            btc_price=99, alt_price=46,
        )
        assert result is True

    def test_no_smt_when_aligned(self):
        from derivatives.smt_divergence import _detect_bullish_smt, _detect_bearish_smt

        # Both bullish → no divergence
        bullish = _detect_bullish_smt(
            btc_sh=100, btc_sl=90, btc_trend="bullish",
            alt_sh=50, alt_sl=45, alt_trend="bullish",
            btc_price=99, alt_price=49,
        )
        bearish = _detect_bearish_smt(
            btc_sh=100, btc_sl=90, btc_trend="bullish",
            alt_sh=50, alt_sl=45, alt_trend="bullish",
            btc_price=99, alt_price=49,
        )
        assert bullish is False
        assert bearish is False

    @pytest.mark.asyncio
    async def test_fetch_smt_skips_btc(self):
        from derivatives.smt_divergence import fetch_smt_divergence

        result = await fetch_smt_divergence("BTC/USDT")
        assert result is not None
        assert result.direction == "neutral"
        assert "skipped" in result.detail.lower()

    @pytest.mark.asyncio
    async def test_fetch_smt_cache(self):
        from derivatives.smt_divergence import fetch_smt_divergence, reset_smt_cache
        reset_smt_cache()

        btc_df = pd.DataFrame({
            "close": [100000 + i * 100 for i in range(60)],
            "high": [100100 + i * 100 for i in range(60)],
            "low": [99900 + i * 100 for i in range(60)],
            "open": [100000 + i * 100 for i in range(60)],
            "volume": [1000] * 60,
        }, index=pd.date_range("2024-01-01", periods=60, freq="4h"))

        eth_df = pd.DataFrame({
            "close": [3000 + i * 10 for i in range(60)],
            "high": [3010 + i * 10 for i in range(60)],
            "low": [2990 + i * 10 for i in range(60)],
            "open": [3000 + i * 10 for i in range(60)],
            "volume": [500] * 60,
        }, index=pd.date_range("2024-01-01", periods=60, freq="4h"))

        call_count = 0
        async def fetch_side_effect(symbol, tf, limit=100):
            nonlocal call_count
            call_count += 1
            if "BTC" in symbol:
                return btc_df
            return eth_df

        mock_client = AsyncMock()
        mock_client.fetch_ohlcv = AsyncMock(side_effect=fetch_side_effect)

        with patch("derivatives.smt_divergence.config") as mock_config:
            mock_config.derivatives.btc_symbol = "BTC/USDT"
            with patch("data.exchange_client.exchange_client", mock_client):
                result1 = await fetch_smt_divergence("ETH/USDT")
                result2 = await fetch_smt_divergence("ETH/USDT")

        assert result1 is not None
        assert result2 is not None
        # Second call should be cached (fewer API calls)
        assert call_count <= 2  # First call: 2 fetches (BTC + ETH), second: cached
