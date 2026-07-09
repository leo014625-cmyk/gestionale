import os
from dotenv import load_dotenv
load_dotenv('.env')

from app import app
from psycopg2.extras import RealDictCursor
from app import get_db

app.config['TESTING'] = True
app.config['WTF_CSRF_ENABLED'] = False
app.config['LOGIN_DISABLED'] = True

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        
    print("Test: POST /clienti/modifica/13/salva_categorie_pdf")
    
    # Cerchiamo i prodotti appena creati
    prodotti_da_categorizzare = []
    
    with app.app_context():
        with get_db() as db:
            cur = db.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT id FROM categorie LIMIT 1")
            cat = cur.fetchone()
            cat_id = cat['id'] if cat else 1
            
            cur.execute("SELECT id FROM prodotti WHERE categoria_id IS NULL AND nome LIKE '%Test%' OR nome='Birra Artigianale Speziata 33cl'")
            for p in cur.fetchall():
                prodotti_da_categorizzare.append(p['id'])
                
    if not prodotti_da_categorizzare:
        # Prende i primi tre
        with app.app_context():
            with get_db() as db:
                cur = db.cursor(cursor_factory=RealDictCursor)
                cur.execute("SELECT id FROM prodotti WHERE categoria_id IS NULL LIMIT 3")
                prodotti_da_categorizzare = [p['id'] for p in cur.fetchall()]

    data = {}
    for pid in prodotti_da_categorizzare:
        data[f'categoria[{pid}]'] = str(cat_id)
        
    print("Inviando data:", data)
    
    resp_post = client.post('/clienti/modifica/13/salva_categorie_pdf', data=data, follow_redirects=True)
    print("POST Status:", resp_post.status_code)
    
    if 'danger' in resp_post.text or 'warning' in resp_post.text or 'success' in resp_post.text:
        print("Found flash messages:")
        import re
        matches = re.findall(r'alert-(danger|warning|success).*?>(.*?)</div', resp_post.text, re.DOTALL)
        for m in matches: print(f"Flash {m[0].upper()}:", m[1].strip())
        
    if resp_post.status_code != 200:
        print("SERVER ERROR TEXT:")
        print(resp_post.text[:2000])
