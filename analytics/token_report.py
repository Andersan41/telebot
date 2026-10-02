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
    # Numeric values for the web dashboard (status, % distances, calculator)
    entry_price: Optional[float] = None
    sl_price: Optional[float] = None
    tp1_price: Optional[float] = None
    tp2_price: Optional[float] = None
    tp3_price: Optional[float] = None
    rr1: Optional[float] = None  # R:R to TP1
    rr2: Optional[float] = None  # R:R to TP2


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
    volume_24h: Optional[float] = None
    change_24h: Optional[float] = None
    change_7d: Optional[float] = None
    change_30d: Optional[float] = None

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
    recommendation_votes: dict = field(default_factory=dict)  # {"bull": n, "bear": n, "neutral": n}


def _fmt_px(v: float) -> str:
    """Format a price with symbol-appropriate precision (no 4-decimal noise)."""
    if v <= 0:
        return "-"
    if v < 0.001:
        return f"${v:.8f}"
    if v < 0.10:
        return f"${v:.6f}"
    if v < 1.0:
        return f"${v:.4f}"
    if v < 100:
        return f"${v:.2f}"
    if v < 1000:
        return f"${v:,.1f}"
    return f"${v:,.0f}"


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
        entry = nearest_resistance
        sl = entry * 1.03
        tp1 = nearest_support if nearest_support else price * 0.90
        tp2 = tp1 * 0.95
        risk = sl - entry
        rr1 = (entry - tp1) / risk if risk > 0 else 0
        rr2 = (entry - tp2) / risk if risk > 0 else 0
        reason_parts = [f"RSI {rsi}"]
        if ls_ratio and ls_ratio > 1.2:
            reason_parts.append(f"L/S {ls_ratio:.2f} (crowded longs)")
        if ind_1h and ind_1h.macd_signal in ("Decline", "Falling"):
            reason_parts.append("MACD fading")
        strategies.append(TradeStrategy(
            type="short_rejection",
            direction="SHORT",
            entry=f"{_fmt_px(price)} - {_fmt_px(entry)}",
            stop_loss=_fmt_px(sl),
            tp1=_fmt_px(tp1),
            tp2=_fmt_px(tp2),
            rr_ratio=f"1:{rr1:.1f}" if rr1 > 0 else "N/A",
            reason=", ".join(reason_parts),
            confidence="HIGH" if rsi >= 65 else "MEDIUM",
            entry_price=entry,
            sl_price=sl,
            tp1_price=tp1,
            tp2_price=tp2,
            rr1=round(rr1, 2) if rr1 > 0 else None,
            rr2=round(rr2, 2) if rr2 > 0 else None,
        ))

    # Strategy 2: Long Retest (if oversold near support)
    if rsi <= 40 and nearest_support and price <= nearest_support * 1.03:
        entry = nearest_support
        sl = entry * 0.97
        tp1 = nearest_resistance if nearest_resistance else price * 1.10
        tp2 = tp1 * 1.05
        risk = entry - sl
        rr1 = (tp1 - entry) / risk if risk > 0 else 0
        rr2 = (tp2 - entry) / risk if risk > 0 else 0
        reason_parts = [f"RSI {rsi}"]
        if ind_1h and ind_1h.macd_signal in ("Recovery", "Growth"):
            reason_parts.append("MACD recovering")
        strategies.append(TradeStrategy(
            type="long_retest",
            direction="LONG",
            entry=f"{_fmt_px(price)} - {_fmt_px(entry)}",
            stop_loss=_fmt_px(sl),
            tp1=_fmt_px(tp1),
            tp2=_fmt_px(tp2),
            rr_ratio=f"1:{rr1:.1f}" if rr1 > 0 else "N/A",
            reason=", ".join(reason_parts),
            confidence="HIGH" if rsi <= 35 else "MEDIUM",
            entry_price=entry,
            sl_price=sl,
            tp1_price=tp1,
            tp2_price=tp2,
            rr1=round(rr1, 2) if rr1 > 0 else None,
            rr2=round(rr2, 2) if rr2 > 0 else None,
        ))

    # Strategy 3: Long Breakout (if price near resistance with momentum)
    if nearest_resistance and price >= nearest_resistance * 0.98 and price <= nearest_resistance * 1.02:
        entry = nearest_resistance
        sl = entry * 0.97
        tp1 = price * 1.05
        tp2 = price * 1.10
        tp3 = price * 1.15
        risk = entry - sl
        rr1 = (tp1 - entry) / risk if risk > 0 else 0
        rr2 = (tp2 - entry) / risk if risk > 0 else 0
        strategies.append(TradeStrategy(
            type="long_breakout",
            direction="LONG",
            entry=f"Пробой выше {_fmt_px(entry)} (подтверждение)",
            stop_loss=_fmt_px(sl),
            tp1=_fmt_px(tp1),
            tp2=_fmt_px(tp2),
            tp3=_fmt_px(tp3),
            rr_ratio=f"1:{rr1:.1f}" if rr1 > 0 else "N/A",
            reason="Breakout above resistance with momentum",
            confidence="MEDIUM",
            entry_price=entry,
            sl_price=sl,
            tp1_price=tp1,
            tp2_price=tp2,
            tp3_price=tp3,
            rr1=round(rr1, 2) if rr1 > 0 else None,
            rr2=round(rr2, 2) if rr2 > 0 else None,
        ))

    # Strategy 4: Short Breakdown (if price near support with weakness)
    if nearest_support and price <= nearest_support * 1.02 and price >= nearest_support * 0.98:
        entry = nearest_support
        sl = entry * 1.03
        tp1 = price * 0.95
        tp2 = price * 0.90
        risk = sl - entry
        rr1 = (entry - tp1) / risk if risk > 0 else 0
        rr2 = (entry - tp2) / risk if risk > 0 else 0
        strategies.append(TradeStrategy(
            type="short_breakdown",
            direction="SHORT",
            entry=f"Пробой ниже {_fmt_px(entry)} (подтверждение)",
            stop_loss=_fmt_px(sl),
            tp1=_fmt_px(tp1),
            tp2=_fmt_px(tp2),
            rr_ratio=f"1:{rr1:.1f}" if rr1 > 0 else "N/A",
            reason="Breakdown below support with weakness",
            confidence="MEDIUM",
            entry_price=entry,
            sl_price=sl,
            tp1_price=tp1,
            tp2_price=tp2,
            rr1=round(rr1, 2) if rr1 > 0 else None,
            rr2=round(rr2, 2) if rr2 > 0 else None,
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
    """Generate key observations from the report data.

    Each item is prefixed with an icon: ✅ argument FOR (long),
    ⚠️ argument AGAINST, ℹ️ neutral note.
    """
    obs = []

    ind_1h = report.indicators_1h
    ind_4h = report.indicators_4h

    if ind_1h:
        if ind_1h.rsi >= 70:
            obs.append(f"⚠️ RSI 1H {ind_1h.rsi} — перекуплен, возможен откат")
        elif ind_1h.rsi <= 30:
            obs.append(f"✅ RSI 1H {ind_1h.rsi} — перепродан, возможен отскок")
        elif ind_1h.rsi >= 60:
            obs.append(f"✅ RSI 1H {ind_1h.rsi} — бычья зона")
        elif ind_1h.rsi <= 40:
            obs.append(f"⚠️ RSI 1H {ind_1h.rsi} — медвежья зона")

    if report.long_short_ratio:
        if report.long_short_ratio > 1.5:
            obs.append(f"⚠️ L/S {report.long_short_ratio:.2f} — перекошен в лонги, риск шорт-сквиза")
        elif report.long_short_ratio < 0.7:
            obs.append(f"✅ L/S {report.long_short_ratio:.2f} — перекошен в шорты, риск реверса")

    if report.funding_rate:
        if report.funding_rate > 0.01:
            obs.append(f"⚠️ Funding {report.funding_rate:.4f} — высокий, лонги переплачивают")
        elif report.funding_rate < -0.01:
            obs.append(f"✅ Funding {report.funding_rate:.4f} — отрицательный, шорты переплачивают")

    if report.fear_greed:
        if report.fear_greed >= 70:
            obs.append(f"⚠️ F&G {report.fear_greed} ({report.fear_greed_label}) — перегрев, осторожность к лонгам")
        elif report.fear_greed <= 25:
            obs.append(f"✅ F&G {report.fear_greed} ({report.fear_greed_label}) — страх, контртрендовая зона покупки")

    if ind_1h and ind_4h:
        if ind_1h.supertrend_direction == 1 and ind_4h.supertrend_direction == 1:
            obs.append("✅ Supertrend бычий на 1H и 4H — тренд согласован")
        elif ind_1h.supertrend_direction == -1 and ind_4h.supertrend_direction == -1:
            obs.append("⚠️ Supertrend медвежий на 1H и 4H — тренд согласован вниз")
        else:
            obs.append("ℹ️ Supertrend конфликтует между TF — sideways, вход без подтверждения рискован")

    if report.change_7d and abs(report.change_7d) > 15:
        direction = "вырос" if report.change_7d > 0 else "упал"
        obs.append(f"ℹ️ За 7D {direction} {abs(report.change_7d):.1f}% — сильное движение, возможна коррекция")

    if not obs:
        obs.append("ℹ️ Нет явных сигналов — ожидание")

    return obs


def _factor_votes(report: TokenReport) -> List[tuple]:
    """Collect per-factor votes for/against a long setup.

    Returns list of (label, vote, weight) where vote is +1 (bull),
    -1 (bear) or 0 (neutral). Weight: RSI counts double.
    """
    factors: List[tuple] = []

    for tf, ind in (("1H", report.indicators_1h), ("4H", report.indicators_4h)):
        if not ind:
            continue

        # RSI (weight 2)
        if ind.rsi <= 35:
            factors.append((f"RSI {tf} перепродан", 1, 2))
        elif ind.rsi >= 65:
            factors.append((f"RSI {tf} перекуплен", -1, 2))
        elif ind.rsi <= 45:
            factors.append((f"RSI {tf} ниже 45", 1, 2))
        elif ind.rsi >= 55:
            factors.append((f"RSI {tf} выше 55", -1, 2))
        else:
            factors.append((f"RSI {tf} нейтрален", 0, 2))

        # MACD
        if ind.macd_signal in ("Growth", "Recovery"):
            factors.append((f"MACD {tf} растёт", 1, 1))
        elif ind.macd_signal in ("Decline", "Falling"):
            factors.append((f"MACD {tf} падает", -1, 1))
        else:
            factors.append((f"MACD {tf} нейтрален", 0, 1))

        # EMA alignment
        if ind.ema_signal == "Aligned Up":
            factors.append((f"EMA {tf} бычий срез", 1, 1))
        elif ind.ema_signal == "Aligned Down":
            factors.append((f"EMA {tf} медвежий срез", -1, 1))
        else:
            factors.append((f"EMA {tf} нейтрально", 0, 1))

        # Supertrend direction
        if ind.supertrend_direction == 1:
            factors.append((f"Supertrend {tf} бычий", 1, 1))
        elif ind.supertrend_direction == -1:
            factors.append((f"Supertrend {tf} медвежий", -1, 1))
        else:
            factors.append((f"Supertrend {tf} нет данных", 0, 1))

    # Context factors
    if report.long_short_ratio:
        if report.long_short_ratio > 1.5:
            factors.append(("перекос L/S в лонги", -1, 1))
        elif report.long_short_ratio < 0.7:
            factors.append(("перекос L/S в шорты", 1, 1))

    if report.fear_greed:
        if report.fear_greed <= 25:
            factors.append(("страх на рынке (контртенд)", 1, 1))
        elif report.fear_greed >= 70:
            factors.append(("жадность на рынке (перегрев)", -1, 1))

    return factors


def _entry_wait_phrase(strategy: TradeStrategy) -> str:
    """One-line 'what are we waiting for' phrase for a strategy."""
    if not strategy.entry_price:
        return ""
    px = _fmt_px(strategy.entry_price)
    return {
        "long_breakout": f"ждём пробоя {px}",
        "short_breakdown": f"ждём пробоя ниже {px}",
        "long_retest": f"ждём возврата к {px}",
        "short_rejection": f"ждём реакции у {px}",
    }.get(strategy.type, f"ждём входа у {px}")


def _determine_recommendation(report: TokenReport) -> tuple:
    """Determine overall recommendation.

    Returns (recommendation, reason, votes) where votes is a dict
    {"bull": n, "bear": n, "neutral": n, "total": n}.
    """
    factors = _factor_votes(report)
    if not report.indicators_1h and not report.indicators_4h:
        return "WAIT", "Недостаточно данных", {"bull": 0, "bear": 0, "neutral": 0, "total": 0}

    score = sum(vote * weight for _, vote, weight in factors)
    bull_labels = [label for label, vote, _ in factors if vote > 0]
    bear_labels = [label for label, vote, _ in factors if vote < 0]
    bulls = len(bull_labels)
    bears = len(bear_labels)
    neutral = len(factors) - bulls - bears
    votes = {"bull": bulls, "bear": bears, "neutral": neutral, "total": len(factors)}

    # 1H vs 4H Supertrend conflict
    conflict = (
        report.indicators_1h
        and report.indicators_4h
        and report.indicators_1h.supertrend_direction != report.indicators_4h.supertrend_direction
    )

    if score >= 4 and bulls > bears:
        recommendation = "LONG"
        base = ", ".join(bull_labels[:2])
    elif score <= -4 and bears > bulls:
        recommendation = "SHORT"
        base = ", ".join(bear_labels[:2])
    else:
        recommendation = "WAIT"
        if conflict:
            base = "Тренды 1H и 4H расходятся"
        elif neutral >= bulls and neutral >= bears:
            base = f"Нейтральных сигналов больше ({neutral} из {len(factors)})"
        elif bulls > bears:
            base = f"Лёгкий перевес быков ({bulls}:{bears}), порог не набран"
        else:
            base = f"Лёгкий перевес медведей ({bears}:{bulls}), порог не набран"

    # Link the reason to the active strategy, if any
    active = next((s for s in report.strategies if s.type != "wait"), None)
    if active:
        wait_phrase = _entry_wait_phrase(active)
        if recommendation == "WAIT" or active.direction == recommendation:
            if wait_phrase:
                base = f"{base}, {wait_phrase}" if base else wait_phrase
        else:
            base = f"{base}, сетап {active.direction} против вердикта — без входа"

    if not base:
        base = "Neutral signals"

    return recommendation, base, votes


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

            # CoinGecko market data (missing values stay None — UI shows "нет данных")
            coin_id = symbol.split("/")[0].lower()
            try:
                cg = await context_fetcher.fetch_coingecko(coin_id)
                if cg:
                    report.change_24h = cg.get("price_change_24h")
                    report.change_7d = cg.get("price_change_7d")
                    report.change_30d = cg.get("price_change_30d")
                    report.volume_24h = cg.get("total_volume")
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
        (
            report.recommendation,
            report.recommendation_reason,
            report.recommendation_votes,
        ) = _determine_recommendation(report)

        return report

    except Exception as e:
        logger.error(f"Error generating report for {symbol}: {e}")
        return None
