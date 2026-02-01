import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")


def aggiorna_db():
    if not DATABASE_URL:
        raise ValueError("Variabile d'ambiente DATABASE_URL non impostata")

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()

    try:
        # ============================
        # CLIENTI
        # ============================
        cur.execute("""
            CREATE TABLE IF NOT EXISTS clienti (
                id SERIAL PRIMARY KEY,
                nome TEXT NOT NULL,
                zona TEXT,
                email TEXT,
                data_registrazione DATE
            )
        """)

        cur.execute("""ALTER TABLE clienti ADD COLUMN IF NOT EXISTS telefono TEXT""")
        cur.execute("""ALTER TABLE clienti ADD COLUMN IF NOT EXISTS whatsapp_linked BOOLEAN NOT NULL DEFAULT FALSE""")
        cur.execute("""ALTER TABLE clienti ADD COLUMN IF NOT EXISTS whatsapp_linked_at TIMESTAMP""")

        # ✅ Preferenze offerte WhatsApp (Meta Cloud API)
        cur.execute("""ALTER TABLE clienti ADD COLUMN IF NOT EXISTS marketing_opt_in BOOLEAN NOT NULL DEFAULT FALSE""")
        cur.execute("""ALTER TABLE clienti ADD COLUMN IF NOT EXISTS marketing_opt_in_at TIMESTAMP""")
        cur.execute("""ALTER TABLE clienti ADD COLUMN IF NOT EXISTS pref_scadenza BOOLEAN NOT NULL DEFAULT FALSE""")
        cur.execute("""ALTER TABLE clienti ADD COLUMN IF NOT EXISTS pref_pesce BOOLEAN NOT NULL DEFAULT FALSE""")
        cur.execute("""ALTER TABLE clienti ADD COLUMN IF NOT EXISTS pref_carne BOOLEAN NOT NULL DEFAULT FALSE""")

        cur.execute("""CREATE INDEX IF NOT EXISTS clienti_telefono_idx ON clienti (telefono)""")
        cur.execute("""CREATE INDEX IF NOT EXISTS clienti_whatsapp_linked_idx ON clienti (whatsapp_linked)""")
        cur.execute("""CREATE INDEX IF NOT EXISTS clienti_marketing_opt_in_idx ON clienti (marketing_opt_in)""")

        # ============================
        # WHATSAPP LINK CODES
        # ============================
        cur.execute("""
            CREATE TABLE IF NOT EXISTS whatsapp_link_codes (
                id SERIAL PRIMARY KEY,
                cliente_id INTEGER NOT NULL REFERENCES clienti(id) ON DELETE CASCADE,
                code TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                used_at TIMESTAMP
            )
        """)

        cur.execute("""CREATE INDEX IF NOT EXISTS whatsapp_link_codes_cliente_idx ON whatsapp_link_codes (cliente_id)""")
        cur.execute("""CREATE INDEX IF NOT EXISTS whatsapp_link_codes_used_at_idx ON whatsapp_link_codes (used_at)""")

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

        cur.execute("""ALTER TABLE prodotti ADD COLUMN IF NOT EXISTS codice VARCHAR(50)""")
        cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS prodotti_codice_unique ON prodotti (codice)""")
        cur.execute("""CREATE INDEX IF NOT EXISTS prodotti_codice_idx ON prodotti (codice)""")

        # ✅ Cancellazione logica
        cur.execute("""
            ALTER TABLE prodotti
            ADD COLUMN IF NOT EXISTS eliminato BOOLEAN NOT NULL DEFAULT FALSE
        """)
        cur.execute("""CREATE INDEX IF NOT EXISTS prodotti_eliminato_idx ON prodotti (eliminato)""")

        # ============================
        # ZONE
        # ============================
        cur.execute("""
            CREATE TABLE IF NOT EXISTS zone (
                id SERIAL PRIMARY KEY,
                nome TEXT UNIQUE NOT NULL
            )
        """)

        # ============================
        # FORNITORI
        # ============================
        cur.execute("""
            CREATE TABLE IF NOT EXISTS fornitori (
                id SERIAL PRIMARY KEY,
                nome TEXT UNIQUE NOT NULL
            )
        """)

        # ============================
        # CLIENTI_PRODOTTI
        # ============================
        cur.execute("""
            CREATE TABLE IF NOT EXISTS clienti_prodotti (
                id SERIAL PRIMARY KEY,
                cliente_id INTEGER REFERENCES clienti(id),
                prodotto_id INTEGER REFERENCES prodotti(id),
                lavorato BOOLEAN DEFAULT FALSE,
                prezzo_attuale NUMERIC,
                prezzo_offerta NUMERIC,
                data_operazione TIMESTAMP DEFAULT NOW()
            )
        """)

        cur.execute("""
            ALTER TABLE clienti_prodotti
            ADD COLUMN IF NOT EXISTS fornitore_id INTEGER REFERENCES fornitori(id)
        """)

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
                id SERIAL PRIMARY KEY,
                cliente_id INTEGER REFERENCES clienti(id),
                totale NUMERIC DEFAULT 0,
                mese INTEGER NOT NULL,
                anno INTEGER NOT NULL
            )
        """)

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
                data_creazione TIMESTAMP DEFAULT NOW(),
                prezzo NUMERIC NOT NULL DEFAULT 0,
                immagine TEXT,
                sfondo TEXT,
                layout TEXT
            )
        """)

        # ============================
        # INDICI
        # ============================
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_clienti_prodotti_cliente ON clienti_prodotti(cliente_id)""")
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_clienti_prodotti_prodotto ON clienti_prodotti(prodotto_id)""")
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_clienti_prodotti_fornitore ON clienti_prodotti(fornitore_id)""")
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_fatturato_cliente_mese_anno ON fatturato(cliente_id, mese, anno)""")
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_volantino_prodotti_volantino ON volantino_prodotti(volantino_id)""")

        conn.commit()
        print("✅ Database PostgreSQL aggiornato con successo.")

    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


if __name__ == "__main__":
    aggiorna_db()
