"""
scripts/gate_simulator.py — Gate Simulation Toolkit

Virtual filter application to historical trades. Determines which gates
improve expectancy vs merely reducing trade count.

Usage:
    python scripts/gate_simulator.py [--db data/signals.db] [--days 90]
    python scripts/gate_simulator.py --sweep
    python scripts/gate_simulator.py --combo "bos_age_3,adx_25,trend_regime"
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Optional


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "signals.db"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"

# Regime numeric → human-readable mapping
REGIME_MAP = {
    "1": "trend", "1.0": "trend",
    "0.5": "expansion",
    "-0.5": "range",
    "-1": "compression", "-1.0": "compression",
    "0": "unknown", "0.0": "unknown",
}


# ══════════════════════════════════════════════════════════════════
# Data loading (reuse from scenario_forensics)
# ══════════════════════════════════════════════════════════════════

def _get_available_trace_columns(conn: sqlite3.Connection) -> set[str]:
    """Get column names that actually exist in decision_traces."""
    cursor = conn.execute("PRAGMA table_info(decision_traces)")
    return {row[1] for row in cursor.fetchall()}


def load_trades_for_simulation(db_path: str, days: int = 90) -> list[dict]:
    """Load resolved trades as flat dicts for gate simulation."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    traces_cols = _get_available_trace_columns(conn)

    select_parts = [
        "s.id as signal_id", "s.symbol", "s.timeframe",
        "s.signal_type as direction", "s.close_price as entry_price",
        "s.sl", "s.tp", "s.created_at", "s.mfe_pct", "s.mae_pct",
        "o.status as outcome", "o.pnl_pct", "o.closed_at",
    ]

    # Add trace columns that actually exist
    trace_fields = [
        "adx", "rsi", "regime", "atr_pct", "rr_ratio",
        "has_bos", "has_sweep", "has_ob", "ob_distance_pct",
        "btc_trend_strength", "mtf_alignment_score",
        "sl_distance_pct", "tp_distance_pct",
        "supertrend_direction", "ema_spread_pct",
        "volume_ratio", "confidence",
    ]
    for field in trace_fields:
        if field in traces_cols:
            select_parts.append(f"dt.{field}")

    # Gate columns (always select if they exist)
    gate_cols = [c for c in traces_cols if c.startswith("gate_")]
    for col in gate_cols:
        select_parts.append(f"dt.{col}")

    # hypothesis_snapshot — may or may not exist
    if "hypothesis_snapshot" in traces_cols:
        select_parts.append("dt.hypothesis_snapshot")

    sql = f"""
        SELECT {', '.join(select_parts)}
        FROM signals s
        JOIN signal_outcomes o ON o.signal_id = s.id
        LEFT JOIN decision_traces dt ON dt.signal_id = s.id
        WHERE o.status IN ('HIT_TP', 'HIT_SL', 'EXPIRED')
          AND s.created_at > ?
        ORDER BY s.created_at
    """
    rows = conn.execute(sql, (cutoff,)).fetchall()
    conn.close()

    trades = []
    for row in rows:
        r = dict(row)
        t = _enrich_trade(r)
        if t is not None:
            trades.append(t)

    return trades


def _enrich_trade(r: dict) -> Optional[dict]:
    """Enrich raw DB row with computed fields."""
    try:
        entry = r["entry_price"] or 0.0
        sl = r["sl"]
        tp = r["tp"]
        direction = r["direction"] or "BUY"
        pnl_pct = r["pnl_pct"] or 0.0
        outcome = r["outcome"] or ""

        # R-multiple
        pnl_r = 0.0
        if sl and entry and entry != sl:
            risk = abs(entry - sl)
            if outcome == "HIT_TP" and tp:
                reward = (tp - entry) if direction == "BUY" else (entry - tp)
                pnl_r = reward / risk
            elif outcome == "HIT_SL":
                pnl_r = -1.0
            elif pnl_pct != 0:
                price_change = pnl_pct / 100.0 * entry
                pnl_r = price_change / risk

        # Structure trend
        st_dir = r.get("supertrend_direction")
        ema_spread = r.get("ema_spread_pct") or 0.0
        if st_dir == 1 and ema_spread > 0:
            structure_trend = "bullish"
        elif st_dir == -1 and ema_spread < 0:
            structure_trend = "bearish"
        else:
            structure_trend = "ranging"

        structure_alignment = (structure_trend == ("bullish" if direction == "BUY" else "bearish"))

        # ADX / ATR
        adx = r.get("adx")
        atr_pct = r.get("atr_pct") or 0.0
        ob_dist_pct = r.get("ob_distance_pct") or 0.0
        ob_distance_atr = ob_dist_pct / atr_pct if atr_pct > 0 else None

        # Hypothesis (may not exist in older DBs)
        h_snap = {}
        h_raw = r.get("hypothesis_snapshot")
        if h_raw:
            try:
                h_snap = json.loads(h_raw)
            except Exception:
                pass

        scenario_type = h_snap.get("narrative_type", "")
        scenario_confidence = h_snap.get("confidence", 0.0)
        scenario_score = h_snap.get("quality", 0.0)
        decay_factor = h_snap.get("decay_factor", 0.0)

        created_bar = h_snap.get("created_at_bar")
        current_bar = h_snap.get("current_bar")
        bos_age_bars = None
        if created_bar is not None and current_bar is not None:
            bos_age_bars = current_bar - created_bar

        sweep_present = bool(r["has_sweep"])
        ob_present = bool(r["has_ob"])
        fvg_present = "fvg" in scenario_type.lower() if scenario_type else False

        return {
            "signal_id": r["signal_id"],
            "symbol": r["symbol"],
            "timeframe": r["timeframe"],
            "direction": direction,
            "outcome": outcome,
            "pnl_pct": pnl_pct,
            "pnl_r": pnl_r,
            "entry_price": entry,
            "sl": sl,
            "tp": tp,
            "adx": adx,
            "rsi": r.get("rsi"),
            "regime": REGIME_MAP.get(r.get("regime") or "", r.get("regime") or ""),
            "atr_pct": atr_pct,
            "rr_ratio": r.get("rr_ratio"),
            "has_bos": bool(r.get("has_bos")),
            "has_sweep": sweep_present,
            "has_ob": ob_present,
            "ob_distance_atr": ob_distance_atr,
            "structure_trend": structure_trend,
            "structure_alignment": structure_alignment,
            "bos_age_bars": bos_age_bars,
            "sweep_present": sweep_present,
            "ob_present": ob_present,
            "fvg_present": fvg_present,
            "scenario_type": scenario_type,
            "scenario_confidence": scenario_confidence,
            "scenario_score": scenario_score,
            "decay_factor": decay_factor,
            "mtf_alignment": r.get("mtf_alignment_score"),
            "btc_correlation": r.get("btc_trend_strength"),
            "volume_ratio": r.get("volume_ratio"),
            "confidence": r.get("confidence"),
            # Gate columns (may or may not exist)
            "gate_cooldown": r.get("gate_cooldown"),
            "gate_portfolio_risk": r.get("gate_portfolio_risk"),
            "gate_btc_global_trend": r.get("gate_btc_global_trend"),
            "gate_indicators": r.get("gate_indicators"),
            "gate_confirm_tf": r.get("gate_confirm_tf"),
            "gate_signal_engine": r.get("gate_signal_engine"),
            "gate_distance_filter": r.get("gate_distance_filter"),
            "gate_tp_path": r.get("gate_tp_path"),
            "gate_mtf_alignment": r.get("gate_mtf_alignment"),
            "gate_btc_correlation": r.get("gate_btc_correlation"),
            "gate_eth_correlation": r.get("gate_eth_correlation"),
            "gate_volatility": r.get("gate_volatility"),
            "gate_context_timeout": r.get("gate_context_timeout"),
            "gate_context_block": r.get("gate_context_block"),
            "gate_context_min_verdict": r.get("gate_context_min_verdict"),
            "gate_news": r.get("gate_news"),
            "gate_sl_distance": r.get("gate_sl_distance"),
            "gate_rr_guard": r.get("gate_rr_guard"),
            "gate_no_trade_zones": r.get("gate_no_trade_zones"),
            "gate_dynamic_risk": r.get("gate_dynamic_risk"),
            "gate_confidence_v2": r.get("gate_confidence_v2"),
            "gate_dedup": r.get("gate_dedup"),
            "gate_compression_block": r.get("gate_compression_block"),
        }
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════
# Predefined filter functions
# ══════════════════════════════════════════════════════════════════

FILTERS: dict[str, Callable[[dict], bool]] = {
    # BOS age
    "bos_age_3": lambda t: (t.get("bos_age_bars") or 999) <= 3,
    "bos_age_5": lambda t: (t.get("bos_age_bars") or 999) <= 5,
    "bos_age_10": lambda t: (t.get("bos_age_bars") or 999) <= 10,

    # ADX
    "adx_18": lambda t: (t.get("adx") or 0) > 18,
    "adx_25": lambda t: (t.get("adx") or 0) > 25,
    "adx_30": lambda t: (t.get("adx") or 0) > 30,

    # OB distance
    "ob_dist_1atr": lambda t: (t.get("ob_distance_atr") or 99) < 1.0,
    "ob_dist_2atr": lambda t: (t.get("ob_distance_atr") or 99) < 2.0,
    "ob_dist_3atr": lambda t: (t.get("ob_distance_atr") or 99) < 3.0,

    # R:R
    "rr_1.5": lambda t: (t.get("rr_ratio") or 0) >= 1.5,
    "rr_2": lambda t: (t.get("rr_ratio") or 0) >= 2.0,
    "rr_2.5": lambda t: (t.get("rr_ratio") or 0) >= 2.5,
    "rr_3": lambda t: (t.get("rr_ratio") or 0) >= 3.0,

    # Regime
    "trend_regime": lambda t: t.get("regime") == "trend",
    "expansion_regime": lambda t: t.get("regime") == "expansion",
    "no_compression": lambda t: t.get("regime") != "compression",
    "no_range": lambda t: t.get("regime") != "range",

    # MTF
    "mtf_aligned": lambda t: (t.get("mtf_alignment") or 0) > 0.7,
    "mtf_strong": lambda t: (t.get("mtf_alignment") or 0) > 0.85,

    # Structure
    "structure_aligned": lambda t: t.get("structure_alignment", False),
    "counter_trend": lambda t: not t.get("structure_alignment", True),

    # Components
    "sweep_present": lambda t: t.get("sweep_present", False),
    "ob_present": lambda t: t.get("ob_present", False),
    "fvg_present": lambda t: t.get("fvg_present", False),
    "has_bos": lambda t: t.get("has_bos", False),

    # Scenario quality
    "high_confidence": lambda t: (t.get("scenario_confidence") or 0) > 0.6,
    "strong_scenario": lambda t: (t.get("scenario_score") or 0) > 50,
    "fresh_scenario": lambda t: (t.get("decay_factor") or 0) > 0.7,

    # Volatility
    "no_extreme_vol": lambda t: (t.get("atr_pct") or 0) < 3.0,
    "moderate_vol": lambda t: 0.5 < (t.get("atr_pct") or 0) < 2.5,

    # BTC correlation
    "btc_supportive": lambda t: (t.get("btc_correlation") or 0) > 0.98,

    # Volume
    "volume_above_avg": lambda t: (t.get("volume_ratio") or 0) > 1.0,
    "volume_strong": lambda t: (t.get("volume_ratio") or 0) > 1.5,
}

# DB gate column names → human-readable
DB_GATE_MAP = {
    "gate_cooldown": "cooldown",
    "gate_portfolio_risk": "portfolio_risk",
    "gate_btc_global_trend": "btc_global_trend",
    "gate_indicators": "indicators",
    "gate_confirm_tf": "confirm_tf",
    "gate_signal_engine": "signal_engine",
    "gate_distance_filter": "distance_filter",
    "gate_tp_path": "tp_path",
    "gate_mtf_alignment": "mtf_alignment",
    "gate_btc_correlation": "btc_correlation",
    "gate_eth_correlation": "eth_correlation",
    "gate_volatility": "volatility",
    "gate_context_timeout": "context_timeout",
    "gate_context_block": "context_block",
    "gate_context_min_verdict": "context_min_verdict",
    "gate_news": "news",
    "gate_sl_distance": "sl_distance",
    "gate_rr_guard": "rr_guard",
    "gate_no_trade_zones": "no_trade_zones",
    "gate_dynamic_risk": "dynamic_risk",
    "gate_confidence_v2": "confidence_v2",
    "gate_dedup": "dedup",
    "gate_compression_block": "compression_block",
    # Structural gates (Scenario Forensics)
    "gate_structure_alignment": "structure_alignment",
    "gate_sweep_required": "sweep_required",
    "gate_regime_block": "regime_block",
}


# ══════════════════════════════════════════════════════════════════
# GateResult
# ══════════════════════════════════════════════════════════════════

@dataclass
class GateResult:
    """Result of applying a filter to trades."""
    filter_name: str = ""
    trades_before: int = 0
    trades_after: int = 0
    trades_removed: int = 0
    wr_before: float = 0.0
    wr_after: float = 0.0
    pf_before: float = 0.0
    pf_after: float = 0.0
    expectancy_before: float = 0.0
    expectancy_after: float = 0.0
    delta_expectancy: float = 0.0
    delta_wr: float = 0.0
    avg_pnl_before: float = 0.0
    avg_pnl_after: float = 0.0
    is_positive_edge: bool = False
    diagnosis: str = ""

    def to_dict(self) -> dict:
        return {
            "filter": self.filter_name,
            "trades_before": self.trades_before,
            "trades_after": self.trades_after,
            "trades_removed": self.trades_removed,
            "wr_before": round(self.wr_before * 100, 1),
            "wr_after": round(self.wr_after * 100, 1),
            "pf_before": round(self.pf_before, 2),
            "pf_after": round(self.pf_after, 2),
            "expectancy_before": round(self.expectancy_before, 3),
            "expectancy_after": round(self.expectancy_after, 3),
            "delta_expectancy": round(self.delta_expectancy, 3),
            "delta_wr": round(self.delta_wr * 100, 1),
            "avg_pnl_before": round(self.avg_pnl_before, 3),
            "avg_pnl_after": round(self.avg_pnl_after, 3),
            "is_positive_edge": self.is_positive_edge,
            "diagnosis": self.diagnosis,
        }


# ══════════════════════════════════════════════════════════════════
# GateSimulator
# ══════════════════════════════════════════════════════════════════

class GateSimulator:
    """Virtual filter application to historical trades."""

    def __init__(self, trades: list[dict]):
        self.trades = trades
        self.baseline = self._compute_stats(trades)

    def _compute_stats(self, trades: list[dict]) -> dict:
        """Compute WR, PF, expectancy for a set of trades."""
        closed = [t for t in trades if t["outcome"] in ("HIT_TP", "HIT_SL")]
        if not closed:
            return {"count": 0, "wr": 0.0, "pf": 0.0, "expectancy": 0.0, "avg_pnl": 0.0}

        wins = [t for t in closed if t["outcome"] == "HIT_TP"]
        losses = [t for t in closed if t["outcome"] == "HIT_SL"]

        n = len(closed)
        n_win = len(wins)
        wr = n_win / n if n > 0 else 0.0

        gross_profit = sum(t["pnl_r"] for t in wins) if wins else 0.0
        gross_loss = abs(sum(t["pnl_r"] for t in losses)) if losses else 0.0
        pf = gross_profit / gross_loss if gross_loss > 0 else (999.99 if gross_profit > 0 else 0.0)

        avg_win = gross_profit / n_win if n_win > 0 else 0.0
        avg_loss = -gross_loss / n_loss if (n_loss := n - n_win) > 0 else 0.0
        expectancy = (wr * avg_win) + ((1 - wr) * avg_loss) if n > 0 else 0.0

        avg_pnl = sum(t["pnl_pct"] for t in closed) / n if n > 0 else 0.0

        return {
            "count": n,
            "wr": wr,
            "pf": pf,
            "expectancy": expectancy,
            "avg_pnl": avg_pnl,
        }

    def apply_filter(self, filter_name: str, condition: Callable[[dict], bool]) -> GateResult:
        """Apply a single filter and compare before/after."""
        base = self.baseline
        filtered = [t for t in self.trades if condition(t)]
        after = self._compute_stats(filtered)

        delta_e = after["expectancy"] - base["expectancy"]
        delta_wr = after["wr"] - base["wr"]

        # Diagnosis
        if delta_e > 0 and after["count"] >= 10:
            diagnosis = "IMPROVES_EDGE: filter adds positive expectancy"
        elif delta_e > 0 and after["count"] < 10:
            diagnosis = "TOO_FEW_TRADES: positive but insufficient sample"
        elif delta_e < -0.05:
            diagnosis = "DESTROYS_EDGE: filter reduces expectancy"
        elif after["count"] < base["count"] * 0.3:
            diagnosis = "OVER_FILTERED: removes >70% of trades"
        else:
            diagnosis = "NEUTRAL: minor impact on expectancy"

        return GateResult(
            filter_name=filter_name,
            trades_before=base["count"],
            trades_after=after["count"],
            trades_removed=base["count"] - after["count"],
            wr_before=base["wr"],
            wr_after=after["wr"],
            pf_before=base["pf"],
            pf_after=after["pf"],
            expectancy_before=base["expectancy"],
            expectancy_after=after["expectancy"],
            delta_expectancy=delta_e,
            delta_wr=delta_wr,
            avg_pnl_before=base["avg_pnl"],
            avg_pnl_after=after["avg_pnl"],
            is_positive_edge=(delta_e > 0 and after["count"] >= 10),
            diagnosis=diagnosis,
        )

    def sweep_single_gates(self) -> list[GateResult]:
        """Test each predefined filter independently."""
        results = []
        for name, condition in FILTERS.items():
            result = self.apply_filter(name, condition)
            results.append(result)
        # Sort by delta_expectancy descending
        results.sort(key=lambda r: r.delta_expectancy, reverse=True)
        return results

    def apply_combo(self, filter_names: list[str]) -> GateResult:
        """Apply AND-combined filters."""
        conditions = []
        for name in filter_names:
            if name in FILTERS:
                conditions.append(FILTERS[name])
            elif name in DB_GATE_MAP:
                col = name
                conditions.append(lambda t, c=col: t.get(c) is True)
            else:
                print(f"Warning: unknown filter '{name}', skipping")

        if not conditions:
            return GateResult(filter_name=",".join(filter_names))

        def combined(t):
            return all(c(t) for c in conditions)

        return self.apply_filter(" AND ".join(filter_names), combined)

    def sweep_db_gates(self) -> list[GateResult]:
        """Test each DB gate column independently."""
        results = []
        for col, name in DB_GATE_MAP.items():
            condition = lambda t, c=col: t.get(c) is True
            result = self.apply_filter(f"db:{name}", condition)
            results.append(result)
        results.sort(key=lambda r: r.delta_expectancy, reverse=True)
        return results

    def find_best_combos(self, max_depth: int = 3, min_trades: int = 10) -> list[GateResult]:
        """Find best filter combinations (greedy, not exhaustive)."""
        # Start with single filters that have positive edge
        singles = self.sweep_single_gates()
        positive_singles = [r for r in singles if r.is_positive_edge]

        combos = []

        # Test top single filters
        for r in positive_singles[:10]:
            combos.append(r)

        # Test pairs from top singles
        if max_depth >= 2:
            top_names = [r.filter_name for r in positive_singles[:8]]
            for i, name_a in enumerate(top_names):
                for name_b in top_names[i+1:]:
                    combo_result = self.apply_combo([name_a, name_b])
                    if combo_result.trades_after >= min_trades:
                        combos.append(combo_result)

        # Test triples from top singles
        if max_depth >= 3:
            top_names = [r.filter_name for r in positive_singles[:5]]
            for i, a in enumerate(top_names):
                for j, b in enumerate(top_names[i+1:], i+1):
                    for c in top_names[j+1:]:
                        combo_result = self.apply_combo([a, b, c])
                        if combo_result.trades_after >= min_trades:
                            combos.append(combo_result)

        # Deduplicate and sort
        seen = set()
        unique = []
        for r in combos:
            key = r.filter_name
            if key not in seen:
                seen.add(key)
                unique.append(r)

        unique.sort(key=lambda r: r.delta_expectancy, reverse=True)
        return unique[:20]


# ══════════════════════════════════════════════════════════════════
# Report generator
# ══════════════════════════════════════════════════════════════════

def generate_gate_simulation_report(
    single_results: list[GateResult],
    db_gate_results: list[GateResult],
    best_combos: list[GateResult],
    baseline: dict,
    output_path: Path,
) -> None:
    """Generate gate_simulation.md."""
    lines = []
    w = lines.append

    w("# Gate Simulation Report\n")
    w(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")
    w(f"Trades analyzed: {baseline['count']}\n")
    w(f"Baseline: WR={baseline['wr']*100:.1f}% | PF={baseline['pf']:.2f} | "
      f"E={baseline['expectancy']:+.3f}R | Avg PnL={baseline['avg_pnl']:+.3f}%\n")

    # Single filter sweep
    w("## Single Filter Impact\n")
    w("Sorted by delta expectancy (best filters first).\n")
    w("| Filter | Trades | WR | PF | Expectancy | Delta E | Diagnosis |")
    w("|--------|--------|----|----|------------|---------|-----------|")
    for r in single_results:
        emoji = "+" if r.delta_expectancy > 0 else ""
        w(f"| {r.filter_name} | {r.trades_after}/{r.trades_before} | "
          f"{r.wr_after:.1f}% | {r.pf_after:.2f} | "
          f"{r.expectancy_after:+.3f}R | {emoji}{r.delta_expectancy:+.3f}R | "
          f"{r.diagnosis} |")
    w("")

    # DB gates
    w("## DB Gate Columns (Pipeline Gates)\n")
    w("These are actual gates from the production pipeline.\n")
    w("| Gate | Trades | WR | PF | Expectancy | Delta E | Diagnosis |")
    w("|------|--------|----|----|------------|---------|-----------|")
    for r in db_gate_results:
        emoji = "+" if r.delta_expectancy > 0 else ""
        w(f"| {r.filter_name} | {r.trades_after}/{r.trades_before} | "
          f"{r.wr_after:.1f}% | {r.pf_after:.2f} | "
          f"{r.expectancy_after:+.3f}R | {emoji}{r.delta_expectancy:+.3f}R | "
          f"{r.diagnosis} |")
    w("")

    # Best combos
    w("## Best Filter Combinations\n")
    w("Top combinations that improve expectancy with sufficient sample size.\n")
    w("| Filters | Trades | WR | PF | Expectancy | Delta E |")
    w("|---------|--------|----|----|------------|---------|")
    for r in best_combos:
        emoji = "+" if r.delta_expectancy > 0 else ""
        w(f"| {r.filter_name} | {r.trades_after}/{r.trades_before} | "
          f"{r.wr_after:.1f}% | {r.pf_after:.2f} | "
          f"{r.expectancy_after:+.3f}R | {emoji}{r.delta_expectancy:+.3f}R |")
    w("")

    # Summary
    positive_filters = [r for r in single_results if r.is_positive_edge]
    negative_filters = [r for r in single_results if r.delta_expectancy < -0.05]

    w("## Summary\n")
    w(f"### Filters that IMPROVE expectancy ({len(positive_filters)}):\n")
    for r in positive_filters:
        w(f"- **{r.filter_name}**: {r.delta_expectancy:+.3f}R "
          f"({r.trades_after} trades, WR {r.wr_after:.1f}%)")
    w("")

    w(f"### Filters that DESTROY expectancy ({len(negative_filters)}):\n")
    for r in negative_filters:
        w(f"- **{r.filter_name}**: {r.delta_expectancy:+.3f}R "
          f"({r.trades_after} trades, WR {r.wr_after:.1f}%)")
    w("")

    w("### Recommendation\n")
    if positive_filters:
        best = positive_filters[0]
        w(f"Best single filter: **{best.filter_name}** "
          f"(+{best.delta_expectancy:+.3f}R, {best.trades_after} trades)\n")
    if best_combos:
        best_combo = best_combos[0]
        w(f"Best combination: **{best_combo.filter_name}** "
          f"(+{best_combo.delta_expectancy:+.3f}R, {best_combo.trades_after} trades)\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written: {output_path}")


# ══════════════════════════════════════════════════════════════════
# Console output
# ══════════════════════════════════════════════════════════════════

def print_simulation_summary(
    single_results: list[GateResult],
    baseline: dict,
) -> None:
    """Print concise console summary."""
    print("\n" + "=" * 70)
    print("GATE SIMULATION — SUMMARY")
    print("=" * 70)

    print(f"\n  Baseline: {baseline['count']} trades | "
          f"WR={baseline['wr']*100:.1f}% | PF={baseline['pf']:.2f} | "
          f"E={baseline['expectancy']:+.3f}R")

    positive = [r for r in single_results if r.is_positive_edge]
    negative = [r for r in single_results if r.delta_expectancy < -0.05]

    print(f"\n  Filters improving expectancy: {len(positive)}")
    for r in positive[:5]:
        print(f"    + {r.filter_name:<25} E={r.expectancy_after:+.3f}R "
              f"(+{r.delta_expectancy:+.3f}) n={r.trades_after}")

    print(f"\n  Filters destroying expectancy: {len(negative)}")
    for r in negative[:5]:
        print(f"    - {r.filter_name:<25} E={r.expectancy_after:+.3f}R "
              f"({r.delta_expectancy:+.3f}) n={r.trades_after}")

    print("\n" + "=" * 70)


# ══════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Gate Simulation — test which filters improve expectancy"
    )
    parser.add_argument("--db", default=str(DB_PATH), help="Path to SQLite database")
    parser.add_argument("--days", type=int, default=90, help="Analyze trades from last N days")
    parser.add_argument("--sweep", action="store_true", help="Full sweep of all filters + combos")
    parser.add_argument("--combo", type=str, help="Comma-separated filter names to combine")
    parser.add_argument("--list-filters", action="store_true", help="List all available filters")
    args = parser.parse_args()

    if args.list_filters:
        print("Available filters:")
        for name in sorted(FILTERS.keys()):
            print(f"  {name}")
        print(f"\nDB gates: {len(DB_GATE_MAP)}")
        for col, name in sorted(DB_GATE_MAP.items()):
            print(f"  {name} ({col})")
        sys.exit(0)

    db_path = args.db
    if not Path(db_path).exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    print(f"Loading trades from {db_path} (last {args.days} days)...")
    trades = load_trades_for_simulation(db_path, args.days)
    print(f"Loaded {len(trades)} resolved trades")

    if not trades:
        print("No resolved trades found.")
        sys.exit(0)

    sim = GateSimulator(trades)

    # Single filter combo
    if args.combo:
        filter_names = [f.strip() for f in args.combo.split(",")]
        print(f"\nApplying filter combination: {filter_names}")
        result = sim.apply_combo(filter_names)
        print(f"\n  Before: {result.trades_before} trades, WR={result.wr_before*100:.1f}%, "
              f"E={result.expectancy_before:+.3f}R")
        print(f"  After:  {result.trades_after} trades, WR={result.wr_after*100:.1f}%, "
              f"E={result.expectancy_after:+.3f}R")
        print(f"  Delta:  {result.delta_expectancy:+.3f}R ({result.diagnosis})")
        sys.exit(0)

    # Full sweep
    print("\nRunning single filter sweep...")
    single_results = sim.sweep_single_gates()

    print("Running DB gate sweep...")
    db_gate_results = sim.sweep_db_gates()

    print("Finding best combinations...")
    best_combos = sim.find_best_combos()

    # Generate report
    print("\nGenerating report...")
    generate_gate_simulation_report(
        single_results, db_gate_results, best_combos,
        sim.baseline,
        REPORTS_DIR / "gate_simulation.md",
    )

    print_simulation_summary(single_results, sim.baseline)


if __name__ == "__main__":
    main()
