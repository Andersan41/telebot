"""
test_xlm_signal.py — Test signal for XLM with new Market Thesis Engine SL/TP.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import config
from data.exchange_client import exchange_client
from indicators.engine import indicator_engine
from strategy.pattern_engine import pattern_engine
from strategy.feature_builder import feature_builder
from strategy.probability_engine import probability_engine
from risk.engine import risk_engine, PortfolioState
from strategy.signal_engine import SignalResult, SignalType
from strategy.trade_engine import trade_engine
from strategy.market_thesis_engine import market_thesis_engine, DynamicTradeThesis
from liquidity.sweep import detect_sweeps
from liquidity.order_blocks import detect_order_blocks
from liquidity.fvg import detect_fvg
from liquidity.equal_levels import detect_equal_levels
from liquidity.external import detect_external_liquidity
from liquidity.candle_quality import analyze_last_candle
from market_structure.structure import analyze_structure
from bot.notifier import get_bot, send_signal
from telegram.constants import ParseMode
from loguru import logger
import html


SYMBOL = "XLM/USDT"
TIMEFRAME = "1h"


async def run():
    logger.info(f"Connecting to exchange...")
    await exchange_client.connect()

    logger.info(f"Fetching {SYMBOL} {TIMEFRAME}...")

    # 1. Fetch OHLCV
    df = await exchange_client.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=config.trading.candles_limit)
    if df is None or len(df) < 10:
        logger.error("Not enough data")
        return

    # 2. Indicators
    ind = indicator_engine.calculate(df, SYMBOL, TIMEFRAME)
    if ind is None:
        logger.error("Indicator calc failed")
        return

    logger.info(f"Close: {ind.close} | ATR: {ind.atr}")

    # 3. Pattern detection
    _df_clean = df.dropna(subset=["open", "high", "low", "close", "volume"])
    sweeps = detect_sweeps(_df_clean, lookback=50)
    order_blocks = detect_order_blocks(_df_clean, lookback=100)
    structure = analyze_structure(_df_clean, lookback=50)
    fvgs = detect_fvg(_df_clean, lookback=getattr(config, "liquidity_fvg_lookback", 100))
    candle_quality = analyze_last_candle(_df_clean, atr_value=ind.atr)

    logger.info(f"Sweeps: {len(sweeps)} | OBs: {len(order_blocks)} | FVGs: {len(fvgs)}")
    logger.info(f"Structure trend: {getattr(structure, 'trend', 'N/A')}")

    # 4. Pattern Engine
    setup = pattern_engine.detect(
        sweeps=sweeps, order_blocks=order_blocks, structure=structure,
        fvgs=fvgs, candle_quality=candle_quality, current_price=ind.close,
    )

    logger.info(f"Setup detected: {setup.detected} | direction: {setup.direction}")

    if not setup.detected:
        logger.warning("No setup detected — running analysis anyway for thesis demo")

    # 5. Trade Engine (legacy SL/TP)
    trade_plan = trade_engine.build_trade_plan(
        ind=ind, direction=setup.direction if setup.detected else "buy",
        structure=structure, order_blocks=order_blocks, sweeps=sweeps,
        fvgs=fvgs, df=_df_clean, timeframe=TIMEFRAME,
    )

    entry_price = ind.close
    logger.info(f"Legacy SL: {trade_plan.sl} | TP: {trade_plan.tp}")

    # 6. Market Thesis Engine (NEW — dynamic graph)
    _swing_highs = getattr(structure, "swing_points", []) or []
    _swing_lows = getattr(structure, "swing_points", []) or []
    _equal_levels = detect_equal_levels(_swing_highs, _swing_lows)
    _external_levels = detect_external_liquidity(_df_clean, lookback=200)

    liq_graph = market_thesis_engine.build_liquidity_graph(
        current_price=entry_price,
        sweeps=sweeps,
        order_blocks=order_blocks,
        fvgs=fvgs,
        structure=structure,
        equal_levels=_equal_levels,
        external_levels=_external_levels,
        candle_quality=candle_quality,
        timeframe=TIMEFRAME,
    )

    logger.info(f"Liquidity graph: {len(liq_graph.nodes)} nodes")

    # Build DynamicTradeThesis and update
    thesis = DynamicTradeThesis(symbol=SYMBOL, timeframe=TIMEFRAME)
    last_row = _df_clean.iloc[-1]
    candle_data = {
        "open": float(last_row["open"]),
        "high": float(last_row["high"]),
        "low": float(last_row["low"]),
        "close": float(last_row["close"]),
        "volume": float(last_row["volume"]),
    }
    thesis.update(liq_graph, entry_price, candle_data, atr=ind.atr if ind.atr else 0)

    # Get best scenario
    best = thesis.best_scenario
    if best and best.is_active:
        logger.info(
            f"Dynamic Thesis: BUY={thesis.buy_scenario.probability:.2f} "
            f"SELL={thesis.sell_scenario.probability:.2f} | "
            f"ambiguous={thesis.is_ambiguous} | stability={thesis.scenario_stability:.2f}"
        )
    else:
        logger.warning("No active scenario in DynamicTradeThesis")

    # Evaluate trade opportunity (backward-compatible)
    opportunity = market_thesis_engine.evaluate_trade_opportunity(
        graph=liq_graph,
        direction=setup.direction if setup.detected else "buy",
        entry_price=entry_price,
        atr=ind.atr if ind.atr else 0,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
    )

    # Evaluate all ranked scenarios
    scenarios = market_thesis_engine.evaluate_scenarios(
        graph=liq_graph,
        direction=setup.direction if setup.detected else "buy",
        entry_price=entry_price,
        atr=ind.atr if ind.atr else 0,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
    )

    if scenarios:
        logger.info("Ranked scenarios:")
        for s in scenarios[:3]:
            bd = s.score_breakdown.breakdown() if s.score_breakdown else {}
            logger.info(
                f"  #{s.alternative_rank + 1} score={s.score:.1f} "
                f"conf={s.confidence:.0f} rr=1:{s.expected_rr:.1f} "
                f"OB={bd.get('ob', 0):.1f} Sweep={bd.get('sweep', 0):.1f} "
                f"BOS={bd.get('bos', 0):.1f} FVG={bd.get('fvg', 0):.1f}"
            )

    # 7. Build signal with thesis-based SL/TP
    direction = setup.direction if setup.detected else "buy"
    signal_type = SignalType.BUY if direction == "buy" else SignalType.SELL

    # Use thesis-based SL/TP if available, otherwise fallback to legacy
    sl = trade_plan.sl
    tp = trade_plan.tp
    thesis_score = 0.0
    thesis_stability = thesis.scenario_stability

    if opportunity:
        # Thesis-based invalidation = SL, target = TP
        thesis_sl = opportunity.invalidation
        thesis_tp = opportunity.expected_target
        thesis_score = opportunity.scenario_score

        if thesis_sl and thesis_tp:
            sl = thesis_sl
            tp = thesis_tp
            logger.info(
                f"Using THESIS SL/TP: SL={sl:.6f} TP={tp:.6f} "
                f"(score={thesis_score:.0f}, stability={thesis_stability:.2f})"
            )
        else:
            logger.info("Thesis incomplete — using legacy SL/TP")
    else:
        logger.info("No thesis opportunity — using legacy SL/TP")

    # 8. Build SignalResult
    result = SignalResult(
        signal=signal_type,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        close=ind.close,
        entry_price=entry_price,
        sl=sl,
        tp=tp,
        score=setup.components_count if setup.detected else 0,
        reasons=[],
    )

    # Add thesis info to reasons
    reasons = []
    if opportunity:
        reasons.append(f"Thesis score: {thesis_score:.0f}/100")
        reasons.append(f"Stability: {thesis_stability:.0%}")
        if opportunity.thesis and opportunity.thesis.components:
            reasons.append(f"Chain: {' → '.join(opportunity.thesis.components)}")
        if opportunity.thesis and opportunity.thesis.score_breakdown:
            bd = opportunity.thesis.score_breakdown.breakdown()
            reasons.append(
                f"Breakdown: OB={bd['ob']:.0f} Sweep={bd['sweep']:.0f} "
                f"BOS={bd['bos']:.0f} FVG={bd['fvg']:.0f} "
                f"Liq={bd['liquidity']:.0f} HTF={bd['htf']:.0f}"
            )
    result.reasons = reasons

    # Attach confidence data
    result._confidence_v2 = type('Obj', (object,), {
        'confidence_pct': 75.0,
        'quality': 'moderate',
        'total_score': thesis_score,
        'factors': reasons,
    })()

    # 9. Format message
    msg = result.format_message()

    # Add thesis section
    thesis_block = []
    thesis_block.append("\n\n🧠 <b>Market Thesis Engine (DAG)</b>")
    if best and best.is_active:
        thesis_block.append(f"├ BUY prob: {thesis.buy_scenario.probability:.0%}")
        thesis_block.append(f"├ SELL prob: {thesis.sell_scenario.probability:.0%}")
        thesis_block.append(f"├ Ambiguous: {'yes' if thesis.is_ambiguous else 'no'}")
        thesis_block.append(f"├ Stability: {thesis_stability:.0%}")
        thesis_block.append(f"├ Graph nodes: {len(liq_graph.nodes)}")
        thesis_block.append(f"├ Graph version: {liq_graph.graph_version}")
    if scenarios:
        thesis_block.append(f"├ Ranked scenarios: {len(scenarios)}")
        for s in scenarios[:3]:
            thesis_block.append(f"│  #{s.alternative_rank + 1} score={s.score:.0f} rr=1:{s.expected_rr:.1f}")
    thesis_block.append(f"└ Score: {thesis_score:.0f}/100")

    msg += "\n".join(thesis_block)

    # 10. Send to Telegram
    bot = get_bot()
    channel_id = config.telegram.channel_id

    if not channel_id:
        logger.error("TELEGRAM_CHANNEL_ID not set!")
        print("\n=== SIGNAL MESSAGE (not sent — no channel_id) ===\n")
        print(msg)
        return

    logger.info(f"Sending to channel {channel_id}...")
    try:
        await bot.send_message(
            chat_id=channel_id,
            text=msg,
            parse_mode=ParseMode.HTML,
        )
        logger.info("Signal sent successfully!")
    except Exception as e:
        logger.error(f"Send failed: {e}")
        # Try without parse_mode
        try:
            safe_msg = msg.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "")
            await bot.send_message(chat_id=channel_id, text=safe_msg)
            logger.info("Sent without HTML formatting")
        except Exception as e2:
            logger.error(f"Retry also failed: {e2}")

    await exchange_client.close()


if __name__ == "__main__":
    asyncio.run(run())
