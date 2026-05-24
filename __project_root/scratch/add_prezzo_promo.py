import psycopg2
import os
DATABASE_URL = "postgresql://gestionale_kg5k_user:Lvw5DUBiSpSogfNzUuBHNNKostYsd5d0@dpg-d3bgkmre5dus73chcht0-a.oregon-postgres.render.com/gestionale_kg5k?sslmode=require"
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()
try:
    cur.execute('ALTER TABLE promozioni_pdf ADD COLUMN IF NOT EXISTS prezzo NUMERIC(10,2)')
    conn.commit()
    print("Column 'prezzo' added to 'promozioni_pdf'")
except Exception as e:
    print(f"Error: {e}")
conn.close()
