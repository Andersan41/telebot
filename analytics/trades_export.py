"""
analytics/trades_export.py — Per-trade export for attribution, feature importance, drift, walk-forward.

Joins signals ↔ signal_outcomes ↔ decision_traces ↔ signal_candidates into
a flat per-trade row with all metadata needed for downstream analysis.

Fields per trade:
    symbol, direction, entry, sl, tp, exit_price, pnl, result,
    strategy_version, config_snapshot, decision_trace_id, candidate_id,
    plus feature snapshot, gate path, factor strengths.

Usage:
    python -m analytics.trades_export [--db data/signals.db] [-o reports/trades.csv]
    python -m analytics.trades_export --format json --closed-only
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "signals.db"

TRADE_COLUMNS = [
    # Identity
    "trade_id", "symbol", "direction", "timeframe",
    # Entry/Exit
    "entry_price", "sl", "tp", "exit_price", "exit_status",
    # Outcome
    "pnl_pct", "result",
    # Timing
    "signal_created", "outcome_closed",
    # Strategy
    "strategy_version", "config_snapshot",
    # Links
    "decision_trace_id", "candidate_id",
    # Factor strengths (from candidate)
    "st_strength", "ema_strength", "macd_strength", "rsi_strength",
    "vol_strength", "adx_strength", "dmi_strength", "weighted_score",
    # Raw indicators
    "adx", "rsi", "ema_fast", "ema_slow", "ema_trend",
    "macd_hist", "dmi_plus", "dmi_minus", "atr",
    "volume", "volume_sma", "supertrend_direction",
    # Regime
    "regime", "regime_confidence",
    # Gate / trace
    "blocked_gate", "final_stage", "gate_path",
    "score", "confidence_v2_pct",
    # Structure
    "has_trigger", "has_leading_trigger", "mtf_aligned",
    # Feature snapshot (from trace)
    "ema_spread_pct", "volume_ratio", "tp_distance_pct", "sl_distance_pct",
    "rr_ratio", "atr_pct", "context_score", "btc_trend_strength",
    "mtf_alignment_score",
]


def load_trades(
    db_path: str | Path,
    closed_only: bool = True,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    """Load per-trade rows from the database."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    query = """
        SELECT
            s.id AS trade_id,
            s.symbol,
            s.signal_type AS direction,
            s.timeframe,
            s.close_price AS entry_price,
            s.sl,
            s.tp,
            o.close_price AS exit_price,
            o.status AS exit_status,
            o.pnl_pct,
            CASE
                WHEN o.status = 'HIT_TP' THEN 'WIN'
                WHEN o.status = 'HIT_SL' THEN 'LOSS'
                WHEN o.status = 'EXPIRED' THEN 'EXPIRED'
                ELSE 'OPEN'
            END AS result,
            s.created_at AS signal_created,
            o.closed_at AS outcome_closed,
            s.factor_fingerprint,
            s.confidence_v2_pct,
            s.score,

            -- Decision trace
            dt.id AS decision_trace_id,
            dt.strategy_version,
            dt.config_snapshot,
            dt.gate_path,
            dt.final_stage,
            dt.outcome AS trace_outcome,
            dt.pnl_pct AS trace_pnl,

            -- Feature snapshot from trace
            dt.adx, dt.rsi, dt.ema_short, dt.ema_long, dt.ema_spread_pct,
            dt.macd_hist, dt.supertrend_direction, dt.volume_ratio,
            dt.dmi_strength, dt.ema_strength,
            dt.signal_score, dt.confidence,
            dt.regime, dt.direction AS trace_direction,
            dt.sl_source, dt.tp_distance_pct, dt.sl_distance_pct, dt.rr_ratio,
            dt.has_bos, dt.has_sweep, dt.has_ob, dt.ob_distance_pct,
            dt.context_score, dt.btc_trend_strength, dt.mtf_alignment_score,
            dt.atr_pct, dt.ema_slope_3, dt.ema_slope_5,
            dt.nearest_support_pct, dt.nearest_resistance_pct, dt.regime_confidence,

            -- Candidate
            sc.id AS candidate_id,
            sc.st_strength, sc.ema_strength AS c_ema_strength,
            sc.macd_strength, sc.rsi_strength, sc.vol_strength,
            sc.adx_strength, sc.dmi_strength AS c_dmi_strength,
            sc.weighted_score,
            sc.ema_fast, sc.ema_slow, sc.ema_trend,
            sc.dmi_plus, sc.dmi_minus, sc.atr AS c_atr,
            sc.volume, sc.volume_sma,
            sc.regime AS c_regime, sc.regime_confidence AS c_regime_confidence,
            sc.blocked_gate,
            sc.has_trigger, sc.has_leading_trigger, sc.mtf_aligned
        FROM signals s
        JOIN signal_outcomes o ON s.id = o.signal_id
        LEFT JOIN decision_traces dt ON dt.signal_id = s.id
        LEFT JOIN signal_candidates sc ON sc.id = dt.candidate_id
    """

    conditions = []
    params: list[Any] = []

    if closed_only:
        conditions.append("o.status IN ('HIT_TP', 'HIT_SL')")
    if symbol:
        conditions.append("s.symbol = ?")
        params.append(symbol)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY s.created_at"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    trades = []
    for row in rows:
        d = dict(row)
        # Normalize: use trace values where candidate is null
        d["ema_fast"] = d.get("ema_fast") or d.get("ema_slow")
        d["atr"] = d.get("atr") or d.get("c_atr")
        d["regime"] = d.get("regime") or d.get("c_regime")
        trades.append(d)

    return trades


def export_csv(trades: list[dict], output: str | Path) -> None:
    """Export trades to CSV."""
    if not trades:
        print("No trades to export.")
        return

    available = [c for c in TRADE_COLUMNS if c in trades[0]]

    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=available, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(trades)

    print(f"Exported {len(trades)} trades to {output}")


def export_json(trades: list[dict], output: str | Path) -> None:
    """Export trades to JSON."""
    with open(output, "w", encoding="utf-8") as f:
        json.dump(trades, f, indent=2, ensure_ascii=False, default=str)
    print(f"Exported {len(trades)} trades to {output}")


def print_trade_summary(trades: list[dict]) -> None:
    """Print summary of exported trades."""
    if not trades:
        print("No trades found.")
        return

    total = len(trades)
    wins = [t for t in trades if t.get("result") == "WIN"]
    losses = [t for t in trades if t.get("result") == "LOSS"]
    pnls = [t["pnl_pct"] for t in trades if t.get("pnl_pct") is not None]

    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    print("=" * 80)
    print("PER-TRADE EXPORT SUMMARY")
    print("=" * 80)
    print(f"\n  Total trades:      {total}")
    print(f"  Wins:              {len(wins)}")
    print(f"  Losses:            {len(losses)}")
    print(f"  Win Rate:          {len(wins) / total * 100:.1f}%")
    print(f"  Profit Factor:     {pf:.2f}")
    print(f"  Total PnL:         {sum(pnls):+.2f}%")
    print(f"  Avg PnL:           {sum(pnls) / total:+.2f}%")
    if pnls:
        print(f"  Best trade:        {max(pnls):+.2f}%")
        print(f"  Worst trade:       {min(pnls):+.2f}%")
        sorted_pnls = sorted(pnls)
        n = len(sorted_pnls)
        print(f"  Median PnL:        {sorted_pnls[n // 2]:+.2f}%")
        print(f"  P5 PnL:            {sorted_pnls[int(n * 0.05)]:+.2f}%")
        print(f"  P95 PnL:           {sorted_pnls[min(n - 1, int(n * 0.95))]:+.2f}%")

    # By direction
    for direction in ["BUY", "SELL"]:
        subset = [t for t in trades if t.get("direction") == direction]
        if not subset:
            continue
        sw = sum(1 for t in subset if t.get("result") == "WIN")
        s_pnls = [t["pnl_pct"] for t in subset if t.get("pnl_pct") is not None]
        s_wr = sw / len(subset) * 100 if subset else 0
        s_avg = sum(s_pnls) / len(s_pnls) if s_pnls else 0
        print(f"\n  {direction}: {len(subset)} trades, WR={s_wr:.1f}%, AvgPnL={s_avg:+.2f}%")

    # By version
    versions: dict[str, list] = {}
    for t in trades:
        v = t.get("strategy_version") or "unknown"
        versions.setdefault(v, []).append(t)

    if len(versions) > 1:
        print(f"\n{'='*80}")
        print("BY STRATEGY VERSION")
        print("=" * 80)
        for v, vtrades in sorted(versions.items()):
            vw = sum(1 for t in vtrades if t.get("result") == "WIN")
            v_pnls = [t["pnl_pct"] for t in vtrades if t.get("pnl_pct") is not None]
            v_wr = vw / len(vtrades) * 100 if vtrades else 0
            v_avg = sum(v_pnls) / len(v_pnls) if v_pnls else 0
            v_gp = sum(p for p in v_pnls if p > 0)
            v_gl = abs(sum(p for p in v_pnls if p < 0))
            v_pf = v_gp / v_gl if v_gl > 0 else float("inf")
            print(f"  {v:<15} {len(vtrades):>5} trades  WR={v_wr:>5.1f}%  PF={v_pf:>5.2f}  AvgPnL={v_avg:>+6.2f}%")


def main():
    parser = argparse.ArgumentParser(description="Per-trade export")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--output", "-o", default=None)
    parser.add_argument("--format", choices=["csv", "json"], default="csv")
    parser.add_argument("--closed-only", action="store_true", default=True)
    parser.add_argument("--all", action="store_true", help="Include open trades")
    parser.add_argument("--symbol", default=None)
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    trades = load_trades(db_path, closed_only=not args.all, symbol=args.symbol)
    print(f"Loaded {len(trades)} trades from {db_path}")

    print_trade_summary(trades)

    if args.output:
        output = Path(args.output)
    else:
        suffix = "json" if args.format == "json" else "csv"
        output = Path(__file__).resolve().parent.parent / "reports" / f"trades_export.{suffix}"

    output.parent.mkdir(parents=True, exist_ok=True)

    if args.format == "json":
        export_json(trades, output)
    else:
        export_csv(trades, output)


if __name__ == "__main__":
    main()
