import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backtest.engine import BacktestEngine, get_preset_config
from config.settings import config

async def test():
    config.trading.candles_limit = 3900
    bt_config = get_preset_config("task2_only")

    # Monkey-patch to use paginated fetch (same as run_abn.py)
    from data.exchange_client import exchange_client
    _orig_fetch = exchange_client.fetch_ohlcv
    async def _fetch_paginated(symbol, timeframe, limit=200):
        if limit > 998:
            return await exchange_client.fetch_ohlcv_paginated(
                symbol, timeframe, total_limit=limit, page_size=998,
            )
        return await _orig_fetch(symbol, timeframe, limit)
    exchange_client.fetch_ohlcv = _fetch_paginated

    try:
        engine = BacktestEngine(symbol="BTC/USDT", timeframe="1h", bt_config=bt_config, send_telegram=False)
        result = await engine.run()
    finally:
        exchange_client.fetch_ohlcv = _orig_fetch
    print(f"Trades: {result.total_trades}")
    print(f"Signals: {result.signals_generated}")
    src_atr = sum(1 for t in result.trades if t.sl_source == "atr")
    src_bos = sum(1 for t in result.trades if t.sl_source == "bos")
    src_struct = sum(1 for t in result.trades if t.sl_source == "structural")
    print(f"SL source ATR: {src_atr}")
    print(f"SL source BOS: {src_bos}")
    print(f"SL source Structural: {src_struct}")
    for t in result.trades[:10]:
        print(f"  {t.direction} src={t.sl_source} entry={t.entry_price:.2f} sl={t.sl:.2f}")

asyncio.run(test())
