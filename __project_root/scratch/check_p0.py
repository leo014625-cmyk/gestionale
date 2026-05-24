import os
import psycopg2
conn_url = os.environ.get('DATABASE_URL')
if conn_url.startswith('postgres://'): conn_url = conn_url.replace('postgres://', 'postgresql://', 1)
conn = psycopg2.connect(conn_url)
cur = conn.cursor()
cur.execute('SELECT id FROM prodotti LIMIT 1')
print("First product:", cur.fetchone())
cur.execute('SELECT id FROM prodotti WHERE id=0')
print("Product 0:", cur.fetchone())
