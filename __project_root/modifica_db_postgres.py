import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")

def aggiorna_db():
    if not DATABASE_URL:
        raise ValueError("Variabile d'ambiente DATABASE_URL non impostata")

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()

    # 🔹 Aggiungi colonne per prezzi clienti sui prodotti
    cur.execute("ALTER TABLE clienti_prodotti ADD COLUMN IF NOT EXISTS prezzo_attuale NUMERIC")
    cur.execute("ALTER TABLE clienti_prodotti ADD COLUMN IF NOT EXISTS prezzo_offerta NUMERIC")

    # 🔹 Aggiungi colonna layout per promo_lampo
    cur.execute("ALTER TABLE promo_lampo ADD COLUMN IF NOT EXISTS layout TEXT")

    # 🔹 Aggiungi flag in_volantino e colonne eliminato/lascia_vuota per volantino_prodotti
    cur.execute("ALTER TABLE volantino_prodotti ADD COLUMN IF NOT EXISTS in_volantino INTEGER DEFAULT 1")
    cur.execute("ALTER TABLE volantino_prodotti ADD COLUMN IF NOT EXISTS eliminato INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE volantino_prodotti ADD COLUMN IF NOT EXISTS lascia_vuota INTEGER DEFAULT 0")

    # 🔹 Aggiungi colonna data_registrazione per clienti
    cur.execute("ALTER TABLE clienti ADD COLUMN IF NOT EXISTS data_registrazione DATE")

    # 🔹 Crea tabella fatturato se non esiste
    cur.execute("""
        CREATE TABLE IF NOT EXISTS fatturato (
            id SERIAL PRIMARY KEY,
            cliente_id INTEGER REFERENCES clienti(id),
            totale NUMERIC DEFAULT 0,
            mese INTEGER NOT NULL,
            anno INTEGER NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    print("Database PostgreSQL aggiornato con successo.")

if __name__ == "__main__":
    aggiorna_db()
