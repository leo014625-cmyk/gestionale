import os
import psycopg2
from psycopg2.extras import RealDictCursor

# Legge la URL del database da variabile d'ambiente di Render
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise RuntimeError("⚠️ Variabile d'ambiente DATABASE_URL non trovata!")

def crea_tabelle(conn):
    """Crea le tabelle principali se non esistono."""
    with conn.cursor() as c:
        # Tabella clienti
        c.execute("""
        CREATE TABLE IF NOT EXISTS clienti (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            zona TEXT
        )
        """)

        # Tabella categorie
        c.execute("""
        CREATE TABLE IF NOT EXISTS categorie (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            immagine TEXT
        )
        """)

        # Tabella prodotti
        c.execute("""
        CREATE TABLE IF NOT EXISTS prodotti (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            prezzo NUMERIC,
            id_categoria INTEGER REFERENCES categorie(id)
        )
        """)

        # Tabella clienti_prodotti
        c.execute("""
        CREATE TABLE IF NOT EXISTS clienti_prodotti (
            id SERIAL PRIMARY KEY,
            id_cliente INTEGER REFERENCES clienti(id),
            id_prodotto INTEGER REFERENCES prodotti(id),
            prezzo_attuale NUMERIC,
            prezzo_offerta NUMERIC
        )
        """)

        # Tabella promo_lampo
        c.execute("""
        CREATE TABLE IF NOT EXISTS promo_lampo (
            id SERIAL PRIMARY KEY,
            nome TEXT,
            layout TEXT
        )
        """)

        # Tabella volantino_prodotti
        c.execute("""
        CREATE TABLE IF NOT EXISTS volantino_prodotti (
            id SERIAL PRIMARY KEY,
            id_prodotto INTEGER REFERENCES prodotti(id),
            in_volantino BOOLEAN DEFAULT TRUE,
            eliminato BOOLEAN DEFAULT FALSE,
            lascia_vuota BOOLEAN DEFAULT FALSE
        )
        """)

def aggiungi_colonna(conn, table, column, tipo):
    """Aggiunge colonna se non esiste (PostgreSQL)."""
    with conn.cursor() as c:
        c.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 
                FROM information_schema.columns 
                WHERE table_name='{table}' AND column_name='{column}'
            ) THEN
                ALTER TABLE {table} ADD COLUMN {column} {tipo};
            END IF;
        END
        $$;
        """)

def aggiorna_db():
    """Crea/aggiorna il DB PostgreSQL su Render senza cancellare dati."""
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        crea_tabelle(conn)

        # Colonne extra per clienti_prodotti
        aggiungi_colonna(conn, 'clienti_prodotti', 'prezzo_attuale', 'NUMERIC')
        aggiungi_colonna(conn, 'clienti_prodotti', 'prezzo_offerta', 'NUMERIC')

        # Colonna layout per promo_lampo
        aggiungi_colonna(conn, 'promo_lampo', 'layout', 'TEXT')

        # Colonne per volantino_prodotti
        aggiungi_colonna(conn, 'volantino_prodotti', 'in_volantino', 'BOOLEAN DEFAULT TRUE')
        aggiungi_colonna(conn, 'volantino_prodotti', 'eliminato', 'BOOLEAN DEFAULT FALSE')
        aggiungi_colonna(conn, 'volantino_prodotti', 'lascia_vuota', 'BOOLEAN DEFAULT FALSE')

        conn.commit()
        print("✅ Database PostgreSQL aggiornato con successo su Render.")
    finally:
        conn.close()

if __name__ == "__main__":
    aggiorna_db()
