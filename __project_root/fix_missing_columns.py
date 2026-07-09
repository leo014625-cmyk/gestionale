import sqlite3
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# 1. Update SQLite (gestionale.db)
db_path = os.path.join(os.path.dirname(__file__), 'gestionale.db')
print("Updating SQLite...")
try:
    conn_sqlite = sqlite3.connect(db_path)
    cur_sqlite = conn_sqlite.cursor()
    
    # Helper to add columns if not exist
    def add_sqlite_col(table, col_name, col_type):
        try:
            cur_sqlite.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
            print(f"  Added column {col_name} to {table} in SQLite")
        except sqlite3.OperationalError:
            pass # already exists
            
    add_sqlite_col("prodotti", "prezzo", "REAL")
    add_sqlite_col("prodotti", "immagine", "TEXT")
    add_sqlite_col("prodotti", "is_promo_mensile", "INTEGER DEFAULT 0")
    add_sqlite_col("prodotti", "img_zoom", "REAL DEFAULT 1.0")
    add_sqlite_col("prodotti", "img_pos_x", "INTEGER DEFAULT 50")
    add_sqlite_col("prodotti", "img_pos_y", "INTEGER DEFAULT 50")
    
    # Create promozioni_pdf in SQLite if it does not exist
    cur_sqlite.execute("""
        CREATE TABLE IF NOT EXISTS promozioni_pdf (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prodotto_id INTEGER,
            data_caricamento TEXT,
            tipo TEXT,
            prezzo TEXT,
            scadenza TEXT
        )
    """)
    print("  Ensured table 'promozioni_pdf' exists in SQLite")
    
    conn_sqlite.commit()
    conn_sqlite.close()
    print("SQLite update complete!")
except Exception as e:
    print(f"Error updating SQLite: {e}")

# 2. Update PostgreSQL
print("Updating PostgreSQL...")
db_url = os.getenv("DATABASE_URL")
if db_url:
    try:
        conn_pg = psycopg2.connect(db_url)
        cur_pg = conn_pg.cursor()
        
        # Helper to add columns if not exist
        def add_pg_col(table, col_name, col_type):
            try:
                cur_pg.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_type}")
                print(f"  Added column {col_name} to {table} in PostgreSQL")
            except Exception as ex:
                print(f"  Failed/skipped adding {col_name} to {table} in PG: {ex}")
                conn_pg.rollback()
                return
            conn_pg.commit()
            
        add_pg_col("prodotti", "prezzo", "NUMERIC")
        add_pg_col("prodotti", "immagine", "TEXT")
        add_pg_col("prodotti", "is_promo_mensile", "BOOLEAN DEFAULT FALSE")
        add_pg_col("prodotti", "img_zoom", "NUMERIC DEFAULT 1.0")
        add_pg_col("prodotti", "img_pos_x", "INTEGER DEFAULT 50")
        add_pg_col("prodotti", "img_pos_y", "INTEGER DEFAULT 50")
        
        cur_pg.execute("""
            CREATE TABLE IF NOT EXISTS promozioni_pdf (
                id SERIAL PRIMARY KEY,
                prodotto_id INTEGER REFERENCES prodotti(id),
                data_caricamento TIMESTAMP DEFAULT NOW(),
                tipo VARCHAR(50),
                prezzo VARCHAR(50),
                scadenza TEXT
            )
        """)
        conn_pg.commit()
        print("  Ensured table 'promozioni_pdf' exists in PostgreSQL")
        
        cur_pg.close()
        conn_pg.close()
        print("PostgreSQL update complete!")
    except Exception as e:
        print(f"Error updating PostgreSQL: {e}")
else:
    print("PostgreSQL connection string not found in environment variables.")
