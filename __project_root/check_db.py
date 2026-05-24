import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(
    host=os.getenv("PGHOST", "localhost"),
    database=os.getenv("PGDATABASE", "gestionale"),
    user=os.getenv("PGUSER", "postgres"),
    password=os.getenv("PGPASSWORD", "")
)
cur = conn.cursor()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
tables = [r[0] for r in cur.fetchall()]
print("Tables List:", tables)
cur.close()
conn.close()
