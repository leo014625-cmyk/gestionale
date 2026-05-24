import sqlite3

db = sqlite3.connect("./__project_root/gestionale.db")
c = db.cursor()

def add_col(table, col_def):
    try:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
    except sqlite3.OperationalError as e:
        pass

add_col("clienti", "telefono TEXT")
add_col("clienti", "whatsapp_linked INTEGER DEFAULT 0")
add_col("clienti", "whatsapp_linked_at TEXT")
add_col("clienti", "email TEXT")
add_col("clienti", "stato TEXT DEFAULT 'automatico'")
add_col("clienti", "giorno_visita_standard INTEGER")
add_col("clienti", "giorni_consegna_standard TEXT")
add_col("clienti", "ora_visita_standard TEXT")
add_col("clienti", "frequenza_visita TEXT DEFAULT 'settimanale'")

add_col("prodotti", "codice TEXT")
add_col("prodotti", "eliminato INTEGER DEFAULT 0")

add_col("clienti_prodotti", "fornitore_id INTEGER")

c.execute("""
CREATE TABLE IF NOT EXISTS visite (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER REFERENCES clienti(id),
    data_visita TEXT,
    ora_visita TEXT,
    completata INTEGER DEFAULT 0,
    note TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS whatsapp_link_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL REFERENCES clienti(id) ON DELETE CASCADE,
    code TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    used_at TIMESTAMP
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS whatsapp_preferenze (
    cliente_id INTEGER PRIMARY KEY REFERENCES clienti(id) ON DELETE CASCADE,
    opt_out INTEGER NOT NULL DEFAULT 0,
    ricevi_scadenza INTEGER NOT NULL DEFAULT 0,
    ricevi_pesce INTEGER NOT NULL DEFAULT 0,
    ricevi_carne INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS bot_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titolo TEXT NOT NULL,
    contenuto TEXT NOT NULL,
    canale TEXT NOT NULL DEFAULT 'whatsapp',
    tipo TEXT NOT NULL DEFAULT 'promo',
    categoria TEXT,
    consenso INTEGER NOT NULL DEFAULT 1,
    attivo INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS fornitori (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT UNIQUE NOT NULL
)
""")

db.commit()
db.close()
print("Done")
