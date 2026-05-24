import os
import psycopg2

db_url = "postgresql://gestionale_kg5k_user:Lvw5DUBiSpSogfNzUuBHNNKostYsd5d0@dpg-d3bgkmre5dus73chcht0-a.oregon-postgres.render.com/gestionale_kg5k"

try:
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute("ALTER TABLE volantino_beta ADD COLUMN tipo VARCHAR(50) DEFAULT 'volantino'")
    conn.commit()
    print("Colonna aggiunta con successo.")
    cur.close()
    conn.close()
except Exception as e:
    print(f"Errore: {e}")
