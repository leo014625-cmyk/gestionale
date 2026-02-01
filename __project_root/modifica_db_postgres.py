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
                telefono TEXT,
                email TEXT,
                data_registrazione DATE
            )
        """)

        # ✅ Compatibilità DB già esistente: assicurati che 'telefono' esista
        cur.execute("""
            ALTER TABLE clienti
            ADD COLUMN IF NOT EXISTS telefono TEXT
        """)

        # ✅ Indice per ricerche su telefono (utile per lookup/controlli)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS clienti_telefono_idx
            ON clienti (telefono)
        """)

        # ============================
        # WHATSAPP LINK CODES (collegamento WA -> Cliente)
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
        cur.execute("""
            CREATE INDEX IF NOT EXISTS whatsapp_link_codes_cliente_idx
            ON whatsapp_link_codes (cliente_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS whatsapp_link_codes_used_at_idx
            ON whatsapp_link_codes (used_at)
        """)

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

        # 🔥 CODICE PRODOTTO (compatibile con DB esistente)
        cur.execute("""
            ALTER TABLE prodotti
            ADD COLUMN IF NOT EXISTS codice VARCHAR(50)
        """)

        # Indici per codice (ricerca + unicità)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS prodotti_codice_unique
            ON prodotti (codice)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS prodotti_codice_idx
            ON prodotti (codice)
        """)

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
                lavora
