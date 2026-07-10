"""
Slim runner: only the removal presets needed for attribution analysis.
Runs on 4 target symbols, uses cached data, shares indicator computation.
"""
import asyncio, io, json, os, sys, time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger as _loguru_logger
_loguru_logger.disable("strategy.signal_engine")
_loguru_logger.disable("indicators.engine")
import logging
logging.getLogger("strategy.signal_engine").setLevel(logging.WARNING)
logging.getLogger("indicators.engine").setLevel(logging.WARNING)

# Import engine modules (they replace sys.stdout)
from scripts.filter_attribution import (
    run_symbol_batch, compute_metrics, aggregate_metrics,
    SYMBOLS, TIMEFRAME, CANDLES, CONFIRM_TF, CONFIRM_CANDLES, WARMUP,
    REMOVAL_PRESETS, REPORTS_DIR,
)
from backtest.cache_ohlcv import load_cached
from indicators.engine import IndicatorEngine

# Do NOT restore stdout - engine's UTF-8 wrapper is fine for printing


async def main():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    indicator_engine = IndicatorEngine()

    all_results = {}
    for sym_idx, symbol in enumerate(SYMBOLS, 1):
        print(f"\n[{sym_idx}/{len(SYMBOLS)}] {symbol}...", end=" ", flush=True)
        t0 = time.time()
        cached_1h = load_cached(symbol, TIMEFRAME, CANDLES)
        cached_15m = load_cached(symbol, CONFIRM_TF, CONFIRM_CANDLES)
        if cached_1h is None:
            print("NO CACHE")
            continue
        df = cached_1h.copy()
        confirm_df = cached_15m.copy() if cached_15m is not None else None

        batch = await run_symbol_batch(symbol, df, confirm_df, indicator_engine, REMOVAL_PRESETS)
        for preset_name, result in batch.items():
            metrics = compute_metrics(result["state"], result["total_candles"])
            all_results[f"{preset_name}_{symbol}"] = metrics

        elapsed = time.time() - t0
        trades = all_results.get(f"full_new_{symbol}", {}).get("total_trades", 0)
        print(f"done ({elapsed:.1f}s) trades={trades}")

    # Save results
    out_path = REPORTS_DIR / "raw_results_attribution.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({k: {kk: vv for kk, vv in v.items() if kk != "pnl_list"} for k, v in all_results.items()}, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(all_results)} results to {out_path}")

    # Now run the full report generation
    preset_aggregates = {}
    for preset_name in REMOVAL_PRESETS:
        per_sym = {s: all_results.get(f"{preset_name}_{s}", {}) for s in SYMBOLS}
        preset_aggregates[preset_name] = aggregate_metrics(per_sym)

    print(f"\nBaseline: {preset_aggregates['full_new']['total_trades']} trades, WR={preset_aggregates['full_new']['winrate']}%, Exp={preset_aggregates['full_new']['expectancy']:+.4f}%")

    # Import and run all report generators
    from scripts.filter_attribution import (
        step0_filter_inventory, step1_baseline, step2_removal_tests,
        step3_rejection_analysis, step3b_filter_funnel, step4_rejected_quality,
        step5_interaction_test, step6_live_only_architecture, step7_edge_source,
        step8_edge_preservation, step8b_anomaly_log, generate_final_report,
    )

    print("\n[Step 0] Filter Inventory...")
    step0_filter_inventory()
    print("[Step 1] Baseline...")
    step1_baseline(preset_aggregates, all_results)
    print("[Step 2] Removal Tests...")
    removal_rows = step2_removal_tests(preset_aggregates, preset_aggregates["full_new"])
    print("[Step 3] Rejection Analysis...")
    step3_rejection_analysis(preset_aggregates)
    print("[Step 3B] Filter Funnel...")
    step3b_filter_funnel(preset_aggregates)
    print("[Step 4] Rejected Signal Quality...")
    step4_rejected_quality(preset_aggregates)
    print("[Step 5] Interaction Tests...")
    step5_interaction_test(preset_aggregates, removal_rows)
    print("[Step 6] Live-Only Architecture...")
    step6_live_only_architecture()
    print("[Step 7] Edge Source Analysis...")
    step7_edge_source(preset_aggregates)
    print("[Step 8] Edge Preservation...")
    step8_edge_preservation(removal_rows)
    print("[Step 8B] Anomaly Log...")
    anomalies = step8b_anomaly_log(preset_aggregates)
    print("[Final] Generating report...")
    generate_final_report(preset_aggregates, preset_aggregates["full_new"], removal_rows, anomalies)

    elapsed = time.time() - t_start
    print(f"\n{'='*70}")
    print(f"  Analysis complete in {elapsed:.1f}s")
    print(f"  Reports: {REPORTS_DIR}")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
