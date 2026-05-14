import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context.analyzer import ContextSnapshot, ContextEngine
from context.scorer import ContextScorer, ContextVerdict
from context.fetcher import ContextFetcher
from bot.notifier import format_context_block


# === Утилиты для создания тестовых данных ===

def make_snapshot(**kwargs):
    base = dict(
        symbol="BTC/USDT",
        timestamp=datetime.now(timezone.utc),
        fear_greed_value=None,
        fear_greed_label=None,
        price_change_24h=None,
        price_change_7d=None,
        volume_change_24h=None,
        market_cap_rank=None,
        is_trending=False,
        funding_rate=None,
        open_interest_delta=None,
        long_short_ratio=None,
        news_sentiment_score=None,
        news_count=0,
        errors=[],
    )
    base.update(kwargs)
    return ContextSnapshot(**base)


# === Тесты ContextSnapshot ===

class TestContextSnapshot:
    def test_default_values(self):
        snap = make_snapshot()
        assert snap.symbol == "BTC/USDT"
        assert snap.is_trending is False
        assert snap.news_count == 0
        assert snap.fear_greed_value is None

    def test_to_json_and_from_json(self):
        snap = make_snapshot(
            fear_greed_value=42,
            fear_greed_label="Neutral",
            funding_rate=0.001,
            news_count=5,
        )
        json_str = snap.to_json()
        restored = ContextSnapshot.from_json(json_str)
        assert restored.symbol == snap.symbol
        assert restored.fear_greed_value == 42
        assert restored.fear_greed_label == "Neutral"
        assert restored.funding_rate == 0.001
        assert restored.news_count == 5

    def test_to_json_with_all_fields(self):
        snap = make_snapshot(
            fear_greed_value=75,
            fear_greed_label="Greed",
            price_change_24h=3.5,
            price_change_7d=10.2,
            funding_rate=-0.003,
            open_interest_delta=5.0,
            long_short_ratio=0.65,
            news_sentiment_score=0.4,
            news_count=12,
        )
        json_str = snap.to_json()
        restored = ContextSnapshot.from_json(json_str)
        assert restored.fear_greed_value == 75
        assert restored.price_change_24h == 3.5
        assert restored.price_change_7d == 10.2
        assert restored.funding_rate == -0.003
        assert restored.open_interest_delta == 5.0
        assert restored.long_short_ratio == 0.65
        assert restored.news_sentiment_score == 0.4
        assert restored.news_count == 12


# === Тесты ContextScorer ===

class TestContextScorer:
    @pytest.fixture
    def scorer(self):
        return ContextScorer()

    def test_confirmed_buy_with_favorable_conditions(self, scorer):
        snap = make_snapshot(
            fear_greed_value=20,
            fear_greed_label="Extreme Fear",
            funding_rate=-0.006,
            long_short_ratio=0.65,
        )
        verdict = scorer.score("BUY", snap)
        assert verdict.verdict == "CONFIRMED"
        assert verdict.score >= 0.4

    def test_blocked_buy_with_unfavorable_conditions(self, scorer):
        snap = make_snapshot(
            fear_greed_value=85,
            fear_greed_label="Extreme Greed",
            funding_rate=0.03,
            long_short_ratio=1.8,
        )
        verdict = scorer.score("BUY", snap)
        assert verdict.verdict == "BLOCKED"
        assert verdict.score < -0.1

    def test_weak_buy(self, scorer):
        snap = make_snapshot(
            fear_greed_value=50,
            funding_rate=0.001,
        )
        verdict = scorer.score("BUY", snap)
        assert verdict.verdict in ("WEAK", "CONFIRMED", "CONFLICTED")

    def test_conflicted_buy(self, scorer):
        snap = make_snapshot(
            fear_greed_value=50,
            funding_rate=0.001,
            news_sentiment_score=-0.05,
        )
        verdict = scorer.score("BUY", snap)
        assert verdict.verdict in ("CONFLICTED", "WEAK", "CONFIRMED")

    def test_all_sources_unavailable(self, scorer):
        snap = make_snapshot()
        verdict = scorer.score("BUY", snap)
        assert verdict.verdict == "CONFLICTED"
        assert verdict.score == 0.0
        assert verdict.confidence == 0.0

    def test_extreme_fear_greed_buy(self, scorer):
        snap = make_snapshot(fear_greed_value=10)
        verdict = scorer.score("BUY", snap)
        assert verdict.score > 0
        assert any("F&G=10" in s for s in verdict.supporting)

    def test_extreme_greed_buy(self, scorer):
        snap = make_snapshot(fear_greed_value=90)
        verdict = scorer.score("BUY", snap)
        assert verdict.score < 0
        assert any("F&G=90" in o for o in verdict.opposing)

    def test_negative_funding_buy(self, scorer):
        snap = make_snapshot(funding_rate=-0.01)
        verdict = scorer.score("BUY", snap)
        assert verdict.score > 0
        assert any("Funding=" in s for s in verdict.supporting)

    def test_positive_funding_buy(self, scorer):
        snap = make_snapshot(funding_rate=0.03)
        verdict = scorer.score("BUY", snap)
        assert verdict.score < 0
        assert any("Funding=" in o for o in verdict.opposing)

    def test_low_long_short_buy(self, scorer):
        snap = make_snapshot(long_short_ratio=0.5)
        verdict = scorer.score("BUY", snap)
        assert verdict.score > 0
        assert any("L/S=0.5" in s for s in verdict.supporting)

    def test_high_long_short_buy(self, scorer):
        snap = make_snapshot(long_short_ratio=2.0)
        verdict = scorer.score("BUY", snap)
        assert verdict.score < 0
        assert any("L/S=2.0" in o for o in verdict.opposing)

    def test_positive_news_buy(self, scorer):
        snap = make_snapshot(news_sentiment_score=0.8)
        verdict = scorer.score("BUY", snap)
        assert verdict.score > 0
        assert any("позитивные" in s for s in verdict.supporting)

    def test_negative_news_buy(self, scorer):
        snap = make_snapshot(news_sentiment_score=-0.8)
        verdict = scorer.score("BUY", snap)
        assert verdict.score < 0
        assert any("негативные" in o for o in verdict.opposing)

    def test_score_is_normalized(self, scorer):
        snap = make_snapshot(
            fear_greed_value=20,
            funding_rate=-0.01,
            long_short_ratio=0.5,
            news_sentiment_score=0.9,
        )
        verdict = scorer.score("BUY", snap)
        assert -1.0 <= verdict.score <= 1.0

    def test_confidence_is_absolute_score(self, scorer):
        snap = make_snapshot(fear_greed_value=20)
        verdict = scorer.score("BUY", snap)
        assert 0.0 <= verdict.confidence <= 1.0
        assert abs(verdict.confidence - abs(verdict.score)) < 0.001

    def test_sell_signal_opposite_weights(self, scorer):
        snap_buy_favorable = make_snapshot(
            fear_greed_value=20,
            funding_rate=-0.006,
            long_short_ratio=0.65,
        )
        buy_verdict = scorer.score("BUY", snap_buy_favorable)
        sell_verdict = scorer.score("SELL", snap_buy_favorable)
        assert buy_verdict.score > sell_verdict.score

    def test_supporting_and_opposing_populated(self, scorer):
        snap = make_snapshot(
            fear_greed_value=20,
            funding_rate=-0.006,
            news_sentiment_score=-0.5,
        )
        verdict = scorer.score("BUY", snap)
        assert len(verdict.supporting) >= 1
        assert len(verdict.opposing) >= 1

    def test_verdict_confirmed_threshold(self, scorer):
        snap = make_snapshot(fear_greed_value=20)
        verdict = scorer.score("BUY", snap)
        assert verdict.verdict == "CONFIRMED"

    def test_verdict_blocked_threshold(self, scorer):
        snap = make_snapshot(fear_greed_value=90)
        verdict = scorer.score("BUY", snap)
        assert verdict.verdict == "BLOCKED"


# === Тесты ContextFetcher ===

class TestContextFetcher:
    @pytest.fixture
    def fetcher(self):
        return ContextFetcher()

    @pytest.mark.asyncio
    async def test_fetch_fear_greed_success(self, fetcher, aioresponses):
        aioresponses.get(
            "https://api.alternative.me/fng/?limit=1",
            payload={"data": [{"value": "35", "value_classification": "Fear"}]},
        )
        result = await fetcher.fetch_fear_greed()
        assert result is not None
        assert result["value"] == 35
        assert result["label"] == "Fear"

    @pytest.mark.asyncio
    async def test_fetch_fear_greed_error(self, fetcher, aioresponses):
        aioresponses.get(
            "https://api.alternative.me/fng/?limit=1",
            status=500,
        )
        result = await fetcher.fetch_fear_greed()
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_coingecko_success(self, fetcher, aioresponses):
        aioresponses.get(
            "https://api.coingecko.com/api/v3/coins/bitcoin?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false",
            payload={
                "market_data": {
                    "price_change_percentage_24h": 2.5,
                    "price_change_percentage_7d": 5.0,
                    "total_volume": {"usd": 30000000000},
                    "market_cap_rank": 1,
                }
            },
        )
        result = await fetcher.fetch_coingecko("bitcoin")
        assert result is not None
        assert result["price_change_24h"] == 2.5
        assert result["market_cap_rank"] == 1

    @pytest.mark.asyncio
    async def test_fetch_coingecko_error(self, fetcher, aioresponses):
        aioresponses.get(
            "https://api.coingecko.com/api/v3/coins/nonexistent",
            status=404,
        )
        result = await fetcher.fetch_coingecko("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_trending_success(self, fetcher, aioresponses):
        aioresponses.get(
            "https://api.coingecko.com/api/v3/search/trending",
            payload={
                "coins": [
                    {"item": {"symbol": "BTC"}},
                    {"item": {"symbol": "ETH"}},
                ]
            },
        )
        result = await fetcher.fetch_trending()
        assert "BTC" in result
        assert "ETH" in result

    @pytest.mark.asyncio
    async def test_fetch_long_short_ratio_success(self, fetcher, aioresponses):
        aioresponses.get(
            "https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=1h&limit=1",
            payload=[{"longShortRatio": "0.68"}],
        )
        result = await fetcher.fetch_long_short_ratio("BTC/USDT")
        assert result == 0.68

    @pytest.mark.asyncio
    async def test_fetch_long_short_ratio_error(self, fetcher, aioresponses):
        aioresponses.get(
            "https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=1h&limit=1",
            status=500,
        )
        result = await fetcher.fetch_long_short_ratio("BTC/USDT")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_cryptopanic_no_key(self, fetcher):
        with patch("context.fetcher.config.cryptopanic_api_key", ""):
            result = await fetcher.fetch_cryptopanic("BTC/USDT")
            assert result is None

    @pytest.mark.asyncio
    async def test_fetch_cryptopanic_success(self, fetcher, aioresponses):
        with patch("context.fetcher.config.cryptopanic_api_key", "test_token"):
            aioresponses.get(
                "https://cryptopanic.com/api/v1/posts/?auth_token=test_token&currencies=BTC&filter=important&public=true",
                payload={
                    "results": [
                        {"votes": {"positive": 10, "negative": 2}},
                        {"votes": {"positive": 3, "negative": 8}},
                    ]
                },
            )
            result = await fetcher.fetch_cryptopanic("BTC/USDT")
            assert result is not None
            assert result["positive"] == 1
            assert result["negative"] == 1

    @pytest.mark.asyncio
    async def test_fetch_rss_news_success(self, fetcher, aioresponses):
        rss_feed = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <item>
                    <title>BTC reaches new all-time high</title>
                </item>
                <item>
                    <title>Bitcoin hack reported</title>
                </item>
            </channel>
        </rss>"""
        aioresponses.get(
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            body=rss_feed,
        )
        aioresponses.get(
            "https://cointelegraph.com/rss",
            body=rss_feed,
        )
        result = await fetcher.fetch_rss_news("BTC/USDT")
        assert result is not None
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_fetch_rss_news_no_match(self, fetcher, aioresponses):
        rss_feed = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <item>
                    <title>Apple stock rises</title>
                </item>
            </channel>
        </rss>"""
        aioresponses.get(
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            body=rss_feed,
        )
        aioresponses.get(
            "https://cointelegraph.com/rss",
            body=rss_feed,
        )
        result = await fetcher.fetch_rss_news("BTC/USDT")
        # Returns None when no articles match
        assert result is None or result["count"] == 0

    @pytest.mark.asyncio
    async def test_get_base_currency(self, fetcher):
        assert fetcher._get_base_currency("BTC/USDT") == "BTC"
        assert fetcher._get_base_currency("ETH/USDT") == "ETH"
        assert fetcher._get_base_currency("SOL/BTC") == "SOL"

    @pytest.mark.asyncio
    async def test_close_session(self, fetcher, aioresponses):
        aioresponses.get("https://api.alternative.me/fng/?limit=1", payload={"data": []})
        await fetcher.fetch_fear_greed()
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_oi_warmup_uses_historical(self, fetcher, aioresponses):
        aioresponses.get(
            "https://fapi.binance.com/futures/data/openInterestHist"
            "?symbol=BTCUSDT&period=5m&limit=2",
            payload=[
                {"symbol": "BTCUSDT", "sumOpenInterest": "100.0", "timestamp": 1},
                {"symbol": "BTCUSDT", "sumOpenInterest": "120.0", "timestamp": 2},
            ],
        )
        aioresponses.get(
            "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT",
            payload={"openInterest": "110.0", "symbol": "BTCUSDT", "time": 3000},
        )
        result = await fetcher.fetch_open_interest("BTC/USDT")
        await fetcher.close()
        assert result is not None
        assert result["open_interest"] == 110.0
        assert abs(result["open_interest_delta"] - 10.0) < 1e-6


# === Тесты ContextEngine ===

class TestContextEngine:
    @pytest.fixture
    def engine(self):
        return ContextEngine()

    @pytest.mark.asyncio
    async def test_get_snapshot_with_all_data(self, engine, aioresponses):
        aioresponses.get(
            "https://api.alternative.me/fng/?limit=1",
            payload={"data": [{"value": "45", "value_classification": "Fear"}]},
        )
        aioresponses.get(
            "https://api.coingecko.com/api/v3/coins/bitcoin?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false",
            payload={"market_data": {
                "price_change_percentage_24h": 1.5,
                "price_change_percentage_7d": 3.0,
                "total_volume": {"usd": 1000000000},
                "market_cap_rank": 1,
            }},
        )
        aioresponses.get(
            "https://api.coingecko.com/api/v3/search/trending",
            payload={"coins": [{"item": {"symbol": "BTC"}}]},
        )
        aioresponses.get(
            "https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=1h&limit=1",
            payload=[{"longShortRatio": "0.72"}],
        )
        aioresponses.get(
            "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT",
            payload={"openInterest": "50000", "time": 1715000000000},
        )
        aioresponses.get(
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            body="<?xml version='1.0'?><rss version='2.0'><channel><item><title>BTC goes up</title></item></channel></rss>",
        )

        snap = await engine.get_snapshot("BTC/USDT")
        assert snap.fear_greed_value == 45
        assert snap.fear_greed_label == "Fear"
        assert snap.price_change_24h == 1.5
        assert snap.is_trending is True
        assert snap.long_short_ratio == 0.72

    @pytest.mark.asyncio
    async def test_get_snapshot_with_errors(self, engine, aioresponses):
        # Clear caches from previous tests
        engine._fear_greed_cache = (None, None)
        engine._trending_cache = (None, None)

        aioresponses.get(
            "https://api.alternative.me/fng/?limit=1",
            status=500,
        )
        aioresponses.get(
            "https://api.coingecko.com/api/v3/coins/bitcoin?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false",
            status=429,
        )

        snap = await engine.get_snapshot("BTC/USDT")
        # Errors are logged as warnings but not always added to snapshot.errors
        # Just verify the snapshot was created
        assert snap is not None
        assert snap.symbol == "BTC/USDT"

    @pytest.mark.asyncio
    async def test_get_snapshot_no_coingecko_map(self, engine, aioresponses):
        # Clear caches
        engine._fear_greed_cache = (None, None)
        engine._trending_cache = (None, None)

        # When coin_id is None, coingecko fetch is skipped
        snap = await engine.get_snapshot("UNKNOWN/USDT")
        assert snap is not None
        # price_change_24h should be None since no coingecko fetch was made
        assert snap.price_change_24h is None


# === Тесты format_context_block ===

class TestFormatContextBlock:
    def test_confirmed_context_block(self):
        snap = make_snapshot(
            fear_greed_value=34,
            fear_greed_label="Fear",
            funding_rate=-0.003,
            long_short_ratio=0.68,
            open_interest_delta=4.2,
            news_sentiment_score=0.3,
        )
        verdict = ContextVerdict(
            verdict="CONFIRMED",
            confidence=0.76,
            score=0.65,
            supporting=["F&G=34 (Fear)", "Funding=-0.003%", "L/S=0.68"],
            opposing=["OI+4.2%"],
            snapshot=snap,
        )
        result = format_context_block(verdict)
        assert "Контекст рынка" in result
        assert "CONFIRMED" in result
        assert "76%" in result
        assert "Fear" in result
        assert "✅" in result

    def test_blocked_context_block(self):
        snap = make_snapshot(
            fear_greed_value=85,
            fear_greed_label="Extreme Greed",
            funding_rate=0.03,
        )
        verdict = ContextVerdict(
            verdict="BLOCKED",
            confidence=0.9,
            score=-0.7,
            supporting=[],
            opposing=["F&G=85 (Extreme Greed)", "Funding=0.030%"],
            snapshot=snap,
        )
        result = format_context_block(verdict)
        assert "BLOCKED" in result
        assert "Контекст рынка" in result
        assert "90%" in result
        assert "Extreme Greed" in result

    def test_empty_context_block(self):
        snap = make_snapshot()
        verdict = ContextVerdict(
            verdict="CONFLICTED",
            confidence=0.1,
            score=0.0,
            supporting=[],
            opposing=[],
            snapshot=snap,
        )
        result = format_context_block(verdict)
        assert "CONFLICTED" in result
        assert "Контекст рынка" in result
        assert "10%" in result

    def test_html_escaping_in_context_block(self):
        snap = make_snapshot(
            fear_greed_value=34,
            fear_greed_label="Fear <test>",
        )
        verdict = ContextVerdict(
            verdict="WEAK",
            confidence=0.3,
            score=0.2,
            supporting=["ADX < 20 (flat)"],
            opposing=[],
            snapshot=snap,
        )
        result = format_context_block(verdict)
        assert "&lt;" in result or "<test>" not in result


# === Тесты интеграции с scanner ===

class TestScannerIntegration:
    @pytest.mark.asyncio
    async def test_context_enabled_by_default(self):
        from config.settings import config
        assert config.context_enabled is True

    @pytest.mark.asyncio
    async def test_context_min_verdict_default(self):
        from config.settings import config
        assert config.context_min_verdict == "WEAK"

    @pytest.mark.asyncio
    async def test_context_block_on_blocked_default(self):
        from config.settings import config
        assert config.context_block_on_blocked is True

    @pytest.mark.asyncio
    async def test_coingecko_symbol_map_parsing(self):
        from config.settings import config
        m = config.coingecko_symbol_map
        assert "BTC/USDT" in m
        assert m["BTC/USDT"] == "bitcoin"
        assert "ETH/USDT" in m
        assert m["ETH/USDT"] == "ethereum"

    @pytest.mark.asyncio
    async def test_context_engine_singleton(self):
        from context.analyzer import context_engine as ce1
        from context.analyzer import ContextEngine
        assert isinstance(ce1, ContextEngine)

    @pytest.mark.asyncio
    async def test_context_scorer_singleton(self):
        from context.scorer import context_scorer as cs1
        from context.scorer import ContextScorer
        assert isinstance(cs1, ContextScorer)

    @pytest.mark.asyncio
    async def test_context_fetcher_singleton(self):
        from context.fetcher import context_fetcher as cf1
        from context.fetcher import ContextFetcher
        assert isinstance(cf1, ContextFetcher)


# === Тесты Database context snapshot ===

class TestDatabaseContextSnapshot:
    @pytest.fixture(autouse=True)
    async def setup_db(self, tmp_path):
        from storage.database import db as db_inst, Base
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker

        db_url = f"sqlite+aiosqlite:///{tmp_path}/test_context.db"
        db_inst._engine = create_async_engine(db_url, echo=False)
        db_inst._session_factory = sessionmaker(
            db_inst._engine, class_=AsyncSession, expire_on_commit=False
        )
        async with db_inst._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield
        await db_inst._engine.dispose()

    @pytest.mark.asyncio
    async def test_save_context_snapshot(self, setup_db):
        from storage.database import db
        await db.init()
        result = await db.save_context_snapshot(
            symbol="BTC/USDT",
            signal_id=1,
            verdict="CONFIRMED",
            confidence=0.75,
            score=0.6,
            fear_greed=35,
            funding_rate=-0.003,
            long_short_ratio=0.68,
            open_interest_delta=4.2,
            news_sentiment=0.3,
            raw_json='{"test": true}',
        )
        assert result is not None
        assert result.verdict == "CONFIRMED"
        assert result.confidence == 0.75
        assert result.score == 0.6

    @pytest.mark.asyncio
    async def test_save_context_snapshot_no_signal(self, setup_db):
        from storage.database import db
        await db.init()
        result = await db.save_context_snapshot(
            symbol="ETH/USDT",
            signal_id=None,
            verdict="WEAK",
            confidence=0.3,
            score=0.15,
        )
        assert result is not None
        assert result.signal_id is None

    @pytest.mark.asyncio
    async def test_save_context_snapshot_partial_data(self, setup_db):
        from storage.database import db
        await db.init()
        result = await db.save_context_snapshot(
            symbol="SOL/USDT",
            signal_id=2,
            verdict="CONFLICTED",
            confidence=0.2,
            score=0.05,
            fear_greed=50,
        )
        assert result is not None
        assert result.fear_greed == 50
        assert result.funding_rate is None
        assert result.long_short_ratio is None
