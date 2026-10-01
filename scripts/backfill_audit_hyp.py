"""
scripts/backfill_audit_hyp.py — Перенос hyp_* полей из meta в колонки signal_audit_log.

Старые blocked-строки писали hyp_entry/hyp_sl/hyp_tp/hyp_rr/hyp_ptp только
в строку meta; колонки hypothetical_* и synthetic_plan оставались NULL, из-за
чего get_unresolved_audits() их не видел и audit_resolver не разрешал.

Скрипт одноразовый: парсит meta, заполняет колонки, ставит synthetic_plan=1
(только для строк с direction — без направления симуляция невозможна).
Дальше строки разрешает scheduler/audit_resolver.py.

Usage:
    python scripts/backfill_audit_hyp.py [--dry-run] [--days 14]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

_HYP_RE = {
    "hypothetical_entry": re.compile(r"(?:^|,)hyp_entry=(-?[\d.]+)"),
    "hypothetical_sl": re.compile(r"(?:^|,)hyp_sl=(-?[\d.]+)"),
    "hypothetical_tp": re.compile(r"(?:^|,)hyp_tp=(-?[\d.]+)"),
    "hypothetical_rr": re.compile(r"(?:^|,)hyp_rr=(-?[\d.]+)"),
    "hypothetical_p_tp": re.compile(r"(?:^|,)hyp_ptp=(-?[\d.]+)"),
}


def parse_meta(meta: str) -> dict | None:
    """Extract hyp_* values from the meta string. None if entry/sl/tp incomplete."""
    out: dict = {}
    for col, rx in _HYP_RE.items():
        m = rx.search(meta or "")
        if m:
            try:
                out[col] = float(m.group(1))
            except ValueError:
                return None
    if not all(k in out for k in ("hypothetical_entry", "hypothetical_sl", "hypothetical_tp")):
        return None
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill hypothetical_* columns from meta")
    parser.add_argument("--db", default="data/signals.db")
    parser.add_argument("--days", type=int, default=14,
                        help="Only rows newer than N days (resolver max-age window)")
    parser.add_argument("--batch", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(args.db, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    rows = conn.execute(
        """SELECT id, meta FROM signal_audit_log
           WHERE outcome IS NULL
             AND (synthetic_plan IS NULL OR synthetic_plan = 0)
             AND meta LIKE '%hyp_entry=%'
             AND direction IS NOT NULL
             AND ts_event >= ?""",
        (cutoff,),
    ).fetchall()

    updated = skipped = 0
    for row_id, meta in rows:
        vals = parse_meta(meta)
        if vals is None:
            skipped += 1
            continue
        updated += 1
        if args.dry_run:
            continue
        sets = ", ".join(f"{col}=?" for col in vals)
        conn.execute(
            f"UPDATE signal_audit_log SET {sets}, synthetic_plan=1 WHERE id=?",
            (*vals.values(), row_id),
        )
        if updated % args.batch == 0:
            conn.commit()

    if not args.dry_run:
        conn.commit()
    conn.close()

    mode = "DRY-RUN " if args.dry_run else ""
    print(f"{mode}backfill: scanned={len(rows)} updated={updated} skipped(incomplete meta)={skipped}")
    if updated == 0 and not rows:
        print("Nothing to backfill (rows already have columns or meta lacks hyp_*).")


if __name__ == "__main__":
    sys.exit(main())
