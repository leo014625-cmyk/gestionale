import sqlite3
db = sqlite3.connect("./__project_root/gestionale.db")
db.execute("""
CREATE TABLE IF NOT EXISTS volantino_beta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome VARCHAR(255) NOT NULL,
    layout_json TEXT NOT NULL,
    thumbnail TEXT,
    tipo VARCHAR(50) DEFAULT 'volantino',
    creato_il DATETIME,
    aggiornato_il DATETIME
)
""")
db.commit()
db.close()
