import os
import sqlite3

# Percorso al database
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, 'gestionale.db')

# Connessione al database
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Verifica se esiste la categoria "Alimentari"
cur.execute("SELECT id FROM categorie WHERE LOWER(nome) = 'alimentari'")
row = cur.fetchone()

if row:
    # Aggiorna immagine della categoria
    cur.execute(
        "UPDATE categorie SET immagine = ? WHERE id = ?",
        ('alimentari.jpg', row[0])
    )
    print("Categoria 'Alimentari' aggiornata con immagine 'alimentari.jpg'.")
else:
    # Inserisce nuova categoria con immagine
    cur.execute(
        "INSERT INTO categorie (nome, immagine) VALUES (?, ?)",
        ('Alimentari', 'alimentari.jpg')
    )
    print("Categoria 'Alimentari' creata con immagine 'alimentari.jpg'.")

# Salva e chiudi
conn.commit()
conn.close()
