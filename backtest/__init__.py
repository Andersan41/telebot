"""
backtest/ — Consolidated backtest engine with full parity to live pipeline.
"""
from .engine import (
    BacktestEngine, BacktestTrade, BacktestResult, RejectStats,
    BacktestConfig, PRESETS, get_preset_config,
)

__all__ = [
    "BacktestEngine", "BacktestTrade", "BacktestResult", "RejectStats",
    "BacktestConfig", "PRESETS", "get_preset_config",
]
