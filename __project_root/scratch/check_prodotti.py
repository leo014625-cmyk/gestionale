import psycopg2
import os
DATABASE_URL = "postgresql://gestionale_kg5k_user:Lvw5DUBiSpSogfNzUuBHNNKostYsd5d0@dpg-d3bgkmre5dus73chcht0-a.oregon-postgres.render.com/gestionale_kg5k?sslmode=require"
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()
cur.execute("SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name='prodotti'")
for r in cur.fetchall():
    print(f"{r[0]}: {r[1]} (Nullable: {r[2]})")
conn.close()
