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
        CREATE TABLE IF NOT EXISTS clienti_prodotti (
            id SERIAL PRIMARY KEY
        )
    """)
    # Aggiungi colonne se mancanti
    cur.execute("ALTER TABLE clienti_prodotti ADD COLUMN IF NOT EXISTS cliente_id INTEGER REFERENCES clienti(id)")
    cur.execute("ALTER TABLE clienti_prodotti ADD COLUMN IF NOT EXISTS prodotto_id INTEGER REFERENCES prodotti(id)")
    cur.execute("ALTER TABLE clienti_prodotti ADD COLUMN IF NOT EXISTS data_operazione DATE")
    cur.execute("ALTER TABLE clienti_prodotti ADD COLUMN IF NOT EXISTS prezzo_attuale NUMERIC")
    cur.execute("ALTER TABLE clienti_prodotti ADD COLUMN IF NOT EXISTS prezzo_offerta NUMERIC")

    # ============================
    # CLIENTI
    # ============================
    cur.execute("ALTER TABLE clienti ADD COLUMN IF NOT EXISTS data_registrazione DATE")

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
    # VOLANTINO_PRODOTTI
    # ============================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS volantino_prodotti (
            id SERIAL PRIMARY KEY,
            volantino_id INTEGER REFERENCES volantini(id)
        )
    """)
    cur.execute("ALTER TABLE volantino_prodotti ADD COLUMN IF NOT EXISTS nome TEXT")
    cur.execute("ALTER TABLE volantino_prodotti ADD COLUMN IF NOT EXISTS prezzo NUMERIC")
    cur.execute("ALTER TABLE volantino_prodotti ADD COLUMN IF NOT EXISTS immagine TEXT")
    cur.execute("ALTER TABLE volantino_prodotti ADD COLUMN IF NOT EXISTS in_volantino INTEGER DEFAULT 1")
    cur.execute("ALTER TABLE volantino_prodotti ADD COLUMN IF NOT EXISTS eliminato INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE volantino_prodotti ADD COLUMN IF NOT EXISTS lascia_vuota INTEGER DEFAULT 0")

    # ============================
    # PROMO_LAMPO
    # ============================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS promo_lampo (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            prezzo NUMERIC NOT NULL,
            data_creazione TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("ALTER TABLE promo_lampo ADD COLUMN IF NOT EXISTS immagine TEXT")
    cur.execute("ALTER TABLE promo_lampo ADD COLUMN IF NOT EXISTS sfondo TEXT")
    cur.execute("ALTER TABLE promo_lampo ADD COLUMN IF NOT EXISTS layout TEXT")

    # ============================
    # FATTURATO
    # ============================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS fatturato (
            id SERIAL PRIMARY KEY
        )
    """)
    cur.execute("ALTER TABLE fatturato ADD COLUMN IF NOT EXISTS cliente_id INTEGER REFERENCES clienti(id)")
    cur.execute("ALTER TABLE fatturato ADD COLUMN IF NOT EXISTS totale NUMERIC DEFAULT 0")
    cur.execute("ALTER TABLE fatturato ADD COLUMN IF NOT EXISTS mese INTEGER NOT NULL")
    cur.execute("ALTER TABLE fatturato ADD COLUMN IF NOT EXISTS anno INTEGER NOT NULL")

    conn.commit()
    conn.close()
    print("Database PostgreSQL aggiornato con successo.")

if __name__ == "__main__":
    aggiorna_db()
