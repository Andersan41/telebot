"""Quick check: how much data has accumulated in the bot's database."""
import sqlite3
import os

db_path = "data/signals.db"
if not os.path.exists(db_path):
    print(f"DB not found: {db_path}")
    raise SystemExit(1)

conn = sqlite3.connect(db_path)
cur = conn.cursor()

tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("=== Tables ===")
for (t,) in tables:
    count = cur.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0]
    print(f"  {t}: {count} rows")

print("\n=== signal_candidates ===")
rows = cur.execute("SELECT signal_type, COUNT(*) FROM signal_candidates GROUP BY signal_type").fetchall()
for st, c in rows:
    print(f"  signal_type={st}: {c}")

print("\n--- outcome ---")
rows = cur.execute("SELECT outcome, COUNT(*) FROM signal_candidates GROUP BY outcome").fetchall()
for ot, c in rows:
    print(f"  outcome={ot}: {c}")

print("\n--- blocked_gate (top 15) ---")
rows = cur.execute(
    "SELECT blocked_gate, COUNT(*) FROM signal_candidates GROUP BY blocked_gate ORDER BY COUNT(*) DESC LIMIT 15"
).fetchall()
for bg, c in rows:
    print(f"  blocked_gate={bg}: {c}")

print("\n--- stats ---")
sent = cur.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
with_outcome = cur.execute("SELECT COUNT(*) FROM signal_candidates WHERE outcome IS NOT NULL").fetchone()[0]
passed_all = cur.execute("SELECT COUNT(*) FROM signal_candidates WHERE blocked_gate IS NULL").fetchone()[0]
dt_count = cur.execute("SELECT COUNT(*) FROM decision_traces").fetchone()[0]
r = cur.execute("SELECT MIN(timestamp), MAX(timestamp) FROM signal_candidates").fetchone()
print(f"  signals sent to channel: {sent}")
print(f"  candidates passed all gates: {passed_all}")
print(f"  candidates with resolved outcome: {with_outcome}")
print(f"  decision_traces: {dt_count}")
print(f"  date range: {r[0]} -> {r[1]}")

# Confidence distribution for passed candidates
print("\n--- confidence_v2 for passed candidates ---")
rows = cur.execute("""
    SELECT
        CASE
            WHEN confidence_v2_pct IS NULL THEN 'NULL'
            WHEN confidence_v2_pct < 30 THEN '<30%'
            WHEN confidence_v2_pct < 50 THEN '30-50%'
            WHEN confidence_v2_pct < 70 THEN '50-70%'
            ELSE '70%+'
        END AS bucket,
        COUNT(*),
        SUM(CASE WHEN outcome='HIT_TP' THEN 1 ELSE 0 END),
        SUM(CASE WHEN outcome='HIT_SL' THEN 1 ELSE 0 END)
    FROM signal_candidates
    WHERE blocked_gate IS NULL
    GROUP BY bucket
""").fetchall()
print(f"  {'bucket':<12} {'count':>6} {'HIT_TP':>7} {'HIT_SL':>7}")
for bucket, cnt, tp, sl in rows:
    print(f"  {bucket:<12} {cnt:>6} {tp or 0:>7} {sl or 0:>7}")

conn.close()
