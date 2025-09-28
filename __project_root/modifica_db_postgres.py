import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("⚠️ Variabile d'ambiente DATABASE_URL non trovata!")

def safe_alter_table(cur, table_name, column_name, column_type, default=None):
    """Aggiunge una colonna se non esiste, senza abortire la transazione."""
    default_sql = f" DEFAULT {default}" if default is not None else ""
    cur.execute(f"""
    DO $$
    BEGIN
        BEGIN
            ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}{default_sql};
        EXCEPTION
            WHEN duplicate_column THEN
                -- ignora se la colonna esiste
        END;
    END
    $$;
    """)

def aggiorna_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()

    # 🔹 Colonne aggiuntive per clienti_prodotti
    safe_alter_table(cur, "clienti_prodotti", "prezzo_attuale", "NUMERIC")
    safe_alter_table(cur, "clienti_prodotti", "prezzo_offerta", "NUMERIC")

    # 🔹 Colonna layout per promo_lampo
    safe_alter_table(cur, "promo_lampo", "layout", "TEXT")

    # 🔹 Colonne per volantino_prodotti
    safe_alter_table(cur, "volantino_prodotti", "in_volantino", "INTEGER", default=1)
    safe_alter_table(cur, "volantino_prodotti", "eliminato", "INTEGER", default=0)
    safe_alter_table(cur, "volantino_prodotti", "lascia_vuota", "INTEGER", default=0)

    # 🔹 Creazione tabella fatturato se non esiste
    cur.execute("""
    CREATE TABLE IF NOT EXISTS fatturato (
        id SERIAL PRIMARY KEY,
        mese INTEGER NOT NULL,
        anno INTEGER NOT NULL,
        totale NUMERIC DEFAULT 0
    );
    """)

    conn.commit()
    conn.close()
    print("✅ Database PostgreSQL aggiornato con successo su Render.")

if __name__ == "__main__":
    aggiorna_db()

