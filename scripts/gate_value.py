"""
scripts/gate_value.py — Measure gate value in R (expectancy).

The checklist says: "Count not gates, but cost of gates."
Each gate is measured by how much money it ADDS or TAKES from expectancy.

Usage:
    python scripts/gate_value.py [--db data/signals.db] [--cost-per-trade 0.15]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import numpy as np


# Information sources (not "gates") mapped to DB column names
INFORMATION_SOURCES = {
    "market_structure": {
        "label": "Market Structure (BOS/CHoCH)",
        "gates": ["signal_engine"],
        "description": "Is there a structural setup?",
    },
    "liquidity_zones": {
        "label": "Liquidity Zones (OB/FVG/Sweep)",
        "gates": ["distance_filter", "tp_path"],
        "description": "Is there a valid entry zone?",
    },
    "higher_timeframe": {
        "label": "Higher Timeframe Trend",
        "gates": ["mtf_alignment"],
        "description": "Does HTF confirm direction?",
    },
    "market_context": {
        "label": "Market Context (BTC/ETH)",
        "gates": ["btc_global_trend", "btc_correlation", "eth_correlation"],
        "description": "Does the broader market support?",
    },
    "volatility": {
        "label": "Volatility & Regime",
        "gates": ["volatility", "compression_block"],
        "description": "Is volatility sufficient?",
    },
    "sentiment": {
        "label": "Sentiment & Context",
        "gates": ["context_min_verdict", "context_block"],
        "description": "Does sentiment support?",
    },
    "risk": {
        "label": "Risk Management",
        "gates": ["sl_distance", "rr_guard", "dynamic_risk"],
        "description": "Is the risk acceptable?",
    },
    "execution": {
        "label": "Execution Filters",
        "gates": ["cooldown", "confirm_tf", "dedup"],
        "description": "Execution-level filtering",
    },
}


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


def load_traces(db_path: str, days: int = 90) -> list[dict]:
    """Load decision traces with outcomes."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM decision_traces WHERE timestamp > ? ORDER BY timestamp",
        (cutoff,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_signals(db_path: str, days: int = 90) -> list[dict]:
    """Load resolved signals with PnL."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT s.symbol, s.signal_type, s.close_price, s.sl, s.tp,
               s.created_at, o.pnl_pct, o.status
        FROM signal_outcomes o
        JOIN signals s ON o.signal_id = s.id
        WHERE o.status IN ('HIT_TP', 'HIT_SL')
          AND s.created_at > ?
        ORDER BY s.created_at
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def compute_r_values(signals: list[dict]) -> list[float]:
    """Compute R-multiple for each signal."""
    r_values = []
    for s in signals:
        if s["pnl_pct"] is None:
            continue
        entry = s["close_price"]
        sl = s.get("sl")
        if not sl or sl == entry:
            # Fallback: use 2% as risk unit
            r_values.append(s["pnl_pct"] / 2.0)
        else:
            risk = abs(entry - sl)
            reward = s["pnl_pct"] / 100 * entry
            r_values.append(reward / risk if risk > 0 else 0)
    return r_values


def analyze_gate_value(
    traces: list[dict],
    signals: list[dict],
    cost_per_trade: float = 0.15,
) -> dict:
    """Analyze the value of each gate in terms of R (expectancy)."""

    # Baseline: all passed signals
    passed = [t for t in traces if t.get("signal_generated")]
    passed_signals = [s for s in signals]  # These are the ones that passed

    if not passed_signals:
        return {"error": "No passed signals with outcomes"}

    r_values = compute_r_values(passed_signals)
    if not r_values:
        return {"error": "No R values computed"}

    baseline_wr = sum(1 for r in r_values if r > 0) / len(r_values) * 100
    baseline_avg_r = np.mean(r_values)
    baseline_expectancy = baseline_avg_r - cost_per_trade

    results = {
        "baseline": {
            "signals": len(passed_signals),
            "wr": round(baseline_wr, 1),
            "avg_r": round(float(baseline_avg_r), 3),
            "expectancy_r": round(float(baseline_expectancy), 3),
        },
        "gates": [],
        "information_sources": [],
    }

    # Analyze each gate
    for gate_name, col in GATE_COL_MAP.items():
        # Find signals blocked by this gate that would pass all others
        would_add = []
        for t in traces:
            if t.get("signal_generated"):
                continue
            if t.get(col) is not False:
                continue

            # Check if all other gates pass
            would_pass = True
            for other_gate, other_col in GATE_COL_MAP.items():
                if other_gate == gate_name:
                    continue
                if other_col and t.get(other_col) is False:
                    would_pass = False
                    break

            if would_pass:
                would_add.append(t)

        if not would_add:
            continue

        # Estimate R for added signals (use average of passed signals as proxy)
        n_added = len(would_add)
        avg_r_added = float(np.mean(r_values)) if r_values else 0

        # Net impact of removing this gate
        net_signals = n_added
        net_r = avg_r_added * n_added
        net_cost = cost_per_trade * n_added
        net_expectancy = net_r - net_cost

        results["gates"].append({
            "gate": gate_name,
            "blocked": n_added,
            "avg_r_if_added": round(avg_r_added, 3),
            "total_r_added": round(net_r, 2),
            "cost_added": round(net_cost, 2),
            "net_expectancy": round(net_expectancy, 2),
            "verdict": "REMOVE" if net_expectancy > 0 else "KEEP",
        })

    # Aggregate by information source
    for source_id, source in INFORMATION_SOURCES.items():
        source_gates = [g for g in results["gates"] if g["gate"] in source["gates"]]
        total_blocked = sum(g["blocked"] for g in source_gates)
        total_net_r = sum(g["net_expectancy"] for g in source_gates)

        results["information_sources"].append({
            "id": source_id,
            "label": source["label"],
            "description": source["description"],
            "gates": source["gates"],
            "total_blocked": total_blocked,
            "net_expectancy_r": round(total_net_r, 2),
            "verdict": "REMOVE" if total_net_r > 0 else "KEEP",
        })

    return results


def print_gate_value_report(results: dict) -> None:
    """Print the gate value analysis."""
    print("=" * 90)
    print("GATE VALUE ANALYSIS — Measured in R (Expectancy)")
    print("=" * 90)

    b = results["baseline"]
    print(f"\n  Baseline: {b['signals']} signals, WR={b['wr']}%, "
          f"AvgR={b['avg_r']:+.3f}, Expectancy={b['expectancy_r']:+.3f}R per trade")

    # Individual gates
    print(f"\n--- Individual Gates (sorted by net expectancy) ---")
    print(f"  {'Gate':<25} {'Blocked':>8} {'AvgR':>8} {'TotalR':>10} {'Cost':>8} {'Net':>10} {'Verdict':<8}")
    print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*10} {'-'*8} {'-'*10} {'-'*8}")

    for g in sorted(results["gates"], key=lambda x: x["net_expectancy"]):
        emoji = "[REMOVE]" if g["verdict"] == "REMOVE" else "[KEEP]"
        print(f"  {g['gate']:<25} {g['blocked']:>8} {g['avg_r']:>+7.3f} "
              f"{g['total_r_added']:>+9.2f} {g['cost_added']:>7.2f} "
              f"{g['net_expectancy']:>+9.2f}R {g['verdict']:<8} {emoji}")

    # Information sources
    print(f"\n--- Information Sources (aggregated) ---")
    print(f"  {'Source':<30} {'Blocked':>8} {'Net R':>10} {'Verdict':<8}")
    print(f"  {'-'*30} {'-'*8} {'-'*10} {'-'*8}")

    for s in sorted(results["information_sources"], key=lambda x: x["net_expectancy_r"]):
        emoji = "[REMOVE]" if s["verdict"] == "REMOVE" else "[KEEP]"
        print(f"  {s['label']:<30} {s['total_blocked']:>8} "
              f"{s['net_expectancy_r']:>+9.2f}R {s['verdict']:<8} {emoji}")

    # Summary
    removable = [s for s in results["information_sources"] if s["verdict"] == "REMOVE"]
    essential = [s for s in results["information_sources"] if s["verdict"] == "KEEP"]

    print(f"\n--- Summary ---")
    print(f"  Information sources to REMOVE: {len(removable)}")
    for s in removable:
        print(f"    - {s['label']}: {s['net_expectancy_r']:+.2f}R")
    print(f"\n  Information sources to KEEP: {len(essential)}")
    for s in essential:
        print(f"    + {s['label']}: {s['net_expectancy_r']:+.2f}R")

    total_removable_r = sum(s["net_expectancy_r"] for s in removable)
    print(f"\n  Estimated improvement from removing all: {total_removable_r:+.2f}R per trade")


def main():
    parser = argparse.ArgumentParser(description="Gate value analysis in R (expectancy)")
    parser.add_argument("--db", default="data/signals.db")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--cost-per-trade", type=float, default=0.15,
                        help="Cost per trade in R (commission + slippage)")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    traces = load_traces(args.db, args.days)
    signals = load_signals(args.db, args.days)

    print(f"Loaded {len(traces)} traces, {len(signals)} resolved signals (last {args.days} days)")

    if not signals:
        print("No resolved signals found.")
        sys.exit(0)

    results = analyze_gate_value(traces, signals, args.cost_per_trade)

    if "error" in results:
        print(f"Error: {results['error']}")
        sys.exit(1)

    print_gate_value_report(results)


if __name__ == "__main__":
    main()
