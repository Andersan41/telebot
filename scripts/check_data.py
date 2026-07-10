import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "signals.db"
conn = sqlite3.connect(str(DB))
c = conn.cursor()

c.execute("SELECT COUNT(*) FROM decision_traces")
total = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM decision_traces WHERE signal_generated = 1")
signals = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM decision_traces WHERE outcome IS NOT NULL")
with_outcome = c.fetchone()[0]
c.execute("SELECT MIN(timestamp), MAX(timestamp) FROM decision_traces")
dates = c.fetchone()
c.execute("SELECT strategy_version, COUNT(*) FROM decision_traces GROUP BY strategy_version")
versions = c.fetchall()
c.execute("SELECT outcome, COUNT(*) FROM decision_traces WHERE outcome IS NOT NULL GROUP BY outcome")
outcomes = c.fetchall()

gates = [
    "gate_cooldown","gate_portfolio_risk","gate_btc_global_trend","gate_indicators",
    "gate_confirm_tf","gate_signal_engine","gate_distance_filter","gate_tp_path",
    "gate_mtf_alignment","gate_btc_correlation","gate_eth_correlation","gate_volatility",
    "gate_context_timeout","gate_context_block","gate_context_min_verdict","gate_news",
    "gate_sl_distance","gate_rr_guard","gate_no_trade_zones","gate_dynamic_risk",
    "gate_confidence_v2","gate_dedup","gate_compression_block"
]
gate_activity = []
for g in gates:
    c.execute("SELECT COUNT(*) FROM decision_traces WHERE %s = 0" % g)
    blocked = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM decision_traces WHERE %s IS NOT NULL" % g)
    entered = c.fetchone()[0]
    gate_activity.append((g, entered, blocked))

conn.close()

print("=" * 60)
print("DATA VOLUME CHECK")
print("=" * 60)
print("Total traces:      %d" % total)
print("Signals generated: %d" % signals)
print("With outcome:      %d" % with_outcome)
print("Date range:        %s -> %s" % (dates[0], dates[1]))
print("Versions:          %s" % versions)
print("Outcomes:          %s" % outcomes)

print()
print("=" * 60)
print("REQUIREMENTS")
print("=" * 60)
r1 = with_outcome >= 2000
r2 = signals >= 50
r3 = with_outcome > 0
print("  2000+ outcomes:  %6d / 2000   %s" % (with_outcome, "PASS" if r1 else "FAIL"))
print("  50+ signals:     %6d / 50     %s" % (signals, "PASS" if r2 else "FAIL"))
tp_sl = "YES" if r3 else "NO"
print("  TP/SL data:      %6s          %s" % (tp_sl, "PASS" if r3 else "FAIL"))

print()
print("=" * 60)
print("GATE ACTIVITY (all gates)")
print("=" * 60)
for g, e, b in gate_activity:
    rate = b / max(e, 1) * 100
    print("  %-30s  entered=%5d  blocked=%5d  rate=%5.1f%%" % (g, e, b, rate))

print()
print("=" * 60)
print("VERDICT")
print("=" * 60)
if r1 and r2 and r3:
    print("  READY for Gate Redundancy Validation")
else:
    missing = []
    if not r1:
        missing.append("%d more outcomes" % (2000 - with_outcome))
    if not r2:
        missing.append("%d more signals" % (50 - signals))
    if not r3:
        missing.append("any TP/SL outcomes")
    print("  NOT READY. Need: %s" % ", ".join(missing))
