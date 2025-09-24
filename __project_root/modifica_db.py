import sqlite3

DB_PATH = 'gestionale.db'  # sostituire con il path corretto del DB

def aggiorna_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 🔹 Aggiungi colonne per prezzi clienti sui prodotti, se non esistono
    try:
        c.execute("ALTER TABLE clienti_prodotti ADD COLUMN prezzo_attuale REAL")
    except sqlite3.OperationalError:
        pass  # la colonna esiste già

    try:
        c.execute("ALTER TABLE clienti_prodotti ADD COLUMN prezzo_offerta REAL")
    except sqlite3.OperationalError:
        pass  # la colonna esiste già

    # 🔹 Aggiungi colonna layout per promo_lampo, se non esiste
    try:
        c.execute("ALTER TABLE promo_lampo ADD COLUMN layout TEXT")
    except sqlite3.OperationalError:
        pass  # la colonna esiste già

    # 🔹 Aggiungi flag in_volantino per volantino_prodotti
    try:
        c.execute("ALTER TABLE volantino_prodotti ADD COLUMN in_volantino INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass  # la colonna esiste già

    # 🔹 Aggiungi colonne eliminato e lascia_vuota per gestire volantino_prodotti
    try:
        c.execute("ALTER TABLE volantino_prodotti ADD COLUMN eliminato INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # la colonna esiste già

    try:
        c.execute("ALTER TABLE volantino_prodotti ADD COLUMN lascia_vuota INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # la colonna esiste già

    # 🔹 Eventuali altre colonne/indici senza toccare dati
    # es.: c.execute("ALTER TABLE clienti ADD COLUMN telefono TEXT")

    conn.commit()
    conn.close()
    print("Database aggiornato senza resettare le tabelle.")

if __name__ == "__main__":
    aggiorna_db()

