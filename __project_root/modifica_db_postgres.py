import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")

def aggiorna_db():
    if not DATABASE_URL:
        raise ValueError("Variabile d'ambiente DATABASE_URL non impostata")

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()

    # =========================
    # CREAZIONE TABELLE PRINCIPALI
    # =========================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS clienti (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            zona TEXT,
            data_registrazione DATE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS prodotti (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            categoria_id INTEGER REFERENCES categorie(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS categorie (
            id SERIAL PRIMARY KEY,
            nome TEXT UNIQUE NOT NULL,
            immagine TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS clienti_prodotti (
            id SERIAL PRIMARY KEY,
            cliente_id INTEGER REFERENCES clienti(id),
            prodotto_id INTEGER REFERENCES prodotti(id),
            lavorato INTEGER DEFAULT 0,
            prezzo_attuale NUMERIC,
            prezzo_offerta NUMERIC,
            data_operazione TIMESTAMP,
            elimina INTEGER DEFAULT 0,
            lascia_vuota INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS prodotti_rimossi (
            id SERIAL PRIMARY KEY,
            cliente_id INTEGER REFERENCES clienti(id),
            prodotto_id INTEGER REFERENCES prodotti(id),
            data_rimozione TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fatturato (
            id SERIAL PRIMARY KEY,
            cliente_id INTEGER REFERENCES clienti(id),
            totale NUMERIC DEFAULT 0,
            mese INTEGER NOT NULL,
            anno INTEGER NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS volantini (
            id SERIAL PRIMARY KEY,
            titolo TEXT NOT NULL,
            sfondo TEXT,
            layout_json TEXT,
            data_creazione TIMESTAMP DEFAULT NOW()
        )
    """)

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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS promo_lampo (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            prezzo NUMERIC NOT NULL,
            immagine TEXT,
            sfondo TEXT,
            data_creazione TIMESTAMP DEFAULT NOW(),
            layout TEXT
        )
    """)

    # =========================
    # AGGIUNTE COLONNE SUPPLEMENTARI
    # =========================

    cur.execute("ALTER TABLE clienti_prodotti ADD COLUMN IF NOT EXISTS prezzo_attuale NUMERIC")
    cur.execute("ALTER TABLE clienti_prodotti ADD COLUMN IF NOT EXISTS prezzo_offerta NUMERIC")
    cur.execute("ALTER TABLE promo_lampo ADD COLUMN IF NOT EXISTS layout TEXT")
    cur.execute("ALTER TABLE volantino_prodotti ADD COLUMN IF NOT EXISTS in_volantino INTEGER DEFAULT 1")
    cur.execute("ALTER TABLE volantino_prodotti ADD COLUMN IF NOT EXISTS eliminato INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE volantino_prodotti ADD COLUMN IF NOT EXISTS lascia_vuota INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE clienti ADD COLUMN IF NOT EXISTS data_registrazione DATE")

    # =========================
    # CONVERSIONE COLONNE JSON -> JSONB PER INDICI GIN
    # =========================

    cur.execute("""
        ALTER TABLE volantini
        ALTER COLUMN layout_json TYPE JSONB USING layout_json::JSONB
    """)
    cur.execute("""
        ALTER TABLE promo_lampo
        ALTER COLUMN layout TYPE JSONB USING layout::JSONB
    """)

    # =========================
    # CREAZIONE INDICI
    # =========================

    cur.execute("CREATE INDEX IF NOT EXISTS idx_clienti_prodotti_cliente ON clienti_prodotti(cliente_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_clienti_prodotti_prodotto ON clienti_prodotti(prodotto_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_prodotti_rimossi_cliente ON prodotti_rimossi(cliente_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_prodotti_rimossi_prodotto ON prodotti_rimossi(prodotto_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fatturato_cliente ON fatturato(cliente_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fatturato_mese_anno ON fatturato(mese, anno)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_volantino_prodotti_volantino ON volantino_prodotti(volantino_id)")

    # 🔹 INDICI GIN JSONB
    cur.execute("CREATE INDEX IF NOT EXISTS idx_volantini_layout_gin ON volantini USING GIN (layout_json)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_promo_layout_gin ON promo_lampo USING GIN (layout)")

    conn.commit()
    conn.close()
    print("Database PostgreSQL aggiornato con successo, inclusi indici GIN per JSONB.")

if __name__ == "__main__":
    aggiorna_db()
