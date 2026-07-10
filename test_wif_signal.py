"""
test_wif_signal.py — Quick test analysis for WIF/USDT
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import config
from data.exchange_client import exchange_client
from indicators.engine import indicator_engine
from strategy.pattern_engine import pattern_engine
from strategy.trade_engine import trade_engine
from strategy.market_thesis_engine import market_thesis_engine, DynamicTradeThesis
from liquidity.sweep import detect_sweeps
from liquidity.order_blocks import detect_order_blocks
from liquidity.fvg import detect_fvg
from liquidity.equal_levels import detect_equal_levels
from liquidity.external import detect_external_liquidity
from liquidity.candle_quality import analyze_last_candle
from market_structure.structure import analyze_structure
from bot.notifier import get_bot
from telegram.constants import ParseMode
from loguru import logger
import html


SYMBOL = "WIF/USDT"
TIMEFRAME = "1h"


async def run():
    logger.info(f"Connecting to exchange...")
    await exchange_client.connect()

    logger.info(f"Fetching {SYMBOL} {TIMEFRAME}...")
    df = await exchange_client.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=config.trading.candles_limit)
    if df is None or len(df) < 10:
        logger.error("Not enough data")
        return

    ind = indicator_engine.calculate(df, SYMBOL, TIMEFRAME)
    if ind is None:
        logger.error("Indicator calc failed")
        return

    logger.info(f"Close: {ind.close} | ATR: {ind.atr}")

    _df_clean = df.dropna(subset=["open", "high", "low", "close", "volume"])
    sweeps = detect_sweeps(_df_clean, lookback=50)
    order_blocks = detect_order_blocks(_df_clean, lookback=100)
    structure = analyze_structure(_df_clean, lookback=50)
    fvgs = detect_fvg(_df_clean, lookback=getattr(config, "liquidity_fvg_lookback", 100))
    candle_quality = analyze_last_candle(_df_clean, atr_value=ind.atr)

    logger.info(f"Sweeps: {len(sweeps)} | OBs: {len(order_blocks)} | FVGs: {len(fvgs)}")

    setup = pattern_engine.detect(
        sweeps=sweeps, order_blocks=order_blocks, structure=structure,
        fvgs=fvgs, candle_quality=candle_quality, current_price=ind.close,
    )
    logger.info(f"Setup: detected={setup.detected} direction={setup.direction}")

    trade_plan = trade_engine.build_trade_plan(
        ind=ind, direction=setup.direction if setup.detected else "buy",
        structure=structure, order_blocks=order_blocks, sweeps=sweeps,
        fvgs=fvgs, df=_df_clean, timeframe=TIMEFRAME,
    )

    entry_price = ind.close

    _swing_highs = getattr(structure, "swing_points", []) or []
    _swing_lows = getattr(structure, "swing_points", []) or []
    _equal_levels = detect_equal_levels(_swing_highs, _swing_lows)
    _external_levels = detect_external_liquidity(_df_clean, lookback=200)

    liq_graph = market_thesis_engine.build_liquidity_graph(
        current_price=entry_price, sweeps=sweeps, order_blocks=order_blocks,
        fvgs=fvgs, structure=structure, equal_levels=_equal_levels,
        external_levels=_external_levels, candle_quality=candle_quality,
        timeframe=TIMEFRAME,
    )
    logger.info(f"Graph: {len(liq_graph.nodes)} nodes")

    thesis = DynamicTradeThesis(symbol=SYMBOL, timeframe=TIMEFRAME)
    last_row = _df_clean.iloc[-1]
    candle_data = {
        "open": float(last_row["open"]), "high": float(last_row["high"]),
        "low": float(last_row["low"]), "close": float(last_row["close"]),
        "volume": float(last_row["volume"]),
    }
    thesis.update(liq_graph, entry_price, candle_data, atr=ind.atr if ind.atr else 0)

    best = thesis.best_scenario
    if best and best.is_active:
        logger.info(f"Thesis: BUY={thesis.buy_scenario.probability:.2f} SELL={thesis.sell_scenario.probability:.2f}")

    opportunity = market_thesis_engine.evaluate_trade_opportunity(
        graph=liq_graph, direction=setup.direction if setup.detected else "buy",
        entry_price=entry_price, atr=ind.atr if ind.atr else 0,
        symbol=SYMBOL, timeframe=TIMEFRAME,
    )

    direction = setup.direction if setup.detected else "buy"
    from strategy.signal_engine import SignalResult, SignalType
    signal_type = SignalType.BUY if direction == "buy" else SignalType.SELL

    sl = trade_plan.sl
    tp = trade_plan.tp
    thesis_score = 0.0
    thesis_stability = thesis.scenario_stability

    if opportunity:
        thesis_sl = opportunity.invalidation
        thesis_tp = opportunity.expected_target
        thesis_score = opportunity.scenario_score
        if thesis_sl and thesis_tp:
            sl = thesis_sl
            tp = thesis_tp

    result = SignalResult(
        signal=signal_type, symbol=SYMBOL, timeframe=TIMEFRAME,
        close=ind.close, entry_price=entry_price, sl=sl, tp=tp,
        score=setup.components_count if setup.detected else 0, reasons=[],
    )

    reasons = []
    if opportunity:
        reasons.append(f"Thesis score: {thesis_score:.0f}/100")
        reasons.append(f"Stability: {thesis_stability:.0%}")
        if opportunity.thesis and opportunity.thesis.components:
            reasons.append(f"Chain: {' → '.join(opportunity.thesis.components)}")
    result.reasons = reasons

    result._confidence_v2 = type('Obj', (object,), {
        'confidence_pct': 75.0, 'quality': 'moderate',
        'total_score': thesis_score, 'factors': reasons,
    })()

    msg = result.format_message()

    thesis_block = ["\n\n🧠 <b>Market Thesis Engine</b>"]
    if best and best.is_active:
        thesis_block.append(f"├ BUY prob: {thesis.buy_scenario.probability:.0%}")
        thesis_block.append(f"├ SELL prob: {thesis.sell_scenario.probability:.0%}")
        thesis_block.append(f"├ Stability: {thesis_stability:.0%}")
        thesis_block.append(f"├ Graph nodes: {len(liq_graph.nodes)}")
    thesis_block.append(f"└ Score: {thesis_score:.0f}/100")
    msg += "\n".join(thesis_block)

    bot = get_bot()
    channel_id = config.telegram.channel_id

    if not channel_id:
        logger.error("TELEGRAM_CHANNEL_ID not set!")
        print("\n=== MESSAGE (not sent) ===\n")
        print(msg)
        return

    logger.info(f"Sending to {channel_id}...")
    try:
        await bot.send_message(chat_id=channel_id, text=msg, parse_mode=ParseMode.HTML)
        logger.info("Sent!")
    except Exception as e:
        logger.error(f"Send failed: {e}")
        safe_msg = msg.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "")
        try:
            await bot.send_message(chat_id=channel_id, text=safe_msg)
            logger.info("Sent without HTML")
        except Exception as e2:
            logger.error(f"Retry failed: {e2}")

    await exchange_client.close()


if __name__ == "__main__":
    asyncio.run(run())
