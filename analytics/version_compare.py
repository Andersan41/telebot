"""
analytics/version_compare.py — Strategy version comparison.

Compares WR, PF, PnL across strategy versions. Shows parameter diffs
from config_snapshot to identify which changes actually improved performance.

Usage:
    python -m analytics.version_compare [--db data/signals.db]
    python -m analytics.version_compare --versions 2.4.0 2.4.1
    python -m analytics.version_compare --export
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "signals.db"

KEY_PARAMS = [
    "adx_min", "min_score_for_signal", "min_rr_threshold",
    "ema_fast", "ema_slow", "ema_trend",
    "rsi_period", "macd_fast", "macd_slow", "macd_signal",
    "supertrend_period", "supertrend_multiplier",
    "mtf_required_alignment", "signal_cooldown_minutes",
    "min_sl_distance_pct", "max_sl_distance_pct",
    "context_min_verdict", "context_block_on_blocked",
]


def load_version_trades(db_path: str | Path) -> dict[str, list[dict]]:
    """Load trades grouped by strategy_version."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    query = """
        SELECT
            s.id, s.symbol, s.signal_type, s.close_price, s.sl, s.tp,
            s.created_at, s.confidence_v2_pct,
            o.status, o.pnl_pct, o.closed_at,
            dt.strategy_version, dt.config_snapshot,
            dt.adx, dt.rsi, dt.ema_spread_pct, dt.volume_ratio,
            dt.regime, dt.confidence, dt.gate_path
        FROM signals s
        JOIN signal_outcomes o ON s.id = o.signal_id
        LEFT JOIN decision_traces dt ON dt.signal_id = s.id
        WHERE o.status IN ('HIT_TP', 'HIT_SL')
        ORDER BY s.created_at
    """

    rows = conn.execute(query).fetchall()
    conn.close()

    versions: dict[str, list[dict]] = {}
    for row in rows:
        d = dict(row)
        v = d.get("strategy_version") or "unknown"
        versions.setdefault(v, []).append(d)

    return versions


def compute_version_stats(trades: list[dict]) -> dict:
    """Compute aggregate stats for a list of trades."""
    n = len(trades)
    if n == 0:
        return {}

    wins = sum(1 for t in trades if t.get("status") == "HIT_TP")
    losses = n - wins
    pnls = [t["pnl_pct"] for t in trades if t.get("pnl_pct") is not None]

    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    avg_pnl = sum(pnls) / len(pnls) if pnls else 0
    total_pnl = sum(pnls)
    avg_conf = sum(t.get("confidence_v2_pct", 0) or 0 for t in trades) / n

    # By direction
    buy_trades = [t for t in trades if t.get("signal_type") == "BUY"]
    sell_trades = [t for t in trades if t.get("signal_type") == "SELL"]

    buy_wr = sum(1 for t in buy_trades if t.get("status") == "HIT_TP") / len(buy_trades) * 100 if buy_trades else 0
    sell_wr = sum(1 for t in sell_trades if t.get("status") == "HIT_TP") / len(sell_trades) * 100 if sell_trades else 0

    # By regime
    regime_stats: dict[str, dict] = {}
    for t in trades:
        r = t.get("regime") or "unknown"
        regime_stats.setdefault(r, {"n": 0, "wins": 0})
        regime_stats[r]["n"] += 1
        if t.get("status") == "HIT_TP":
            regime_stats[r]["wins"] += 1

    for r, d in regime_stats.items():
        d["wr"] = round(d["wins"] / d["n"] * 100, 1) if d["n"] > 0 else 0

    return {
        "total": n,
        "wins": wins,
        "losses": losses,
        "wr": round(wins / n * 100, 1),
        "pf": round(pf, 2),
        "avg_pnl": round(avg_pnl, 3),
        "total_pnl": round(total_pnl, 2),
        "avg_confidence": round(avg_conf, 1),
        "buy_count": len(buy_trades),
        "buy_wr": round(buy_wr, 1),
        "sell_count": len(sell_trades),
        "sell_wr": round(sell_wr, 1),
        "regimes": regime_stats,
    }


def parse_config_snapshot(snapshot_json: str | None) -> dict:
    """Parse config_snapshot JSON string."""
    if not snapshot_json:
        return {}
    try:
        return json.loads(snapshot_json)
    except (json.JSONDecodeError, TypeError):
        return {}


def diff_configs(old: dict, new: dict) -> list[dict]:
    """Show parameter differences between two config snapshots."""
    diffs = []
    all_keys = set(list(old.keys()) + list(new.keys()))

    for key in sorted(all_keys):
        old_val = old.get(key)
        new_val = new.get(key)
        if old_val != new_val:
            diffs.append({
                "param": key,
                "old": old_val,
                "new": new_val,
            })

    return diffs


def print_version_comparison(version_stats: dict[str, dict]) -> None:
    """Print version comparison table."""
    print("=" * 110)
    print("STRATEGY VERSION COMPARISON")
    print("=" * 110)
    print()

    versions = sorted(version_stats.keys())
    if not versions:
        print("  No versions found.")
        return

    header = f"  {'Version':<15} {'Trades':>7} {'WR':>7} {'PF':>7} {'AvgPnL':>9} {'TotalPnL':>10} " \
             f"{'BuyWR':>7} {'SellWR':>7} {'BuyN':>6} {'SellN':>6}"
    print(header)
    print(f"  {'-'*15} {'-'*7} {'-'*7} {'-'*7} {'-'*9} {'-'*10} {'-'*7} {'-'*7} {'-'*6} {'-'*6}")

    prev_stats = None
    for v in versions:
        s = version_stats[v]
        delta_wr = ""
        delta_pf = ""
        if prev_stats:
            dw = s["wr"] - prev_stats["wr"]
            dp = s["pf"] - prev_stats["pf"]
            delta_wr = f" ({dw:+.1f}%)"
            delta_pf = f" ({dp:+.2f})"

        print(f"  {v:<15} {s['total']:>7} {s['wr']:>6.1f}% {s['pf']:>6.2f} "
              f"{s['avg_pnl']:>+8.3f}% {s['total_pnl']:>+9.2f}% "
              f"{s['buy_wr']:>6.1f}% {s['sell_wr']:>6.1f}% "
              f"{s['buy_count']:>6} {s['sell_count']:>6}")

        if delta_wr:
            print(f"  {'':>15} ΔWR={delta_wr}  ΔPF={delta_pf}")

        prev_stats = s

    print()

    # Regime breakdown for latest version
    if versions:
        latest = versions[-1]
        regimes = version_stats[latest].get("regimes", {})
        if regimes:
            print(f"  Regime breakdown ({latest}):")
            for r, d in sorted(regimes.items(), key=lambda x: -x[1]["n"]):
                print(f"    {r:<15} {d['n']:>5} trades  WR={d['wr']:>5.1f}%")
            print()


def print_config_diffs(version_configs: dict[str, dict]) -> None:
    """Print parameter changes between consecutive versions."""
    versions = sorted(version_configs.keys())
    if len(versions) < 2:
        return

    print("=" * 110)
    print("PARAMETER CHANGES BETWEEN VERSIONS")
    print("=" * 110)

    for i in range(1, len(versions)):
        old_v, new_v = versions[i - 1], versions[i]
        old_cfg = version_configs[old_v]
        new_cfg = version_configs[new_v]

        diffs = diff_configs(old_cfg, new_cfg)
        # Filter to KEY_PARAMS only
        key_diffs = [d for d in diffs if d["param"] in KEY_PARAMS]
        # Also show any non-None changes
        other_diffs = [d for d in diffs if d["param"] not in KEY_PARAMS and d["old"] is not None and d["new"] is not None]

        if not key_diffs and not other_diffs:
            print(f"\n  {old_v} → {new_v}: No parameter changes detected")
            continue

        print(f"\n  {old_v} → {new_v}:")
        print(f"  {'Parameter':<30} {'Old':>15} {'New':>15} {'Delta':>15}")
        print(f"  {'-'*30} {'-'*15} {'-'*15} {'-'*15}")

        for d in key_diffs:
            old_val = d["old"]
            new_val = d["new"]
            try:
                delta = float(new_val) - float(old_val) if old_val is not None and new_val is not None else "N/A"
                if isinstance(delta, float):
                    delta = f"{delta:+.4f}" if abs(delta) < 1 else f"{delta:+.2f}"
            except (TypeError, ValueError):
                delta = "N/A"

            print(f"  {d['param']:<30} {str(old_val):>15} {str(new_val):>15} {str(delta):>15}")

        if other_diffs:
            print(f"\n  Other changes:")
            for d in other_diffs[:10]:
                print(f"    {d['param']:<30} {str(d['old']):>15} → {str(d['new']):>15}")


def main():
    parser = argparse.ArgumentParser(description="Strategy Version Comparison")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--versions", nargs="+", default=None, help="Compare specific versions")
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    version_trades = load_version_trades(db_path)

    if not version_trades:
        print("No trades with strategy_version data found.")
        return

    # Filter to requested versions
    if args.versions:
        version_trades = {v: t for v, t in version_trades.items() if v in args.versions}

    # Compute stats
    version_stats = {}
    version_configs: dict[str, dict] = {}

    for v, trades in version_trades.items():
        version_stats[v] = compute_version_stats(trades)
        # Get config snapshot from first trade
        for t in trades:
            cfg = parse_config_snapshot(t.get("config_snapshot"))
            if cfg:
                version_configs[v] = cfg
                break

    print_version_comparison(version_stats)
    print_config_diffs(version_configs)

    if args.export:
        output = Path(__file__).resolve().parent.parent / "reports" / "version_compare.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        export = {
            "versions": version_stats,
            "configs": {v: c for v, c in version_configs.items()},
        }
        with open(output, "w", encoding="utf-8") as f:
            json.dump(export, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nExported to {output}")


if __name__ == "__main__":
    main()
