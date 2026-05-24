import psycopg2
DATABASE_URL = "postgresql://gestionale_kg5k_user:Lvw5DUBiSpSogfNzUuBHNNKostYsd5d0@dpg-d3bgkmre5dus73chcht0-a.oregon-postgres.render.com/gestionale_kg5k?sslmode=require"
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='volantino_prodotti'")
for r in cur.fetchall():
    print(r[0])
conn.close()
