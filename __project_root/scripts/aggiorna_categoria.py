import os
import sqlite3

# Percorso al database
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'gestionale.db')


def aggiungi_categoria(nome_categoria, link_immagine=None):
    """
    Aggiunge una nuova categoria al database.
    :param nome_categoria: nome della categoria
    :param link_immagine: link opzionale dell'immagine
    """
    nome_categoria = nome_categoria.strip()
    link_immagine = link_immagine.strip() if link_immagine else None

    if not nome_categoria:
        raise ValueError("Il nome della categoria non può essere vuoto.")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO categorie (nome, immagine) VALUES (?, ?)",
        (nome_categoria, link_immagine)
    )
    conn.commit()
    conn.close()
    print(f"✅ Categoria '{nome_categoria}' aggiunta con immagine: {link_immagine}")


def modifica_categoria(vecchio_nome, nuovo_nome, link_immagine=None):
    """
    Modifica una categoria esistente.
    :param vecchio_nome: nome attuale della categoria
    :param nuovo_nome: nuovo nome della categoria
    :param link_immagine: nuovo link immagine (opzionale)
    """
    nuovo_nome = nuovo_nome.strip()
    link_immagine = link_immagine.strip() if link_immagine else None

    if not nuovo_nome:
        raise ValueError("Il nuovo nome della categoria non può essere vuoto.")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "UPDATE categorie SET nome = ?, immagine = ? WHERE nome = ?",
        (nuovo_nome, link_immagine, vecchio_nome)
    )
    conn.commit()
    conn.close()
    print(f"✏️ Categoria '{vecchio_nome}' modificata in '{nuovo_nome}' con immagine: {link_immagine}")


def elimina_categoria(nome_categoria):
    """
    Elimina una categoria dal database.
    :param nome_categoria: nome della categoria da eliminare
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM categorie WHERE nome = ?", (nome_categoria,))
    conn.commit()
    conn.close()
    print(f"🗑️ Categoria '{nome_categoria}' eliminata.")


# Esempi di utilizzo
if __name__ == "__main__":
    # aggiungi_categoria("Bevande", "https://example.com/bevande.jpg")
    # modifica_categoria("Bevande", "Drink", "https://example.com/drink.jpg")
    # elimina_categoria("Drink")
    pass
