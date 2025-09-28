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
    # CLIENTI
    # ============================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clienti (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            zona TEXT,
            telefono TEXT,
            email TEXT
        )
    """)
    cur.execute("ALTER TABLE clienti ADD COLUMN IF NOT EXISTS data_registrazione DATE")

    # ============================
    # CATEGORIE
    # ============================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS categorie (
            id SERIAL PRIMARY KEY,
            nome TEXT UNIQUE NOT NULL,
            immagine TEXT
        )
    """)

    # ============================
    # PRODOTTI
    # ============================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prodotti (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            categoria_id INTEGER REFERENCES categorie(id)
        )
    """)

    # ============================
    # CLIENTI_PRODOTTI
    # ============================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clienti_prodotti (
            id SERIAL PRIMARY KEY
        )
    """)
    cur.execute("ALTER TABLE clienti_prodotti ADD COLUMN IF NOT EXISTS cliente_id INTEGER REFERENCES clienti(id)")
    cur.execute("ALTER TABLE clienti_prodotti ADD COLUMN IF NOT EXISTS prodotto_id INTEGER REFERENCES prodotti(id)")
    cur.execute("ALTER TABLE clienti_prodotti ADD COLUMN IF NOT EXISTS lavorato BOOLEAN DEFAULT FALSE")
    cur.execute("ALTER TABLE clienti_prodotti ADD COLUMN IF NOT EXISTS prezzo_attuale NUMERIC")
    cur.execute("ALTER TABLE clienti_prodotti ADD COLUMN IF NOT EXISTS prezzo_offerta NUMERIC")
    cur.execute("ALTER TABLE clienti_prodotti ADD COLUMN IF NOT EXISTS data_operazione TIMESTAMP DEFAULT NOW()")

    # ============================
    # PRODOTTI_RIMOSSI
    # ============================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prodotti_rimossi (
            id SERIAL PRIMARY KEY,
            cliente_id INTEGER REFERENCES clienti(id),
            prodotto_id INTEGER REFERENCES prodotti(id),
            data_rimozione TIMESTAMP DEFAULT NOW()
        )
    """)

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
            id_prodotto INTEGER REFERENCES prodotti(id),
            volantino_id INTEGER REFERENCES volantini(id),
            nome TEXT,
            prezzo NUMERIC,
            immagine TEXT,
            in_volantino BOOLEAN DEFAULT TRUE,
            eliminato BOOLEAN DEFAULT FALSE,
            lascia_vuota BOOLEAN DEFAULT FALSE
        )
    """)

    # ============================
    # PROMO_LAMPO
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
    # INDICI UTILI
    # ============================
    cur.execute("CREATE INDEX IF NOT EXISTS idx_clienti_prodotti_cliente ON clienti_prodotti(cliente_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_clienti_prodotti_prodotto ON clienti_prodotti(prodotto_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fatturato_cliente_mese_anno ON fatturato(cliente_id, mese, anno)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_volantino_prodotti_volantino ON volantino_prodotti(volantino_id)")

    conn.commit()
    conn.close()
    print("Database PostgreSQL aggiornato con successo.")

if __name__ == "__main__":
    aggiorna_db()
