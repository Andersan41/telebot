"""
charts/signal_chart.py — Генерация PNG графика для Telegram сигнала.

Рисует: свечи, entry/SL/TP, OB/FVG зоны, MSS/Sweep маркеры, volume.
Тёмная тема, компактный размер (~800x450).
"""
from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Rectangle
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd


BG = "#111114"
BG_PANEL = "#18181c"
TEXT = "#aaaaaa"
TEXT_BRIGHT = "#e0e0e0"
GREEN = "#a3e635"
RED = "#f87171"
BLUE = "#60a5fa"
AMBER = "#facc15"
PURPLE = "#c084fc"
GRID = "#222228"
GRID_LIGHT = "#2a2a32"

# DPI for Telegram (not too large)
DPI = 110
FIG_W = 800 / DPI
FIG_H = 450 / DPI


def _price_decimals(price: float) -> int:
    if price >= 1000:
        return 2
    if price >= 1:
        return 4
    if price >= 0.01:
        return 6
    if price >= 0.001:
        return 8
    return 10


def _fmt_price(price: float, decimals: int = None) -> str:
    if decimals is None:
        decimals = _price_decimals(price)
    if price >= 1000:
        return f"{price:,.{decimals}f}"
    return f"{price:.{decimals}f}"


def generate_signal_chart(
    df: pd.DataFrame,
    direction: str,
    entry_price: float,
    sl: float,
    tp: float,
    symbol: str,
    timeframe: str,
    visual: Optional[Dict[str, Any]] = None,
    score: int = 0,
    p_tp: float = 0.0,
    expected_rr: float = 0.0,
) -> bytes:
    """Generate signal chart PNG as bytes.

    Args:
        df: OHLCV DataFrame with datetime index (last 100+ candles)
        direction: "buy" or "sell"
        entry_price: Entry level
        sl: Stop loss level
        tp: Take profit level
        symbol: e.g. "BTC/USDT"
        timeframe: e.g. "1h"
        visual: Optional visual trace dict (sweep, mss, ob, fvg keys)
        score: Signal score
        p_tp: Probability of TP
        expected_rr: Expected risk-reward

    Returns:
        PNG bytes
    """
    if df is None or len(df) < 5:
        return b""

    # Use last 80 candles for chart
    n = min(80, len(df))
    chart_df = df.tail(n).copy()
    chart_df = chart_df.reset_index(drop=True)

    dec = _price_decimals(entry_price)

    # Colors based on direction
    is_buy = direction == "buy"
    entry_color = GREEN if is_buy else RED

    # ── Setup figure ──
    fig, (ax_main, ax_vol) = plt.subplots(
        2, 1, figsize=(FIG_W, FIG_H),
        gridspec_kw={"height_ratios": [4, 1], "hspace": 0.08},
        facecolor=BG, constrained_layout=True,
    )
    for ax in (ax_main, ax_vol):
        ax.set_facecolor(BG)
        ax.tick_params(colors=TEXT, labelsize=7)
        ax.grid(True, color=GRID, linewidth=0.3, alpha=0.6)
        for spine in ax.spines.values():
            spine.set_color(GRID)

    ax_main.set_ylabel("Price", color=TEXT, fontsize=8)
    ax_vol.set_ylabel("Vol", color=TEXT, fontsize=7)

    # ── Draw candles ──
    opens = chart_df["open"].values
    highs = chart_df["high"].values
    lows = chart_df["low"].values
    closes = chart_df["close"].values
    volumes = chart_df["volume"].values if "volume" in chart_df.columns else np.zeros(n)
    x = np.arange(n)

    # Wick lines
    for i in range(n):
        color = GREEN if closes[i] >= opens[i] else RED
        ax_main.plot([i, i], [lows[i], highs[i]], color=color, linewidth=0.6, zorder=2)

    # Bodies
    for i in range(n):
        color = GREEN if closes[i] >= opens[i] else RED
        body_low = min(opens[i], closes[i])
        body_high = max(opens[i], closes[i])
        body_h = max(body_high - body_low, (highs[i] - lows[i]) * 0.005)
        rect = Rectangle((i - 0.35, body_low), 0.7, body_h, facecolor=color, edgecolor=color, linewidth=0.5, zorder=3)
        ax_main.add_patch(rect)

    # Volume bars
    vol_colors = [GREEN if closes[i] >= opens[i] else RED for i in range(n)]
    ax_vol.bar(x, volumes, width=0.7, color=vol_colors, alpha=0.5, zorder=3)

    # ── Entry / SL / TP1/TP2/TP3 lines ──
    risk = abs(entry_price - sl)
    if risk > 0:
        if direction == "buy":
            tp1 = entry_price + risk * 2
            tp2 = entry_price + risk * 3
            tp3 = entry_price + risk * 4
        else:
            tp1 = entry_price - risk * 2
            tp2 = entry_price - risk * 3
            tp3 = entry_price - risk * 4
    else:
        tp1 = tp2 = tp3 = tp

    price_min = min(lows)
    price_max = max(highs)
    all_levels = [entry_price, sl, tp1, tp2, tp3]
    level_min = min(min(all_levels), price_min)
    level_max = max(max(all_levels), price_max)
    margin = (level_max - level_min) * 0.12

    ax_main.axhline(entry_price, color=entry_color, linewidth=1.2, linestyle="--", zorder=5, alpha=0.9)
    ax_main.axhline(sl, color=RED, linewidth=1.0, linestyle=":", zorder=5, alpha=0.7)
    ax_main.axhline(tp1, color="#4caf50", linewidth=0.8, linestyle=":", zorder=5, alpha=0.6)
    ax_main.axhline(tp2, color="#66bb6a", linewidth=0.8, linestyle=":", zorder=5, alpha=0.6)
    ax_main.axhline(tp3, color=GREEN, linewidth=1.0, linestyle=":", zorder=5, alpha=0.7)

    # Labels for levels
    label_x = n - 1
    ax_main.text(label_x + 0.5, entry_price, f"  Entry {_fmt_price(entry_price, dec)}", color=entry_color, fontsize=7, va="center", fontweight="bold", zorder=6)
    ax_main.text(label_x + 0.5, sl, f"  SL {_fmt_price(sl, dec)}", color=RED, fontsize=7, va="center", zorder=6)
    ax_main.text(label_x + 0.5, tp1, f"  TP1 {_fmt_price(tp1, dec)}", color="#4caf50", fontsize=6, va="center", zorder=6)
    ax_main.text(label_x + 0.5, tp2, f"  TP2 {_fmt_price(tp2, dec)}", color="#66bb6a", fontsize=6, va="center", zorder=6)
    ax_main.text(label_x + 0.5, tp3, f"  TP3 {_fmt_price(tp3, dec)}", color=GREEN, fontsize=7, va="center", zorder=6)

    ax_main.set_ylim(level_min - margin, level_max + margin * 1.5)

    # ── Draw OB / FVG zones ──
    if visual:
        # Order Blocks
        for ob_key in ("ob",):
            ob = visual.get(ob_key)
            if ob and ob.get("high") and ob.get("low"):
                ob_high = ob["high"]
                ob_low = ob["low"]
                ob_type = ob.get("type", "")
                ob_color = PURPLE if "bull" in ob_type.lower() or "demand" in ob_type.lower() else AMBER
                rect = Rectangle((0, ob_low), n, ob_high - ob_low,
                                 facecolor=ob_color, alpha=0.1, edgecolor=ob_color,
                                 linewidth=0.5, linestyle="--", zorder=1)
                ax_main.add_patch(rect)
                ax_main.text(n * 0.02, ob_high, f"OB {'↑' if is_buy else '↓'}",
                             color=ob_color, fontsize=6, va="bottom", zorder=6, alpha=0.8)

        # FVG
        fvg = visual.get("fvg")
        if fvg and fvg.get("high") and fvg.get("low"):
            fvg_high = fvg["high"]
            fvg_low = fvg["low"]
            rect = Rectangle((0, fvg_low), n, fvg_high - fvg_low,
                             facecolor=BLUE, alpha=0.08, edgecolor=BLUE,
                             linewidth=0.5, linestyle=":", zorder=1)
            ax_main.add_patch(rect)

        # MSS line
        mss = visual.get("mss")
        if mss and mss.get("price"):
            ax_main.axhline(mss["price"], color=AMBER, linewidth=0.8, linestyle="-.", zorder=4, alpha=0.5)
            ax_main.text(1, mss["price"], " MSS", color=AMBER, fontsize=6, va="center", zorder=6, alpha=0.7)

    # ── Title / Info ──
    arrow = "▲" if is_buy else "▼"
    title_color = GREEN if is_buy else RED
    title = f"{symbol} {timeframe}  {arrow} {direction.upper()}"
    ax_main.set_title(title, color=title_color, fontsize=10, fontweight="bold", loc="left", pad=8)

    # Stats box
    stats = f"Score: {score}  |  P(TP): {p_tp:.0%}  |  RR: {expected_rr:.1f}"
    ax_main.text(0.99, 0.97, stats, transform=ax_main.transAxes, color=TEXT_BRIGHT,
                 fontsize=7, va="top", ha="right", zorder=10,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor=BG_PANEL, edgecolor=GRID, alpha=0.9))

    # X-axis labels (time)
    if hasattr(chart_df.index, 'strftime') and len(chart_df.index) > 0:
        idx = chart_df.index
        tick_positions = np.linspace(0, n - 1, min(6, n)).astype(int)
        tick_labels = []
        for tp_i in tick_positions:
            try:
                tick_labels.append(idx[tp_i].strftime("%m/%d\n%H:%M"))
            except (AttributeError, IndexError):
                tick_labels.append(str(tp_i))
        ax_vol.set_xticks(tick_positions)
        ax_vol.set_xticklabels(tick_labels, color=TEXT, fontsize=6)
    else:
        ax_vol.set_xlabel("Candles", color=TEXT, fontsize=7)

    ax_main.set_xticks([])
    ax_vol.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v/1e6:.1f}M" if v >= 1e6 else f"{v/1e3:.0f}K" if v >= 1e3 else f"{v:.0f}"))

    # ── Render to bytes ──
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, facecolor=BG, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    buf.seek(0)
    return buf.read()
