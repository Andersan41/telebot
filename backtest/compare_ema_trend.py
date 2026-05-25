"""
backtest/compare_ema_trend.py — Compare backtest results for EMA_TREND=50 vs EMA_TREND=200.

Usage:
    python -m backtest.compare_ema_trend          # uses default BTC/USDT 1h
    python -m backtest.compare_ema_trend ETH/USDT 4h

Reads OHLCV from exchange (or local CSV if available), runs backtest twice
with different EMA_TREND values, and prints a side-by-side comparison.

DO NOT change the default EMA_TREND based on this alone — validate on
multiple symbols/timeframes and live forward-test first.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import config
from backtest.engine import BacktestEngine, BacktestResult


async def fetch_ohlcv(symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
    """Fetch OHLCV data from exchange."""
    from data.exchange_client import exchange_client
    return await exchange_client.fetch_ohlcv(symbol, timeframe, limit=limit)


def run_backtest(df: pd.DataFrame, symbol: str, timeframe: str, ema_trend: int) -> BacktestResult:
    """Run backtest with a specific EMA_TREND value and return full BacktestResult."""
    original = config.trading.ema_trend
    try:
        object.__setattr__(config.trading, "ema_trend", ema_trend)
        engine = BacktestEngine(symbol=symbol, timeframe=timeframe)
        return engine.run(df)
    finally:
        object.__setattr__(config.trading, "ema_trend", original)


def _metric_rows(r50: BacktestResult, r200: BacktestResult) -> list[list]:
    rows = []
    keys = [
        ("total_trades", "Total Trades", False),
        ("wins", "Wins", False),
        ("losses", "Losses", False),
        ("winrate", "Winrate %", True),
        ("avg_pnl", "Avg PnL %", True),
        ("avg_rr", "Avg R/R", True),
        ("profit_factor", "Profit Factor", True),
        ("expectancy", "Expectancy", True),
        ("sharpe_ratio", "Sharpe Ratio", True),
        ("max_drawdown", "Max Drawdown", True),
        ("total_pnl_pct", "Total PnL %", True),
        ("signals_generated", "Signals", False),
        ("exposure_time_pct", "Time in Market %", True),
        ("avg_trade_duration", "Avg Trade (candles)", True),
    ]
    for attr, label, is_float in keys:
        v50 = getattr(r50, attr)
        v200 = getattr(r200, attr)
        if is_float:
            rows.append([label, f"{v50:.2f}", f"{v200:.2f}", f"{v200 - v50:+.2f}"])
        else:
            rows.append([label, str(v50), str(v200), f"{v200 - v50:+d}"])
    return rows


def _print_table(headers: list[str], rows: list[list]):
    col_widths = [max(len(str(row[i])) for row in [headers] + rows) + 2 for i in range(len(headers))]
    def fmt(vals):
        return "".join(str(v).ljust(w) for v, w in zip(vals, col_widths))
    print("\n" + "=" * sum(col_widths))
    print(fmt(headers))
    print("-" * sum(col_widths))
    for row in rows:
        print(fmt(row))
    print("=" * sum(col_widths))


def _print_direction_stats(label: str, r50: BacktestResult, r200: BacktestResult):
    s50 = getattr(r50, f"{label}_stats", None)
    s200 = getattr(r200, f"{label}_stats", None)
    if s50 is None and s200 is None:
        return
    headers = [f"Metric ({label.upper()})", "EMA50", "EMA200", "Delta"]
    rows = []
    for attr, is_float in [("total_trades", False), ("winrate", True), ("profit_factor", True),
                            ("expectancy", True), ("avg_pnl", True), ("avg_rr", True)]:
        v50 = getattr(s50, attr, 0) if s50 else 0
        v200 = getattr(s200, attr, 0) if s200 else 0
        if is_float:
            rows.append([f"  {attr}", f"{v50:.2f}", f"{v200:.2f}", f"{v200 - v50:+.2f}"])
        else:
            rows.append([f"  {attr}", str(v50), str(v200), f"{v200 - v50:+d}"])
    _print_table(headers, rows)


def _print_volatility_stats(r50: BacktestResult, r200: BacktestResult):
    all_labels = sorted(set(list(r50.volatility_stats.keys()) + list(r200.volatility_stats.keys())))
    if not all_labels:
        return
    print("\n  --- Volatility regime breakdown ---")
    for vol_label in all_labels:
        s50 = r50.volatility_stats.get(vol_label)
        s200 = r200.volatility_stats.get(vol_label)
        v50_t = s50.total_trades if s50 else 0
        v200_t = s200.total_trades if s200 else 0
        v50_wr = s50.winrate if s50 else 0.0
        v200_wr = s200.winrate if s200 else 0.0
        v50_pf = s50.profit_factor if s50 else 0.0
        v200_pf = s200.profit_factor if s200 else 0.0
        v50_exp = s50.expectancy if s50 else 0.0
        v200_exp = s200.expectancy if s200 else 0.0
        print(f"  {vol_label:8s}: trades={v50_t:3d}/{v200_t:3d}  "
              f"wr={v50_wr:.1f}%/{v200_wr:.1f}%  "
              f"pf={v50_pf:.2f}/{v200_pf:.2f}  "
              f"exp={v50_exp:+.2f}/{v200_exp:+.2f}")


def print_comparison(r50: BacktestResult, r200: BacktestResult):
    """Print side-by-side comparison table with all metrics."""
    headers = ["Metric", "EMA50", "EMA200", "Delta"]
    rows = _metric_rows(r50, r200)
    _print_table(headers, rows)

    # Long / Short breakdown
    print("\n--- Direction breakdown ---")
    _print_direction_stats("long", r50, r200)
    _print_direction_stats("short", r50, r200)

    # Volatility regime breakdown
    _print_volatility_stats(r50, r200)

    # Regime breakdown (market structure regimes)
    print("\n--- Market regime breakdown (EMA200) ---")
    for regime_name, stats in sorted(r200.regime_stats.items()):
        r50_s = r50.regime_stats.get(regime_name)
        r50_t = r50_s.total_trades if r50_s else 0
        r50_wr = r50_s.winrate if r50_s else 0.0
        r50_pf = r50_s.profit_factor if r50_s else 0.0
        r50_exp = r50_s.expectancy if r50_s else 0.0
        print(f"  {regime_name:12s}: trades={r50_t:3d}/{stats.total_trades:3d}  "
              f"wr={r50_wr:.1f}%/{stats.winrate:.1f}%  "
              f"pf={r50_pf:.2f}/{stats.profit_factor:.2f}  "
              f"exp={r50_exp:+.2f}/{stats.expectancy:+.2f}")


async def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC/USDT"
    timeframe = sys.argv[2] if len(sys.argv) > 2 else "1h"

    print(f"Fetching {symbol} {timeframe} OHLCV...")
    df = await fetch_ohlcv(symbol, timeframe, limit=500)
    if df is None or len(df) < 100:
        print(f"ERROR: Not enough data for {symbol} {timeframe}")
        return

    print(f"Loaded {len(df)} candles")

    print("\n--- Running backtest with EMA_TREND=50 ---")
    r50 = run_backtest(df, symbol, timeframe, ema_trend=50)

    print("\n--- Running backtest with EMA_TREND=200 ---")
    r200 = run_backtest(df, symbol, timeframe, ema_trend=200)

    print_comparison(r50, r200)


if __name__ == "__main__":
    asyncio.run(main())
