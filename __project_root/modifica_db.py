import sqlite3

DB_PATH = 'gestionale.db'  # sostituire con il path corretto del DB

def aggiorna_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 🔹 Aggiungi colonne per prezzi clienti sui prodotti, se non esistono
    try:
        c.execute("ALTER TABLE clienti_prodotti ADD COLUMN prezzo_attuale REAL")
        print("Colonna prezzo_attuale aggiunta a clienti_prodotti")
    except sqlite3.OperationalError:
        pass  # la colonna esiste già

    try:
        c.execute("ALTER TABLE clienti_prodotti ADD COLUMN prezzo_offerta REAL")
        print("Colonna prezzo_offerta aggiunta a clienti_prodotti")
    except sqlite3.OperationalError:
        pass  # la colonna esiste già

    # 🔹 Aggiungi colonna layout per promo_lampo
    try:
        c.execute("ALTER TABLE promo_lampo ADD COLUMN layout TEXT")
        print("Colonna layout aggiunta a promo_lampo")
    except sqlite3.OperationalError:
        pass  # la colonna esiste già

    # 🔹 Aggiungi colonne per volantino_prodotti
    try:
        c.execute("ALTER TABLE volantino_prodotti ADD COLUMN in_volantino INTEGER DEFAULT 1")
        print("Colonna in_volantino aggiunta a volantino_prodotti")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE volantino_prodotti ADD COLUMN eliminato INTEGER DEFAULT 0")
        print("Colonna eliminato aggiunta a volantino_prodotti")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE volantino_prodotti ADD COLUMN lascia_vuota INTEGER DEFAULT 0")
        print("Colonna lascia_vuota aggiunta a volantino_prodotti")
    except sqlite3.OperationalError:
        pass

    # 🔹 Crea tabella fatturato se non esiste
    c.execute("""
    CREATE TABLE IF NOT EXISTS fatturato (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mese INTEGER NOT NULL,
        anno INTEGER NOT NULL,
        totale REAL DEFAULT 0,
        data_creazione TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    print("Tabella fatturato creata o già esistente")

    conn.commit()
    conn.close()
    print("Database aggiornato senza resettare le tabelle.")

if __name__ == "__main__":
    aggiorna_db()
