"""
Run 10 custom presets for Report 6: final A/B/n backtest.
Presets:
  1. true_baseline — all flags False
  2. unified_only — unified_entry=True only
  3. structural_sl_only — structural_sl=True only
  4. sl_guard_only — sl_distance_guard=True only
  5. rr_filter_only — rr_filter=True only
  6. gate_only — confirm_tf_gate=True only
  7. buffer_only — stop_hunt_buffer=True (+ structural_sl, coupled)
  8. full_old — all flags True (old FULL)
  9. full_new — gate=False, buffer=False, rest True (new FULL)
  10. unified_plus_filters — unified + structural_sl + sl_guard + rr_filter (clean combo)
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

_saved_stdout = sys.stdout
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger as _loguru_logger
_loguru_logger.disable("strategy.signal_engine")
_loguru_logger.disable("indicators.engine")
import logging
logging.getLogger("strategy.signal_engine").setLevel(logging.WARNING)
logging.getLogger("indicators.engine").setLevel(logging.WARNING)

from backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    BacktestTrade,
    get_preset_config,
)
from config.settings import config
sys.stdout = _saved_stdout

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "XRP/USDT", "SOL/USDT", "DOGE/USDT",
    "AVAX/USDT", "LINK/USDT", "ADA/USDT", "DOT/USDT", "UNI/USDT",
    "NEAR/USDT", "APT/USDT", "ARB/USDT", "OP/USDT", "SUI/USDT",
    "INJ/USDT", "WIF/USDT", "FLOKI/USDT", "FIL/USDT", "GRT/USDT",
]

TIMEFRAME = "1h"
CANDLES = 3900

# 10 custom presets
PRESETS = {
    "true_baseline": {
        "enable_unified_entry": False,
        "enable_confirm_tf_gate": False,
        "enable_structural_sl": False,
        "enable_sl_distance_guard": False,
        "enable_rr_filter": False,
        "enable_news_filter": False,
        "enable_stop_hunt_buffer": False,
    },
    "unified_only": {
        "enable_unified_entry": True,
        "enable_confirm_tf_gate": False,
        "enable_structural_sl": False,
        "enable_sl_distance_guard": False,
        "enable_rr_filter": False,
        "enable_news_filter": False,
        "enable_stop_hunt_buffer": False,
    },
    "structural_sl_only": {
        "enable_unified_entry": False,
        "enable_confirm_tf_gate": False,
        "enable_structural_sl": True,
        "enable_sl_distance_guard": False,
        "enable_rr_filter": False,
        "enable_news_filter": False,
        "enable_stop_hunt_buffer": False,
    },
    "sl_guard_only": {
        "enable_unified_entry": False,
        "enable_confirm_tf_gate": False,
        "enable_structural_sl": False,
        "enable_sl_distance_guard": True,
        "enable_rr_filter": False,
        "enable_news_filter": False,
        "enable_stop_hunt_buffer": False,
    },
    "rr_filter_only": {
        "enable_unified_entry": False,
        "enable_confirm_tf_gate": False,
        "enable_structural_sl": False,
        "enable_sl_distance_guard": False,
        "enable_rr_filter": True,
        "enable_news_filter": False,
        "enable_stop_hunt_buffer": False,
    },
    "gate_only": {
        "enable_unified_entry": False,
        "enable_confirm_tf_gate": True,
        "enable_structural_sl": False,
        "enable_sl_distance_guard": False,
        "enable_rr_filter": False,
        "enable_news_filter": False,
        "enable_stop_hunt_buffer": False,
    },
    "buffer_only": {
        # Coupled: buffer requires structural SL to be active
        "enable_unified_entry": False,
        "enable_confirm_tf_gate": False,
        "enable_structural_sl": True,
        "enable_sl_distance_guard": False,
        "enable_rr_filter": False,
        "enable_news_filter": False,
        "enable_stop_hunt_buffer": True,
    },
    "full_old": {
        "enable_unified_entry": True,
        "enable_confirm_tf_gate": True,
        "enable_structural_sl": True,
        "enable_sl_distance_guard": True,
        "enable_rr_filter": True,
        "enable_news_filter": True,
        "enable_stop_hunt_buffer": True,
    },
    "full_new": {
        "enable_unified_entry": True,
        "enable_confirm_tf_gate": False,
        "enable_structural_sl": True,
        "enable_sl_distance_guard": True,
        "enable_rr_filter": True,
        "enable_news_filter": True,
        "enable_stop_hunt_buffer": False,
    },
    "unified_plus_filters": {
        "enable_unified_entry": True,
        "enable_confirm_tf_gate": False,
        "enable_structural_sl": True,
        "enable_sl_distance_guard": True,
        "enable_rr_filter": True,
        "enable_news_filter": False,
        "enable_stop_hunt_buffer": False,
    },
}

PRESET_ORDER = list(PRESETS.keys())
RESULTS_DIR = Path(__file__).parent.parent / "reports" / "abn"


def make_config(flags: dict) -> BacktestConfig:
    return BacktestConfig(**flags)


def result_to_record(symbol: str, preset: str, r: BacktestResult) -> dict:
    rs = r.reject_stats
    rec = {
        "symbol": symbol,
        "preset": preset,
        "total_trades": r.total_trades,
        "wins": r.wins,
        "losses": r.losses,
        "winrate": r.winrate,
        "avg_pnl": r.avg_pnl,
        "avg_net_pnl": r.avg_net_pnl,
        "avg_rr": r.avg_rr,
        "profit_factor": r.profit_factor,
        "expectancy": r.expectancy,
        "sharpe_ratio": r.sharpe_ratio,
        "max_drawdown": r.max_drawdown,
        "total_pnl_pct": r.total_pnl_pct,
        "total_net_pnl_pct": r.total_net_pnl_pct,
        "signals_generated": r.signals_generated,
        "signals_rejected": r.signals_rejected,
        "exposure_time_pct": r.exposure_time_pct,
        "avg_trade_duration": r.avg_trade_duration,
        "reject_rr": rs.rr_rejected,
        "reject_sl_dist": rs.sl_distance_rejected,
        "reject_confirm_tf": rs.confirm_tf_rejected,
        "reject_news": rs.news_rejected,
        "exit_sl": 0,
        "exit_tp": 0,
        "exit_eob": 0,
        "src_atr": 0,
        "src_bos": 0,
        "src_structural": 0,
        "trades": [],
    }
    for t in r.trades:
        rec["trades"].append({
            "symbol": t.symbol,
            "direction": t.direction,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "exit_reason": t.exit_reason,
            "pnl_pct": t.pnl_pct,
            "net_pnl_pct": t.net_pnl_pct,
            "rr": t.rr,
            "sl_source": t.sl_source,
            "regime": t.regime,
            "entry_timestamp": t.entry_timestamp,
            "exit_timestamp": t.exit_timestamp,
        })
        if t.exit_reason == "sl":
            rec["exit_sl"] += 1
        elif t.exit_reason == "tp":
            rec["exit_tp"] += 1
        elif t.exit_reason == "eob":
            rec["exit_eob"] += 1
        src = t.sl_source or "atr"
        if src == "bos":
            rec["src_bos"] += 1
        elif src == "structural":
            rec["src_structural"] += 1
        else:
            rec["src_atr"] += 1
    return rec


def aggregate_records(records: list[dict]) -> dict:
    if not records:
        return {}
    total_trades = sum(r["total_trades"] for r in records)
    if total_trades == 0:
        return {"total_trades": 0, "symbols": len(records), "winrate": 0.0,
                "total_pnl_pct": 0.0, "total_net_pnl_pct": 0.0}
    total_wins = sum(r["wins"] for r in records)
    total_pnl = sum(r["total_pnl_pct"] for r in records)
    total_net_pnl = sum(r["total_net_pnl_pct"] for r in records)
    total_signals = sum(r["signals_generated"] for r in records)
    total_rejected = sum(r["signals_rejected"] for r in records)
    total_exit_sl = sum(r["exit_sl"] for r in records)
    total_exit_tp = sum(r["exit_tp"] for r in records)
    total_exit_eob = sum(r["exit_eob"] for r in records)
    total_src_atr = sum(r["src_atr"] for r in records)
    total_src_bos = sum(r["src_bos"] for r in records)
    total_src_structural = sum(r["src_structural"] for r in records)
    total_rr = sum(r["avg_rr"] * r["total_trades"] for r in records)
    total_reject_rr = sum(r["reject_rr"] for r in records)
    total_reject_sl = sum(r["reject_sl_dist"] for r in records)
    total_reject_ctf = sum(r["reject_confirm_tf"] for r in records)
    max_dd = max(r["max_drawdown"] for r in records) if records else 0.0

    gross_profit = sum(r["total_pnl_pct"] for r in records if r["total_pnl_pct"] > 0)
    gross_loss = abs(sum(r["total_pnl_pct"] for r in records if r["total_pnl_pct"] < 0))

    return {
        "total_trades": total_trades,
        "symbols": len(records),
        "winrate": round(total_wins / total_trades * 100, 1),
        "avg_pnl": round(sum(r["avg_pnl"] * r["total_trades"] for r in records) / total_trades, 4),
        "avg_net_pnl": round(sum(r["avg_net_pnl"] * r["total_trades"] for r in records) / total_trades, 4),
        "avg_rr": round(total_rr / total_trades, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0,
        "expectancy": round(sum(r["expectancy"] * r["total_trades"] for r in records) / total_trades, 4),
        "max_drawdown": round(max_dd, 4),
        "total_pnl_pct": round(total_pnl, 4),
        "total_net_pnl_pct": round(total_net_pnl, 4),
        "signals_generated": total_signals,
        "signals_rejected": total_rejected,
        "exit_sl": total_exit_sl,
        "exit_tp": total_exit_tp,
        "exit_eob": total_exit_eob,
        "src_atr": total_src_atr,
        "src_bos": total_src_bos,
        "src_structural": total_src_structural,
        "reject_rr": total_reject_rr,
        "reject_sl_dist": total_reject_sl,
        "reject_confirm_tf": total_reject_ctf,
    }


async def run_one(symbol: str, preset: str, candles: int) -> dict:
    bt_config = make_config(PRESETS[preset])
    config.trading.candles_limit = candles

    from data.exchange_client import exchange_client
    _orig_fetch = exchange_client.fetch_ohlcv

    from backtest.cache_ohlcv import load_cached, CONFIRM_TIMEFRAME, CONFIRM_CANDLES
    cached_1h = load_cached(symbol, TIMEFRAME, candles)
    cached_15m = load_cached(symbol, CONFIRM_TIMEFRAME, CONFIRM_CANDLES)

    async def _fetch_cached(s, tf, limit=200):
        if s == symbol and tf == TIMEFRAME and cached_1h is not None:
            return cached_1h.iloc[-limit:].copy() if limit < len(cached_1h) else cached_1h.copy()
        if s == symbol and tf == CONFIRM_TIMEFRAME and cached_15m is not None:
            return cached_15m.iloc[-limit:].copy() if limit < len(cached_15m) else cached_15m.copy()
        return await _orig_fetch(s, tf, limit)

    exchange_client.fetch_ohlcv = _fetch_cached
    try:
        engine = BacktestEngine(
            symbol=symbol,
            timeframe=TIMEFRAME,
            send_telegram=False,
            bt_config=bt_config,
        )
        result = await engine.run()
    finally:
        exchange_client.fetch_ohlcv = _orig_fetch

    sys.stdout = _saved_stdout
    return result_to_record(symbol, preset, result)


async def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    partial_path = RESULTS_DIR / "raw_results_r6.jsonl"

    all_results: dict[str, dict] = {}
    if partial_path.exists():
        with open(partial_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                key = f"{rec['symbol']}|{rec['preset']}"
                all_results[key] = rec

    total_runs = len(SYMBOLS) * len(PRESETS)
    completed = len(all_results)
    print(f"=" * 70)
    print(f"  REPORT 6 BACKTEST: {len(SYMBOLS)} symbols x {len(PRESETS)} presets = {total_runs} runs")
    print(f"  Candles: {CANDLES} (~{CANDLES / 24:.0f} days = ~{CANDLES / 24 / 30:.1f} months)")
    print(f"  Already completed: {completed}/{total_runs}")
    print(f"=" * 70)

    with open(partial_path, "a", encoding="utf-8") as f:
        run_idx = 0
        for symbol in SYMBOLS:
            for preset in PRESET_ORDER:
                run_idx += 1
                key = f"{symbol}|{preset}"
                if key in all_results:
                    print(f"  [{run_idx}/{total_runs}] SKIP {symbol} {preset} (already done)")
                    continue

                print(f"  [{run_idx}/{total_runs}] Running {symbol} {preset}...", end=" ", flush=True)
                t0 = time.time()
                try:
                    rec = await run_one(symbol, preset, CANDLES)
                    elapsed = time.time() - t0
                    print(f"trades={rec['total_trades']} pnl={rec['total_net_pnl_pct']:+.2f}% ({elapsed:.1f}s)")
                    all_results[key] = rec
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    f.flush()
                except Exception as e:
                    elapsed = time.time() - t0
                    print(f"ERROR: {e} ({elapsed:.1f}s)")

                await asyncio.sleep(0.3)

    results_json = RESULTS_DIR / "raw_results_r6.json"
    with open(results_json, "w", encoding="utf-8") as f:
        json.dump(list(all_results.values()), f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(all_results)} results to {results_json}")

    # Build aggregates for quick access
    agg: dict[str, dict] = {}
    for preset in PRESET_ORDER:
        preset_records = [all_results[f"{s}|{preset}"] for s in SYMBOLS if f"{s}|{preset}" in all_results]
        agg[preset] = aggregate_records(preset_records)

    agg_json = RESULTS_DIR / "aggregates_r6.json"
    with open(agg_json, "w", encoding="utf-8") as f:
        json.dump(agg, f, indent=2, ensure_ascii=False)
    print(f"Saved aggregates to {agg_json}")

    # Print summary
    print(f"\n{'='*70}")
    print(f"  SUMMARY: {len(PRESETS)} presets")
    print(f"{'='*70}")
    for preset in PRESET_ORDER:
        a = agg.get(preset, {})
        print(f"  {preset:28s} trades={a.get('total_trades', 0):4d}  "
              f"wr={a.get('winrate', 0):5.1f}%  "
              f"pnl={a.get('total_net_pnl_pct', 0):+8.2f}%  "
              f"pf={a.get('profit_factor', 0):5.2f}  "
              f"dd={a.get('max_drawdown', 0):6.2f}%")


if __name__ == "__main__":
    asyncio.run(main())
