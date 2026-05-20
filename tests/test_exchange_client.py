import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.exchange_client import ExchangeClient, exchange_client
from config.settings import config


@pytest.fixture
def client():
    return ExchangeClient()


@pytest.fixture
def mock_ccxt():
    with patch("data.exchange_client.ccxt") as mock:
        mock_exchange = MagicMock()
        mock_exchange.fetch_ohlcv = AsyncMock()
        mock_exchange.close = AsyncMock()
        mock_class = MagicMock(return_value=mock_exchange)
        setattr(mock, "binance", mock_class)
        mock.NetworkError = Exception
        mock.ExchangeError = Exception
        yield mock, mock_exchange


class TestExchangeClient:
    @pytest.mark.asyncio
    async def test_connect(self, client, mock_ccxt):
        mock, mock_ex = mock_ccxt
        await client.connect()
        assert client._exchange is not None

    @pytest.mark.asyncio
    async def test_connect_creates_exchange(self, client, mock_ccxt):
        mock, _ = mock_ccxt
        await client.connect()
        mock.binance.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_ohlcv_returns_dataframe(self, client, mock_ccxt):
        _, mock_ex = mock_ccxt
        now_ms = 1715000000000
        raw = [[now_ms + i * 3600000, 100.0, 101.0, 99.0, 100.5, 1000.0] for i in range(10)]
        mock_ex.fetch_ohlcv.return_value = raw
        await client.connect()
        df = await client.fetch_ohlcv("BTC/USDT", "1h", limit=10)
        assert df is not None
        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert len(df) == 9

    @pytest.mark.asyncio
    async def test_fetch_ohlcv_empty_response(self, client, mock_ccxt):
        _, mock_ex = mock_ccxt
        mock_ex.fetch_ohlcv.return_value = []
        await client.connect()
        result = await client.fetch_ohlcv("BTC/USDT", "1h")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_ohlcv_network_error(self, client, mock_ccxt):
        _, mock_ex = mock_ccxt
        mock_ex.fetch_ohlcv.side_effect = Exception("Network error")
        await client.connect()
        result = await client.fetch_ohlcv("BTC/USDT", "1h")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_all_symbols(self, client, mock_ccxt):
        _, mock_ex = mock_ccxt
        now_ms = 1715000000000
        mock_ex.fetch_ohlcv.return_value = [
            [now_ms + i * 3600000, 100.0, 101.0, 99.0, 100.5, 1000.0] for i in range(10)
        ]
        await client.connect()
        data = await client.fetch_all_symbols("1h", limit=10)
        assert len(data) > 0

    @pytest.mark.asyncio
    async def test_close(self, client, mock_ccxt):
        _, mock_ex = mock_ccxt
        await client.connect()
        await client.close()
        mock_ex.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_when_not_connected(self, client):
        await client.close()

    def test_singleton_exists(self):
        assert exchange_client is not None
        assert isinstance(exchange_client, ExchangeClient)

    @pytest.mark.asyncio
    async def test_connect_passes_defaultType_from_config(self, client, mock_ccxt):
        mock, _ = mock_ccxt
        await client.connect()
        call_kwargs = mock.binance.call_args[0][0]
        assert call_kwargs["options"]["defaultType"] == "spot"

    @pytest.mark.asyncio
    async def test_connect_defaultType_future(self, client, mock_ccxt, monkeypatch):
        monkeypatch.setattr(config.exchange, "market_type", "future")
        mock, _ = mock_ccxt
        await client.connect()
        call_kwargs = mock.binance.call_args[0][0]
        assert call_kwargs["options"]["defaultType"] == "future"

    @pytest.mark.asyncio
    async def test_fetch_taker_buy_volumes_spot_returns_none(self, client, mock_ccxt, monkeypatch):
        """Spot market should return None for taker buy volumes."""
        monkeypatch.setattr(config.exchange, "market_type", "spot")
        _, mock_ex = mock_ccxt
        await client.connect()
        result = await client._fetch_taker_buy_volumes("BTC/USDT", "1h", 10)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_ohlcv_without_taker_buy(self, client, mock_ccxt, monkeypatch):
        """Spot market fetch_ohlcv should not have taker_buy_volume column."""
        monkeypatch.setattr(config.exchange, "market_type", "spot")
        _, mock_ex = mock_ccxt
        now_ms = 1715000000000
        raw = [[now_ms + i * 3600000, 100.0, 101.0, 99.0, 100.5, 1000.0] for i in range(10)]
        mock_ex.fetch_ohlcv.return_value = raw
        await client.connect()
        df = await client.fetch_ohlcv("BTC/USDT", "1h", limit=10)
        assert df is not None
        assert "taker_buy_volume" not in df.columns
