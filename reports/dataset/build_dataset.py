"""
build_dataset.py — Build Feature Dataset for Factor Importance Analysis

Loads backtest trades from raw_results_r6.json (full_new preset),
matches each trade to its snapshot from snapshot_cache,
recomputes factor strengths from IndicatorValues,
and saves the combined dataset.
"""
import sys
import os
import json
import pickle
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure project root is on path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import config
from indicators.engine import IndicatorValues
from strategy.signal_engine import (
    _strength_ema, _strength_macd, _strength_rsi,
    _strength_volume, _strength_adx, _strength_dmi,
    _strength_supertrend,
)

# ── Paths ──────────────────────────────────────────────────────────────
RAW_PATH = ROOT / "reports" / "abn" / "raw_results_r6.json"
CACHE_DIR = ROOT / "reports" / "abn" / "snapshot_cache"
OUT_DIR = ROOT / "reports" / "dataset"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PRESET = "full_new"


def make_signal_id(symbol: str, entry_ts: str) -> str:
    h = hashlib.md5(f"{symbol}_{entry_ts}".encode()).hexdigest()[:8]
    return f"{symbol.replace('/', '_')}_{h}"


def load_snapshots(symbol: str) -> dict:
    """Load snapshot list and index by df_index_i timestamp string."""
    fname = symbol.replace("/", "_") + f"_1h_3900_snapshots.pkl"
    path = CACHE_DIR / fname
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        data = pickle.load(f)
    # Index by timestamp string (truncated to minutes for matching)
    index = {}
    for snap in data:
        ts = snap.get("df_index_i", "")
        if ts:
            # Normalize: "2026-01-15 12:00:00+00:00" -> "2026-01-15 12:00:00"
            key = ts[:19]
            index[key] = snap
    return index


def extract_indicator_fields(ind: IndicatorValues) -> dict:
    """Extract all IndicatorValues fields as a flat dict."""
    return {
        "close": ind.close,
        "high": ind.high,
        "low": ind.low,
        "volume": ind.volume,
        "ema_fast": ind.ema_fast,
        "ema_slow": ind.ema_slow,
        "ema_trend": ind.ema_trend,
        "ema_fast_prev": ind.ema_fast_prev,
        "ema_slow_prev": ind.ema_slow_prev,
        "rsi": ind.rsi,
        "macd": ind.macd,
        "macd_signal": ind.macd_signal,
        "macd_hist": ind.macd_hist,
        "macd_hist_prev": ind.macd_hist_prev,
        "adx": ind.adx,
        "dmi_plus": ind.dmi_plus,
        "dmi_minus": ind.dmi_minus,
        "atr": ind.atr,
        "supertrend": ind.supertrend,
        "supertrend_direction": ind.supertrend_direction,
        "volume_sma": ind.volume_sma,
        "volume_delta_pct": ind.volume_delta_pct,
        "ema_bullish_cross": ind.ema_bullish_cross,
        "ema_bearish_cross": ind.ema_bearish_cross,
        "ema_bullish_alignment": ind.ema_bullish_alignment,
        "ema_bearish_alignment": ind.ema_bearish_alignment,
        "macd_bullish_cross": ind.macd_bullish_cross,
        "macd_bearish_cross": ind.macd_bearish_cross,
        "volume_above_avg": ind.volume_above_avg,
        "supertrend_bullish": ind.supertrend_bullish,
        "supertrend_bearish": ind.supertrend_bearish,
        "trend_is_strong": ind.trend_is_strong,
    }


def compute_factors_from_snapshot(snap: dict, direction: str) -> dict:
    """Recompute factor strengths from snapshot's IndicatorValues."""
    ind = snap["ind"]
    regime_obj = snap.get("regime_obj")
    structure = snap.get("structure")
    valid_sweeps = snap.get("valid_sweeps", [])
    valid_obs = snap.get("valid_obs", [])

    # Direction for strength functions
    d = direction.lower()  # "buy" or "sell"

    # Factor strengths
    ema_str = _strength_ema(ind, d)
    macd_str = _strength_macd(ind, d)
    rsi_str = _strength_rsi(ind, d)
    vol_str = _strength_volume(ind, d)
    adx_str = _strength_adx(ind)
    dmi_str = _strength_dmi(ind, d)
    st_str = _strength_supertrend(ind, d)

    # EMA spread
    if ind.ema_slow and ind.ema_slow > 0:
        if d == "buy":
            ema_spread_pct = (ind.ema_fast - ind.ema_slow) / ind.ema_slow * 100
        else:
            ema_spread_pct = (ind.ema_slow - ind.ema_fast) / ind.ema_fast * 100
    else:
        ema_spread_pct = 0.0

    # EMA slope check
    current_spread = ind.ema_fast - ind.ema_slow
    prev_spread = ind.ema_fast_prev - ind.ema_slow_prev
    if d == "buy":
        ema_slope_ok = current_spread > 0 and current_spread >= prev_spread * 0.95
    else:
        ema_slope_ok = current_spread < 0 and abs(current_spread) >= abs(prev_spread) * 0.95

    # MACD histogram normalized
    macd_hist_norm = (ind.macd_hist / ind.close * 100) if ind.close > 0 else 0.0

    # Volume ratio
    vol_ratio = ind.volume / ind.volume_sma if ind.volume_sma > 0 else 1.0

    # Sweep strength
    sweep_strength = 0.0
    if valid_sweeps:
        sweep_strength = max(sw.strength for sw in valid_sweeps)

    # OB valid
    ob_valid = any(ob.is_valid for ob in valid_obs) if valid_obs else False

    # Structure
    has_bos = structure.last_bos is not None if structure else False
    bos_type = structure.last_bos.type if structure and structure.last_bos else None
    structure_trend = structure.trend if structure else "ranging"
    structure_breaks = structure.structure_breaks if structure else 0

    # Signal score: count factors with positive strength aligned with direction
    aligned_count = sum(1 for s in [st_str, ema_str, macd_str, rsi_str, vol_str, adx_str, dmi_str] if s > 0)

    return {
        # Factor strengths
        "ema_strength": ema_str,
        "ema_spread_pct": round(ema_spread_pct, 4),
        "ema_slope_ok": ema_slope_ok,
        "adx_value": ind.adx,
        "adx_strength": adx_str,
        "supertrend_strength": st_str,
        "macd_hist_normalized": round(macd_hist_norm, 6),
        "rsi_value": ind.rsi,
        "rsi_strength": rsi_str,
        "volume_ratio": round(vol_ratio, 4),
        "volume_delta": ind.volume_delta_pct,
        "dmi_strength": dmi_str,
        # Structure
        "has_bos": has_bos,
        "bos_type": bos_type,
        "has_sweep": len(valid_sweeps) > 0,
        "sweep_strength": sweep_strength,
        "has_ob": len(valid_obs) > 0,
        "ob_valid": ob_valid,
        "structure_trend": structure_trend,
        "structure_breaks": structure_breaks,
        # Regime
        "regime": regime_obj.regime if regime_obj else None,
        "regime_confidence": regime_obj.confidence if regime_obj else None,
        "atr_percentile": regime_obj.atr_percentile if regime_obj else None,
        "ema_spread_trend": regime_obj.ema_spread_trend if regime_obj else None,
        # Signal quality
        "signal_score": aligned_count,
        "score_verdict": "strong" if aligned_count >= 6 else ("moderate" if aligned_count >= 4 else "weak"),
        # Raw indicator values for reference
        **extract_indicator_fields(ind),
    }


def build_backtest_dataset() -> pd.DataFrame:
    """Build the backtest feature dataset."""
    print(f"Loading {RAW_PATH}...")
    with open(RAW_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # Filter full_new preset
    records = [r for r in raw if r.get("preset") == PRESET]
    print(f"Found {len(records)} records for preset '{PRESET}'")

    # Collect all trades
    all_trades = []
    for rec in records:
        symbol = rec["symbol"]
        for t in rec.get("trades", []):
            t["_source_symbol"] = symbol
            all_trades.append(t)

    print(f"Total trades: {len(all_trades)}")

    # Load all snapshots indexed by symbol
    symbols = set(t["_source_symbol"] for t in all_trades)
    print(f"Loading snapshots for {len(symbols)} symbols...")
    snapshots_by_symbol = {}
    for sym in symbols:
        snaps = load_snapshots(sym)
        snapshots_by_symbol[sym] = snaps
        print(f"  {sym}: {len(snaps)} snapshots")

    # Build rows
    rows = []
    matched = 0
    unmatched = 0

    for t in all_trades:
        symbol = t["_source_symbol"]
        direction = t["direction"]  # "BUY" or "SELL"
        entry_ts = t["entry_timestamp"][:19]  # "2026-01-25 19:00:00"

        # Parse timestamps for hours_in_trade
        try:
            entry_dt = datetime.fromisoformat(t["entry_timestamp"])
            exit_dt = datetime.fromisoformat(t["exit_timestamp"]) if t.get("exit_timestamp") else None
            hours_in_trade = (exit_dt - entry_dt).total_seconds() / 3600.0 if exit_dt else None
        except Exception:
            hours_in_trade = None

        # Result mapping
        exit_reason = t.get("exit_reason", "")
        result_map = {"tp": "TP", "sl": "SL", "eob": "EOB"}
        result = result_map.get(exit_reason, exit_reason.upper())

        # Base row from raw data
        row = {
            "signal_id": make_signal_id(symbol, t["entry_timestamp"]),
            "symbol": symbol,
            "timeframe": "1h",
            "direction": direction,
            "created_at": t["entry_timestamp"],
            "source": "backtest",
            # Target
            "result": result,
            "pnl_pct": t["pnl_pct"],
            "net_pnl_pct": t["net_pnl_pct"],
            "win": t["pnl_pct"] > 0,
            "hours_in_trade": hours_in_trade,
            # Trade mechanics
            "sl_source": t.get("sl_source", "atr"),
            "entry_price": t["entry_price"],
            "exit_price": t.get("exit_price"),
            "rr": t.get("rr", 0.0),
            # Enriched fields (from new BacktestTrade format)
            "signal_score": t.get("signal_score", 0),
            "confidence": t.get("confidence", 0.0),
            "verdict": t.get("verdict", ""),
            "confidence_v2_score": t.get("confidence_v2_score", 0.0),
            "confidence_v2_quality": t.get("confidence_v2_quality", ""),
            "sl_price": t.get("sl_price", t.get("sl", 0.0)),
            "tp_price": t.get("tp_price", t.get("tp", 0.0)),
            "sl_distance_pct": t.get("sl_distance_pct", 0.0),
            "theoretical_rr": t.get("theoretical_rr", 0.0),
        }

        # Extract factor strengths from JSON (enriched format)
        fs = t.get("factor_strengths", {})
        if fs:
            for fname in ["Supertrend", "EMA", "MACD", "RSI", "Volume", "ADX", "DMI"]:
                row[f"factor_{fname.lower()}_strength"] = fs.get(fname, 0.0)
            row["factor_buy_score"] = fs.get("BUY", 0.0)
            row["factor_sell_score"] = fs.get("SELL", 0.0)

        # Match snapshot
        snap_index = snapshots_by_symbol.get(symbol, {})
        snap = snap_index.get(entry_ts)

        if snap is not None:
            matched += 1
            factors = compute_factors_from_snapshot(snap, direction)
            row.update(factors)
        else:
            unmatched += 1
            # Fill with NaN for all factor columns
            factor_cols = [
                "ema_strength", "ema_spread_pct", "ema_slope_ok",
                "adx_value", "adx_strength", "supertrend_strength",
                "macd_hist_normalized", "rsi_value", "rsi_strength",
                "volume_ratio", "volume_delta", "dmi_strength",
                "has_bos", "bos_type", "has_sweep", "sweep_strength",
                "has_ob", "ob_valid", "structure_trend", "structure_breaks",
                "regime", "regime_confidence", "atr_percentile", "ema_spread_trend",
                "signal_score", "score_verdict",
            ]
            for col in factor_cols:
                row[col] = np.nan

        rows.append(row)

    print(f"\nMatched: {matched}/{len(all_trades)} ({matched/len(all_trades)*100:.1f}%)")
    print(f"Unmatched: {unmatched}")

    df = pd.DataFrame(rows)
    return df


def main():
    df = build_backtest_dataset()

    # Save
    parquet_path = OUT_DIR / "backtest_features.parquet"
    csv_path = OUT_DIR / "backtest_features.csv"

    df.to_parquet(parquet_path, index=False)
    df.to_csv(csv_path, index=False)

    print(f"\nSaved: {parquet_path} ({parquet_path.stat().st_size // 1024}KB)")
    print(f"Saved: {csv_path} ({csv_path.stat().st_size // 1024}KB)")
    print(f"Shape: {df.shape[0]} rows x {df.shape[1]} columns")

    # Quick stats
    print(f"\n--- Quick Stats ---")
    print(f"Win rate: {df['win'].mean()*100:.1f}%")
    print(f"Avg PnL: {df['pnl_pct'].mean():.4f}%")
    print(f"Avg Net PnL: {df['net_pnl_pct'].mean():.4f}%")
    print(f"\nDirection distribution:")
    print(df["direction"].value_counts().to_string())
    print(f"\nResult distribution:")
    print(df["result"].value_counts().to_string())
    print(f"\nRegime distribution:")
    print(df["regime"].value_counts().dropna().to_string())
    print(f"\nNaN counts per column:")
    nan_counts = df.isnull().sum()
    nan_cols = nan_counts[nan_counts > 0]
    if len(nan_cols) > 0:
        for col, cnt in nan_cols.items():
            print(f"  {col}: {cnt} ({cnt/len(df)*100:.1f}%)")
    else:
        print("  No NaN columns!")


if __name__ == "__main__":
    main()
