import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')

def check():
    if not DATABASE_URL:
        print("DATABASE_URL not set")
        return
    
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM clienti")
    print(f"Clienti: {cur.fetchone()['count']}")
    
    cur.execute("SELECT COUNT(*) FROM prodotti")
    print(f"Prodotti: {cur.fetchone()['count']}")
    
    cur.execute("SELECT COUNT(*) FROM categorie")
    print(f"Categorie: {cur.fetchone()['count']}")
    
    cur.execute("SELECT COUNT(*) FROM volantini")
    print(f"Volantini: {cur.fetchone()['count']}")
    
    conn.close()

if __name__ == '__main__':
    check()
