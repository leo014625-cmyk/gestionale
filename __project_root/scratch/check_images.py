import psycopg2
DATABASE_URL = "postgresql://gestionale_kg5k_user:Lvw5DUBiSpSogfNzUuBHNNKostYsd5d0@dpg-d3bgkmre5dus73chcht0-a.oregon-postgres.render.com/gestionale_kg5k?sslmode=require"
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()
cur.execute("SELECT count(*) FROM prodotti WHERE immagine IS NOT NULL AND immagine != ''")
print(f"Products with images: {cur.fetchone()[0]}")
cur.execute("SELECT count(*) FROM prodotti")
print(f"Total products: {cur.fetchone()[0]}")
conn.close()
