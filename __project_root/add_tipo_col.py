import os
from dotenv import load_dotenv

load_dotenv()
import psycopg2

db_url = os.environ.get("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

if not db_url:
    db_url = "sqlite:///local.db" # locally we might be using sqlite or not see get_db in app.py

from app import get_db

conn = get_db()
cur = conn.cursor()
try:
    cur.execute("ALTER TABLE volantino_beta ADD COLUMN tipo VARCHAR(50) DEFAULT 'volantino'")
    conn.commit()
    print("Colonna aggiunta o esiste gia")
except Exception as e:
    conn.rollback()
    print(f"Errore {e}")
conn.close()
