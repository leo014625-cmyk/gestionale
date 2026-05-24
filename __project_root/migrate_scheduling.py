import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')

def migrate():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        print("Adding columns to 'clienti' table...")
        cur.execute("ALTER TABLE clienti ADD COLUMN IF NOT EXISTS ora_visita_standard TIME;")
        cur.execute("ALTER TABLE clienti ADD COLUMN IF NOT EXISTS frequenza_visita TEXT DEFAULT 'settimanale';")
        
        conn.commit()
        print("Migration completed successfully.")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    migrate()
