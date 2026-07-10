"""
market_structure — Market structure analysis: BOS, CHoCH, swing points,
distance filter, TP path quality, multi-timeframe alignment.
"""
from market_structure.structure import (
    SwingPoint,
    BOS,
    CHoCH,
    StructureState,
    MTFAlignmentResult,
    analyze_structure,
    check_mtf_alignment,
    calc_htf_alignment_score,
    calc_premium_discount_score,
)
from market_structure.distance_filter import (
    DistanceFilterResult,
    check_distance_filter,
)
from market_structure.tp_path import (
    Obstacle,
    TPEvaluation,
    evaluate_tp_path,
)

__all__ = [
    "SwingPoint",
    "BOS",
    "CHoCH",
    "StructureState",
    "MTFAlignmentResult",
    "analyze_structure",
    "check_mtf_alignment",
    "calc_htf_alignment_score",
    "calc_premium_discount_score",
    "DistanceFilterResult",
    "check_distance_filter",
    "Obstacle",
    "TPEvaluation",
    "evaluate_tp_path",
]
