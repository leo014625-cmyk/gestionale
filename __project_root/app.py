import os
import json
import sqlite3
from functools import wraps
from contextlib import contextmanager
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from jinja2 import FileSystemLoader
from collections import defaultdict
from werkzeug.utils import secure_filename
from dateutil.relativedelta import relativedelta
from PIL import Image, ImageDraw
import psycopg2
from psycopg2.extras import RealDictCursor
import re
import time
import traceback
from pathlib import Path
import requests
import pdfplumber

# ============================
# PATH STATIC E PLACEHOLDER
# ============================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))  # __project_root
TEMPLATES_DIR = os.path.join(BASE_DIR, "_templates")  # cartella _templates dentro __project_root

# Static si trova in ../gestionale/static
STATIC_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "gestionale", "static"))
NO_IMAGE_PATH = os.path.join(STATIC_DIR, "no-image.png")

# 🔹 Crea immagine placeholder se non esiste
if not os.path.exists(NO_IMAGE_PATH):
    os.makedirs(STATIC_DIR, exist_ok=True)
    img = Image.new("RGB", (100, 100), color=(220, 220, 220))  # grigio chiaro
    draw = ImageDraw.Draw(img)
    draw.text((10, 40), "No Img", fill=(100, 100, 100))
    img.save(NO_IMAGE_PATH)
    print("✅ Immagine placeholder no-image.png creata automaticamente")

# ============================
# CONFIGURAZIONE FLASK
# ============================
app = Flask(
    __name__,
    template_folder=TEMPLATES_DIR,
    static_folder=STATIC_DIR
)

# Forza loader Jinja sulla cartella corretta
app.jinja_loader = FileSystemLoader(TEMPLATES_DIR)

# Secret key per session
app.secret_key = 'la_tua_chiave_segreta_sicura'

# SQLAlchemy (for VolantinoBeta and new features)
db_url = os.environ.get("DATABASE_URL", "")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
# In locale usa SQLite, su Render usa PostgreSQL
if os.environ.get("ON_RENDER") and db_url:
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "local.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

class VolantinoBeta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), nullable=False)
    layout_json = db.Column(db.Text, nullable=False)
    thumbnail = db.Column(db.Text)
    tipo = db.Column(db.String(50), default='volantino')
    creato_il = db.Column(db.DateTime, default=datetime.utcnow)
    aggiornato_il = db.Column(db.DateTime)

with app.app_context():
    db.create_all()

# Additional Config
app.config["UPLOAD_FOLDER_VOLANTINI"] = os.path.join(STATIC_DIR, "uploads", "volantini")
app.config["UPLOAD_FOLDER_PROMO"] = os.path.join(STATIC_DIR, "uploads", "promo")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


# ============================
# UPLOAD CATEGORIE
# ============================
CATEGORIE_UPLOAD_FOLDER = os.path.join(STATIC_DIR, 'uploads', 'categorie')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
os.makedirs(CATEGORIE_UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ============================
# DEBUG
# ============================
print("DEBUG - BASE_DIR:", BASE_DIR)
print("DEBUG - STATIC_DIR:", STATIC_DIR)
print("DEBUG - TEMPLATES_DIR:", TEMPLATES_DIR)
print("DEBUG - app.jinja_loader searchpath:", app.jinja_loader.searchpath)
if os.path.exists(TEMPLATES_DIR):
    print("DEBUG - os.listdir(TEMPLATES_DIR):", os.listdir(TEMPLATES_DIR))
else:
    print("⚠️ DEBUG - TEMPLATES_DIR non trovato:", TEMPLATES_DIR)

# ============================
# CONTEXT PROCESSOR
# ============================
@app.context_processor
def inject_now():
    """Rende disponibile current_year in tutti i template"""
    return {'current_year': datetime.now().year}

# ============================
# DATABASE POSTGRESQL
# ============================
# Legge la URL del database da variabile d'ambiente (Render)
DATABASE_URL = os.environ.get('DATABASE_URL')  # es. postgres://user:pass@host:port/dbname

class SQLiteCursorWrapper:
    """Adatta un cursor SQLite a essere compatibile con psycopg2 RealDictCursor."""
    def __init__(self, cursor):
        self._cursor = cursor
    def execute(self, query, params=None):
        import re as _re
        query = _re.sub(r'%s', '?', query)
        query = _re.sub(r'make_date\(([^,]+),\s*([^,]+),\s*1\)',
                        r"date(printf('%04d-%02d-01', \\1, \\2))", query)
        query = _re.sub(r'\s+RETURNING\s+\w+', '', query, flags=_re.IGNORECASE)
        if params is not None:
            self._cursor.execute(query, params)
        else:
            self._cursor.execute(query)
    def executemany(self, query, seq_of_parameters):
        import re as _re
        query = _re.sub(r'%s', '?', query)
        query = _re.sub(r'make_date\(([^,]+),\s*([^,]+),\s*1\)',
                        r"date(printf('%04d-%02d-01', \\1, \\2))", query)
        query = _re.sub(r'\s+RETURNING\s+\w+', '', query, flags=_re.IGNORECASE)
        self._cursor.executemany(query, seq_of_parameters)
    def _conv(self, row):
        if not row: return row
        d = dict(row)
        for k,v in list(d.items()):
            kl = k.lower()
            if kl.startswith("coalesce("): d["coalesce"] = v
            elif kl.startswith("sum("): d["sum"] = v
        return d
    def fetchone(self): return self._conv(self._cursor.fetchone())
    def fetchall(self): return [self._conv(r) for r in (self._cursor.fetchall() or [])]
    def __iter__(self):
        for row in self._cursor: yield self._conv(row)
    @property
    def lastrowid(self): return self._cursor.lastrowid
    def close(self): self._cursor.close()
    def __getattr__(self, name): return getattr(self._cursor, name)

class SQLiteConnWrapper:
    """Adatta una connessione SQLite a essere compatibile con psycopg2."""
    def __init__(self, conn):
        self._conn = conn
    def cursor(self, cursor_factory=None):
        return SQLiteCursorWrapper(self._conn.cursor())
    def execute(self, query, params=None):
        cur = self.cursor(); cur.execute(query, params); return cur
    def commit(self): self._conn.commit()
    def rollback(self): self._conn.rollback()
    def close(self): self._conn.close()

@contextmanager
def get_db():
    """Connessione DB. Tenta PostgreSQL; se offline usa gestionale.db (SQLite)."""
    if not DATABASE_URL:
        raise ValueError("❌ Variabile d'ambiente DATABASE_URL non settata")
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        yield conn
    except psycopg2.OperationalError as e:
        print(f"⚠️ POSTGRESQL non disponibile: {e}")
        print("⚠️ Uso SQLite locale (gestionale.db)")
        sqlite_raw = sqlite3.connect(os.path.join(BASE_DIR, 'gestionale.db'))
        sqlite_raw.row_factory = sqlite3.Row
        conn = SQLiteConnWrapper(sqlite_raw)
        yield conn
    finally:
        if conn: conn.close()


# ============================
# LOGIN WRAPPER
# ============================
USERNAME = 'admin'
PASSWORD = 'password123'

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash("Devi effettuare il login per accedere.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ============================
# TEST ROUTE
# ============================
@app.route('/test-login')
def test_login():
    return render_template('00_login.html')

# ============================
# LOGIN / LOGOUT ROUTE
# ============================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if username == USERNAME and password == PASSWORD:
            session['logged_in'] = True
            flash(f'Benvenuto {username}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Credenziali non valide', 'danger')
            return render_template('00_login.html')
    return render_template('00_login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Sei stato disconnesso con successo.', 'success')
    return redirect(url_for('login'))

@app.route('/test')
@login_required
def test():
    return "Test OK"

# ============================
# TEMPLATE FILTER
# ============================
@app.template_filter('mese_nome')
def mese_nome_filter(mese_num):
    mesi = [
        "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"
    ]
    try:
        return mesi[int(mese_num)-1]
    except (IndexError, ValueError, TypeError):
        return mese_num

def ordina_fatturato_mensile(fatturato_dict):
    def keyfunc(item):
        mese_anno = item[0]
        try:
            return datetime.strptime(mese_anno, "%m/%Y")
        except Exception:
            return datetime.min
    return sorted(fatturato_dict.items(), key=keyfunc)

# ============================
# INIZIALIZZAZIONE DATABASE
# ============================
def init_db():
    statements = [
        '''CREATE TABLE IF NOT EXISTS zone (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL UNIQUE
        )''',
        '''CREATE TABLE IF NOT EXISTS categorie (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL UNIQUE
        )''',
        '''CREATE TABLE IF NOT EXISTS prodotti (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            categoria_id INTEGER REFERENCES categorie(id)
        )''',
        '''CREATE TABLE IF NOT EXISTS clienti (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            zona TEXT NOT NULL,
            fatturato_totale REAL DEFAULT 0,
            data_registrazione TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''',
        '''CREATE TABLE IF NOT EXISTS fatturato (
            id SERIAL PRIMARY KEY,
            cliente_id INTEGER NOT NULL REFERENCES clienti(id),
            prodotto_id INTEGER REFERENCES prodotti(id),
            quantita INTEGER NOT NULL DEFAULT 0,
            mese INTEGER NOT NULL,
            anno INTEGER NOT NULL,
            totale REAL NOT NULL
        )''',
        '''CREATE TABLE IF NOT EXISTS clienti_prodotti (
            cliente_id INTEGER NOT NULL REFERENCES clienti(id) ON DELETE CASCADE,
            prodotto_id INTEGER NOT NULL REFERENCES prodotti(id) ON DELETE CASCADE,
            PRIMARY KEY (cliente_id, prodotto_id)
        )''',
        '''CREATE TABLE IF NOT EXISTS prodotti_rimossi (
            id SERIAL PRIMARY KEY,
            prodotto_id INTEGER NOT NULL REFERENCES prodotti(id),
            data_rimozione TIMESTAMP NOT NULL
        )''',
        '''CREATE TABLE IF NOT EXISTS promo_scadenze_prodotti (
            id SERIAL PRIMARY KEY,
            codice TEXT,
            nome TEXT,
            prezzo REAL,
            um TEXT,
            scadenza TEXT,
            quantita TEXT,
            prodotto_id INTEGER REFERENCES prodotti(id) ON DELETE SET NULL
        )''',
        '''CREATE TABLE IF NOT EXISTS fatturato_settimanale (
            id SERIAL PRIMARY KEY,
            cliente_id INTEGER NOT NULL REFERENCES clienti(id) ON DELETE CASCADE,
            settimana INTEGER NOT NULL,
            anno INTEGER NOT NULL,
            totale REAL NOT NULL DEFAULT 0,
            note TEXT,
            data_inserimento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''',
        '''CREATE TABLE IF NOT EXISTS acquisti_settimanali_pdf (
            id SERIAL PRIMARY KEY,
            cliente_id INTEGER NOT NULL REFERENCES clienti(id) ON DELETE CASCADE,
            settimana INTEGER NOT NULL,
            anno INTEGER NOT NULL,
            nome_file TEXT,
            data_caricamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''',
        '''CREATE TABLE IF NOT EXISTS acquisti_settimanali_dettaglio (
            id SERIAL PRIMARY KEY,
            cliente_id INTEGER NOT NULL REFERENCES clienti(id) ON DELETE CASCADE,
            settimana INTEGER NOT NULL,
            anno INTEGER NOT NULL,
            prodotto_id INTEGER REFERENCES prodotti(id) ON DELETE CASCADE,
            codice_pdf TEXT,
            nome_pdf TEXT,
            um_pdf TEXT,
            prezzo_pdf REAL DEFAULT 0,
            quantita INTEGER DEFAULT 1
        )'''
    ]

    with get_db() as db:
        cur = db.cursor()
        for stmt in statements:
            try:
                cur.execute(stmt)
                db.commit()
            except Exception as _e:
                print(f"init_db statement warning: {_e}")
                try:
                    db.rollback()
                except Exception:
                    pass
        try:
            cur.execute("ALTER TABLE clienti_prodotti ADD COLUMN potenziale BOOLEAN DEFAULT FALSE")
            db.commit()
        except Exception:
            try: db.rollback()
            except Exception: pass

        for alt_stmt in [
            "ALTER TABLE fatturato ADD COLUMN prodotto_id INTEGER",
            "ALTER TABLE fatturato ADD COLUMN quantita INTEGER DEFAULT 0",
            "ALTER TABLE fatturato_settimanale ADD COLUMN data_inizio DATE",
            "ALTER TABLE fatturato_settimanale ADD COLUMN data_fine DATE",
            "ALTER TABLE fatturato_settimanale ADD COLUMN mese INTEGER",
            "ALTER TABLE acquisti_settimanali_pdf ADD COLUMN data_inizio DATE",
            "ALTER TABLE acquisti_settimanali_pdf ADD COLUMN data_fine DATE",
            "ALTER TABLE acquisti_settimanali_dettaglio ADD COLUMN update_id INTEGER",
            "ALTER TABLE acquisti_settimanali_dettaglio ADD COLUMN data_inizio DATE",
            "ALTER TABLE acquisti_settimanali_dettaglio ADD COLUMN data_fine DATE",
            "ALTER TABLE promo_scadenze_prodotti ADD COLUMN scadenza TEXT",
            "ALTER TABLE promo_scadenze_prodotti ADD COLUMN quantita TEXT"
        ]:
            try:
                cur.execute(alt_stmt)
                db.commit()
            except Exception:
                try: db.rollback()
                except Exception: pass

def aggiorna_fatturato_totale(id, cur=None):
    query = '''
        UPDATE clienti SET fatturato_totale = (
            SELECT COALESCE(SUM(totale), 0) FROM (
                SELECT totale FROM fatturato WHERE cliente_id = %s
                UNION ALL
                SELECT totale FROM fatturato_settimanale WHERE cliente_id = %s
            ) AS t
        ) WHERE id = %s
    '''
    try:
        if cur:
            cur.execute(query, (id, id, id))
        else:
            with get_db() as db:
                cur_db = db.cursor()
                cur_db.execute(query, (id, id, id))
                db.commit()
    except Exception as _e:
        print(f"aggiorna_fatturato_totale fallback warning: {_e}")
        query_fb = '''
            UPDATE clienti SET fatturato_totale = (
                SELECT COALESCE(SUM(totale), 0) FROM fatturato WHERE cliente_id = %s
            ) WHERE id = %s
        '''
        if cur:
            cur.execute(query_fb, (id, id))
        else:
            with get_db() as db:
                cur_db = db.cursor()
                cur_db.execute(query_fb, (id, id))
                db.commit()

try:
    init_db()
except Exception as _e:
    print(f"Db init status: {_e}")

# ============================
# ROUTE PRINCIPALE
# ============================
@app.route('/')
@login_required
def index():
    with get_db() as db:
        cur = db.cursor()
        now = datetime.now()
        mese_corrente = now.month
        anno_corrente = now.year

        primo_giorno_mese_corrente = datetime(anno_corrente, mese_corrente, 1)
        primo_giorno_prossimo_mese = primo_giorno_mese_corrente + relativedelta(months=1)

        # Fatturato totale corrente
        cur.execute('SELECT COALESCE(SUM(totale),0) as totale FROM fatturato WHERE mese=%s AND anno=%s',
                    (mese_corrente, anno_corrente))
        fatturato_corrente = cur.fetchone()['totale']

        # Fatturato precedente (es. Maggio)
        mese_prec = 12 if mese_corrente == 1 else mese_corrente - 1
        anno_prec = anno_corrente - 1 if mese_corrente == 1 else anno_corrente
        cur.execute('SELECT COALESCE(SUM(totale),0) as totale FROM fatturato WHERE mese=%s AND anno=%s',
                    (mese_prec, anno_prec))
        fatturato_precedente = cur.fetchone()['totale']

        # Fatturato due mesi fa (es. Aprile)
        mese_due_fa = 12 if mese_corrente <= 2 else mese_corrente - 2
        anno_due_fa = anno_corrente - 1 if mese_corrente <= 2 else anno_corrente
        cur.execute('SELECT COALESCE(SUM(totale),0) as totale FROM fatturato WHERE mese=%s AND anno=%s',
                    (mese_due_fa, anno_due_fa))
        fatturato_due_mesi_fa = cur.fetchone()['totale']

        variazione_fatturato = None
        if fatturato_due_mesi_fa != 0:
            variazione_fatturato = ((fatturato_precedente - fatturato_due_mesi_fa) / fatturato_due_mesi_fa) * 100

        # Clienti nuovi
        cur.execute('''
            SELECT id, nome, zona, data_registrazione
            FROM clienti
            WHERE data_registrazione >= %s AND data_registrazione < %s
        ''', (primo_giorno_mese_corrente, primo_giorno_prossimo_mese))
        clienti_nuovi_rows = cur.fetchall()

        clienti_nuovi_dettaglio = [
            {'id': c['id'], 'nome': c['nome'], 'data_registrazione': c['data_registrazione']}
            for c in clienti_nuovi_rows
        ]
        clienti_nuovi = len(clienti_nuovi_rows)

        # Clienti bloccati / inattivi
        mese_due_fa = 12 if mese_corrente <= 2 else mese_corrente - 2
        anno_due_fa = anno_corrente - 1 if mese_corrente <= 2 else anno_corrente

        cur.execute('''
            SELECT 
                c.id, 
                c.nome,
                COALESCE(SUM(CASE WHEN f.mese = %s AND f.anno = %s THEN f.totale ELSE 0 END), 0) AS totale_corrente,
                COALESCE(SUM(CASE WHEN f.mese = %s AND f.anno = %s THEN f.totale ELSE 0 END), 0) AS totale_prec,
                COALESCE(SUM(CASE WHEN f.mese = %s AND f.anno = %s THEN f.totale ELSE 0 END), 0) AS totale_due_mesi_fa
            FROM clienti c
            LEFT JOIN fatturato f ON c.id = f.cliente_id
            GROUP BY c.id, c.nome
        ''', (
            mese_corrente, anno_corrente,
            mese_prec, anno_prec,
            mese_due_fa, anno_due_fa
        ))
        clienti_status_rows = cur.fetchall()

        clienti_bloccati_dettaglio = []
        clienti_bloccati_inattivi_dettaglio = []

        for row in clienti_status_rows:
            totale_corrente = row['totale_corrente']
            totale_prec = row['totale_prec']
            totale_due_mesi_fa = row['totale_due_mesi_fa']

            if totale_corrente > 0 or totale_prec > 0:
                stato = 'attivo'
            elif totale_due_mesi_fa > 0:
                stato = 'bloccato'
            else:
                stato = 'inattivo'

            if stato == 'bloccato':
                clienti_bloccati_dettaglio.append({'id': row['id'], 'nome': row['nome']})
            if stato in ('bloccato', 'inattivo'):
                clienti_bloccati_inattivi_dettaglio.append({'id': row['id'], 'nome': row['nome'], 'stato': stato})

        # Prodotti inseriti
        cur.execute('''
            SELECT c.nome AS cliente, p.nome AS prodotto, cp.data_operazione
            FROM clienti_prodotti cp
            JOIN clienti c ON cp.cliente_id = c.id
            JOIN prodotti p ON cp.prodotto_id = p.id
            WHERE cp.lavorato = TRUE
              AND cp.data_operazione >= %s AND cp.data_operazione < %s
        ''', (primo_giorno_mese_corrente, primo_giorno_prossimo_mese))
        prodotti_inseriti_rows = cur.fetchall()
        prodotti_inseriti = [
            {'cliente': r['cliente'], 'prodotto': r['prodotto'], 'data_operazione': r['data_operazione']}
            for r in prodotti_inseriti_rows
        ]

        # Prodotti rimossi
        cur.execute('''
            SELECT c.nome AS cliente, p.nome AS prodotto, pr.data_rimozione
            FROM prodotti_rimossi pr
            JOIN prodotti p ON pr.prodotto_id = p.id
            JOIN clienti_prodotti cp ON cp.prodotto_id = p.id
            JOIN clienti c ON cp.cliente_id = c.id
            WHERE pr.data_rimozione >= %s AND pr.data_rimozione < %s
        ''', (primo_giorno_mese_corrente, primo_giorno_prossimo_mese))
        prodotti_rimossi_rows = cur.fetchall()
        prodotti_rimossi = [
            {'cliente': r['cliente'], 'prodotto': r['prodotto'], 'data_operazione': r['data_rimozione']}
            for r in prodotti_rimossi_rows
        ]

        # Fatturato ultimi 12 mesi
        cur.execute('''
            SELECT anno, mese, COALESCE(SUM(totale),0) as totale
            FROM fatturato
            GROUP BY anno, mese
            ORDER BY anno DESC, mese DESC
            LIMIT 12
        ''')
        fatturato_mensile_rows = cur.fetchall()
        fatturato_mensile = {f"{r['anno']}-{r['mese']:02}": r['totale'] for r in reversed(fatturato_mensile_rows)}

        # Fatturato per zona
        cur.execute('''
            SELECT COALESCE(c.zona, 'Sconosciuta') AS zona, COALESCE(SUM(f.totale),0) AS totale
            FROM fatturato f
            JOIN clienti c ON f.cliente_id = c.id
            GROUP BY c.zona
            ORDER BY zona
        ''')
        fatturato_per_zona_rows = cur.fetchall()
        fatturato_per_zona = {r['zona']: float(r['totale']) for r in fatturato_per_zona_rows}

        # Visite di oggi
        oggi_data = now.date()
        cur.execute('''
            SELECT v.id, c.nome as cliente_nome, v.ora_visita, v.completata 
            FROM visite v 
            JOIN clienti c ON v.cliente_id = c.id 
            WHERE v.data_visita = %s
            ORDER BY v.ora_visita DESC
        ''', (oggi_data,))
        visite_oggi = cur.fetchall()

        # Notifiche (simulated or simplified)
        notifiche = []
        if fatturato_corrente == 0:
            notifiche.append({
                "id": "fatturato_mancante",
                "titolo": "Fatturato Mancante",
                "descrizione": "Fatturato del mese corrente non ancora inserito.",
                "data": datetime.now(),
                "tipo": "danger",
                "letto": False
            })

    return render_template(
        '02_index.html',
        variazione_fatturato=variazione_fatturato,
        clienti_nuovi=clienti_nuovi_dettaglio,
        clienti_nuovi_count=len(clienti_nuovi_dettaglio),
        clienti_bloccati=clienti_bloccati_dettaglio,
        clienti_inattivi=[c for c in clienti_bloccati_inattivi_dettaglio if c['stato'] == 'inattivo'],
        prodotti_inseriti=prodotti_inseriti,
        prodotti_rimossi=prodotti_rimossi,
        fatturato_mensile=fatturato_mensile,
        fatturato_per_zona=fatturato_per_zona,
        visite_oggi=visite_oggi,
        notifiche=notifiche
    )


# ============================
# ROUTE CLIENTI
# ============================

@app.route('/clienti')
@login_required
def clienti():
    zona_filtro = request.args.get('zona')
    order = request.args.get('order', 'zona')
    search = request.args.get('search', '').strip().lower()

    oggi = datetime.today()
    mese_corrente = oggi.month
    anno_corrente = oggi.year
    mese_prec = 12 if mese_corrente == 1 else mese_corrente - 1
    anno_prec = anno_corrente - 1 if mese_corrente == 1 else anno_corrente
    mese_due_fa = 12 if mese_corrente <= 2 else mese_corrente - 2
    anno_due_fa = anno_corrente - 1 if mese_corrente <= 2 else anno_corrente

    with get_db() as db:
        cur = db.cursor()
        
        # Singola query ottimizzata per estrarre i clienti e il fatturato aggregato
        query = '''
            SELECT 
                c.id, 
                c.nome, 
                c.zona,
                COALESCE(SUM(f.totale), 0) AS fatturato_totale,
                COALESCE(SUM(CASE WHEN f.mese = %s AND f.anno = %s THEN f.totale ELSE 0 END), 0) AS totale_mese_corrente,
                COALESCE(SUM(CASE WHEN f.mese = %s AND f.anno = %s THEN f.totale ELSE 0 END), 0) AS totale_mese_prec,
                COALESCE(SUM(CASE WHEN f.mese = %s AND f.anno = %s THEN f.totale ELSE 0 END), 0) AS totale_due_mesi_fa
            FROM clienti c
            LEFT JOIN fatturato f ON c.id = f.cliente_id
        '''
        condizioni = []
        params = [
            mese_corrente, anno_corrente,
            mese_prec, anno_prec,
            mese_due_fa, anno_due_fa
        ]

        if zona_filtro:
            condizioni.append('c.zona = %s')
            params.append(zona_filtro)
        if search:
            condizioni.append('LOWER(c.nome) LIKE %s')
            params.append(f'%{search}%')
            
        if condizioni:
            query += ' WHERE ' + ' AND '.join(condizioni)
            
        query += ' GROUP BY c.id, c.nome, c.zona'
        
        cur.execute(query, params)
        clienti_rows = cur.fetchall()

        clienti_list = []
        stati_clienti = {}
        andamento_clienti = {}

        for row in clienti_rows:
            c_id = row['id']
            fatturato_totale = row['fatturato_totale']
            totale_mese_corrente = row['totale_mese_corrente']
            totale_mese_prec = row['totale_mese_prec']
            totale_due_mesi_fa = row['totale_due_mesi_fa']

            stato = ('attivo' if (totale_mese_corrente > 0 or totale_mese_prec > 0)
                     else 'bloccato' if totale_due_mesi_fa > 0
                     else 'inattivo')
            stati_clienti[c_id] = stato

            # Calcola andamento (trend mensile: mese precedente rispetto a due mesi fa, es. Maggio rispetto ad Aprile)
            if totale_due_mesi_fa > 0:
                andamento = round(((totale_mese_prec - totale_due_mesi_fa) / totale_due_mesi_fa) * 100, 2)
            elif totale_mese_prec > 0:
                andamento = 100.0
            else:
                andamento = 0.0
            andamento_clienti[c_id] = andamento

            clienti_list.append({
                'id': c_id,
                'nome': row['nome'],
                'zona': row['zona'],
                'fatturato_totale': fatturato_totale,
                'fatturato_corrente': totale_mese_corrente,
                'fatturato_precedente': totale_mese_prec,
                'fatturato_due_mesi_fa': totale_due_mesi_fa
            })

        clienti_per_zona = defaultdict(list)
        fatturato_per_zona = defaultdict(float)

        for c in clienti_list:
            clienti_per_zona[c['zona']].append(c)
            fatturato_per_zona[c['zona'] or 'Zona Non Specificata'] += float(c['fatturato_totale'] or 0.0)

        cur.execute('SELECT DISTINCT zona FROM clienti')
        zone = cur.fetchall()
        zone_lista = sorted([z['zona'] for z in zone if z['zona']])

        top_clienti = sorted(clienti_list, key=lambda c: c['fatturato_totale'], reverse=True)[:5]
        clienti_bloccati_list = [c for c in clienti_list if stati_clienti.get(c['id']) == 'bloccato']

        tab_attiva = request.args.get('tab', 'lista')

    return render_template(
        '01_clienti/01_clienti.html',
        clienti_per_zona=clienti_per_zona,
        tutti_clienti=clienti_list,
        zone=zone_lista,
        zona_filtro=zona_filtro,
        order=order,
        search=search,
        stati_clienti=stati_clienti,
        andamento_clienti=andamento_clienti,
        fatturato_per_zona=dict(fatturato_per_zona),
        top_clienti=top_clienti,
        clienti_bloccati_list=clienti_bloccati_list,
        tab_attiva=tab_attiva
    )


@app.route('/clienti/aggiungi', methods=['GET', 'POST'])
@login_required
def nuovo_cliente():
    current_year = datetime.now().year
    with get_db() as db:
        cur = db.cursor()
        cur.execute('SELECT nome FROM zone ORDER BY nome')
        zone = cur.fetchall()
        cur.execute('SELECT * FROM categorie ORDER BY nome')
        categorie = cur.fetchall()
        cur.execute('SELECT p.id, p.nome, p.codice, p.categoria_id FROM prodotti p ORDER BY p.nome')
        prodotti = cur.fetchall()

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        zona = request.form.get('zona', '').strip()
        nuova_zona = request.form.get('nuova_zona', '').strip()

        with get_db() as db:
            cur = db.cursor()
            if zona == 'nuova_zona' and nuova_zona:
                zona = nuova_zona
                cur.execute('SELECT 1 FROM zone WHERE nome=%s', (zona,))
                if not cur.fetchone():
                    cur.execute('INSERT INTO zone (nome) VALUES (%s)', (zona,))

            if not nome:
                flash('Il nome del cliente è obbligatorio.', 'warning')
                return redirect(request.url)

            # Get planning and phone inputs
            consegna_giorni_list = request.form.getlist('consegna_giorni[]')
            giorni_consegna_standard = ",".join(consegna_giorni_list) if consegna_giorni_list else None
            
            giorno_visita_standard = request.form.get('giorno_visita_standard')
            if giorno_visita_standard == "":
                giorno_visita_standard = None
            else:
                giorno_visita_standard = int(giorno_visita_standard)
                
            frequenza_visita = request.form.get('frequenza_visita') or None
            
            ora_visita_standard = request.form.get('ora_visita_standard')
            if not ora_visita_standard:
                ora_visita_standard = None
                
            telefono = request.form.get('telefono', '').strip()
            
            phone_col = _detect_phone_column(cur) or "telefono"
            
            now = datetime.now()
            cur.execute(f'''
                INSERT INTO clienti (nome, zona, data_registrazione, {phone_col}, giorni_consegna_standard, giorno_visita_standard, frequenza_visita, ora_visita_standard) 
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            ''', (nome, zona, now, telefono, giorni_consegna_standard, giorno_visita_standard, frequenza_visita, ora_visita_standard))
            cliente_id = cur.fetchone()['id']

            prodotti_scelti = request.form.getlist('prodotti[]')
            for prodotto_id in prodotti_scelti:
                cur.execute('''
                    INSERT INTO clienti_prodotti (cliente_id, prodotto_id, lavorato, data_operazione)
                    VALUES (%s,%s,1,%s)
                ''', (cliente_id, prodotto_id, datetime.now()))

            mese = request.form.get('mese')
            anno = request.form.get('anno')
            fatturato_mensile = request.form.get('fatturato_mensile')
            if mese and anno and fatturato_mensile:
                try:
                    cur.execute('INSERT INTO fatturato (cliente_id, mese, anno, totale) VALUES (%s,%s,%s,%s)',
                                (cliente_id, int(mese), int(anno), float(fatturato_mensile)))
                except ValueError:
                    flash('Dati di fatturato non validi.', 'warning')

            db.commit()

        flash('Cliente aggiunto con successo.', 'success')
        return redirect(url_for('clienti'))

    return render_template(
        '01_clienti/02_aggiungi_cliente.html',
        zone=zone,
        categorie=categorie,
        prodotti=prodotti,
        current_year=current_year
    )


@app.route('/clienti/modifica/<int:id>', methods=['GET', 'POST'])
@login_required
def modifica_cliente(id):
    current_datetime = datetime.now()
    with get_db() as db:
        cur = db.cursor()

        # Recupera cliente
        cur.execute('SELECT * FROM clienti WHERE id=%s', (id,))
        cliente = cur.fetchone()
        if not cliente:
            flash('Cliente non trovato.', 'danger')
            return redirect(url_for('clienti'))
        cliente = dict(cliente)
        if cliente.get('ora_visita_standard'):
            cliente['ora_visita_standard_str'] = str(cliente['ora_visita_standard'])[:5]
        else:
            cliente['ora_visita_standard_str'] = ''

        # Zone e categorie
        cur.execute('SELECT * FROM zone ORDER BY nome')
        zone = cur.fetchall()
        cur.execute('SELECT * FROM categorie ORDER BY nome')
        categorie = cur.fetchall()

        # Prodotti
        cur.execute('''
            SELECT p.id, p.nome, p.codice, p.categoria_id, c.nome AS categoria_nome
            FROM prodotti p
            LEFT JOIN categorie c ON p.categoria_id = c.id
            WHERE COALESCE(p.eliminato, FALSE) = FALSE
            ORDER BY c.nome, p.nome
        ''')
        prodotti = cur.fetchall()

        # Prodotti associati al cliente
        cur.execute('''
            SELECT cp.id, cp.prodotto_id, cp.lavorato, cp.potenziale, cp.prezzo_attuale, cp.prezzo_offerta,
                   f.nome AS fornitore
            FROM clienti_prodotti cp
            LEFT JOIN fornitori f ON cp.fornitore_id = f.id
            WHERE cp.cliente_id=%s
        ''', (id,))
        prodotti_assoc = cur.fetchall()

        assoc_dict = {p['prodotto_id']: p for p in prodotti_assoc}
        prodotti_lavorati = [str(p['prodotto_id']) for p in prodotti_assoc if p['lavorato'] == 1 or p['lavorato'] is True]
        prodotti_potenziali = [str(p['prodotto_id']) for p in prodotti_assoc if p['potenziale'] == 1 or p['potenziale'] is True]
        prodotti_non_lavorati = [str(p['prodotto_id']) for p in prodotti_assoc if not p['lavorato'] and not p['potenziale']]
        prezzi_attuali = {str(p['prodotto_id']): p['prezzo_attuale'] for p in prodotti_assoc}
        prezzi_offerta = {str(p['prodotto_id']): p['prezzo_offerta'] for p in prodotti_assoc}
        fornitori = {str(p['prodotto_id']): p['fornitore'] or "" for p in prodotti_assoc}

        # Fatturati cliente
        cur.execute('''
            SELECT id, mese, anno, totale AS importo
            FROM fatturato
            WHERE cliente_id=%s
            ORDER BY anno DESC, mese DESC
        ''', (id,))
        fatturati_storico = cur.fetchall()
        fatturati_cliente = fatturati_storico

        if request.method == 'POST':
            # Aggiorna cliente
            nome = request.form.get('nome', '').strip()
            zona = request.form.get('zona', '').strip()
            nuova_zona = request.form.get('nuova_zona', '').strip()
            if zona == 'nuova_zona' and nuova_zona:
                zona = nuova_zona
                try:
                    cur.execute('INSERT INTO zone (nome) VALUES (%s)', (zona,))
                except:
                    pass
            if not nome:
                flash('Il nome del cliente è obbligatorio.', 'warning')
                return redirect(request.url)
            # Get planning and phone inputs
            consegna_giorni_list = request.form.getlist('consegna_giorni[]')
            giorni_consegna_standard = ",".join(consegna_giorni_list) if consegna_giorni_list else None
            
            giorno_visita_standard = request.form.get('giorno_visita_standard')
            if giorno_visita_standard == "":
                giorno_visita_standard = None
            else:
                giorno_visita_standard = int(giorno_visita_standard)
                
            frequenza_visita = request.form.get('frequenza_visita') or None
            
            ora_visita_standard = request.form.get('ora_visita_standard')
            if not ora_visita_standard:
                ora_visita_standard = None
                
            telefono = request.form.get('telefono', '').strip()
            
            phone_col = _detect_phone_column(cur) or "telefono"
            
            cur.execute(f'''
                UPDATE clienti 
                SET nome=%s, zona=%s, {phone_col}=%s, giorni_consegna_standard=%s, giorno_visita_standard=%s, frequenza_visita=%s, ora_visita_standard=%s 
                WHERE id=%s
            ''', (nome, zona, telefono, giorni_consegna_standard, giorno_visita_standard, frequenza_visita, ora_visita_standard, id))

            # Aggiorna prodotti (Ottimizzato con pre-caricamento fornitori e dirty-checking)
            prodotti_modificati = request.form.get('prodotti_modificati') == '1'
            if prodotti_modificati:
                cur.execute("SELECT id, nome FROM fornitori")
                fornitori_map = {f["nome"].strip().lower(): f["id"] for f in cur.fetchall()}

                for prodotto in prodotti:
                    pid = str(prodotto['id'])
                    pid_int = prodotto['id']
                    
                    stato = request.form.get(f'stato_associazione[{pid}]', 'no')
                    lavorato = (stato == 'lavorato')
                    potenziale = (stato == 'potenziale')
                    
                    prezzo_att_str = request.form.get(f'prezzo_attuale[{pid}]')
                    prezzo_off_str = request.form.get(f'prezzo_offerta[{pid}]')
                    
                    def to_float_or_none(val):
                        if val is None:
                            return None
                        v = val.strip().replace(',', '.')
                        if not v:
                            return None
                        try:
                            return float(v)
                        except ValueError:
                            return None
                    
                    prezzo_attuale = to_float_or_none(prezzo_att_str)
                    prezzo_offerta = to_float_or_none(prezzo_off_str)
                    
                    f_nome = (request.form.get(f"fornitore[{pid}]") or "").strip()
                    f_id = None
                    if f_nome:
                        f_nome_lower = f_nome.lower()
                        if f_nome_lower in fornitori_map:
                            f_id = fornitori_map[f_nome_lower]
                        else:
                            cur.execute("INSERT INTO fornitori (nome) VALUES (%s) RETURNING id", (f_nome,))
                            f_id = cur.fetchone()["id"]
                            fornitori_map[f_nome_lower] = f_id

                    esiste = assoc_dict.get(pid_int)
                    
                    if esiste:
                        db_lavorato = bool(esiste['lavorato'])
                        db_potenziale = bool(esiste.get('potenziale'))
                        db_prezzo_att = float(esiste['prezzo_attuale']) if esiste['prezzo_attuale'] is not None else None
                        db_prezzo_off = float(esiste['prezzo_offerta']) if esiste['prezzo_offerta'] is not None else None
                        
                        db_fornitore = (esiste['fornitore'] or "").strip().lower()
                        form_fornitore = f_nome.lower()
                        
                        is_dirty = (
                            db_lavorato != lavorato or
                            db_potenziale != potenziale or
                            db_prezzo_att != prezzo_attuale or
                            db_prezzo_off != prezzo_offerta or
                            db_fornitore != form_fornitore
                        )
                        
                        if is_dirty:
                            cur.execute('''
                                UPDATE clienti_prodotti
                                SET lavorato=%s, potenziale=%s, prezzo_attuale=%s, prezzo_offerta=%s, fornitore_id=%s, data_operazione=%s
                                WHERE id=%s
                            ''', (lavorato, potenziale, prezzo_attuale, prezzo_offerta, f_id, datetime.now(), esiste['id']))
                    else:
                        if lavorato or potenziale or prezzo_attuale is not None or prezzo_offerta is not None or f_id is not None:
                            cur.execute('''
                                INSERT INTO clienti_prodotti
                                (cliente_id, prodotto_id, lavorato, potenziale, prezzo_attuale, prezzo_offerta, fornitore_id, data_operazione)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                            ''', (id, pid_int, lavorato, potenziale, prezzo_attuale, prezzo_offerta, f_id, datetime.now()))

            # Aggiorna storico fatturato (Batch/Tabella con Dirty Checking in memoria)
            existing_fatturato = {(r['mese'], r['anno']): (r['id'], float(r['importo'])) for r in fatturati_storico}
            new_records = []
            
            fatturato_json = request.form.get('fatturato_storico_json')
            mesi_list = request.form.getlist('fatt_mese[]')
            anni_list = request.form.getlist('fatt_anno[]')
            importi_list = request.form.getlist('fatt_importo[]')

            if fatturato_json:
                try:
                    records = json.loads(fatturato_json)
                    for r in records:
                        mese_val = int(r.get('mese'))
                        anno_val = int(r.get('anno'))
                        importo_val = float(r.get('importo', 0))
                        new_records.append((mese_val, anno_val, importo_val))
                except Exception as ex:
                    print(f"Errore salvataggio storico fatturato JSON: {ex}")
            else:
                if mesi_list and anni_list and importi_list:
                    for m, a, imp in zip(mesi_list, anni_list, importi_list):
                        if m and a and imp:
                            try:
                                new_records.append((int(m), int(a), float(imp)))
                            except ValueError:
                                pass

            # Esegui dirty checking per inserire, aggiornare o eliminare solo le differenze
            if new_records or fatturato_json or (mesi_list and anni_list and importi_list):
                new_keys = {(r[0], r[1]) for r in new_records}
                # 1. Rimuovi i record che non sono più presenti
                for (m, a), (db_id, _) in list(existing_fatturato.items()):
                    if (m, a) not in new_keys:
                        cur.execute("DELETE FROM fatturato WHERE id = %s", (db_id,))
                        existing_fatturato.pop((m, a))

                # 2. Inserisci o aggiorna i record rimanenti
                for m_val, a_val, imp_val in new_records:
                    if (m_val, a_val) in existing_fatturato:
                        db_id, db_importo = existing_fatturato[(m_val, a_val)]
                        if db_importo != imp_val:
                            cur.execute("UPDATE fatturato SET totale = %s WHERE id = %s", (imp_val, db_id))
                            existing_fatturato[(m_val, a_val)] = (db_id, imp_val)
                    else:
                        cur.execute("INSERT INTO fatturato (cliente_id, mese, anno, totale) VALUES (%s, %s, %s, %s) RETURNING id",
                                    (id, m_val, a_val, imp_val))
                        new_id = cur.fetchone()["id"]
                        existing_fatturato[(m_val, a_val)] = (new_id, imp_val)

            # Aggiorna singolo mese inserito dai campi veloci (se presenti)
            mese = request.form.get('mese')
            anno = request.form.get('anno')
            importo = request.form.get('fatturato_mensile')
            if mese and anno and importo:
                try:
                    importo_float = float(importo)
                    mese_int = int(mese)
                    anno_int = int(anno)
                    
                    esiste_info = existing_fatturato.get((mese_int, anno_int))
                    if esiste_info:
                        db_id, db_importo = esiste_info
                        if db_importo != importo_float:
                            cur.execute('UPDATE fatturato SET totale=%s WHERE id=%s', (importo_float, db_id))
                    else:
                        cur.execute('INSERT INTO fatturato (cliente_id,mese,anno,totale) VALUES (%s,%s,%s,%s)',
                                    (id, mese_int, anno_int, importo_float))
                except ValueError:
                    flash('Importo fatturato non valido.', 'warning')

            aggiorna_fatturato_totale(id, cur)
            db.commit()
            flash('Cliente modificato con successo.', 'success')
            return redirect(url_for('clienti'))

        # Precompila ultimo fatturato
        cur.execute('''
            SELECT mese, anno, totale FROM fatturato
            WHERE cliente_id=%s
            ORDER BY anno DESC, mese DESC
            LIMIT 1
        ''', (id,))
        ultimo_fatturato = cur.fetchone()
        mese = ultimo_fatturato['mese'] if ultimo_fatturato else None
        anno = ultimo_fatturato['anno'] if ultimo_fatturato else None
        importo = ultimo_fatturato['totale'] if ultimo_fatturato else None

        zone_nomi = [z['nome'] for z in zone]
        nuova_zona_selected = cliente['zona'] not in zone_nomi
        nuova_zona_value = cliente['zona'] if nuova_zona_selected else ''

        # Recupera preview PDF
        import_preview_data = _PDF_IMPORT_CACHE.get(f'import_preview_{id}', None)
        show_import_popup = request.args.get('show_import_popup', '0') == '1'

        # Recupera aggiornamenti settimanali per Modifica Cliente
        try:
            cur.execute('''
                SELECT f.id, f.data_inizio, f.data_fine, f.mese, f.anno, f.totale, f.note, f.data_inserimento, p.nome_file AS pdf_nome
                FROM fatturato_settimanale f
                LEFT JOIN acquisti_settimanali_pdf p ON f.cliente_id = p.cliente_id AND (f.data_inizio = p.data_inizio AND f.data_fine = p.data_fine)
                WHERE f.cliente_id = %s
                ORDER BY f.data_inizio DESC, f.id DESC
            ''', (id,))
            rows_set = cur.fetchall()
            fatturato_settimanale_list = []
            for r in rows_set:
                r_dict = dict(r)
                d_ini = r_dict.get('data_inizio')
                d_end = r_dict.get('data_fine')
                if d_ini and d_end:
                    ini_str = d_ini.strftime('%d/%m/%Y') if hasattr(d_ini, 'strftime') else str(d_ini)
                    end_str = d_end.strftime('%d/%m/%Y') if hasattr(d_end, 'strftime') else str(d_end)
                    r_dict['periodo_str'] = f"Dal {ini_str} al {end_str}"
                else:
                    r_dict['periodo_str'] = f"Settimana {r_dict.get('settimana', 1)} ({r_dict.get('anno', 2026)})"
                fatturato_settimanale_list.append(r_dict)
        except Exception:
            fatturato_settimanale_list = []

    return render_template(
        '01_clienti/03_modifica_cliente.html',
        cliente=cliente,
        zone=zone,
        categorie=categorie,
        prodotti=prodotti,
        prodotti_lavorati=prodotti_lavorati,
        prodotti_potenziali=prodotti_potenziali,
        prodotti_non_lavorati=prodotti_non_lavorati,
        prezzi_attuali=prezzi_attuali,
        prezzi_offerta=prezzi_offerta,
        fornitori=fornitori,
        nuova_zona_selected=nuova_zona_selected,
        nuova_zona_value=nuova_zona_value,
        import_preview_data=import_preview_data,
        import_result=import_preview_data,
        show_import_popup=show_import_popup,
        fatturato_mese=mese,
        fatturato_anno=anno,
        fatturato_importo=importo,
        fatturati_cliente=fatturati_cliente,
        fatturati_storico=fatturati_cliente,
        fatturato_settimanale_list=fatturato_settimanale_list,
        target_update_id=request.args.get('update_id', type=int),
        current_month=current_datetime.month,
        current_year=current_datetime.year
    )


# ============================
# CACHE PER IMPORTAZIONE PDF
# ============================
_PDF_IMPORT_CACHE = {}

def parse_int(value):
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    try:
        return int(s)
    except ValueError:
        return None

def parse_decimal(value):
    from decimal import Decimal, InvalidOperation
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    s = s.replace("€", "").replace(" ", "")
    if "." in s and "," in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None

@app.route('/clienti/modifica/<int:id>/importa_pdf', methods=['POST'])
@app.route('/clienti/modifica/<int:cliente_id>/importa_pdf', methods=['POST'])
@login_required
def importa_pdf_lavorati_auto(id=None, cliente_id=None):
    target_id = id if id is not None else cliente_id
    if not target_id:
        flash('ID cliente mancante.', 'danger')
        return redirect(url_for('clienti'))

    if 'pdf' not in request.files:
        flash('Nessun file selezionato.', 'danger')
        return redirect(url_for('modifica_cliente', id=target_id))
        
    file = request.files['pdf']
    if file.filename == '':
        flash('Nessun file selezionato.', 'danger')
        return redirect(url_for('modifica_cliente', id=target_id))
        
    if not file.filename.lower().endswith('.pdf'):
        flash('Seleziona un file PDF.', 'danger')
        return redirect(url_for('modifica_cliente', id=target_id))
        
    import tempfile
    import os
    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        file.save(temp_path)
        
        # 1. ESTRAZIONE PRODOTTI
        offerte = parse_offers_from_pdf(temp_path)
        
        prodotti_anteprima = []
        
        with get_db() as db:
            cur = db.cursor(cursor_factory=RealDictCursor)
            for off in offerte:
                codice = off['code']
                nome_pdf = off['name']
                um_pdf = off.get('um', 'PZ')
                nome_con_um = f"{nome_pdf} ({um_pdf})"
                prezzo = parse_decimal(off['price']) if off.get('price') else 0.0
                
                # Controlla se esiste già
                cur.execute("""
                    SELECT p.id, p.nome, p.categoria_id, c.nome AS categoria_nome 
                    FROM prodotti p
                    LEFT JOIN categorie c ON p.categoria_id = c.id
                    WHERE p.codice=%s AND COALESCE(p.eliminato, FALSE) = FALSE
                """, (codice,))
                esistente = cur.fetchone()
                
                conflitto_nome = False
                if esistente:
                    conflitto_nome = esistente['nome'].lower().strip() != nome_con_um.lower().strip()
                
                prodotti_anteprima.append({
                    'codice': codice,
                    'nome_pdf': nome_pdf,
                    'um_pdf': um_pdf,
                    'nome_con_um': nome_con_um,
                    'nome_sistema': esistente['nome'] if esistente else None,
                    'prezzo_pdf': float(prezzo) if prezzo else 0.0,
                    'categoria_id': esistente['categoria_id'] if esistente else None,
                    'categoria_nome': esistente['categoria_nome'] if esistente else None,
                    'nuovo': esistente is None,
                    'conflitto_nome': conflitto_nome
                })
        
        da_categorizzare = [p for p in prodotti_anteprima if p['categoria_id'] is None]
        nuovi = [p for p in prodotti_anteprima if p['nuovo']]
        gia_esistenti = [p for p in prodotti_anteprima if not p['nuovo']]
        
        import_result = {
            'totale': len(prodotti_anteprima),
            'assigned': len(gia_esistenti),
            'created': len(nuovi),
            'prodotti_importati': prodotti_anteprima,
            'da_categorizzare': da_categorizzare
        }
        
        _PDF_IMPORT_CACHE[f'import_preview_{target_id}'] = import_result
        return redirect(url_for('modifica_cliente', id=target_id, show_import_popup='1'))
    except Exception as e:
        flash(f"Errore durante l'elaborazione del PDF: {str(e)}", 'danger')
        return redirect(url_for('modifica_cliente', id=target_id))
    finally:
        if os.path.exists(temp_path):
            try:
                os.close(fd)
                os.remove(temp_path)
            except:
                pass

@app.route('/clienti/modifica/<int:id>/conferma_import_pdf', methods=['POST'])
@app.route('/clienti/modifica/<int:id>/salva_categorie_pdf', methods=['POST'])
@app.route('/clienti/modifica/<int:cliente_id>/conferma_import_pdf', methods=['POST'])
@app.route('/clienti/modifica/<int:cliente_id>/salva_categorie_pdf', methods=['POST'])
@login_required
def salva_categorie_import_pdf_modal(id=None, cliente_id=None):
    target_id = id if id is not None else cliente_id
    if not target_id:
        flash('ID cliente mancante.', 'danger')
        return redirect(url_for('clienti'))

    import_result = _PDF_IMPORT_CACHE.pop(f'import_preview_{target_id}', None)
    if not import_result:
        flash("Sessione scaduta o elaborazione fallita. Ricarica il file.", "danger")
        return redirect(url_for('modifica_cliente', id=target_id))
        
    anteprima = import_result.get('prodotti_importati', [])
    current_datetime = datetime.now()
    count_agg = 0
    
    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)
        prodotti_nel_pdf = set()
        
        # Carica associazioni prodotti esistenti del cliente
        cur.execute('''
            SELECT prodotto_id, lavorato, prezzo_attuale, prezzo_offerta, data_operazione
            FROM clienti_prodotti
            WHERE cliente_id=%s
        ''', (target_id,))
        prodotti_assoc = cur.fetchall()
        assoc_dict = {p['prodotto_id']: p for p in prodotti_assoc}
        
        for item in anteprima:
            codice = item['codice']
            # Leggiamo i valori affinati dal form se presenti, altrimenti usiamo quelli del PDF
            nome_final = request.form.get(f'nome[{codice}]', item['nome_con_um']).strip()
            
            # Categoria da form, altrimenti da cache
            cat_val = request.form.get(f'categoria[{codice}]')
            if not cat_val:
                cat_id_final = item['categoria_id']
            else:
                cat_id_final = parse_int(cat_val)
                
            prezzo_pdf = item.get('prezzo_pdf', 0.0)
            prezzo_str = request.form.get(f'prezzo[{codice}]')
            prezzo_final = parse_decimal(prezzo_str) if prezzo_str else parse_decimal(prezzo_pdf)
            
            f_nome = request.form.get(f'fornitore[{codice}]', '').strip()
            f_id = None
            if f_nome:
                cur.execute("SELECT id FROM fornitori WHERE nome=%s", (f_nome,))
                f_row = cur.fetchone()
                if f_row: 
                    f_id = f_row["id"]
                else:
                    cur.execute("INSERT INTO fornitori (nome) VALUES (%s) RETURNING id", (f_nome,))
                    f_id = cur.fetchone()["id"]
            
            # 1. CERCA O CREA PRODOTTO
            cur.execute("SELECT id, nome, eliminato FROM prodotti WHERE codice=%s", (codice,))
            prod = cur.fetchone()
            
            if prod:
                pid = prod['id']
                scelta_nome = request.form.get(f'scelta_nome[{codice}]', 'mantieni')
                if scelta_nome == 'sovrascrivi':
                    nome_salvato = nome_final
                else:
                    nome_salvato = prod['nome']
                
                # Aggiorna categoria, nome (se scelto) e riattiva il prodotto in caso fosse stato eliminato
                cur.execute('''
                    UPDATE prodotti 
                    SET nome=%s, categoria_id=COALESCE(%s, categoria_id), eliminato=FALSE 
                    WHERE id=%s
                ''', (nome_salvato, cat_id_final, pid))
            else:
                # Nuovo prodotto
                cur.execute('''
                    INSERT INTO prodotti (codice, nome, categoria_id) 
                    VALUES (%s, %s, %s) RETURNING id
                ''', (codice, nome_final, cat_id_final))
                pid = cur.fetchone()['id']
                
            prodotti_nel_pdf.add(pid)
            
            # 2. ASSOCIA AL CLIENTE E AGGIORNA PREZZO ATTUALE e FORNITORE
            cur.execute("SELECT id, lavorato FROM clienti_prodotti WHERE cliente_id=%s AND prodotto_id=%s", (target_id, pid))
            link = cur.fetchone()
            
            if link:
                lavorato_id = link['id']
                is_lavorato = link['lavorato']
                if not is_lavorato:
                    cur.execute('''
                        UPDATE clienti_prodotti 
                        SET lavorato=TRUE, volte_mancante=0, prezzo_attuale=%s, fornitore_id=%s, data_operazione=%s, data_inizio_lavorazione=%s, data_fine_lavorazione=NULL
                        WHERE id=%s
                    ''', (prezzo_final, f_id, current_datetime, current_datetime, lavorato_id))
                else:
                    cur.execute('''
                        UPDATE clienti_prodotti 
                        SET volte_mancante=0, prezzo_attuale=%s, fornitore_id=%s, data_operazione=%s 
                        WHERE id=%s
                    ''', (prezzo_final, f_id, current_datetime, lavorato_id))
            else:
                cur.execute('''
                    INSERT INTO clienti_prodotti (cliente_id, prodotto_id, lavorato, volte_mancante, prezzo_attuale, fornitore_id, data_operazione, data_inizio_lavorazione)
                    VALUES (%s, %s, TRUE, 0, %s, %s, %s, %s)
                ''', (target_id, pid, prezzo_final, f_id, current_datetime, current_datetime))
            
            count_agg += 1
            
        # 3. INCREMENTA VOLTE MANCANTE PER PRODOTTI NON NEL PDF (MA PROPRIO LAVORATI)
        if prodotti_nel_pdf:
            cur.execute('''
                SELECT id, volte_mancante FROM clienti_prodotti 
                WHERE cliente_id=%s AND lavorato=TRUE AND prodotto_id NOT IN %s
            ''', (target_id, tuple(prodotti_nel_pdf)))
        else:
            cur.execute('''
                SELECT id, volte_mancante FROM clienti_prodotti 
                WHERE cliente_id=%s AND lavorato=TRUE
            ''', (target_id,))
            
        missing_links = cur.fetchall()
        for ml in missing_links:
            mid = ml['id']
            miss_count = (ml['volte_mancante'] or 0) + 1
            if miss_count >= 3:
                # Muove a non-lavorato
                cur.execute('''
                    UPDATE clienti_prodotti 
                    SET lavorato=FALSE, volte_mancante=%s, data_fine_lavorazione=%s 
                    WHERE id=%s
                ''', (miss_count, current_datetime, mid))
            else:
                cur.execute('UPDATE clienti_prodotti SET volte_mancante=%s WHERE id=%s', (miss_count, mid))
                
        aggiorna_fatturato_totale(target_id, cur)
        db.commit()
        
    flash(f"Importazione completata: {count_agg} prodotti elaborati.", "success")
    return redirect(url_for('modifica_cliente', id=target_id))



@app.route('/clienti/<int:id>')
@login_required
def cliente_scheda(id):
    oggi = datetime.today()
    current_month = oggi.month
    current_year = oggi.year
    prev_month = 12 if current_month == 1 else current_month - 1
    prev_year = current_year - 1 if current_month == 1 else current_year

    with get_db() as db:
        cur = db.cursor()
        cur.execute('SELECT * FROM clienti WHERE id=%s', (id,))
        cliente = cur.fetchone()
        if not cliente:
            flash('Cliente non trovato.', 'danger')
            return redirect(url_for('clienti'))
        cliente = dict(cliente)
        if cliente.get('ora_visita_standard'):
            cliente['ora_visita_standard_str'] = str(cliente['ora_visita_standard'])[:5]
        else:
            cliente['ora_visita_standard_str'] = ''

        cur.execute('''
            SELECT p.id, p.nome, p.codice, p.categoria_id, COALESCE(c.nome,'–') AS categoria_nome
            FROM prodotti p
            LEFT JOIN categorie c ON p.categoria_id=c.id
            WHERE COALESCE(p.eliminato, FALSE) = FALSE
            ORDER BY c.nome, p.nome
        ''')
        prodotti = cur.fetchall()

        cur.execute('''
            SELECT prodotto_id, lavorato, potenziale, prezzo_attuale, prezzo_offerta, data_operazione
            FROM clienti_prodotti
            WHERE cliente_id=%s
        ''', (id,))
        prodotti_assoc = cur.fetchall()
        assoc_dict = {p['prodotto_id']: p for p in prodotti_assoc}

        prodotti_lavorati, prodotti_potenziali, prezzi_attuali, prezzi_offerta, prodotti_data = [], [], {}, {}, {}
        for p in prodotti:
            pid = p['id']
            if pid in assoc_dict:
                lavorato = assoc_dict[pid]['lavorato']
                potenziale = assoc_dict[pid].get('potenziale')
                prezzo_attuale = assoc_dict[pid]['prezzo_attuale']
                prezzo_offerta = assoc_dict[pid]['prezzo_offerta']
                data_op = assoc_dict[pid]['data_operazione']
            else:
                lavorato = False
                potenziale = False
                prezzo_attuale = None
                prezzo_offerta = None
                data_op = None

            prodotti_lavorati.append(str(pid)) if lavorato is True or lavorato == 1 else None
            prodotti_potenziali.append(str(pid)) if potenziale is True or potenziale == 1 else None
            prezzi_attuali[str(pid)] = prezzo_attuale
            prezzi_offerta[str(pid)] = prezzo_offerta
            prodotti_data[str(pid)] = data_op

        cur.execute('SELECT id, nome FROM categorie ORDER BY nome')
        categorie = [dict(c) for c in cur.fetchall()]

        cur.execute('SELECT COALESCE(SUM(totale),0) AS totale FROM fatturato WHERE cliente_id=%s', (id,))
        fatturato_totale = cur.fetchone()['totale']

        cur.execute('SELECT COALESCE(SUM(totale),0) FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                    (id, current_month, current_year))
        totale_corrente = cur.fetchone()['coalesce']

        cur.execute('SELECT COALESCE(SUM(totale),0) FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                    (id, prev_month, prev_year))
        totale_prec = cur.fetchone()['coalesce']

        # Calcola due mesi fa
        date_two_months_ago = datetime(current_year, current_month, 1) - relativedelta(months=2)
        two_months_ago_month = date_two_months_ago.month
        two_months_ago_year = date_two_months_ago.year
        cur.execute('SELECT COALESCE(SUM(totale),0) FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                    (id, two_months_ago_month, two_months_ago_year))
        totale_due_mesi_fa = cur.fetchone()['coalesce']

        variazione_fatturato_cliente = ((totale_prec - totale_due_mesi_fa) / totale_due_mesi_fa * 100) if totale_due_mesi_fa else None
        stato_cliente = ('attivo' if (totale_corrente > 0 or totale_prec > 0)
                         else 'bloccato' if totale_due_mesi_fa > 0
                         else 'inattivo')

        cur.execute('''
            SELECT anno, mese, SUM(totale) AS totale
            FROM fatturato
            WHERE cliente_id=%s
            GROUP BY anno, mese
            ORDER BY anno ASC, mese ASC
        ''', (id,))
        fatturato_mensile = {f"{r['anno']}-{r['mese']:02d}": r['totale'] for r in cur.fetchall()}

        is_sqlite = isinstance(db, SQLiteConnWrapper)
        datetime_expr = "datetime(anno || '-' || mese || '-01')" if is_sqlite else "CAST(anno || '-' || mese || '-01' AS timestamp)"
        
        cur.execute(f'''
            SELECT descrizione, data
            FROM (
                SELECT 'Aggiunto prodotto: ' || p.nome AS descrizione, cp.data_operazione AS data
                FROM clienti_prodotti cp JOIN prodotti p ON cp.prodotto_id=p.id
                WHERE cp.cliente_id=%s AND cp.lavorato
                UNION ALL
                SELECT 'Rimosso prodotto: ' || p.nome, pr.data_rimozione
                FROM prodotti_rimossi pr JOIN prodotti p ON pr.prodotto_id=p.id
                WHERE pr.cliente_id=%s
                UNION ALL
                SELECT 'Fatturato aggiornato: ' || totale || ' €', {datetime_expr}
                FROM fatturato
                WHERE cliente_id=%s
                UNION ALL
                SELECT 'Prezzo prodotto modificato: ' || p.nome, cp.data_operazione
                FROM clienti_prodotti cp JOIN prodotti p ON cp.prodotto_id=p.id
                WHERE cp.cliente_id=%s AND (cp.prezzo_attuale IS NOT NULL OR cp.prezzo_offerta IS NOT NULL)
            ) AS logs
            ORDER BY data DESC
        ''', (id, id, id, id))
        log_cliente = []
        for l in cur.fetchall():
            log_dict = dict(l)
            if not log_dict['data']:
                log_dict['data'] = datetime.min
            elif isinstance(log_dict['data'], str):
                try:
                    log_dict['data'] = datetime.fromisoformat(log_dict['data'])
                except ValueError:
                    try:
                        log_dict['data'] = datetime.strptime(log_dict['data'], '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        log_dict['data'] = datetime.min
            log_cliente.append(log_dict)

        # List of worked products for the modal checklist
        cur.execute('''
            SELECT p.id, p.codice, p.nome, COALESCE(c.nome, '–') AS categoria_nome, cp.prezzo_attuale, cp.prezzo_offerta
            FROM clienti_prodotti cp
            JOIN prodotti p ON cp.prodotto_id = p.id
            LEFT JOIN categorie c ON p.categoria_id = c.id
            WHERE cp.cliente_id = %s AND cp.lavorato = TRUE AND COALESCE(p.eliminato, FALSE) = FALSE
            ORDER BY c.nome, p.nome
        ''', (id,))
        prodotti_lavorati_full = [dict(r) for r in cur.fetchall()]

        try:
            cur.execute('''
                SELECT f.id, f.data_inizio, f.data_fine, f.mese, f.anno, f.totale, f.note, f.data_inserimento, p.nome_file AS pdf_nome
                FROM fatturato_settimanale f
                LEFT JOIN acquisti_settimanali_pdf p ON f.cliente_id = p.cliente_id AND (f.data_inizio = p.data_inizio AND f.data_fine = p.data_fine)
                WHERE f.cliente_id = %s
                ORDER BY f.data_inizio DESC, f.id DESC
            ''', (id,))
            rows = cur.fetchall()
            fatturato_settimanale_list = []
            for r in rows:
                r_dict = dict(r)
                d_ini = r_dict.get('data_inizio')
                d_end = r_dict.get('data_fine')
                if d_ini and d_end:
                    ini_str = d_ini.strftime('%d/%m/%Y') if hasattr(d_ini, 'strftime') else str(d_ini)
                    end_str = d_end.strftime('%d/%m/%Y') if hasattr(d_end, 'strftime') else str(d_end)
                    r_dict['periodo_str'] = f"Dal {ini_str} al {end_str}"
                else:
                    r_dict['periodo_str'] = f"Settimana {r_dict.get('settimana', 1)} ({r_dict.get('anno', 2026)})"
                fatturato_settimanale_list.append(r_dict)
        except Exception:
            fatturato_settimanale_list = []

    return render_template(
        "01_clienti/04_cliente_scheda.html",
        cliente=cliente,
        categorie=categorie,
        prodotti=prodotti,
        prodotti_lavorati=prodotti_lavorati,
        prodotti_lavorati_full=prodotti_lavorati_full,
        prodotti_potenziali=prodotti_potenziali,
        log_cliente=log_cliente,
        fatturato_totale=fatturato_totale,
        variazione_fatturato_cliente=variazione_fatturato_cliente,
        fatturato_mensile=fatturato_mensile,
        fatturato_settimanale_list=fatturato_settimanale_list,
        target_update_id=request.args.get('update_id', type=int),
        prezzi_attuali=prezzi_attuali,
        prezzi_offerta=prezzi_offerta,
        prodotti_data=prodotti_data,
        stato_cliente=stato_cliente
    )

# ============================
# AGGIORNAMENTO SETTIMANALE CLIENTE & ANALISI PDF ACQUISTI
# ============================
@app.route('/clienti/<int:cliente_id>/aggiornamento_settimanale', methods=['POST'])
@login_required
def salva_aggiornamento_settimanale(cliente_id):
    import time
    import os
    import werkzeug.utils
    from datetime import datetime

    data_inizio_str = request.form.get('data_inizio', '').strip()
    data_fine_str = request.form.get('data_fine', '').strip()

    if not data_inizio_str or not data_fine_str:
        flash("Seleziona sia la data di inizio che la data di fine periodo.", "danger")
        return redirect(url_for('cliente_scheda', id=cliente_id))

    try:
        data_inizio = datetime.strptime(data_inizio_str, '%Y-%m-%d').date()
        data_fine = datetime.strptime(data_fine_str, '%Y-%m-%d').date()
    except ValueError:
        flash("Formato data non valido.", "danger")
        return redirect(url_for('cliente_scheda', id=cliente_id))

    mese = data_inizio.month
    anno = data_inizio.year
    settimana = data_inizio.isocalendar()[1]

    totale_fatturato = float(request.form.get('totale_fatturato', 0.0) or 0.0)
    note = request.form.get('note', '').strip()

    pdf_file = request.files.get('pdf_file')

    with get_db() as db:
        cur = db.cursor()
        
        # 1. Upsert record periodo settimanale
        target_update_id = request.form.get('update_id', type=int)

        if target_update_id:
            update_id = target_update_id
            cur.execute('''
                UPDATE fatturato_settimanale
                SET data_inizio = %s, data_fine = %s, totale = %s, note = %s, mese = %s, anno = %s, settimana = %s, data_inserimento = CURRENT_TIMESTAMP
                WHERE id = %s AND cliente_id = %s
            ''', (data_inizio, data_fine, totale_fatturato, note, mese, anno, settimana, update_id, cliente_id))
        else:
            cur.execute('''
                SELECT id FROM fatturato_settimanale
                WHERE cliente_id = %s AND (data_inizio = %s AND data_fine = %s)
            ''', (cliente_id, data_inizio, data_fine))
            esistente = cur.fetchone()

            if esistente:
                update_id = esistente['id'] if isinstance(esistente, dict) else esistente[0]
                cur.execute('''
                    UPDATE fatturato_settimanale
                    SET totale = %s, note = %s, mese = %s, anno = %s, settimana = %s, data_inserimento = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (totale_fatturato, note, mese, anno, settimana, update_id))
            else:
                cur.execute('''
                    INSERT INTO fatturato_settimanale (cliente_id, data_inizio, data_fine, settimana, mese, anno, totale, note)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ''', (cliente_id, data_inizio, data_fine, settimana, mese, anno, totale_fatturato, note))
                
                cur.execute('''
                    SELECT id FROM fatturato_settimanale
                    WHERE cliente_id = %s AND data_inizio = %s AND data_fine = %s
                    ORDER BY id DESC LIMIT 1
                ''', (cliente_id, data_inizio, data_fine))
                res_max = cur.fetchone()
                update_id = res_max['id'] if isinstance(res_max, dict) else res_max[0]

        # 2. ACCUMULA IL FATTURATO SETTIMANALE NEL MESE CORRISPONDENTE IN TABELLA FATTURATO
        cur.execute('''
            SELECT COALESCE(SUM(totale), 0) AS tot
            FROM fatturato_settimanale
            WHERE cliente_id = %s AND mese = %s AND anno = %s
        ''', (cliente_id, mese, anno))
        totale_mese_settimanale = float(cur.fetchone()['tot'] or 0)

        cur.execute('''
            SELECT id FROM fatturato
            WHERE cliente_id = %s AND mese = %s AND anno = %s
            LIMIT 1
        ''', (cliente_id, mese, anno))
        f_row = cur.fetchone()

        if f_row:
            f_id = f_row['id'] if isinstance(f_row, dict) else f_row[0]
            cur.execute('UPDATE fatturato SET totale = %s WHERE id = %s', (totale_mese_settimanale, f_id))
        else:
            cur.execute('''
                INSERT INTO fatturato (cliente_id, mese, anno, totale)
                VALUES (%s, %s, %s, %s)
            ''', (cliente_id, mese, anno, totale_mese_settimanale))

        # 3. Aggiorna fatturato totale generale cliente
        aggiorna_fatturato_totale(cliente_id, cur)

        # 4. Rimuovi vecchi dettagli per lo stesso update_id se presenti
        cur.execute('''
            DELETE FROM acquisti_settimanali_dettaglio
            WHERE cliente_id = %s AND (update_id = %s OR (data_inizio = %s AND data_fine = %s))
        ''', (cliente_id, update_id, data_inizio, data_fine))

        # 5. Salva i prodotti selezionati manualmente via Checkbox con UM, Quantita e Prezzo
        prodotti_acquistati_ids = request.form.getlist('prodotti_acquistati_ids')
        inserted_pids = set()

        for pid_str in prodotti_acquistati_ids:
            try:
                pid = int(pid_str)
                custom_price_str = request.form.get(f'prezzo_prodotto_{pid}')
                custom_um_str = request.form.get(f'um_prodotto_{pid}', 'PZ').strip().upper()
                custom_qty_str = request.form.get(f'quantita_prodotto_{pid}', '1')

                um_p = 'KG' if custom_um_str == 'KG' else 'PZ'
                try:
                    qty_p = float(custom_qty_str)
                    if qty_p <= 0: qty_p = 1.0
                except (ValueError, TypeError):
                    qty_p = 1.0

                cur.execute('''
                    SELECT p.codice, p.nome, COALESCE(c.nome, '–') AS cat, cp.prezzo_attuale, cp.prezzo_offerta, p.prezzo AS prezzo_catalogo
                    FROM prodotti p
                    LEFT JOIN categorie c ON p.categoria_id = c.id
                    LEFT JOIN clienti_prodotti cp ON (cp.prodotto_id = p.id AND cp.cliente_id = %s)
                    WHERE p.id = %s
                ''', (cliente_id, pid))
                p_info = cur.fetchone()
                if p_info:
                    info_dict = dict(p_info)
                    cod_p = info_dict.get('codice') or ''
                    nome_p = info_dict.get('nome') or ''
                    
                    prezzo_p = None
                    if custom_price_str:
                        try:
                            prezzo_p = float(custom_price_str)
                        except (ValueError, TypeError):
                            prezzo_p = None

                    if prezzo_p is None:
                        prezzo_p = float(info_dict.get('prezzo_offerta') or info_dict.get('prezzo_attuale') or info_dict.get('prezzo_catalogo') or 0.0)

                    cur.execute('''
                        INSERT INTO acquisti_settimanali_dettaglio 
                        (cliente_id, settimana, anno, update_id, data_inizio, data_fine, prodotto_id, codice_pdf, nome_pdf, um_pdf, prezzo_pdf, quantita)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (cliente_id, settimana, anno, update_id, data_inizio, data_fine, pid, cod_p, nome_p, um_p, prezzo_p, qty_p))
                    inserted_pids.add(pid)

                    # Se il prodotto non era contrassegnato come lavorato per questo cliente, o se e stato modificato il prezzo, aggiorna clienti_prodotti!
                    cur.execute('''
                        SELECT lavorato FROM clienti_prodotti WHERE cliente_id = %s AND prodotto_id = %s
                    ''', (cliente_id, pid))
                    cp_row = cur.fetchone()
                    if cp_row:
                        cur.execute('''
                            UPDATE clienti_prodotti SET lavorato = TRUE, prezzo_attuale = COALESCE(%s, prezzo_attuale) WHERE cliente_id = %s AND prodotto_id = %s
                        ''', (prezzo_p, cliente_id, pid))
                    else:
                        cur.execute('''
                            INSERT INTO clienti_prodotti (cliente_id, prodotto_id, lavorato, prezzo_attuale) VALUES (%s, %s, TRUE, %s)
                        ''', (cliente_id, pid, prezzo_p))

            except (ValueError, TypeError):
                pass

        # 6. Se inviato un file PDF, integra i prodotti estratti dal PDF
        if pdf_file and pdf_file.filename and pdf_file.filename.lower().endswith('.pdf'):
            filename = werkzeug.utils.secure_filename(pdf_file.filename)
            nome_file_saved = f"settimana_{data_inizio_str}_{int(time.time())}_{filename}"
            
            uploads_dir = os.path.join(app.static_folder, 'uploads', 'pdf_settimanali')
            os.makedirs(uploads_dir, exist_ok=True)
            file_path = os.path.join(uploads_dir, nome_file_saved)
            pdf_file.save(file_path)

            # Salva record PDF
            cur.execute('''
                INSERT INTO acquisti_settimanali_pdf (cliente_id, settimana, anno, data_inizio, data_fine, nome_file)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (cliente_id, settimana, anno, data_inizio, data_fine, nome_file_saved))

            # Estrai offerte dal PDF
            offerte = parse_offers_from_pdf(file_path)
            for off in offerte:
                codice = off.get('code')
                nome_pdf = off.get('name', '')
                um_pdf = off.get('um', 'PZ')
                prezzo_pdf = parse_decimal(off['price']) if off.get('price') else 0.0

                prodotto_id = None
                if codice:
                    cur.execute("SELECT id FROM prodotti WHERE codice = %s AND COALESCE(eliminato, FALSE) = FALSE", (codice,))
                    p_row = cur.fetchone()
                    if p_row:
                        prodotto_id = p_row['id'] if isinstance(p_row, dict) else p_row[0]

                if not prodotto_id and nome_pdf:
                    cur.execute("SELECT id FROM prodotti WHERE LOWER(nome) = LOWER(%s) AND COALESCE(eliminato, FALSE) = FALSE", (nome_pdf,))
                    p_row = cur.fetchone()
                    if p_row:
                        prodotto_id = p_row['id'] if isinstance(p_row, dict) else p_row[0]

                if prodotto_id not in inserted_pids:
                    cur.execute('''
                        INSERT INTO acquisti_settimanali_dettaglio 
                        (cliente_id, settimana, anno, update_id, data_inizio, data_fine, prodotto_id, codice_pdf, nome_pdf, um_pdf, prezzo_pdf)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (cliente_id, settimana, anno, update_id, data_inizio, data_fine, prodotto_id, codice, nome_pdf, um_pdf, float(prezzo_pdf)))
                    if prodotto_id:
                        inserted_pids.add(prodotto_id)

        db.commit()

    periodo_str = f"dal {data_inizio.strftime('%d/%m/%Y')} al {data_fine.strftime('%d/%m/%Y')}"
    flash(f"Aggiornamento settimanale ({periodo_str}) di € {totale_fatturato:.2f} salvato! Fatturato del mese {mese}/{anno} aggiornato.", "success")
    return redirect(url_for('cliente_scheda', id=cliente_id, update_id=update_id, _anchor='sezione-settimanale'))


@app.route('/clienti/<int:cliente_id>/aggiornamento_settimanale/<int:update_id>/elimina', methods=['POST'])
@login_required
def elimina_aggiornamento_settimanale(cliente_id, update_id):
    with get_db() as db:
        cur = db.cursor()
        
        # 1. Recupera informazioni prima dell'eliminazione
        cur.execute('''
            SELECT mese, anno, data_inizio, data_fine
            FROM fatturato_settimanale
            WHERE id = %s AND cliente_id = %s
        ''', (update_id, cliente_id))
        rec = cur.fetchone()

        if not rec:
            flash("Aggiornamento settimanale non trovato.", "warning")
            return redirect(url_for('cliente_scheda', id=cliente_id))

        rec_dict = dict(rec)
        mese = rec_dict.get('mese')
        anno = rec_dict.get('anno')
        d_ini = rec_dict.get('data_inizio')
        d_end = rec_dict.get('data_fine')

        if not mese and d_ini:
            mese = d_ini.month
            anno = d_ini.year

        # 2. Rimuovi dettagli prodotti
        cur.execute('''
            DELETE FROM acquisti_settimanali_dettaglio
            WHERE cliente_id = %s AND (update_id = %s OR (data_inizio = %s AND data_fine = %s))
        ''', (cliente_id, update_id, d_ini, d_end))

        # 3. Rimuovi allegati PDF
        cur.execute('''
            DELETE FROM acquisti_settimanali_pdf
            WHERE cliente_id = %s AND (data_inizio = %s AND data_fine = %s)
        ''', (cliente_id, d_ini, d_end))

        # 4. Rimuovi record settimanale principale
        cur.execute('''
            DELETE FROM fatturato_settimanale
            WHERE id = %s AND cliente_id = %s
        ''', (update_id, cliente_id))

        # 5. Ricalcola fatturato mensile per questo mese/anno
        if mese and anno:
            cur.execute('''
                SELECT COALESCE(SUM(totale), 0) AS tot
                FROM fatturato_settimanale
                WHERE cliente_id = %s AND mese = %s AND anno = %s
            ''', (cliente_id, mese, anno))
            totale_mese_settimanale = float(cur.fetchone()['tot'] or 0)

            cur.execute('''
                SELECT id FROM fatturato
                WHERE cliente_id = %s AND mese = %s AND anno = %s
                LIMIT 1
            ''', (cliente_id, mese, anno))
            f_row = cur.fetchone()

            if f_row:
                f_id = f_row['id'] if isinstance(f_row, dict) else f_row[0]
                if totale_mese_settimanale > 0:
                    cur.execute('UPDATE fatturato SET totale = %s WHERE id = %s', (totale_mese_settimanale, f_id))
                else:
                    cur.execute('DELETE FROM fatturato WHERE id = %s', (f_id,))

        # 6. Ricalcola fatturato totale generale cliente
        aggiorna_fatturato_totale(cliente_id, cur)

        db.commit()

    flash("Aggiornamento settimanale eliminato con successo. Fatturato ricalcolato.", "success")
    return redirect(url_for('cliente_scheda', id=cliente_id, _anchor='sezione-settimanale'))


@app.route('/api/clienti/<int:cliente_id>/prodotti_completi')
@login_required
def api_clienti_prodotti_completi(cliente_id):
    with get_db() as db:
        cur = db.cursor()

        # 1. Prodotti gia lavorati per il cliente
        try:
            cur.execute('''
                SELECT p.id, p.codice, p.nome, COALESCE(c.nome, '–') AS categoria_nome, cp.prezzo_attuale, cp.prezzo_offerta
                FROM clienti_prodotti cp
                JOIN prodotti p ON cp.prodotto_id = p.id
                LEFT JOIN categorie c ON p.categoria_id = c.id
                WHERE cp.cliente_id = %s AND cp.lavorato = TRUE
                ORDER BY c.nome, p.nome
            ''', (cliente_id,))
            lavorati = [dict(r) for r in cur.fetchall()]
        except Exception as _e:
            print(f"api_clienti_prodotti_completi lavorati warning: {_e}")
            lavorati = []

        pids_lavorati = set(r['id'] for r in lavorati)

        # 2. Altri prodotti a catalogo
        try:
            cur.execute('''
                SELECT p.id, p.codice, p.nome, COALESCE(c.nome, '–') AS categoria_nome, COALESCE(p.prezzo, 0.0) AS prezzo_attuale
                FROM prodotti p
                LEFT JOIN categorie c ON p.categoria_id = c.id
                ORDER BY c.nome, p.nome
            ''')
            tutti_prodotti = [dict(r) for r in cur.fetchall()]
        except Exception as _e:
            print(f"api_clienti_prodotti_completi tutti prodotti warning: {_e}")
            tutti_prodotti = []

        altri = [p for p in tutti_prodotti if p['id'] not in pids_lavorati]

    return jsonify({
        "status": "ok",
        "cliente_id": cliente_id,
        "lavorati": lavorati,
        "altri": altri
    })


@app.route('/api/clienti/<int:cliente_id>/analisi_settimanale')
@login_required
def api_analisi_settimanale(cliente_id):
    from datetime import datetime
    update_id = request.args.get('update_id', type=int)

    with get_db() as db:
        cur = db.cursor()

        if not update_id:
            cur.execute('''
                SELECT id FROM fatturato_settimanale
                WHERE cliente_id = %s
                ORDER BY data_inizio DESC, id DESC
                LIMIT 1
            ''', (cliente_id,))
            latest = cur.fetchone()
            if latest:
                update_id = latest['id'] if isinstance(latest, dict) else latest[0]

        row_sett = None
        if update_id:
            cur.execute('''
                SELECT id, data_inizio, data_fine, settimana, mese, anno, totale, note, data_inserimento
                FROM fatturato_settimanale
                WHERE id = %s AND cliente_id = %s
            ''', (update_id, cliente_id))
            row_sett = cur.fetchone()

        if not row_sett:
            return jsonify({
                "status": "ok",
                "has_data": False,
                "totale_settimana": 0.0,
                "totale_prec": 0.0,
                "delta_settimana": 0.0,
                "perc_delta": 0.0,
                "acquistati": [],
                "prodotti_mancanti": [],
                "prodotti_potenziali_mancanti": [],
                "fatturato_mancante_stimato": 0.0,
                "storico_settimanale": []
            })

        update_dict = dict(row_sett)
        data_inizio = update_dict['data_inizio']
        data_fine = update_dict['data_fine']
        totale_settimana = float(update_dict['totale'] or 0.0)
        note_settimana = update_dict.get('note', '') or ""

        if hasattr(data_inizio, 'strftime'):
            dt_ini_str = data_inizio.strftime('%d/%m/%Y')
            dt_end_str = data_fine.strftime('%d/%m/%Y') if hasattr(data_fine, 'strftime') else str(data_fine)
        else:
            dt_ini_str = str(data_inizio)
            dt_end_str = str(data_fine)

        periodo_str = f"Dal {dt_ini_str} al {dt_end_str}"

        # 2. Fatturato precedente per confronto delta
        cur.execute('''
            SELECT totale FROM fatturato_settimanale
            WHERE cliente_id = %s AND id < %s
            ORDER BY id DESC
            LIMIT 1
        ''', (cliente_id, update_id))
        row_prec = cur.fetchone()
        totale_prec = float(row_prec['totale']) if row_prec else 0.0

        delta_settimana = totale_settimana - totale_prec
        perc_delta = ((delta_settimana / totale_prec) * 100) if totale_prec > 0 else (100.0 if totale_settimana > 0 else 0.0)

        # 3. Prodotti acquistati nel periodo
        cur.execute('''
            SELECT d.id, d.prodotto_id, d.codice_pdf, d.nome_pdf, d.um_pdf, d.prezzo_pdf, COALESCE(d.quantita, 1.0) AS quantita, p.nome AS prodotto_nome, COALESCE(c.nome, '–') AS categoria_nome
            FROM acquisti_settimanali_dettaglio d
            LEFT JOIN prodotti p ON d.prodotto_id = p.id
            LEFT JOIN categorie c ON p.categoria_id = c.id
            WHERE d.cliente_id = %s AND (d.update_id = %s OR (d.data_inizio = %s AND d.data_fine = %s))
        ''', (cliente_id, update_id, data_inizio, data_fine))
        acquistati_rows = cur.fetchall()
        acquistati = []
        for r in acquistati_rows:
            rd = dict(r)
            rd['prezzo_pdf'] = float(rd['prezzo_pdf'] or 0.0)
            rd['quantita'] = float(rd['quantita'] or 1.0)
            rd['totale_riga'] = round(rd['prezzo_pdf'] * rd['quantita'], 2)
            acquistati.append(rd)

        pids_acquistati = set(r['prodotto_id'] for r in acquistati if r['prodotto_id'] is not None)

        # 4. Prodotti abituali NON ACQUISTATI
        cur.execute('''
            SELECT p.id, p.codice, p.nome, COALESCE(c.nome, '–') AS categoria_nome, cp.prezzo_attuale, cp.prezzo_offerta
            FROM clienti_prodotti cp
            JOIN prodotti p ON cp.prodotto_id = p.id
            LEFT JOIN categorie c ON p.categoria_id = c.id
            WHERE cp.cliente_id = %s AND cp.lavorato = TRUE AND COALESCE(p.eliminato, FALSE) = FALSE
        ''', (cliente_id,))
        habitual_rows = cur.fetchall()
        
        prodotti_mancanti = []
        fatturato_mancante_stimato = 0.0
        for p in habitual_rows:
            p_dict = dict(p)
            if p_dict['id'] not in pids_acquistati:
                prezzo_stimato = float(p_dict['prezzo_offerta'] or p_dict['prezzo_attuale'] or 0.0)
                p_dict['prezzo_stimato'] = prezzo_stimato
                fatturato_mancante_stimato += prezzo_stimato
                prodotti_mancanti.append(p_dict)

        # 5. Prodotti potenziali non ancora acquistati
        cur.execute('''
            SELECT p.id, p.codice, p.nome, COALESCE(c.nome, '–') AS categoria_nome
            FROM clienti_prodotti cp
            JOIN prodotti p ON cp.prodotto_id = p.id
            LEFT JOIN categorie c ON p.categoria_id = c.id
            WHERE cp.cliente_id = %s AND cp.potenziale = TRUE AND COALESCE(p.eliminato, FALSE) = FALSE
        ''', (cliente_id,))
        potenziali_rows = cur.fetchall()
        prodotti_potenziali_mancanti = [dict(p) for p in potenziali_rows if dict(p)['id'] not in pids_acquistati]

        # 6. Storico caricamenti
        cur.execute('''
            SELECT f.id, f.data_inizio, f.data_fine, f.mese, f.anno, f.totale, f.note, f.data_inserimento, p.nome_file AS pdf_nome
            FROM fatturato_settimanale f
            LEFT JOIN acquisti_settimanali_pdf p ON f.cliente_id = p.cliente_id AND (f.data_inizio = p.data_inizio AND f.data_fine = p.data_fine)
            WHERE f.cliente_id = %s
            ORDER BY f.data_inizio DESC, f.id DESC
        ''', (cliente_id,))
        storico_rows = cur.fetchall()
        storico_settimanale = []
        for s in storico_rows:
            s_dict = dict(s)
            d_ini = s_dict.get('data_inizio')
            d_end = s_dict.get('data_fine')
            if d_ini and d_end:
                ini_str = d_ini.strftime('%d/%m/%Y') if hasattr(d_ini, 'strftime') else str(d_ini)
                end_str = d_end.strftime('%d/%m/%Y') if hasattr(d_end, 'strftime') else str(d_end)
                s_dict['periodo_str'] = f"Dal {ini_str} al {end_str}"
            else:
                s_dict['periodo_str'] = f"Settimana {s_dict.get('settimana', 1)} ({s_dict.get('anno', 2026)})"
            storico_settimanale.append(s_dict)

    return jsonify({
        "status": "ok",
        "has_data": True,
        "update_id": update_id,
        "data_inizio_iso": str(data_inizio),
        "data_fine_iso": str(data_fine),
        "periodo_str": periodo_str,
        "totale_settimana": totale_settimana,
        "note_settimana": note_settimana,
        "totale_prec": totale_prec,
        "delta_settimana": delta_settimana,
        "perc_delta": perc_delta,
        "acquistati": acquistati,
        "prodotti_mancanti": prodotti_mancanti,
        "prodotti_potenziali_mancanti": prodotti_potenziali_mancanti,
        "fatturato_mancante_stimato": fatturato_mancante_stimato,
        "storico_settimanale": storico_settimanale
    })


@app.route('/api/clienti/<int:cliente_id>/statistiche_settimanali_4w')
@login_required
def api_statistiche_settimanali_4w(cliente_id):
    with get_db() as db:
        cur = db.cursor()

        # 1. Recupera le ultime 4 settimane registrate
        cur.execute('''
            SELECT id, data_inizio, data_fine, settimana, mese, anno, totale, note
            FROM fatturato_settimanale
            WHERE cliente_id = %s
            ORDER BY data_inizio DESC, id DESC
            LIMIT 4
        ''', (cliente_id,))
        rows_4w_raw = cur.fetchall()

        if not rows_4w_raw:
            return jsonify({
                "status": "ok",
                "has_data": False,
                "totale_4w": 0.0,
                "media_settimanale": 0.0,
                "settimane": [],
                "prodotti_trend": [],
                "prodotti_nuovi": [],
                "prodotti_persi": []
            })

        weeks_chronological = list(reversed([dict(r) for r in rows_4w_raw]))
        num_weeks = len(weeks_chronological)
        
        update_ids = [w['id'] for w in weeks_chronological]
        totale_4w = sum(float(w['totale'] or 0.0) for w in weeks_chronological)
        media_4w = (totale_4w / num_weeks) if num_weeks > 0 else 0.0

        perc_trend = 0.0
        stato_trend = "stabile"
        if num_weeks >= 2:
            first_w = float(weeks_chronological[0]['totale'] or 0.0)
            last_w = float(weeks_chronological[-1]['totale'] or 0.0)
            delta_trend = last_w - first_w
            if first_w > 0:
                perc_trend = (delta_trend / first_w) * 100.0
            elif last_w > 0:
                perc_trend = 100.0
            
            if perc_trend > 3.0:
                stato_trend = "crescita"
            elif perc_trend < -3.0:
                stato_trend = "calo"

        settimane = []
        for idx, w in enumerate(weeks_chronological):
            d_ini = w['data_inizio']
            d_end = w['data_fine']
            ini_str = d_ini.strftime('%d/%m') if hasattr(d_ini, 'strftime') else str(d_ini)
            end_str = d_end.strftime('%d/%m') if hasattr(d_end, 'strftime') else str(d_end)
            settimane.append({
                "update_id": w['id'],
                "label": f"{ini_str} - {end_str}",
                "totale": float(w['totale'] or 0.0),
                "index": idx
            })

        # 2. Dettaglio acquisti per prodotto nelle 4 settimane
        cur.execute('''
            SELECT d.update_id, d.prodotto_id, d.codice_pdf, d.nome_pdf, d.um_pdf, d.prezzo_pdf, COALESCE(d.quantita, 1.0) AS quantita,
                   p.id AS p_id, p.codice AS p_codice, p.nome AS p_nome, COALESCE(c.nome, '–') AS categoria_nome
            FROM acquisti_settimanali_dettaglio d
            LEFT JOIN prodotti p ON d.prodotto_id = p.id
            LEFT JOIN categorie c ON p.categoria_id = c.id
            WHERE d.cliente_id = %s AND d.update_id = ANY(%s)
        ''', (cliente_id, update_ids))
        dettagli_4w = [dict(r) for r in cur.fetchall()]

        prod_map = {}
        for d in dettagli_4w:
            pid = d['prodotto_id'] or f"pdf_{d['nome_pdf']}"
            if pid not in prod_map:
                prod_map[pid] = {
                    "prodotto_id": d['prodotto_id'],
                    "nome": d['p_nome'] or d['nome_pdf'] or 'Prodotto Sconosciuto',
                    "codice": d['p_codice'] or d['codice_pdf'] or '–',
                    "categoria": d['categoria_nome'],
                    "um": d['um_pdf'] or 'PZ',
                    "weekly_qty": [0.0] * num_weeks,
                    "weekly_euro": [0.0] * num_weeks,
                    "totale_qty": 0.0,
                    "totale_spesa": 0.0,
                    "settimane_presenze": set()
                }
            
            u_id = d['update_id']
            w_idx = next((i for i, w in enumerate(weeks_chronological) if w['id'] == u_id), None)
            if w_idx is not None:
                q = float(d['quantita'] or 1.0)
                p = float(d['prezzo_pdf'] or 0.0)
                tot_e = q * p
                
                prod_map[pid]['weekly_qty'][w_idx] += q
                prod_map[pid]['weekly_euro'][w_idx] += tot_e
                prod_map[pid]['totale_qty'] += q
                prod_map[pid]['totale_spesa'] += tot_e
                prod_map[pid]['settimane_presenze'].add(w_idx)

        prodotti_trend = []
        prodotti_nuovi = []
        prodotti_persi = []

        for pid, pdata in prod_map.items():
            wq = pdata['weekly_qty']
            t_qty = round(pdata['totale_qty'], 2)
            t_euro = round(pdata['totale_spesa'], 2)
            
            if num_weeks >= 2:
                q_first = sum(wq[:num_weeks//2])
                q_last = sum(wq[num_weeks//2:])
                if q_last > q_first * 1.05:
                    p_trend = "crescita"
                elif q_last < q_first * 0.95:
                    p_trend = "calo"
                else:
                    p_trend = "stabile"
            else:
                p_trend = "stabile"

            item_res = {
                "prodotto_id": pdata["prodotto_id"],
                "nome": pdata["nome"],
                "codice": pdata["codice"],
                "categoria": pdata["categoria"],
                "um": pdata["um"],
                "weekly_qty": [round(x, 2) for x in wq],
                "weekly_euro": [round(x, 2) for x in pdata['weekly_euro']],
                "totale_qty": t_qty,
                "totale_spesa": t_euro,
                "trend": p_trend
            }
            prodotti_trend.append(item_res)

            if num_weeks >= 2 and 0 not in pdata['settimane_presenze'] and (num_weeks - 1) in pdata['settimane_presenze']:
                prodotti_nuovi.append(item_res)

        cur.execute('''
            SELECT p.id, p.codice, p.nome, COALESCE(c.nome, '–') AS categoria, cp.prezzo_attuale, cp.prezzo_offerta
            FROM clienti_prodotti cp
            JOIN prodotti p ON cp.prodotto_id = p.id
            LEFT JOIN categorie c ON p.categoria_id = c.id
            WHERE cp.cliente_id = %s AND cp.lavorato = TRUE AND COALESCE(p.eliminato, FALSE) = FALSE
        ''', (cliente_id,))
        habitual_all = [dict(r) for r in cur.fetchall()]

        last_2_w_indices = set(range(max(0, num_weeks - 2), num_weeks))
        for hab in habitual_all:
            h_id = hab['id']
            p_entry = prod_map.get(h_id)
            has_recent = False
            if p_entry:
                if any(w_i in p_entry['settimane_presenze'] for w_i in last_2_w_indices):
                    has_recent = True
            
            if not has_recent:
                prodotti_persi.append({
                    "prodotto_id": hab['id'],
                    "nome": hab['nome'],
                    "codice": hab['codice'] or '–',
                    "categoria": hab['categoria'],
                    "prezzo": float(hab['prezzo_offerta'] or hab['prezzo_attuale'] or 0.0)
                })

        prodotti_trend.sort(key=lambda x: x['totale_spesa'], reverse=True)

        return jsonify({
            "status": "ok",
            "has_data": True,
            "num_settimane": num_weeks,
            "totale_4w": round(totale_4w, 2),
            "media_settimanale": round(media_4w, 2),
            "perc_trend": round(perc_trend, 1),
            "stato_trend": stato_trend,
            "settimane": settimane,
            "prodotti_trend": prodotti_trend,
            "prodotti_nuovi": prodotti_nuovi,
            "prodotti_persi": prodotti_persi
        })


@app.route('/api/statistiche_portfolio')
@login_required
def api_statistiche_portfolio():
    def get_first_val(row, default=0.0):
        if not row:
            return default
        if isinstance(row, dict):
            for k in ['sum', 'coalesce', 'totale', 'count']:
                if k in row:
                    return row[k]
            return list(row.values())[0]
        else:
            return row[0]

    with get_db() as db:
        cur = db.cursor()

        # 1. Calcoli dello Stato Clienti
        cur.execute('SELECT id, nome, zona FROM clienti')
        all_clienti = [dict(r) if isinstance(r, dict) else {"id": r[0], "nome": r[1], "zona": r[2]} for r in cur.fetchall()]
        tot_clienti = len(all_clienti)

        oggi = datetime.today()
        cur_month = oggi.month
        cur_year = oggi.year
        cur_day = oggi.day

        # Identifica clienti attivi, inattivi, bloccati
        # Calcoliamo i fatturati per gli ultimi periodi
        mese_prec = 12 if cur_month == 1 else cur_month - 1
        anno_prec = cur_year - 1 if cur_month == 1 else cur_year
        mese_due_fa = 12 if cur_month <= 2 else cur_month - 2
        anno_due_fa = cur_year - 1 if cur_month <= 2 else cur_year

        cur.execute('''
            SELECT 
                cliente_id,
                COALESCE(SUM(CASE WHEN mese = %s AND anno = %s THEN totale ELSE 0 END), 0) AS cur_tot,
                COALESCE(SUM(CASE WHEN mese = %s AND anno = %s THEN totale ELSE 0 END), 0) AS prec_tot,
                COALESCE(SUM(CASE WHEN mese = %s AND anno = %s THEN totale ELSE 0 END), 0) AS due_fa_tot,
                COALESCE(SUM(totale), 0) AS totale_storico
            FROM fatturato
            GROUP BY cliente_id
        ''', (cur_month, cur_year, mese_prec, anno_prec, mese_due_fa, anno_due_fa))
        fatturato_map = {}
        for r in cur.fetchall():
            d = dict(r) if isinstance(r, dict) else {"cliente_id": r[0], "cur_tot": r[1], "prec_tot": r[2], "due_fa_tot": r[3], "totale_storico": r[4]}
            fatturato_map[d["cliente_id"]] = d

        attivi = 0
        bloccati = 0
        inattivi = 0
        for c in all_clienti:
            c_id = c["id"]
            f = fatturato_map.get(c_id, {"cur_tot": 0.0, "prec_tot": 0.0, "due_fa_tot": 0.0, "totale_storico": 0.0})
            if f["cur_tot"] > 0 or f["prec_tot"] > 0:
                attivi += 1
            elif f["due_fa_tot"] > 0:
                bloccati += 1
            else:
                inattivi += 1

        # 2. Statistica del Fatturato nello stesso periodo in base al mese precedente
        # Mese corrente (MTD)
        t_mtd_start = f"{cur_year:04d}-{cur_month:02d}-01"
        t_mtd_end = oggi.strftime('%Y-%m-%d')

        # Mese precedente (PMTD)
        prev_month = 12 if cur_month == 1 else cur_month - 1
        prev_year = cur_year - 1 if cur_month == 1 else cur_year
        import calendar
        last_day_prev = calendar.monthrange(prev_year, prev_month)[1]
        prev_day_end = min(cur_day, last_day_prev)
        t_pmtd_start = f"{prev_year:04d}-{prev_month:02d}-01"
        t_pmtd_end = f"{prev_year:04d}-{prev_month:02d}-{prev_day_end:02d}"

        cur.execute('SELECT SUM(totale) FROM fatturato_settimanale WHERE data_inizio >= %s AND data_inizio <= %s', (t_mtd_start, t_mtd_end))
        mtd_tot = float(get_first_val(cur.fetchone()) or 0.0)

        cur.execute('SELECT SUM(totale) FROM fatturato_settimanale WHERE data_inizio >= %s AND data_inizio <= %s', (t_pmtd_start, t_pmtd_end))
        pmtd_tot = float(get_first_val(cur.fetchone()) or 0.0)

        delta_pmtd = mtd_tot - pmtd_tot
        perc_pmtd = round((delta_pmtd / pmtd_tot * 100), 1) if pmtd_tot > 0 else 100.0 if mtd_tot > 0 else 0.0

        # Totale storico cumulato
        cur.execute('SELECT SUM(totale) FROM fatturato_settimanale')
        tot_cumulato = float(get_first_val(cur.fetchone()) or 0.0)

        # 3. Differenze fatturati ultime settimane (Ultime 6 settimane)
        cur.execute('''
            SELECT data_inizio, data_fine, SUM(totale) AS totale_settimana
            FROM fatturato_settimanale
            GROUP BY data_inizio, data_fine
            ORDER BY data_inizio DESC, data_fine DESC
            LIMIT 6
        ''')
        weeks_raw = cur.fetchall()
        weeks_chrono = []
        for r in reversed(weeks_raw):
            if isinstance(r, dict):
                d_ini = r.get('data_inizio')
                d_end = r.get('data_fine')
                tot = float(r.get('totale_settimana') or r.get('sum') or 0.0)
            else:
                d_ini = r[0]
                d_end = r[1]
                tot = float(r[2] or 0.0)
            
            ini_str = d_ini.strftime('%d/%m') if hasattr(d_ini, 'strftime') else str(d_ini)
            end_str = d_end.strftime('%d/%m') if hasattr(d_end, 'strftime') else str(d_end)
            
            weeks_chrono.append({
                "label": f"{ini_str} - {end_str}",
                "totale": round(tot, 2),
                "delta": 0.0,
                "perc": 0.0
            })

        for i in range(1, len(weeks_chrono)):
            prev_val = weeks_chrono[i-1]["totale"]
            cur_val = weeks_chrono[i]["totale"]
            diff = cur_val - prev_val
            perc = round((diff / prev_val * 100), 1) if prev_val > 0 else 100.0 if cur_val > 0 else 0.0
            weeks_chrono[i]["delta"] = round(diff, 2)
            weeks_chrono[i]["perc"] = perc

        # 4. Prodotti Inseriti / Persi nelle ultime 4 settimane
        cur.execute('SELECT DISTINCT data_inizio FROM fatturato_settimanale ORDER BY data_inizio DESC LIMIT 4')
        last_4w_dates = [r['data_inizio'] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
        
        prev_4w_dates = []
        if last_4w_dates:
            min_last_date = min(last_4w_dates)
            cur.execute('SELECT DISTINCT data_inizio FROM fatturato_settimanale WHERE data_inizio < %s ORDER BY data_inizio DESC LIMIT 4', (min_last_date,))
            prev_4w_dates = [r['data_inizio'] if isinstance(r, dict) else r[0] for r in cur.fetchall()]

        prodotti_nuovi = []
        prodotti_persi = []

        if last_4w_dates and prev_4w_dates:
            last_placeholders = ",".join(["%s"] * len(last_4w_dates))
            prev_placeholders = ",".join(["%s"] * len(prev_4w_dates))

            # Nuovi prodotti inseriti
            query_nuovi = f'''
                SELECT p.id, p.codice, p.nome, COALESCE(cat.nome, '–') AS categoria, SUM(d.quantita) AS tot_qty, COUNT(DISTINCT d.cliente_id) AS tot_clienti
                FROM acquisti_settimanali_dettaglio d
                JOIN prodotti p ON d.prodotto_id = p.id
                LEFT JOIN categorie cat ON p.categoria_id = cat.id
                WHERE d.data_inizio IN ({last_placeholders})
                  AND d.prodotto_id NOT IN (
                      SELECT DISTINCT prodotto_id FROM acquisti_settimanali_dettaglio
                      WHERE data_inizio IN ({prev_placeholders}) AND prodotto_id IS NOT NULL
                  )
                GROUP BY p.id, p.codice, p.nome, cat.nome
                ORDER BY tot_qty DESC LIMIT 8
            '''
            cur.execute(query_nuovi, last_4w_dates + prev_4w_dates)
            for r in cur.fetchall():
                d = dict(r) if isinstance(r, dict) else {"id": r[0], "codice": r[1], "nome": r[2], "categoria": r[3], "tot_qty": r[4], "tot_clienti": r[5]}
                prodotti_nuovi.append({
                    "id": d["id"],
                    "codice": d["codice"] or '–',
                    "nome": d["nome"],
                    "categoria": d["categoria"],
                    "tot_qty": round(float(d["tot_qty"] or 0.0), 1),
                    "tot_clienti": d["tot_clienti"]
                })

            # Prodotti persi
            query_persi = f'''
                SELECT p.id, p.codice, p.nome, COALESCE(cat.nome, '–') AS categoria, SUM(d.quantita) AS tot_qty, COUNT(DISTINCT d.cliente_id) AS tot_clienti
                FROM acquisti_settimanali_dettaglio d
                JOIN prodotti p ON d.prodotto_id = p.id
                LEFT JOIN categorie cat ON p.categoria_id = cat.id
                WHERE d.data_inizio IN ({prev_placeholders})
                  AND d.prodotto_id NOT IN (
                      SELECT DISTINCT prodotto_id FROM acquisti_settimanali_dettaglio
                      WHERE d.data_inizio IN ({last_placeholders}) AND prodotto_id IS NOT NULL
                  )
                GROUP BY p.id, p.codice, p.nome, cat.nome
                ORDER BY tot_qty DESC LIMIT 8
            '''
            cur.execute(query_persi, prev_4w_dates + last_4w_dates)
            for r in cur.fetchall():
                d = dict(r) if isinstance(r, dict) else {"id": r[0], "codice": r[1], "nome": r[2], "categoria": r[3], "tot_qty": r[4], "tot_clienti": r[5]}
                prodotti_persi.append({
                    "id": d["id"],
                    "codice": d["codice"] or '–',
                    "nome": d["nome"],
                    "categoria": d["categoria"],
                    "tot_qty": round(float(d["tot_qty"] or 0.0), 1),
                    "tot_clienti": d["tot_clienti"]
                })

        # 5. Top growing and declining clients
        growing_clients = []
        declining_clients = []
        if last_4w_dates and prev_4w_dates:
            last_placeholders = ",".join(["%s"] * len(last_4w_dates))
            prev_placeholders = ",".join(["%s"] * len(prev_4w_dates))

            cur.execute(f'''
                SELECT c.id, c.nome, c.zona,
                       COALESCE(SUM(CASE WHEN f.data_inizio IN ({last_placeholders}) THEN f.totale ELSE 0 END), 0) AS cur_tot,
                       COALESCE(SUM(CASE WHEN f.data_inizio IN ({prev_placeholders}) THEN f.totale ELSE 0 END), 0) AS prev_tot
                FROM clienti c
                LEFT JOIN fatturato_settimanale f ON c.id = f.cliente_id
                GROUP BY c.id, c.nome, c.zona
            ''', last_4w_dates + prev_4w_dates)
            
            clienti_performance = []
            for r in cur.fetchall():
                d = dict(r) if isinstance(r, dict) else {"id": r[0], "nome": r[1], "zona": r[2], "cur_tot": r[3], "prev_tot": r[4]}
                cur_tot = float(d["cur_tot"] or 0.0)
                prev_tot = float(d["prev_tot"] or 0.0)
                delta = cur_tot - prev_tot
                perc = round((delta / prev_tot * 100), 1) if prev_tot > 0 else 100.0 if cur_tot > 0 else 0.0

                clienti_performance.append({
                    "id": d["id"],
                    "nome": d["nome"],
                    "zona": d["zona"] or '–',
                    "cur_tot": round(cur_tot, 2),
                    "prev_tot": round(prev_tot, 2),
                    "delta": round(delta, 2),
                    "perc": perc
                })

            growing_clients = [c for c in clienti_performance if c["delta"] > 0.1]
            growing_clients.sort(key=lambda x: x["delta"], reverse=True)
            growing_clients = growing_clients[:5]

            declining_clients = [c for c in clienti_performance if c["delta"] < -0.1]
            declining_clients.sort(key=lambda x: x["delta"])
            declining_clients = declining_clients[:5]

        # 6. Ripartizione zone con clienti e fatturato
        # Calcoliamo i fatturati per zona
        cur.execute('''
            SELECT c.zona, COUNT(DISTINCT c.id) AS num_clienti, COALESCE(SUM(f.totale), 0) AS tot_fatturato
            FROM clienti c
            LEFT JOIN fatturato_settimanale f ON c.id = f.cliente_id
            GROUP BY c.zona
            ORDER BY tot_fatturato DESC
        ''')
        zone_perf = []
        for r in cur.fetchall():
            d = dict(r) if isinstance(r, dict) else {"zona": r[0], "num_clienti": r[1], "tot_fatturato": r[2]}
            z_name = d["zona"] or 'Altre Zone'
            n_cli = int(d["num_clienti"] or 0)
            tot_fat = float(d["tot_fatturato"] or 0.0)
            avg_cli = round(tot_fat / n_cli, 2) if n_cli > 0 else 0.0
            zone_perf.append({
                "zona": z_name,
                "num_clienti": n_cli,
                "tot_fatturato": round(tot_fat, 2),
                "avg_per_cliente": avg_cli
            })

        # Top 5 clienti per fatturato settimanale assoluto degli ultimi 4 update
        top_clienti_4w = []
        if last_4w_dates:
            last_placeholders = ",".join(["%s"] * len(last_4w_dates))
            cur.execute(f'''
                SELECT c.id, c.nome, c.zona, SUM(f.totale) AS tot_4w
                FROM clienti c
                JOIN fatturato_settimanale f ON c.id = f.cliente_id
                WHERE f.data_inizio IN ({last_placeholders})
                GROUP BY c.id, c.nome, c.zona
                ORDER BY tot_4w DESC
                LIMIT 5
            ''', last_4w_dates)
            for r in cur.fetchall():
                d = dict(r) if isinstance(r, dict) else {"id": r[0], "nome": r[1], "zona": r[2], "tot_4w": r[3]}
                top_clienti_4w.append({
                    "id": d["id"],
                    "nome": d["nome"],
                    "zona": d["zona"] or '–',
                    "totale_4w": round(float(d["tot_4w"] or 0.0), 2)
                })

        return jsonify({
            "status": "ok",
            "tot_clienti": tot_clienti,
            "attivi": attivi,
            "bloccati": bloccati,
            "inattivi": inattivi,
            "mtd_tot": round(mtd_tot, 2),
            "pmtd_tot": round(pmtd_tot, 2),
            "delta_pmtd": round(delta_pmtd, 2),
            "perc_pmtd": perc_pmtd,
            "tot_cumulato": round(tot_cumulato, 2),
            "weeks_chrono": weeks_chrono,
            "prodotti_nuovi": prodotti_nuovi,
            "prodotti_persi": prodotti_persi,
            "growing_clients": growing_clients,
            "declining_clients": declining_clients,
            "zone_perf": zone_perf,
            "top_clienti_4w": top_clienti_4w
        })



@app.route('/clienti/promo_scadenze/carica', methods=['POST'])
@login_required
def carica_promo_scadenze():
    referer = request.referrer or url_for('clienti')
    redirect_url = url_for('lista_volantini_beta') if 'beta-volantini' in referer else url_for('clienti')

    pdf_file = request.files.get('pdf_file')
    if not pdf_file or not pdf_file.filename:
        flash("Seleziona un file PDF valido.", "warning")
        return redirect(redirect_url)

    if not pdf_file.filename.lower().endswith('.pdf'):
        flash("Il file caricato deve essere in formato PDF.", "warning")
        return redirect(redirect_url)

    # Salvataggio temporaneo
    import tempfile
    temp_dir = tempfile.gettempdir()
    temp_path = os.path.join(temp_dir, f"promo_scad_{int(time.time())}.pdf")
    pdf_file.save(temp_path)

    try:
        # Estrai prodotti dal PDF usando la funzione specifica per le scadenze
        offers = parse_promo_scadenze_from_pdf(temp_path)
        
        if not offers:
            flash("Nessun prodotto trovato nel file PDF.", "warning")
            return redirect(redirect_url)

        with get_db() as db:
            cur = db.cursor()
            
            # Caricamento in memoria di tutti i codici prodotto per lookup istantaneo (ottimizzazione O(1))
            cur.execute("SELECT id, codice FROM prodotti WHERE codice IS NOT NULL AND codice != ''")
            prod_map = {}
            for r in cur.fetchall():
                p_dict = dict(r) if isinstance(r, dict) else {"id": r[0], "codice": r[1]}
                cod = str(p_dict["codice"]).strip()
                prod_map[cod] = p_dict["id"]
                prod_map[cod.lstrip('0')] = p_dict["id"]
                try:
                    prod_map[str(int(cod))] = p_dict["id"]
                except ValueError:
                    pass

            # Pulisce le promo precedenti (azzerare quella precedente)
            cur.execute('DELETE FROM promo_scadenze_prodotti')

            # Prepara il batch di dati da inserire
            insert_data = []
            for off in offers:
                code = off.get('code')
                name = off.get('name', 'Prodotto')
                price = off.get('price', 0.0)
                um = off.get('um', 'PZ')
                scadenza = off.get('scadenza', '')
                quantita = off.get('quantita', '')
                cat_name = off.get('categoria', 'SCADENZE').upper().strip()

                # Trova corrispondenza
                prodotto_id = None
                if code:
                    prodotto_id = prod_map.get(code)
                    if not prodotto_id:
                        prodotto_id = prod_map.get(code.lstrip('0'))
                    if not prodotto_id:
                        try:
                            prodotto_id = prod_map.get(str(int(code)))
                        except ValueError:
                            pass

                # Se non esiste nel database, lo creiamo direttamente!
                if not prodotto_id:
                    # Trova o crea la categoria in tempo reale
                    cur.execute("SELECT id FROM categorie WHERE nome = %s LIMIT 1", (cat_name,))
                    cat_row = cur.fetchone()
                    if cat_row:
                        cat_id = cat_row['id'] if isinstance(cat_row, dict) else cat_row[0]
                    else:
                        cur.execute("INSERT INTO categorie (nome) VALUES (%s) RETURNING id", (cat_name,))
                        try:
                            cat_row = cur.fetchone()
                            cat_id = cat_row['id'] if isinstance(cat_row, dict) else cat_row[0]
                        except Exception:
                            cur.execute("SELECT id FROM categorie WHERE nome = %s LIMIT 1", (cat_name,))
                            cat_row = cur.fetchone()
                            cat_id = cat_row['id'] if isinstance(cat_row, dict) else cat_row[0]

                    price_str = f"{price:.2f}"
                    cur.execute("""
                        INSERT INTO prodotti (codice, nome, prezzo, prezzo_con_simbolo, is_promo_mensile, categoria_id)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (code, name, price, f"€ {price_str}", False, cat_id))
                    try:
                        row_new = cur.fetchone()
                        if row_new:
                            prodotto_id = row_new['id'] if isinstance(row_new, dict) else row_new[0]
                    except Exception:
                        pass
                    if not prodotto_id:
                        cur.execute("SELECT id FROM prodotti WHERE codice = %s LIMIT 1", (code,))
                        row_new = cur.fetchone()
                        if row_new:
                            prodotto_id = row_new['id'] if isinstance(row_new, dict) else row_new[0]
                    
                    # Aggiorniamo la mappa in memoria
                    if prodotto_id:
                        prod_map[code] = prodotto_id

                insert_data.append((code, name, price, um, scadenza, quantita, prodotto_id))

            # Inserimento batch ad altissime prestazioni
            cur.executemany('''
                INSERT INTO promo_scadenze_prodotti (codice, nome, prezzo, um, scadenza, quantita, prodotto_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', insert_data)
            
            db.commit()
            flash(f"Promo scadenze caricata con successo! Trovati e sincronizzati {len(offers)} prodotti.", "success")
    except Exception as e:
        flash(f"Si è verificato un errore durante l'elaborazione del PDF: {e}", "danger")
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass

    return redirect(redirect_url)


@app.route('/api/salva_preset_default', methods=['POST'])
@login_required
def api_salva_preset_default():
    try:
        preset_data = request.json or {}
        
        # Salva in preset_default.json nella project root
        preset_path = os.path.join(app.root_path, 'preset_default.json')
        with open(preset_path, 'w', encoding='utf-8') as f:
            json.dump(preset_data, f, ensure_ascii=False, indent=4)
            
        return jsonify({"status": "ok", "message": "Preset salvato come Default sul server!"})
    except Exception as e:
        print("Errore nel salvataggio del preset di default:", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/carica_preset_default', methods=['GET'])
@login_required
def api_carica_preset_default():
    try:
        preset_path = os.path.join(app.root_path, 'preset_default.json')
        if os.path.exists(preset_path):
            with open(preset_path, 'r', encoding='utf-8') as f:
                preset_data = json.load(f)
            return jsonify({"status": "ok", "preset": preset_data})
        else:
            return jsonify({"status": "not_found", "message": "Nessun preset default salvato sul server"})
    except Exception as e:
        print("Errore nel caricamento del preset di default:", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/importa-pdf-scadenze', methods=['POST'])
@login_required
def api_importa_pdf_scadenze():
    if 'pdf_file' not in request.files:
        return jsonify({"status": "error", "message": "Nessun file inviato"}), 400
        
    pdf_file = request.files['pdf_file']
    if pdf_file.filename == '':
        return jsonify({"status": "error", "message": "Nessun file selezionato"}), 400
        
    if not pdf_file.filename.lower().endswith('.pdf'):
        return jsonify({"status": "error", "message": "Il file deve essere un PDF"}), 400

    import tempfile
    temp_dir = tempfile.gettempdir()
    temp_path = os.path.join(temp_dir, f"promo_scad_{int(time.time())}.pdf")
    pdf_file.save(temp_path)

    try:
        offers = parse_promo_scadenze_from_pdf(temp_path)
        if not offers:
            return jsonify({"status": "error", "message": "Nessun prodotto trovato nel PDF"}), 400

        with get_db() as db:
            cur = db.cursor()
            
            # Carica in memoria i prodotti per codice
            cur.execute("SELECT id, codice FROM prodotti WHERE codice IS NOT NULL AND codice != ''")
            prod_map = {}
            for r in cur.fetchall():
                p_dict = dict(r) if isinstance(r, dict) else {"id": r[0], "codice": r[1]}
                cod = str(p_dict["codice"]).strip()
                prod_map[cod] = p_dict["id"]
                prod_map[cod.lstrip('0')] = p_dict["id"]
                try:
                    prod_map[str(int(cod))] = p_dict["id"]
                except ValueError:
                    pass

            # Pulisce le promo scadenze precedenti
            cur.execute('DELETE FROM promo_scadenze_prodotti')

            insert_data = []
            for off in offers:
                code = off.get('code')
                name = off.get('name', 'Prodotto')
                price = off.get('price', 0.0)
                um = off.get('um', 'PZ')
                scadenza = off.get('scadenza', '')
                quantita = off.get('quantita', '')
                cat_name = off.get('categoria', 'SCADENZE').upper().strip()

                prodotto_id = None
                if code:
                    prodotto_id = prod_map.get(code)
                    if not prodotto_id:
                        prodotto_id = prod_map.get(code.lstrip('0'))
                    if not prodotto_id:
                        try:
                            prodotto_id = prod_map.get(str(int(code)))
                        except ValueError:
                            pass

                # Se non esiste nel database, lo creiamo direttamente!
                if not prodotto_id:
                    # Trova o crea la categoria in tempo reale
                    cur.execute("SELECT id FROM categorie WHERE nome = %s LIMIT 1", (cat_name,))
                    cat_row = cur.fetchone()
                    if cat_row:
                        cat_id = cat_row['id'] if isinstance(cat_row, dict) else cat_row[0]
                    else:
                        cur.execute("INSERT INTO categorie (nome) VALUES (%s) RETURNING id", (cat_name,))
                        try:
                            cat_row = cur.fetchone()
                            cat_id = cat_row['id'] if isinstance(cat_row, dict) else cat_row[0]
                        except Exception:
                            cur.execute("SELECT id FROM categorie WHERE nome = %s LIMIT 1", (cat_name,))
                            cat_row = cur.fetchone()
                            cat_id = cat_row['id'] if isinstance(cat_row, dict) else cat_row[0]

                    price_str = f"{price:.2f}"
                    cur.execute("""
                        INSERT INTO prodotti (codice, nome, prezzo, prezzo_con_simbolo, is_promo_mensile, categoria_id)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (code, name, price, f"€ {price_str}", False, cat_id))
                    try:
                        row_new = cur.fetchone()
                        if row_new:
                            prodotto_id = row_new['id'] if isinstance(row_new, dict) else row_new[0]
                    except Exception:
                        pass
                    if not prodotto_id:
                        cur.execute("SELECT id FROM prodotti WHERE codice = %s LIMIT 1", (code,))
                        row_new = cur.fetchone()
                        if row_new:
                            prodotto_id = row_new['id'] if isinstance(row_new, dict) else row_new[0]
                    
                    # Aggiorniamo la mappa in memoria
                    if prodotto_id:
                        prod_map[code] = prodotto_id

                insert_data.append((code, name, price, um, scadenza, quantita, prodotto_id))

            cur.executemany('''
                INSERT INTO promo_scadenze_prodotti (codice, nome, prezzo, um, scadenza, quantita, prodotto_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', insert_data)
            
            db.commit()

        return jsonify({
            "status": "ok",
            "message": f"Promo scadenze caricata con successo! Sincronizzati {len(offers)} prodotti.",
            "count": len(offers)
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Errore scansione ed elaborazione: {str(e)}"}), 500
    finally:
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass


@app.route('/api/promo_scadenze')
@login_required
def api_promo_scadenze():
    with get_db() as db:
        cur = db.cursor()
        
        # Seleziona tutti i prodotti caricati nella promo scadenze attuale
        cur.execute('''
            SELECT id, codice, nome, prezzo, um, scadenza, quantita, prodotto_id
            FROM promo_scadenze_prodotti
            ORDER BY id
        ''')
        rows = cur.fetchall()
        
        prodotti_promo = []
        prod_ids = []
        for r in rows:
            p_dict = dict(r) if isinstance(r, dict) else {
                "id": r[0], "codice": r[1], "nome": r[2], "prezzo": r[3], "um": r[4], "scadenza": r[5], "quantita": r[6], "prodotto_id": r[7]
            }
            pid = p_dict["prodotto_id"]
            prodotti_promo.append({
                "id": p_dict["id"],
                "codice": p_dict["codice"] or '–',
                "nome": p_dict["nome"],
                "prezzo": p_dict["prezzo"] or 0.0,
                "um": p_dict["um"] or 'PZ',
                "scadenza": p_dict["scadenza"] or '–',
                "quantita": p_dict["quantita"] or '–',
                "prodotto_id": pid,
                "clienti": []
            })
            if pid:
                prod_ids.append(pid)
                
        # Carica tutti i clienti associati in una singola query
        clienti_per_prodotto = {}
        if prod_ids:
            placeholders = ",".join(["%s"] * len(prod_ids))
            phone_col = _detect_phone_column(cur) or "telefono"
            cur.execute(f'''
                SELECT cp.prodotto_id, c.id AS cliente_id, c.nome AS cliente_nome, c.zona AS cliente_zona, c.{phone_col} AS cliente_telefono
                FROM clienti_prodotti cp
                JOIN clienti c ON cp.cliente_id = c.id
                WHERE cp.prodotto_id IN ({placeholders}) AND cp.lavorato = TRUE
                ORDER BY c.nome
            ''', prod_ids)
            for r in cur.fetchall():
                d = dict(r) if isinstance(r, dict) else {
                    "prodotto_id": r[0], "cliente_id": r[1], "cliente_nome": r[2], "cliente_zona": r[3], "cliente_telefono": r[4]
                }
                pid_val = d["prodotto_id"]
                if pid_val not in clienti_per_prodotto:
                    clienti_per_prodotto[pid_val] = []
                clienti_per_prodotto[pid_val].append({
                    "id": d["cliente_id"],
                    "nome": d["cliente_nome"],
                    "zona": d["cliente_zona"] or '–',
                    "telefono": d["cliente_telefono"] or ''
                })
                
        # Associa i clienti in memoria in O(1)
        for p in prodotti_promo:
            pid = p["prodotto_id"]
            if pid in clienti_per_prodotto:
                p["clienti"] = clienti_per_prodotto[pid]
            
        return jsonify({
            "status": "ok",
            "has_data": len(prodotti_promo) > 0,
            "prodotti": prodotti_promo
        })


@app.route('/clienti/rimuovi/<int:id>', methods=['POST'])
@login_required
def elimina_cliente(id):
    with get_db() as db:
        cur = db.cursor()
        cur.execute('SELECT * FROM clienti WHERE id=%s', (id,))
        cliente = cur.fetchone()
        if not cliente:
            flash('Cliente non trovato.', 'danger')
            return redirect(url_for('clienti'))

        cur.execute('DELETE FROM fatturato WHERE cliente_id=%s', (id,))
        cur.execute('DELETE FROM clienti_prodotti WHERE cliente_id=%s', (id,))
        cur.execute('DELETE FROM clienti WHERE id=%s', (id,))
        db.commit()
        flash('Cliente rimosso con successo.', 'success')
        return redirect(url_for('clienti'))


@app.route('/clienti/fatturato_totale')
@login_required
def fatturato_totale_clienti():
    with get_db() as db:
        cur = db.cursor()
        cur.execute('''
            SELECT c.id, c.nome, c.zona, COALESCE(SUM(f.totale),0) AS fatturato_totale
            FROM clienti c
            LEFT JOIN fatturato f ON c.id=f.cliente_id
            GROUP BY c.id, c.nome, c.zona
            ORDER BY fatturato_totale DESC, c.nome ASC
        ''')
        clienti = cur.fetchall()
    return render_template('01_clienti/05_fatturato_totale.html', clienti=clienti)

# ============================
# ROUTE PRODOTTI
# ============================

@app.route('/prodotti')
@login_required
def prodotti():
    q = request.args.get('q', '').strip()

    with get_db() as db:
        cur = db.cursor()
        # Recupera tutte le categorie
        cur.execute('SELECT id, nome, immagine FROM categorie ORDER BY nome')
        categorie_rows = cur.fetchall()
        categorie = [{'id': c['id'], 'nome': c['nome'], 'immagine': c['immagine'] or None} for c in categorie_rows]

        # Prodotti per categoria
        prodotti_per_categoria = {}
        for c in categorie:
            query = '''
                SELECT p.id, p.nome, p.codice, p.categoria_id
                FROM prodotti p
                LEFT JOIN categorie c ON p.categoria_id = c.id
                WHERE c.nome = %s AND COALESCE(p.eliminato, FALSE) = FALSE
            '''
            params = [c['nome']]
            if q:
                query += ' AND p.nome ILIKE %s'
                params.append(f'%{q}%')
            cur.execute(query, params)
            prodotti_rows = cur.fetchall()
            prodotti_per_categoria[c['nome']] = [dict(p) for p in prodotti_rows]

        # Prodotti senza categoria
        query_senza = '''
            SELECT p.id, p.nome, p.codice, p.categoria_id
            FROM prodotti p
            WHERE p.categoria_id IS NULL AND COALESCE(p.eliminato, FALSE) = FALSE
        '''
        params_senza = []
        if q:
            query_senza += ' AND p.nome ILIKE %s'
            params_senza.append(f'%{q}%')
        cur.execute(query_senza, params_senza)
        prodotti_senza_rows = cur.fetchall()
        prodotti_senza_categoria = [dict(p) for p in prodotti_senza_rows]

        # Tutti i prodotti attivi (per lo strumento di gestione massiva)
        cur.execute('''
            SELECT p.id, p.nome, p.codice, p.categoria_id, c.nome AS categoria_nome
            FROM prodotti p
            LEFT JOIN categorie c ON p.categoria_id = c.id
            WHERE COALESCE(p.eliminato, FALSE) = FALSE
            ORDER BY p.nome
        ''')
        tutti_rows = cur.fetchall()
        tutti_i_prodotti = [dict(r) for r in tutti_rows]

    return render_template(
        '02_prodotti/01_prodotti.html',
        prodotti_per_categoria=prodotti_per_categoria,
        categorie=categorie,
        prodotti_senza_categoria=prodotti_senza_categoria,
        tutti_i_prodotti=tutti_i_prodotti
    )


@app.route('/api/prodotti/quick_edit/<int:id>', methods=['POST'])
@login_required
def api_prodotto_quick_edit(id):
    nome = request.form.get('nome', '').strip()
    categoria_id = request.form.get('categoria_id')
    
    if categoria_id == "" or categoria_id == "None" or categoria_id == "null":
        categoria_id = None
    else:
        try:
            categoria_id = int(categoria_id)
        except ValueError:
            categoria_id = None
            
    if not nome:
        return jsonify({'success': False, 'message': 'Il nome del prodotto è obbligatorio.'}), 400
        
    with get_db() as db:
        cur = db.cursor()
        cur.execute('UPDATE prodotti SET nome = %s, categoria_id = %s WHERE id = %s', (nome, categoria_id, id))
        db.commit()
        
    return jsonify({'success': True, 'message': 'Prodotto aggiornato con successo.'})


@app.route('/prodotti/aggiungi', methods=['GET', 'POST'])
@login_required
def aggiungi_prodotto():
    with get_db() as db:
        cur = db.cursor()
        cur.execute('SELECT id, nome FROM categorie ORDER BY nome')
        categorie = cur.fetchall()

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        codice = request.form.get('codice', '').strip()
        categoria_id = request.form.get('categoria_id')
        nuova_categoria = request.form.get('nuova_categoria', '').strip()

        if not nome:
            flash('Il nome del prodotto è obbligatorio.', 'danger')
            return render_template('02_prodotti/02_aggiungi_prodotto.html', categorie=categorie)

        if not codice:
            return render_template('02_prodotti/02_aggiungi_prodotto.html', categorie=categorie, errore_codice='Il codice prodotto è obbligatorio.')

        with get_db() as db:
            cur = db.cursor()
            # Controlla se il codice esiste già per un prodotto attivo
            cur.execute('SELECT id FROM prodotti WHERE codice=%s AND COALESCE(eliminato, FALSE)=FALSE', (codice,))
            if cur.fetchone():
                return render_template('02_prodotti/02_aggiungi_prodotto.html', categorie=categorie, errore_codice='Questo codice prodotto è già utilizzato da un altro prodotto attivo.')

            if nuova_categoria:
                cur.execute('SELECT id FROM categorie WHERE nome=%s', (nuova_categoria,))
                categoria_row = cur.fetchone()
                if categoria_row:
                    categoria_id = categoria_row['id']
                else:
                    cur.execute('INSERT INTO categorie (nome) VALUES (%s) RETURNING id', (nuova_categoria,))
                    categoria_id = cur.fetchone()['id']
            else:
                categoria_id = int(categoria_id) if categoria_id else None

            cur.execute('INSERT INTO prodotti (codice, nome, categoria_id) VALUES (%s, %s, %s)', (codice, nome, categoria_id))
            db.commit()

        flash(f'Prodotto "{nome}" aggiunto con successo.', 'success')
        return redirect(url_for('prodotti'))

    return render_template('02_prodotti/02_aggiungi_prodotto.html', categorie=categorie)


@app.route('/prodotti/modifica/<int:id>', methods=['GET', 'POST'])
@login_required
def modifica_prodotto(id):
    with get_db() as db:
        cur = db.cursor()
        cur.execute('SELECT * FROM prodotti WHERE id=%s', (id,))
        prodotto = cur.fetchone()
        if not prodotto:
            abort(404)
        cur.execute('SELECT id, nome FROM categorie ORDER BY nome')
        categorie = cur.fetchall()

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        codice = request.form.get('codice', '').strip()
        categoria_id = request.form.get('categoria_id')
        nuova_categoria = request.form.get('nuova_categoria', '').strip()
        error = None

        if not nome:
            error = 'Il nome del prodotto è obbligatorio.'
            return render_template('02_prodotti/03_modifica_prodotto.html', prodotto=prodotto, categorie=categorie, error=error)

        if not codice:
            return render_template('02_prodotti/03_modifica_prodotto.html', prodotto=prodotto, categorie=categorie, errore_codice='Il codice prodotto è obbligatorio.')

        with get_db() as db:
            cur = db.cursor()
            # Controlla se il codice esiste già per un altro prodotto attivo
            cur.execute('SELECT id FROM prodotti WHERE codice=%s AND id!=%s AND COALESCE(eliminato, FALSE)=FALSE', (codice, id))
            if cur.fetchone():
                return render_template('02_prodotti/03_modifica_prodotto.html', prodotto=prodotto, categorie=categorie, errore_codice='Questo codice prodotto è già utilizzato da un altro prodotto attivo.')

            if nuova_categoria:
                cur.execute('SELECT id FROM categorie WHERE nome=%s', (nuova_categoria,))
                categoria_row = cur.fetchone()
                if categoria_row:
                    categoria_id = categoria_row['id']
                else:
                    cur.execute('INSERT INTO categorie (nome) VALUES (%s) RETURNING id', (nuova_categoria,))
                    categoria_id = cur.fetchone()['id']
            else:
                categoria_id = int(categoria_id) if categoria_id else None

            cur.execute('UPDATE prodotti SET codice=%s, nome=%s, categoria_id=%s WHERE id=%s', (codice, nome, categoria_id, id))
            db.commit()

        flash(f'Prodotto "{nome}" modificato con successo.', 'success')
        return redirect(url_for('prodotti'))

    return render_template('02_prodotti/03_modifica_prodotto.html', prodotto=prodotto, categorie=categorie, error=None)


@app.route('/prodotti/elimina/<int:id>', methods=['POST'])
@login_required
def elimina_prodotto(id):
    with get_db() as db:
        cur = db.cursor()
        cur.execute('SELECT nome FROM prodotti WHERE id=%s', (id,))
        prodotto = cur.fetchone()
        if not prodotto:
            flash('Prodotto non trovato.', 'danger')
            return redirect(url_for('prodotti'))

        # Soft delete: Rimuove associazioni attive e segna come eliminato
        cur.execute('DELETE FROM clienti_prodotti WHERE prodotto_id = %s', (id,))
        cur.execute('DELETE FROM prodotti_rimossi WHERE prodotto_id = %s', (id,))
        cur.execute('UPDATE prodotti SET eliminato = TRUE WHERE id = %s', (id,))
        db.commit()
        flash(f'Prodotto "{prodotto["nome"]}" eliminato con successo.', 'success')
        return redirect(url_for('prodotti'))


@app.route('/prodotti/elimina-selezionati', methods=['POST'])
@login_required
def elimina_prodotti_selezionati():
    ids = request.form.getlist('prodotto_ids')
    if not ids:
        flash('Nessun prodotto selezionato.', 'warning')
        return redirect(url_for('prodotti'))

    # Convert to integers
    ids = [int(x) for x in ids if x.isdigit()]
    if not ids:
        flash('Nessun prodotto valido selezionato.', 'warning')
        return redirect(url_for('prodotti'))

    with get_db() as db:
        cur = db.cursor()
        placeholders = ', '.join(['%s'] * len(ids))
        
        # 1. Rimuove associazioni attive
        cur.execute(f'DELETE FROM clienti_prodotti WHERE prodotto_id IN ({placeholders})', tuple(ids))
        # 2. Rimuove record prodotti_rimossi
        cur.execute(f'DELETE FROM prodotti_rimossi WHERE prodotto_id IN ({placeholders})', tuple(ids))
        # 3. Soft-delete prodotti
        cur.execute(f'UPDATE prodotti SET eliminato = TRUE WHERE id IN ({placeholders})', tuple(ids))
        
        db.commit()

    flash(f'{len(ids)} prodotti eliminati con successo.', 'success')
    return redirect(url_for('prodotti'))


@app.route('/prodotti/elimina-tutti', methods=['POST'])
@login_required
def elimina_tutti_prodotti():
    with get_db() as db:
        cur = db.cursor()
        # 1. Rimuove tutte le associazioni attive
        cur.execute('DELETE FROM clienti_prodotti')
        # 2. Rimuove tutti i log di rimozione
        cur.execute('DELETE FROM prodotti_rimossi')
        # 3. Soft-delete tutti i prodotti
        cur.execute('UPDATE prodotti SET eliminato = TRUE')
        db.commit()

    flash('Tutti i prodotti del catalogo sono stati eliminati con successo.', 'success')
    return redirect(url_for('prodotti'))


@app.route('/prodotti/clienti/<int:id>')
def clienti_prodotto(id):
    with get_db() as db:
        cur = db.cursor()
        cur.execute('SELECT * FROM prodotti WHERE id=%s', (id,))
        prodotto = cur.fetchone()
        if not prodotto:
            return "Prodotto non trovato", 404

        cur.execute('''
            SELECT c.*
            FROM clienti c
            JOIN clienti_prodotti cp ON c.id=cp.cliente_id
            WHERE cp.prodotto_id=%s AND cp.lavorato
        ''', (id,))
        clienti = cur.fetchall()

    return render_template('/02_prodotti/04_prodotto_clienti.html', prodotto=prodotto, clienti=clienti)


@app.route('/categorie')
def gestisci_categorie():
    with get_db() as db:
        cur = db.cursor()
        cur.execute('SELECT nome, immagine FROM categorie ORDER BY nome')
        categorie = cur.fetchall()
    return render_template('/02_prodotti/05_gestisci_categorie.html', categorie=categorie)


@app.route('/categorie/aggiungi', methods=['POST'])
def aggiungi_categoria():
    nome = request.form.get('nome_categoria', '').strip()
    immagine = request.form.get('link_immagine', '').strip() or None

    if not nome:
        flash("⚠️ Devi inserire un nome per la categoria.", "warning")
        return redirect(url_for('gestisci_categorie'))

    with get_db() as db:
        cur = db.cursor()
        cur.execute('INSERT INTO categorie (nome, immagine) VALUES (%s, %s) ON CONFLICT DO NOTHING', (nome, immagine))
        db.commit()

    flash(f"✅ Categoria '{nome}' aggiunta.", "success")
    return redirect(url_for('gestisci_categorie'))


@app.route('/categorie/modifica', methods=['POST'])
def modifica_categoria():
    vecchio_nome = request.form.get('vecchio_nome')
    nuovo_nome = request.form.get('nome_categoria', '').strip()
    immagine = request.form.get('link_immagine', '').strip() or None

    if not nuovo_nome:
        flash("⚠️ Il nome non può essere vuoto.", "warning")
        return redirect(url_for('gestisci_categorie'))

    with get_db() as db:
        cur = db.cursor()
        cur.execute('UPDATE categorie SET nome=%s, immagine=%s WHERE nome=%s', (nuovo_nome, immagine, vecchio_nome))
        db.commit()

    flash(f"✏️ Categoria '{vecchio_nome}' modificata in '{nuovo_nome}'.", "info")
    return redirect(url_for('gestisci_categorie'))


@app.route('/categorie/elimina/<nome_categoria>', methods=['POST'])
def elimina_categoria(nome_categoria):
    with get_db() as db:
        cur = db.cursor()
        cur.execute('DELETE FROM categorie WHERE nome=%s', (nome_categoria,))
        db.commit()

    flash(f"🗑️ Categoria '{nome_categoria}' eliminata.", "danger")
    return redirect(url_for('gestisci_categorie'))

# ============================
# ROUTE STATISTICHE E ANALYTICS
# ============================
@app.route('/statistiche')
@login_required
def pagina_statistiche():
    import datetime
    from dateutil.relativedelta import relativedelta

    with get_db() as db:
        cur = db.cursor()

        # 1. KPI FATTURATO
        cur.execute("SELECT COALESCE(SUM(totale), 0) AS totale FROM fatturato")
        fatturato_globale = cur.fetchone()['totale'] or 0

        # Andamento fatturato negli ultimi 12 mesi
        cur.execute('''
            SELECT anno, mese, COALESCE(SUM(totale), 0) AS totale
            FROM fatturato
            GROUP BY anno, mese
            ORDER BY anno DESC, mese DESC
            LIMIT 12
        ''')
        fatturato_mensile_rows = cur.fetchall()
        fatturato_mensile = {f"{r['anno']}-{r['mese']:02}": float(r['totale']) for r in reversed(fatturato_mensile_rows)}

        # TOP 5 Clienti per Fatturato
        cur.execute('''
            SELECT id, nome, zona, stato, COALESCE(fatturato_totale, 0) AS fatturato_totale
            FROM clienti
            ORDER BY fatturato_totale DESC
            LIMIT 5
        ''')
        top_clienti = cur.fetchall()

        # Clienti bloccati o inattivi di valore da recuperare
        cur.execute('''
            SELECT id, nome, zona, stato, COALESCE(fatturato_totale, 0) AS fatturato_totale
            FROM clienti
            WHERE stato IN ('bloccato', 'inattivo') AND fatturato_totale > 0
            ORDER BY fatturato_totale DESC
            LIMIT 5
        ''')
        clienti_recupero = cur.fetchall()

        # 2. ANALISI STATO CLIENTI
        cur.execute("SELECT stato, COUNT(*) AS conteggio FROM clienti GROUP BY stato")
        stato_clienti_rows = cur.fetchall()
        stato_clienti = {r['stato'].lower(): r['conteggio'] for r in stato_clienti_rows}
        clienti_totali = sum(stato_clienti.values())

        # 3. ANALISI PRODOTTI
        cur.execute("SELECT COUNT(*) AS totale FROM prodotti")
        prodotti_catalogo = cur.fetchone()['totale'] or 0

        # Prodotti inseriti e rimossi negli ultimi 30 giorni
        now = datetime.datetime.now()
        trenta_giorni_fa = now - datetime.timedelta(days=30)
        
        cur.execute('''
            SELECT COUNT(*) AS conteggio
            FROM clienti_prodotti
            WHERE lavorato = TRUE AND data_operazione >= %s
        ''', (trenta_giorni_fa,))
        prodotti_inseriti_30gg = cur.fetchone()['conteggio'] or 0

        cur.execute('''
            SELECT COUNT(*) AS conteggio
            FROM prodotti_rimossi
            WHERE data_rimozione >= %s
        ''', (trenta_giorni_fa,))
        prodotti_rimossi_30gg = cur.fetchone()['conteggio'] or 0

        # Prodotti lavorati, potenziali e non lavorati totali
        cur.execute('''
            SELECT 
                SUM(CASE WHEN lavorato = TRUE THEN 1 ELSE 0 END) AS lavorati,
                SUM(CASE WHEN potenziale = TRUE THEN 1 ELSE 0 END) AS potenziali,
                SUM(CASE WHEN lavorato = FALSE AND potenziale = FALSE THEN 1 ELSE 0 END) AS non_lavorati
            FROM clienti_prodotti
        ''')
        prodotti_assoc_summary = cur.fetchone()
        lavorati_tot = prodotti_assoc_summary['lavorati'] or 0
        potenziali_tot = prodotti_assoc_summary['potenziali'] or 0
        non_lavorati_tot = prodotti_assoc_summary['non_lavorati'] or 0

        # TOP 5 Prodotti Potenziali (Upselling opportuni)
        cur.execute('''
            SELECT p.id, p.nome AS prodotto, COALESCE(c.nome, '–') AS categoria, COUNT(cp.id) AS interesse
            FROM clienti_prodotti cp
            JOIN prodotti p ON cp.prodotto_id = p.id
            LEFT JOIN categorie c ON p.categoria_id = c.id
            WHERE cp.potenziale = TRUE
            GROUP BY p.id, p.nome, c.nome
            ORDER BY interesse DESC
            LIMIT 5
        ''')
        top_potenziali = cur.fetchall()

        # 4. RACCOMANDAZIONI COMMERCIALI INTELLIGENTI
        raccomandazioni = []
        
        # Raccomandazione 1: VIP Bloccati da recuperare
        cur.execute('''
            SELECT id, nome, fatturato_totale
            FROM clienti
            WHERE stato = 'bloccato' AND fatturato_totale > 0
            ORDER BY fatturato_totale DESC
            LIMIT 2
        ''')
        vip_bloccati = cur.fetchall()
        for c in vip_bloccati:
            raccomandazioni.append({
                "categoria": "danger",
                "titolo": f"Recupero Cliente VIP: {c['nome']}",
                "descrizione": f"Questo cliente ha generato storicamente €{c['fatturato_totale']:.2f} ma è attualmente BLOCCATO. Pianifica una visita o proponi condizioni di pagamento agevolate per sbloccarlo."
            })

        # Raccomandazione 2: Prodotti con alto potenziale di vendita
        if top_potenziali:
            top_p = top_potenziali[0]
            raccomandazioni.append({
                "categoria": "success",
                "titolo": f"Upselling Opportunità: {top_p['prodotto']}",
                "descrizione": f"Questo prodotto è segnato come 'Potenziale' per ben {top_p['interesse']} clienti. Prepara una promo dedicata sul prossimo volantino mensile per convertirli."
            })

        # Raccomandazione 3: Clienti con più prodotti potenziali inseriti
        cur.execute('''
            SELECT c.id, c.nome, COUNT(cp.id) AS num_potenziali
            FROM clienti_prodotti cp
            JOIN clienti c ON cp.cliente_id = c.id
            WHERE cp.potenziale = TRUE
            GROUP BY c.id, c.nome
            ORDER BY num_potenziali DESC
            LIMIT 2
        ''')
        clienti_molti_potenziali = cur.fetchall()
        for c in clienti_molti_potenziali:
            raccomandazioni.append({
                "categoria": "warning",
                "titolo": f"Sviluppo Portafoglio: {c['nome']}",
                "descrizione": f"Ha {c['num_potenziali']} prodotti identificati come 'Potenziali' in scheda. Approfitta del prossimo appuntamento o inviagli una proposta mirata per queste referenze."
            })

        # Default fallback raccomandazioni se vuote
        if not raccomandazioni:
            raccomandazioni.append({
                "categoria": "info",
                "titolo": "Ottimizzazione Copertura",
                "descrizione": "Identifica nuovi prodotti e digitalizza il listino dei clienti per far emergere nuove opportunità di vendita incrociata (Cross-Selling)."
            })

    return render_template(
        '03_statistiche.html',
        fatturato_globale=fatturato_globale,
        fatturato_mensile=fatturato_mensile,
        top_clienti=top_clienti,
        clienti_recupero=clienti_recupero,
        stato_clienti=stato_clienti,
        clienti_totali=clienti_totali,
        prodotti_catalogo=prodotti_catalogo,
        prodotti_inseriti_30gg=prodotti_inseriti_30gg,
        prodotti_rimossi_30gg=prodotti_rimossi_30gg,
        lavorati_tot=lavorati_tot,
        potenziali_tot=potenziali_tot,
        non_lavorati_tot=non_lavorati_tot,
        top_potenziali=top_potenziali,
        raccomandazioni=raccomandazioni
    )

# ============================
# ROUTE FATTURATO
# ============================

@app.route('/fatturato')
@login_required
def fatturato():
    zona_filtro = request.args.get('zona', 'tutte')

    with get_db() as db:
        cur = db.cursor()
        # Recupera tutte le zone clienti distinte
        cur.execute('SELECT DISTINCT zona FROM clienti ORDER BY zona')
        zone = cur.fetchall()

        # Recupero clienti (con eventuale filtro zona)
        params = []
        zona_cond = ''
        if zona_filtro != 'tutte':
            zona_cond = 'WHERE zona = %s'
            params.append(zona_filtro)

        cur.execute(f'''
            SELECT id, nome, zona
            FROM clienti
            {zona_cond}
            ORDER BY nome
        ''', params)
        clienti = cur.fetchall()

        clienti_list = []
        if clienti:
            # Fatturato totale storico per tutti i clienti in un'unica query
            clienti_ids = [c['id'] for c in clienti]
            placeholders = ','.join(['%s'] * len(clienti_ids))
            cur.execute(f'''
                SELECT cliente_id, SUM(totale) AS totale
                FROM fatturato
                WHERE cliente_id IN ({placeholders})
                GROUP BY cliente_id
            ''', clienti_ids)
            totali_rows = cur.fetchall()
            totali_dict = {row['cliente_id']: float(row['totale'] or 0) for row in totali_rows}

            for cliente in clienti:
                clienti_list.append({
                    'id': cliente['id'],
                    'nome': cliente['nome'],
                    'zona': cliente['zona'],
                    'fatturato_totale': totali_dict.get(cliente['id'], 0.0)
                })

        # Grafico ultimi 3 mesi
        oggi = datetime.now()
        mesi_ultimi = [( (oggi.replace(day=1) - relativedelta(months=i)).year,
                         (oggi.replace(day=1) - relativedelta(months=i)).month ) for i in range(2, -1, -1)]

        fatturato_mensile = {}
        for anno, mese in mesi_ultimi:
            params = [anno, mese]
            query = '''
                SELECT SUM(f.totale) AS totale_mese
                FROM fatturato f
                JOIN clienti c ON f.cliente_id = c.id
                WHERE f.anno = %s AND f.mese = %s
            '''
            if zona_filtro != 'tutte':
                query += ' AND c.zona = %s'
                params.append(zona_filtro)
            cur.execute(query, params)
            totale_row = cur.fetchone()
            key = f"{anno}-{str(mese).zfill(2)}"
            fatturato_mensile[key] = float(totale_row['totale_mese'] or 0)

    return render_template(
        '03_fatturato/01_fatturato.html',
        clienti=clienti_list,
        zone=zone,
        zona_filtro=zona_filtro,
        fatturato_mensile=fatturato_mensile
    )


@app.route('/fatturato_totale')
@login_required
def fatturato_totale():
    with get_db() as db:
        cur = db.cursor()
        cur.execute('SELECT id, nome, zona FROM clienti ORDER BY nome')
        clienti = cur.fetchall()
        clienti_list = []

        if clienti:
            clienti_ids = [c['id'] for c in clienti]
            if clienti_ids:
                placeholders = ','.join(['%s'] * len(clienti_ids))
                cur.execute(f'''
                    SELECT cliente_id, SUM(totale) AS totale
                    FROM fatturato
                    WHERE cliente_id IN ({placeholders})
                    GROUP BY cliente_id
                ''', clienti_ids)
                totali_rows = cur.fetchall()
                totali_dict = {row['cliente_id']: float(row['totale'] or 0) for row in totali_rows}

            for cliente in clienti:
                clienti_list.append({
                    'id': cliente['id'],
                    'nome': cliente['nome'],
                    'zona': cliente['zona'],
                    'fatturato_totale': totali_dict.get(cliente['id'], 0.0)
                })

    return render_template('01_clienti/05_fatturato_totale.html', clienti=clienti_list)


@app.route('/clienti/aggiorna_fatturati', methods=['POST'])
@login_required
def aggiorna_fatturati():
    data = request.get_json()
    if not data or 'fatturati' not in data or 'cliente_id' not in data:
        return jsonify(success=False, message="Dati mancanti"), 400

    cliente_id = data['cliente_id']
    fatturati = data['fatturati']

    with get_db() as db:
        cur = db.cursor()
        try:
            for f in fatturati:
                fid = f.get('id')
                importo = float(f.get('importo', 0))
                cur.execute('UPDATE fatturato SET totale=%s WHERE id=%s', (importo, fid))
            aggiorna_fatturato_totale(cliente_id, cur)
            db.commit()
            return jsonify(success=True)
        except Exception as e:
            return jsonify(success=False, message=str(e)), 500


# ============================
# LISTA VOLANTINI
# ============================
@app.route('/beta-volantini')
@login_required
def lista_volantini_beta():
    lista = VolantinoBeta.query.order_by(VolantinoBeta.creato_il.desc()).all()
    count_std = sum(1 for v in lista if not v.tipo or v.tipo == 'volantino')
    count_promo = sum(1 for v in lista if v.tipo and v.tipo.startswith('promo_'))
    return render_template(
        '05_beta_volantino/05_beta_volantino_lista.html',
        lista=lista,
        count_std=count_std,
        count_promo=count_promo
    )

# ============================
# NUOVO VOLANTINO
# ============================
@app.route("/volantini/nuovo", methods=["GET", "POST"])
@login_required
def nuovo_volantino():
    if request.method == "POST":
        titolo = request.form.get("titolo", "").strip()
        sfondo_file = request.files.get("sfondo")

        if not titolo or not sfondo_file:
            flash("⚠️ Titolo e immagine sfondo sono obbligatori.", "danger")
            return redirect(url_for("nuovo_volantino"))

        # 🔹 Salva sfondo
        filename = secure_filename(sfondo_file.filename)
        os.makedirs(UPLOAD_FOLDER_VOLANTINI, exist_ok=True)
        sfondo_file.save(os.path.join(UPLOAD_FOLDER_VOLANTINI, filename))

        # 🔹 Inserisci volantino in DB
        with get_db() as db:
            cur = db.execute(
                "INSERT INTO volantini (titolo, sfondo, data_creazione) VALUES (?, ?, datetime('now'))",
                (titolo, filename)
            )
            volantino_id = cur.lastrowid

            # 🔹 Inizializza griglia 3x3 con slot vuoti
            layout_json = {"objects": []}
            for i in range(9):
                col = i % 3
                row = i // 3
                x = 50 + col * 250
                y = 50 + row * 280
                layout_json["objects"].append({
                    "type": "group",
                    "objects": [
                        {"type": "rect", "left":0, "top":0, "width":200, "height":240, "fill":"#ffffff", "stroke":"#cccccc", "strokeWidth":1},
                        {"type": "text", "text":"", "left":100, "top":190, "fontSize":14, "originX":"center", "textAlign":"center"},
                        {"type": "text", "text":"", "left":100, "top":215, "fontSize":18, "fill":"red", "originX":"center", "textAlign":"center"}
                    ],
                    "left": x, "top": y, "width":200, "height":240, "metadata": {}
                })

            # 🔹 Salva layout nel DB
            db.execute(
                "UPDATE volantini SET layout_json=? WHERE id=?",
                (json.dumps(layout_json, ensure_ascii=False), volantino_id)
            )
            db.commit()

        flash("✅ Volantino creato con successo!", "success")
        return redirect(url_for("lista_volantini"))

    return render_template("04_volantino/02_nuovo_volantino.html")


# ============================
# ELIMINA VOLANTINO
# ============================
@app.route("/volantini/elimina/<int:volantino_id>", methods=["POST"])
@login_required
def elimina_volantino(volantino_id):
    with get_db() as db:
        volantino = db.execute(
            "SELECT sfondo FROM volantini WHERE id = ?", (volantino_id,)
        ).fetchone()

        if not volantino:
            flash("❌ Volantino non trovato.", "danger")
            return redirect(url_for("lista_volantini"))

        # 🔹 Elimina sfondo
        if volantino["sfondo"]:
            sfondo_path = os.path.join(UPLOAD_FOLDER_VOLANTINI, volantino["sfondo"])
            if os.path.exists(sfondo_path):
                os.remove(sfondo_path)

        # 🔹 Elimina immagini prodotti collegati
        prodotti = db.execute(
            "SELECT immagine FROM volantino_prodotti WHERE volantino_id = ?", (volantino_id,)
        ).fetchall()
        for prod in prodotti:
            if prod["immagine"]:
                img_path = os.path.join(UPLOAD_FOLDER_VOLANTINI_PRODOTTI, prod["immagine"])
                if os.path.exists(img_path):
                    os.remove(img_path)

        # 🔹 Elimina volantino e prodotti dal DB
        db.execute("DELETE FROM volantini WHERE id = ?", (volantino_id,))
        db.execute("DELETE FROM volantino_prodotti WHERE volantino_id = ?", (volantino_id,))
        db.commit()

        flash("✅ Volantino eliminato con successo!", "success")

    return redirect(url_for("lista_volantini"))


# ============================
# MODIFICA VOLANTINO
# ============================
@app.route("/volantini/modifica/<int:volantino_id>", methods=["GET", "POST"])
@login_required
def modifica_volantino(volantino_id):
    with get_db() as db:
        volantino = db.execute(
            "SELECT * FROM volantini WHERE id = ?", (volantino_id,)
        ).fetchone()

        if not volantino:
            flash("❌ Volantino non trovato", "danger")
            return redirect(url_for("lista_volantini"))

        if request.method == "POST":
            titolo = request.form.get("titolo", "").strip()
            sfondo_file = request.files.get("sfondo")
            sfondo_nome = volantino["sfondo"]

            if sfondo_file and sfondo_file.filename:
                filename = secure_filename(sfondo_file.filename)
                sfondo_nome = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                os.makedirs(UPLOAD_FOLDER_VOLANTINI, exist_ok=True)
                sfondo_file.save(os.path.join(UPLOAD_FOLDER_VOLANTINI, sfondo_nome))

            db.execute(
                "UPDATE volantini SET titolo=?, sfondo=? WHERE id=?",
                (titolo, sfondo_nome, volantino_id)
            )
            db.commit()
            flash("✅ Volantino aggiornato con successo", "success")
            return redirect(url_for("modifica_volantino", volantino_id=volantino_id))

        # 🔹 Prodotti attivi del volantino
        prodotti_raw = db.execute(
            "SELECT * FROM volantino_prodotti WHERE volantino_id=? AND eliminato=0 ORDER BY id ASC",
            (volantino_id,)
        ).fetchall()
        prodotti = [dict(p) for p in prodotti_raw]

        # 🔹 Prodotti consigliati
        prodotti_precedenti_raw = db.execute(
            """
            SELECT id, nome, prezzo AS prezzo_default,
                   COALESCE(immagine, 'no-image.png') AS immagine
            FROM volantino_prodotti
            WHERE eliminato=0 AND immagine IS NOT NULL
            ORDER BY id DESC LIMIT 15
            """
        ).fetchall()
        prodotti_precedenti = [dict(p) for p in prodotti_precedenti_raw]

    return render_template(
        "04_volantino/03_modifica_volantino.html",
        volantino=dict(volantino),
        prodotti=prodotti,
        prodotti_precedenti=prodotti_precedenti
    )


# ============================
# AGGIUNGI PRODOTTO AL VOLANTINO
# ============================
@app.route('/volantini/<int:volantino_id>/aggiungi_prodotto', methods=['GET', 'POST'])
@login_required
def aggiungi_prodotto_volantino(volantino_id):
    with get_db() as db:
        volantino = db.execute("SELECT * FROM volantini WHERE id = ?", (volantino_id,)).fetchone()
        if not volantino:
            flash("❌ Volantino non trovato.", "danger")
            return redirect(url_for("lista_volantini"))

        if request.method == 'POST':
            nome = request.form.get('nome', '').strip()
            prezzo_raw = request.form.get('prezzo', '').strip()
            immagine_file = request.files.get('immagine')

            if not nome or not prezzo_raw:
                flash("⚠️ Inserisci nome e prezzo.", "warning")
                return redirect(request.url)

            try:
                prezzo = float(prezzo_raw)
                if prezzo < 0:
                    raise ValueError
            except ValueError:
                flash("⚠️ Prezzo non valido.", "warning")
                return redirect(request.url)

            immagine_filename = None
            if immagine_file and immagine_file.filename:
                filename = secure_filename(immagine_file.filename)
                immagine_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                os.makedirs(UPLOAD_FOLDER_VOLANTINI_PRODOTTI, exist_ok=True)
                immagine_file.save(os.path.join(UPLOAD_FOLDER_VOLANTINI_PRODOTTI, immagine_filename))

            db.execute(
                "INSERT INTO volantino_prodotti (volantino_id, nome, prezzo, immagine, eliminato) VALUES (?, ?, ?, ?, 0)",
                (volantino_id, nome, prezzo, immagine_filename)
            )
            db.commit()
            flash("✅ Prodotto aggiunto al volantino con successo!", "success")
            return redirect(url_for("modifica_volantino", volantino_id=volantino_id))

    return render_template("04_volantino/05_aggiungi_prodotto_volantino.html", volantino=dict(volantino))


# ============================
# MODIFICA PRODOTTO DEL VOLANTINO
# ============================
@app.route('/volantini/prodotto/modifica/<int:prodotto_id>', methods=['GET', 'POST'])
@login_required
def modifica_prodotto_volantino(prodotto_id):
    with get_db() as db:
        prodotto = db.execute("SELECT * FROM volantino_prodotti WHERE id = ?", (prodotto_id,)).fetchone()
        if not prodotto:
            flash("❌ Prodotto non trovato.", "danger")
            return redirect(url_for("lista_volantini"))

        if request.method == "POST":
            if "lascia_vuota" in request.form:
                db.execute(
                    "UPDATE volantino_prodotti SET nome='', prezzo=0, immagine=NULL, lascia_vuota=1, eliminato=0 WHERE id=?",
                    (prodotto_id,)
                )
                db.commit()
                flash("✅ Box lasciata vuota.", "success")
                return redirect(url_for("modifica_volantino", volantino_id=prodotto["volantino_id"]))

            nome = request.form.get("nome", "").strip()
            prezzo_raw = request.form.get("prezzo", "").strip()

            if not nome or not prezzo_raw:
                flash("⚠️ Inserisci nome e prezzo, oppure usa 'Lascia vuota'.", "warning")
                return redirect(request.url)

            try:
                prezzo = float(prezzo_raw)
                if prezzo < 0:
                    raise ValueError
            except ValueError:
                flash("⚠️ Prezzo non valido.", "warning")
                return redirect(request.url)

            file = request.files.get("immagine")
            filename = prodotto["immagine"]

            if file and file.filename:
                original_name = secure_filename(file.filename)
                filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{original_name}"
                os.makedirs(UPLOAD_FOLDER_VOLANTINI_PRODOTTI, exist_ok=True)
                file.save(os.path.join(UPLOAD_FOLDER_VOLANTINI_PRODOTTI, filename))

            db.execute(
                "UPDATE volantino_prodotti SET nome=?, prezzo=?, immagine=?, lascia_vuota=0, eliminato=0 WHERE id=?",
                (nome, prezzo, filename, prodotto_id)
            )
            db.commit()
            flash("✅ Prodotto aggiornato con successo!", "success")
            return redirect(url_for("modifica_volantino", volantino_id=prodotto["volantino_id"]))

    return render_template("04_volantino/06_modifica_prodotto_volantino.html", prodotto=dict(prodotto))

# ============================
# AGGIUNGI PRODOTTO CONSIGLIATO
# ============================
@app.route("/volantini/<int:volantino_id>/aggiungi_consigliato", methods=["POST"])
@login_required
def aggiungi_consigliato(volantino_id):
    data = request.get_json(silent=True)
    if not data or "id" not in data or "prezzo" not in data:
        return jsonify({"status": "error", "msg": "Dati mancanti"}), 400

    prodotto_id = data.get("id")
    prezzo = data.get("prezzo")

    try:
        prezzo = float(prezzo)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "msg": "Prezzo non valido"}), 400

    with get_db() as db:
        prodotto = db.execute(
            "SELECT nome, immagine FROM volantino_prodotti WHERE id=?",
            (prodotto_id,)
        ).fetchone()
        if not prodotto:
            return jsonify({"status": "error", "msg": "Prodotto non trovato"}), 404

        # Riattiva prodotto già eliminato
        esistente = db.execute(
            "SELECT id FROM volantino_prodotti WHERE volantino_id=? AND nome=? AND eliminato=1",
            (volantino_id, prodotto["nome"])
        ).fetchone()

        if esistente:
            db.execute(
                "UPDATE volantino_prodotti SET prezzo=?, eliminato=0 WHERE id=?",
                (prezzo, esistente["id"])
            )
            db.commit()
            return jsonify({"status": "ok", "id": esistente["id"], "riattivato": True})

        # Inserimento nuovo prodotto
        cursor = db.execute(
            "INSERT INTO volantino_prodotti (volantino_id, nome, prezzo, immagine, eliminato) VALUES (?, ?, ?, ?, 0)",
            (volantino_id, prodotto["nome"], prezzo, prodotto["immagine"])
        )
        db.commit()
        return jsonify({"status": "ok", "id": cursor.lastrowid, "riattivato": False})


# ============================
# ELIMINA PRODOTTO VOLANTINO
# ============================
@app.route("/volantini/prodotto/elimina/<int:prodotto_id>", methods=["POST"])
@login_required
def elimina_prodotto_volantino(prodotto_id):
    with get_db() as db:
        row = db.execute(
            "SELECT volantino_id FROM volantino_prodotti WHERE id=?", (prodotto_id,)
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "msg": "Prodotto non trovato"}), 404

        db.execute(
            "UPDATE volantino_prodotti SET eliminato=1 WHERE id=?", (prodotto_id,)
        )
        db.commit()
        return jsonify({"status": "ok"})


# ============================
# VISUALIZZA VOLANTINO
# ============================
@app.route("/volantino/<int:volantino_id>")
def visualizza_volantino(volantino_id):
    with get_db() as db:
        volantino = db.execute("SELECT * FROM volantini WHERE id=?", (volantino_id,)).fetchone()
        if not volantino:
            flash("❌ Volantino non trovato.", "danger")
            return redirect(url_for("lista_volantini"))

        prodotti = db.execute(
            "SELECT * FROM volantino_prodotti WHERE volantino_id=? ORDER BY id ASC", (volantino_id,)
        ).fetchall()

    volantino_dict = dict(volantino)
    try:
        layout = json.loads(volantino_dict.get("layout_json") or "{}")
        if isinstance(layout, list):
            layout = {"objects": layout}
        elif not isinstance(layout, dict):
            layout = {"objects": []}
    except Exception:
        layout = {"objects": []}
    volantino_dict["layout_json"] = json.dumps(layout, ensure_ascii=False)

    return render_template(
        "04_volantino/04_visualizza_volantino.html",
        volantino=volantino_dict,
        prodotti=[dict(p) for p in prodotti]
    )


# ============================
# EDITOR VOLANTINO
# ============================
@app.route('/volantini/<int:volantino_id>/editor')
@login_required
def editor_volantino(volantino_id):
    with get_db() as db:
        volantino = db.execute("SELECT * FROM volantini WHERE id=?", (volantino_id,)).fetchone()
        if not volantino:
            flash("❌ Volantino non trovato.", "danger")
            return redirect(url_for("lista_volantini"))

        prodotti_raw = db.execute(
            "SELECT * FROM volantino_prodotti WHERE volantino_id=? AND eliminato=0 ORDER BY id ASC",
            (volantino_id,)
        ).fetchall()

    volantino_dict = dict(volantino)
    cols, rows = 3, 3
    max_slots = cols * rows

    if not volantino_dict.get("layout_json"):
        grid = []
        for i in range(max_slots):
            col = i % cols
            row = i // cols
            x = 50 + col * 250
            y = 50 + row * 280
            prodotto = dict(prodotti_raw[i]) if i < len(prodotti_raw) else {}
            grid.append({
                "type": "group",
                "objects": [
                    {"type": "rect", "left":0, "top":0, "width":200, "height":240, "fill":"#ffffff", "stroke":"#cccccc", "strokeWidth":1},
                    {"type": "text", "text": prodotto.get("nome",""), "left":100, "top":190, "fontSize":14, "originX":"center", "textAlign":"center"},
                    {"type": "text", "text": f"€ {prodotto.get('prezzo','')}" if prodotto.get('prezzo') else "", "left":100, "top":215, "fontSize":18, "fill":"red", "originX":"center", "textAlign":"center"}
                ],
                "left": x, "top": y, "width":200, "height":240,
                "metadata": {
                    "id": prodotto.get("id"), "nome": prodotto.get("nome"), "prezzo": prodotto.get("prezzo"),
                    "url": url_for("static", filename=f"uploads/volantino_prodotti/{prodotto.get('immagine')}") if prodotto.get("immagine") else "",
                    "lascia_vuota": prodotto.get("lascia_vuota", 0)
                }
            })
        volantino_dict["layout_json"] = json.dumps({"objects": grid}, ensure_ascii=False)
    else:
        try:
            layout = json.loads(volantino_dict["layout_json"])
            if isinstance(layout, list):
                layout = {"objects": layout}
            volantino_dict["layout_json"] = json.dumps(layout, ensure_ascii=False)
        except Exception:
            volantino_dict["layout_json"] = json.dumps({"objects": []}, ensure_ascii=False)

    return render_template(
        "04_volantino/07_editor_volantino.html",
        volantino=volantino_dict,
        volantino_prodotti=[dict(p) for p in prodotti_raw],
        num_prodotti=max_slots
    )


# ============================
# SALVA LAYOUT VOLANTINO
# ============================
@app.route('/volantini/<int:volantino_id>/salva_layout', methods=['POST'])
@login_required
def salva_layout_volantino(volantino_id):
    data = request.get_json(silent=True)
    if not data or "layout" not in data:
        return jsonify({"success": False, "message": "❌ Nessun layout ricevuto"}), 400

    layout = data.get("layout")
    try:
        if isinstance(layout, list):
            layout = {"objects": layout}
        elif not isinstance(layout, dict):
            return jsonify({"success": False, "message": "❌ Formato layout non valido"}), 400
        layout.setdefault("objects", [])
        layout_json = json.dumps(layout, ensure_ascii=False)
    except Exception as e:
        return jsonify({"success": False, "message": f"❌ Errore JSON: {e}"}), 500

    with get_db() as db:
        cursor = db.execute("UPDATE volantini SET layout_json=? WHERE id=?", (layout_json, volantino_id))
        for obj in layout["objects"]:
            metadata = obj.get("metadata", {})
            prod_id = metadata.get("id")
            if prod_id:
                db.execute("UPDATE volantino_prodotti SET eliminato=0 WHERE id=? AND eliminato=1", (prod_id,))
        db.commit()
        updated = cursor.rowcount

    if updated == 0:
        return jsonify({"success": False, "message": "❌ Volantino non trovato"}), 404

    return jsonify({"success": True, "message": "✅ Layout salvato correttamente"})

# ============================
# LISTA VOLANTINI + PROMO LAMPO
# ============================
@app.route("/volantini")
@login_required
def lista_volantini():
    return redirect(url_for('lista_volantini_beta'))


# ============================
# NUOVA PROMO LAMPO
# ============================
@app.route("/promo-lampo/nuovo", methods=["GET", "POST"])
@login_required
def nuova_promo_lampo():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        prezzo_raw = request.form.get("prezzo", "").strip()
        immagine_file = request.files.get("immagine")
        sfondo_file = request.files.get("sfondo")

        if not nome or not prezzo_raw or not immagine_file or not sfondo_file:
            flash("❌ Tutti i campi sono obbligatori", "danger")
            return redirect(url_for("nuova_promo_lampo"))

        try:
            prezzo = float(prezzo_raw)
        except ValueError:
            flash("❌ Prezzo non valido", "danger")
            return redirect(url_for("nuova_promo_lampo"))

        os.makedirs(UPLOAD_FOLDER_PROMO, exist_ok=True)

        immagine_nome = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(immagine_file.filename)}"
        immagine_file.save(os.path.join(UPLOAD_FOLDER_PROMO, immagine_nome))

        sfondo_nome = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(sfondo_file.filename)}"
        sfondo_file.save(os.path.join(UPLOAD_FOLDER_PROMO, sfondo_nome))

        with get_db() as db:
            db.execute(
                "INSERT INTO promo_lampo (nome, prezzo, immagine, sfondo, data_creazione) VALUES (?, ?, ?, ?, ?)",
                (nome, prezzo, immagine_nome, sfondo_nome, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )

        flash("✅ Promo Lampo creata con successo!", "success")
        return redirect(url_for("lista_volantini"))

    return render_template("04_volantino/08_nuova_promo_lampo.html")


# ============================
# MODIFICA PROMO LAMPO
# ============================
@app.route("/promo-lampo/modifica/<int:promo_id>", methods=["GET", "POST"])
@login_required
def modifica_promo_lampo(promo_id):
    with get_db() as db:
        promo = db.execute("SELECT * FROM promo_lampo WHERE id=?", (promo_id,)).fetchone()
        if not promo:
            flash("❌ Promo Lampo non trovata", "danger")
            return redirect(url_for("lista_volantini"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        prezzo_raw = request.form.get("prezzo", "").strip()
        immagine_file = request.files.get("immagine")

        try:
            prezzo = float(prezzo_raw)
        except ValueError:
            flash("❌ Prezzo non valido", "danger")
            return redirect(url_for("modifica_promo_lampo", promo_id=promo_id))

        immagine_nome = promo["immagine"]
        if immagine_file and immagine_file.filename.strip():
            old_path = os.path.join(UPLOAD_FOLDER_PROMO, immagine_nome)
            if os.path.exists(old_path):
                os.remove(old_path)

            immagine_nome = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(immagine_file.filename)}"
            immagine_file.save(os.path.join(UPLOAD_FOLDER_PROMO, immagine_nome))

        with get_db() as db:
            db.execute(
                "UPDATE promo_lampo SET nome=?, prezzo=?, immagine=? WHERE id=?",
                (nome, prezzo, immagine_nome, promo_id)
            )

        flash("✅ Promo Lampo aggiornata con successo!", "success")
        return redirect(url_for("lista_volantini"))

    return render_template("04_volantino/09_modifica_promo_lampo.html", promo=promo)


# ============================
# ELIMINA PROMO LAMPO
# ============================
@app.route("/promo-lampo/elimina/<int:promo_id>", methods=["POST"])
@login_required
def elimina_promo_lampo(promo_id):
    with get_db() as db:
        promo = db.execute("SELECT immagine, sfondo FROM promo_lampo WHERE id=?", (promo_id,)).fetchone()
        if not promo:
            flash("❌ Promo Lampo non trovata", "danger")
            return redirect(url_for("lista_volantini"))

        # elimina immagini
        for file_attr in ["immagine", "sfondo"]:
            if promo[file_attr]:
                path = os.path.join(UPLOAD_FOLDER_PROMO, promo[file_attr])
                if os.path.exists(path):
                    os.remove(path)

        db.execute("DELETE FROM promo_lampo WHERE id=?", (promo_id,))

    flash("✅ Promo Lampo eliminata con successo!", "success")
    return redirect(url_for("lista_volantini"))


# ============================
# EDITOR PROMO LAMPO
# ============================
@app.route("/promo-lampo/<int:promo_id>/editor", methods=["GET", "POST"])
@login_required
def editor_promo_lampo(promo_id):
    with get_db() as db:
        promo = db.execute("SELECT * FROM promo_lampo WHERE id=?", (promo_id,)).fetchone()
        if not promo:
            flash("❌ Promo Lampo non trovata", "danger")
            return redirect(url_for("lista_volantini"))

    promo_prodotti = [{
        "url": promo["immagine"],
        "nome": promo["nome"],
        "prezzo": promo["prezzo"]
    }]

    return render_template(
        "04_volantino/10_editor_promo_lampo.html",
        promo=promo,
        promo_prodotti=promo_prodotti
    )


# ============================
# SALVA LAYOUT PROMO LAMPO
# ============================
@app.route("/promo-lampo/<int:promo_id>/salva_layout", methods=["POST"])
@login_required
def salva_layout_promo_lampo(promo_id):
    data = request.get_json(silent=True)
    layout = data.get("layout") if data else None

    if not layout:
        return jsonify({"status": "error", "message": "Layout mancante"}), 400

    try:
        layout_json = json.dumps(layout, ensure_ascii=False)
        with get_db() as db:
            db.execute("UPDATE promo_lampo SET layout=? WHERE id=?", (layout_json, promo_id))
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ============================
# ROUTE DI TEST TEMPLATE
# ============================
@app.route('/test-template')
def test_template():
    return render_template('00_login.html')


@app.route('/debug-template')
def debug_template():
    return f"""
    Loader: {app.jinja_loader}<br>
    Template path: {app.jinja_loader.searchpath}
    """

# ------------------------------------------------------------
# WHATSAPP & PDF HELPERS
# ------------------------------------------------------------

def _normalize_phone(s: str | None) -> str | None:
    if not s:
        return None
    s = s.replace("whatsapp:", "").replace("+", "")
    s = "".join(ch for ch in s if ch.isdigit())
    if s.startswith("00"):
        s = s[2:]
    return s or None

def send_text(to: str, text: str):
    to_norm = _normalize_phone(to)
    if not to_norm:
        return None
    token = os.getenv("META_WA_TOKEN")
    phone_id = os.getenv("META_WA_PHONE_NUMBER_ID")
    if not token or not phone_id:
        return None
    url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_norm,
        "type": "text",
        "text": {"body": text}
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        return r.json()
    except:
        return None

def parse_scadenze_from_pdf(pdf_path: str) -> list[dict]:
    offers = []
    date_re = re.compile(r'(\d{2}[-/. ]\d{2}[-/. ]\d{2,4})')
    code_re = re.compile(r'\b\d{4,10}\b')
    price_re = re.compile(r'((?:\d{1,3}[.,])*\d{1,3}[.,]\d{1,3})')
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            for raw in text.splitlines():
                row_text = " ".join(raw.strip().split())
                if not row_text: continue
                date_matches = date_re.search(row_text)
                if date_matches:
                    scadenza = date_matches.group(1).replace(".", "/")
                    pre_date = row_text[:date_matches.start()].strip()
                    cms = list(code_re.finditer(pre_date))
                    if cms:
                        codice = cms[-1].group(0)
                        nome = pre_date[cms[-1].end():].strip()
                        post_date = row_text[date_matches.end():].strip()
                        p_matches = price_re.findall(post_date)
                        prezzo = p_matches[-1] if p_matches else ""
                        offers.append({"code": codice, "name": nome, "scadenza": scadenza, "price": prezzo, "page": page_idx})
    return offers

def parse_offers_from_pdf(pdf_path: str) -> list[dict]:
    offers = []
    code_re = re.compile(r"^\s*(\d{4,10})")
    price_re = re.compile(r"(\d+[\.,]\d{2})\s*(?:€|euro|Euro)?\s*$", re.IGNORECASE)
    um_re = re.compile(r"\b(KG|PZ)\b", re.IGNORECASE)
    
    with pdfplumber.open(pdf_path) as pdf:
        current_code = None
        current_text = ""
        current_page = 0
        
        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            for raw_line in text.splitlines():
                line = " ".join(raw_line.strip().split())
                if not line:
                    continue
                
                m_code = code_re.match(line)
                if m_code:
                    if current_code:
                        parsed = parse_single_offer(current_code, current_text, current_page)
                        if parsed:
                            offers.append(parsed)
                    
                    current_code = m_code.group(1)
                    current_text = line[m_code.end():].strip()
                    current_page = page_idx
                else:
                    if current_code:
                        current_text += " " + line
                
                if current_code:
                    m_price = price_re.search(current_text)
                    if m_price:
                        price = m_price.group(1)
                        before_price = current_text[:m_price.start()].strip()
                        
                        m_um = um_re.search(before_price)
                        if m_um:
                            um = m_um.group(1).upper()
                            name = (before_price[:m_um.start()] + " " + before_price[m_um.end():]).strip()
                        else:
                            um = "PZ"
                            name = before_price
                        
                        offers.append({
                            "code": current_code,
                            "name": " ".join(name.split()),
                            "price": price.replace(",", "."),
                            "um": um,
                            "page": current_page
                        })
                        current_code = None
                        current_text = ""
                        
        if current_code:
            parsed = parse_single_offer(current_code, current_text, current_page)
            if parsed:
                offers.append(parsed)
                
    # Rimuovi duplicati
    seen = set()
    uniq = []
    for o in offers:
        if o["code"] in seen:
            continue
        seen.add(o["code"])
        uniq.append(o)
    return uniq

def parse_promo_scadenze_from_pdf(pdf_path: str) -> list[dict]:
    products = []
    import pdfplumber
    import re
    
    code_pattern = re.compile(r"^\s*(\d{4,12})\s*$")
    current_category = "SCADENZE"
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                # Prova prima con la strategia standard
                tables = page.extract_tables()
                # Se non trova tabelle, prova con una strategia basata sull'allineamento del testo
                if not tables or len(tables) == 0:
                    tables = page.extract_tables({
                        "vertical_strategy": "text",
                        "horizontal_strategy": "text",
                        "snap_tolerance": 3,
                    })
                
                for table in tables:
                    if not table:
                        continue
                    for row in table:
                        if not row or len(row) < 8:
                            continue
                        
                        raw_code = row[1]
                        code_str = str(raw_code or "").strip()
                        
                        # Rilevamento categoria: se il codice non è numerico e c'è del testo maiuscolo
                        if not code_str or not code_pattern.match(code_str):
                            cand_cat = str(row[2] or row[1] or "").strip()
                            if cand_cat.isupper() and len(cand_cat) > 2 and len(cand_cat) < 50:
                                # Controlla che non sia intestazione generica
                                if not any(w in cand_cat for w in ["CODICE", "DESCRIZIONE", "UM", "PREZZO", "PAGINA", "SCADENZA", "QUANTIT", "QTA", "DISP"]):
                                    # E che il resto delle celle sia per lo più vuoto per essere una riga header di categoria
                                    has_data = False
                                    for cell in row[3:]:
                                        if cell and str(cell).strip():
                                            has_data = True
                                            break
                                    if not has_data:
                                        current_category = cand_cat
                                        continue
                        
                        if not code_str or not code_pattern.match(code_str):
                            continue
                            
                        nome = str(row[2] or "").strip()
                        um = str(row[3] or "PZ").strip().upper()
                        scadenza = str(row[4] or "").strip()
                        quantita = str(row[6] or "").strip()
                        prezzo_raw = str(row[7] or "").strip()
                        
                        price_cleaned = prezzo_raw.replace("€", "").replace(" ", "").replace(",", ".").strip()
                        try:
                            prezzo = float(price_cleaned) if price_cleaned else 0.0
                        except ValueError:
                            prezzo = 0.0
                            
                        products.append({
                            "code": code_str,
                            "name": nome,
                            "um": um,
                            "scadenza": scadenza,
                            "quantita": quantita,
                            "price": prezzo,
                            "price_str": prezzo_raw,
                            "categoria": current_category,
                            "page": page_idx
                        })
    except Exception as e:
        print(f"Errore nel parsing del PDF promo scadenze: {e}")
        import traceback
        traceback.print_exc()
        
    # Rimuovi duplicati
    seen = set()
    uniq = []
    for p in products:
        if p["code"] in seen:
            continue
        seen.add(p["code"])
        uniq.append(p)
    return uniq

def parse_single_offer(code, text, page_idx):
    price_re = re.compile(r"(\d+[\.,]\d{2})")
    um_re = re.compile(r"\b(KG|PZ)\b", re.IGNORECASE)
    
    p_matches = list(price_re.finditer(text))
    if p_matches:
        last_price_match = p_matches[-1]
        price = last_price_match.group(1)
        before_price = text[:last_price_match.start()].strip()
        
        m_um = um_re.search(before_price)
        if m_um:
            um = m_um.group(1).upper()
            name = (before_price[:m_um.start()] + " " + before_price[m_um.end():]).strip()
        else:
            um = "PZ"
            name = before_price
            
        return {
            "code": code,
            "name": " ".join(name.split()),
            "price": price.replace(",", "."),
            "um": um,
            "page": page_idx
        }
    else:
        m_um = um_re.search(text)
        if m_um:
            um = m_um.group(1).upper()
            name = (text[:m_um.start()] + " " + text[m_um.end():]).strip()
        else:
            um = "PZ"
            name = text
        return {
            "code": code,
            "name": " ".join(name.split()),
            "price": "",
            "um": um,
            "page": page_idx
        }


PHONE_COL_CACHE = {"value": None}
def _detect_phone_column(cur) -> str | None:
    if PHONE_COL_CACHE["value"]: return PHONE_COL_CACHE["value"]
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='clienti'")
    cols = [r['column_name'] for r in cur.fetchall()]
    for cand in ["telefono", "cellulare", "whatsapp"]:
        if cand in [c.lower() for c in cols]:
            PHONE_COL_CACHE["value"] = cand
            return cand
    return None

def _segment_where(pref: str) -> str:
    pref = (pref or "").lower()
    if pref == "scadenza": return "wp.opt_out = FALSE AND wp.ricevi_scadenza = TRUE"
    if pref == "pesce": return "wp.opt_out = FALSE AND wp.ricevi_pesce = TRUE"
    if pref == "carne": return "wp.opt_out = FALSE AND wp.ricevi_carne = TRUE"
    if pref == "stop": return "wp.opt_out = TRUE"
    if pref == "nessuna": return "wp.cliente_id IS NULL"
    return "c.id IS NOT NULL"

def _normalize_phone_admin(s: str | None) -> str:
    if not s: return ""
    return "".join(ch for ch in s if ch.isdigit())

def _admin_list() -> set[str]:
    raw = os.getenv("ADMIN_WHATSAPP", "")
    return { _normalize_phone_admin(a) for a in raw.split(",") if a }

def is_admin(from_number: str | None) -> bool:
    return _normalize_phone_admin(from_number) in _admin_list()

def find_cliente_id_by_phone(cur, phone_norm: str) -> int | None:
    cur.execute("SELECT id FROM clienti WHERE telefono=%s LIMIT 1", (phone_norm,))
    row = cur.fetchone()
    return row[0] if row else None

def upsert_preferenza(cur, cliente_id: int, scelta: str):
    col_map = {"1": "ricevi_scadenza", "2": "ricevi_pesce", "3": "ricevi_carne"}
    if scelta == "0":
        cur.execute("INSERT INTO whatsapp_preferenze (cliente_id, opt_out) VALUES (%s, TRUE) ON CONFLICT (cliente_id) DO UPDATE SET opt_out=TRUE", (cliente_id,))
    elif scelta in col_map:
        col = col_map[scelta]
        cur.execute(f"INSERT INTO whatsapp_preferenze (cliente_id, {col}, opt_out) VALUES (%s, TRUE, FALSE) ON CONFLICT (cliente_id) DO UPDATE SET {col}=TRUE, opt_out=FALSE", (cliente_id,))

def mark_whatsapp_linked_by_phone(cur, phone_norm: str):
    cur.execute("UPDATE clienti SET whatsapp_linked = TRUE WHERE telefono = %s", (phone_norm,))

def product_id_by_code_pg(cur, code: str) -> int | None:
    cur.execute("SELECT id FROM prodotti WHERE codice = %s LIMIT 1", (code,))
    row = cur.fetchone()
    return row[0] if row else None

def customer_phones_for_product_pg(cur, prodotto_id: int) -> list[tuple[int, str]]:
    cur.execute("SELECT c.id, c.telefono FROM clienti c JOIN clienti_prodotti cp ON cp.cliente_id = c.id WHERE cp.prodotto_id = %s", (prodotto_id,))
    return [(r[0], r[1]) for r in cur.fetchall() if r[1]]

def send_offers_to_customers_pg(cur, offers: list[dict]) -> tuple[int, int]:
    sent = 0
    for o in offers:
        pid = product_id_by_code_pg(cur, o["code"])
        if pid:
            for cid, phone in customer_phones_for_product_pg(cur, pid):
                send_text(phone, f"Offerta: {o['name']} a {o['price']}")
                sent += 1
    return sent, len(offers)

# ------------------------------------------------------------
# BOT & WHATSAPP ROUTES
# ------------------------------------------------------------

@app.route("/bot", methods=["GET"])
@login_required
def bot_dashboard():
    pref = request.args.get("pref", "scadenza").strip().lower()
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT 
                SUM(CASE WHEN wp.ricevi_scadenza = TRUE AND wp.opt_out = FALSE THEN 1 ELSE 0 END) as n_scadenza,
                SUM(CASE WHEN wp.ricevi_carne = TRUE AND wp.opt_out = FALSE THEN 1 ELSE 0 END) as n_carne,
                SUM(CASE WHEN wp.cliente_id IS NULL THEN 1 ELSE 0 END) as n_nessuna
            FROM clienti c
            LEFT JOIN whatsapp_preferenze wp ON c.id = wp.cliente_id
        """)
        counts = cur.fetchone() or {}
        where_clause = _segment_where(pref)
        phone_col = _detect_phone_column(cur) or "telefono"
        q = f"""
            SELECT c.id, c.nome, c.zona, c.{phone_col} as telefono,
                   wp.ricevi_scadenza, wp.ricevi_pesce, wp.ricevi_carne, wp.opt_out, wp.updated_at
            FROM clienti c
            LEFT JOIN whatsapp_preferenze wp ON c.id = wp.cliente_id
            WHERE {where_clause}
            ORDER BY c.nome
        """
        cur.execute(q)
        clienti = cur.fetchall()
    return render_template("06_bot/06_bot_dashboard.html", pref=pref, counts=counts, clienti=clienti)

@app.route("/bot/invia", methods=["POST"])
@login_required
def bot_invia():
    pref = request.form.get("pref", "scadenza").strip().lower()
    testo = request.form.get("testo", "").strip()
    if not testo:
        flash("Inserisci un testo.", "warning")
        return redirect(url_for('bot_dashboard', pref=pref))
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        where_clause = _segment_where(pref)
        phone_col = _detect_phone_column(cur) or "telefono"
        cur.execute(f"SELECT c.{phone_col} FROM clienti c LEFT JOIN whatsapp_preferenze wp ON c.id = wp.cliente_id WHERE {where_clause}")
        for r in cur.fetchall():
            phone = _normalize_phone(r.get(phone_col))
            if phone: send_text(phone, testo)
        conn.commit()
        flash(f"Inviato!", "success")
    return redirect(url_for('bot_dashboard', pref=pref))

@app.route("/meta/webhook", methods=["GET", "POST"])
def meta_webhook():
    if request.method == "GET":
        verify_token = os.getenv("META_VERIFY_TOKEN", "")
        if request.args.get("hub.verify_token") == verify_token:
            return request.args.get("hub.challenge"), 200
        return "Invalid verify token", 403
        
    data = request.json or {}
    
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if "messages" not in value:
                continue
                
            for msg in value["messages"]:
                from_raw = msg.get("from", "")
                from_number = _normalize_phone(from_raw)
                
                if not from_number:
                    continue
                msg_type = msg.get("type", "")
                body = ""
                media_id = None
                media_mime = None
                
                if msg_type == "text":
                    body = msg.get("text", {}).get("body", "").strip()
                elif msg_type == "document":
                    doc = msg.get("document", {})
                    media_id = doc.get("id")
                    media_mime = doc.get("mime_type", "")
                
                low = body.lower()
                def safe_send(to, txt):
                    try:
                        send_text(to, txt)
                    except Exception as e:
                        print("META SEND ERROR:", repr(e))
                        
                # SE È ADMIN
                if is_admin(from_number):
                    # 1. Controllo File PDF (da Meta WA Media API)
                    if media_id and "pdf" in (media_mime or ""):
                        try:
                            safe_send(from_number, "⏳ PDF ricevuto. Sto scaricando e analizzando le offerte...")
                            token = os.getenv("META_WA_TOKEN")
                            # Step A: Get Media URL
                            media_req = requests.get(f"https://graph.facebook.com/v17.0/{media_id}", headers={"Authorization": f"Bearer {token}"})
                            if not media_req.ok:
                                safe_send(from_number, "🚨 Errore URL Media Meta Whatsapp.")
                                return "OK", 200
                                
                            actual_url = media_req.json().get("url")
                            # Step B: Download File (must pass Bearer header again)
                            pdf_data = requests.get(actual_url, headers={"Authorization": f"Bearer {token}"})
                            
                            pdf_path = f"/tmp/meta_{int(time.time())}.pdf"
                            with open(pdf_path, 'wb') as f:
                                f.write(pdf_data.content)
                            
                            offers = parse_offers_from_pdf(pdf_path)
                            if not offers:
                                safe_send(from_number, "⚠️ Nessuna offerta rilevata dal PDF. Controlla il formato.")
                                return "OK", 200
                            
                            with get_db() as db:
                                cur = db.cursor(cursor_factory=RealDictCursor)
                                sent, total_mapped = send_offers_to_customers_pg(cur, offers)
                                db.commit()
                                 
                            safe_send(from_number, f"✅ PDF elaborato! Trovate {len(offers)} offerte.\nMessaggi inviati a *{sent}* clienti (su {total_mapped} con prodotti corrispondenti).")
                        except Exception as e:
                            safe_send(from_number, f"🚨 Errore elaborazione PDF:\n{str(e)}")
                        return "OK", 200
                        
                    # 2. Controllo testuale (STATS, SEND)
                    if low.startswith("stats"):
                        try:
                            with get_db() as db:
                                cur = db.cursor(cursor_factory=RealDictCursor)
                                cur.execute("SELECT COUNT(*) as tot FROM clienti")
                                tot_clients = cur.fetchone()["tot"]
                                cur.execute("SELECT COUNT(*) as tot FROM whatsapp_preferenze WHERE opt_out = FALSE")
                                linked = cur.fetchone()["tot"]
                            safe_send(from_number, f"📊 *STATISTICHE BOT*\nClienti Totali: {tot_clients}\nIscritti WhatsApp: {linked}")
                        except Exception as e:
                            safe_send(from_number, f"Errore stats: {str(e)}")
                        return "OK", 200
                        
                    if low.startswith("send "):
                        parts = body.split(" ", 2)
                        if len(parts) >= 3:
                            target_pref = parts[1].lower()
                            msg_body = parts[2]
                            try:
                                with get_db() as db:
                                    cur = db.cursor(cursor_factory=RealDictCursor)
                                    where_clause = _segment_where(target_pref)
                                    phone_col = _detect_phone_column(cur) or "telefono"
                                    cur.execute(f"SELECT c.{phone_col} FROM clienti c LEFT JOIN whatsapp_preferenze wp ON c.id = wp.cliente_id WHERE {where_clause}")
                                    rows = cur.fetchall()
                                    cnt = 0
                                    for r in rows:
                                        pn = _normalize_phone(r[phone_col])
                                        if pn:
                                            send_text(pn, msg_body)
                                            cnt += 1
                                    safe_send(from_number, f"✅ Messaggio inviato a {cnt} clienti nel segmento *{target_pref.upper()}*.")
                            except Exception as e:
                                safe_send(from_number, f"Errore broadcast: {str(e)}")
                        return "OK", 200
                        
                # MENU (Per Clienti Normali o controlli standard)
                if low in ("menu", "start", "offerte", "preferenze"):
                    safe_send(from_number,
                        "📌 *Preferenze offerte*\n"
                        "Rispondi con:\n"
                        "1 = Scadenze\n"
                        "2 = Pesce\n"
                        "3 = Carne\n"
                        "0 = STOP (non ricevere)\n"
                    )
                    return "OK", 200
                    
                scelta_map = {"1":"PREF_SCADENZA","2":"PREF_PESCE","3":"PREF_CARNE","0":"PREF_STOP"}
                if low in scelta_map:
                    scelta_id = scelta_map[low]
                    try:
                        with get_db() as conn:
                            cur = conn.cursor(cursor_factory=RealDictCursor)
                            cid = find_cliente_id_by_phone(cur, from_number)
                            if not cid:
                                safe_send(from_number, "⚠️ Non ti trovo in anagrafica. Usa il numero salvato nel gestionale.")
                                return "OK", 200
                            upsert_preferenza(cur, cid, scelta_id)
                            mark_whatsapp_linked_by_phone(cur, from_number)
                            conn.commit()
                        if scelta_id == "PREF_STOP":
                            safe_send(from_number, "✅ Ok, non riceverai più offerte. Se cambi idea scrivi *MENU*.")
                        else:
                            safe_send(from_number, "✅ Preferenza salvata! Se vuoi cambiare, scrivi *MENU*.")
                    except Exception as e:
                        print("META PREF ERROR:", repr(e))
                        safe_send(from_number, "⚠️ Errore nel salvataggio preferenze. Riprova tra poco.")
                    return "OK", 200
                    
                safe_send(from_number, "Scrivi *MENU* per scegliere preferenze.")
                
    return "OK", 200

@app.route("/bot/invia-pdf", methods=["POST"])
@login_required
def bot_invia_pdf():
    if "pdf_file" not in request.files:
        flash("Seleziona un file PDF.", "warning")
        return redirect(url_for('bot_dashboard'))
    file = request.files["pdf_file"]
    if file.filename == "":
        flash("Nessun file selezionato.", "warning")
        return redirect(url_for('bot_dashboard'))
    if file and file.filename.endswith(".pdf"):
        pdf_path = f"/tmp/web_{int(time.time())}.pdf"
        file.save(pdf_path)
        offers = parse_offers_from_pdf(pdf_path)
        if not offers:
            flash("Nessuna offerta rilevata dal PDF.", "danger")
            return redirect(url_for('bot_dashboard'))
        with get_db() as db_conn:
            cur = db_conn.cursor(cursor_factory=RealDictCursor)
            sent, total_mapped = send_offers_to_customers_pg(cur, offers)
            db_conn.commit()
        flash(f"PDF elaborato!", "success")
    return redirect(url_for('bot_dashboard'))

@app.route("/admin/whatsapp/broadcast-preferenze")
@login_required
def broadcast_preferenze():
    try:
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT telefono FROM clienti WHERE whatsapp_linked = TRUE")
            for r in cur.fetchall():
                phone = _normalize_phone(r.get("telefono"))
                if phone: send_text(phone, "Scegli cosa vuoi ricevere: Scadenze, Pesce, Carne. Scrivi MENU.")
        flash("Inviato!", "success")
    except Exception as e:
        flash(f"Errore: {e}", "danger")
    return redirect(url_for("clienti"))

@app.route('/visite')
@login_required
def visite_clienti():
    with get_db() as db_conn:
        cur = db_conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, nome, zona FROM clienti ORDER BY nome")
        tutti_clienti = cur.fetchall()
        cur.execute("SELECT id, nome, zona FROM clienti WHERE giorno_visita_standard IS NOT NULL LIMIT 10")
        clienti_frequenti = cur.fetchall()
    return render_template('06_visite/06_visite.html', tutti_clienti=tutti_clienti, clienti_frequenti=clienti_frequenti)

@app.route('/ordini')
@login_required
def ordini_settimanali():
    with get_db() as db_conn:
        cur = db_conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, nome, zona, giorni_consegna_standard FROM clienti WHERE giorni_consegna_standard IS NOT NULL AND giorni_consegna_standard != ''")
        clienti = cur.fetchall()
        ordini_per_giorno = {}
        for c in clienti:
            days = c['giorni_consegna_standard'].split(',')
            for d in days:
                d = d.strip()
                if d not in ordini_per_giorno: ordini_per_giorno[d] = []
                ordini_per_giorno[d].append(c)
    return render_template('01_clienti/07_ordini.html', ordini_per_giorno=ordini_per_giorno)


from fpdf import FPDF

class WeeklyOrdersPDF(FPDF):
    def header(self):
        self.set_font('helvetica', 'B', 15)
        self.set_text_color(16, 185, 129)  # Emerald Horeca
        self.cell(0, 10, 'Horeca Suite - Programma Scarichi Settimanali', ln=True, align='L')
        self.set_font('helvetica', 'I', 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, f'Generato il {datetime.now().strftime("%d/%m/%Y alle %H:%M")}', ln=True, align='L')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f'Pagina {self.page_no()}/{{nb}}', align='C')

@app.route('/ordini/download_pdf')
@login_required
def download_ordini_pdf():
    with get_db() as db_conn:
        cur = db_conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, nome, zona, giorni_consegna_standard FROM clienti WHERE giorni_consegna_standard IS NOT NULL AND giorni_consegna_standard != ''")
        clienti = cur.fetchall()
        
    ordini_per_giorno = {str(i): [] for i in range(7)}
    for c in clienti:
        days = c['giorni_consegna_standard'].split(',')
        for d in days:
            d = d.strip()
            if d in ordini_per_giorno:
                ordini_per_giorno[d].append(c)

    for k in ordini_per_giorno:
        ordini_per_giorno[k].sort(key=lambda x: (x['zona'] or '', x['nome']))

    pdf = WeeklyOrdersPDF(orientation='L', unit='mm', format='A4')
    pdf.alias_nb_pages()
    pdf.add_page()
    
    giorni_nomi = {
        '1': 'Lunedì',
        '2': 'Martedì',
        '3': 'Mercoledì',
        '4': 'Giovedì',
        '5': 'Venerdì',
        '6': 'Sabato',
        '0': 'Domenica'
    }
    
    col_width = 38
    margin_left = 10
    top_y = pdf.get_y()
    
    pdf.set_font('helvetica', 'B', 10)
    giorni_keys = ['1', '2', '3', '4', '5', '6', '0']
    
    for idx, gk in enumerate(giorni_keys):
        x = margin_left + (idx * col_width)
        pdf.set_xy(x, top_y)
        pdf.set_fill_color(240, 240, 240)
        pdf.set_draw_color(200, 200, 200)
        pdf.cell(col_width, 8, giorni_nomi[gk], border=1, ln=0, align='C', fill=True)
    
    max_clients = max(len(ordini_per_giorno[gk]) for gk in giorni_keys) if ordini_per_giorno else 0
    
    current_y = top_y + 8
    pdf.set_font('helvetica', '', 7.5)
    
    for row_idx in range(max_clients):
        if current_y > 180:
            pdf.add_page()
            top_y = pdf.get_y()
            pdf.set_font('helvetica', 'B', 10)
            for idx, gk in enumerate(giorni_keys):
                x = margin_left + (idx * col_width)
                pdf.set_xy(x, top_y)
                pdf.set_fill_color(240, 240, 240)
                pdf.cell(col_width, 8, giorni_nomi[gk], border=1, ln=0, align='C', fill=True)
            current_y = top_y + 8
            pdf.set_font('helvetica', '', 7.5)

        row_height = 12
        
        for idx, gk in enumerate(giorni_keys):
            x = margin_left + (idx * col_width)
            pdf.set_xy(x, current_y)
            
            day_clients = ordini_per_giorno[gk]
            if row_idx < len(day_clients):
                c = day_clients[row_idx]
                nome_c = c['nome']
                zona_c = c['zona'] or '–'
                
                if len(nome_c) > 22:
                    nome_c = nome_c[:20] + "..."
                if len(zona_c) > 22:
                    zona_c = zona_c[:20] + "..."
                
                pdf.set_fill_color(255, 255, 255)
                pdf.rect(x, current_y, col_width, row_height, style='DF')
                
                pdf.set_xy(x + 2, current_y + 1.5)
                pdf.set_font('helvetica', 'B', 7.5)
                pdf.set_text_color(50, 50, 50)
                pdf.cell(col_width - 4, 4, nome_c, ln=True)
                
                pdf.set_xy(x + 2, current_y + 6)
                pdf.set_font('helvetica', '', 6.5)
                pdf.set_text_color(120, 120, 120)
                pdf.cell(col_width - 4, 3, f'({zona_c})', ln=True)
            else:
                pdf.set_fill_color(250, 250, 250)
                pdf.rect(x, current_y, col_width, row_height, style='DF')
                
        current_y += row_height

    from flask import make_response
    response = make_response(bytes(pdf.output()))
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=programma_scarichi_settimanali.pdf'
    return response

@app.route('/api/visite/save', methods=['POST'])
@login_required
def api_visite_save():
    cliente_id = request.form.get('cliente_id')
    data_visita = request.form.get('data_visita')
    ora_visita = request.form.get('ora_visita') or None
    note = request.form.get('note')
    with get_db() as db_conn:
        cur = db_conn.cursor()
        cur.execute('''
            INSERT INTO visite (cliente_id, data_visita, ora_visita, note)
            VALUES (%s, %s, %s, %s)
        ''', (cliente_id, data_visita, ora_visita, note))
        db_conn.commit()
    flash("Appuntamento salvato.", "success")
    return redirect(url_for('visite_clienti'))

@app.route('/api/visite/detail/<int:id>')
@login_required
def api_visite_detail(id):
    with get_db() as db_conn:
        cur = db_conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT v.*, c.nome as cliente_nome, c.zona 
            FROM visite v 
            JOIN clienti c ON v.cliente_id = c.id 
            WHERE v.id = %s
        ''', (id,))
        v = cur.fetchone()
    if not v: return "Visita non trovata", 404
    html = f'''
        <div class="modal-header border-0 p-4 pb-0">
            <h5 class="modal-title fw-bold">Dettaglio Visita</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
        </div>
        <div class="modal-body p-4">
            <h6 class="text-primary fw-bold mb-1">{v['cliente_nome']}</h6>
            <p class="text-muted small mb-3">{v['zona']}</p>
            <div class="mb-3">
                <span class="badge {'bg-success' if v['completata'] else 'bg-primary'} mb-2">
                    {'Completata' if v['completata'] else 'In programma'}
                </span>
                <p class="mb-0"><strong>Note:</strong> {v['note'] or 'Nessuna nota'}</p>
            </div>
        </div>
    '''
    return html

@app.route('/api/visite/move', methods=['POST'])
@login_required
def api_visite_move():
    data = request.json
    with get_db() as db_conn:
        cur = db_conn.cursor()
        cur.execute("UPDATE visite SET data_visita = %s, ora_visita = %s WHERE id = %s", (data['new_date'], data['new_time'], data['id']))
        db_conn.commit()
    return jsonify({"status": "ok"})

# ============================
# DISMISS NOTIFICHE AND OTHERS
# ============================
# ROUTE: dismiss_notifica
# ============================
@app.route("/api/notifiche/dismiss", methods=["POST"])
@login_required
def dismiss_notifica():
    id_notifica = request.form.get("id")
    if id_notifica:
        from flask import session
        if 'dismissed_notifiche' not in session:
            session['dismissed_notifiche'] = []
        if id_notifica not in session['dismissed_notifiche']:
            session['dismissed_notifiche'].append(id_notifica)
            session.modified = True
    return jsonify(success=True)
from collections import defaultdict
from datetime import datetime
# ============================
# GESTIONE PRODOTTI CLIENTI (PANNELLO RAPIDO)
# ============================

# ============================
# ROUTE: gestione_prodotti_clienti
# ============================
@app.route('/clienti/gestione_prodotti')
@login_required
def gestione_prodotti_clienti():
    from datetime import datetime
    oggi = datetime.now()
    with get_db() as db:
        cur = db.cursor()
        cur.execute("""
            SELECT id, nome, zona
            FROM clienti
            ORDER BY nome
        """)
        rows = cur.fetchall()
        
        clienti = []
        for r in rows:
            cid = r['id']
            # Max date
            cur.execute("SELECT MAX(data_operazione) AS max_d FROM clienti_prodotti WHERE cliente_id = %s", (cid,))
            res_d = cur.fetchone()
            last_date = res_d['max_d'] if res_d else None
            
            # Lavorati
            cur.execute("SELECT COUNT(*) AS c FROM clienti_prodotti WHERE cliente_id=%s AND lavorato=TRUE", (cid,))
            res_lav = cur.fetchone()
            count_lav = res_lav['c'] if res_lav else 0
            
            # Ex-lavorati
            cur.execute("SELECT COUNT(*) AS c FROM clienti_prodotti WHERE cliente_id=%s AND lavorato=FALSE AND data_inizio_lavorazione IS NOT NULL", (cid,))
            res_ex = cur.fetchone()
            count_ex = res_ex['c'] if res_ex else 0
            
            # Warnings
            cur.execute("SELECT COUNT(*) AS c FROM clienti_prodotti WHERE cliente_id=%s AND lavorato=TRUE AND volte_mancante > 0", (cid,))
            res_warn = cur.fetchone()
            count_warn = res_warn['c'] if res_warn else 0
            
            c_dict = dict(r)
            c_dict['ultima_importazione'] = last_date
            c_dict['count_lavorati'] = count_lav
            c_dict['count_ex'] = count_ex
            c_dict['count_warnings'] = count_warn
            clienti.append(c_dict)
    return render_template(
        '01_clienti/08_gestione_prodotti.html',
        clienti=clienti,
        is_saturday=(datetime.today().weekday() == 5)
    )
# ============================
# ROUTE CLIENTI
# ============================

# ============================
# ROUTE: quick_fatturato
# ============================
@app.route('/clienti/quick_fatturato/<int:id>', methods=['POST'])
@login_required
def quick_fatturato(id):
    anno = request.form.get('anno')
    if not anno:
        flash('Anno obbligatorio.', 'warning')
        return redirect(url_for('clienti'))
    try:
        anno_i = int(anno)
        saved_months = []
        
        with get_db() as db:
            cur = db.cursor()
            
            # Pre-carica i fatturati esistenti per questo cliente/anno
            cur.execute('SELECT mese, totale FROM fatturato WHERE cliente_id=%s AND anno=%s', (id, anno_i))
            exist_map = {row['mese']: float(row['totale']) for row in cur.fetchall()}
            
            is_any_dirty = False
            # Iteriamo per tutti i 12 mesi
            for m_num in range(1, 13):
                field_name = f'fatturato_{m_num}'
                valore = request.form.get(field_name)
                
                if valore and valore.strip() != "":
                    try:
                        totale_d = float(parse_decimal(valore))
                        
                        if m_num in exist_map:
                            if exist_map[m_num] != totale_d:
                                cur.execute('''
                                    UPDATE fatturato SET totale=%s 
                                    WHERE cliente_id=%s AND mese=%s AND anno=%s
                                ''', (totale_d, id, m_num, anno_i))
                                saved_months.append(str(m_num))
                                is_any_dirty = True
                        else:
                            cur.execute('''
                                INSERT INTO fatturato (cliente_id, mese, anno, totale)
                                VALUES (%s,%s,%s,%s)
                            ''', (id, m_num, anno_i, totale_d))
                            saved_months.append(str(m_num))
                            is_any_dirty = True
                    except (ValueError, TypeError):
                        continue
            
            if is_any_dirty:
                aggiorna_fatturato_totale(id, cur)
            db.commit()
        if saved_months:
            flash(f'Fatturato salvato per {len(saved_months)} mesi nell\'anno {anno_i}.', 'success')
        else:
            flash('Nessun dato inserito.', 'info')
            
    except Exception as e:
        flash(f'Errore salvataggio fatturato: {e}', 'danger')
    return redirect(url_for('clienti'))

# ============================
# ROUTE: api_prodotti_quick_update
# ============================
@app.route('/api/prodotti/quick_update', methods=['POST'])
@login_required
def api_prodotti_quick_update():
    """API per aggiornamento rapido nome e/o categoria di un prodotto."""
    data = request.get_json(silent=True) or {}
    prodotto_id = data.get('id')
    nuovo_nome = data.get('nome', '').strip() if data.get('nome') else None
    categoria_id = data.get('categoria_id')  # può essere int o None
    if not prodotto_id:
        return jsonify({'ok': False, 'error': 'ID prodotto mancante'}), 400
    try:
        with get_db() as db:
            cur = db.cursor(cursor_factory=RealDictCursor)
            # Verifica esistenza
            cur.execute('SELECT id, nome, categoria_id FROM prodotti WHERE id=%s AND COALESCE(eliminato, FALSE)=FALSE', (prodotto_id,))
            prodotto = cur.fetchone()
            if not prodotto:
                return jsonify({'ok': False, 'error': 'Prodotto non trovato'}), 404
            updates = []
            params = []
            if nuovo_nome:
                updates.append('nome=%s')
                params.append(nuovo_nome)
            if categoria_id is not None:
                cat_id = int(categoria_id) if categoria_id else None
                updates.append('categoria_id=%s')
                params.append(cat_id)
            if not updates:
                return jsonify({'ok': False, 'error': 'Nessun campo da aggiornare'}), 400
            params.append(prodotto_id)
            cur.execute(f'UPDATE prodotti SET {", ".join(updates)} WHERE id=%s', params)
            db.commit()
            # Ritorna i dati aggiornati
            cur.execute('''
                SELECT p.id, p.nome, p.codice, p.categoria_id, COALESCE(c.nome, '') AS categoria_nome
                FROM prodotti p LEFT JOIN categorie c ON p.categoria_id=c.id
                WHERE p.id=%s
            ''', (prodotto_id,))
            updated = cur.fetchone()
        return jsonify({
            'ok': True,
            'prodotto': {
                'id': updated['id'],
                'nome': updated['nome'],
                'codice': updated['codice'],
                'categoria_id': updated['categoria_id'],
                'categoria_nome': updated['categoria_nome']
            }
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ============================
# ROUTE: gestione_fatturato
# ============================
@app.route('/fatturato/gestione', methods=['GET'])
@login_required
def gestione_fatturato():
    oggi = datetime.now()
    # Default to previous month
    mese_def = (oggi.replace(day=1) - relativedelta(months=1)).month
    anno_def = (oggi.replace(day=1) - relativedelta(months=1)).year
    
    mese = request.args.get('mese', default=mese_def, type=int)
    anno = request.args.get('anno', default=anno_def, type=int)
    
    # Calcola mese e anno precedenti per confronto e copia rapida
    selected_date = datetime(anno, mese, 1)
    prev_date = selected_date - relativedelta(months=1)
    prev_mese = prev_date.month
    prev_anno = prev_date.year

    with get_db() as db:
        cur = db.cursor()
        cur.execute('''
            SELECT id, nome, zona
            FROM clienti
            WHERE stato = 'attivo' OR stato IS NULL OR stato = 'automatico'
            ORDER BY nome
        ''')
        clienti_attivi = cur.fetchall()
        if clienti_attivi:
            c_ids = [c['id'] for c in clienti_attivi]
            placeholders = ','.join(['%s'] * len(c_ids))
            
            # Query per mese corrente
            cur.execute(f'''
                SELECT cliente_id, totale
                FROM fatturato
                WHERE mese = %s AND anno = %s AND cliente_id IN ({placeholders})
            ''', (mese, anno, *c_ids))
            fatt_dati = {row['cliente_id']: row['totale'] for row in cur.fetchall()}
            
            # Query per mese precedente
            cur.execute(f'''
                SELECT cliente_id, totale
                FROM fatturato
                WHERE mese = %s AND anno = %s AND cliente_id IN ({placeholders})
            ''', (prev_mese, prev_anno, *c_ids))
            prev_fatt_dati = {row['cliente_id']: row['totale'] for row in cur.fetchall()}
            
            for c in clienti_attivi:
                c['importo'] = fatt_dati.get(c['id'], '')
                c['prev_importo'] = prev_fatt_dati.get(c['id'], '')
                
    return render_template(
        '03_fatturato/02_gestione_fatturato.html', 
        mese=mese, 
        anno=anno, 
        prev_mese=prev_mese, 
        prev_anno=prev_anno, 
        clienti=clienti_attivi
    )

# ============================
# ROUTE: salva_gestione_fatturato
# ============================
@app.route('/fatturato/gestione/salva', methods=['POST'])
@login_required
def salva_gestione_fatturato():
    mese = int(request.form.get('mese'))
    anno = int(request.form.get('anno'))
    
    with get_db() as db:
        cur = db.cursor()
        # Pre-carica tutti i record di fatturato esistenti per quel mese/anno
        cur.execute('SELECT id, cliente_id, totale FROM fatturato WHERE mese=%s AND anno=%s', (mese, anno))
        exist_map = {row['cliente_id']: row for row in cur.fetchall()}

        updated_clients = set()
        for key, value in request.form.items():
            if key.startswith('fatturato_') and value.strip() != '':
                c_id = int(key.split('_')[1])
                try:
                    importo = float(value)
                except ValueError:
                    continue
                
                if c_id in exist_map:
                    db_row = exist_map[c_id]
                    if float(db_row['totale']) != importo:
                        cur.execute('UPDATE fatturato SET totale=%s WHERE id=%s', (importo, db_row['id']))
                        updated_clients.add(c_id)
                else:
                    cur.execute('INSERT INTO fatturato (cliente_id, mese, anno, totale) VALUES (%s, %s, %s, %s)', (c_id, mese, anno, importo))
                    updated_clients.add(c_id)
        
        # Aggiorna il fatturato totale accumulato per ciascun cliente effettivamente aggiornato
        for c_id in updated_clients:
            aggiorna_fatturato_totale(c_id, cur)
            
        db.commit()
    
    flash("Fatturati aggiornati con successo massivamente!", "success")
    return redirect(url_for('fatturato'))

# ============================
# ROUTE: api_genera_volantino_da_prodotti
# ============================
@app.route('/api/genera_volantino_da_prodotti', methods=['POST'])
@login_required
def api_genera_volantino_da_prodotti():
    """Genera un volantino partendo da una lista di prodotti già rivisti dall'utente."""
    data = request.get_json(silent=True) or {}
    prodotti_list = data.get('prodotti', [])
    tema = data.get('tema', 'standard')
    return jsonify({"success": True, "message": "✅ Layout salvato correttamente"})
    if not prodotti_list:
        return jsonify({"success": False, "message": "Nessun prodotto da importare"}), 400
    try:
        # Funzione helper per dividere la lista in blocchi da 16 (4x4)
        def chunk_list(lst, n):
            for i in range(0, len(lst), n):
                yield lst[i:i + n]
        pagine_prodotti = list(chunk_list(prodotti_list, 16))
        is_themed = (tema in ['carne', 'pesce'])
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            doc_pages = []
            for index_pag, blocco in enumerate(pagine_prodotti):
                bg_url = ""
                if tema == 'carne': bg_url = "/static/uploads/volantini_sfondi/sfondo_carne.png"
                page_layout = {
                    "header": {
                        "title": "",
                        "titleColor": "#000000",
                        "titleSize": 48,
                        "logoUrl": "https://us-east-1.tixte.net/uploads/leonardogiorgini.tixte.co/logo-pregis-bordo.png",
                        "logoSize": 180,
                        "logoPos": "none" if is_themed else "center",
                        "titlePos": "none" if is_themed else "center"
                    },
                    "global": {
                        "theme": tema,
                        "border": True,
                        "bgColor": "#ffffff",
                        "width": 4200,
                        "height": 2600,
                        "gridWidth": 1800,
                        "cols": 4,
                        "paddingTop": 30,
                        "paddingBottom": 30,
                        "paddingSides": 30,
                        "gridGap": 15,
                        "nameSize": 1.0,
                        "priceSize": 1.8
                    },
                    "background": {
                        "url": bg_url,
                        "nome": f"Sfondo {tema.capitalize()} Default"
                    } if bg_url else None,
                    "grid": []
                }
                # Costruisci le 16 celle
                cell_counter = 1
                for prod in blocco:
                    page_layout["grid"].append({
                        "id": f"cell_{cell_counter}",
                        "colSpan": 1,
                        "rowSpan": 1,
                        "isHidden": False,
                        "productId": prod.get("id"),
                        "name": prod.get("nome", ""),
                        "price": prod.get("prezzo", ""),
                        "img": prod.get("immagine", ""),
                        "bgTransparent": False,
                        "bgColor": "#ffffff",
                        "nameColor": "#000000",
                        "priceColor": "#e60000"
                    })
                    cell_counter += 1
                # Pad remaining cells to fill the 4x4 grid
                while cell_counter <= 16:
                    page_layout["grid"].append({
                        "id": f"cell_{cell_counter}",
                        "colSpan": 1,
                        "rowSpan": 1,
                        "isHidden": False,
                        "productId": None,
                        "name": "",
                        "price": "",
                        "img": "",
                        "bgColor": "#ffffff",
                        "nameColor": "#000000",
                        "priceColor": "#e60000"
                    })
                    cell_counter += 1
                doc_pages.append(page_layout)
            # Build layout_json
            if len(doc_pages) > 1:
                layout_json = {
                    "isMultiPage": True,
                    "pages": doc_pages
                }
            else:
                layout_json = doc_pages[0] if doc_pages else {}
            titolo_volantino = f"Volantino {tema.capitalize()} - {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            nuovo_volantino = VolantinoBeta(
                nome=titolo_volantino,
                layout_json=json.dumps(layout_json, ensure_ascii=False),
                tipo='volantino'
            )
            db.session.add(nuovo_volantino)
            db.session.commit()
        return jsonify({"success": True, "id": nuovo_volantino.id})
    except Exception as e:
        print(f"Errore generazione da prodotti: {e}")
        return jsonify({"success": False, "message": f"Errore interno: {str(e)}"}), 500
# ============================
# GENERA VOLANTINO DA PDF
# ============================

# ============================
# ROUTE: api_genera_volantino_da_pdf
# ============================
@app.route('/api/genera_volantino_da_pdf', methods=['POST'])
@login_required
def api_genera_volantino_da_pdf():
    if 'file' not in request.files:
        return jsonify({"success": False, "message": "Nessun file inviato"}), 400
        
    file = request.files['file']
    if not file.filename.endswith('.pdf'):
        return jsonify({"success": False, "message": "Il file deve essere un PDF"}), 400
        
    try:
        # Salvataggio temporaneo sicuro usando tempfile
        fd, temp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        file.save(temp_path)
        
        # Parsing usando la logica esistente
        offerte = parse_offers_from_pdf(temp_path)
        
        # Pulizia file temporaneo
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        if not offerte:
            return jsonify({"success": False, "message": "Nessun prodotto trovato nel PDF"}), 400
            
        # Funzione helper per dividere la lista in blocchi
        def chunk_list(lst, n):
            for i in range(0, len(lst), n):
                yield lst[i:i + n]
        # Dividiamo le offerte estratte in pagine (max 9 formelle per pagina)
        pagine_offerte = list(chunk_list(offerte, 9))
        primo_volantino_id = None
        tema = request.form.get("tema", "standard")
        
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            for index_pag, blocco_offerte in enumerate(pagine_offerte):
                is_themed = (tema in ['carne', 'pesce'])
                
                bg_url = ""
                if tema == 'carne': bg_url = "/static/uploads/volantini_sfondi/sfondo_carne.png"
                elif tema == 'pesce': bg_url = ""
                # Costruiamo il layout per questa specifica pagina
                layout_json = {
                    "header": {
                        "title": "", 
                        "titleColor": "#000000", 
                        "titleSize": 48, # 32 * 1.5
                        "logoUrl": "https://us-east-1.tixte.net/uploads/leonardogiorgini.tixte.co/logo-pregis-bordo.png", 
                        "logoSize": 180, # 120 * 1.5
                        "logoPos": "none" if is_themed else "center", 
                        "titlePos": "none" if is_themed else "center"
                    }, 
                    "global": {
                        "theme": tema,
                        "border": True,
                        "bgColor": "#ffffff",
                        "width": 4200,
                        "height": 1250,
                        "paddingTop": 0,
                        "paddingBottom": 0,
                        "paddingSides": 0,
                        "gridGap": 0
                    },
                    "background": {
                        "url": bg_url,
                        "nome": f"Sfondo {tema.capitalize()} Default"
                    } if is_themed else None,
                    "grid": []
                }
                
                # --- AUTO-LOAD THEME PERSISTENCE ---
                # Cerca l'ultimo volantino salvato con questo stesso tema per ereditarne sfondo e margini
                try:
                    cur.execute("""
                        SELECT layout_json, titolo FROM volantini 
                        WHERE layout_json::jsonb -> 'global' ->> 'theme' = %s 
                        ORDER BY data_creazione DESC LIMIT 1
                    """, (tema,))
                    last_themed_vol = cur.fetchone()
                    
                    if last_themed_vol and last_themed_vol['layout_json']:
                        prev_layout = json.loads(last_themed_vol['layout_json'])
                        # Se il volo sorgente si chiamava esattamente "volantino carne" / "volantino pesce", clona anche la griglia
                        clona_griglia = last_themed_vol['titolo'].strip().lower() in ['volantino carne', 'volantino pesce']
                        
                        if 'global' in prev_layout:
                            layout_json['global'] = prev_layout['global']
                            layout_json['global']['theme'] = tema
                        if 'header' in prev_layout:
                            layout_json['header'] = prev_layout['header']
                        if 'background' in prev_layout:
                            layout_json['background'] = prev_layout['background']
                            if layout_json['background'] and 'placeholder.com' in layout_json['background'].get('url', ''):
                                layout_json['background']['url'] = ''
                        
                        if clona_griglia and 'grid' in prev_layout:
                            layout_json['grid'] = prev_layout['grid']
                            
                except Exception as ex:
                    print(f"Errore recupero template precedente: {ex}")
                # -----------------------------------
                
                # Inizializziamo sempre una griglia fissa 3x3 (= 9 celle) per evitare che si sformi, 
                # MA SOLO SE non è stata appena clonata integralmente dal template "Volantino carne" / "pesce"
                if not layout_json.get("grid"):
                    for c in range(1, 10):
                        layout_json["grid"].append({
                            "id": f"cell_{c}",
                            "colSpan": 1,
                            "rowSpan": 1,
                            "isHidden": False,
                            "productId": None,
                            "name": "",
                            "price": "",
                            "img": "",
                            "bgTransparent": True,
                            "bgColor": "#ffffff",
                            "nameColor": "#000000",
                            "priceColor": "#e60000"
                        })
                
                # Riempiamo le celle sequenzialmente con i prodotti di questo blocco
                for i, offerta in enumerate(blocco_offerte):
                    # Proviamo prima il match esatto per codice prodotto
                    cur.execute("SELECT id, immagine, nome FROM prodotti WHERE codice=%s LIMIT 1", (offerta['code'],))
                    prod = cur.fetchone()
                    
                    # Se non trova per codice, tenta fallback per nome
                    if not prod:
                        cur.execute("SELECT id, immagine, nome FROM prodotti WHERE nome ILIKE %s LIMIT 1", (f"%{offerta['name']}%",))
                        prod = cur.fetchone()
                    
                    prod_id = prod['id'] if prod else None
                    img_url = prod['immagine'] if prod and prod['immagine'] else ""
                    # Se trova il prodotto nel DB (per codice o nome simmetrico), usa RIGOROSAMENTE il nome del DB
                    nome_display = prod['nome'] if prod else offerta['name']
                    
                    # Popoliamo la cella i-esima (aggiornando le proprietà preimpostate)
                    cella = layout_json["grid"][i]
                    cella["productId"] = prod_id
                    cella["name"] = nome_display
                    cella["price"] = f"€ {offerta['price']}"
                    cella["img"] = img_url
                    cella["bgTransparent"] = False # Ha contenuto, mostriamo lo sfondo della cella
                    
                # Costruiamo il titolo progressivo
                tot_pagine = len(pagine_offerte)
                titolo_base = f"Volantino {datetime.now().strftime('%d/%m/%Y')} (Da PDF)"
                if tot_pagine > 1:
                    titolo_volantino = f"{titolo_base} - Pag. {index_pag + 1}"
                else:
                    titolo_volantino = titolo_base
                    
                # Salviamo la pagina corrente nel database usando SQLAlchemy
                nuovo_volantino = VolantinoBeta(
                    nome=titolo_volantino,
                    layout_json=json.dumps(layout_json, ensure_ascii=False)
                )
                db.session.add(nuovo_volantino)
                db.session.flush() # Flush per ottenere l'ID per impostarlo se è il primo
                
                if primo_volantino_id is None:
                    primo_volantino_id = nuovo_volantino.id
            # Commit di tutti i volantini generati
            db.session.commit()
            
        return jsonify({"success": True, "id": primo_volantino_id})
        
    except Exception as e:
        print(f"Errore generazione PDF: {e}")
        return jsonify({"success": False, "message": f"Errore interno: {str(e)}"}), 500
# ============================
# ESTRAI PRODOTTI DA PDF (JSON)
# ============================

# ============================
# ROUTE: api_estrai_prodotti_da_pdf
# ============================
@app.route('/api/estrai_prodotti_da_pdf', methods=['POST'])
@login_required
def api_estrai_prodotti_da_pdf():
    if 'file' not in request.files:
        return jsonify({"success": False, "message": "Nessun file inviato"}), 400
        
    file = request.files['file']
    if not file.filename.endswith('.pdf'):
        return jsonify({"success": False, "message": "Il file deve essere un PDF"}), 400
        
    try:
        # Salvataggio temporaneo sicuro usando tempfile
        fd, temp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        file.save(temp_path)
        
        # Parsing usando la logica esistente
        offerte = parse_offers_from_pdf(temp_path)
        
        # Pulizia file temporaneo
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        if not offerte:
            return jsonify({"success": False, "message": "Nessun prodotto trovato nel PDF"}), 400
            
        risultati = []
        
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            for offerta in offerte:
                # Proviamo prima il match esatto per codice prodotto
                cur.execute("SELECT id, immagine, nome FROM prodotti WHERE codice=%s LIMIT 1", (offerta['code'],))
                prod = cur.fetchone()
                
                # Se non trova per codice, tenta fallback per nome
                if not prod:
                    cur.execute("SELECT id, immagine, nome FROM prodotti WHERE nome ILIKE %s LIMIT 1", (f"%{offerta['name']}%",))
                    prod = cur.fetchone()
                
                prod_id = prod['id'] if prod else None
                img_url = prod['immagine'] if prod and prod['immagine'] else ""
                nome_display = prod['nome'] if prod else offerta['name']
                
                # Costruisci l'URL finale dell'immagine visibile al front-end se presente
                img_full_url = ""
                if img_url:
                    img_full_url = url_for("static", filename=f"uploads/volantino_prodotti/{img_url}")
                else: 
                     img_full_url = f"https://via.placeholder.com/300?text={urllib.parse.quote(nome_display[:15])}"
                risultati.append({
                    "id": prod_id,
                    "nome": nome_display,
                    "prezzo": f"€ {offerta['price']}" if offerta.get('price') and offerta['price'].strip() and offerta['price'].strip() != '€' else "",
                    "immagine": img_full_url,
                    "page": offerta.get('page', 0)
                })
                
        return jsonify({"success": True, "prodotti": risultati})
        
    except Exception as e:
        print(f"Errore estrazione PDF: {e}")
        return jsonify({"success": False, "message": f"Errore interno: {str(e)}"}), 500
# ============================
# API SFONDI VOLANTINO
# ============================
UPLOAD_FOLDER_SFONDI_VOLANTINO = os.path.join(STATIC_DIR, "uploads", "volantini_sfondi")
os.makedirs(UPLOAD_FOLDER_SFONDI_VOLANTINO, exist_ok=True)

# ============================
# ROUTE: get_sfondi_volantino
# ============================
@app.route('/api/sfondi_volantino', methods=['GET'])
@login_required
def get_sfondi_volantino():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, nome, immagine, data_creazione FROM volantini_sfondi ORDER BY data_creazione DESC")
        sfondi = cur.fetchall()
        
        # Mappa i path completi per il frontend
        for s in sfondi:
            s['url'] = url_for('static', filename=f'uploads/volantini_sfondi/{s["immagine"]}')
            
        return jsonify({"success": True, "sfondi": sfondi})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()

# ============================
# ROUTE: upload_sfondo_volantino
# ============================
@app.route('/api/sfondi_volantino', methods=['POST'])
@login_required
def upload_sfondo_volantino():
    nome = request.form.get('nome', '').strip()
    file = request.files.get('file')
    link = request.form.get('link', '').strip()
    
    if not nome:
        return jsonify({"success": False, "message": "Il nome dello sfondo è obbligatorio."}), 400
        
    immagine_filename = ""
    
    if file and file.filename:
        filename = secure_filename(file.filename)
        immagine_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
        file.save(os.path.join(UPLOAD_FOLDER_SFONDI_VOLANTINO, immagine_filename))
    elif link:
        immagine_filename = link # Salviamo direttamente il link
    else:
        return jsonify({"success": False, "message": "Devi fornire un'immagine o un link."}), 400
        
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO volantini_sfondi (nome, immagine, data_creazione) VALUES (%s, %s, NOW()) RETURNING id",
            (nome, immagine_filename)
        )
        new_id = cur.fetchone()["id"]
        conn.commit()
        
        url = link if link else url_for('static', filename=f'uploads/volantini_sfondi/{immagine_filename}')
        return jsonify({"success": True, "sfondo": {"id": new_id, "nome": nome, "immagine": immagine_filename, "url": url}})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()

# ============================
# ROUTE: delete_sfondo_volantino
# ============================
@app.route('/api/sfondi_volantino/<int:sfondo_id>', methods=['DELETE'])
@login_required
def delete_sfondo_volantino(sfondo_id):
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SELECT immagine FROM volantini_sfondi WHERE id = %s", (sfondo_id,))
        sfondo = cur.fetchone()
        
        if not sfondo:
            return jsonify({"success": False, "message": "Sfondo non trovato"}), 404
            
        # Elimina il file fisico se non è un link
        img_name = sfondo["immagine"]
        if not img_name.startswith("http"):
            img_path = os.path.join(UPLOAD_FOLDER_SFONDI_VOLANTINO, img_name)
            if os.path.exists(img_path):
                os.remove(img_path)
                
        cur.execute("DELETE FROM volantini_sfondi WHERE id = %s", (sfondo_id,))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()
# ============================
# LISTA VOLANTINI + PROMO LAMPO
# ============================

# ============================
# ROUTE: beta_volantino
# ============================
@app.route('/beta-volantino')
def beta_volantino():
    tema = request.args.get('tema', 'standard')
    tipo = request.args.get('tipo', 'volantino')
    is_themed = (tema in ['carne', 'pesce'])
    
    bg_url = ""
    if tema == 'carne': bg_url = "/static/uploads/volantini_sfondi/sfondo_carne.png"
    elif tema == 'pesce': bg_url = ""
    
    # Creiamo un layout base con il tema preimpostato se passato dalla query
    base_layout = {
        "header": {
            "title": "", 
            "titleColor": "#000000", 
            "titleSize": 48,
            "logoUrl": "https://us-east-1.tixte.net/uploads/leonardogiorgini.tixte.co/logo-pregis-bordo.png", 
            "logoSize": 180,
            "logoPos": "none" if is_themed else "center",
            "titlePos": "none" if is_themed else "center"
        },
        "global": {
            "theme": tema,
            "width": 1250 if is_themed else 4200, 
            "height": 2800 if is_themed else 1250,
            "gridWidth": 1150 if is_themed else 1800,
            "cols": 3,
            "rowHeight": 0,
            "nameSize": 1.0,
            "priceSize": 1.8,
            "border": True,
            "bgColor": "#ffffff",
            "paddingTop": 50,
            "paddingBottom": 50,
            "paddingSides": 50,
            "gridGap": 20
        },
        "background": {
            "url": bg_url,
            "nome": f"Sfondo {tema.capitalize()} Default"
        } if bg_url else None
    }
    
    # --- AUTO-LOAD THEME PERSISTENCE ---
    # Cerca l'ultimo volantino salvato con questo stesso tema per ereditarne sfondo e margini
    try:
        vols = VolantinoBeta.query.order_by(VolantinoBeta.creato_il.desc()).all()
        last_themed_vol = None
        for v in vols:
            try:
                layout = json.loads(v.layout_json)
                if layout.get('global', {}).get('theme') == tema:
                    last_themed_vol = v
                    break
            except:
                continue

        if last_themed_vol:
            prev_layout = json.loads(last_themed_vol.layout_json)
            
            clona_griglia = last_themed_vol.nome.strip().lower() in ['volantino carne', 'volantino pesce']
            
            if 'global' in prev_layout:
                base_layout['global'] = prev_layout['global']
                base_layout['global']['theme'] = tema
            if 'header' in prev_layout:
                base_layout['header'] = prev_layout['header']
            if 'background' in prev_layout:
                base_layout['background'] = prev_layout['background']
                # Sanitize legacy placeholders from the old fish theme
                if base_layout['background'] and 'placeholder.com' in base_layout['background'].get('url', ''):
                    base_layout['background']['url'] = ''
                    
            if clona_griglia and 'grid' in prev_layout and len(prev_layout['grid']) > 0:
                base_layout['grid'] = prev_layout['grid']
            
            # Assicuriamoci che i valori globali siano sensati se ereditati
            if 'global' in base_layout:
                g = base_layout['global']
                if not g.get('cols') or int(g['cols']) < 1: g['cols'] = 3
                if not g.get('gridWidth') or int(g['gridWidth']) < 100: g['gridWidth'] = 1800
                if not g.get('width') or int(g['width']) < 100: g['width'] = 4200
                if not g.get('height') or int(g['height']) < 100: g['height'] = 1250
    except Exception as ex:
        print(f"Errore recupero template precedente: {ex}")
    # -----------------------------------
    
    # Caricamento automatico dei prodotti da promo scadenze se richiesto
    import_scadenze = request.args.get('scadenze')
    if import_scadenze == '1':
        preset_data = {}
        preset_path = os.path.join(app.root_path, 'preset_default.json')
        if os.path.exists(preset_path):
            try:
                with open(preset_path, 'r', encoding='utf-8') as pf:
                    preset_data = json.load(pf)
            except Exception as pex:
                print("Errore lettura preset default in beta_volantino:", pex)

        try:
            with get_db() as db:
                cur = db.cursor()
                # Seleziona prodotti della promo scadenze ordinati come da PDF (per ID)
                cur.execute('''
                    SELECT psp.codice, psp.nome, psp.prezzo, psp.um, psp.prodotto_id, prod.immagine, psp.scadenza
                    FROM promo_scadenze_prodotti psp
                    LEFT JOIN prodotti prod ON psp.prodotto_id = prod.id
                    ORDER BY psp.id
                ''')
                psp_rows = cur.fetchall()
                
                # Raggruppiamo i prodotti in pagine di 9 elementi (3x3)
                pagine_prodotti = []
                temp_page = []
                for r in psp_rows:
                    row_dict = dict(r) if isinstance(r, dict) else {
                        "codice": r[0], "nome": r[1], "prezzo": r[2], "um": r[3], "prodotto_id": r[4], "immagine": r[5], "scadenza": r[6]
                    }
                    
                    prod_id = row_dict["prodotto_id"]
                    codice = row_dict["codice"] or ""
                    nome = row_dict["nome"] or ""
                    prezzo = row_dict["prezzo"]
                    um = row_dict["um"] or "PZ"
                    immagine = row_dict["immagine"]
                    scadenza = row_dict["scadenza"] or ""
                    
                    img_url = ""
                    if immagine:
                        img_url = url_for('static', filename=f'uploads/volantino_prodotti/{immagine}')
                        
                    prezzo_str = f"€ {prezzo:.2f} / {um}" if prezzo else "–"
                    
                    cell_data = {
                        "codice": codice,
                        "titolo": nome,
                        "descrizione": "",
                        "scadenza": scadenza,
                        "scadenzaSize": "12",
                        "scadenzaY": "-4",
                        "prezzo": prezzo_str,
                        "img": img_url,
                        "imgOriginal": img_url,
                        "imgNoBg": img_url,
                        "useNoBg": "1",
                        "showDesc": "0",
                        "priceSize": "26",
                        "priceColor": "#e11d48",
                        "priceBg": "#ffffff",
                        "priceCurrency": "€",
                        "priceWeight": "800",
                        "priceStyle": "base",
                        "layout": "modern-split",
                        "titleSize": "17",
                        "titleWeight": "700",
                        "titleSpacing": "0",
                        "titleHeight": "1.2",
                        "codeSize": "10",
                        "descSize": "11",
                        "descItalic": "0",
                        "textUpper": "1",
                        "fontColor": "#0f172a",
                        "borderStyle": "solid",
                        "borderColor": "#cbd5e1",
                        "radius": "8",
                        "bgColor": "#ffffff",
                        "bgTransparent": "0",
                        "shadow": "1",
                        "imageZoom": "1.0",
                        "imagePosX": "50",
                        "imagePosY": "50",
                        "imageRadius": "6",
                        "imagePadding": "5",
                        "imageAspect": "contain",
                        "productId": prod_id
                    }
                    
                    if 'cellStyles' in preset_data:
                        for k, v in preset_data['cellStyles'].items():
                            if k not in ['codice', 'titolo', 'descrizione', 'scadenza', 'prezzo', 'img', 'imgOriginal', 'imgNoBg', 'productId']:
                                cell_data[k] = v
                                
                    temp_page.append(cell_data)
                    if len(temp_page) == 9:
                        pagine_prodotti.append(temp_page)
                        temp_page = []
                if temp_page:
                    pagine_prodotti.append(temp_page)
                
                # Se non c'è nessun prodotto, assicuriamoci di avere almeno una griglia vuota
                if not pagine_prodotti:
                    pagine_prodotti = [[]]
                
                # Costruiamo il layout JSON compatibile (array di pagine)
                layout_pages = []
                
                g_cols = int(preset_data.get('cols', 3)) if preset_data.get('cols') else 3
                g_rows = int(preset_data.get('rows', 3)) if preset_data.get('rows') else 3
                g_gap = int(preset_data.get('gap', 10)) if preset_data.get('gap') else 10
                
                g_larghezza = preset_data.get('larghezza', '1250')
                g_altezza = preset_data.get('altezza', '1750')
                g_padTop = preset_data.get('padTop', '20')
                g_padBottom = preset_data.get('padBottom', '20')
                g_padSides = preset_data.get('padSides', '20')
                g_headerH = preset_data.get('headerH', '120')
                g_footerH = preset_data.get('footerH', '80')
                
                default_logo = "https://us-east-1.tixte.net/uploads/leonardogiorgini.tixte.co/logo-pregis-bordo.png"
                g_headerImg = preset_data.get('headerImg') if preset_data.get('headerImg') else default_logo
                
                g_bgImg = preset_data.get('bgImg', '')
                g_bgWidth = preset_data.get('bgWidth', '100')
                g_bgHeight = preset_data.get('bgHeight', '100')
                g_bgPosX = preset_data.get('bgPosX', '50')
                g_bgPosY = preset_data.get('bgPosY', '50')
                g_cellWidth = preset_data.get('cellWidth', '380')
                g_cellHeight = preset_data.get('cellHeight', '500')
                
                for p_idx, cells in enumerate(pagine_prodotti):
                    layout_pages.append({
                        "cols": g_cols,
                        "rows": g_rows,
                        "gap": g_gap,
                        "larghezza": g_larghezza,
                        "altezza": g_altezza,
                        "padTop": g_padTop,
                        "padBottom": g_padBottom,
                        "padSides": g_padSides,
                        "headerH": g_headerH if p_idx == 0 else "50",
                        "footerH": g_footerH,
                        "headerImg": g_headerImg if p_idx == 0 else None,
                        "footerImg": None,
                        "cells": cells,
                        "bgImg": g_bgImg,
                        "bgWidth": g_bgWidth,
                        "bgHeight": g_bgHeight,
                        "bgPosX": g_bgPosX,
                        "bgPosY": g_bgPosY,
                        "cellWidth": g_cellWidth,
                        "cellHeight": g_cellHeight
                    })
                    
                return render_template(
                    '05_beta_volantino/05_beta_volantino.html',
                    volantino_id=None,
                    nome_volantino="Volantino Scadenze",
                    layout_json=json.dumps(layout_pages),
                    thumbnail="",
                    tipo_volantino=tipo
                )
        except Exception as ex:
            print(f"Errore caricamento prodotti scadenze nel volantino: {ex}")
            import traceback
            traceback.print_exc()

    if not base_layout.get("grid"):
        base_layout["grid"] = []
        for c in range(1, 10):
            base_layout["grid"].append({
                "id": f"cell_{c}",
                "colSpan": 1,
                "rowSpan": 1,
                "isHidden": False,
                "productId": None,
                "name": "",
                "price": "",
                "img": "",
                "bgTransparent": False,
                "bgColor": "#f9f9f9",
                "nameColor": "#333",
                "priceColor": "#e60000"
            })
    return render_template(
        '05_beta_volantino/05_beta_volantino.html',
        volantino_id=None,
        nome_volantino="",
        layout_json=json.dumps(base_layout),
        thumbnail="",
        tipo_volantino=tipo
    )

# ============================
# ROUTE: api_prodotti_volantino
# ============================
@app.route('/api/prodotti_volantino')
@login_required
def api_prodotti_volantino():
    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT
                p.id,
                p.codice,
                p.nome,
                p.prezzo,
                p.immagine,
                p.categoria_id,
                p.img_zoom,
                p.img_pos_x,
                p.img_pos_y,
                c.nome AS categoria_nome
            FROM prodotti p
            LEFT JOIN categorie c ON p.categoria_id = c.id
            WHERE COALESCE(p.eliminato, FALSE) = FALSE
            ORDER BY c.nome NULLS LAST, p.nome
        ''')
        prodotti = cur.fetchall()
        
        # Format the result correctly to handle decimals or dates if any
        res = []
        for p in prodotti:
            # Generate the full static URL for the image if it exists in the database
            img_val = p.get("immagine")
            img_url = ""
            if img_val:
                if img_val.startswith('http://') or img_val.startswith('https://') or img_val.startswith('/'):
                    img_url = img_val
                else:
                    img_url = url_for('static', filename=f"uploads/volantino_prodotti/{img_val}")
                    
            res.append({
                "id": p["id"],
                "codice": p["codice"] or "",
                "nome": p["nome"],
                "prezzo": str(p["prezzo"]) if p["prezzo"] is not None else "",
                "immagine": img_url,
                "categoria_nome": p["categoria_nome"] or "Senza Categoria",
                "imageZoom": str(p.get("img_zoom")) if p.get("img_zoom") is not None else "1.0",
                "imagePosX": str(p.get("img_pos_x")) if p.get("img_pos_x") is not None else "50",
                "imagePosY": str(p.get("img_pos_y")) if p.get("img_pos_y") is not None else "50"
            })
            
    return jsonify(res)

# ============================
# ROUTE: api_cerca_immagine
# ============================
@app.route('/api/cerca_immagine')
@login_required
def api_cerca_immagine():
    import urllib.parse
    import re
    import requests
    
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.0.0 Safari/537.36"
    }
    
    # Search the exact product name, pure and simple, for the most accurate results
    url = f"https://www.bing.com/images/search?q={urllib.parse.quote(query)}"
    try:
        r = requests.get(url, headers=headers, timeout=5)
        
        # Extract all high-quality Bing CDN thumbnail links (th.bing.com / mm.bing.net)
        urls = re.findall(r'https?://[a-z0-9\.]+\.bing\.net/th[^"\'\s>]+', r.text, re.IGNORECASE)
        
        filtered_urls = []
        seen = set()
        for u in urls:
            # HTML entity decoding / cleaning
            u = u.replace('&amp;', '&').replace('&quot;', '"').replace('&#39;', "'")
            
            # Remove any low-resolution width/height limits to upgrade quality
            u = re.sub(r'[&?]w=[0-9]+', '', u)
            u = re.sub(r'[&?]h=[0-9]+', '', u)
            
            # Inject high-definition parameters (1200x1200px)
            if '?' in u:
                u += '&w=1200&h=1200&c=7'
            else:
                u += '?w=1200&h=1200&c=7'
                
            if u not in seen:
                seen.add(u)
                filtered_urls.append(u)
            if len(filtered_urls) >= 15:
                break
                
        # Fallback to high-quality Unsplash images if search produces no results
        if not filtered_urls:
            filtered_urls = [
                f"https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=600&auto=format&fit=crop&q=80",
                f"https://images.unsplash.com/photo-1567620905732-2d1ec7ab7445?w=600&auto=format&fit=crop&q=80",
                f"https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?w=600&auto=format&fit=crop&q=80",
                f"https://images.unsplash.com/photo-1482049016688-2d3e1b311543?w=600&auto=format&fit=crop&q=80",
                f"https://images.unsplash.com/photo-1484723091739-30a097e8f929?w=600&auto=format&fit=crop&q=80"
            ]
            
        return jsonify(filtered_urls)
    except Exception as e:
        print("Errore scraping immagini:", e)
        return jsonify([])

import werkzeug.utils
def remove_bg_if_possible(file_path):
    try:
        print(f"Rimuovendo sfondo da {file_path} con rembg...")
        from rembg import remove
        from PIL import Image
        import os
        
        input_image = Image.open(file_path)
        output_image = remove(input_image)
        
        base, _ = os.path.splitext(file_path)
        new_path = base + "_nobg.png"
        
        output_image.save(new_path, "PNG")
        if file_path != new_path:
            try: os.remove(file_path)
            except: pass
        return new_path
    except Exception as e:
        print("Errore durante rembg:", e)
        return file_path

# ============================
# ROUTE: api_upload_image
# ============================
@app.route('/api/upload_image', methods=['POST'])
@login_required
def api_upload_image():
    if 'image' not in request.files:
        return jsonify({"status": "error", "message": "Nessun file inviato"}), 400
        
    file = request.files['image']
    if file.filename == '':
        return jsonify({"status": "error", "message": "Nessun file selezionato"}), 400
        
    if file:
        filename = werkzeug.utils.secure_filename(file.filename)
        import time
        unique_name = f"{int(time.time())}_{filename}"
        
        uploads_dir = os.path.join(app.static_folder, 'uploads', 'volantino_prodotti')
        os.makedirs(uploads_dir, exist_ok=True)
        
        file_path = os.path.join(uploads_dir, unique_name)
        file.save(file_path)
        
        # RIMUOVI SFONDO
        file_path = remove_bg_if_possible(file_path)
        unique_name = os.path.basename(file_path)
        
        file_url = url_for('static', filename=f'uploads/volantino_prodotti/{unique_name}')
        
        # Salviamo SOLO il nome file nel DB se inviato ID prodotto
        prodotto_id = request.form.get('prodotto_id')
        if prodotto_id:
            try:
                pid = int(prodotto_id)
                with get_db() as db:
                    cur = db.cursor()
                    cur.execute("UPDATE prodotti SET immagine=%s WHERE id=%s", (unique_name, pid))
                    db.commit()
            except ValueError:
                pass
                
        return jsonify({"status": "ok", "url": file_url})
        
    return jsonify({"status": "error", "message": "Errore caricamento"}), 500

# ============================
# ROUTE: api_cerca_immagini_prodotto
# ============================
@app.route('/api/cerca_immagini_prodotto', methods=['GET'])
@login_required
def api_cerca_immagini_prodotto():
    q = request.args.get('q', '')
    if not q:
        return jsonify({"status": "error", "message": "Nessuna query fornita"}), 400
    try:
        import requests, re, urllib.parse
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0"}
        url = f"https://www.bing.com/images/search?q={urllib.parse.quote(q)}"
        r = requests.get(url, headers=headers, timeout=5)
        urls = re.findall(r'murl&quot;:&quot;(.*?)&quot;', r.text)
        return jsonify({"status": "ok", "images": urls[:6]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ============================
# ROUTE: api_salva_immagine_suggerita
# ============================
@app.route('/api/salva_immagine_suggerita', methods=['POST'])
@login_required
def api_salva_immagine_suggerita():
    data = request.json
    pid = data.get('prodotto_id')
    image_url = data.get('image_url')
    if not image_url:
        return jsonify({"status": "error", "message": "Immagine mancante"}), 400
    
    try:
        import requests, time, os
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r = requests.get(image_url, headers=headers, timeout=10)
        r.raise_for_status()
        
        unique_name = f"{int(time.time())}_downloaded.jpg"
        uploads_dir = os.path.join(app.static_folder, 'uploads', 'volantino_prodotti')
        os.makedirs(uploads_dir, exist_ok=True)
        
        file_path = os.path.join(uploads_dir, unique_name)
        with open(file_path, 'wb') as f:
            f.write(r.content)
            
        # RIMUOVI SFONDO
        file_path = remove_bg_if_possible(file_path)
        unique_name = os.path.basename(file_path)
            
        if pid:
            with get_db() as db:
                cur = db.cursor()
                cur.execute("UPDATE prodotti SET immagine=%s WHERE id=%s", (unique_name, pid))
                db.commit()
            
        file_url = url_for('static', filename=f'uploads/volantino_prodotti/{unique_name}')
        return jsonify({"status": "ok", "url": file_url})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ============================
# ROUTE: api_salva_immagine_volantino_prodotto
# ============================
@app.route('/api/salva_immagine_volantino_prodotto', methods=['POST'])
@login_required
def api_salva_immagine_volantino_prodotto():
    data = request.json or {}
    codice = data.get('codice', '').strip()
    titolo = data.get('titolo', '').strip()
    image_src = data.get('image_src', '').strip()
    
    if not image_src:
        return jsonify({"status": "error", "message": "Nessuna immagine fornita"}), 400
    if not codice and not titolo:
        return jsonify({"status": "error", "message": "Codice o Titolo necessari per identificare il prodotto"}), 400
        
    try:
        import time
        import os
        import base64
        import requests
        
        unique_name = None
        uploads_dir = os.path.join(app.static_folder, 'uploads', 'volantino_prodotti')
        os.makedirs(uploads_dir, exist_ok=True)
        
        # 1. Se l'immagine è in Base64 (caricata localmente)
        if image_src.startswith('data:image/'):
            # Estraiamo il formato e i dati base64
            header, encoded = image_src.split(',', 1)
            fmt = header.split(';')[0].split('/')[1]
            if fmt == 'jpeg':
                fmt = 'jpg'
            
            unique_name = f"{int(time.time())}_uploaded.{fmt}"
            file_path = os.path.join(uploads_dir, unique_name)
            
            with open(file_path, 'wb') as f:
                f.write(base64.b64decode(encoded))
                
            # Rimuovi sfondo se possibile
            file_path = remove_bg_if_possible(file_path)
            unique_name = os.path.basename(file_path)
            
        # 2. Se l'immagine è già un URL locale
        elif '/static/uploads/volantino_prodotti/' in image_src:
            unique_name = image_src.split('/static/uploads/volantino_prodotti/')[-1]
            
        # 3. Se l'immagine è un URL remoto (es: bing, google, unsplash, ecc.)
        elif image_src.startswith('http://') or image_src.startswith('https://'):
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            r = requests.get(image_src, headers=headers, timeout=10)
            r.raise_for_status()
            
            # Determina formato
            fmt = 'jpg'
            if 'image/png' in r.headers.get('Content-Type', ''):
                fmt = 'png'
            elif 'image/webp' in r.headers.get('Content-Type', ''):
                fmt = 'webp'
                
            unique_name = f"{int(time.time())}_downloaded.{fmt}"
            file_path = os.path.join(uploads_dir, unique_name)
            
            with open(file_path, 'wb') as f:
                f.write(r.content)
                
            # Rimuovi sfondo se possibile
            file_path = remove_bg_if_possible(file_path)
            unique_name = os.path.basename(file_path)
            
        if unique_name:
            # Aggiorniamo il database prodotti
            with get_db() as db:
                cur = db.cursor()
                
                # Cerchiamo prima per codice (se fornito)
                updated = False
                if codice:
                    cur.execute("UPDATE prodotti SET immagine=%s WHERE codice=%s", (unique_name, codice))
                    if cur.rowcount > 0:
                        updated = True
                
                # Se non è stato aggiornato per codice (o il codice non c'era), proviamo per titolo/nome
                if not updated and titolo:
                    cur.execute("UPDATE prodotti SET immagine=%s WHERE LOWER(nome)=LOWER(%s)", (unique_name, titolo))
                    
                db.commit()
                
            file_url = url_for('static', filename=f'uploads/volantino_prodotti/{unique_name}')
            return jsonify({"status": "ok", "url": file_url, "filename": unique_name})
        else:
            return jsonify({"status": "error", "message": "Tipo di sorgente immagine non supportato"}), 400
            
    except Exception as e:
        print("Errore nel salvataggio dell'immagine sul DB:", e)
        return jsonify({"status": "error", "message": str(e)}), 500

# ============================
# ROUTE: api_importa_pdf_volantino
# ============================
@app.route('/api/importa-pdf-volantino', methods=['POST'])
@login_required
def api_importa_pdf_volantino():
    print("--- [PDF IMPORT] Endpoint triggered ---", flush=True)
    if 'pdf' not in request.files:
        print("--- [PDF IMPORT] Error: No 'pdf' key in request.files ---", flush=True)
        return jsonify({"status": "error", "message": "Nessun file inviato"}), 400
        
    file = request.files['pdf']
    print(f"--- [PDF IMPORT] Received file: {file.filename} ---", flush=True)
    if file.filename == '':
        print("--- [PDF IMPORT] Error: Empty filename ---", flush=True)
        return jsonify({"status": "error", "message": "Nessun file selezionato"}), 400
        
    import tempfile
    import pdfplumber
    import re
    import werkzeug.utils
    
    temp_dir = tempfile.gettempdir()
    temp_path = os.path.join(temp_dir, werkzeug.utils.secure_filename(file.filename))
    file.save(temp_path)
    
    products = []
    current_category = "FRESCO"
    
    regex = re.compile(r"^(\d{4,10})\s+(.+?)\s+([A-Za-z]{2,3})\s+(?:€\s*)?(\d+[\.,]\d{2})")
    
    try:
        with pdfplumber.open(temp_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text:
                    continue
                for line in text.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    
                    if line.isupper() and not any(c.isdigit() for c in line) and len(line) < 50:
                        words = line.split()
                        if len(words) <= 4 and not any(w in ["CODICE", "DESCRIZIONE", "UM", "PREZZO", "PAGINA", "PAG."] for w in words):
                            current_category = line
                            continue
                            
                    m = regex.match(line)
                    if m:
                        code, name, um, price_str = m.groups()
                        price_dot = price_str.replace(',', '.')
                        price_val = float(price_dot)
                        price_display = price_dot.replace('.', ',')
                        products.append({
                            "codice": code,
                            "nome": name.strip(),
                            "um": um.upper(),
                            "prezzo": price_val,
                            "prezzo_str": price_display,
                            "categoria": current_category
                        })
    except Exception as e:
        print(f"--- [PDF IMPORT] Error scanning PDF: {e} ---", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Errore scansione PDF: {str(e)}"}), 500
    finally:
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass

    print(f"--- [PDF IMPORT] Parsed {len(products)} products from PDF. Starting DB sync ---", flush=True)
    imported_products = []
    
    with get_db() as db:
        cur = db.cursor()
        
        # 1. Pre-fetch all categories to map name -> id
        cur.execute("SELECT id, nome FROM categorie")
        categories_map = {}
        for row in cur.fetchall():
            cat_id = row['id'] if isinstance(row, dict) else row[0]
            cat_nome = row['nome'] if isinstance(row, dict) else row[1]
            categories_map[cat_nome.upper()] = cat_id
            
        def get_or_create_category_optimized(cat_name):
            cat_upper = cat_name.upper()
            if cat_upper in categories_map:
                return categories_map[cat_upper]
            
            cur.execute("INSERT INTO categorie (nome) VALUES (%s) RETURNING id", (cat_name,))
            try:
                row = cur.fetchone()
                if row:
                    cat_id = row['id'] if isinstance(row, dict) else row[0]
                    categories_map[cat_upper] = cat_id
                    return cat_id
            except Exception:
                pass
            cur.execute("SELECT id FROM categorie WHERE nome = %s LIMIT 1", (cat_name,))
            row = cur.fetchone()
            cat_id = row['id'] if isinstance(row, dict) else row[0]
            categories_map[cat_upper] = cat_id
            return cat_id

        # Estrazione data scadenza dal nome del file (es: PROMO P0 D250 RM_01.06-30.06.2026.pdf)
        scadenza = None
        date_patterns = re.findall(r'(\d{2})[./-](\d{2})[./-](\d{4})', file.filename)
        if date_patterns:
            day, month, year = date_patterns[-1]
            scadenza = f"{day}/{month}/{year}"
        else:
            date_patterns_short = re.findall(r'(\d{2})[./-](\d{2})[./-](\d{2})', file.filename)
            if date_patterns_short:
                day, month, year = date_patterns_short[-1]
                scadenza = f"{day}/{month}/20{year}"
                
        if not scadenza:
            import datetime as dt
            today = dt.date.today()
            next_month = today.replace(day=28) + dt.timedelta(days=4)
            last_day = next_month - dt.timedelta(days=next_month.day)
            scadenza = last_day.strftime("%d/%m/%Y")

        # 2. Pre-fetch all products with columns to check if update is needed
        cur.execute("SELECT id, nome, codice, immagine, prezzo, prezzo_con_simbolo, is_promo_mensile, categoria_id, img_zoom, img_pos_x, img_pos_y FROM prodotti")
        products_by_code = {}
        products_by_name = {}
        for row in cur.fetchall():
            p_id = row['id'] if isinstance(row, dict) else row[0]
            p_nome = row['nome'] if isinstance(row, dict) else row[1]
            p_codice = row['codice'] if isinstance(row, dict) else row[2]
            p_immagine = row['immagine'] if isinstance(row, dict) else row[3]
            p_prezzo = row['prezzo'] if isinstance(row, dict) else row[4]
            p_prezzo_con_simbolo = row['prezzo_con_simbolo'] if isinstance(row, dict) else row[5]
            p_is_promo_mensile = row['is_promo_mensile'] if isinstance(row, dict) else row[6]
            p_categoria_id = row['categoria_id'] if isinstance(row, dict) else row[7]
            p_img_zoom = row['img_zoom'] if isinstance(row, dict) else row[8]
            p_img_pos_x = row['img_pos_x'] if isinstance(row, dict) else row[9]
            p_img_pos_y = row['img_pos_y'] if isinstance(row, dict) else row[10]
            
            is_promo_bool = True if (p_is_promo_mensile is True or p_is_promo_mensile == 1) else False
            
            p_info = {
                "id": p_id, 
                "nome": p_nome, 
                "codice": p_codice, 
                "immagine": p_immagine,
                "prezzo": p_prezzo,
                "prezzo_con_simbolo": p_prezzo_con_simbolo,
                "is_promo_mensile": is_promo_bool,
                "categoria_id": p_categoria_id,
                "img_zoom": p_img_zoom,
                "img_pos_x": p_img_pos_x,
                "img_pos_y": p_img_pos_y
            }
            if p_codice:
                products_by_code[p_codice] = p_info
            if p_nome:
                products_by_name[p_nome.upper()] = p_info

        # 3. Pre-fetch existing monthly promos
        cur.execute("SELECT id, prodotto_id, prezzo, scadenza FROM promozioni_pdf WHERE tipo IN ('mensile', 'promo_mensile')")
        promos_by_prod_id = {}
        for row in cur.fetchall():
            pr_id = row['id'] if isinstance(row, dict) else row[0]
            pr_prod_id = row['prodotto_id'] if isinstance(row, dict) else row[1]
            pr_prezzo = row['prezzo'] if isinstance(row, dict) else row[2]
            pr_scadenza = row['scadenza'] if isinstance(row, dict) else row[3]
            promos_by_prod_id[pr_prod_id] = {
                "id": pr_id,
                "prezzo": pr_prezzo,
                "scadenza": pr_scadenza
            }

        # Process all products
        for prod in products:
            code = prod["codice"]
            name = prod["nome"]
            price = prod["prezzo"]
            price_str = prod["prezzo_str"]
            um = prod["um"]
            cat_name = prod["categoria"]
            
            cat_id = get_or_create_category_optimized(cat_name)
            
            prod_id = None
            existing_img = ""
            
            # Cerca per codice
            if code in products_by_code:
                p_info = products_by_code[code]
                prod_id = p_info["id"]
                existing_img = p_info["immagine"] or ""
                
                # Check if UPDATE is actually needed
                needs_update = (
                    p_info["nome"] != name or
                    p_info["prezzo"] != price or
                    p_info["prezzo_con_simbolo"] != f"{price_str} *" or
                    p_info["is_promo_mensile"] is not True or
                    p_info["categoria_id"] != cat_id
                )
                if needs_update:
                    cur.execute("""
                        UPDATE prodotti 
                        SET nome = %s, prezzo = %s, prezzo_con_simbolo = %s, is_promo_mensile = %s, categoria_id = %s
                        WHERE id = %s
                    """, (name, price, f"{price_str} *", True, cat_id, prod_id))
            else:
                # Cerca per nome
                name_upper = name.upper()
                if name_upper in products_by_name:
                    p_info = products_by_name[name_upper]
                    prod_id = p_info["id"]
                    existing_img = p_info["immagine"] or ""
                    
                    needs_update = (
                        p_info["codice"] != code or
                        p_info["prezzo"] != price or
                        p_info["prezzo_con_simbolo"] != f"{price_str} *" or
                        p_info["is_promo_mensile"] is not True or
                        p_info["categoria_id"] != cat_id
                    )
                    if needs_update:
                        cur.execute("""
                            UPDATE prodotti 
                            SET codice = %s, prezzo = %s, prezzo_con_simbolo = %s, is_promo_mensile = %s, categoria_id = %s
                            WHERE id = %s
                        """, (code, price, f"{price_str} *", True, cat_id, prod_id))
                    
                    # Update local cache mapping for code
                    p_info["codice"] = code
                    products_by_code[code] = p_info
                else:
                    # Inserisci nuovo
                    cur.execute("""
                        INSERT INTO prodotti (codice, nome, prezzo, prezzo_con_simbolo, is_promo_mensile, categoria_id) 
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (code, name, price, f"{price_str} *", True, cat_id))
                    try:
                        prod_id = cur.lastrowid
                    except:
                        pass
                    if not prod_id:
                        cur.execute("SELECT id FROM prodotti WHERE codice = %s LIMIT 1", (code,))
                        row_new = cur.fetchone()
                        if row_new:
                            prod_id = row_new['id'] if isinstance(row_new, dict) else row_new[0]
                    
                    # Add to local cache mapping dynamically
                    p_info = {
                        "id": prod_id, 
                        "nome": name, 
                        "codice": code, 
                        "immagine": "",
                        "prezzo": price,
                        "prezzo_con_simbolo": f"{price_str} *",
                        "is_promo_mensile": True,
                        "categoria_id": cat_id
                    }
                    products_by_code[code] = p_info
                    products_by_name[name_upper] = p_info
            
            # Aggiorna promozioni_pdf
            if prod_id in promos_by_prod_id:
                promo_info = promos_by_prod_id[prod_id]
                new_prezzo = f"€ {price_str} *"
                if promo_info["prezzo"] != new_prezzo or promo_info["scadenza"] != scadenza:
                    cur.execute("""
                        UPDATE promozioni_pdf 
                        SET prezzo = %s, data_caricamento = %s, scadenza = %s
                        WHERE id = %s
                    """, (new_prezzo, datetime.utcnow(), scadenza, promo_info["id"]))
            else:
                cur.execute("""
                    INSERT INTO promozioni_pdf (prodotto_id, tipo, prezzo, data_caricamento, scadenza)
                    VALUES (%s, 'promo_mensile', %s, %s, %s)
                """, (prod_id, f"€ {price_str} *", datetime.utcnow(), scadenza))
                
            img_url = ""
            if existing_img:
                img_url = url_for('static', filename=f'uploads/volantino_prodotti/{existing_img}')
                
            img_zoom = p_info.get("img_zoom")
            img_pos_x = p_info.get("img_pos_x")
            img_pos_y = p_info.get("img_pos_y")
            
            imported_products.append({
                "id": prod_id,
                "codice": code,
                "nome": name,
                "prezzo": price_str,
                "um": um,
                "immagine": img_url,
                "categoria": cat_name,
                "imageZoom": str(img_zoom) if img_zoom is not None else "1.0",
                "imagePosX": str(img_pos_x) if img_pos_x is not None else "50",
                "imagePosY": str(img_pos_y) if img_pos_y is not None else "50"
            })
            
        db.commit()
        print(f"--- [PDF IMPORT] Successfully synced {len(imported_products)} products to database and committed ---", flush=True)

    return jsonify({
        "status": "ok",
        "message": f"Scansionati e sincronizzati {len(imported_products)} prodotti correttamente!",
        "products": imported_products
    })

# ----------------------------------------------------------------------
#  SALVA / AGGIORNA VOLANTINO  (con miniatura)
# ----------------------------------------------------------------------
@app.route('/salva-volantino-beta', methods=['POST'])
@login_required
def salva_volantino_beta():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"ok": False, "message": "Payload JSON mancante o troppo grande. Riprova."}), 400
            
        vol_id = data.get("id")
        nome = data.get("nome", "Volantino BETA")
        layout = data.get("layout")
        tipo = data.get("tipo", "volantino")
        thumbnail = data.get("thumbnail")   # base64 da html2canvas
        
        if not layout:
            return jsonify({"ok": False, "message": "Layout mancante nel payload."}), 400
            
        layout_json = json.dumps(layout)
        
        if vol_id:
            # Aggiorna esistente
            vol = VolantinoBeta.query.get(int(vol_id))
            if not vol:
                return jsonify({"ok": False, "message": f"Volantino #{vol_id} non trovato."}), 404
            vol.nome = nome
            vol.layout_json = layout_json
            vol.tipo = tipo
            if thumbnail:
                vol.thumbnail = thumbnail
            vol.aggiornato_il = datetime.utcnow()
        else:
            # Nuovo volantino
            vol = VolantinoBeta(
                nome=nome,
                layout_json=layout_json,
                thumbnail=thumbnail,
                tipo=tipo
            )
            db.session.add(vol)
            
        # Aggiorna lo zoom e le coordinate X/Y globali del prodotto nel database
        if isinstance(layout, list):
            try:
                with get_db() as conn:
                    cur = conn.cursor()
                    for page in layout:
                        for cell in page.get("cells", []):
                            code = cell.get("codice")
                            if code:
                                zoom = cell.get("imageZoom", "1.0")
                                pos_x = cell.get("imagePosX", "50")
                                pos_y = cell.get("imagePosY", "50")
                                try:
                                    zoom_val = float(zoom)
                                    pos_x_val = int(pos_x)
                                    pos_y_val = int(pos_y)
                                except Exception:
                                    zoom_val = 1.0
                                    pos_x_val = 50
                                    pos_y_val = 50
                                
                                cur.execute("""
                                    UPDATE prodotti 
                                    SET img_zoom = %s, img_pos_x = %s, img_pos_y = %s
                                    WHERE codice = %s
                                """, (zoom_val, pos_x_val, pos_y_val, code))
                    conn.commit()
            except Exception as dberr:
                print(f"Errore aggiornamento coordinate prodotti nel db di produzione: {dberr}")
            
        db.session.commit()
        return jsonify({"ok": True, "id": vol.id})
    except Exception as e:
        db.session.rollback()
        print(f"Errore salvataggio volantino beta: {e}")
        return jsonify({"ok": False, "message": f"Errore server: {str(e)}"}), 500

# ============================
# ROUTE: beta_volantino_modifica
# ============================
@app.route('/beta-volantino/<int:id>')
def beta_volantino_modifica(id):
    vol = VolantinoBeta.query.get_or_404(id)
    return render_template(
        '05_beta_volantino/05_beta_volantino.html',
        volantino_id=id,
        nome_volantino=vol.nome,
        layout_json=vol.layout_json,
        thumbnail=vol.thumbnail,
        tipo_volantino=vol.tipo
    )
# ----------------------------------------------------------------------
#  LISTA VOLANTINI
# ----------------------------------------------------------------------

# ============================
# ROUTE: beta_volantino_duplica
# ============================
@app.route('/beta-volantino/duplica/<int:id>')
def beta_volantino_duplica(id):
    vol = VolantinoBeta.query.get_or_404(id)
    nuovo = VolantinoBeta(
        nome=vol.nome + " (Copia)",
        layout_json=vol.layout_json,
        thumbnail=vol.thumbnail,
        tipo=vol.tipo
    )
    db.session.add(nuovo)
    db.session.commit()
    return redirect(url_for('beta_volantino_modifica', id=nuovo.id))
# ----------------------------------------------------------------------
#  ELIMINA VOLANTINO
# ----------------------------------------------------------------------

# ============================
# ROUTE: beta_volantino_elimina
# ============================
@app.route('/beta-volantino/elimina/<int:id>')
def beta_volantino_elimina(id):
    vol = VolantinoBeta.query.get_or_404(id)
    db.session.delete(vol)
    db.session.commit()
    return redirect(url_for('lista_volantini_beta'))
# =========================
# WhatsApp via TWILIO - BLOCCO COMPLETO (per il tuo app.py)
# - Riceve testo su /twilio/webhook (Twilio form-encoded)
# - Gestisce MENU preferenze e salva su DB
# - Admin da WhatsApp: STATS, SEND PESCE..., SEND CARNE..., SEND SCADENZA..., SEND TUTTI...
# - Invio mirato dal tuo pannello /bot (che già hai)
#
# ENV su Render:
#   TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM
#   ADMIN_WHATSAPP  (es: "3342380230,393342380230")
#
# NOTE:
# - Questo blocco usa *get_db()* (psycopg2) del tuo progetto.
# =========================
import os
from dotenv import load_dotenv
load_dotenv()
import re
import time
import traceback
from pathlib import Path
from collections import defaultdict
import pdfplumber
from flask import request
from psycopg2.extras import RealDictCursor
import requests
def _normalize_phone(s: str | None) -> str | None:
    if not s:
        return None
    s = str(s).strip()
    s = s.replace("whatsapp:", "").replace("+", "")
    s = s.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    s = "".join(ch for ch in s if ch.isdigit())
    if s.startswith("00"):
        s = s[2:]
    return s or None
# ------------------------------------------------------------
# 1) SEND TEXT (WhatsApp via META)
# ------------------------------------------------------------
def send_text(to: str, text: str):
    """
    to: numero in formato '39334xxxxxxx' (senza +)
    """
    to_norm = _normalize_phone(to)
    if not to_norm:
        print("⚠️ send_text: numero non valido:", to)
        return None
    token = os.getenv("META_WA_TOKEN")
    phone_id = os.getenv("META_WA_PHONE_NUMBER_ID")
    
    if not token or not phone_id:
        print("Errore: Credenziali Meta non impostate in .env")
        return None
    url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_norm,
        "type": "text",
        "text": {"body": text}
    }
    
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        r.raise_for_status()
        print("META SEND OK:", r.json())
        return r.json()
    except Exception as e:
        print("META SEND ERROR:", e)
        if hasattr(e, 'response') and e.response is not None:
            print("META ERROR BODY:", e.response.text)
        return None
# ------------------------------------------------------------
# 2A) PARSING PDF SCADENZE (2° col: codice, 3° col: nome, 4° col: data, ultima: prezzo)
# ------------------------------------------------------------
def parse_scadenze_from_pdf(pdf_path: str) -> list[dict]:
    offers = []
    
    date_re = re.compile(r'(\d{2}[-/. ]\d{2}[-/. ]\d{2,4})')
    code_re = re.compile(r'\b\d{4,10}\b')
    price_re = re.compile(r'((?:\d{1,3}[.,])*\d{1,3}[.,]\d{1,3})')
    
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            lines = text.splitlines()
            
            for raw in lines:
                row_text = " ".join(raw.strip().split())
                if not row_text:
                    continue
                
                date_matches = date_re.search(row_text)
                if date_matches:
                    scadenza = date_matches.group(1).replace(".", "/")
                    pre_date = row_text[:date_matches.start()].strip()
                    
                    cms = list(code_re.finditer(pre_date))
                    if cms:
                        cm = cms[-1]
                        codice = cm.group(0)
                        nome = pre_date[cm.end():].strip()
                        
                        post_date = row_text[date_matches.end():].strip()
                        p_matches = price_re.findall(post_date)
                        prezzo = p_matches[-1] if p_matches else ""
                        
                        offers.append({
                            "code": codice,
                            "name": nome,
                            "scadenza": scadenza,
                            "price": prezzo,
                            "raw": "[Scadenza]",
                            "page": page_idx
                        })
    return offers
# ------------------------------------------------------------
# 2) PARSING PDF
# ------------------------------------------------------------
# Utilizza la definizione unificata di parse_offers_from_pdf definita sopra.
# ------------------------------------------------------------
# 3) DB HELPERS (psycopg2)
# ------------------------------------------------------------
PHONE_COL_CACHE = {"value": None}
def _detect_phone_column(cur) -> str | None:
    if PHONE_COL_CACHE["value"] is not None:
        return PHONE_COL_CACHE["value"]
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public'
          AND table_name='clienti'
    """)
    cols = [r["column_name"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
    cols_l = [c.lower() for c in cols]
    candidates = [
        "telefono", "cellulare", "whatsapp", "numero", "tel",
        "phone", "mobile", "phone_number", "telefono_whatsapp"
    ]
    for cand in candidates:
        if cand in cols_l:
            PHONE_COL_CACHE["value"] = cols[cols_l.index(cand)]
            print("DEBUG - PHONE COLUMN DETECTED:", PHONE_COL_CACHE["value"])
            return PHONE_COL_CACHE["value"]
    PHONE_COL_CACHE["value"] = None
    print("⚠️ DEBUG - Nessuna colonna telefono trovata in 'clienti'. Colonne:", cols)
    return None
def product_id_by_code_pg(cur, code: str) -> int | None:
    cur.execute("SELECT id FROM prodotti WHERE codice = %s LIMIT 1", (code,))
    row = cur.fetchone()
    if row:
        return row["id"] if isinstance(row, dict) else row[0]
    cur.execute("SELECT id FROM prodotti WHERE codice ILIKE %s LIMIT 1", (f"%{code}%",))
    row = cur.fetchone()
    if row:
        return row["id"] if isinstance(row, dict) else row[0]
    return None
def customer_phones_for_product_pg(cur, prodotto_id: int) -> list[tuple[int, str]]:
    phone_col = _detect_phone_column(cur)
    if not phone_col:
        return []
    q = f"""
        SELECT c.id AS cliente_id, c.{phone_col} AS phone
        FROM clienti c
        JOIN clienti_prodotti cp ON cp.cliente_id = c.id
        WHERE cp.prodotto_id = %s
          AND (cp.lavorato IS TRUE OR cp.lavorato IS NULL)
        ORDER BY c.id
    """
    cur.execute(q, (prodotto_id,))
    rows = cur.fetchall() or []
    out = []
    for r in rows:
        cid = r["cliente_id"] if isinstance(r, dict) else r[0]
        phone = r["phone"] if isinstance(r, dict) else r[1]
        phone = _normalize_phone(phone) or ""
        if phone:
            out.append((cid, phone))
    return out
def build_customer_offer_map_pg(cur, offers: list[dict]) -> dict[int, dict]:
    items_by_customer = defaultdict(dict)
    phone_by_customer = {}
    for o in offers:
        pid = product_id_by_code_pg(cur, o["code"])
        if not pid:
            continue
        for cid, phone in customer_phones_for_product_pg(cur, pid):
            phone_by_customer[cid] = phone
            items_by_customer[cid][o["code"]] = o
    out = {}
    for cid, by_code in items_by_customer.items():
        items = list(by_code.values())
        items.sort(key=lambda x: x["code"])
        out[cid] = {"phone": phone_by_customer[cid], "items": items}
    return out
def format_customer_message(items: list[dict]) -> str:
    lines = ["📌 *Offerte per te oggi:*"]
    for o in items[:25]:
        lines.append(f"- *{o['code']}* {o['name']} → *€ {o['price']}*")
    if len(items) > 25:
        lines.append(f"\n(+{len(items)-25} altre)")
    lines.append("\nRispondi con il codice per ordinare 👍")
    return "\n".join(lines)
def send_offers_to_customers_pg(cur, offers: list[dict]) -> tuple[int, int]:
    customer_map = build_customer_offer_map_pg(cur, offers)
    sent = 0
    for _, payload in customer_map.items():
        phone = payload["phone"]
        text = format_customer_message(payload["items"])
        send_text(phone, text)
        sent += 1
    return sent, len(customer_map)
# ------------------------------------------------------------
# 4) ADMIN HELPERS
# ------------------------------------------------------------
def _normalize_phone_admin(s: str | None) -> str:
    s = (s or "").strip()
    s = s.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    s = "".join(ch for ch in s if ch.isdigit())
    if s.startswith("00"):
        s = s[2:]
    return s
def _admin_list() -> set[str]:
    raw = os.getenv("ADMIN_WHATSAPP", "")
    admins = set()
    for a in raw.split(","):
        a = _normalize_phone_admin(a)
        if a:
            admins.add(a)
            if len(a) == 10 and not a.startswith("39"):
                admins.add("39" + a)
    return admins
def is_admin(from_number: str | None) -> bool:
    n = _normalize_phone_admin(from_number)
    return n in _admin_list()
# ------------------------------------------------------------
# 5) PREFERENZE DB HELPERS (usati da Twilio webhook + /bot)
# ------------------------------------------------------------
def find_cliente_id_by_phone(cur, phone_norm: str) -> int | None:
    cur.execute("SELECT id FROM clienti WHERE telefono=%s LIMIT 1", (phone_norm,))
    row = cur.fetchone()
    return (row["id"] if isinstance(row, dict) else row[0]) if row else None
def upsert_preferenza(cur, cliente_id: int, scelta: str):
    """
    - PREF_SCADENZA / PREF_PESCE / PREF_CARNE: abilita flag e opt_out=FALSE
    - PREF_STOP: opt_out=TRUE e spegne tutto
    """
    if scelta == "PREF_STOP":
        cur.execute("""
            INSERT INTO whatsapp_preferenze (cliente_id, opt_out, updated_at)
            VALUES (%s, TRUE, NOW())
            ON CONFLICT (cliente_id) DO UPDATE
            SET opt_out=TRUE,
                ricevi_scadenza=FALSE,
                ricevi_pesce=FALSE,
                ricevi_carne=FALSE,
                updated_at=NOW()
        """, (cliente_id,))
        return
    col_map = {
        "PREF_SCADENZA": "ricevi_scadenza",
        "PREF_PESCE": "ricevi_pesce",
        "PREF_CARNE": "ricevi_carne",
    }
    col = col_map.get(scelta)
    if not col:
        return
    cur.execute(f"""
        INSERT INTO whatsapp_preferenze (cliente_id, {col}, opt_out, updated_at)
        VALUES (%s, TRUE, FALSE, NOW())
        ON CONFLICT (cliente_id) DO UPDATE
        SET {col}=TRUE,
            opt_out=FALSE,
            updated_at=NOW()
    """, (cliente_id,))
def mark_whatsapp_linked_by_phone(cur, phone_norm: str):
    try:
        cur.execute("""
            UPDATE clienti
            SET whatsapp_linked = TRUE,
                whatsapp_linked_at = COALESCE(whatsapp_linked_at, NOW())
            WHERE telefono = %s
        """, (phone_norm,))
    except Exception:
        pass
# ------------------------------------------------------------
# 6) SEGMENT WHERE (coerente con /bot)
# ------------------------------------------------------------
def _segment_where(pref: str) -> str:
    pref = (pref or "").lower()
    if pref == "scadenza":
        return "wp.opt_out = FALSE AND wp.ricevi_scadenza = TRUE"
    if pref == "pesce":
        return "wp.opt_out = FALSE AND wp.ricevi_pesce = TRUE"
    if pref == "carne":
        return "wp.opt_out = FALSE AND wp.ricevi_carne = TRUE"
    if pref == "stop":
        return "wp.opt_out = TRUE"
    if pref == "nessuna":
        return "wp.cliente_id IS NULL"
    return "c.whatsapp_linked = TRUE"
# ------------------------------------------------------------
# 7) WEBHOOK META WHATSAPP (testo + preferenze + admin)
# ------------------------------------------------------------

# ============================
# ROUTE: api_genera_promo_cliente
# ============================
@app.route('/api/genera_promo_cliente/<int:cliente_id>', methods=['POST'])
@login_required
def api_genera_promo_cliente(cliente_id):
    try:
        with get_db() as db:
            cur = db.cursor(cursor_factory=RealDictCursor)
            
            # Recuperiamo i prodotti in promo_mensile lavorati da questo cliente
            cur.execute("""
                SELECT p.id, p.nome, p.immagine, cp.prezzo_offerta, cp.prezzo_attuale
                FROM clienti_prodotti cp
                JOIN prodotti p ON p.id = cp.prodotto_id
                JOIN promozioni_pdf promo ON promo.prodotto_id = p.id
                WHERE cp.cliente_id = %s 
                  AND cp.lavorato = TRUE 
                  AND promo.tipo IN ('mensile', 'promo_mensile')
            """, (cliente_id,))
            prodotti_cliente = cur.fetchall()
            
            if not prodotti_cliente:
                return jsonify(success=False, message="Il cliente non lavora nessun prodotto dell'attuale promo mensile.")
            
            cur.execute("SELECT nome FROM clienti WHERE id = %s", (cliente_id,))
            cline = cur.fetchone()
            cliente_nome = cline['nome'] if cline else "Cliente"
            
            # Generazione layout a blocchi di 9 (3x3)
            doc_pages = []
            for i in range(0, len(prodotti_cliente), 9):
                chunk = prodotti_cliente[i:i+9]
                grid_cells = []
                cell_counter = 1
                for p in chunk:
                    img_path = ""
                    if p['immagine']:
                        if p['immagine'].startswith("http") or p['immagine'].startswith("/static/"):
                            img_path = p['immagine']
                        else:
                            img_path = f"/static/uploads/volantino_prodotti/{p['immagine']}"
                            
                    # Usa il prezzo offerta se c'è, altrimenti l'attuale
                    prezzo_val = p['prezzo_offerta'] if p['prezzo_offerta'] else p['prezzo_attuale']
                    prezzo_str = f"€ {prezzo_val}" if prezzo_val else ""
                    
                    grid_cells.append({
                        "id": f"cell_{cell_counter}", "colSpan": 1, "rowSpan": 1,
                        "isHidden": False, "productId": p['id'],
                        "name": p['nome'], "price": prezzo_str, "img": img_path,
                        "bgColor": "#ffffff", "nameColor": "#000000", "priceColor": "#e60000"
                    })
                    cell_counter += 1
                
                # Padding
                remainder = len(chunk) % 9
                if remainder != 0:
                    for _ in range(9 - remainder):
                        grid_cells.append({
                            "id": f"cell_{cell_counter}", "colSpan": 1, "rowSpan": 1,
                            "isHidden": False, "productId": None,
                            "name": "", "price": "", "img": "",
                            "bgColor": "#ffffff", "nameColor": "#000000", "priceColor": "#e60000"
                        })
                        cell_counter += 1
                # Leggiamo il template globale se esiste
                import json
                template_path = os.path.join(app.config["UPLOAD_FOLDER_PROMO"], f"promo_template_mensile.json")
                custom_global, custom_header, custom_bg = None, None, None
                if os.path.exists(template_path):
                    try:
                        with open(template_path, "r", encoding="utf-8") as f:
                            tdata = json.load(f)
                            custom_global = tdata.get("global")
                            custom_header = tdata.get("header")
                            custom_bg = tdata.get("background")
                            for c in grid_cells:
                                if custom_global:
                                    if custom_global.get("cellBgColor"): c["bgColor"] = custom_global["cellBgColor"]
                                    if custom_global.get("nameColor"): c["nameColor"] = custom_global["nameColor"]
                                    if custom_global.get("priceColor"): c["priceColor"] = custom_global["priceColor"]
                    except: pass
                
                header_data = custom_header or {
                    "logoSize": 160, "logoPos": "center", "titlePos": "center",
                    "title": f"Promo su Misura - {cliente_nome}",
                    "titleColor": "#0d6efd", "titleSize": 48, "logoUrl": ""
                }
                global_data = custom_global or {
                    "theme": "standard", "cols": 3, "width": 3200, "height": 4500,
                    "gridWidth": 1800, "rowHeight": 0, "gridGap": 15,
                    "paddingSides": 30, "paddingTop": 30, "paddingBottom": 30,
                    "border": True, "bgColor": "#ffffff", "nameSize": 1.0, "priceSize": 1.8
                }
                
                doc_pages.append({
                    "header": header_data, "global": global_data, "background": custom_bg, "grid": grid_cells
                })
                
            layout_json = {"isMultiPage": True, "pages": doc_pages}
            v_name = f"Promo {cliente_nome} - {datetime.today().strftime('%d/%m/%Y %H:%M')}"
            
            cur.execute("INSERT INTO volantino_beta (nome, layout_json, tipo) VALUES (%s, %s, %s) RETURNING id", 
                        (v_name, json.dumps(layout_json), "volantino_cliente"))
            new_vol_id = cur.fetchone()['id']
            db.commit()
            
        return jsonify(success=True, url=url_for('beta_volantino_modifica', id=new_vol_id))
    except Exception as e:
        print(f"Errore creazione volantino promo cliente: {e}")
        return jsonify(success=False, message=str(e))

# ============================
# ROUTE: salva_template_promo
# ============================
@app.route('/api/salva_template_promo', methods=['POST'])
@login_required
def salva_template_promo():
    data = request.json
    tipo = data.get("tipo", "")
    if not tipo.startswith("promo_"):
        return jsonify(success=False, message="Tipo non valido")
    
    tipo_base = tipo.replace("promo_", "")
    template_path = os.path.join(app.config["UPLOAD_FOLDER_PROMO"], f"promo_template_{tipo_base}.json")
    
    try:
        with open(template_path, "w", encoding="utf-8") as f:
            json.dump({
                "global": data.get("global", {}),
                "header": data.get("header", {}),
                "background": data.get("background")
            }, f)
        return jsonify(success=True)
    except Exception as e:
        print(f"Errore salvataggio template promo: {e}")
        return jsonify(success=False, message=str(e))

# ============================
# ROUTE: ping
# ============================
@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

# ============================
# ROUTE: api_visite_get_events
# ============================
@app.route('/api/visite/get_events')
@login_required
def api_visite_get_events():
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    
    if not start_str or not end_str:
        return jsonify([])
    # Converti stringhe in date (formato ISO: YYYY-MM-DD)
    try:
        start_date = datetime.fromisoformat(start_str.split('T')[0]).date()
        end_date = datetime.fromisoformat(end_str.split('T')[0]).date()
    except Exception:
        return jsonify([])
    
    events = []
    
    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)
        
        # 1. Recupero Visite reali (manuali o confermate)
        cur.execute('''
            SELECT v.id, v.cliente_id, v.data_visita, v.ora_visita, v.completata, v.note, c.nome as cliente_nome 
            FROM visite v 
            JOIN clienti c ON v.cliente_id = c.id 
            WHERE v.data_visita >= %s AND v.data_visita <= %s
        ''', (start_date, end_date))
        rows = cur.fetchall()
        
        # Mappa per evitare duplicati con le ricorrenti (chiave: cliente_id + data)
        real_occupied = set()
        
        for r in rows:
            color = '#10b981' if r['completata'] else '#3b82f6'
            start_dt = str(r['data_visita'])
            if r['ora_visita']:
                start_dt += 'T' + str(r['ora_visita'])
                
            events.append({
                'id': f"real_{r['id']}",
                'title': r['cliente_nome'],
                'start': start_dt,
                'backgroundColor': color,
                'borderColor': color,
                'extendedProps': {
                    'note': r['note'],
                    'completata': r['completata'],
                    'tipo': 'real',
                    'cliente_id': r['cliente_id']
                }
            })
            real_occupied.add((r['cliente_id'], r['data_visita']))
            
        # 2. Generazione Visite ricorrenti (virtuali)
        cur.execute('''
            SELECT id, nome, giorno_visita_standard, ora_visita_standard, frequenza_visita, data_registrazione 
            FROM clienti 
            WHERE giorno_visita_standard IS NOT NULL
        ''')
        clients = cur.fetchall()
        
        for c in clients:
            try:
                target_dow = int(c['giorno_visita_standard'])
            except (ValueError, TypeError):
                continue
            # Mapping dow: 0=Dom, 1=Lun ... 6=Sab (come da template)
            # Python weekday(): 0=Mon ... 6=Sun
            # Conversione a Python dow:
            python_dow = (target_dow - 1) % 7 if target_dow != 0 else 6
            
            curr = start_date
            while curr <= end_date:
                if curr.weekday() == python_dow:
                    # Verifica se c'è già una visita reale per questo cliente/giorno
                    if (c['id'], curr) in real_occupied:
                        curr += timedelta(days=1)
                        continue
                    # Verifica frequenza
                    show = True
                    if c['frequenza_visita'] == 'bisettimanale':
                        ref_date = c['data_registrazione'] or datetime(2026, 1, 1)
                        if hasattr(ref_date, 'date'):
                            ref_date = ref_date.date()
                        delta_weeks = (curr - ref_date).days // 7
                        if delta_weeks % 2 != 0:
                            show = False
                    
                    if show:
                        start_dt = str(curr)
                        if c['ora_visita_standard']:
                            # L'oggetto time in Postgres può essere formattato in stringa
                            ora_str = str(c['ora_visita_standard'])
                            if len(ora_str) == 5: ora_str += ":00" # Assicurati formato HH:MM:SS
                            start_dt += 'T' + ora_str
                        
                        events.append({
                            'id': f"virtual_{c['id']}_{curr}",
                            'title': f"🔄 {c['nome']}",
                            'start': start_dt,
                            'backgroundColor': '#0ea5e9', # Sky blue per virtuali
                            'borderColor': '#0284c7',
                            'editable': False, # Non spostabile se non crei visita reale
                            'extendedProps': {
                                'note': 'Passaggio programmato (automatico)',
                                'completata': False,
                                'tipo': 'virtual',
                                'cliente_id': c['id']
                            }
                        })
                curr += timedelta(days=1)
                
    return jsonify(events)

# ============================
# ROUTE: api_visite_toggle_complete
# ============================
@app.route('/api/visite/toggle_complete/<int:id>', methods=['POST'])
@login_required
def api_visite_toggle_complete(id):
    with get_db() as db:
        cur = db.cursor()
        cur.execute("UPDATE visite SET completata = NOT completata WHERE id = %s", (id,))
        db.commit()
    flash("Stato visita aggiornato.", "success")
    return redirect(url_for('visite_clienti'))

# ============================
# ROUTE: ical_visite
# ============================
@app.route('/ical/visite.ics')
def ical_visite():
    token = request.args.get('token')
    if token != 'HorecaCalendar':
         return "Accesso Negato", 403
    from datetime import datetime, timedelta
    calendar_str = "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Horeca//Gestionale//IT\nCALSCALE:GREGORIAN\nMETHOD:PUBLISH\nX-WR-CALNAME:Visite Horeca\nX-WR-TIMEZONE:Europe/Rome\n"
    
    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)
        
        # 1. Visite Reali
        cur.execute('''
            SELECT v.id, v.cliente_id, v.data_visita, v.ora_visita, v.completata, v.note, c.nome as cliente_nome 
            FROM visite v 
            JOIN clienti c ON v.cliente_id = c.id 
        ''')
        rows = cur.fetchall()
        
        exemptions = {}
        
        for r in rows:
            uid = f"real_{r['id']}@horeca"
            summary = f"Visita: {r['cliente_nome']}" + (" (Completata)" if r['completata'] else "")
            desc = r['note'] or ""
            dt_start = r['data_visita'].strftime("%Y%m%d")
            
            # Salva esenzione per le ricorsioni virtuali
            if r['cliente_id'] not in exemptions:
                exemptions[r['cliente_id']] = []
            exemptions[r['cliente_id']].append(dt_start)
            if r['ora_visita']:
                ora_str = str(r['ora_visita'])
                if len(ora_str) == 5: ora_str += ":00"
                dt_start += "T" + ora_str.replace(":", "")
                h_start = datetime.combine(r['data_visita'], datetime.strptime(ora_str, "%H:%M:%S").time())
                dt_end = (h_start + timedelta(hours=1)).strftime("%Y%m%dT%H%M%S")
                calendar_str += f"BEGIN:VEVENT\nUID:{uid}\nDTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}\nDTSTART:{dt_start}\nDTEND:{dt_end}\nSUMMARY:{summary}\nDESCRIPTION:{desc}\nEND:VEVENT\n"
            else:
                dt_end = (r['data_visita'] + timedelta(days=1)).strftime("%Y%m%d")
                calendar_str += f"BEGIN:VEVENT\nUID:{uid}\nDTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}\nDTSTART;VALUE=DATE:{dt_start}\nDTEND;VALUE=DATE:{dt_end}\nSUMMARY:{summary}\nDESCRIPTION:{desc}\nEND:VEVENT\n"
        # 2. Visite Virtuali (Ricorrenti)
        cur.execute('''
            SELECT id, nome, giorno_visita_standard, ora_visita_standard, frequenza_visita, data_registrazione 
            FROM clienti 
            WHERE giorno_visita_standard IS NOT NULL
        ''')
        clients = cur.fetchall()
        for c in clients:
            try:
                target_dow = int(c['giorno_visita_standard'])
            except:
                continue
               
            day_map = {1: 'MO', 2: 'TU', 3: 'WE', 4: 'TH', 5: 'FR', 6: 'SA', 0: 'SU'}
            byday = day_map.get(target_dow, 'MO')
            interval = 2 if c['frequenza_visita'] == 'bisettimanale' else 1
            
            uid = f"virtual_{c['id']}@horeca"
            summary = f"🔄 Visita Standard: {c['nome']}"
            desc = "Passaggio programmato automatico."
            
            py_dow = (target_dow - 1) % 7 if target_dow != 0 else 6
            start_ref = c['data_registrazione'] or datetime(2026, 1, 1)
            # data_registrazione è un datetime nel db o stringa? Facciamo fallback robusto.
            try:
                d_start = start_ref.date() if hasattr(start_ref, 'date') else start_ref
            except:
                d_start = datetime(2026, 1, 1).date()
            while d_start.weekday() != py_dow:
                d_start += timedelta(days=1)
                
            dt_start_str = d_start.strftime("%Y%m%d")
            
            ex_list = exemptions.get(c['id'], [])
            ex_str = ""
            if ex_list:
                ex_str = "EXDATE;VALUE=DATE:" + ",".join(ex_list) + "\n"
            if c['ora_visita_standard']:
                 ora_str = str(c['ora_visita_standard']).replace(":", "")[:4].ljust(4, '0') + "00"
                 dt_start_str += "T" + ora_str
                 calendar_str += f"BEGIN:VEVENT\nUID:{uid}\nDTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}\nDTSTART:{dt_start_str}\nDURATION:PT1H\nRRULE:FREQ=WEEKLY;INTERVAL={interval};BYDAY={byday}\n{ex_str}SUMMARY:{summary}\nDESCRIPTION:{desc}\nEND:VEVENT\n"
            else:
                 calendar_str += f"BEGIN:VEVENT\nUID:{uid}\nDTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}\nDTSTART;VALUE=DATE:{dt_start_str}\nRRULE:FREQ=WEEKLY;INTERVAL={interval};BYDAY={byday}\n{ex_str}SUMMARY:{summary}\nDESCRIPTION:{desc}\nEND:VEVENT\n"
    calendar_str += "END:VCALENDAR"
    from flask import make_response
    response = make_response(calendar_str)
    response.headers["Content-Type"] = "text/calendar; charset=utf-8"
    response.headers["Content-Disposition"] = "inline; filename=visite.ics"
    return response
# ============================
# AVVIO APP
# ============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)


