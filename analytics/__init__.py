"""
analytics/ — Data-driven audit suite for trading signal optimization.

Modules:
    trace_export      — Full DecisionTrace export (300-1000+ trades)
    trades_export     — Per-trade export for attribution/drift/walk-forward
    gate_funnel       — Gate funnel: Entered/Passed/TP/SL/WR per gate
    version_compare   — Strategy version comparison with param diffs
    drift_report      — Weekly factor/regime performance drift
    counterfactual    — What-if gate removal analysis
    distributions     — Factor distributions (median, P5/P95, TP vs SL)
    feature_drift     — Feature distribution drift detection
    calibration       — Probability calibration (confidence vs actual WR)
    evolution         — Automated weight optimization via walk-forward
    factor_stats      — Per-factor winrate/PF/expectancy (original)
    entry_delay       — Entry timing analysis (original)
    performance       — Overall/segmented/MFE-MAE stats, filter counterfactual
"""
from .factor_stats import (
    FactorContribution,
    FactorCombination,
    FalsePositiveReport,
    compute_factor_stats,
    compute_combination_stats,
    compute_false_positives,
)
from .entry_delay import (
    EntryTimingRecord,
    EntryEfficiencySummary,
    analyze_entry_timing,
    compute_entry_efficiency_summary,
)
from .performance import (
    WinrateStats,
    SegmentStats,
    MfeMaeReport,
    FilterCounterfactual,
    overall_stats,
    segmented_stats,
    mfe_mae_analysis,
    filter_counterfactual,
    format_overall_stats,
    format_segmented_stats,
    format_mfe_mae,
    format_counterfactual,
    format_stats_telegram,
    format_segmented_telegram,
)

__all__ = [
    "FactorContribution",
    "FactorCombination",
    "FalsePositiveReport",
    "compute_factor_stats",
    "compute_combination_stats",
    "compute_false_positives",
    "EntryTimingRecord",
    "EntryEfficiencySummary",
    "analyze_entry_timing",
    "compute_entry_efficiency_summary",
    "WinrateStats",
    "SegmentStats",
    "MfeMaeReport",
    "FilterCounterfactual",
    "overall_stats",
    "segmented_stats",
    "mfe_mae_analysis",
    "filter_counterfactual",
    "format_overall_stats",
    "format_segmented_stats",
    "format_mfe_mae",
    "format_counterfactual",
    "format_stats_telegram",
    "format_segmented_telegram",
]
