import os
import json
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, jsonify
from datetime import datetime
from werkzeug.utils import secure_filename
from PIL import Image, ImageDraw
import psycopg2
from psycopg2.extras import RealDictCursor
from dateutil.relativedelta import relativedelta
from collections import defaultdict


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

# Config upload
app.config["UPLOAD_FOLDER_VOLANTINI"] = UPLOAD_FOLDER_VOLANTINI
app.config["UPLOAD_FOLDER_VOLANTINI_PRODOTTI"] = UPLOAD_FOLDER_VOLANTINI_PRODOTTI
app.config["UPLOAD_FOLDER_PROMO"] = UPLOAD_FOLDER_PROMO
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # limite upload 16MB


# Secret key per session
app.secret_key = 'la_tua_chiave_segreta_sicura'


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

# ============================
# ROUTE PRINCIPALE - DASHBOARD
# ============================
@app.route('/')
@login_required
def index():
    with get_db() as db:
        cur = db.cursor()

        # --- Data e mesi di riferimento ---
        oggi = datetime.now()
        ultimo_mese_completo = oggi.replace(day=1) - relativedelta(days=1)
        mese_corrente, anno_corrente = ultimo_mese_completo.month, ultimo_mese_completo.year
        mese_prec_dt = ultimo_mese_completo - relativedelta(months=1)
        mese_prec, anno_prec = mese_prec_dt.month, mese_prec_dt.year

        primo_giorno_mese_corrente = datetime(anno_corrente, mese_corrente, 1)
        primo_giorno_prossimo_mese = primo_giorno_mese_corrente + relativedelta(months=1)
        data_30_giorni_fa = oggi - timedelta(days=30)

        # === Fatturato mese corrente e precedente ===
        cur.execute('SELECT COALESCE(SUM(totale),0) AS totale FROM fatturato WHERE mese=%s AND anno=%s',
                    (mese_corrente, anno_corrente))
        fatturato_corrente = cur.fetchone()['totale']

        cur.execute('SELECT COALESCE(SUM(totale),0) AS totale FROM fatturato WHERE mese=%s AND anno=%s',
                    (mese_prec, anno_prec))
        fatturato_precedente = cur.fetchone()['totale']

        variazione_fatturato = ((fatturato_corrente - fatturato_precedente) / fatturato_precedente * 100) \
            if fatturato_precedente != 0 else None

        # === Clienti ===
        cur.execute('SELECT id, nome, data_registrazione, bloccato FROM clienti')
        clienti_rows = cur.fetchall()

        clienti_nuovi_dettaglio = []
        clienti_bloccati_dettaglio = []
        clienti_attivi_dettaglio = []
        clienti_inattivi_dettaglio = []

        # Pre-calcolo mesi ultimi 3 mesi
        mesi_ultimi_3 = [
            (anno_corrente, mese_corrente),
            (anno_prec, mese_prec),
            ((ultimo_mese_completo - relativedelta(months=2)).year,
             (ultimo_mese_completo - relativedelta(months=2)).month)
        ]

        for cliente in clienti_rows:
            # Clienti nuovi
            if cliente['data_registrazione'] >= data_30_giorni_fa:
                clienti_nuovi_dettaglio.append(cliente)

            # Clienti bloccati
            if cliente['bloccato']:
                clienti_bloccati_dettaglio.append(cliente)

            # Clienti inattivi/attivi
            cur.execute('''
                SELECT COALESCE(SUM(totale),0) AS totale
                FROM fatturato
                WHERE cliente_id=%s AND ((anno=%s AND mese=%s) OR (anno=%s AND mese=%s) OR (anno=%s AND mese=%s))
            ''', (
                cliente['id'],
                mesi_ultimi_3[0][0], mesi_ultimi_3[0][1],
                mesi_ultimi_3[1][0], mesi_ultimi_3[1][1],
                mesi_ultimi_3[2][0], mesi_ultimi_3[2][1],
            ))
            totale_periodo = cur.fetchone()['totale']
            if totale_periodo == 0:
                clienti_inattivi_dettaglio.append(cliente)
            else:
                clienti_attivi_dettaglio.append(cliente)

        # Conteggi
        clienti_nuovi = len(clienti_nuovi_dettaglio)
        clienti_bloccati = len(clienti_bloccati_dettaglio)
        clienti_inattivi = len(clienti_inattivi_dettaglio)
        clienti_attivi = len(clienti_attivi_dettaglio)

        # === Prodotti inseriti e rimossi nel mese ===
        cur.execute('''
            SELECT c.nome AS cliente, p.nome AS prodotto, cp.data_operazione
            FROM clienti_prodotti cp
            JOIN clienti c ON cp.cliente_id = c.id
            JOIN prodotti p ON cp.prodotto_id = p.id
            WHERE cp.lavorato = TRUE
              AND cp.data_operazione >= %s AND cp.data_operazione < %s
        ''', (primo_giorno_mese_corrente, primo_giorno_prossimo_mese))
        prodotti_inseriti_rows = cur.fetchall()
        prodotti_inseriti = [{'cliente': r['cliente'], 'prodotto': r['prodotto'], 'data_operazione': r['data_operazione']} 
                             for r in prodotti_inseriti_rows]
        prodotti_totali_mese = len(prodotti_inseriti)

        cur.execute('''
            SELECT c.nome AS cliente, p.nome AS prodotto, pr.data_rimozione
            FROM prodotti_rimossi pr
            JOIN prodotti p ON pr.prodotto_id = p.id
            JOIN clienti_prodotti cp ON cp.prodotto_id = p.id
            JOIN clienti c ON cp.cliente_id = c.id
            WHERE pr.data_rimozione >= %s AND pr.data_rimozione < %s
        ''', (primo_giorno_mese_corrente, primo_giorno_prossimo_mese))
        prodotti_rimossi_rows = cur.fetchall()
        prodotti_rimossi = [{'cliente': r['cliente'], 'prodotto': r['prodotto'], 'data_operazione': r['data_rimozione']} 
                            for r in prodotti_rimossi_rows]
        prodotti_rimossi_mese = len(prodotti_rimossi)

        # === Fatturato ultimi 12 mesi ===
        cur.execute('''
            SELECT anno, mese, COALESCE(SUM(totale),0) AS totale
            FROM fatturato
            GROUP BY anno, mese
            ORDER BY anno DESC, mese DESC
            LIMIT 12
        ''')
        fatturato_mensile_rows = cur.fetchall()
        fatturato_mensile = {f"{r['anno']}-{r['mese']:02}": r['totale'] for r in reversed(fatturato_mensile_rows)}

        # === Fatturato per zona ===
        cur.execute('''
            SELECT COALESCE(c.zona,'Sconosciuta') AS zona, COALESCE(SUM(f.totale),0) AS totale
            FROM fatturato f
            JOIN clienti c ON f.cliente_id = c.id
            GROUP BY c.zona
            ORDER BY zona
        ''')
        fatturato_per_zona_rows = cur.fetchall()
        fatturato_per_zona = {r['zona']: r['totale'] for r in fatturato_per_zona_rows}

        # === Notifiche dinamiche ===
        notifiche = []
        if clienti_attivi_dettaglio:
            notifiche.append({
                'titolo': "Aggiorna Fatturato",
                'descrizione': "Ricorda di aggiornare il fatturato dei clienti attivi questo mese.",
                'data': datetime.now(),
                'tipo': "warning",
                'clienti_attivi': clienti_attivi_dettaglio
            })
        if clienti_inattivi_dettaglio:
            notifiche.append({
                'titolo': "Clienti Inattivi",
                'descrizione': "Verifica eventuali aggiornamenti sui clienti inattivi.",
                'data': datetime.now(),
                'tipo': "secondary",
                'clienti': clienti_inattivi_dettaglio
            })

    # === RENDER TEMPLATE ===
    return render_template(
        '02_index.html',
        variazione_fatturato=variazione_fatturato,
        clienti_nuovi=clienti_nuovi,
        clienti_bloccati=clienti_bloccati,
        clienti_inattivi=clienti_inattivi,
        clienti_nuovi_dettaglio=clienti_nuovi_dettaglio,
        clienti_bloccati_dettaglio=clienti_bloccati_dettaglio,
        clienti_attivi_dettaglio=clienti_attivi_dettaglio,
        clienti_inattivi_dettaglio=clienti_inattivi_dettaglio,
        prodotti_totali_mese=prodotti_totali_mese,
        prodotti_rimossi_mese=prodotti_rimossi_mese,
        prodotti_inseriti=prodotti_inseriti,
        prodotti_rimossi=prodotti_rimossi,
        fatturato_mensile=fatturato_mensile,
        fatturato_per_zona=fatturato_per_zona,
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

    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)

        # Recupero clienti con eventuali filtri
        query = 'SELECT id, nome, zona FROM clienti'
        condizioni = []
        params = []

        if zona_filtro:
            condizioni.append('zona = %s')
            params.append(zona_filtro)
        if search:
            condizioni.append('LOWER(nome) LIKE %s')
            params.append(f'%{search}%')

        if condizioni:
            query += ' WHERE ' + ' AND '.join(condizioni)
        query += ' ORDER BY nome'

        cur.execute(query, params)
        clienti_rows = cur.fetchall()

        clienti_list = []
        stati_clienti = {}

        for cliente in clienti_rows:
            # Totale fatturato
            cur.execute('SELECT COALESCE(SUM(totale),0) AS totale FROM fatturato WHERE cliente_id=%s', (cliente['id'],))
            fatturato_totale = cur.fetchone()['totale']

            # Data ultimo fatturato
            cur.execute('SELECT MAX(make_date(anno, mese, 1)) AS ultimo_fatturato FROM fatturato WHERE cliente_id=%s', (cliente['id'],))
            ultimo = cur.fetchone()['ultimo_fatturato']

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

            stati_clienti[cliente['id']] = stato

            clienti_list.append({
                'id': cliente['id'],
                'nome': cliente['nome'],
                'zona': cliente['zona'],
                'fatturato_totale': fatturato_totale,
                'ultimo_fatturato': ultimo
            })

        # Ordinamento
        if order == 'fatturato':
            clienti_list.sort(key=lambda c: c['fatturato_totale'], reverse=True)
        else:
            clienti_list.sort(key=lambda c: (c['zona'] or '', c['nome']))

        # Raggruppamento per zona
        clienti_per_zona = defaultdict(list)
        for c in clienti_list:
            clienti_per_zona[c['zona']].append(c)

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
        stati_clienti=stati_clienti
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

@app.route('/clienti/modifica/<int:id>', methods=['GET', 'POST'])
@login_required
def modifica_cliente(id):
    current_datetime = datetime.now()
    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)

        # Recupera cliente
        cur.execute('SELECT * FROM clienti WHERE id=%s', (id,))
        cliente = cur.fetchone()
        if not cliente:
            flash('Cliente non trovato.', 'danger')
            return redirect(url_for('clienti'))

        # Zone e categorie
        cur.execute('SELECT * FROM zone ORDER BY nome')
        zone = cur.fetchall()
        cur.execute('SELECT * FROM categorie ORDER BY nome')
        categorie = cur.fetchall()

        # Prodotti
        cur.execute('''
            SELECT p.id, p.nome, p.categoria_id, c.nome AS categoria_nome
            FROM prodotti p
            LEFT JOIN categorie c ON p.categoria_id = c.id
            ORDER BY c.nome, p.nome
        ''')
        prodotti = cur.fetchall()

        # 💡 CREA prodotti_per_categoria (risolve l'errore!)
        prodotti_per_categoria = {}
        for p in prodotti:
            cat = p['categoria_nome'] or 'Senza categoria'
            if cat not in prodotti_per_categoria:
                prodotti_per_categoria[cat] = []
            prodotti_per_categoria[cat].append(p)

        # Prodotti associati al cliente
        cur.execute('''
            SELECT prodotto_id, lavorato, prezzo_attuale, prezzo_offerta
            FROM clienti_prodotti
            WHERE cliente_id=%s
        ''', (id,))
        prodotti_assoc = cur.fetchall()

        # Preparazione liste e dizionari per il template
        prodotti_lavorati = [str(p['prodotto_id']) for p in prodotti_assoc if p['lavorato']]
        prodotti_non_lavorati = [str(p['prodotto_id']) for p in prodotti_assoc if not p['lavorato']]
        prezzi_attuali = {str(p['prodotto_id']): p['prezzo_attuale'] for p in prodotti_assoc}
        prezzi_offerta = {str(p['prodotto_id']): p['prezzo_offerta'] for p in prodotti_assoc}

        # Fatturati cliente
        cur.execute('''
            SELECT id, mese, anno, totale
            FROM fatturato
            WHERE cliente_id=%s
            ORDER BY anno DESC, mese DESC
        ''', (id,))
        fatturati_cliente = cur.fetchall()

        if request.method == 'POST':
            # Aggiorna dati cliente
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

            cur.execute('UPDATE clienti SET nome=%s, zona=%s WHERE id=%s', (nome, zona, id))

            # Aggiorna prodotti associati
            prodotti_selezionati = request.form.getlist('prodotti_lavorati[]')
            for prodotto in prodotti:
                pid = str(prodotto['id'])
                lavorato = pid in prodotti_selezionati
                prezzo_attuale = request.form.get(f'prezzo_attuale[{pid}]') or None
                prezzo_offerta = request.form.get(f'prezzo_offerta[{pid}]') or None

                cur.execute('SELECT prodotto_id FROM clienti_prodotti WHERE cliente_id=%s AND prodotto_id=%s', (id, pid))
                esiste = cur.fetchone()
                if esiste:
                    cur.execute('''
                        UPDATE clienti_prodotti
                        SET lavorato=%s, prezzo_attuale=%s, prezzo_offerta=%s, data_operazione=%s
                        WHERE cliente_id=%s AND prodotto_id=%s
                    ''', (lavorato, prezzo_attuale, prezzo_offerta, current_datetime, id, pid))
                else:
                    cur.execute('''
                        INSERT INTO clienti_prodotti
                        (cliente_id, prodotto_id, lavorato, prezzo_attuale, prezzo_offerta, data_operazione)
                        VALUES (%s,%s,%s,%s,%s,%s)
                    ''', (id, pid, lavorato, prezzo_attuale, prezzo_offerta, current_datetime))

            # Aggiorna fatturato mensile
            mese = request.form.get('mese')
            anno = request.form.get('anno')
            importo = request.form.get('fatturato_mensile')
            if mese and anno and importo:
                try:
                    importo_float = float(importo)
                    mese_int = int(mese)
                    anno_int = int(anno)
                    cur.execute('SELECT id FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                                (id, mese_int, anno_int))
                    esiste = cur.fetchone()
                    if esiste:
                        cur.execute('UPDATE fatturato SET totale=%s WHERE id=%s', (importo_float, esiste['id']))
                    else:
                        cur.execute('INSERT INTO fatturato (cliente_id,mese,anno,totale) VALUES (%s,%s,%s,%s)',
                                    (id, mese_int, anno_int, importo_float))
                except ValueError:
                    flash('Importo fatturato non valido.', 'warning')

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

    return render_template(
        '01_clienti/03_modifica_cliente.html',
        cliente=cliente,
        zone=zone,
        categorie=categorie,
        prodotti=prodotti,
        prodotti_per_categoria=prodotti_per_categoria,
        prodotti_lavorati=prodotti_lavorati,
        prodotti_non_lavorati=prodotti_non_lavorati,
        prezzi_attuali=prezzi_attuali,
        prezzi_offerta=prezzi_offerta,
        nuova_zona_selected=nuova_zona_selected,
        nuova_zona_value=nuova_zona_value,
        fatturato_mese=mese,
        fatturato_anno=anno,
        fatturato_importo=importo,
        fatturati_cliente=fatturati_cliente,
        current_month=current_datetime.month,
        current_year=current_datetime.year
    )




import calendar


@app.route('/clienti/<int:id>')
@login_required
def cliente_scheda(id):
    oggi = datetime.today()
    current_month = oggi.month
    current_year = oggi.year
    prev_month = 12 if current_month == 1 else current_month - 1
    prev_year = current_year - 1 if current_month == 1 else current_year

    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)

        # Cliente
        cur.execute('SELECT * FROM clienti WHERE id=%s', (id,))
        cliente = cur.fetchone()
        if not cliente:
            flash('Cliente non trovato.', 'danger')
            return redirect(url_for('clienti'))

        # Prodotti
        cur.execute('''
            SELECT p.id, p.nome, p.categoria_id, COALESCE(c.nome,'–') AS categoria_nome
            FROM prodotti p
            LEFT JOIN categorie c ON p.categoria_id=c.id
            ORDER BY c.nome, p.nome
        ''')
        prodotti = cur.fetchall()

        # Prodotti associati
        cur.execute('''
            SELECT prodotto_id, lavorato, prezzo_attuale, prezzo_offerta, data_operazione
            FROM clienti_prodotti
            WHERE cliente_id=%s
        ''', (id,))
        prodotti_assoc = cur.fetchall()
        assoc_dict = {p['prodotto_id']: p for p in prodotti_assoc}

        prodotti_lavorati, prezzi_attuali, prezzi_offerta, prodotti_data = [], {}, {}, {}

        for p in prodotti:
            pid = p['id']
            if pid in assoc_dict:
                lavorato = assoc_dict[pid]['lavorato']
                prezzo_attuale = assoc_dict[pid]['prezzo_attuale']
                prezzo_offerta = assoc_dict[pid]['prezzo_offerta']
                data_op = assoc_dict[pid]['data_operazione']
            else:
                lavorato = False
                prezzo_attuale = None
                prezzo_offerta = None
                data_op = None

            if lavorato:
                prodotti_lavorati.append(str(pid))

            prezzi_attuali[str(pid)] = prezzo_attuale
            prezzi_offerta[str(pid)] = prezzo_offerta
            prodotti_data[str(pid)] = data_op

        # Categorie
        cur.execute('SELECT id, nome FROM categorie ORDER BY nome')
        categorie = [dict(c) for c in cur.fetchall()]

        # Fatturato totale
        cur.execute('SELECT COALESCE(SUM(totale),0) AS totale FROM fatturato WHERE cliente_id=%s', (id,))
        fatturato_totale = cur.fetchone()['totale']

        # Fatturato mese corrente
        cur.execute('SELECT COALESCE(SUM(totale),0) AS totale FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                    (id, current_month, current_year))
        totale_corrente = cur.fetchone()['totale']

        # Fatturato mese precedente
        cur.execute('SELECT COALESCE(SUM(totale),0) AS totale FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                    (id, prev_month, prev_year))
        totale_prec = cur.fetchone()['totale']

        # Variazione fatturato
        variazione_fatturato_cliente = ((totale_corrente - totale_prec) / totale_prec * 100) if totale_prec else None

        # STATO CLIENTE BASATO SULL'ULTIMO FATTURATO
        cur.execute('''
            SELECT anno, mese, MAX(totale) AS totale
            FROM fatturato
            WHERE cliente_id=%s
            GROUP BY anno, mese
            ORDER BY anno DESC, mese DESC
            LIMIT 1
        ''', (id,))
        ultimo_fatturato_row = cur.fetchone()

        if ultimo_fatturato_row and ultimo_fatturato_row['totale'] > 0:
            anno = ultimo_fatturato_row['anno']
            mese = ultimo_fatturato_row['mese']
            ultimo_giorno = calendar.monthrange(anno, mese)[1]
            ultimo_fatturato_date = datetime(anno, mese, ultimo_giorno)
            giorni_ult_fatt = (oggi - ultimo_fatturato_date).days

            if giorni_ult_fatt <= 60:
                stato_cliente = 'attivo'
            elif 61 <= giorni_ult_fatt <= 91:
                stato_cliente = 'bloccato'
            else:
                stato_cliente = 'inattivo'
        else:
            stato_cliente = 'inattivo'

        # Fatturato mensile storico
        cur.execute('''
            SELECT anno, mese, SUM(totale) AS totale
            FROM fatturato
            WHERE cliente_id=%s
            GROUP BY anno, mese
            ORDER BY anno ASC, mese ASC
        ''', (id,))
        fatturato_mensile = {f"{r['anno']}-{r['mese']:02d}": r['totale'] for r in cur.fetchall()}

        # Log cliente
        cur.execute('''
            SELECT descrizione, data
            FROM (
                SELECT 'Aggiunto prodotto: ' || p.nome AS descrizione, cp.data_operazione AS data
                FROM clienti_prodotti cp JOIN prodotti p ON cp.prodotto_id=p.id
                WHERE cp.cliente_id=%s AND cp.lavorato=TRUE

                UNION ALL

                SELECT 'Rimosso prodotto: ' || p.nome, pr.data_rimozione
                FROM prodotti_rimossi pr JOIN prodotti p ON pr.prodotto_id=p.id
                WHERE pr.cliente_id=%s

                UNION ALL

                SELECT 'Fatturato aggiornato: ' || totale || ' €', make_date(anno, mese, 1)
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
            log_cliente.append(log_dict)

    return render_template(
        "01_clienti/04_cliente_scheda.html",
        cliente=cliente,
        categorie=categorie,
        prodotti=prodotti,
        prodotti_lavorati=prodotti_lavorati,
        log_cliente=log_cliente,
        fatturato_totale=fatturato_totale,
        variazione_fatturato_cliente=variazione_fatturato_cliente,
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
        cur = db.cursor()
        # Recupera tutte le categorie
        cur.execute('SELECT id, nome, immagine FROM categorie ORDER BY nome')
        categorie_rows = cur.fetchall()
        categorie = [{'nome': c['nome'], 'immagine': c['immagine'] or None} for c in categorie_rows]

        # Prodotti per categoria
        prodotti_per_categoria = {}
        for c in categorie:
            query = '''
                SELECT p.id, p.nome
                FROM prodotti p
                LEFT JOIN categorie c ON p.categoria_id = c.id
                WHERE c.nome = %s
            '''
            params = [c['nome']]
            if q:
                query += ' AND p.nome ILIKE %s'
                params.append(f'%{q}%')
            cur.execute(query, params)
            prodotti_rows = cur.fetchall()
            prodotti_per_categoria[c['nome']] = [dict(p) for p in prodotti_rows]

    return render_template('02_prodotti/01_prodotti.html', prodotti_per_categoria=prodotti_per_categoria, categorie=categorie)


@app.route('/prodotti/aggiungi', methods=['GET', 'POST'])
@login_required
def aggiungi_prodotto():
    with get_db() as db:
        cur = db.cursor()
        cur.execute('SELECT id, nome FROM categorie ORDER BY nome')
        categorie = cur.fetchall()

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        categoria_id = request.form.get('categoria_id')
        nuova_categoria = request.form.get('nuova_categoria', '').strip()

        if not nome:
            flash('Il nome del prodotto è obbligatorio.', 'danger')
            return render_template('02_prodotti/02_aggiungi_prodotto.html', categorie=categorie)

        with get_db() as db:
            cur = db.cursor()
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

            cur.execute('INSERT INTO prodotti (nome, categoria_id) VALUES (%s, %s)', (nome, categoria_id))
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
        categoria_id = request.form.get('categoria_id')
        nuova_categoria = request.form.get('nuova_categoria', '').strip()
        error = None

        if not nome:
            error = 'Il nome del prodotto è obbligatorio.'
            return render_template('02_prodotti/03_modifica_prodotto.html', prodotto=prodotto, categorie=categorie, error=error)

        with get_db() as db:
            cur = db.cursor()
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

            cur.execute('UPDATE prodotti SET nome=%s, categoria_id=%s WHERE id=%s', (nome, categoria_id, id))
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

        cur.execute('DELETE FROM prodotti WHERE id=%s', (id,))
        db.commit()
        flash(f'Prodotto "{prodotto["nome"]}" eliminato con successo.', 'success')
        return redirect(url_for('prodotti'))


@app.route('/prodotti/clienti/<int:id>')
@login_required
def clienti_prodotto(id):
    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)  # ritorna dict invece di tuple

        # Recupera il prodotto
        cur.execute('SELECT * FROM prodotti WHERE id=%s', (id,))
        prodotto = cur.fetchone()
        if not prodotto:
            flash("❌ Prodotto non trovato", "danger")
            return redirect(url_for("prodotti"))  # oppure 404

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
        '/02_prodotti/04_prodotto_clienti.html',
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


# ============================
# AVVIO APP
# ============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
