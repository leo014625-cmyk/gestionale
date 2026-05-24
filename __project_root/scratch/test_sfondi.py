import os
import psycopg2
from psycopg2.extras import RealDictCursor

db_url = 'postgresql://gestionale_kg5k_user:Lvw5DUBiSpSogfNzUuBHNNKostYsd5d0@dpg-d3bgkmre5dus73chcht0-a.oregon-postgres.render.com/gestionale_kg5k?sslmode=require'

try:
    conn = psycopg2.connect(db_url)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, nome, immagine FROM volantini_sfondi ORDER BY id DESC")
    rows = cur.fetchall()
    print("SUCCESS: Fetched", len(rows), "backgrounds")
    for r in rows:
        print(f"- {r['nome']} ({r['immagine']})")
except Exception as e:
    print("FAILURE:", e)
