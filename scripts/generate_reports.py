"""Generate all reports from saved attribution results."""
import json, sys, os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger as _loguru_logger
_loguru_logger.disable("strategy.signal_engine")
_loguru_logger.disable("indicators.engine")

from scripts.filter_attribution import (
    aggregate_metrics, step0_filter_inventory, step1_baseline,
    step2_removal_tests, step3_rejection_analysis, step3b_filter_funnel,
    step4_rejected_quality, step5_interaction_test, step6_live_only_architecture,
    step7_edge_source, step8_edge_preservation, step8b_anomaly_log,
    generate_final_report, SYMBOLS, REMOVAL_PRESETS, REPORTS_DIR,
)

sys.stdout = sys.__stdout__

# Load saved results
raw_path = REPORTS_DIR / "raw_results_attribution.json"
print(f"Loading {raw_path}...")
with open(raw_path, "r", encoding="utf-8") as f:
    all_results = json.load(f)
print(f"Loaded {len(all_results)} result sets")

# Aggregate across symbols
print("\nAggregating across symbols...")
preset_aggregates = {}
for preset_name in REMOVAL_PRESETS:
    per_sym = {s: all_results.get(f"{preset_name}_{s}", {}) for s in SYMBOLS}
    preset_aggregates[preset_name] = aggregate_metrics(per_sym)

baseline_agg = preset_aggregates["full_new"]
print(f"Baseline: {baseline_agg['total_trades']} trades, WR={baseline_agg['winrate']}%, Exp={baseline_agg['expectancy']:+.4f}%")

# Generate all reports
print("\n[Step 0] Filter Inventory...")
step0_filter_inventory()
print("[Step 1] Baseline...")
step1_baseline(preset_aggregates, all_results)
print("[Step 2] Removal Tests...")
removal_rows = step2_removal_tests(preset_aggregates, baseline_agg)
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
generate_final_report(preset_aggregates, baseline_agg, removal_rows, anomalies)

print(f"\nDone! Reports in: {REPORTS_DIR}")
