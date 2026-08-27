import sqlite3
conn = sqlite3.connect('data/signals.db')
for t in ['signals', 'signal_outcomes', 'signal_candidates', 'decision_traces', 'context_snapshots', 'bot_settings']:
    try:
        count = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
        print(f'  {t}: {count} rows')
    except:
        print(f'  {t}: ERROR')
conn.close()
