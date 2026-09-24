"""
analytics/token_formatter.py — HTML Formatting for Token Reports.

Formats TokenReport into HTML for Telegram and plain text for web dashboard.
"""
from __future__ import annotations

import html
from typing import Optional

from analytics.token_report import TokenReport, IndicatorSnapshot, TradeStrategy


def _fmt_price(price: float) -> str:
    """Format price with appropriate precision."""
    if price <= 0:
        return "-"
    if price < 0.001:
        return f"${price:.8f}"
    elif price < 0.10:
        return f"${price:.6f}"
    elif price < 1.0:
        return f"${price:.4f}"
    elif price < 100:
        return f"${price:.4f}"
    else:
        return f"${price:,.2f}"


def _fmt_volume(vol: float) -> str:
    """Format volume with K/M/B suffix."""
    if vol >= 1_000_000_000:
        return f"${vol / 1_000_000_000:.1f}B"
    elif vol >= 1_000_000:
        return f"${vol / 1_000_000:.1f}M"
    elif vol >= 1_000:
        return f"${vol / 1_000:.1f}K"
    return f"${vol:.0f}"


def _fmt_change(change: Optional[float]) -> str:
    """Format percentage change with sign and emoji."""
    if change is None:
        return "N/A"
    sign = "+" if change >= 0 else ""
    emoji = "📈" if change >= 0 else "📉"
    return f"{sign}{change:.1f}% {emoji}"


def _rsi_emoji(rsi: float) -> str:
    if rsi >= 70:
        return "🔴"
    elif rsi <= 30:
        return "🟢"
    elif rsi >= 60:
        return "🟡"
    elif rsi <= 40:
        return "🟠"
    return "⚪"


def _signal_emoji(signal: str) -> str:
    if signal in ("Growth", "Aligned Up", "Bullish", "Trend", "High", "Above Avg"):
        return "✅"
    elif signal in ("Decline", "Aligned Down", "Bearish", "Low", "Below Avg"):
        return "❌"
    return "➖"


def _supertrend_emoji(direction: int) -> str:
    return "🟢" if direction == 1 else "🔴"


def _strategy_emoji(direction: str) -> str:
    if direction == "LONG":
        return "🟢"
    elif direction == "SHORT":
        return "🔴"
    return "⏸️"


def _funding_emoji(rate: Optional[float]) -> str:
    if rate is None:
        return "➖"
    if rate > 0.01:
        return "⚠️"
    elif rate < -0.01:
        return "✅"
    return "➖"


def _ls_emoji(ratio: Optional[float]) -> str:
    if ratio is None:
        return "➖"
    if ratio > 1.5:
        return "⚠️"
    elif ratio < 0.7:
        return "✅"
    return "➖"


def _fng_emoji(value: Optional[int]) -> str:
    if value is None:
        return "➖"
    if value >= 75:
        return "⚠️"
    elif value <= 25:
        return "🟢"
    return "➖"


def format_indicator_line(name: str, value: str, signal: str, signal_emoji: str) -> str:
    """Format a single indicator line in compact format."""
    return f"├ {name}: <b>{value}</b> {signal} {signal_emoji}"


def _signal_arrow(signal: str) -> str:
    """Get arrow for signal trend."""
    if signal in ("Growth", "Aligned Up", "Bullish", "Trend", "High", "Above Avg"):
        return "↗"
    elif signal in ("Decline", "Aligned Down", "Bearish", "Low", "Below Avg"):
        return "↘"
    return "⟶"


def _supertrend_signal_emoji(direction: int) -> str:
    """Get emoji for supertrend signal."""
    return "✅" if direction == 1 else "❌"


def format_indicators_table(ind_1h: Optional[IndicatorSnapshot], ind_4h: Optional[IndicatorSnapshot]) -> str:
    """
    Format indicators in table format combining both timeframes.

    Example:
    ┌────────┬────────┬────────┬────────┐
    │  1H    │ Signal │  4H    │ Signal │
    ├────────┼────────┼────────┼────────┤
    │ RSI    │ 47.4 ⟶ │ RSI    │ 55.2 ↗ │
    │ MACD   │ -0.00 ↘ │ MACD   │ +0.12 ↗ │
    │ EMA    │ ↑ ✅    │ EMA    │ ↑ ✅    │
    │ ADX    │ 15.6 ⟶ │ ADX    │ 22.1 ↗ │
    │ ST     │ ✅      │ ST     │ ✅      │
    │ Volume │ 📉      │ Volume │ 📈      │
    └────────┴────────┴────────┴────────┘
    """
    if not ind_1h and not ind_4h:
        return ""

    # Helper to get value or dash
    def v(ind, attr, fmt="{:.1f}"):
        if not ind:
            return "—"
        val = getattr(ind, attr, None)
        if val is None:
            return "—"
        if isinstance(val, float):
            return fmt.format(val)
        return str(val)

    def s(ind, attr):
        if not ind:
            return "—"
        return getattr(ind, attr, "—") or "—"

    # Build rows
    rows = []

    # RSI
    rsi_1h = v(ind_1h, "rsi") if ind_1h else "—"
    rsi_4h = v(ind_4h, "rsi") if ind_4h else "—"
    rsi_s1h = _signal_arrow(s(ind_1h, "rsi_signal")) if ind_1h else "—"
    rsi_s4h = _signal_arrow(s(ind_4h, "rsi_signal")) if ind_4h else "—"
    rows.append(f"│ RSI    │ {rsi_1h} {rsi_s1h} │ RSI    │ {rsi_4h} {rsi_s4h} │")

    # MACD
    macd_1h = v(ind_1h, "macd", "{:.2f}") if ind_1h else "—"
    macd_4h = v(ind_4h, "macd", "{:.2f}") if ind_4h else "—"
    macd_s1h = _signal_arrow(s(ind_1h, "macd_signal")) if ind_1h else "—"
    macd_s4h = _signal_arrow(s(ind_4h, "macd_signal")) if ind_4h else "—"
    rows.append(f"│ MACD   │ {macd_1h} {macd_s1h} │ MACD   │ {macd_4h} {macd_s4h} │")

    # EMA
    ema_s1h = "↑" if ind_1h and s(ind_1h, "ema_signal") == "Aligned Up" else "↓" if ind_1h and s(ind_1h, "ema_signal") == "Aligned Down" else "—"
    ema_s4h = "↑" if ind_4h and s(ind_4h, "ema_signal") == "Aligned Up" else "↓" if ind_4h and s(ind_4h, "ema_signal") == "Aligned Down" else "—"
    ema_e1h = _signal_emoji(s(ind_1h, "ema_signal")) if ind_1h else "—"
    ema_e4h = _signal_emoji(s(ind_4h, "ema_signal")) if ind_4h else "—"
    rows.append(f"│ EMA    │ {ema_s1h} {ema_e1h}    │ EMA    │ {ema_s4h} {ema_e4h}    │")

    # ADX
    adx_1h = v(ind_1h, "adx") if ind_1h else "—"
    adx_4h = v(ind_4h, "adx") if ind_4h else "—"
    adx_s1h = _signal_arrow(s(ind_1h, "adx_signal")) if ind_1h else "—"
    adx_s4h = _signal_arrow(s(ind_4h, "adx_signal")) if ind_4h else "—"
    rows.append(f"│ ADX    │ {adx_1h} {adx_s1h} │ ADX    │ {adx_4h} {adx_s4h} │")

    # Supertrend
    st_1h = _supertrend_signal_emoji(ind_1h.supertrend_direction) if ind_1h else "—"
    st_4h = _supertrend_signal_emoji(ind_4h.supertrend_direction) if ind_4h else "—"
    rows.append(f"│ ST     │ {st_1h}      │ ST     │ {st_4h}      │")

    # Volume
    vol_1h = "📈" if ind_1h and s(ind_1h, "volume_signal") in ("High", "Above Avg") else "📉" if ind_1h and s(ind_1h, "volume_signal") in ("Low", "Below Avg") else "—"
    vol_4h = "📈" if ind_4h and s(ind_4h, "volume_signal") in ("High", "Above Avg") else "📉" if ind_4h and s(ind_4h, "volume_signal") in ("Low", "Below Avg") else "—"
    rows.append(f"│ Volume │ {vol_1h}      │ Volume │ {vol_4h}      │")

    # Build table
    table = [
        "┌────────┬────────┬────────┬────────┐",
        "│  1H    │ Signal │  4H    │ Signal │",
        "├────────┼────────┼────────┼────────┤",
    ]
    table.extend(rows)
    table.append("└────────┴────────┴────────┴────────┘")

    return "<code>" + "\n".join(table) + "</code>"


def format_indicators_block(ind: Optional[IndicatorSnapshot], label: str) -> str:
    """Format indicators for a single timeframe (legacy format)."""
    if not ind:
        return ""

    lines = [f"📊 <b>{label}:</b>"]
    lines.append(format_indicator_line("RSI", str(ind.rsi), ind.rsi_signal, _rsi_emoji(ind.rsi)))
    lines.append(format_indicator_line("MACD", str(ind.macd), ind.macd_signal, _signal_emoji(ind.macd_signal)))
    lines.append(format_indicator_line("EMA", f"{ind.ema_fast}/{ind.ema_slow}", ind.ema_signal, _signal_emoji(ind.ema_signal)))
    lines.append(format_indicator_line("ADX", str(ind.adx), ind.adx_signal, _signal_emoji(ind.adx_signal)))
    lines.append(f"├ Supertrend: <b>{ind.supertrend_signal}</b> {_supertrend_emoji(ind.supertrend_direction)}")
    lines.append(f"└ Volume: <b>{ind.volume_signal}</b> {_signal_emoji(ind.volume_signal)}")

    return "\n".join(lines)


def format_levels_block(resistance: list, support: list, label: str) -> str:
    """Format support/resistance levels."""
    r_str = " | ".join([f"R{i+1}: {_fmt_price(r)}" for i, r in enumerate(resistance[:3])])
    s_str = " | ".join([f"S{i+1}: {_fmt_price(s)}" for i, s in enumerate(support[:3])])

    lines = [f"📍 <b>Уровни ({label}):</b>"]
    lines.append(f"├ 🔴 {r_str}")
    lines.append(f"└ 🟢 {s_str}")

    return "\n".join(lines)


def format_strategy_block(index: int, strategy: TradeStrategy) -> str:
    """Format a single trading strategy."""
    emoji = _strategy_emoji(strategy.direction)

    lines = [f"{emoji} <b>{index}. {strategy.direction}</b> ({strategy.type})"]
    lines.append(f"├ Entry: {strategy.entry}")
    lines.append(f"├ SL: {strategy.stop_loss}")
    lines.append(f"├ TP1: {strategy.tp1}")
    if strategy.tp2 and strategy.tp2 != "-":
        lines.append(f"├ TP2: {strategy.tp2}")
    if strategy.tp3 and strategy.tp3 != "-":
        lines.append(f"├ TP3: {strategy.tp3}")
    lines.append(f"├ R:R: {strategy.rr_ratio}")
    lines.append(f"└ {strategy.reason}")

    return "\n".join(lines)


def format_token_report(report: TokenReport) -> str:
    """
    Format TokenReport as HTML for Telegram.

    Uses table format for indicators combining both timeframes.
    """
    lines = []

    # Header
    lines.append(f"📊 <b>{report.symbol}</b> — Анализ")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")

    # Price & Market Data
    lines.append(f"💰 <b>Цена:</b> {_fmt_price(report.price)}")
    if report.market_cap_rank:
        lines.append(f"📊 <b>Rank:</b> #{report.market_cap_rank} | Vol 24h: {_fmt_volume(report.volume_24h)}")
    else:
        lines.append(f"📊 <b>Vol 24h:</b> {_fmt_volume(report.volume_24h)}")
    lines.append(f"📈 <b>24h:</b> {_fmt_change(report.change_24h)} | 7D: {_fmt_change(report.change_7d)} | 30D: {_fmt_change(report.change_30d)}")

    # Indicators (table format)
    lines.append("")
    lines.append("📊 <b>Индикаторы:</b>")
    lines.append(format_indicators_table(report.indicators_1h, report.indicators_4h))

    # Context
    lines.append("")
    lines.append("🌍 <b>Контекст:</b>")
    fng_str = f"{report.fear_greed} ({report.fear_greed_label})" if report.fear_greed else "N/A"
    lines.append(f"├ F&G: {fng_str} {_fng_emoji(report.fear_greed)}")
    fr_str = f"{report.funding_rate:.4f}%" if report.funding_rate is not None else "N/A"
    lines.append(f"├ Funding: {fr_str} {_funding_emoji(report.funding_rate)}")
    ls_str = f"{report.long_short_ratio:.2f}" if report.long_short_ratio else "N/A"
    lines.append(f"├ Long/Short: {ls_str} {_ls_emoji(report.long_short_ratio)}")
    oi_str = f"{report.oi_delta:+.1f}%" if report.oi_delta is not None else "N/A"
    lines.append(f"└ OI: {oi_str}")

    # Levels
    lines.append("")
    if report.resistance_1h or report.support_1h:
        lines.append(format_levels_block(report.resistance_1h, report.support_1h, "1H"))
    if report.resistance_4h or report.support_4h:
        lines.append(format_levels_block(report.resistance_4h, report.support_4h, "4H"))

    # Strategies
    lines.append("")
    lines.append("💼 <b>Стратегии:</b>")
    for i, strategy in enumerate(report.strategies[:3], 1):
        lines.append(format_strategy_block(i, strategy))

    # Observations
    lines.append("")
    lines.append("💡 <b>Наблюдения:</b>")
    for obs in report.observations[:4]:
        lines.append(f"• {obs}")

    # Recommendation
    lines.append("")
    rec_emoji = {"LONG": "🟢", "SHORT": "🔴", "WAIT": "⏸️"}.get(report.recommendation, "❓")
    lines.append(f"{rec_emoji} <b>Рекомендация:</b> {report.recommendation}")
    if report.recommendation_reason:
        lines.append(f"<i>{report.recommendation_reason}</i>")

    return "\n".join(lines)


def format_token_report_compact(report: TokenReport) -> str:
    """
    Ultra-compact format for inline Telegram messages.
    """
    ind_1h = report.indicators_1h
    rsi_str = f"RSI {ind_1h.rsi}" if ind_1h else "RSI N/A"
    st_str = f"ST {ind_1h.supertrend_signal}" if ind_1h else "ST N/A"

    rec_emoji = {"LONG": "🟢", "SHORT": "🔴", "WAIT": "⏸️"}.get(report.recommendation, "❓")

    return (
        f"{rec_emoji} <b>{report.symbol}</b> {_fmt_price(report.price)} "
        f"| 7D: {_fmt_change(report.change_7d)} "
        f"| {rsi_str} | {st_str} "
        f"| R:{report.recommendation}"
    )
