"""Shared configuration for ML training pipeline."""
from __future__ import annotations

import os
from pathlib import Path

# --- Paths ---
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "training"
OHLCV_DIR = DATA_DIR / "ohlcv"
LABELED_DIR = DATA_DIR / "labeled"
DATASET_PATH = DATA_DIR / "dataset.parquet"
MODEL_DIR = PROJECT_ROOT / "models"
MODEL_PATH = MODEL_DIR / "probability_model.pkl"
NEW_MODEL_PATH = MODEL_DIR / "probability_model_new.pkl"

# --- Data ---
TIMEFRAME = "4h"
DEFAULT_CANDLES = 5000  # ~833 days for 4h

# --- Triple-barrier ---
LABELING_MODE = "structural"  # "atr" (legacy fixed ATR) | "structural" (TradeEngine TP/SL)
TP_ATR_MULT = 2.0       # TP = 2 × ATR (fallback when LABELING_MODE="atr" or TradeEngine fails)
SL_ATR_MULT = 1.0       # SL = 1 × ATR (fallback when LABELING_MODE="atr" or TradeEngine fails)
MAX_BARS = 12           # Max 12 candles (48h for 4h TF)
EXPIRED_LABEL = -1      # Timeout label (used in expected return as 0R)

# --- Training ---
MIN_SAMPLES = 100       # Minimum labeled setups to train
EMBARGO_BARS = 5        # Bars between train/test splits
HOLDOUT_PCT = 0.2       # 20% holdout for A/B comparison

# --- Model ---
N_ESTIMATORS = 300
MAX_DEPTH = 3
LEARNING_RATE = 0.05
MIN_CHILD_WEIGHT = 10
REG_ALPHA = 1.0
REG_LAMBDA = 5.0
SUBSAMPLE = 0.7
COLSAMPLE_BYTREE = 0.7
CALIBRATION_cv = 3

# --- Feature names (47 features matching SetupFeatures.to_vector()) ---
FEATURE_NAMES = [
    "setup_type", "has_bos", "has_sweep", "has_ob", "has_fvg",
    "has_displacement", "has_mss", "components_count", "mss_score",
    "mss_causality", "displacement_atr_ratio", "sweep_to_mss_bars",
    "ob_distance_pct", "fvg_size_pct", "sweep_reclaim_speed",
    "sweep_strength", "structure_trend", "structure_bos_aligned",
    "volume_ratio", "volume_delta_pct", "volume_above_avg", "atr_pct",
    "regime", "rsi", "adx", "ema_spread_pct", "dmi_diff",
    "macd_hist_pct", "mtf_aligned", "mtf_htf_count", "is_4h_aligned",
    "fear_greed", "funding_rate", "context_score", "rr_ratio",
    "sl_distance_pct", "tp_distance_pct", "session", "candle_close_pct",
    "is_reversal", "entry_armed", "nearest_support_pct",
    "nearest_resistance_pct", "htf_alignment_score",
    "premium_discount_score", "smt_divergence_score",
]
