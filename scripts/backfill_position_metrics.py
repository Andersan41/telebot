"""
scripts/backfill_position_metrics.py — Заполнение pnl/RR метрик закрытых позиций.

positions.pnl_usdt / pnl_percent / actual_rr / expected_rr исторически оставались
NULL (close_position не принимал метрики; quantity всегда 1.0). Скрипт берёт
закрытые строки без метрик, джойнит signals + signal_outcomes и считает:

  pnl_percent = signal_outcomes.pnl_pct            (net price move %, те же единицы)
  pnl_usdt    = pnl_percent/100 × entry × quantity
  actual_rr   = (close-entry)/(entry-ORIGINAL_SL)  (direction-aware, gross)
  expected_rr = |tp-entry|/|entry-ORIGINAL_SL|

ORIGINAL_SL = signals.sl (positions.stop_loss мутирует на BE/trailing —
например NEAR: SL ушёл в безубыток 4.577, оригинальный 4.242).

Usage:
    python scripts/backfill_position_metrics.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone


def compute_metrics(
    direction: str,
    entry: float,
    sl: float,
    tp: float | None,
    close_price: float,
    quantity: float,
    net_price_pct: float | None,
) -> dict:
    metrics: dict = {}
    if net_price_pct is not None:
        metrics["pnl_percent"] = round(net_price_pct, 4)
        metrics["pnl_usdt"] = round(net_price_pct / 100.0 * entry * quantity, 8)
    risk = abs(entry - sl) if entry and sl else 0.0
    if risk > 0 and close_price:
        if direction == "BUY":
            metrics["actual_rr"] = round((close_price - entry) / risk, 4)
        else:
            metrics["actual_rr"] = round((entry - close_price) / risk, 4)
        if tp:
            metrics["expected_rr"] = round(abs(tp - entry) / risk, 4)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill closed-position PnL/RR metrics")
    parser.add_argument("--db", default="data/signals.db")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row

    positions = conn.execute(
        "SELECT id, symbol, direction, entry_price, stop_loss, take_profit, quantity, "
        "       entry_time, close_price, close_reason "
        "FROM positions WHERE status='CLOSED' AND pnl_percent IS NULL"
    ).fetchall()

    # signals by symbol → resolve via entry_time == created_at (int seconds)
    sig_rows = conn.execute(
        "SELECT id, symbol, signal_type, created_at, close_price, sl, tp FROM signals"
    ).fetchall()
    sig_by_key: dict[tuple[str, int], sqlite3.Row] = {}
    for s in sig_rows:
        try:
            dt = datetime.fromisoformat(s["created_at"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            sig_by_key[(s["symbol"], int(dt.timestamp()))] = s
        except (ValueError, TypeError):
            continue

    outcome_by_signal = {
        r["signal_id"]: r["pnl_pct"]
        for r in conn.execute(
            "SELECT signal_id, pnl_pct FROM signal_outcomes WHERE pnl_pct IS NOT NULL"
        )
    }

    updated = 0
    missing = 0
    for pos in positions:
        try:
            et = datetime.fromisoformat(pos["entry_time"])
        except (ValueError, TypeError):
            missing += 1
            continue
        if et.tzinfo is None:
            et = et.replace(tzinfo=timezone.utc)
        sig = sig_by_key.get((pos["symbol"], int(et.timestamp())))
        if sig is None:
            missing += 1
            continue
        net_pct = outcome_by_signal.get(sig["id"])
        metrics = compute_metrics(
            direction=sig["signal_type"],
            entry=sig["close_price"],
            sl=sig["sl"],
            tp=sig["tp"],
            close_price=pos["close_price"] or 0.0,
            quantity=pos["quantity"] or 1.0,
            net_price_pct=net_pct,
        )
        if not metrics:
            missing += 1
            continue
        updated += 1
        if args.dry_run:
            continue
        sets = ", ".join(f"{k}=?" for k in metrics)
        conn.execute(
            f"UPDATE positions SET {sets} WHERE id=?", (*metrics.values(), pos["id"])
        )

    if not args.dry_run:
        conn.commit()
    conn.close()

    mode = "DRY-RUN " if args.dry_run else ""
    print(f"{mode}backfill: closed_without_metrics={len(positions)} "
          f"updated={updated} missing_join_or_data={missing}")


if __name__ == "__main__":
    sys.exit(main())
