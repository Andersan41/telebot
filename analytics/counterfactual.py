"""
analytics/counterfactual.py — Counterfactual gate analysis with bootstrap CI.

Shows what happens if each gate is disabled: how many extra trades,
what their WR is, and whether the overall PF improves or degrades.

Includes bootstrap confidence intervals for all metrics.

LIMITATION: This analysis uses historical outcomes of blocked trades.
It does NOT re-run the pipeline without the gate, so downstream gates
honesty are not tested. For true counterfactual, use shadow/paper mode
(Step 7 in tgbot-adv.md).

Usage:
    python -m analytics.counterfactual [--db data/signals.db]
    python -m analytics.counterfactual --gate mtf_alignment
    python -m analytics.counterfactual --export
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import numpy as np

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
}


def load_traces(db_path: str | Path) -> list[dict]:
    """Load all decision traces."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM decision_traces ORDER BY timestamp").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def bootstrap_ci(
    values: list[float], n_bootstrap: int = 1000, ci: float = 0.95
) -> tuple[float, float, float]:
    """Compute bootstrap confidence interval for mean.

    Returns:
        (mean, ci_low, ci_high)
    """
    if len(values) < 2:
        mean = values[0] if values else 0.0
        return mean, mean, mean

    arr = np.array(values)
    mean = float(np.mean(arr))

    boot_means = []
    rng = np.random.RandomState(42)
    for _ in range(n_bootstrap):
        sample = rng.choice(arr, size=len(arr), replace=True)
        boot_means.append(float(np.mean(sample)))

    alpha = (1 - ci) / 2
    ci_low = float(np.percentile(boot_means, alpha * 100))
    ci_high = float(np.percentile(boot_means, (1 - alpha) * 100))

    return mean, ci_low, ci_high


def compute_baseline(traces: list[dict]) -> dict:
    """Compute baseline stats for current signals."""
    signals = [t for t in traces if t.get("signal_generated")]
    wins = sum(1 for t in signals if t.get("outcome") == "HIT_TP")
    losses = sum(1 for t in signals if t.get("outcome") == "HIT_SL")
    closed = wins + losses
    pnls = [t["pnl_pct"] for t in signals if t.get("pnl_pct") is not None]

    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    return {
        "total_signals": len(signals),
        "wins": wins,
        "losses": losses,
        "closed": closed,
        "wr": round(wins / closed * 100, 1) if closed > 0 else 0,
        "pf": round(pf, 2),
        "total_pnl": round(sum(pnls), 2),
        "avg_pnl": round(sum(pnls) / len(pnls), 3) if pnls else 0,
    }


def compute_single_gate_removal(
    traces: list[dict], gate: str, baseline: dict
) -> dict | None:
    """Compute impact of removing a single gate with bootstrap CI."""
    col = GATE_COL_MAP.get(gate)
    if not col:
        return None

    # Find traces blocked by this gate that would pass all other gates
    would_add = []
    for t in traces:
        if t.get("signal_generated"):
            continue
        if t.get(col) is not False:
            continue

        would_pass = True
        for other_gate in GATE_ORDER:
            if other_gate == gate:
                continue
            other_col = GATE_COL_MAP.get(other_gate)
            if other_col and t.get(other_col) is False:
                would_pass = False
                break

        if would_pass:
            would_add.append(t)

    if not would_add:
        return {
            "gate": gate,
            "blocked": 0,
            "would_add": 0,
            "add_wins": 0,
            "add_losses": 0,
            "add_pnl": 0,
            "new_total": baseline["total_signals"],
            "new_wr": baseline["wr"],
            "new_pf": baseline["pf"],
            "wr_delta": 0,
            "pf_delta": 0,
            "wr_ci": (baseline["wr"], baseline["wr"], baseline["wr"]),
            "pf_ci": (baseline["pf"], baseline["pf"], baseline["pf"]),
            "verdict": "NO_EFFECT",
        }

    add_wins = sum(1 for t in would_add if t.get("outcome") == "HIT_TP")
    add_losses = sum(1 for t in would_add if t.get("outcome") == "HIT_SL")
    add_pnls = [t["pnl_pct"] for t in would_add if t.get("pnl_pct") is not None]

    new_total = baseline["total_signals"] + len(would_add)
    new_closed = baseline["closed"] + add_wins + add_losses
    new_wins = baseline["wins"] + add_wins
    new_wr = new_wins / new_closed * 100 if new_closed > 0 else 0

    all_pnls = [t["pnl_pct"] for t in traces if t.get("signal_generated") and t.get("pnl_pct") is not None]
    all_pnls.extend(add_pnls)
    gp = sum(p for p in all_pnls if p > 0)
    gl = abs(sum(p for p in all_pnls if p < 0))
    new_pf = gp / gl if gl > 0 else float("inf")

    wr_delta = new_wr - baseline["wr"]
    pf_delta = new_pf - baseline["pf"]

    # Bootstrap CI on added trades' WR
    if add_wins + add_losses > 0:
        add_wr = add_wins / (add_wins + add_losses) * 100
        add_wr_values = [1.0] * add_wins + [0.0] * add_losses
        _, wr_ci_low, wr_ci_high = bootstrap_ci(add_wr_values)
        wr_ci = (add_wr, wr_ci_low * 100, wr_ci_high * 100)
    else:
        wr_ci = (0, 0, 0)

    # Bootstrap CI on new PF
    if all_pnls:
        pf_values = []
        rng = np.random.RandomState(42)
        for _ in range(500):
            sample = rng.choice(all_pnls, size=len(all_pnls), replace=True)
            s_gp = sum(p for p in sample if p > 0)
            s_gl = abs(sum(p for p in sample if p < 0))
            pf_values.append(s_gp / s_gl if s_gl > 0 else float("inf"))
        pf_mean = float(np.mean(pf_values))
        pf_ci_low = float(np.percentile(pf_values, 2.5))
        pf_ci_high = float(np.percentile(pf_values, 97.5))
        pf_ci = (new_pf, pf_ci_low, pf_ci_high)
    else:
        pf_ci = (new_pf, new_pf, new_pf)

    # Verdict
    if abs(wr_delta) < 0.5 and abs(pf_delta) < 0.05:
        verdict = "NEUTRAL"
    elif wr_delta > 0.5 and new_pf >= baseline["pf"]:
        verdict = "REMOVABLE"
    elif wr_delta < -1.0 or new_pf < baseline["pf"] - 0.1:
        verdict = "ESSENTIAL"
    else:
        verdict = "MIXED"

    return {
        "gate": gate,
        "blocked": len(would_add),
        "would_add": len(would_add),
        "add_wins": add_wins,
        "add_losses": add_losses,
        "add_pnl": round(sum(add_pnls), 2) if add_pnls else 0,
        "add_wr": round(add_wins / (add_wins + add_losses) * 100, 1) if (add_wins + add_losses) > 0 else "N/A",
        "new_total": new_total,
        "new_wr": round(new_wr, 1),
        "new_pf": round(new_pf, 2),
        "wr_delta": round(wr_delta, 1),
        "pf_delta": round(pf_delta, 2),
        "wr_ci": tuple(round(v, 1) for v in wr_ci),
        "pf_ci": tuple(round(v, 2) for v in pf_ci),
        "verdict": verdict,
    }


def compute_pair_removal(
    traces: list[dict], gate_a: str, gate_b: str, baseline: dict
) -> dict | None:
    """Compute impact of removing two gates simultaneously."""
    col_a = GATE_COL_MAP.get(gate_a)
    col_b = GATE_COL_MAP.get(gate_b)
    if not col_a or not col_b:
        return None

    would_add = []
    for t in traces:
        if t.get("signal_generated"):
            continue
        blocked_by_a = t.get(col_a) is False
        blocked_by_b = t.get(col_b) is False
        if not (blocked_by_a or blocked_by_b):
            continue

        would_pass = True
        for other_gate in GATE_ORDER:
            if other_gate in (gate_a, gate_b):
                continue
            other_col = GATE_COL_MAP.get(other_gate)
            if other_col and t.get(other_col) is False:
                would_pass = False
                break

        if would_pass:
            would_add.append(t)

    if not would_add:
        return None

    add_wins = sum(1 for t in would_add if t.get("outcome") == "HIT_TP")
    add_losses = sum(1 for t in would_add if t.get("outcome") == "HIT_SL")
    add_pnls = [t["pnl_pct"] for t in would_add if t.get("pnl_pct") is not None]

    new_total = baseline["total_signals"] + len(would_add)
    new_closed = baseline["closed"] + add_wins + add_losses
    new_wins = baseline["wins"] + add_wins
    new_wr = new_wins / new_closed * 100 if new_closed > 0 else 0

    return {
        "gates": f"{gate_a} + {gate_b}",
        "would_add": len(would_add),
        "add_wr": round(add_wins / (add_wins + add_losses) * 100, 1) if (add_wins + add_losses) > 0 else "N/A",
        "new_wr": round(new_wr, 1),
        "wr_delta": round(new_wr - baseline["wr"], 1),
    }


def print_counterfactual_report(results: list[dict], baseline: dict) -> None:
    """Print the counterfactual analysis with bootstrap CI."""
    print("=" * 120)
    print("COUNTERFACTUAL GATE ANALYSIS (with bootstrap 95% CI)")
    print("=" * 120)
    print("\n  NOTE: Uses historical outcomes of blocked trades, not pipeline re-run.")
    print("  Downstream gate interactions are NOT modeled. Treat as upper-bound estimate.\n")

    print(f"  Baseline: {baseline['total_signals']} signals, "
          f"WR={baseline['wr']:.1f}%, PF={baseline['pf']:.2f}, "
          f"TotalPnL={baseline['total_pnl']:+.2f}%")

    print()
    print(f"  {'Gate':<25} {'Add':>5} {'AddWR':>7} {'95%CI':>14} {'NewWR':>7} {'ΔWR':>7} "
          f"{'NewPF':>7} {'95%CI':>14} {'Verdict':<10}")
    print(f"  {'-'*25} {'-'*5} {'-'*7} {'-'*14} {'-'*7} {'-'*7} {'-'*7} {'-'*14} {'-'*10}")

    for r in sorted(results, key=lambda x: x.get("wr_delta", 0)):
        add_wr = f"{r['add_wr']:.1f}%" if isinstance(r["add_wr"], float) else r["add_wr"]
        wr_ci = r.get("wr_ci", (0, 0, 0))
        pf_ci = r.get("pf_ci", (0, 0, 0))
        emoji = "✓" if r["verdict"] == "REMOVABLE" else "✗" if r["verdict"] == "ESSENTIAL" else "~"

        print(f"  {r['gate']:<25} {r['would_add']:>5} "
              f"{add_wr:>7} [{wr_ci[1]:.1f},{wr_ci[2]:.1f}]"
              f" {r['new_wr']:>6.1f}% {r['wr_delta']:>+6.1f}% "
              f"{r['new_pf']:>6.2f} [{pf_ci[1]:.2f},{pf_ci[2]:.2f}]"
              f" {r['verdict']:<10} {emoji}")

    print()
    print("  Verdict legend:")
    print("    REMOVABLE  = gate can be safely removed (WR improves, PF stable)")
    print("    ESSENTIAL  = gate must stay (removal hurts WR or PF)")
    print("    NEUTRAL    = gate has negligible effect")
    print("    MIXED      = mixed signals (WR improves but PF degrades or vice versa)")
    print("\n  CI interpretation: if CI overlaps baseline WR, the effect is not significant.")

    # Top candidates for removal
    removable = [r for r in results if r["verdict"] == "REMOVABLE"]
    if removable:
        print(f"\n  GATES TO CONSIDER REMOVING:")
        for r in sorted(removable, key=lambda x: -x["wr_delta"]):
            print(f"    {r['gate']:<25} +{r['would_add']} trades, ΔWR={r['wr_delta']:+.1f}%")

    # Essential gates
    essential = [r for r in results if r["verdict"] == "ESSENTIAL"]
    if essential:
        print(f"\n  ESSENTIAL GATES (do not remove):")
        for r in sorted(essential, key=lambda x: x["wr_delta"]):
            print(f"    {r['gate']:<25} blocks {r['blocked']} trades, removing would cost ΔWR={r['wr_delta']:+.1f}%")


def main():
    parser = argparse.ArgumentParser(description="Counterfactual Gate Analysis")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--gate", default=None, help="Analyze single gate removal")
    parser.add_argument("--pairs", action="store_true", help="Analyze pair removals")
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    traces = load_traces(db_path)
    print(f"Loaded {len(traces)} decision traces")

    if not traces:
        print("No traces found.")
        return

    baseline = compute_baseline(traces)

    if args.gate:
        # Single gate analysis
        result = compute_single_gate_removal(traces, args.gate, baseline)
        if result:
            print_counterfactual_report([result], baseline)
        else:
            print(f"Gate '{args.gate}' not found.")
    else:
        # All gates
        results = []
        for gate in GATE_ORDER:
            r = compute_single_gate_removal(traces, gate, baseline)
            if r:
                results.append(r)

        print_counterfactual_report(results, baseline)

        # Pair analysis for top removable gates
        if args.pairs:
            removable = [r["gate"] for r in results if r["verdict"] == "REMOVABLE"]
            if len(removable) >= 2:
                print(f"\n{'='*110}")
                print("PAIR REMOVAL ANALYSIS (top removable combinations)")
                print("=" * 110)
                print()

                pair_results = []
                for i, ga in enumerate(removable):
                    for gb in removable[i + 1:]:
                        pr = compute_pair_removal(traces, ga, gb, baseline)
                        if pr:
                            pair_results.append(pr)

                pair_results.sort(key=lambda x: x.get("wr_delta", 0), reverse=True)
                for pr in pair_results[:10]:
                    add_wr = f"{pr['add_wr']:.1f}%" if isinstance(pr["add_wr"], float) else pr["add_wr"]
                    print(f"  {pr['gates']:<40} +{pr['would_add']:>3} trades  "
                          f"NewWR={pr['new_wr']:.1f}%  ΔWR={pr['wr_delta']:+.1f}%")

    if args.export:
        output = Path(__file__).resolve().parent.parent / "reports" / "counterfactual.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        all_results = []
        for gate in GATE_ORDER:
            r = compute_single_gate_removal(traces, gate, baseline)
            if r:
                all_results.append(r)
        with open(output, "w", encoding="utf-8") as f:
            json.dump({"baseline": baseline, "gates": all_results}, f, indent=2, ensure_ascii=False)
        print(f"\nExported to {output}")


if __name__ == "__main__":
    main()
