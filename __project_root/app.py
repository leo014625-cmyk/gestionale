import os
import json
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, jsonify
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from PIL import Image, ImageDraw
import psycopg2
from psycopg2.extras import RealDictCursor
from dateutil.relativedelta import relativedelta
from collections import defaultdict
from flask_sqlalchemy import SQLAlchemy
import threading
import requests
from requests.auth import HTTPBasicAuth




# ============================
# PATH STATIC E PLACEHOLDER
# ============================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "_templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")  # STATIC dentro il progetto

NO_IMAGE_PATH = os.path.join(STATIC_DIR, "no-image.png")

# Cartelle upload
UPLOAD_FOLDER_VOLANTINI = os.path.join(STATIC_DIR, "uploads", "volantini")
UPLOAD_FOLDER_VOLANTINI_PRODOTTI = os.path.join(STATIC_DIR, "uploads", "volantino_prodotti")
UPLOAD_FOLDER_PROMO = os.path.join(STATIC_DIR, "uploads", "promo")
UPLOAD_FOLDER_PROMOLAMPO = os.path.join(STATIC_DIR, "uploads", "promolampo")

# Creazione cartelle se non esistono
for folder in [
    UPLOAD_FOLDER_VOLANTINI,
    UPLOAD_FOLDER_VOLANTINI_PRODOTTI,
    UPLOAD_FOLDER_PROMO,
    UPLOAD_FOLDER_PROMOLAMPO,
]:
    os.makedirs(folder, exist_ok=True)

# 🔹 Crea immagine placeholder se non esiste
if not os.path.exists(NO_IMAGE_PATH):
    img = Image.new("RGB", (100, 100), color=(220, 220, 220))
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

# ----------------------------------------------------------------------
# CONFIG DATABASE (Render + Local)
# ----------------------------------------------------------------------

# Compatibilità: Render usa DATABASE_URL ma SQLAlchemy vuole postgres:// → postgresql://
db_url = os.environ.get("DATABASE_URL", "")

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url or "sqlite:///local.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
# CREA LE TABELLE SE NON ESISTONO (Render + locale)
with app.app_context():
    db.create_all()


# Config upload
app.config["UPLOAD_FOLDER_VOLANTINI"] = UPLOAD_FOLDER_VOLANTINI
app.config["UPLOAD_FOLDER_VOLANTINI_PRODOTTI"] = UPLOAD_FOLDER_VOLANTINI_PRODOTTI
app.config["UPLOAD_FOLDER_PROMO"] = UPLOAD_FOLDER_PROMO
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # limite upload 16MB


# Secret key per session
app.secret_key = 'la_tua_chiave_segreta_sicura'

# -------------------------------
# MODELLO
# -------------------------------
class VolantinoBeta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), nullable=False)
    layout_json = db.Column(db.Text, nullable=False)
    thumbnail = db.Column(db.Text)
    creato_il = db.Column(db.DateTime, default=datetime.utcnow)
    aggiornato_il = db.Column(db.DateTime)

# ============================
# UPLOAD CATEGORIE
# ============================
CATEGORIE_UPLOAD_FOLDER = os.path.join(STATIC_DIR, 'uploads', 'categorie')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
os.makedirs(CATEGORIE_UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

UPLOAD_FOLDER_PROMO = os.path.join(STATIC_DIR, "promo_lampo")
os.makedirs(UPLOAD_FOLDER_PROMO, exist_ok=True)

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

def get_db_connection():
    """
    Restituisce una connessione al database PostgreSQL.
    Usa RealDictCursor per ottenere risultati come dizionari (simile a sqlite3.Row)
    """
    if not DATABASE_URL:
        raise ValueError("❌ Variabile d'ambiente DATABASE_URL non settata")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def get_db():
    """
    Restituisce una connessione per l'uso nelle query.
    """
    return get_db_connection()

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
    with get_db() as db:
        cur = db.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS zone (
                id SERIAL PRIMARY KEY,
                nome TEXT NOT NULL UNIQUE
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS categorie (
                id SERIAL PRIMARY KEY,
                nome TEXT NOT NULL UNIQUE
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS prodotti (
                id SERIAL PRIMARY KEY,
                nome TEXT NOT NULL,
                categoria_id INTEGER REFERENCES categorie(id)
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS clienti (
                id SERIAL PRIMARY KEY,
                nome TEXT NOT NULL,
                zona TEXT NOT NULL,
                fatturato_totale REAL DEFAULT 0,
                data_registrazione TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS fatturato (
                id SERIAL PRIMARY KEY,
                cliente_id INTEGER NOT NULL REFERENCES clienti(id),
                prodotto_id INTEGER REFERENCES prodotti(id),
                quantita INTEGER NOT NULL DEFAULT 0,
                mese INTEGER NOT NULL,
                anno INTEGER NOT NULL,
                totale REAL NOT NULL
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS clienti_prodotti (
                cliente_id INTEGER NOT NULL REFERENCES clienti(id) ON DELETE CASCADE,
                prodotto_id INTEGER NOT NULL REFERENCES prodotti(id) ON DELETE CASCADE,
                PRIMARY KEY (cliente_id, prodotto_id)
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS prodotti_rimossi (
                id SERIAL PRIMARY KEY,
                prodotto_id INTEGER NOT NULL REFERENCES prodotti(id),
                data_rimozione TIMESTAMP NOT NULL
            )
        ''')
        db.commit()

def aggiorna_fatturato_totale(id):
    with get_db() as db:
        cur = db.cursor()
        cur.execute('''
            UPDATE clienti SET fatturato_totale = (
                SELECT COALESCE(SUM(totale), 0) FROM fatturato WHERE cliente_id = %s
            ) WHERE id = %s
        ''', (id, id))
        db.commit()

@app.route('/')
@login_required
def index():

    with get_db() as db:
        cur = db.cursor()

        oggi = datetime.now()
        oggi_data = oggi.date()
        trenta_giorni_fa = oggi - timedelta(days=30)

        # === Calcolo mesi fatturato ===
        ultimo_mese_completo = oggi.replace(day=1) - relativedelta(days=1)
        mese_corrente = ultimo_mese_completo.month
        anno_corrente = ultimo_mese_completo.year

        mese_prec_dt = ultimo_mese_completo - relativedelta(months=1)
        mese_prec = mese_prec_dt.month
        anno_prec = mese_prec_dt.year

        # === Fatturato mese corrente ===
        cur.execute(
            "SELECT COALESCE(SUM(totale),0) AS totale FROM fatturato WHERE mese=%s AND anno=%s",
            (mese_corrente, anno_corrente)
        )
        fatturato_corrente = cur.fetchone()['totale']

        # === Fatturato mese precedente ===
        cur.execute(
            "SELECT COALESCE(SUM(totale),0) AS totale FROM fatturato WHERE mese=%s AND anno=%s",
            (mese_prec, anno_prec)
        )
        fatturato_precedente = cur.fetchone()['totale']

        variazione_fatturato = None
        if fatturato_precedente != 0:
            variazione_fatturato = ((fatturato_corrente - fatturato_precedente) / fatturato_precedente) * 100

        # ======================================================================================
        # === CLIENTI NUOVI (ULTIMI 30 GIORNI)
        # ======================================================================================
        cur.execute("""
            SELECT id, nome, zona, data_registrazione
            FROM clienti
            WHERE data_registrazione >= %s
        """, (trenta_giorni_fa,))
        clienti_nuovi_rows = cur.fetchall()

        clienti_nuovi_dettaglio = [
            {
                "id": c["id"],
                "nome": c["nome"],
                "data_registrazione": c["data_registrazione"]
            }
            for c in clienti_nuovi_rows
        ]
        clienti_nuovi = len(clienti_nuovi_rows)

        # ======================================================================================
        # === CLIENTI ATTIVI / BLOCCATI / INATTIVI
        # ======================================================================================
        cur.execute("SELECT id, nome FROM clienti ORDER BY nome")
        clienti_rows = cur.fetchall()

        clienti_attivi_dettaglio = []
        clienti_bloccati_dettaglio = []
        clienti_inattivi_dettaglio = []

        for cliente in clienti_rows:

            cur.execute("""
                SELECT MAX(make_date(anno, mese, 1)) AS ultimo_fatturato
                FROM fatturato
                WHERE cliente_id = %s
            """, (cliente["id"],))

            ultimo = cur.fetchone()["ultimo_fatturato"]

            if ultimo:
                giorni = (oggi_data - ultimo).days
            else:
                giorni = 9999   # se non ha fatturato: inattivo vecchissimo
                ultimo = None

            # Logica stato
            if giorni <= 60:
                stato = "attivo"
            elif 61 <= giorni <= 91:
                stato = "bloccato"
            else:
                stato = "inattivo"

            info = {
                "id": cliente["id"],
                "nome": cliente["nome"],
                "ultimo_fatturato": ultimo,
                "giorni": giorni
            }

            if stato == "attivo":
                clienti_attivi_dettaglio.append(info)
            elif stato == "bloccato":
                clienti_bloccati_dettaglio.append(info)
            else:
                clienti_inattivi_dettaglio.append(info)

        # ======================================================================================
        # === PRODOTTI INSERITI (30 giorni)
        # ======================================================================================
        cur.execute("""
            SELECT 
                c.nome AS cliente, 
                p.nome AS prodotto,
                cp.data_operazione
            FROM clienti_prodotti cp
            JOIN clienti c ON cp.cliente_id = c.id
            JOIN prodotti p ON cp.prodotto_id = p.id
            WHERE cp.lavorato = TRUE
              AND cp.data_operazione >= %s
        """, (trenta_giorni_fa,))
        prodotti_inseriti_rows = cur.fetchall()

        prodotti_inseriti = [
            {
                "cliente": r["cliente"],
                "prodotto": r["prodotto"],
                "data_operazione": r["data_operazione"]
            }
            for r in prodotti_inseriti_rows
        ]

        # ======================================================================================
        # === PRODOTTI RIMOSSI (30 giorni)
        # ======================================================================================
        cur.execute("""
            SELECT 
                c.nome AS cliente,
                p.nome AS prodotto,
                pr.data_rimozione
            FROM prodotti_rimossi pr
            JOIN prodotti p ON pr.prodotto_id = p.id
            JOIN clienti c ON pr.cliente_id = c.id
            WHERE pr.data_rimozione >= %s
        """, (trenta_giorni_fa,))
        prodotti_rimossi_rows = cur.fetchall()

        prodotti_rimossi = [
            {
                "cliente": r["cliente"],
                "prodotto": r["prodotto"],
                "data_operazione": r["data_rimozione"]
            }
            for r in prodotti_rimossi_rows
        ]

        # ======================================================================================
        # === FATTURATO 12 MESI
        # ======================================================================================
        cur.execute("""
            SELECT anno, mese, COALESCE(SUM(totale),0) as totale
            FROM fatturato
            GROUP BY anno, mese
            ORDER BY anno DESC, mese DESC
            LIMIT 12
        """)
        fatturato_mensile_rows = cur.fetchall()

        fatturato_mensile = {
            f"{r['anno']}-{r['mese']:02}": r["totale"]
            for r in reversed(fatturato_mensile_rows)
        }

        # ======================================================================================
        # === FATTURATO PER ZONA
        # ======================================================================================
        cur.execute("""
            SELECT 
                COALESCE(c.zona, 'Sconosciuta') AS zona,
                COALESCE(SUM(f.totale),0) AS totale
            FROM fatturato f
            JOIN clienti c ON f.cliente_id = c.id
            GROUP BY c.zona
            ORDER BY zona
        """)
        fatturato_per_zona_rows = cur.fetchall()

        fatturato_per_zona = {r["zona"]: r["totale"] for r in fatturato_per_zona_rows}

        # ======================================================================================
        # === NOTIFICHE
        # ======================================================================================
        notifiche = []

        if clienti_attivi_dettaglio:
            notifiche.append({
                "titolo": "Aggiorna Fatturato",
                "descrizione": "Ricorda di aggiornare il fatturato dei clienti attivi.",
                "data": datetime.now(),
                "tipo": "warning",
                "clienti_attivi": clienti_attivi_dettaglio
            })

        if clienti_inattivi_dettaglio:
            notifiche.append({
                "titolo": "Clienti Inattivi",
                "descrizione": "Verifica eventuali aggiornamenti.",
                "data": datetime.now(),
                "tipo": "secondary",
                "clienti": clienti_inattivi_dettaglio
            })

    # ----------------------------------------------
    # RENDER TEMPLATE
    # ----------------------------------------------
    return render_template(
        "02_index.html",
        variazione_fatturato=variazione_fatturato,

        clienti_nuovi=clienti_nuovi,
        clienti_nuovi_dettaglio=clienti_nuovi_dettaglio,

        clienti_bloccati=clienti_bloccati_dettaglio,
        clienti_bloccati_dettaglio=clienti_bloccati_dettaglio,

        clienti_attivi_dettaglio=clienti_attivi_dettaglio,
        clienti_inattivi=clienti_inattivi_dettaglio,

        prodotti_inseriti=prodotti_inseriti,
        prodotti_rimossi=prodotti_rimossi,

        fatturato_mensile=fatturato_mensile,
        fatturato_per_zona=fatturato_per_zona,

        notifiche=notifiche
    )

from collections import defaultdict
from datetime import datetime

# ============================
# ROUTE CLIENTI
# ============================
@app.route('/clienti')
@login_required
def clienti():
    zona_filtro = request.args.get('zona')
    stato_filtro = request.args.get('stato')   # filtro stato
    order = request.args.get('order', 'zona')
    search = request.args.get('search', '').strip().lower()

    oggi = datetime.today()
    current_month = oggi.month
    current_year = oggi.year

    # Mese appena concluso
    mese_ref = current_month - 1 if current_month > 1 else 12
    anno_ref = current_year if current_month > 1 else current_year - 1

    # Mese precedente a quello concluso
    mese_ref_prev = mese_ref - 1 if mese_ref > 1 else 12
    anno_ref_prev = anno_ref if mese_ref > 1 else anno_ref - 1

    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)

        # ----------------------------------------------------
        # Query unica: clienti + aggregati fatturato
        # ----------------------------------------------------
        query = '''
            SELECT
                c.id,
                c.nome,
                c.zona,

                COALESCE(SUM(f.totale), 0) AS fatturato_totale,
                MAX(make_date(f.anno, f.mese, 1)) AS ultimo_fatturato,

                COALESCE(SUM(CASE WHEN f.mese = %s AND f.anno = %s THEN f.totale ELSE 0 END), 0) AS fatt_ref,
                COALESCE(SUM(CASE WHEN f.mese = %s AND f.anno = %s THEN f.totale ELSE 0 END), 0) AS fatt_prev

            FROM clienti c
            LEFT JOIN fatturato f ON f.cliente_id = c.id
        '''

        condizioni = []
        params = [mese_ref, anno_ref, mese_ref_prev, anno_ref_prev]

        if zona_filtro:
            condizioni.append('c.zona = %s')
            params.append(zona_filtro)

        if search:
            condizioni.append('LOWER(c.nome) LIKE %s')
            params.append(f'%{search}%')

        if condizioni:
            query += ' WHERE ' + ' AND '.join(condizioni)

        query += '''
            GROUP BY c.id, c.nome, c.zona
        '''

        # ordinamento base (poi rifiniamo in Python come prima)
        query += ' ORDER BY c.nome'

        cur.execute(query, params)
        rows = cur.fetchall()

        clienti_list = []
        stati_clienti = {}
        andamento_clienti = {}

        for r in rows:
            ultimo = r['ultimo_fatturato']

            # Stato cliente in base all'ultimo fatturato
            if ultimo:
                giorni_trascorsi = (oggi.date() - ultimo).days
                if giorni_trascorsi <= 60:
                    stato = 'attivo'
                elif 61 <= giorni_trascorsi <= 91:
                    stato = 'bloccato'
                else:
                    stato = 'inattivo'
            else:
                stato = 'inattivo'

            stati_clienti[r['id']] = stato

            # filtro stato cliente
            if stato_filtro and stato != stato_filtro:
                continue

            # andamento
            fatt_ref = float(r['fatt_ref'] or 0)
            fatt_prev = float(r['fatt_prev'] or 0)

            if fatt_prev > 0:
                andamento = round(((fatt_ref - fatt_prev) / fatt_prev) * 100)
            else:
                andamento = None

            andamento_clienti[r['id']] = andamento

            clienti_list.append({
                'id': r['id'],
                'nome': r['nome'],
                'zona': r['zona'],
                'fatturato_totale': float(r['fatturato_totale'] or 0),
                'ultimo_fatturato': ultimo
            })

        # Ordinamento come prima
        if order == 'fatturato':
            clienti_list.sort(key=lambda c: c['fatturato_totale'], reverse=True)
        else:
            clienti_list.sort(key=lambda c: (c['zona'] or '', c['nome']))

        # Raggruppamento per zona
        clienti_per_zona = defaultdict(list)
        for c in clienti_list:
            clienti_per_zona[c['zona']].append(c)

        # Recupero zone per select filtro
        cur.execute('SELECT DISTINCT zona FROM clienti')
        zone = cur.fetchall()
        zone_lista = sorted([z['zona'] for z in zone if z['zona']])

    return render_template(
        '01_clienti/01_clienti.html',
        clienti_per_zona=clienti_per_zona,
        zone=zone_lista,
        zona_filtro=zona_filtro,
        order=order,
        search=search,
        stati_clienti=stati_clienti,
        andamento_clienti=andamento_clienti,
        stato_filtro=stato_filtro
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
        cur.execute('SELECT p.id, p.nome, p.categoria_id FROM prodotti p ORDER BY p.nome')
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

            now = datetime.now()
            cur.execute('INSERT INTO clienti (nome, zona, data_registrazione) VALUES (%s,%s,%s) RETURNING id',
                        (nome, zona, now))
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

from decimal import Decimal, InvalidOperation
import json
from datetime import datetime

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
    """
    Converte input tipo '9,90', '€ 9.90', '' in Decimal o None.
    """
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    s = s.replace("€", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


# --- FUNZIONE PRINCIPALE MODIFICA CLIENTE ---
@app.route('/clienti/modifica/<int:id>', methods=['GET', 'POST'])
@login_required
def modifica_cliente(id):
    current_datetime = datetime.now()

    def normalize_phone(s: str | None) -> str | None:
        """
        Normalizza numero telefono:
        - toglie spazi, +, -, parentesi
        - lascia solo cifre
        """
        if not s:
            return None
        s = str(s).strip()
        if not s:
            return None
        s = s.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        s = "".join(ch for ch in s if ch.isdigit())
        return s or None

    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)

        # ============================
        # CLIENTE
        # ============================
        cur.execute('SELECT * FROM clienti WHERE id=%s', (id,))
        cliente = cur.fetchone()
        if not cliente:
            flash('Cliente non trovato.', 'danger')
            return redirect(url_for('clienti'))

        # ============================
        # ZONE
        # ============================
        cur.execute('SELECT * FROM zone ORDER BY nome')
        zone = cur.fetchall()

        # ============================
        # CATEGORIE
        # ============================
        cur.execute('SELECT * FROM categorie ORDER BY nome')
        categorie = cur.fetchall()

        # ============================
        # PRODOTTI
        # ============================
        cur.execute('''
            SELECT p.id, p.nome, p.categoria_id, c.nome AS categoria_nome
            FROM prodotti p
            LEFT JOIN categorie c ON p.categoria_id = c.id
            ORDER BY c.nome, p.nome
        ''')
        prodotti = cur.fetchall()

        # ============================
        # PRODOTTI ASSOCIATI
        # ============================
        cur.execute('''
            SELECT prodotto_id, lavorato, prezzo_attuale, prezzo_offerta, fornitori.nome AS fornitore
            FROM clienti_prodotti cp
            LEFT JOIN fornitori ON cp.fornitore_id = fornitori.id
            WHERE cliente_id=%s
        ''', (id,))
        prodotti_assoc = cur.fetchall()

        prodotti_lavorati = []
        prezzi_attuali = {}
        prezzi_offerta = {}
        fornitori = {}

        for p in prodotti_assoc:
            pid = str(p["prodotto_id"])
            if p["lavorato"]:
                prodotti_lavorati.append(pid)
            prezzi_attuali[pid] = p["prezzo_attuale"]
            prezzi_offerta[pid] = p["prezzo_offerta"]
            fornitori[pid] = p["fornitore"] or ""

        # ============================
        # FATTURATI (per tabella storico)
        # ============================
        cur.execute('''
            SELECT id, mese, anno, totale AS importo
            FROM fatturato
            WHERE cliente_id=%s
            ORDER BY anno DESC, mese DESC
        ''', (id,))
        fatturati_cliente = cur.fetchall()

        # ============================
        # POST
        # ============================
        if request.method == 'POST':

            nome = (request.form.get('nome') or '').strip()
            zona = request.form.get('zona')
            nuova_zona = (request.form.get('nuova_zona') or '').strip()

            # ✅ NUOVO: telefono cliente
            telefono_raw = request.form.get("telefono")
            telefono = normalize_phone(telefono_raw)

            # Validazione leggera
            if telefono and (len(telefono) < 8 or len(telefono) > 15):
                flash("⚠️ Telefono non valido (controlla lunghezza).", "warning")
                telefono = None

            # nuova zona
            if zona == 'nuova_zona' and nuova_zona:
                zona = nuova_zona
                try:
                    cur.execute('INSERT INTO zone (nome) VALUES (%s)', (zona,))
                except Exception:
                    pass

            # ✅ LOGICA WHATSAPP COLLEGATO:
            # - se telefono valido -> collegato TRUE e timestamp
            # - se telefono vuoto/None -> collegato FALSE e timestamp NULL
            old_tel = normalize_phone(cliente.get("telefono"))
            old_linked = bool(cliente.get("whatsapp_collegato") or False)

            new_linked = True if telefono else False

            # aggiorna timestamp solo quando "passa a collegato" oppure cambia numero
            set_linked_at = None
            clear_linked_at = False

            if new_linked:
                if (not old_linked) or (old_tel != telefono):
                    set_linked_at = current_datetime
            else:
                clear_linked_at = True

            # ✅ UPDATE CLIENTE con telefono + flag whatsapp
            if new_linked:
                if set_linked_at is not None:
                    cur.execute(
                        """
                        UPDATE clienti
                        SET nome=%s, zona=%s, telefono=%s,
                            whatsapp_collegato=TRUE,
                            whatsapp_collegato_il=%s
                        WHERE id=%s
                        """,
                        (nome, zona, telefono, set_linked_at, id)
                    )
                else:
                    # già collegato e numero uguale: non tocco whatsapp_collegato_il
                    cur.execute(
                        """
                        UPDATE clienti
                        SET nome=%s, zona=%s, telefono=%s,
                            whatsapp_collegato=TRUE
                        WHERE id=%s
                        """,
                        (nome, zona, telefono, id)
                    )
            else:
                # telefono mancante -> discollego
                cur.execute(
                    """
                    UPDATE clienti
                    SET nome=%s, zona=%s, telefono=%s,
                        whatsapp_collegato=FALSE,
                        whatsapp_collegato_il=NULL
                    WHERE id=%s
                    """,
                    (nome, zona, None, id)
                )

            # ---------------------------
            # PRODOTTI LAVORATI
            # ---------------------------
            selezionati = set(request.form.getlist("prodotti_lavorati[]"))

            for prodotto in prodotti:
                pid = str(prodotto["id"])
                lavorato = pid in selezionati

                prezzo_attuale_raw = request.form.get(f"prezzo_attuale[{pid}]")
                prezzo_offerta_raw = request.form.get(f"prezzo_offerta[{pid}]")
                fornitore_nome = (request.form.get(f"fornitore[{pid}]") or "").strip() or None

                prezzo_attuale = parse_decimal(prezzo_attuale_raw)
                prezzo_offerta = parse_decimal(prezzo_offerta_raw)

                # --- gestisci fornitore ---
                fornitore_id = None
                if fornitore_nome:
                    cur.execute("SELECT id FROM fornitori WHERE nome=%s", (fornitore_nome,))
                    f = cur.fetchone()
                    if f:
                        fornitore_id = f["id"]
                    else:
                        cur.execute("INSERT INTO fornitori (nome) VALUES (%s) RETURNING id", (fornitore_nome,))
                        fornitore_id = cur.fetchone()["id"]

                # --- esiste già? ---
                cur.execute('''
                    SELECT id FROM clienti_prodotti
                    WHERE cliente_id=%s AND prodotto_id=%s
                ''', (id, pid))
                esiste = cur.fetchone()

                if esiste:
                    cur.execute('''
                        UPDATE clienti_prodotti
                        SET lavorato=%s,
                            prezzo_attuale=%s,
                            prezzo_offerta=%s,
                            fornitore_id=%s,
                            data_operazione=%s
                        WHERE cliente_id=%s AND prodotto_id=%s
                    ''', (lavorato, prezzo_attuale, prezzo_offerta, fornitore_id,
                          current_datetime, id, pid))
                else:
                    cur.execute('''
                        INSERT INTO clienti_prodotti
                        (cliente_id, prodotto_id, lavorato, prezzo_attuale, prezzo_offerta, fornitore_id, data_operazione)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ''', (id, pid, lavorato, prezzo_attuale, prezzo_offerta, fornitore_id, current_datetime))

            # ---------------------------
            # FATTURATO (PRIORITÀ: storico tabella)
            # (tuo blocco invariato)
            # ---------------------------
            salvato_storico = False
            use_storico = (request.form.get("fatturato_use_storico") == "1")

            mesi_list = request.form.getlist("fatt_mese[]")
            anni_list = request.form.getlist("fatt_anno[]")
            importi_list = request.form.getlist("fatt_importo[]")

            if mesi_list or anni_list or importi_list:
                try:
                    righe = []
                    n = max(len(mesi_list), len(anni_list), len(importi_list))
                    for i in range(n):
                        m = mesi_list[i] if i < len(mesi_list) else None
                        a = anni_list[i] if i < len(anni_list) else None
                        imp = importi_list[i] if i < len(importi_list) else None

                        mese_i = parse_int(m)
                        anno_i = parse_int(a)
                        imp_d = parse_decimal(imp)

                        if mese_i and anno_i:
                            righe.append((mese_i, anno_i, imp_d))

                    cur.execute('''
                        SELECT DISTINCT mese, anno
                        FROM fatturato
                        WHERE cliente_id=%s
                    ''', (id,))
                    existing = {(row["mese"], row["anno"]) for row in cur.fetchall()}
                    incoming = {(m, a) for (m, a, _) in righe}

                    if use_storico and not righe:
                        cur.execute('DELETE FROM fatturato WHERE cliente_id=%s', (id,))
                        salvato_storico = True
                    else:
                        to_delete = existing - incoming
                        for (m, a) in to_delete:
                            cur.execute(
                                'DELETE FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                                (id, m, a)
                            )

                        for (m, a, imp) in righe:
                            cur.execute(
                                'DELETE FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                                (id, m, a)
                            )
                            cur.execute('''
                                INSERT INTO fatturato (cliente_id, mese, anno, totale)
                                VALUES (%s,%s,%s,%s)
                            ''', (id, m, a, imp))

                        salvato_storico = True

                except Exception as e:
                    flash(f"Errore storico fatturato (campi): {e}", "warning")
                    salvato_storico = False

            if not salvato_storico:
                fatt_json = (request.form.get("fatturato_storico_json") or "").strip()
                if fatt_json:
                    try:
                        righe = json.loads(fatt_json)
                        cleaned = []
                        if isinstance(righe, list):
                            for r in righe:
                                mese = parse_int(r.get("mese"))
                                anno = parse_int(r.get("anno"))
                                importo = parse_decimal(r.get("importo"))
                                if mese and anno:
                                    cleaned.append((mese, anno, importo))

                        cur.execute('''
                            SELECT DISTINCT mese, anno
                            FROM fatturato
                            WHERE cliente_id=%s
                        ''', (id,))
                        existing = {(row["mese"], row["anno"]) for row in cur.fetchall()}
                        incoming = {(m, a) for (m, a, _) in cleaned}

                        if use_storico and not cleaned:
                            cur.execute('DELETE FROM fatturato WHERE cliente_id=%s', (id,))
                            salvato_storico = True
                        elif cleaned:
                            to_delete = existing - incoming
                            for (m, a) in to_delete:
                                cur.execute(
                                    'DELETE FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                                    (id, m, a)
                                )

                            for (m, a, imp) in cleaned:
                                cur.execute(
                                    'DELETE FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                                    (id, m, a)
                                )
                                cur.execute('''
                                    INSERT INTO fatturato (cliente_id, mese, anno, totale)
                                    VALUES (%s,%s,%s,%s)
                                ''', (id, m, a, imp))
                            salvato_storico = True

                    except Exception as e:
                        flash(f"Errore storico fatturato (JSON): {e}", "warning")

            if not salvato_storico and not use_storico:
                mese = request.form.get('mese')
                anno = request.form.get('anno')
                importo = request.form.get('fatturato_mensile')

                if mese and anno and importo:
                    try:
                        mese_i = int(mese)
                        anno_i = int(anno)
                        imp_d = parse_decimal(importo)
                        if imp_d is None:
                            raise ValueError("Importo non valido")

                        cur.execute(
                            'DELETE FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                            (id, mese_i, anno_i)
                        )
                        cur.execute('''
                            INSERT INTO fatturato (cliente_id,mese,anno,totale)
                            VALUES (%s,%s,%s,%s)
                        ''', (id, mese_i, anno_i, imp_d))

                    except Exception as e:
                        flash(f"Errore importo fatturato: {e}", "warning")

            db.commit()
            flash("Cliente aggiornato con successo!", "success")
            return redirect(url_for('clienti'))

        # ============================
        # PRECOMPILAZIONE ULTIMO FATTURATO
        # ============================
        cur.execute('''
            SELECT mese, anno, totale FROM fatturato
            WHERE cliente_id=%s
            ORDER BY anno DESC, mese DESC
            LIMIT 1
        ''', (id,))
        ultimo = cur.fetchone()

        mese = ultimo['mese'] if ultimo else None
        anno = ultimo['anno'] if ultimo else None
        importo = ultimo['totale'] if ultimo else None

        zone_nomi = [z['nome'] for z in zone]
        nuova_zona_selected = cliente['zona'] not in zone_nomi
        nuova_zona_value = cliente['zona'] if nuova_zona_selected else ''

        cur.execute('''
            SELECT mese, anno, totale AS importo
            FROM fatturato
            WHERE cliente_id=%s
            ORDER BY anno DESC, mese DESC
        ''', (id,))
        fatturati_storico = cur.fetchall()

        # ✅ telefono precompilato
        telefono_cliente = (cliente.get("telefono") or "")

    return render_template(
        '01_clienti/03_modifica_cliente.html',
        cliente=cliente,
        telefono_cliente=telefono_cliente,
        zone=zone,
        categorie=categorie,
        prodotti=prodotti,
        prodotti_lavorati=prodotti_lavorati,
        prezzi_attuali=prezzi_attuali,
        prezzi_offerta=prezzi_offerta,
        fornitori=fornitori,
        nuova_zona_selected=nuova_zona_selected,
        nuova_zona_value=nuova_zona_value,
        fatturato_mese=mese,
        fatturato_anno=anno,
        fatturato_importo=importo,
        fatturati_cliente=fatturati_cliente,
        fatturati_storico=fatturati_storico,
        current_month=current_datetime.month,
        current_year=current_datetime.year
    )


import calendar

@app.route('/clienti/<int:id>')
@login_required
def cliente_scheda(id):
    oggi = datetime.today()

    # ===============================
    # CALCOLO MESI PER LA CRESCITA
    # ===============================
    mese_corrente = oggi.month
    anno_corrente = oggi.year

    mese_ref = mese_corrente - 1 if mese_corrente > 1 else 12
    anno_ref = anno_corrente if mese_corrente > 1 else anno_corrente - 1

    mese_ref_prec = mese_ref - 1 if mese_ref > 1 else 12
    anno_ref_prec = anno_ref if mese_ref > 1 else anno_ref - 1

    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)

        # ====================================
        # DATI CLIENTE
        # ====================================
        cur.execute('SELECT * FROM clienti WHERE id=%s', (id,))
        cliente = cur.fetchone()

        if not cliente:
            flash('Cliente non trovato.', 'danger')
            return redirect(url_for('clienti'))

        # ====================================
        # PRODOTTI
        # ====================================
        cur.execute('''
            SELECT p.id, p.nome, p.categoria_id, COALESCE(c.nome,'–') AS categoria_nome
            FROM prodotti p
            LEFT JOIN categorie c ON p.categoria_id=c.id
            ORDER BY c.nome, p.nome
        ''')
        prodotti = cur.fetchall()

        # Prodotti già assegnati al cliente
        cur.execute('''
            SELECT prodotto_id, lavorato, prezzo_attuale, prezzo_offerta, data_operazione
            FROM clienti_prodotti
            WHERE cliente_id=%s
        ''', (id,))
        prodotti_assoc = cur.fetchall()

        assoc_dict = {p['prodotto_id']: p for p in prodotti_assoc}

        prodotti_lavorati = []
        prezzi_attuali = {}
        prezzi_offerta = {}
        prodotti_data = {}

        for p in prodotti:
            pid = p['id']

            if pid in assoc_dict:
                lavorato = assoc_dict[pid]['lavorato']
                prezzi_attuali[str(pid)] = assoc_dict[pid]['prezzo_attuale']
                prezzi_offerta[str(pid)] = assoc_dict[pid]['prezzo_offerta']
                prodotti_data[str(pid)] = assoc_dict[pid]['data_operazione']
            else:
                lavorato = False
                prezzi_attuali[str(pid)] = None
                prezzi_offerta[str(pid)] = None
                prodotti_data[str(pid)] = None

            if lavorato:
                prodotti_lavorati.append(str(pid))

        # ====================================
        # CATEGORIE
        # ====================================
        cur.execute('SELECT id, nome FROM categorie ORDER BY nome')
        categorie = [dict(c) for c in cur.fetchall()]

        # ====================================
        # FATTURATO: query unica (totale, ultimo mese, ref/ref_prec)
        # ====================================
        cur.execute('''
            SELECT
                COALESCE(SUM(totale),0) AS fatturato_totale,
                MAX(make_date(anno, mese, 1)) AS ultimo_fatturato,

                COALESCE(SUM(CASE WHEN mese=%s AND anno=%s THEN totale ELSE 0 END),0) AS fatt_ref,
                COALESCE(SUM(CASE WHEN mese=%s AND anno=%s THEN totale ELSE 0 END),0) AS fatt_prec
            FROM fatturato
            WHERE cliente_id=%s
        ''', (mese_ref, anno_ref, mese_ref_prec, anno_ref_prec, id))
        fatt_row = cur.fetchone() or {}

        fatturato_totale = fatt_row.get("fatturato_totale", 0) or 0
        ultimo_fatturato_date = fatt_row.get("ultimo_fatturato")  # date o None
        fatt_ref = fatt_row.get("fatt_ref", 0) or 0
        fatt_prec = fatt_row.get("fatt_prec", 0) or 0

        # Crescita mensile
        if fatt_prec and fatt_prec > 0:
            crescita_mensile = round(((fatt_ref - fatt_prec) / fatt_prec) * 100, 2)
        else:
            crescita_mensile = None

        # Stato cliente (coerente con /clienti)
        if ultimo_fatturato_date:
            giorni_ult_fatt = (oggi.date() - ultimo_fatturato_date).days
            if giorni_ult_fatt <= 60:
                stato_cliente = "attivo"
            elif 61 <= giorni_ult_fatt <= 91:
                stato_cliente = "bloccato"
            else:
                stato_cliente = "inattivo"
        else:
            stato_cliente = "inattivo"

        # ====================================
        # FATTURATO MENSILE STORICO
        # ====================================
        cur.execute('''
            SELECT anno, mese, SUM(totale) AS totale
            FROM fatturato
            WHERE cliente_id=%s
            GROUP BY anno, mese
            ORDER BY anno ASC, mese ASC
        ''', (id,))
        fatturato_mensile = {
            f"{r['anno']}-{r['mese']:02d}": r['totale']
            for r in cur.fetchall()
        }

        # ====================================
        # LOG COMPLETAMENTE SISTEMATO
        # ====================================
        cur.execute('''
            SELECT descrizione, data
            FROM (
                SELECT 
                    'Aggiunto prodotto: ' || p.nome AS descrizione,
                    cp.data_operazione AS data
                FROM clienti_prodotti cp 
                JOIN prodotti p ON cp.prodotto_id=p.id
                WHERE cp.cliente_id=%s AND cp.lavorato=TRUE

                UNION ALL

                SELECT 
                    'Rimosso prodotto: ' || p.nome AS descrizione,
                    pr.data_rimozione AS data
                FROM prodotti_rimossi pr 
                JOIN prodotti p ON pr.prodotto_id=p.id
                WHERE pr.cliente_id=%s

                UNION ALL

                SELECT 
                    'Fatturato aggiornato: ' || totale || ' €' AS descrizione,
                    make_date(anno, mese, 1) AS data
                FROM fatturato
                WHERE cliente_id=%s

                UNION ALL

                SELECT 
                    'Prezzo prodotto modificato: ' || p.nome AS descrizione,
                    cp.data_operazione AS data
                FROM clienti_prodotti cp 
                JOIN prodotti p ON cp.prodotto_id=p.id
                WHERE cp.cliente_id=%s 
                  AND (cp.prezzo_attuale IS NOT NULL OR cp.prezzo_offerta IS NOT NULL)
            ) AS logs
            ORDER BY data DESC
        ''', (id, id, id, id))

        log_cliente = []
        for l in cur.fetchall():
            log_dict = dict(l)
            if not log_dict['data']:
                log_dict['data'] = datetime.min
            log_cliente.append(log_dict)

    return render_template(
        "01_clienti/04_cliente_scheda.html",
        cliente=cliente,
        categorie=categorie,
        prodotti=prodotti,
        prodotti_lavorati=prodotti_lavorati,
        log_cliente=log_cliente,
        fatturato_totale=fatturato_totale,
        crescita_mensile=crescita_mensile,
        fatturato_mensile=fatturato_mensile,
        prezzi_attuali=prezzi_attuali,
        prezzi_offerta=prezzi_offerta,
        prodotti_data=prodotti_data,
        stato_cliente=stato_cliente
    )




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
        cur = db.cursor(cursor_factory=RealDictCursor)

        # Recupera tutte le categorie
        cur.execute('SELECT id, nome, immagine FROM categorie ORDER BY nome')
        categorie_rows = cur.fetchall()
        categorie = [{'nome': c['nome'], 'immagine': c['immagine'] or None} for c in categorie_rows]

        # Recupera tutti i prodotti (con codice) + nome categoria
        query = '''
            SELECT
                p.id,
                p.nome,
                p.codice,
                c.nome AS categoria_nome
            FROM prodotti p
            LEFT JOIN categorie c ON p.categoria_id = c.id
        '''
        params = []
        if q:
            query += ' WHERE (p.nome ILIKE %s OR p.codice ILIKE %s)'
            like = f'%{q}%'
            params.extend([like, like])

        query += ' ORDER BY c.nome NULLS LAST, p.nome'

        cur.execute(query, params)
        prodotti_rows = cur.fetchall() or []

        # Dizionario prodotti_per_categoria (solo categorie esistenti)
        prodotti_per_categoria = {c['nome']: [] for c in categorie}

        # ✅ Lista separata per bottone "Prodotti senza categoria"
        prodotti_senza_categoria = []

        for p in prodotti_rows:
            item = {
                'id': p['id'],
                'nome': p['nome'],
                'codice': p.get('codice')
            }

            cat_nome = p.get('categoria_nome')

            # ✅ Senza categoria
            if not cat_nome:
                prodotti_senza_categoria.append(item)
                continue

            # ✅ Categoria normale
            if cat_nome not in prodotti_per_categoria:
                # edge: categoria esiste in DB ma non in categorie_rows (raro, ma safe)
                prodotti_per_categoria[cat_nome] = []
            prodotti_per_categoria[cat_nome].append(item)

    return render_template(
        '02_prodotti/01_prodotti.html',
        prodotti_per_categoria=prodotti_per_categoria,
        categorie=categorie,
        prodotti_senza_categoria=prodotti_senza_categoria  # ✅ per bottone + modal
    )


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

        errore_codice = None

        # Validazioni base
        if not codice:
            errore_codice = "Il codice prodotto è obbligatorio."
        elif " " in codice:
            errore_codice = "Il codice prodotto non può contenere spazi."

        if not nome:
            flash('Il nome del prodotto è obbligatorio.', 'danger')
            return render_template(
                '02_prodotti/02_aggiungi_prodotto.html',
                categorie=categorie,
                errore_codice=errore_codice
            )

        with get_db() as db:
            cur = db.cursor()

            # Controllo codice univoco
            cur.execute('SELECT id FROM prodotti WHERE codice = %s', (codice,))
            if cur.fetchone():
                errore_codice = f'Il codice "{codice}" è già usato da un altro prodotto.'
                return render_template(
                    '02_prodotti/02_aggiungi_prodotto.html',
                    categorie=categorie,
                    errore_codice=errore_codice
                )

            # Gestione categoria
            if nuova_categoria:
                cur.execute('SELECT id FROM categorie WHERE nome=%s', (nuova_categoria,))
                categoria_row = cur.fetchone()
                if categoria_row:
                    categoria_id = categoria_row['id']
                else:
                    cur.execute(
                        'INSERT INTO categorie (nome) VALUES (%s) RETURNING id',
                        (nuova_categoria,)
                    )
                    categoria_id = cur.fetchone()['id']
            else:
                categoria_id = int(categoria_id) if categoria_id else None

            # Inserimento prodotto
            cur.execute(
                'INSERT INTO prodotti (codice, nome, categoria_id) VALUES (%s, %s, %s)',
                (codice, nome, categoria_id)
            )
            db.commit()

        flash(f'Prodotto "{nome}" ({codice}) aggiunto con successo.', 'success')
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
        errore_codice = None

        # Validazioni
        if not codice:
            errore_codice = "Il codice prodotto è obbligatorio."
        elif " " in codice:
            errore_codice = "Il codice prodotto non può contenere spazi."

        if not nome:
            error = 'Il nome del prodotto è obbligatorio.'

        # Se ci sono errori, torna al template (con valori aggiornati per non perdere input)
        if error or errore_codice:
            prodotto = dict(prodotto)
            prodotto['nome'] = nome
            prodotto['codice'] = codice
            prodotto['categoria_id'] = int(categoria_id) if categoria_id else prodotto.get('categoria_id')

            return render_template(
                '02_prodotti/03_modifica_prodotto.html',
                prodotto=prodotto,
                categorie=categorie,
                error=error,
                errore_codice=errore_codice
            )

        with get_db() as db:
            cur = db.cursor()

            # Controllo codice univoco (escludendo questo prodotto)
            cur.execute('SELECT id FROM prodotti WHERE codice=%s AND id<>%s', (codice, id))
            if cur.fetchone():
                errore_codice = f'Il codice "{codice}" è già usato da un altro prodotto.'

                prodotto = dict(prodotto)
                prodotto['nome'] = nome
                prodotto['codice'] = codice
                prodotto['categoria_id'] = int(categoria_id) if categoria_id else prodotto.get('categoria_id')

                return render_template(
                    '02_prodotti/03_modifica_prodotto.html',
                    prodotto=prodotto,
                    categorie=categorie,
                    error=None,
                    errore_codice=errore_codice
                )

            # Gestione categoria
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

            # Update prodotto
            cur.execute(
                'UPDATE prodotti SET codice=%s, nome=%s, categoria_id=%s WHERE id=%s',
                (codice, nome, categoria_id, id)
            )
            db.commit()

        flash(f'Prodotto "{nome}" ({codice}) modificato con successo.', 'success')
        return redirect(url_for('prodotti'))

    return render_template(
        '02_prodotti/03_modifica_prodotto.html',
        prodotto=prodotto,
        categorie=categorie,
        error=None,
        errore_codice=None
    )

@app.route('/prodotti/elimina/<int:id>', methods=['POST'])
@login_required
def elimina_prodotto(id):
    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)

        # verifica prodotto
        cur.execute('SELECT id, nome FROM prodotti WHERE id=%s', (id,))
        prodotto = cur.fetchone()

        if not prodotto:
            flash('Prodotto non trovato.', 'danger')
            return redirect(url_for('prodotti'))

        # ✅ soft delete (non rompe le FK)
        cur.execute(
            'UPDATE prodotti SET eliminato=TRUE WHERE id=%s',
            (id,)
        )

        db.commit()

    flash(f'🗑️ Prodotto "{prodotto["nome"]}" eliminato.', 'success')
    return redirect(url_for('prodotti'))


@app.route('/prodotti/clienti/<int:id>')
@login_required
def clienti_prodotto(id):
    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)

        # Recupera il prodotto (include codice)
        cur.execute('SELECT id, codice, nome, categoria_id FROM prodotti WHERE id=%s', (id,))
        prodotto = cur.fetchone()
        if not prodotto:
            flash("❌ Prodotto non trovato", "danger")
            return redirect(url_for("prodotti"))

        # Recupera i clienti associati con lavorato=True
        cur.execute('''
            SELECT c.*
            FROM clienti c
            JOIN clienti_prodotti cp ON c.id = cp.cliente_id
            WHERE cp.prodotto_id=%s AND cp.lavorato IS TRUE
            ORDER BY c.nome
        ''', (id,))
        clienti = cur.fetchall()

    return render_template(
        '02_prodotti/04_prodotto_clienti.html',
        prodotto=prodotto,
        clienti=clienti
    )


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

        # === Fatturato per zona (come in index) ===
        cur.execute('''
            SELECT 
                COALESCE(c.zona, 'Sconosciuta') AS zona, 
                COALESCE(SUM(f.totale),0) AS totale
            FROM fatturato f
            JOIN clienti c ON f.cliente_id = c.id
            GROUP BY c.zona
            ORDER BY zona
        ''')
        fatturato_per_zona_rows = cur.fetchall()
        fatturato_per_zona = {r['zona']: r['totale'] for r in fatturato_per_zona_rows}

    return render_template(
        '03_fatturato/01_fatturato.html',
        clienti=clienti_list,
        zone=zone,
        zona_filtro=zona_filtro,
        fatturato_mensile=fatturato_mensile,
        fatturato_per_zona=fatturato_per_zona  # <-- aggiunto per grafico
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
            db.commit()
            aggiorna_fatturato_totale(cliente_id)
            return jsonify(success=True)
        except Exception as e:
            return jsonify(success=False, message=str(e)), 500


# ============================
# LISTA VOLANTINI
# ============================
@app.route('/volantini')
@login_required
def lista_volantini():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()

        # Volantini
        cur.execute('SELECT id, titolo, sfondo, data_creazione FROM volantini ORDER BY data_creazione DESC')
        volantini = cur.fetchall()

        # Promo lampo
        cur.execute('SELECT id, nome, prezzo, immagine, sfondo, data_creazione FROM promo_lampo ORDER BY data_creazione DESC')
        promo_lampo = cur.fetchall()

    finally:
        cur.close()
        conn.close()

    return render_template(
        "04_volantino/01_lista_volantini.html",
        volantini=volantini,
        promo_lampo=promo_lampo
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
        os.makedirs(app.config["UPLOAD_FOLDER_VOLANTINI"], exist_ok=True)
        sfondo_path = os.path.join(app.config["UPLOAD_FOLDER_VOLANTINI"], filename)
        sfondo_file.save(sfondo_path)

        # 🔹 Inserisci volantino in DB
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO volantini (titolo, sfondo, data_creazione) VALUES (%s, %s, NOW()) RETURNING id",
                (titolo, filename)
            )
            volantino_id = cur.fetchone()["id"]

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
                    "left": x, "top": y, "width":200, "height":240,
                    "metadata": {}
                })

            # 🔹 Salva layout nel DB
            cur.execute(
                "UPDATE volantini SET layout_json=%s WHERE id=%s",
                (json.dumps(layout_json, ensure_ascii=False), volantino_id)
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()

        flash("✅ Volantino creato con successo!", "success")
        return redirect(url_for("lista_volantini"))

    return render_template("04_volantino/02_nuovo_volantino.html")

# ============================
# ELIMINA VOLANTINO
# ============================
@app.route("/volantini/elimina/<int:volantino_id>", methods=["POST"])
@login_required
def elimina_volantino(volantino_id):
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SELECT sfondo FROM volantini WHERE id = %s", (volantino_id,))
        volantino = cur.fetchone()

        if not volantino:
            flash("❌ Volantino non trovato.", "danger")
            return redirect(url_for("lista_volantini"))

        # 🔹 Elimina immagini prodotti collegati dal filesystem
        cur.execute("SELECT immagine FROM volantino_prodotti WHERE volantino_id = %s", (volantino_id,))
        prodotti = cur.fetchall()
        for prod in prodotti:
            if prod["immagine"]:
                img_path = os.path.join(UPLOAD_FOLDER_VOLANTINI_PRODOTTI, prod["immagine"])
                if os.path.exists(img_path):
                    os.remove(img_path)

        # 🔹 Elimina prodotti dal DB prima del volantino
        cur.execute("DELETE FROM volantino_prodotti WHERE volantino_id = %s", (volantino_id,))

        # 🔹 Elimina sfondo del volantino dal filesystem
        if volantino["sfondo"]:
            sfondo_path = os.path.join(UPLOAD_FOLDER_VOLANTINI, volantino["sfondo"])
            if os.path.exists(sfondo_path):
                os.remove(sfondo_path)

        # 🔹 Elimina volantino dal DB
        cur.execute("DELETE FROM volantini WHERE id = %s", (volantino_id,))
        conn.commit()
        flash("✅ Volantino eliminato con successo!", "success")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("lista_volantini"))

# ============================
# MODIFICA VOLANTINO
# ============================
@app.route("/volantini/modifica/<int:volantino_id>", methods=["GET", "POST"])
@login_required
def modifica_volantino(volantino_id):
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM volantini WHERE id = %s", (volantino_id,))
        volantino = cur.fetchone()

        if not volantino:
            flash("❌ Volantino non trovato", "danger")
            return redirect(url_for("lista_volantini"))

        # ============================
        # POST → aggiorna volantino
        # ============================
        if request.method == "POST":
            titolo = request.form.get("titolo", "").strip()
            sfondo_file = request.files.get("sfondo")
            sfondo_nome = volantino["sfondo"] or "no-image.png"

            if sfondo_file and sfondo_file.filename:
                filename = secure_filename(sfondo_file.filename)
                sfondo_nome = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                os.makedirs(UPLOAD_FOLDER_VOLANTINI, exist_ok=True)
                sfondo_path = os.path.join(UPLOAD_FOLDER_VOLANTINI, sfondo_nome)
                sfondo_file.save(sfondo_path)

            cur.execute(
                "UPDATE volantini SET titolo=%s, sfondo=%s WHERE id=%s",
                (titolo, sfondo_nome, volantino_id)
            )
            conn.commit()

            flash("✅ Volantino aggiornato con successo", "success")
            return redirect(url_for("modifica_volantino", volantino_id=volantino_id))

        # ============================
        # GET → prodotti nel volantino
        # ============================
        cur.execute("""
            SELECT id, nome, prezzo, immagine
            FROM volantino_prodotti
            WHERE volantino_id=%s AND eliminato=FALSE
            ORDER BY id ASC
        """, (volantino_id,))
        prodotti_raw = cur.fetchall()
        prodotti = [dict(p) for p in prodotti_raw]

        # ============================
        # Ultimi 15 prodotti inseriti
        # ============================
        cur.execute("""
            SELECT id, nome, prezzo AS prezzo_default,
                   COALESCE(immagine, 'no-image.png') AS immagine
            FROM volantino_prodotti
            WHERE eliminato=FALSE
            ORDER BY id DESC
            LIMIT 15
        """)
        prodotti_precedenti_raw = cur.fetchall()
        prodotti_precedenti = [dict(p) for p in prodotti_precedenti_raw]

        # ============================
        # Controllo sfondo
        # ============================
        sfondo_path_full = os.path.join(UPLOAD_FOLDER_VOLANTINI, volantino["sfondo"])
        if not os.path.exists(sfondo_path_full):
            volantino["sfondo"] = os.path.basename(NO_IMAGE_PATH)

    finally:
        cur.close()
        conn.close()

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
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM volantini WHERE id = %s", (volantino_id,))
        volantino = cur.fetchone()
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

            cur.execute(
                "INSERT INTO volantino_prodotti (volantino_id, nome, prezzo, immagine, eliminato) VALUES (%s, %s, %s, %s, FALSE) RETURNING id",
                (volantino_id, nome, prezzo, immagine_filename)
            )
            new_id = cur.fetchone()["id"]
            conn.commit()
            flash("✅ Prodotto aggiunto al volantino con successo!", "success")
            return redirect(url_for("modifica_volantino", volantino_id=volantino_id))
    finally:
        cur.close()
        conn.close()

    return render_template("04_volantino/05_aggiungi_prodotto_volantino.html", volantino=dict(volantino))


# ============================
# MODIFICA PRODOTTO DEL VOLANTINO
# ============================
@app.route('/volantini/prodotto/modifica/<int:prodotto_id>', methods=['GET', 'POST'])
@login_required
def modifica_prodotto_volantino(prodotto_id):
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM volantino_prodotti WHERE id = %s", (prodotto_id,))
        prodotto = cur.fetchone()
        if not prodotto:
            flash("❌ Prodotto non trovato.", "danger")
            return redirect(url_for("lista_volantini"))

        if request.method == "POST":
            if "lascia_vuota" in request.form:
                cur.execute(
                    "UPDATE volantino_prodotti SET nome='', prezzo=0, immagine=NULL, lascia_vuota=TRUE, eliminato=FALSE WHERE id=%s",
                    (prodotto_id,)
                )
                conn.commit()
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

            cur.execute(
                "UPDATE volantino_prodotti SET nome=%s, prezzo=%s, immagine=%s, lascia_vuota=FALSE, eliminato=FALSE WHERE id=%s",
                (nome, prezzo, filename, prodotto_id)
            )
            conn.commit()
            flash("✅ Prodotto aggiornato con successo!", "success")
            return redirect(url_for("modifica_volantino", volantino_id=prodotto["volantino_id"]))
    finally:
        cur.close()
        conn.close()

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

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SELECT nome, immagine FROM volantino_prodotti WHERE id=%s", (prodotto_id,))
        prodotto = cur.fetchone()
        if not prodotto:
            return jsonify({"status": "error", "msg": "Prodotto non trovato"}), 404

        # Riattiva prodotto già eliminato
        cur.execute(
            "SELECT id FROM volantino_prodotti WHERE volantino_id=%s AND nome=%s AND eliminato=TRUE",
            (volantino_id, prodotto["nome"])
        )
        esistente = cur.fetchone()
        if esistente:
            cur.execute(
                "UPDATE volantino_prodotti SET prezzo=%s, eliminato=FALSE WHERE id=%s",
                (prezzo, esistente["id"])
            )
            conn.commit()
            return jsonify({"status": "ok", "id": esistente["id"], "riattivato": True})

        # Inserimento nuovo prodotto
        cur.execute(
            "INSERT INTO volantino_prodotti (volantino_id, nome, prezzo, immagine, eliminato) VALUES (%s, %s, %s, %s, FALSE) RETURNING id",
            (volantino_id, prodotto["nome"], prezzo, prodotto["immagine"])
        )
        new_id = cur.fetchone()["id"]
        conn.commit()
        return jsonify({"status": "ok", "id": new_id, "riattivato": False})
    finally:
        cur.close()
        conn.close()


# ============================
# ELIMINA PRODOTTO VOLANTINO
# ============================
@app.route("/volantini/prodotto/elimina/<int:prodotto_id>", methods=["POST"])
@login_required
def elimina_prodotto_volantino(prodotto_id):
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SELECT volantino_id FROM volantino_prodotti WHERE id=%s", (prodotto_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"status": "error", "msg": "Prodotto non trovato"}), 404

        cur.execute("UPDATE volantino_prodotti SET eliminato=TRUE WHERE id=%s", (prodotto_id,))
        conn.commit()
        return jsonify({"status": "ok"})
    finally:
        cur.close()
        conn.close()


# ============================
# VISUALIZZA VOLANTINO
# ============================
@app.route("/volantino/<int:volantino_id>")
@login_required
def visualizza_volantino(volantino_id):
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM volantini WHERE id=%s", (volantino_id,))
        volantino = cur.fetchone()
        if not volantino:
            flash("❌ Volantino non trovato.", "danger")
            return redirect(url_for("lista_volantini"))

        cur.execute(
            "SELECT * FROM volantino_prodotti WHERE volantino_id=%s ORDER BY id ASC",
            (volantino_id,)
        )
        prodotti_raw = cur.fetchall()

        volantino_dict = dict(volantino)

        # 🔹 Usa placeholder se sfondo non esiste
        sfondo_path_full = os.path.join(UPLOAD_FOLDER_VOLANTINI, volantino_dict.get("sfondo") or "")
        if not os.path.exists(sfondo_path_full):
            volantino_dict["sfondo"] = os.path.basename(NO_IMAGE_PATH)

        # 🔹 Layout JSON
        try:
            layout = json.loads(volantino_dict.get("layout_json") or "{}")
            if isinstance(layout, list):
                layout = {"objects": layout}
            elif not isinstance(layout, dict):
                layout = {"objects": []}
        except Exception:
            layout = {"objects": []}
        volantino_dict["layout_json"] = json.dumps(layout, ensure_ascii=False)

        # 🔹 Prodotti con placeholder immagini
        prodotti = []
        for p in prodotti_raw:
            prod = dict(p)
            if not prod.get("immagine") or not os.path.exists(os.path.join(STATIC_DIR, "uploads", "volantino_prodotti", prod["immagine"])):
                prod["immagine"] = os.path.basename(NO_IMAGE_PATH)
            prodotti.append(prod)

        return render_template(
            "04_volantino/04_visualizza_volantino.html",
            volantino=volantino_dict,
            prodotti=prodotti
        )
    finally:
        cur.close()
        conn.close()


# ============================
# EDITOR VOLANTINO
# ============================
@app.route('/volantini/<int:volantino_id>/editor')
@login_required
def editor_volantino(volantino_id):
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM volantini WHERE id=%s", (volantino_id,))
        volantino = cur.fetchone()
        if not volantino:
            flash("❌ Volantino non trovato.", "danger")
            return redirect(url_for("lista_volantini"))

        cur.execute(
            "SELECT * FROM volantino_prodotti WHERE volantino_id=%s AND eliminato=FALSE ORDER BY id ASC",
            (volantino_id,)
        )
        prodotti_raw = cur.fetchall()

        volantino_dict = dict(volantino)
        cols, rows = 3, 3
        max_slots = cols * rows

        # 🔹 Sfondo placeholder
        sfondo_path_full = os.path.join(UPLOAD_FOLDER_VOLANTINI, volantino_dict.get("sfondo") or "")
        if not os.path.exists(sfondo_path_full):
            volantino_dict["sfondo"] = os.path.basename(NO_IMAGE_PATH)

        # 🔹 Layout
        if not volantino_dict.get("layout_json"):
            grid = []
            for i in range(max_slots):
                col = i % cols
                row = i // cols
                x = 50 + col * 250
                y = 50 + row * 280
                prodotto = dict(prodotti_raw[i]) if i < len(prodotti_raw) else {}
                immagine_path = os.path.join(STATIC_DIR, "uploads", "volantino_prodotti", prodotto.get("immagine", ""))
                if not prodotto.get("immagine") or not os.path.exists(immagine_path):
                    immagine_file = os.path.basename(NO_IMAGE_PATH)
                else:
                    immagine_file = prodotto.get("immagine")
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
                        "url": url_for("static", filename=f"uploads/volantino_prodotti/{immagine_file}"),
                        "lascia_vuota": prodotto.get("lascia_vuota", False)
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
    finally:
        cur.close()
        conn.close()


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

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("UPDATE volantini SET layout_json=%s WHERE id=%s RETURNING id", (layout_json, volantino_id))
        updated_row = cur.fetchone()
        if not updated_row:
            return jsonify({"success": False, "message": "❌ Volantino non trovato"}), 404

        for obj in layout["objects"]:
            metadata = obj.get("metadata", {})
            prod_id = metadata.get("id")
            if prod_id:
                cur.execute("UPDATE volantino_prodotti SET eliminato=FALSE WHERE id=%s AND eliminato=TRUE", (prod_id,))

        conn.commit()
        return jsonify({"success": True, "message": "✅ Layout salvato correttamente"})
    finally:
        cur.close()
        conn.close()

# ============================
# LISTA VOLANTINI + PROMO LAMPO
# ============================
@app.route("/volantini")
@login_required
def lista_volantini_completa():
    with get_db() as db:
        volantini = db.execute(
            "SELECT id, titolo, sfondo, data_creazione FROM volantini ORDER BY data_creazione DESC"
        ).fetchall()

        promo_lampo = db.execute(
            "SELECT id, nome, prezzo, immagine, sfondo, data_creazione FROM promo_lampo ORDER BY data_creazione DESC"
        ).fetchall()

    # 🔹 Prepara i percorsi completi per le immagini promo lampo
    promo_lampo_lista = []
    for p in promo_lampo:
        promo_lampo_lista.append({
            "id": p["id"],
            "nome": p["nome"],
            "prezzo": p["prezzo"],
            "immagine": url_for("static", filename=f"uploads/promolampo/{p['immagine']}") if p["immagine"] else url_for("static", filename="no-image.png"),
            "sfondo": url_for("static", filename=f"uploads/promolampo/{p['sfondo']}") if p["sfondo"] else url_for("static", filename="no-image.png"),
            "data_creazione": p["data_creazione"]
        })

    return render_template(
        "04_volantino/01_lista_volantini.html",
        volantini=volantini,
        promo_lampo=promo_lampo_lista,
    )


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

        # 🔹 Assicurati che la cartella corretta esista
        os.makedirs(UPLOAD_FOLDER_PROMOLAMPO, exist_ok=True)

        # 🔹 Salva immagine prodotto
        immagine_nome = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(immagine_file.filename)}"
        immagine_file.save(os.path.join(UPLOAD_FOLDER_PROMOLAMPO, immagine_nome))

        # 🔹 Salva sfondo promo
        sfondo_nome = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(sfondo_file.filename)}"
        sfondo_file.save(os.path.join(UPLOAD_FOLDER_PROMOLAMPO, sfondo_nome))

        # 🔹 Salva nel DB con psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO promo_lampo (nome, prezzo, immagine, sfondo, data_creazione)
                VALUES (%s, %s, %s, %s, NOW())
                """,
                (nome, prezzo, immagine_nome, sfondo_nome)
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()

        flash("✅ Promo Lampo creata con successo!", "success")
        return redirect(url_for("lista_volantini_completa"))

    return render_template("04_volantino/08_nuova_promo_lampo.html")


# ============================
# MODIFICA PROMO LAMPO
# ============================
@app.route("/promo-lampo/modifica/<int:promo_id>", methods=["GET", "POST"])
@login_required
def modifica_promo_lampo(promo_id):
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM promo_lampo WHERE id=%s", (promo_id,))
        promo = cur.fetchone()
        if not promo:
            flash("❌ Promo Lampo non trovata", "danger")
            return redirect(url_for("lista_volantini_completa"))

        if request.method == "POST":
            nome = request.form.get("nome", "").strip()
            prezzo_raw = request.form.get("prezzo", "").strip()
            immagine_file = request.files.get("immagine")
            sfondo_file = request.files.get("sfondo")

            try:
                prezzo = float(prezzo_raw)
            except ValueError:
                flash("❌ Prezzo non valido", "danger")
                return redirect(url_for("modifica_promo_lampo", promo_id=promo_id))

            # Aggiorna immagine se caricata
            immagine_nome = promo["immagine"]
            if immagine_file and immagine_file.filename.strip():
                old_path = os.path.join(UPLOAD_FOLDER_PROMO, immagine_nome)
                if os.path.exists(old_path):
                    os.remove(old_path)
                immagine_nome = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(immagine_file.filename)}"
                immagine_file.save(os.path.join(UPLOAD_FOLDER_PROMO, immagine_nome))

            # Aggiorna sfondo se caricato
            sfondo_nome = promo.get("sfondo")
            if sfondo_file and sfondo_file.filename.strip():
                old_sfondo_path = os.path.join(UPLOAD_FOLDER_PROMO, sfondo_nome) if sfondo_nome else None
                if old_sfondo_path and os.path.exists(old_sfondo_path):
                    os.remove(old_sfondo_path)
                sfondo_nome = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(sfondo_file.filename)}"
                sfondo_file.save(os.path.join(UPLOAD_FOLDER_PROMO, sfondo_nome))

            # Aggiorna DB
            cur.execute(
                "UPDATE promo_lampo SET nome=%s, prezzo=%s, immagine=%s, sfondo=%s WHERE id=%s",
                (nome, prezzo, immagine_nome, sfondo_nome, promo_id)
            )
            conn.commit()
            flash("✅ Promo Lampo aggiornata con successo!", "success")
            return redirect(url_for("lista_volantini_completa"))

    finally:
        cur.close()
        conn.close()

    return render_template("04_volantino/09_modifica_promo_lampo.html", promo=promo)


# ============================
# ELIMINA PROMO LAMPO
# ============================
@app.route("/promo-lampo/elimina/<int:promo_id>", methods=["POST"])
@login_required
def elimina_promo_lampo(promo_id):
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SELECT immagine, sfondo FROM promo_lampo WHERE id=%s", (promo_id,))
        promo = cur.fetchone()
        if not promo:
            flash("❌ Promo Lampo non trovata", "danger")
            return redirect(url_for("lista_volantini_completa"))

        # elimina immagini dalla cartella
        for file_attr in ["immagine", "sfondo"]:
            if promo[file_attr]:
                path = os.path.join(UPLOAD_FOLDER_PROMO, promo[file_attr])
                if os.path.exists(path):
                    os.remove(path)

        # elimina dal DB
        cur.execute("DELETE FROM promo_lampo WHERE id=%s", (promo_id,))
        conn.commit()
        flash("✅ Promo Lampo eliminata con successo!", "success")
        return redirect(url_for("lista_volantini_completa"))
    finally:
        cur.close()
        conn.close()


# ============================
# EDITOR PROMO LAMPO
# ============================
@app.route("/promo-lampo/<int:promo_id>/editor", methods=["GET"])
@login_required
def editor_promo_lampo(promo_id):
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM promo_lampo WHERE id=%s", (promo_id,))
        promo = cur.fetchone()
        if not promo:
            flash("❌ Promo Lampo non trovata", "danger")
            return redirect(url_for("lista_volantini_completa"))

        # 🔹 Prepara i percorsi completi per immagine e sfondo
        promo_prodotti = [{
            "url": url_for("static", filename=f"uploads/promolampo/{promo['immagine']}") if promo.get("immagine") else url_for("static", filename="no-image.png"),
            "sfondo": url_for("static", filename=f"uploads/promolampo/{promo['sfondo']}") if promo.get("sfondo") else url_for("static", filename="no-image.png"),
            "nome": promo["nome"],
            "prezzo": promo["prezzo"]
        }]

        return render_template(
            "04_volantino/10_editor_promo_lampo.html",
            promo=promo,
            promo_prodotti=promo_prodotti
        )
    finally:
        cur.close()
        conn.close()


# ============================
# SALVA LAYOUT PROMO LAMPO
# ============================
@app.route("/promo-lampo/<int:promo_id>/salva_layout", methods=["POST"], endpoint="salva_layout")
@login_required
def salva_layout_promo_lampo(promo_id):
    data = request.get_json(silent=True)
    layout = data.get("layout") if data else None

    if not layout:
        return jsonify({"status": "error", "message": "⚠️ Layout mancante"}), 400

    try:
        layout_json = json.dumps(layout, ensure_ascii=False)

        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        try:
            cur = conn.cursor()

            # Verifica che la promo esista
            cur.execute("SELECT id FROM promo_lampo WHERE id=%s", (promo_id,))
            promo = cur.fetchone()
            if not promo:
                return jsonify({"status": "error", "message": "❌ Promo Lampo non trovata"}), 404

            # Aggiorna layout
            cur.execute("UPDATE promo_lampo SET layout=%s WHERE id=%s", (layout_json, promo_id))
            conn.commit()

        except Exception as e:
            conn.rollback()
            return jsonify({"status": "error", "message": f"Errore DB: {str(e)}"}), 500
        finally:
            cur.close()
            conn.close()

        return jsonify({"status": "ok", "message": "✅ Layout salvato con successo"})
    
    except Exception as e:
        return jsonify({"status": "error", "message": f"Errore interno: {str(e)}"}), 500



# ----------------------------------------------------------------------
#  CREA NUOVO VOLANTINO (pagina editor vuota)
# ----------------------------------------------------------------------
@app.route('/beta-volantino')
def beta_volantino():
    return render_template(
        '05_beta_volantino/05_beta_volantino.html',
        volantino_id=None,
        nome_volantino="",
        layout_json="[]",
        thumbnail=""
    )


# ----------------------------------------------------------------------
#  SALVA / AGGIORNA VOLANTINO  (con miniatura)
# ----------------------------------------------------------------------
@app.route('/salva-volantino-beta', methods=['POST'])
def salva_volantino_beta():
    data = request.get_json()

    vol_id = data.get("id")
    nome = data.get("nome", "Volantino BETA")
    layout_json = json.dumps(data["layout"])
    thumbnail = data.get("thumbnail")   # base64 da html2canvas

    if vol_id:
        # Aggiorna esistente
        vol = VolantinoBeta.query.get_or_404(vol_id)
        vol.nome = nome
        vol.layout_json = layout_json
        if thumbnail:
            vol.thumbnail = thumbnail
        vol.aggiornato_il = datetime.utcnow()
    else:
        # Nuovo volantino
        vol = VolantinoBeta(
            nome=nome,
            layout_json=layout_json,
            thumbnail=thumbnail
        )
        db.session.add(vol)

    db.session.commit()
    return jsonify({"ok": True, "id": vol.id})


# ----------------------------------------------------------------------
#  APRI / MODIFICA VOLANTINO
# ----------------------------------------------------------------------
@app.route('/beta-volantino/<int:id>')
def beta_volantino_modifica(id):
    vol = VolantinoBeta.query.get_or_404(id)

    return render_template(
        '05_beta_volantino/05_beta_volantino.html',
        volantino_id=id,
        nome_volantino=vol.nome,
        layout_json=vol.layout_json,
        thumbnail=vol.thumbnail
    )


# ----------------------------------------------------------------------
#  LISTA VOLANTINI
# ----------------------------------------------------------------------
@app.route('/beta-volantini')
def lista_volantini_beta():
    lista = VolantinoBeta.query.order_by(VolantinoBeta.creato_il.desc()).all()
    return render_template(
        '05_beta_volantino/05_beta_volantino_lista.html',
        lista=lista
    )


# ----------------------------------------------------------------------
#  DUPLICA VOLANTINO
# ----------------------------------------------------------------------
@app.route('/beta-volantino/duplica/<int:id>')
def beta_volantino_duplica(id):
    vol = VolantinoBeta.query.get_or_404(id)

    nuovo = VolantinoBeta(
        nome=vol.nome + " (Copia)",
        layout_json=vol.layout_json,
        thumbnail=vol.thumbnail
    )

    db.session.add(nuovo)
    db.session.commit()

    return redirect(url_for('beta_volantino_modifica', id=nuovo.id))


# ----------------------------------------------------------------------
#  ELIMINA VOLANTINO
# ----------------------------------------------------------------------
@app.route('/beta-volantino/elimina/<int:id>')
def beta_volantino_elimina(id):
    vol = VolantinoBeta.query.get_or_404(id)
    db.session.delete(vol)
    db.session.commit()
    return redirect(url_for('lista_volantini_beta'))

# =========================
# WhatsApp Cloud API (Meta) - BLOCCO COMPLETO AGGIORNATO (per il tuo app.py)
# - Riceve testo + PDF su /webhook
# - Se riceve PDF: scarica -> parse (codice/nome/prezzo) -> preview su WA -> incrocio DB (psycopg2) -> invio mirato
#
# ENV su Render:
#   WHATSAPP_VERIFY_TOKEN, WHATSAPP_TOKEN, PHONE_NUMBER_ID
#
# NOTE IMPORTANTI:
# - Questo blocco usa *get_db()* (psycopg2) del tuo progetto.
# - Per inviare ai clienti serve che nella tabella "clienti" esista un campo telefono.
#   Il codice prova a trovarlo automaticamente tra: telefono, cellulare, whatsapp, numero, tel, phone, mobile, ecc.
# =========================

import os
import re
import time
import traceback
from pathlib import Path
from collections import defaultdict

import requests
import pdfplumber
from flask import request

GRAPH_VERSION = "v18.0"

# ------------------------------------------------------------
# 1) SEND TEXT (WhatsApp)
# ------------------------------------------------------------
def send_text(to: str, text: str):
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{os.getenv('PHONE_NUMBER_ID')}/messages"
    headers = {
        "Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,  # es: 39333xxxxxxx (senza +)
        "type": "text",
        "text": {"body": text},
    }

    r = requests.post(url, json=payload, headers=headers, timeout=20)
    print("SEND_TEXT status:", r.status_code)
    print("SEND_TEXT body:", r.text)
    return r


# ------------------------------------------------------------
# 2) DOWNLOAD MEDIA (PDF ricevuto)
# ------------------------------------------------------------
def _wa_headers():
    return {"Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}"}


def get_media_url(media_id: str) -> str:
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{media_id}"
    r = requests.get(url, headers=_wa_headers(), timeout=20)
    r.raise_for_status()
    return r.json()["url"]


def download_media_file(media_url: str, out_path: str) -> str:
    r = requests.get(media_url, headers=_wa_headers(), stream=True, timeout=60)
    r.raise_for_status()
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 64):
            if chunk:
                f.write(chunk)
    return out_path


# ------------------------------------------------------------
# 3) PARSING PDF (codice, nome, prezzo)
# ------------------------------------------------------------
RE_CODE = r"(?P<code>\d{4,10})"
RE_PRICE = r"(?P<price>\d{1,3}(?:[.,]\d{2}))"
RE_NAME = r"(?P<name>[A-Za-z0-9À-ÿ][A-Za-z0-9À-ÿ\s\-\+\/\.,]{2,80})"

LINE_RE = re.compile(
    rf"{RE_CODE}\s+(?:-|–)?\s*{RE_NAME}\s+.*?\s{RE_PRICE}\b",
    re.IGNORECASE,
)

def parse_offers_from_pdf(pdf_path: str) -> list[dict]:
    offers = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw in text.splitlines():
                line = " ".join(raw.strip().split())
                m = LINE_RE.search(line)
                if not m:
                    continue
                offers.append(
                    {
                        "code": m.group("code"),
                        "name": m.group("name").strip(),
                        "price": m.group("price").replace(".", ","),
                        "raw": line,
                    }
                )

    # de-dup per codice (prima occorrenza)
    seen = set()
    uniq = []
    for o in offers:
        if o["code"] in seen:
            continue
        seen.add(o["code"])
        uniq.append(o)

    return uniq


# ------------------------------------------------------------
# 4) DB HELPERS (psycopg2) - coerenti con il tuo DB
# ------------------------------------------------------------
PHONE_COL_CACHE = {"value": None}

def _detect_phone_column(cur) -> str | None:
    """
    Prova a trovare una colonna telefono nella tabella clienti.
    Cache in memoria per evitare query ripetute.
    """
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


def _normalize_phone(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("+", "").replace(" ", "").replace("-", "")
    # se mettono 0039...
    if s.startswith("00"):
        s = s[2:]
    return s


def product_id_by_code_pg(cur, code: str) -> int | None:
    # match esatto
    cur.execute("SELECT id FROM prodotti WHERE codice = %s LIMIT 1", (code,))
    row = cur.fetchone()
    if row:
        return row["id"] if isinstance(row, dict) else row[0]

    # fallback parziale
    cur.execute("SELECT id FROM prodotti WHERE codice ILIKE %s LIMIT 1", (f"%{code}%",))
    row = cur.fetchone()
    if row:
        return row["id"] if isinstance(row, dict) else row[0]
    return None


def customer_phones_for_product_pg(cur, prodotto_id: int) -> list[tuple[int, str]]:
    phone_col = _detect_phone_column(cur)
    if not phone_col:
        return []

    # NB: nel tuo codice usi cp.lavorato e cp.data_operazione, quindi assumiamo esista.
    # Se in qualche DB vecchio 'lavorato' non c'è, la query fallirebbe: in tal caso va aggiornata la tabella.
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
        phone = _normalize_phone(phone)
        if phone:
            out.append((cid, phone))
    return out


def build_customer_offer_map_pg(cur, offers: list[dict]) -> dict[int, dict]:
    """
    customer_id -> {"phone": "...", "items": [...]}
    Dedup per codice per cliente + ordinamento.
    """
    items_by_customer = defaultdict(dict)  # cid -> {code: offer}
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
# 5) WEBHOOK (testo + PDF)
# ------------------------------------------------------------
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # Verifica iniziale Meta
    if request.method == "GET":
        if request.args.get("hub.verify_token") == os.getenv("WHATSAPP_VERIFY_TOKEN"):
            return request.args.get("hub.challenge")
        return "Forbidden", 403

    data = request.json
    print("INCOMING WEBHOOK:", data)

    def normalize_phone(s: str | None) -> str | None:
        """Normalizza numero telefono: lascia solo cifre."""
        if not s:
            return None
        s = str(s).strip()
        if not s:
            return None
        s = s.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        s = "".join(ch for ch in s if ch.isdigit())
        return s or None

    def mark_whatsapp_linked(from_number: str):
        """
        Se esiste un cliente con telefono = from_number (normalizzato),
        marca whatsapp_linked = TRUE e whatsapp_linked_at = NOW().
        """
        n = normalize_phone(from_number)
        if not n:
            return

        try:
            with get_db() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                # Se il DB non è aggiornato e manca la colonna, non blocchiamo il bot.
                try:
                    cur.execute("""
                        UPDATE clienti
                        SET whatsapp_linked = TRUE,
                            whatsapp_linked_at = COALESCE(whatsapp_linked_at, NOW())
                        WHERE telefono = %s
                        RETURNING id, nome
                    """, (n,))
                except Exception as e:
                    print("⚠️ mark_whatsapp_linked: colonne whatsapp/telefono mancanti?", repr(e))
                    return

                row = cur.fetchone()
                if row:
                    try:
                        conn.commit()
                    except Exception:
                        pass
                    print(f"✅ WhatsApp collegato: cliente_id={row['id']} nome={row['nome']} telefono={n}")
                else:
                    # nessun cliente trovato con quel numero
                    pass

        except Exception as e:
            print("⚠️ mark_whatsapp_linked error:", repr(e))

    try:
        value = data["entry"][0]["changes"][0]["value"]
    except Exception:
        print("⚠️ WEBHOOK FORMAT NON ATTESO")
        return "OK", 200

    messages = value.get("messages") or []
    if not messages:
        return "OK", 200

    msg = messages[0]
    from_number = msg.get("from")
    mtype = msg.get("type")

    if not from_number:
        return "OK", 200

    # ✅ QUI: appena arriva un messaggio, segna "collegato" se il numero esiste nei clienti
    mark_whatsapp_linked(from_number)

    # --- Caso PDF ricevuto ---
    if mtype == "document":
        doc = msg.get("document", {})
        media_id = doc.get("id")
        filename = doc.get("filename", "offerte.pdf")

        print("DOC RECEIVED:", filename, media_id)

        if not media_id:
            send_text(from_number, "Ho ricevuto un documento ma manca media_id.")
            return "OK", 200

        try:
            # 1) Scarico PDF da Meta
            media_url = get_media_url(media_id)
            local_path = f"/tmp/{int(time.time())}_{filename}".replace(" ", "_")
            download_media_file(media_url, local_path)
            print("PDF DOWNLOADED TO:", local_path)

            # 2) Parsing PDF
            offers = parse_offers_from_pdf(local_path)
            print("OFFERS PARSED:", len(offers))

            if not offers:
                send_text(
                    from_number,
                    "Non riesco a leggere offerte dal PDF (testo non estraibile). "
                    "Se il volantino è grafico/immagine, serve OCR.",
                )
                return "OK", 200

            # 3) Preview (prime 5 righe)
            preview = "\n".join(
                [f"- {o['code']} | {o['name']} | € {o['price']}" for o in offers[:5]]
            )
            send_text(from_number, f"✅ Letto PDF: {len(offers)} righe trovate.\nEsempi:\n{preview}")

            # 4) Incrocio DB + invio mirato (psycopg2)
            try:
                with get_db() as conn:
                    cur = conn.cursor(cursor_factory=RealDictCursor)

                    # check colonna telefono
                    phone_col = _detect_phone_column(cur)
                    if not phone_col:
                        send_text(
                            from_number,
                            "⚠️ Non posso inviare ai clienti perché nella tabella 'clienti' non trovo un campo telefono.\n"
                            "Aggiungi una colonna (es. 'telefono') e riprova."
                        )
                        return "OK", 200

                    sent, total = send_offers_to_customers_pg(cur, offers)
                    try:
                        conn.commit()
                    except Exception:
                        pass

                    send_text(from_number, f"📤 Inviate offerte a {sent} clienti (mappa clienti: {total}).")

            except Exception as e_db:
                print("DB/SEND ERROR:", repr(e_db))
                print(traceback.format_exc())
                send_text(from_number, f"⚠️ Errore DB/invio: {type(e_db).__name__}")

        except Exception as e:
            print("PDF FLOW ERROR:", repr(e))
            print(traceback.format_exc())
            send_text(from_number, f"❌ Errore lettura PDF: {type(e).__name__}")

        return "OK", 200

    # --- Caso testo ---
    text = (msg.get("text", {}) or {}).get("body", "").strip().lower()
    print("IN MSG:", from_number, text)

    if text == "help":
        send_text(
            from_number,
            "Mandami un PDF offerte come *documento* qui in chat.\n"
            "Io estraggo codici+prezzi e invio un messaggio unico per cliente con i prodotti in offerta per lui.",
        )
    else:
        send_text(from_number, "Scrivi *help* oppure mandami un PDF offerte come documento.")
    return "OK", 200

import os
import re
import tempfile
from datetime import datetime
from werkzeug.utils import secure_filename
from psycopg2.extras import RealDictCursor
from flask import request, redirect, url_for, flash

ALLOWED_EXTENSIONS = {"pdf"}

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# codici tipo: ABC123, 001234, ART-123-XYZ
CODE_RE = re.compile(r"\b([A-Z0-9][A-Z0-9\-_]{2,50})\b", re.IGNORECASE)

def extract_text_from_pdf(path: str) -> str:
    try:
        import pdfplumber
        chunks = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                chunks.append(page.extract_text() or "")
        return "\n".join(chunks)
    except Exception:
        return ""

def extract_items_codice_nome(text: str) -> list[dict]:
    """
    Estrae items da righe tipo:
      CODICE  Nome prodotto ...
    Ritorna: [{"codice": "...", "nome": "..."}]
    """
    items = []
    if not text:
        return items

    seen = set()
    for ln in (l.strip() for l in text.splitlines()):
        if not ln:
            continue
        m = CODE_RE.search(ln)
        if not m:
            continue

        codice = m.group(1).upper().strip("-_")
        if not codice or codice in seen:
            continue

        nome = ln[m.end():].strip(" \t-–—:;")
        if not nome:
            nome = f"PRODOTTO {codice}"
        # taglia nomi troppo lunghi
        nome = re.sub(r"\s{2,}", " ", nome).strip()
        if len(nome) > 200:
            nome = nome[:200]

        seen.add(codice)
        items.append({"codice": codice, "nome": nome})

    return items

from flask import session  # assicurati che ci sia

@app.route("/clienti/<int:cliente_id>/importa_pdf_lavorati_auto", methods=["POST"])
@login_required
def importa_pdf_lavorati_auto(cliente_id: int):
    f = request.files.get("pdf")
    if not f or f.filename == "":
        flash("Carica un PDF.", "warning")
        return redirect(url_for("modifica_cliente", id=cliente_id))

    if not allowed_file(f.filename):
        flash("Formato non valido: serve un PDF.", "warning")
        return redirect(url_for("modifica_cliente", id=cliente_id))

    tmp_dir = tempfile.mkdtemp(prefix="pdf_")
    tmp_path = os.path.join(tmp_dir, secure_filename(f.filename))
    f.save(tmp_path)

    now = datetime.now()

    try:
        text = extract_text_from_pdf(tmp_path)
        items = extract_items_codice_nome(text)

        if not items:
            flash("Non ho trovato righe con CODICE + NOME nel PDF (se è una scansione serve OCR/AI).", "warning")
            return redirect(url_for("modifica_cliente", id=cliente_id))

        created = 0
        assigned = 0
        da_categorizzare = []  # ✅ prodotti che (anche se già esistenti) hanno categoria NULL

        with get_db() as db:
            cur = db.cursor(cursor_factory=RealDictCursor)

            cur.execute("SELECT id FROM clienti WHERE id=%s", (cliente_id,))
            if not cur.fetchone():
                flash("Cliente non trovato.", "danger")
                return redirect(url_for("clienti"))

            for it in items:
                codice = it["codice"]
                nome = it["nome"]

                # 1) crea/recupera prodotto
                cur.execute("""
                    INSERT INTO prodotti (codice, nome, categoria_id)
                    VALUES (%s, %s, NULL)
                    ON CONFLICT (codice) DO UPDATE
                    SET nome = CASE
                        WHEN prodotti.nome IS NULL OR prodotti.nome = '' THEN EXCLUDED.nome
                        ELSE prodotti.nome
                    END
                    RETURNING id, categoria_id, (xmax = 0) AS inserted
                """, (codice, nome))
                pr = cur.fetchone()
                prodotto_id = pr["id"]
                if pr["inserted"]:
                    created += 1

                # ✅ se non ha categoria, lo chiederemo (anche se NON è stato creato ora)
                if pr.get("categoria_id") is None:
                    da_categorizzare.append({
                        "id": prodotto_id,
                        "codice": codice,
                        "nome": nome
                    })

                # 2) assegna lavorato
                cur.execute("""
                    SELECT id
                    FROM clienti_prodotti
                    WHERE cliente_id=%s AND prodotto_id=%s
                    LIMIT 1
                """, (cliente_id, prodotto_id))
                rel = cur.fetchone()

                if rel:
                    cur.execute("""
                        UPDATE clienti_prodotti
                        SET lavorato=TRUE,
                            data_operazione=%s
                        WHERE id=%s
                    """, (now, rel["id"]))
                    assigned += 1
                else:
                    cur.execute("""
                        INSERT INTO clienti_prodotti
                        (cliente_id, prodotto_id, lavorato, data_operazione)
                        VALUES (%s,%s,TRUE,%s)
                    """, (cliente_id, prodotto_id, now))
                    assigned += 1

            db.commit()

        # ✅ se ci sono prodotti senza categoria, vai alla pagina scelta categorie
        if da_categorizzare:
            # dedup per id (nel caso il PDF ripeta righe)
            seen = set()
            clean = []
            for p in da_categorizzare:
                if p["id"] in seen:
                    continue
                seen.add(p["id"])
                clean.append(p)

            session["pdf_import_da_categorizzare"] = clean
            flash(f"✅ Import OK. Ora scegli la categoria per {len(clean)} prodotti.", "warning")
            return redirect(url_for("scegli_categorie_import_pdf", cliente_id=cliente_id))

        flash(
            f"✅ Import PDF completato. Assegnati/aggiornati: {assigned}. 🆕 Creati prodotti: {created}.",
            "success"
        )
        return redirect(url_for("modifica_cliente", id=cliente_id))

    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        try:
            os.rmdir(tmp_dir)
        except Exception:
            pass

@app.route("/clienti/<int:cliente_id>/importa_pdf_scegli_categorie", methods=["GET", "POST"])
@login_required
def scegli_categorie_import_pdf(cliente_id: int):
    prodotti = session.get("pdf_import_da_categorizzare") or []

    if not prodotti:
        flash("Nessun prodotto da categorizzare.", "info")
        return redirect(url_for("modifica_cliente", id=cliente_id))

    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, nome FROM categorie ORDER BY nome")
        categorie = cur.fetchall()

        if request.method == "POST":
            # form: categoria[<prodotto_id>] = <categoria_id>
            mapping = {}
            for p in prodotti:
                pid = str(p["id"])
                cat = request.form.get(f"categoria[{pid}]")
                if cat:
                    mapping[int(pid)] = int(cat)

            # aggiorna DB
            updated = 0
            for pid, catid in mapping.items():
                cur.execute("UPDATE prodotti SET categoria_id=%s WHERE id=%s", (catid, pid))
                updated += 1

            db.commit()
            session.pop("pdf_import_da_categorizzare", None)
            flash(f"✅ Categorie salvate per {updated} prodotti.", "success")
            return redirect(url_for("modifica_cliente", id=cliente_id))

    return render_template(
        "02_prodotti/06_scegli_categorie_import_pdf.html",
        cliente_id=cliente_id,
        prodotti=prodotti,
        categorie=categorie
    )


@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200



@app.route('/debug-template')
def debug_template():
    return f"""
    Loader: {app.jinja_loader}<br>
    Template path: {app.jinja_loader.searchpath}
    """

@app.route('/init-db')
def init_db():
    db.create_all()
    return "Tabelle create!"


# ============================
# AVVIO APP
# ============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
