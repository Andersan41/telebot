import sqlite3
for db_path in ['signals.db', 'data/signals.db']:
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
        print(f'\n{db_path}: {tables}')
        for t in tables:
            count = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
            if count > 0:
                print(f'  {t}: {count} rows')
        conn.close()
    except Exception as e:
        print(f'{db_path}: {e}')
