"""
market_structure/diagnostic.py — MSS Funnel Diagnostics.

Tracks every stage of the MSS pipeline:
  Sweep detected → Sweep valid → CHoCH detected →
  CHoCH + sweep in window → Displacement >= 1 ATR →
  Reclaim <= 2 → MSS final

Usage:
    from market_structure.diagnostic import diagnose_mss_funnel
    stats = diagnose_mss_funnel(df, sweeps, atr_value)
    stats.print_summary()
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from loguru import logger


@dataclass
class MSSFunnelStats:
    """Tracks MSS pipeline funnel statistics."""

    total_candles: int = 0

    # Stage 1: Sweep detection
    sweep_detected: int = 0       # total sweeps found
    sweep_valid: int = 0          # passes is_valid (volume > 1.5, reclaim <= 3)

    # Stage 2: CHoCH detection
    choch_detected: int = 0       # total CHoCH found

    # Stage 3: CHoCH + sweep in causal window
    choch_with_sweep_in_window: int = 0  # CHoCH has matching sweep within 5 bars

    # Stage 4: Displacement check
    displacement_pass: int = 0    # displacement_atr >= 1.0

    # Stage 5: Reclaim check
    reclaim_pass: int = 0         # reclaim_bars <= 2

    # Stage 6: MSS final
    mss_final: int = 0            # all three conditions met

    # Detailed tracking per CHoCH
    choch_details: list[dict] = field(default_factory=list)

    def record_choch(
        self,
        choch_type: str,
        choch_candle_index: int,
        has_sweep_reference: bool,
        bars_since_sweep: int,
        displacement_atr: float,
        reclaim_bars: int,
        is_mss: bool,
    ):
        """Record a single CHoCH classification result."""
        self.choch_details.append({
            "type": choch_type,
            "candle_index": choch_candle_index,
            "has_sweep": has_sweep_reference,
            "bars_since_sweep": bars_since_sweep,
            "displacement_atr": round(displacement_atr, 3),
            "reclaim_bars": reclaim_bars,
            "is_mss": is_mss,
        })

    def print_summary(self):
        """Print funnel summary as a table."""
        lines = [
            "",
            "=== MSS FUNNEL DIAGNOSTICS ===",
            f"  Total candles:          {self.total_candles}",
            "",
            f"  Sweep detected:         {self.sweep_detected}",
            f"  Sweep valid:            {self.sweep_valid}",
            "",
            f"  CHoCH detected:         {self.choch_detected}",
            f"  CHoCH + sweep in window:{self.choch_with_sweep_in_window}",
            "",
            f"  Displacement >= 1 ATR:  {self.displacement_pass}",
            f"  Reclaim <= 2:           {self.reclaim_pass}",
            "",
            f"  MSS final:              {self.mss_final}",
            "",
        ]

        # Drop-off analysis
        if self.choch_detected > 0:
            pct_sweep = self.choch_with_sweep_in_window / self.choch_detected * 100
            lines.append(f"  Drop: CHoCH -> CHoCH+sweep: {pct_sweep:.1f}%")

        if self.choch_with_sweep_in_window > 0:
            pct_disp = self.displacement_pass / self.choch_with_sweep_in_window * 100
            lines.append(f"  Drop: CHoCH+sweep -> displacement: {pct_disp:.1f}%")

        if self.displacement_pass > 0:
            pct_reclaim = self.reclaim_pass / self.displacement_pass * 100
            lines.append(f"  Drop: displacement -> reclaim: {pct_reclaim:.1f}%")

        if self.reclaim_pass > 0:
            pct_mss = self.mss_final / self.reclaim_pass * 100
            lines.append(f"  Drop: reclaim -> MSS: {pct_mss:.1f}%")

        lines.append("")

        # Show failing CHoCH details (first 10)
        fails = [d for d in self.choch_details if not d["is_mss"]]
        if fails:
            lines.append("=== REJECTED CHoCH (up to 10) ===")
            for d in fails[:10]:
                lines.append(
                    f"  {d['type']:8s} idx={d['candle_index']:4d} "
                    f"sweep={d['has_sweep']} "
                    f"bars_since={d['bars_since_sweep']:2d} "
                    f"disp={d['displacement_atr']:.2f} "
                    f"reclaim={d['reclaim_bars']}"
                )
            lines.append("")

        # Show MSS passes
        passes = [d for d in self.choch_details if d["is_mss"]]
        if passes:
            lines.append("=== MSS PASSED ===")
            for d in passes:
                lines.append(
                    f"  {d['type']:8s} idx={d['candle_index']:4d} "
                    f"bars_since={d['bars_since_sweep']:2d} "
                    f"disp={d['displacement_atr']:.2f} "
                    f"reclaim={d['reclaim_bars']}"
                )
            lines.append("")

        summary = "\n".join(lines)
        print(summary)
        logger.info(summary)
        return summary


def diagnose_mss_funnel(
    df: pd.DataFrame,
    sweeps: list,
    atr_value: float,
    lookback: int = 50,
    swing_window: int = 5,
    max_causal_bars: int = 5,
) -> MSSFunnelStats:
    """
    Run full MSS pipeline on a DataFrame and collect funnel stats.

    This is a diagnostic tool — it instruments classify_choch() to record
    every stage of the funnel without modifying the production code path.

    Args:
        df: OHLCV DataFrame
        sweeps: list of SweepEvent from detect_sweeps()
        atr_value: current ATR value
        lookback: swing point lookback
        swing_window: swing point window
        max_causal_bars: causal window for sweep-CHoCH matching

    Returns:
        MSSFunnelStats with full funnel breakdown
    """
    from market_structure.structure import (
        _find_swing_points,
        _detect_bos_choch,
        calc_causality,
    )
    from liquidity.candle_quality import analyze_last_candle

    stats = MSSFunnelStats(total_candles=len(df))

    # Count sweeps
    stats.sweep_detected = len(sweeps)
    stats.sweep_valid = sum(1 for s in sweeps if s.is_valid)

    # Find swing points and detect CHoCH
    swings = _find_swing_points(df, lookback=lookback, swing_window=swing_window)
    last_bos, last_choch, breaks = _detect_bos_choch(swings)

    if last_choch is not None:
        stats.choch_detected = 1  # we only get the LAST choch

        # --- Instrument the MSS classification inline ---
        # Find matching sweep (OPPOSITE direction)
        matching_sweep = None
        bars_since = 999

        for s in sweeps:
            if not s.is_valid:
                continue
            sweep_dir = "buy" if s.type == "bullish" else "sell"
            choch_dir = "buy" if last_choch.type == "bullish" else "sell"
            # MSS requires OPPOSITE directions
            if sweep_dir == choch_dir:
                continue

            if last_choch.candle_index >= 0 and s.candle_index >= 0:
                delta = last_choch.candle_index - s.candle_index
            else:
                delta = 0
            if 0 <= delta <= max_causal_bars:
                if matching_sweep is None or delta < bars_since:
                    matching_sweep = s
                    bars_since = delta

        has_sweep_ref = matching_sweep is not None
        if has_sweep_ref:
            stats.choch_with_sweep_in_window = 1

        # Displacement: max body/ATR between sweep and CHoCH (ICT: displacement leg)
        disp_atr = 0.0
        if has_sweep_ref and atr_value and atr_value > 0:
            start = max(0, matching_sweep.candle_index)
            end = min(last_choch.candle_index + 1, len(df))
            for idx in range(start, end):
                candle = df.iloc[idx]
                body = abs(float(candle["close"]) - float(candle["open"]))
                disp = body / atr_value
                if disp > disp_atr:
                    disp_atr = disp
        elif atr_value and atr_value > 0 and last_choch.candle_index < len(df):
            # Fallback: measure at CHoCH candle if no sweep found
            candle_quality = analyze_last_candle(df, atr_value=atr_value)
            if candle_quality and hasattr(candle_quality, 'body_atr_ratio'):
                disp_atr = candle_quality.body_atr_ratio

        displacement_pass = disp_atr >= 1.0
        if displacement_pass:
            stats.displacement_pass = 1

        # Reclaim: production uses first valid sweep, but MSS should use matching sweep
        reclaim_production = 0
        if sweeps:
            valid_sw = [s for s in sweeps if s.is_valid]
            if valid_sw:
                reclaim_production = valid_sw[0].reclaim_candles

        reclaim_matching = matching_sweep.reclaim_candles if matching_sweep else 999

        # Use PRODUCTION logic (first valid sweep) for funnel stats
        reclaim_bars = reclaim_production
        reclaim_pass = reclaim_bars <= 2
        if reclaim_pass:
            stats.reclaim_pass = 1

        # MSS = all three
        is_mss = has_sweep_ref and displacement_pass and reclaim_pass
        if is_mss:
            stats.mss_final = 1

        stats.record_choch(
            choch_type=last_choch.type,
            choch_candle_index=last_choch.candle_index,
            has_sweep_reference=has_sweep_ref,
            bars_since_sweep=bars_since if has_sweep_ref else 999,
            displacement_atr=disp_atr,
            reclaim_bars=reclaim_bars,
            is_mss=is_mss,
        )

        # Log comparison if mismatch
        if matching_sweep and reclaim_production != reclaim_matching:
            logger.warning(
                f"RECLAIM MISMATCH: production={reclaim_production} "
                f"(first valid sweep) vs matching={reclaim_matching} "
                f"(sweep linked to CHoCH)"
            )

    return stats


def diagnose_mss_funnel_full(
    df: pd.DataFrame,
    atr_value: float,
    lookback: int = 50,
    swing_window: int = 5,
    max_causal_bars: int = 5,
) -> MSSFunnelStats:
    """
    Run diagnostics using the FULL sweep list (not just the last CHoCH).

    This version iterates through all swing points to find ALL potential
    CHoCH-like structure breaks, giving a complete picture.
    """
    from market_structure.structure import (
        _find_swing_points,
        calc_causality,
    )
    from liquidity.sweep import detect_sweeps
    from liquidity.candle_quality import analyze_last_candle

    stats = MSSFunnelStats(total_candles=len(df))

    # Detect sweeps
    all_sweeps = detect_sweeps(df, lookback=lookback)
    stats.sweep_detected = len(all_sweeps)
    stats.sweep_valid = sum(1 for s in all_sweeps if s.is_valid)

    # Find swing points
    swings = _find_swing_points(df, lookback=lookback, swing_window=swing_window)
    highs = [s for s in swings if s.type == "high"]
    lows = [s for s in swings if s.type == "low"]

    # Iterate through ALL swing point pairs to find structure breaks
    choch_count = 0
    for i in range(3, len(swings)):
        # Need at least 2 highs and 2 lows in the window
        window_highs = [s for s in swings[:i+1] if s.type == "high"]
        window_lows = [s for s in swings[:i+1] if s.type == "low"]

        if len(window_highs) < 2 or len(window_lows) < 2:
            continue

        last_high = window_highs[-1]
        prev_high = window_highs[-2]
        last_low = window_lows[-1]
        prev_low = window_lows[-2]

        bullish_structure = prev_high.price > prev_low.price

        # Detect CHoCH — use the swing point's candle_index, not the loop index
        choch = None
        if last_high.price > prev_high.price and not bullish_structure:
            choch = type('CHoCH', (), {
                'type': 'bullish',
                'level': last_high.price,
                'candle_index': last_high.candle_index,
            })()
        elif last_low.price < prev_low.price and bullish_structure:
            choch = type('CHoCH', (), {
                'type': 'bearish',
                'level': last_low.price,
                'candle_index': last_low.candle_index,
            })()

        if choch is None:
            continue

        choch_count += 1
        stats.choch_detected = choch_count

        # Find matching sweep (OPPOSITE direction — bearish sweep for bullish CHoCH)
        matching_sweep = None
        bars_since = 999

        for s in all_sweeps:
            if not s.is_valid:
                continue
            sweep_dir = "buy" if s.type == "bullish" else "sell"
            choch_dir = "buy" if choch.type == "bullish" else "sell"
            # MSS requires OPPOSITE directions
            if sweep_dir == choch_dir:
                continue

            delta = choch.candle_index - s.candle_index
            if 0 <= delta <= max_causal_bars:
                if matching_sweep is None or delta < bars_since:
                    matching_sweep = s
                    bars_since = delta

        has_sweep_ref = matching_sweep is not None

        # Displacement: max body/ATR between sweep and CHoCH (ICT: displacement leg)
        disp_atr = 0.0
        if has_sweep_ref and atr_value and atr_value > 0:
            start = max(0, matching_sweep.candle_index)
            end = min(choch.candle_index + 1, len(df))
            for idx in range(start, end):
                candle = df.iloc[idx]
                body = abs(float(candle["close"]) - float(candle["open"]))
                disp = body / atr_value
                if disp > disp_atr:
                    disp_atr = disp
        elif atr_value and atr_value > 0 and choch.candle_index < len(df):
            # Fallback: measure at CHoCH candle if no sweep found
            candle = df.iloc[choch.candle_index]
            body = abs(float(candle["close"]) - float(candle["open"]))
            disp_atr = body / atr_value

        # Reclaim from matching sweep
        reclaim_bars = matching_sweep.reclaim_candles if matching_sweep else 999

        # MSS classification
        is_mss = has_sweep_ref and disp_atr >= 1.0 and reclaim_bars <= 2

        stats.record_choch(
            choch_type=choch.type,
            choch_candle_index=choch.candle_index,
            has_sweep_reference=has_sweep_ref,
            bars_since_sweep=bars_since if has_sweep_ref else 999,
            displacement_atr=disp_atr,
            reclaim_bars=reclaim_bars,
            is_mss=is_mss,
        )

    # Recompute aggregates from details
    stats.choch_with_sweep_in_window = sum(1 for d in stats.choch_details if d["has_sweep"])
    stats.displacement_pass = sum(1 for d in stats.choch_details if d["displacement_atr"] >= 1.0)
    stats.reclaim_pass = sum(1 for d in stats.choch_details if d["reclaim_bars"] <= 2)
    stats.mss_final = sum(1 for d in stats.choch_details if d["is_mss"])

    return stats
