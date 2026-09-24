"""
analytics/token_report.py — Token Deep Analysis Report.

Collects all data for a token and generates a comprehensive report
with indicators, levels, strategies, and observations.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional, List, Any

from loguru import logger


@dataclass
class TradeStrategy:
    """A trading strategy for a token."""
    type: str  # "long_retest" | "long_breakout" | "short_rejection" | "short_breakdown" | "wait"
    direction: str  # "LONG" | "SHORT" | "WAIT"
    entry: str
    stop_loss: str
    tp1: str
    tp2: str
    tp3: Optional[str] = None
    rr_ratio: str = ""
    reason: str = ""
    confidence: str = "MEDIUM"  # "HIGH" | "MEDIUM" | "LOW"


@dataclass
class IndicatorSnapshot:
    """Indicator values for a single timeframe."""
    rsi: float = 0.0
    rsi_signal: str = "Neutral"
    macd: float = 0.0
    macd_signal: str = "Neutral"
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    ema_signal: str = "Neutral"
    adx: float = 0.0
    adx_signal: str = "Neutral"
    supertrend: float = 0.0
    supertrend_direction: int = 0
    supertrend_signal: str = "Neutral"
    atr: float = 0.0
    volume: float = 0.0
    volume_signal: str = "Neutral"


@dataclass
class TokenReport:
    """Full analysis report for a token."""
    symbol: str
    price: float = 0.0
    market_cap: Optional[int] = None
    market_cap_rank: Optional[int] = None
    volume_24h: float = 0.0
    change_24h: float = 0.0
    change_7d: float = 0.0
    change_30d: float = 0.0

    # Indicators
    indicators_1h: Optional[IndicatorSnapshot] = None
    indicators_4h: Optional[IndicatorSnapshot] = None

    # Context
    fear_greed: Optional[int] = None
    fear_greed_label: Optional[str] = None
    funding_rate: Optional[float] = None
    long_short_ratio: Optional[float] = None
    open_interest: Optional[float] = None
    oi_delta: Optional[float] = None

    # Levels
    resistance_1h: List[float] = field(default_factory=list)
    support_1h: List[float] = field(default_factory=list)
    resistance_4h: List[float] = field(default_factory=list)
    support_4h: List[float] = field(default_factory=list)

    # Strategies
    strategies: List[TradeStrategy] = field(default_factory=list)

    # Observations
    observations: List[str] = field(default_factory=list)

    # Recommendation
    recommendation: str = "WAIT"
    recommendation_reason: str = ""


def _rsi_signal(rsi: float) -> str:
    if rsi >= 70:
        return "Overbought"
    elif rsi <= 30:
        return "Oversold"
    elif rsi >= 60:
        return "Bullish"
    elif rsi <= 40:
        return "Bearish"
    return "Neutral"


def _macd_signal(hist: float, hist_prev: float) -> str:
    if hist > 0 and hist > hist_prev:
        return "Growth"
    elif hist > 0:
        return "Falling"
    elif hist < 0 and hist < hist_prev:
        return "Decline"
    elif hist < 0:
        return "Recovery"
    return "Neutral"


def _ema_signal(fast: float, slow: float) -> str:
    if fast > slow * 1.02:
        return "Aligned Up"
    elif fast < slow * 0.98:
        return "Aligned Down"
    return "Neutral"


def _adx_signal(adx: float) -> str:
    if adx >= 25:
        return "Trend"
    elif adx >= 20:
        return "Weak Trend"
    return "Sideways"


def _supertrend_signal(direction: int) -> str:
    return "Bullish" if direction == 1 else "Bearish"


def _volume_signal(volume: float, volume_sma: float) -> str:
    if volume_sma == 0:
        return "Neutral"
    ratio = volume / volume_sma
    if ratio >= 1.5:
        return "High"
    elif ratio >= 1.0:
        return "Above Avg"
    elif ratio >= 0.7:
        return "Below Avg"
    return "Low"


def _indicators_from_engine(ind) -> IndicatorSnapshot:
    """Convert IndicatorValues from engine to IndicatorSnapshot."""
    return IndicatorSnapshot(
        rsi=round(ind.rsi, 1),
        rsi_signal=_rsi_signal(ind.rsi),
        macd=round(ind.macd_hist, 4),
        macd_signal=_macd_signal(ind.macd_hist, ind.macd_hist_prev),
        ema_fast=round(ind.ema_fast, 6),
        ema_slow=round(ind.ema_slow, 6),
        ema_signal=_ema_signal(ind.ema_fast, ind.ema_slow),
        adx=round(ind.adx, 1),
        adx_signal=_adx_signal(ind.adx),
        supertrend=round(ind.supertrend, 6),
        supertrend_direction=ind.supertrend_direction,
        supertrend_signal=_supertrend_signal(ind.supertrend_direction),
        atr=round(ind.atr, 6),
        volume=ind.volume,
        volume_signal=_volume_signal(ind.volume, ind.volume_sma),
    )


def _generate_strategies(report: TokenReport) -> List[TradeStrategy]:
    """Generate trading strategies based on indicators and levels."""
    strategies = []
    price = report.price
    if price <= 0:
        return strategies

    ind_1h = report.indicators_1h
    ind_4h = report.indicators_4h
    rsi = ind_1h.rsi if ind_1h else 50
    ls_ratio = report.long_short_ratio

    # Determine nearest support and resistance
    nearest_support = report.support_1h[0] if report.support_1h else None
    nearest_resistance = report.resistance_1h[0] if report.resistance_1h else None

    # Strategy 1: Short Rejection (if overbought near resistance)
    if rsi >= 60 and nearest_resistance and price >= nearest_resistance * 0.97:
        sl = nearest_resistance * 1.03
        tp1 = nearest_support if nearest_support else price * 0.90
        rr = (price - tp1) / (sl - price) if sl > price else 0
        reason_parts = [f"RSI {rsi}"]
        if ls_ratio and ls_ratio > 1.2:
            reason_parts.append(f"L/S {ls_ratio:.2f} (crowded longs)")
        if ind_1h and ind_1h.macd_signal in ("Decline", "Falling"):
            reason_parts.append("MACD fading")
        strategies.append(TradeStrategy(
            type="short_rejection",
            direction="SHORT",
            entry=f"${price:.4f} - ${nearest_resistance:.4f}",
            stop_loss=f"${sl:.4f}",
            tp1=f"${tp1:.4f}",
            tp2=f"${tp1 * 0.95:.4f}" if tp1 else "",
            rr_ratio=f"1:{rr:.1f}" if rr > 0 else "N/A",
            reason=", ".join(reason_parts),
            confidence="HIGH" if rsi >= 65 else "MEDIUM",
        ))

    # Strategy 2: Long Retest (if oversold near support)
    if rsi <= 40 and nearest_support and price <= nearest_support * 1.03:
        sl = nearest_support * 0.97
        tp1 = nearest_resistance if nearest_resistance else price * 1.10
        rr = (tp1 - price) / (price - sl) if price > sl else 0
        reason_parts = [f"RSI {rsi}"]
        if ind_1h and ind_1h.macd_signal in ("Recovery", "Growth"):
            reason_parts.append("MACD recovering")
        strategies.append(TradeStrategy(
            type="long_retest",
            direction="LONG",
            entry=f"${price:.4f} - ${nearest_support:.4f}",
            stop_loss=f"${sl:.4f}",
            tp1=f"${tp1:.4f}",
            tp2=f"${tp1 * 1.05:.4f}" if tp1 else "",
            rr_ratio=f"1:{rr:.1f}" if rr > 0 else "N/A",
            reason=", ".join(reason_parts),
            confidence="HIGH" if rsi <= 35 else "MEDIUM",
        ))

    # Strategy 3: Long Breakout (if price near resistance with momentum)
    if nearest_resistance and price >= nearest_resistance * 0.98 and price <= nearest_resistance * 1.02:
        sl = nearest_resistance * 0.97
        tp1 = price * 1.05
        tp2 = price * 1.10
        tp3 = price * 1.15
        rr = (tp1 - price) / (price - sl) if price > sl else 0
        strategies.append(TradeStrategy(
            type="long_breakout",
            direction="LONG",
            entry=f"Above ${nearest_resistance:.4f} (confirmation)",
            stop_loss=f"${sl:.4f}",
            tp1=f"${tp1:.4f}",
            tp2=f"${tp2:.4f}",
            tp3=f"${tp3:.4f}",
            rr_ratio=f"1:{rr:.1f}" if rr > 0 else "N/A",
            reason="Breakout above resistance with momentum",
            confidence="MEDIUM",
        ))

    # Strategy 4: Short Breakdown (if price near support with weakness)
    if nearest_support and price <= nearest_support * 1.02 and price >= nearest_support * 0.98:
        sl = nearest_support * 1.03
        tp1 = price * 0.95
        tp2 = price * 0.90
        rr = (price - tp1) / (sl - price) if sl > price else 0
        strategies.append(TradeStrategy(
            type="short_breakdown",
            direction="SHORT",
            entry=f"Below ${nearest_support:.4f} (confirmation)",
            stop_loss=f"${sl:.4f}",
            tp1=f"${tp1:.4f}",
            tp2=f"${tp2:.4f}",
            rr_ratio=f"1:{rr:.1f}" if rr > 0 else "N/A",
            reason="Breakdown below support with weakness",
            confidence="MEDIUM",
        ))

    # Strategy 5: Wait (if no clear signal)
    if not strategies:
        strategies.append(TradeStrategy(
            type="wait",
            direction="WAIT",
            entry="No entry",
            stop_loss="-",
            tp1="-",
            tp2="-",
            rr_ratio="-",
            reason=f"RSI {rsi} (neutral), no clear setup",
            confidence="LOW",
        ))

    return strategies


def _generate_observations(report: TokenReport) -> List[str]:
    """Generate key observations from the report data."""
    obs = []

    ind_1h = report.indicators_1h
    ind_4h = report.indicators_4h

    if ind_1h:
        if ind_1h.rsi >= 70:
            obs.append(f"RSI 1H {ind_1h.rsi} — overbought, возможен откат")
        elif ind_1h.rsi <= 30:
            obs.append(f"RSI 1H {ind_1h.rsi} — oversold, возможен bounce")
        elif ind_1h.rsi >= 60:
            obs.append(f"RSI 1H {ind_1h.rsi} — bullish zone")
        elif ind_1h.rsi <= 40:
            obs.append(f"RSI 1H {ind_1h.rsi} — bearish zone")

    if report.long_short_ratio:
        if report.long_short_ratio > 1.5:
            obs.append(f"L/S {report.long_short_ratio:.2f} — crowded longs, squeeze risk")
        elif report.long_short_ratio < 0.7:
            obs.append(f"L/S {report.long_short_ratio:.2f} — crowded shorts, reversal risk")

    if report.funding_rate:
        if report.funding_rate > 0.01:
            obs.append(f"Funding {report.funding_rate:.4f} — high, shorts pay longs")
        elif report.funding_rate < -0.01:
            obs.append(f"Funding {report.funding_rate:.4f} — negative, longs pay shorts")

    if report.fear_greed:
        if report.fear_greed >= 75:
            obs.append(f"F&G {report.fear_greed} (Greed) — caution, reversal zone")
        elif report.fear_greed <= 25:
            obs.append(f"F&G {report.fear_greed} (Fear) — contrarian buy zone")

    if ind_1h and ind_4h:
        if ind_1h.supertrend_direction == 1 and ind_4h.supertrend_direction == 1:
            obs.append("Supertrend bullish на 1H и 4H — бычий тренд")
        elif ind_1h.supertrend_direction == -1 and ind_4h.supertrend_direction == -1:
            obs.append("Supertrend bearish на 1H и 4H — медвежий тренд")
        else:
            obs.append("Supertrend конфликтует между TF — sideways")

    if report.change_7d and abs(report.change_7d) > 15:
        direction = "вырос" if report.change_7d > 0 else "упал"
        obs.append(f"За 7D {direction} {abs(report.change_7d):.1f}% — сильное движение")

    if not obs:
        obs.append("Нет явных сигналов — ожидание")

    return obs


def _determine_recommendation(report: TokenReport) -> tuple[str, str]:
    """Determine overall recommendation."""
    ind_1h = report.indicators_1h
    if not ind_1h:
        return "WAIT", "Недостаточно данных"

    score = 0
    reasons = []

    # RSI
    if ind_1h.rsi <= 35:
        score += 2
        reasons.append("RSI oversold")
    elif ind_1h.rsi >= 65:
        score -= 2
        reasons.append("RSI overbought")
    elif ind_1h.rsi <= 45:
        score += 1
    elif ind_1h.rsi >= 55:
        score -= 1

    # MACD
    if ind_1h.macd_signal in ("Growth", "Recovery"):
        score += 1
        reasons.append("MACD bullish")
    elif ind_1h.macd_signal in ("Decline", "Falling"):
        score -= 1
        reasons.append("MACD bearish")

    # Supertrend
    if ind_1h.supertrend_direction == 1:
        score += 1
    else:
        score -= 1

    # Long/Short
    if report.long_short_ratio:
        if report.long_short_ratio > 1.5:
            score -= 1
            reasons.append("crowded longs")
        elif report.long_short_ratio < 0.7:
            score += 1
            reasons.append("crowded shorts")

    # Fear & Greed
    if report.fear_greed:
        if report.fear_greed <= 25:
            score += 1
            reasons.append("extreme fear (contrarian)")
        elif report.fear_greed >= 75:
            score -= 1
            reasons.append("extreme greed")

    if score >= 3:
        return "LONG", ", ".join(reasons[:3])
    elif score <= -3:
        return "SHORT", ", ".join(reasons[:3])
    else:
        return "WAIT", ", ".join(reasons[:3]) if reasons else "Neutral signals"


async def generate_token_report(
    symbol: str,
    exchange_client=None,
    indicator_engine=None,
    context_fetcher=None,
) -> Optional[TokenReport]:
    """
    Generate a comprehensive analysis report for a token.

    Args:
        symbol: Trading pair (e.g. "BTC/USDT", "OP/USDT")
        exchange_client: ExchangeClient instance
        indicator_engine: IndicatorEngine instance
        context_fetcher: ContextFetcher instance

    Returns:
        TokenReport with all data filled, or None on error
    """
    try:
        from analytics.token_levels import calculate_levels, _find_swing_points_from_df
        from liquidity.order_blocks import detect_order_blocks
        from liquidity.fvg import detect_fvg

        report = TokenReport(symbol=symbol)

        # 1. Fetch OHLCV for both timeframes
        if exchange_client:
            df_1h = await exchange_client.fetch_ohlcv(symbol, "1h", limit=200)
            df_4h = await exchange_client.fetch_ohlcv(symbol, "4h", limit=200)

            if df_1h is None or df_4h is None:
                logger.warning(f"Failed to fetch OHLCV for {symbol}")
                return None

            # Current price
            report.price = float(df_1h["close"].iloc[-1])

            # 2. Calculate indicators
            if indicator_engine:
                ind_1h = indicator_engine.calculate(df_1h, symbol, "1h")
                ind_4h = indicator_engine.calculate(df_4h, symbol, "4h")

                if ind_1h:
                    report.indicators_1h = _indicators_from_engine(ind_1h)
                if ind_4h:
                    report.indicators_4h = _indicators_from_engine(ind_4h)

            # 3. Detect Order Blocks
            ob_1h = detect_order_blocks(df_1h, lookback=100)
            ob_4h = detect_order_blocks(df_4h, lookback=100)

            # 4. Detect FVGs
            fvgs_1h = detect_fvg(df_1h, lookback=100)
            fvgs_4h = detect_fvg(df_4h, lookback=100)

            # 5. Detect Swing Points
            swings_1h = _find_swing_points_from_df(df_1h)
            swings_4h = _find_swing_points_from_df(df_4h)

            # 6. Calculate S/R Levels
            levels = calculate_levels(
                df_1h=df_1h,
                df_4h=df_4h,
                indicators_1h=ind_1h if indicator_engine else None,
                indicators_4h=ind_4h if indicator_engine else None,
                order_blocks_1h=ob_1h,
                order_blocks_4h=ob_4h,
                fvgs_1h=fvgs_1h,
                fvgs_4h=fvgs_4h,
                swing_points_1h=swings_1h,
                swing_points_4h=swings_4h,
            )
            report.resistance_1h = levels.get("resistance_1h", [])
            report.support_1h = levels.get("support_1h", [])
            report.resistance_4h = levels.get("resistance_4h", [])
            report.support_4h = levels.get("support_4h", [])

        # 7. Fetch context data
        if context_fetcher:
            # Fear & Greed
            try:
                fng = await context_fetcher.fetch_fear_greed()
                if fng:
                    report.fear_greed = fng.get("value")
                    report.fear_greed_label = fng.get("label")
            except Exception as e:
                logger.debug(f"Failed to fetch F&G for {symbol}: {e}")

            # CoinGecko market data
            coin_id = symbol.split("/")[0].lower()
            try:
                cg = await context_fetcher.fetch_coingecko(coin_id)
                if cg:
                    report.change_24h = cg.get("price_change_24h") or 0
                    report.change_7d = cg.get("price_change_7d") or 0
                    report.volume_24h = cg.get("total_volume") or 0
                    report.market_cap_rank = cg.get("market_cap_rank")
            except Exception as e:
                logger.debug(f"Failed to fetch CoinGecko for {symbol}: {e}")

            # Funding rate
            try:
                fr = await context_fetcher.fetch_funding_rate(symbol)
                if fr is not None:
                    report.funding_rate = fr
            except Exception as e:
                logger.debug(f"Failed to fetch funding for {symbol}: {e}")

            # Long/Short ratio
            try:
                ls = await context_fetcher.fetch_long_short_ratio(symbol)
                if ls is not None:
                    report.long_short_ratio = ls
            except Exception as e:
                logger.debug(f"Failed to fetch L/S for {symbol}: {e}")

            # Open Interest
            try:
                oi = await context_fetcher.fetch_open_interest(symbol)
                if oi:
                    report.open_interest = oi.get("open_interest")
                    report.oi_delta = oi.get("open_interest_delta")
            except Exception as e:
                logger.debug(f"Failed to fetch OI for {symbol}: {e}")

        # 8. Generate strategies
        report.strategies = _generate_strategies(report)

        # 9. Generate observations
        report.observations = _generate_observations(report)

        # 10. Determine recommendation
        report.recommendation, report.recommendation_reason = _determine_recommendation(report)

        return report

    except Exception as e:
        logger.error(f"Error generating report for {symbol}: {e}")
        return None
