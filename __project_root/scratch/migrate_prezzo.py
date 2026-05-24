import psycopg2
DATABASE_URL = "postgresql://gestionale_kg5k_user:Lvw5DUBiSpSogfNzUuBHNNKostYsd5d0@dpg-d3bgkmre5dus73chcht0-a.oregon-postgres.render.com/gestionale_kg5k?sslmode=require"
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()
cur.execute("ALTER TABLE promozioni_pdf ALTER COLUMN prezzo TYPE VARCHAR(50)")
conn.commit()
print("Migration successful: promozioni_pdf.prezzo is now VARCHAR(50)")
conn.close()
