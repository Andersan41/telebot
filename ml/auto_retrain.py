"""
Auto-retrain ML model on a schedule.

Checks if enough labeled data exists, runs the full pipeline:
  cache_ohlcv (--update) → triple_barrier → build_dataset → train_model

Designed to be called from scheduler/scheduler.py daily at 03:00 UTC.

Usage:
    python -m ml.auto_retrain              # full pipeline
    python -m ml.auto_retrain --dry-run    # check only, don't train
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml.config import LABELED_DIR, DATASET_PATH, MODEL_PATH, MIN_SAMPLES, TIMEFRAME


def count_labeled_setups() -> int:
    """Count total labeled setups (TP + SL) across all symbols."""
    total = 0
    for f in LABELED_DIR.glob(f"*_{TIMEFRAME}.parquet"):
        try:
            import pandas as pd
            df = pd.read_parquet(f)
            labeled = (df["label"] != -1).sum()
            total += labeled
        except Exception:
            continue
    return total


def run_step(name: str, cmd: list[str], timeout: int = 300) -> bool:
    """Run a pipeline step. Returns True on success."""
    logger.info(f"[STEP] {name}: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(Path(__file__).parent.parent),
        )
        if result.returncode != 0:
            logger.error(f"[FAIL] {name}: {result.stderr[:500]}")
            return False
        logger.info(f"[OK] {name}")
        if result.stdout.strip():
            for line in result.stdout.strip().split("\n")[-5:]:
                logger.info(f"  {line}")
        return True
    except subprocess.TimeoutExpired:
        logger.error(f"[TIMEOUT] {name} ({timeout}s)")
        return False
    except Exception as e:
        logger.error(f"[ERROR] {name}: {e}")
        return False


async def retrain_ml_model(dry_run: bool = False) -> bool:
    """Full retrain pipeline. Returns True if model was updated."""
    n_labeled = count_labeled_setups()
    logger.info(f"Labeled setups available: {n_labeled} (min required: {MIN_SAMPLES})")

    if n_labeled < MIN_SAMPLES:
        logger.info(f"Insufficient data ({n_labeled}/{MIN_SAMPLES}). Skipping retrain.")
        return False

    if dry_run:
        logger.info("Dry run — would retrain.")
        return True

    py = sys.executable

    # Step 1: Update OHLCV cache
    if not run_step("cache_ohlcv", [py, "-m", "ml.cache_ohlcv", "--update"]):
        return False

    # Step 2: Triple-barrier labeling
    if not run_step("triple_barrier", [py, "-m", "ml.triple_barrier"]):
        return False

    # Step 3: Build dataset
    if not run_step("build_dataset", [py, "-m", "ml.build_dataset"]):
        return False

    # Step 4: Train new model (save as _new for A/B comparison)
    if not run_step("train_model", [py, "-m", "ml.train_model", "--new-model"]):
        return False

    # Step 5: A/B compare and apply if better
    if not run_step("ab_compare", [py, "-m", "ml.ab_compare", "--apply"]):
        return False

    logger.info("Retrain pipeline complete. Model updated.")
    return True


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Auto-retrain ML model")
    parser.add_argument("--dry-run", action="store_true",
                        help="Check only, don't train")
    args = parser.parse_args()

    result = asyncio.run(retrain_ml_model(dry_run=args.dry_run))
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
