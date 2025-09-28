import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")

def aggiorna_db():
    if not DATABASE_URL:
        raise ValueError("Variabile d'ambiente DATABASE_URL non impostata")

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()

    # ============================
    # CLIENTI_PRODOTTI
    # ============================
    cur.execute("""
        ALTER TABLE clienti_prodotti
        ADD COLUMN IF NOT EXISTS prezzo_attuale NUMERIC,
        ADD COLUMN IF NOT EXISTS prezzo_offerta NUMERIC,
        ADD COLUMN IF NOT EXISTS cliente_id INTEGER REFERENCES clienti(id)
    """)

    # ============================
    # VOLANTINO_PRODOTTI
    # ============================
    cur.execute("""
        ALTER TABLE volantino_prodotti
        ADD COLUMN IF NOT EXISTS in_volantino INTEGER DEFAULT 1,
        ADD COLUMN IF NOT EXISTS eliminato INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS lascia_vuota INTEGER DEFAULT 0
    """)

    # ============================
    # CLIENTI
    # ============================
    cur.execute("ALTER TABLE clienti ADD COLUMN IF NOT EXISTS data_registrazione DATE")

    # ============================
    # PROMO_LAMPO
    # ============================
    cur.execute("ALTER TABLE promo_lampo ADD COLUMN IF NOT EXISTS layout TEXT")

    # ============================
    # VOLANTINI
    # ============================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS volantini (
            id SERIAL PRIMARY KEY,
            titolo TEXT NOT NULL,
            sfondo TEXT,
            layout_json TEXT,
            data_creazione TIMESTAMP DEFAULT NOW()
        )
    """)

    # ============================
    # VOLANTINO_PRODOTTI (già aggiunto sopra, ma assicuriamo la tabella)
    # ============================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS volantino_prodotti (
            id SERIAL PRIMARY KEY,
            volantino_id INTEGER REFERENCES volantini(id),
            nome TEXT,
            prezzo NUMERIC,
            immagine TEXT,
            in_volantino INTEGER DEFAULT 1,
            eliminato INTEGER DEFAULT 0,
            lascia_vuota INTEGER DEFAULT 0
        )
    """)

    # ============================
    # PROMO_LAMPO (già aggiunto sopra, ma assicuriamo la tabella)
    # ============================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS promo_lampo (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            prezzo NUMERIC NOT NULL,
            immagine TEXT,
            sfondo TEXT,
            layout TEXT,
            data_creazione TIMESTAMP DEFAULT NOW()
        )
    """)

    # ============================
    # FATTURATO
    # ============================
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
