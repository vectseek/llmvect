import sqlite3
conn = sqlite3.connect('llm_china.db')
c = conn.cursor()
tables = ['api_keys', 'model_ratings', 'arena4_battles', 'arena4_votes', 'audit_log', 'user_fingerprints']
for t in tables:
    try:
        count = c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
        print(f'{t}: {count}')
    except Exception as e:
        print(f'{t}: ERROR {e}')
# Check model_routing
rows = c.execute('SELECT * FROM model_routing LIMIT 5').fetchall()
print(f'model_routing sample: {rows[:3]}')
conn.close()
