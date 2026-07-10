"""
analytics/gate_funnel.py — Gate Funnel analysis from decision_traces.

Shows per-gate: Entered, Passed, TP, SL, WR — enabling instant identification
of which gates add value (improve WR) and which just reduce trade count.

Usage:
    python -m analytics.gate_funnel [--db data/signals.db]
    python -m analytics.gate_funnel --symbol BTC/USDT
    python -m analytics.gate_funnel --export
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "signals.db"

GATE_ORDER = [
    "cooldown", "portfolio_risk", "btc_global_trend", "indicators",
    "confirm_tf", "signal_engine", "distance_filter", "tp_path",
    "mtf_alignment", "btc_correlation", "eth_correlation", "volatility",
    "context_timeout", "context_block", "context_min_verdict",
    "news", "sl_distance", "rr_guard", "no_trade_zones",
    "dynamic_risk", "confidence_v2", "dedup", "compression_block",
]

GATE_COL_MAP = {
    "cooldown": "gate_cooldown",
    "portfolio_risk": "gate_portfolio_risk",
    "btc_global_trend": "gate_btc_global_trend",
    "indicators": "gate_indicators",
    "confirm_tf": "gate_confirm_tf",
    "signal_engine": "gate_signal_engine",
    "distance_filter": "gate_distance_filter",
    "tp_path": "gate_tp_path",
    "mtf_alignment": "gate_mtf_alignment",
    "btc_correlation": "gate_btc_correlation",
    "eth_correlation": "gate_eth_correlation",
    "volatility": "gate_volatility",
    "context_timeout": "gate_context_timeout",
    "context_block": "gate_context_block",
    "context_min_verdict": "gate_context_min_verdict",
    "news": "gate_news",
    "sl_distance": "gate_sl_distance",
    "rr_guard": "gate_rr_guard",
    "no_trade_zones": "gate_no_trade_zones",
    "dynamic_risk": "gate_dynamic_risk",
    "confidence_v2": "gate_confidence_v2",
    "dedup": "gate_dedup",
    "compression_block": "gate_compression_block",
    # Structural gates (Scenario Forensics)
    "structure_alignment": "gate_structure_alignment",
    "sweep_required": "gate_sweep_required",
    "regime_block": "gate_regime_block",
}


def load_traces(db_path: str | Path, symbol: str | None = None) -> list[dict]:
    """Load all decision traces."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM decision_traces"
    params: list[Any] = []
    if symbol:
        query += " WHERE symbol = ?"
        params.append(symbol)
    query += " ORDER BY timestamp"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def compute_gate_funnel(traces: list[dict]) -> list[dict]:
    """Compute gate funnel: Entered/Passed/TP/SL/WR per gate.

    For each gate:
    - Entered: traces where this gate was evaluated (not None)
    - Passed: traces where this gate returned True
    - Dropped: Entered - Passed
    - Of those that PASSED this gate AND all later gates → how many hit TP/SL

    Returns list of dicts ordered by pipeline position.
    """
    results = []

    for gate in GATE_ORDER:
        col = GATE_COL_MAP.get(gate)
        if not col:
            continue

        entered = sum(1 for t in traces if t.get(col) is not None)
        passed = sum(1 for t in traces if t.get(col) is True)
        dropped = entered - passed

        # Downstream: signals that passed this gate AND all subsequent gates
        gate_idx = GATE_ORDER.index(gate)
        downstream_wins = 0
        downstream_losses = 0
        downstream_pnls: list[float] = []

        for t in traces:
            if t.get(col) is not True:
                continue

            # Check all later gates passed
            all_later_pass = True
            for later_gate in GATE_ORDER[gate_idx + 1:]:
                later_col = GATE_COL_MAP.get(later_gate)
                if later_col and t.get(later_col) is False:
                    all_later_pass = False
                    break

            if not all_later_pass:
                continue

            # Only count if signal was actually generated
            if not t.get("signal_generated"):
                continue

            outcome = t.get("outcome")
            pnl = t.get("pnl_pct")

            if outcome == "HIT_TP":
                downstream_wins += 1
            elif outcome == "HIT_SL":
                downstream_losses += 1

            if pnl is not None:
                downstream_pnls.append(pnl)

        total_closed = downstream_wins + downstream_losses
        wr = downstream_wins / total_closed * 100 if total_closed > 0 else None

        gross_profit = sum(p for p in downstream_pnls if p > 0)
        gross_loss = abs(sum(p for p in downstream_pnls if p < 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else None

        results.append({
            "gate": gate,
            "entered": entered,
            "passed": passed,
            "dropped": dropped,
            "drop_rate": round(dropped / entered * 100, 1) if entered > 0 else 0,
            "tp": downstream_wins,
            "sl": downstream_losses,
            "total_closed": total_closed,
            "wr": round(wr, 1) if wr is not None else "N/A",
            "pf": round(pf, 2) if pf is not None else "N/A",
            "total_pnl": round(sum(downstream_pnls), 2) if downstream_pnls else 0,
        })

    return results


def compute_removed_gate_impact(traces: list[dict]) -> list[dict]:
    """For each gate, compute what happens if we remove it.

    Shows: would_add trades, new WR, WR delta — identifying gates that
    just reduce count vs gates that actually filter bad trades.
    """
    results = []

    # Baseline: current signals
    current_signals = [t for t in traces if t.get("signal_generated")]
    current_wins = sum(1 for t in current_signals if t.get("outcome") == "HIT_TP")
    current_losses = sum(1 for t in current_signals if t.get("outcome") == "HIT_SL")
    current_closed = current_wins + current_losses
    current_wr = current_wins / current_closed * 100 if current_closed > 0 else 0

    for gate in GATE_ORDER:
        col = GATE_COL_MAP.get(gate)
        if not col:
            continue

        gate_idx = GATE_ORDER.index(gate)
        would_add = []

        for t in traces:
            if t.get("signal_generated"):
                continue  # already counted

            # Was this trace blocked by THIS gate?
            if t.get(col) is not False:
                continue

            # Would it pass if we removed this gate?
            would_pass = True
            for i, later_gate in enumerate(GATE_ORDER):
                if later_gate == gate:
                    continue
                later_col = GATE_COL_MAP.get(later_gate)
                if later_col and t.get(later_col) is False:
                    would_pass = False
                    break

            if would_pass:
                would_add.append(t)

        add_wins = sum(1 for t in would_add if t.get("outcome") == "HIT_TP")
        add_losses = sum(1 for t in would_add if t.get("outcome") == "HIT_SL")
        add_closed = add_wins + add_losses

        new_total = current_closed + add_closed
        new_wins = current_wins + add_wins
        new_wr = new_wins / new_total * 100 if new_total > 0 else 0

        add_pnls = [t["pnl_pct"] for t in would_add if t.get("pnl_pct") is not None]

        verdict = "USEFUL" if new_wr < current_wr - 0.5 else "NEUTRAL" if abs(new_wr - current_wr) <= 0.5 else "HARMFUL"

        results.append({
            "gate": gate,
            "currently_blocked": len(would_add),
            "would_add": len(would_add),
            "add_wins": add_wins,
            "add_losses": add_losses,
            "add_wr": round(add_wins / add_closed * 100, 1) if add_closed > 0 else "N/A",
            "current_wr": round(current_wr, 1),
            "new_wr": round(new_wr, 1),
            "wr_delta": round(new_wr - current_wr, 1),
            "verdict": verdict,
        })

    return results


def print_funnel_table(funnel: list[dict]) -> None:
    """Print the gate funnel table."""
    print("=" * 100)
    print("GATE FUNNEL ANALYSIS")
    print("=" * 100)
    print()
    print(f"  {'Gate':<28} {'Entered':>8} {'Passed':>8} {'Dropped':>8} {'Drop%':>7} "
          f"{'TP':>5} {'SL':>5} {'WR':>7} {'PF':>7}")
    print(f"  {'-'*28} {'-'*8} {'-'*8} {'-'*8} {'-'*7} {'-'*5} {'-'*5} {'-'*7} {'-'*7}")

    for row in funnel:
        entered = row["entered"]
        if entered == 0:
            continue

        wr_str = f"{row['wr']:.1f}%" if isinstance(row["wr"], float) else row["wr"]
        pf_str = f"{row['pf']:.2f}" if isinstance(row["pf"], float) else row["pf"]

        print(f"  {row['gate']:<28} {row['entered']:>8,} {row['passed']:>8,} "
              f"{row['dropped']:>8,} {row['drop_rate']:>6.1f}% "
              f"{row['tp']:>5} {row['sl']:>5} {wr_str:>7} {pf_str:>7}")

    total_entered = funnel[0]["entered"] if funnel else 0
    total_passed = funnel[-1]["passed"] if funnel else 0
    total_signals = sum(1 for r in funnel if r["gate"] == "dedup")
    print(f"\n  Pipeline: {total_entered:,} candidates → {total_passed:,} final signals")


def print_counterfactual_table(cf: list[dict]) -> None:
    """Print the counterfactual (gate removal) impact table."""
    print()
    print("=" * 100)
    print("GATE REMOVAL IMPACT (Counterfactual)")
    print("=" * 100)
    print()
    print(f"  {'Gate':<28} {'Blocked':>8} {'Add':>5} {'AddWR':>7} {'CurWR':>7} "
          f"{'NewWR':>7} {'ΔWR':>7} {'Verdict':<10}")
    print(f"  {'-'*28} {'-'*8} {'-'*5} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*10}")

    for row in sorted(cf, key=lambda x: x.get("wr_delta", 0)):
        add_wr = f"{row['add_wr']:.1f}%" if isinstance(row["add_wr"], float) else row["add_wr"]
        marker = "✓" if row["verdict"] == "USEFUL" else "✗" if row["verdict"] == "HARMFUL" else "~"

        print(f"  {row['gate']:<28} {row['currently_blocked']:>8} {row['would_add']:>5} "
              f"{add_wr:>7} {row['current_wr']:>6.1f}% {row['new_wr']:>6.1f}% "
              f"{row['wr_delta']:>+6.1f}% {row['verdict']:<10} {marker}")

    print()
    print("  Verdict legend:")
    print("    USEFUL   = removing gate HURTS WR (gate filters bad trades)")
    print("    NEUTRAL  = removing gate has negligible effect")
    print("    HARMFUL  = removing gate IMPROVES WR (gate is counterproductive)")


def export_funnel(funnel: list[dict], cf: list[dict], output: Path) -> None:
    """Export funnel + counterfactual to JSON."""
    data = {
        "funnel": funnel,
        "counterfactual": cf,
    }
    with open(output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\nExported to {output}")


def main():
    parser = argparse.ArgumentParser(description="Gate Funnel Analysis")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    traces = load_traces(db_path, symbol=args.symbol)
    print(f"Loaded {len(traces)} decision traces")

    if not traces:
        print("No traces found.")
        return

    funnel = compute_gate_funnel(traces)
    cf = compute_removed_gate_impact(traces)

    print_funnel_table(funnel)
    print_counterfactual_table(cf)

    if args.export:
        output = Path(__file__).resolve().parent.parent / "reports" / "gate_funnel.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        export_funnel(funnel, cf, output)


if __name__ == "__main__":
    main()
