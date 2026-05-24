import os
import psycopg2
conn_url = os.environ.get('DATABASE_URL')
if conn_url.startswith('postgres://'): conn_url = conn_url.replace('postgres://', 'postgresql://', 1)
conn = psycopg2.connect(conn_url)
cur = conn.cursor()
try:
    cur.execute('ALTER TABLE fatturato ALTER COLUMN prodotto_id DROP NOT NULL')
    print("Column prodotto_id is now nullable.")
except Exception as e:
    print("Error:", e)
conn.commit()
