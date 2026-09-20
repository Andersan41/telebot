"""Resend TRX signal with chart to Telegram."""
import asyncio
import sys
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()

from storage.database import db
from data.exchange_client import exchange_client
from charts.signal_chart import generate_signal_chart
from bot.notifier import send_signal
from strategy.signal_engine import SignalResult


async def main():
    await db.init()

    # Get latest TRX signal
    signals = await db.get_recent_signals(limit=50)
    trx = next((s for s in signals if "TRX" in s.symbol), None)
    if not trx:
        print("No TRX signal found")
        return

    print(f"Found: #{trx.id} {trx.symbol} {trx.signal_type} close={trx.close_price} sl={trx.sl} tp={trx.tp}")

    # Fetch candles
    await exchange_client.connect()
    df = await exchange_client.fetch_ohlcv(trx.symbol, trx.timeframe, limit=100)
    if df is None or df.empty:
        print("No candles fetched")
        return

    print(f"Fetched {len(df)} candles")

    # Generate chart
    png = generate_signal_chart(
        df=df,
        direction="buy" if trx.signal_type == "BUY" else "sell",
        entry_price=trx.close_price,
        sl=trx.sl,
        tp=trx.tp,
        symbol=trx.symbol,
        timeframe=trx.timeframe,
        score=trx.score,
    )
    print(f"Chart: {len(png)} bytes")

    # Build SignalResult for send_signal
    from strategy.signal_engine import SignalType
    sig_type = SignalType.BUY if trx.signal_type == "BUY" else SignalType.SELL
    result = SignalResult(
        signal=sig_type,
        symbol=trx.symbol,
        timeframe=trx.timeframe,
        close=trx.close_price,
        entry_price=trx.close_price,
        sl=trx.sl,
        tp=trx.tp,
        score=trx.score,
    )

    await send_signal(result, chart_png=png)
    print("Sent!")


asyncio.run(main())
