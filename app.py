import os
import sqlite3
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from datetime import datetime, timedelta
from jinja2 import FileSystemLoader
from collections import defaultdict
from werkzeug.utils import secure_filename
from dateutil.relativedelta import relativedelta
from PIL import Image, ImageDraw

# Path della cartella static e dell'immagine placeholder
STATIC_FOLDER = os.path.join(os.path.dirname(__file__), "static")
NO_IMAGE_PATH = os.path.join(STATIC_FOLDER, "no-image.png")

# 🔹 Crea immagine placeholder se non esiste
if not os.path.exists(NO_IMAGE_PATH):
    os.makedirs(STATIC_FOLDER, exist_ok=True)
    img = Image.new("RGB", (100, 100), color=(220, 220, 220))  # grigio chiaro
    draw = ImageDraw.Draw(img)
    draw.text((10, 40), "No Img", fill=(100, 100, 100))
    img.save(NO_IMAGE_PATH)
    print("✅ Immagine placeholder no-image.png creata automaticamente")

# ============================
# CONFIGURAZIONE BASE FLASK
# ============================
# BASE_DIR punta alla cartella del progetto principale, non a __project_root
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Percorso reale dei template
TEMPLATES_DIR = os.path.join(BASE_DIR, "..", "_templates")


STATIC_DIR = os.path.join(BASE_DIR, 'static')

app = Flask(
    __name__,
    template_folder=TEMPLATES_DIR,
    static_folder=os.path.join(BASE_DIR, "static")
)


# Forza loader Jinja sulla cartella corretta
app.jinja_loader = FileSystemLoader(TEMPLATES_DIR)

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

# ============================
# DEBUG
# ============================
print("DEBUG - BASE_DIR:", BASE_DIR)
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
# DATABASE
# ============================
DB_PATH = os.path.join(BASE_DIR, 'gestionale.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_db():
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
        db.execute('''
            CREATE TABLE IF NOT EXISTS zone (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL UNIQUE
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS categorie (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL UNIQUE
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS prodotti (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                categoria_id INTEGER,
                FOREIGN KEY(categoria_id) REFERENCES categorie(id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS clienti (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                zona TEXT NOT NULL,
                fatturato_totale REAL DEFAULT 0,
                data_registrazione TEXT DEFAULT (DATE('now'))
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS fatturato (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                prodotto_id INTEGER,
                quantita INTEGER NOT NULL DEFAULT 0,
                mese INTEGER NOT NULL,
                anno INTEGER NOT NULL,
                totale REAL NOT NULL,
                FOREIGN KEY(cliente_id) REFERENCES clienti(id),
                FOREIGN KEY(prodotto_id) REFERENCES prodotti(id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS clienti_prodotti (
                cliente_id INTEGER NOT NULL,
                prodotto_id INTEGER NOT NULL,
                PRIMARY KEY (cliente_id, prodotto_id),
                FOREIGN KEY(cliente_id) REFERENCES clienti(id) ON DELETE CASCADE,
                FOREIGN KEY(prodotto_id) REFERENCES prodotti(id) ON DELETE CASCADE
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS prodotti_rimossi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prodotto_id INTEGER NOT NULL,
                data_rimozione TEXT NOT NULL,
                FOREIGN KEY(prodotto_id) REFERENCES prodotti(id)
            )
        ''')
        db.commit()

def aggiorna_fatturato_totale(id):
    with get_db() as db:
        db.execute('''
            UPDATE clienti SET fatturato_totale = (
                SELECT COALESCE(SUM(totale), 0) FROM fatturato WHERE cliente_id = ?
            ) WHERE id = ?
        ''', (id, id))
        db.commit()

# ============================
# ROUTE PRINCIPALE
# ============================
from flask import render_template
from datetime import datetime
from dateutil.relativedelta import relativedelta
from functools import wraps

# Assumendo che login_required e get_db siano definiti nello stesso file
# Se sono in un altro modulo, sostituire con l'import corretto

from datetime import datetime
from dateutil.relativedelta import relativedelta

@app.route('/')
@login_required
def index():
    with get_db() as db:
        now = datetime.now()
        mese_corrente = now.month
        anno_corrente = now.year

        primo_giorno_mese_corrente = datetime(anno_corrente, mese_corrente, 1)
        primo_giorno_prossimo_mese = primo_giorno_mese_corrente + relativedelta(months=1)

        # Fatturato totale corrente e precedente
        fatturato_corrente = db.execute(
            'SELECT COALESCE(SUM(totale),0) as totale FROM fatturato WHERE mese=? AND anno=?',
            (mese_corrente, anno_corrente)
        ).fetchone()['totale']

        mese_prec = 12 if mese_corrente == 1 else mese_corrente - 1
        anno_prec = anno_corrente - 1 if mese_corrente == 1 else anno_corrente
        fatturato_precedente = db.execute(
            'SELECT COALESCE(SUM(totale),0) as totale FROM fatturato WHERE mese=? AND anno=?',
            (mese_prec, anno_prec)
        ).fetchone()['totale']

        variazione_fatturato = None
        if fatturato_precedente != 0:
            variazione_fatturato = ((fatturato_corrente - fatturato_precedente) / fatturato_precedente) * 100

        # Clienti nuovi
        clienti_nuovi_rows = db.execute('''
            SELECT id, nome, zona, data_registrazione
            FROM clienti
            WHERE data_registrazione >= ? AND data_registrazione < ?
        ''', (primo_giorno_mese_corrente.isoformat(), primo_giorno_prossimo_mese.isoformat())).fetchall()

        clienti_nuovi_dettaglio = [
            {'nome': c['nome'], 'data_registrazione': datetime.fromisoformat(c['data_registrazione'])}
            for c in clienti_nuovi_rows
        ]
        clienti_nuovi = len(clienti_nuovi_rows)

        # Clienti bloccati / inattivi
        clienti_rows = db.execute('SELECT id, nome FROM clienti').fetchall()
        clienti_bloccati_dettaglio = []
        clienti_bloccati_inattivi_dettaglio = []

        for cliente in clienti_rows:
            totale_corrente = db.execute(
                'SELECT COALESCE(SUM(totale),0) FROM fatturato WHERE cliente_id=? AND mese=? AND anno=?',
                (cliente['id'], mese_corrente, anno_corrente)
            ).fetchone()[0]

            totale_prec = db.execute(
                'SELECT COALESCE(SUM(totale),0) FROM fatturato WHERE cliente_id=? AND mese=? AND anno=?',
                (cliente['id'], mese_prec, anno_prec)
            ).fetchone()[0]

            mese_due_fa = 12 if mese_corrente <= 2 else mese_corrente - 2
            anno_due_fa = anno_corrente - 1 if mese_corrente <= 2 else anno_corrente
            totale_due_mesi_fa = db.execute(
                'SELECT COALESCE(SUM(totale),0) FROM fatturato WHERE cliente_id=? AND mese=? AND anno=?',
                (cliente['id'], mese_due_fa, anno_due_fa)
            ).fetchone()[0]

            if totale_corrente > 0:
                stato = 'attivo'
            elif totale_prec == 0 and totale_due_mesi_fa == 0:
                stato = 'inattivo'
            else:
                stato = 'bloccato'

            if stato == 'bloccato':
                clienti_bloccati_dettaglio.append({'nome': cliente['nome']})
            if stato in ('bloccato', 'inattivo'):
                clienti_bloccati_inattivi_dettaglio.append({'nome': cliente['nome'], 'stato': stato})

        clienti_bloccati = len(clienti_bloccati_dettaglio)
        clienti_bloccati_inattivi = len(clienti_bloccati_inattivi_dettaglio)

        # Prodotti inseriti
        prodotti_inseriti_rows = db.execute('''
            SELECT c.nome AS cliente, p.nome AS prodotto, cp.data_operazione
            FROM clienti_prodotti cp
            JOIN clienti c ON cp.cliente_id = c.id
            JOIN prodotti p ON cp.prodotto_id = p.id
            WHERE cp.lavorato = 1
              AND cp.data_operazione >= ? AND cp.data_operazione < ?
        ''', (primo_giorno_mese_corrente.isoformat(), primo_giorno_prossimo_mese.isoformat())).fetchall()
        prodotti_inseriti = [
            {'cliente': r['cliente'], 'prodotto': r['prodotto'], 'data_operazione': datetime.fromisoformat(r['data_operazione'])}
            for r in prodotti_inseriti_rows
        ]

        # Prodotti rimossi
        prodotti_rimossi_rows = db.execute('''
            SELECT c.nome AS cliente, p.nome AS prodotto, pr.data_rimozione
            FROM prodotti_rimossi pr
            JOIN clienti c ON pr.cliente_id = c.id
            JOIN prodotti p ON pr.prodotto_id = p.id
            WHERE pr.data_rimozione >= ? AND pr.data_rimozione < ?
        ''', (primo_giorno_mese_corrente.isoformat(), primo_giorno_prossimo_mese.isoformat())).fetchall()
        prodotti_rimossi = [
            {'cliente': r['cliente'], 'prodotto': r['prodotto'], 'data_operazione': datetime.fromisoformat(r['data_rimozione'])}
            for r in prodotti_rimossi_rows
        ]

        prodotti_totali_mese = len(prodotti_inseriti)
        prodotti_rimossi_mese = len(prodotti_rimossi)

        # Fatturato ultimi 12 mesi
        fatturato_mensile_rows = db.execute('''
            SELECT anno, mese, COALESCE(SUM(totale),0) as totale
            FROM fatturato
            GROUP BY anno, mese
            ORDER BY anno DESC, mese DESC
            LIMIT 12
        ''').fetchall()
        fatturato_mensile = {f"{r['anno']}-{r['mese']:02}": r['totale'] for r in reversed(fatturato_mensile_rows)}

    return render_template(
        '02_index.html',
        variazione_fatturato=variazione_fatturato,
        clienti_nuovi=clienti_nuovi,
        clienti_nuovi_dettaglio=clienti_nuovi_dettaglio,
        clienti_bloccati=clienti_bloccati,
        clienti_bloccati_dettaglio=clienti_bloccati_dettaglio,
        clienti_bloccati_inattivi=clienti_bloccati_inattivi,
        clienti_bloccati_inattivi_dettaglio=clienti_bloccati_inattivi_dettaglio,
        prodotti_totali_mese=prodotti_totali_mese,
        prodotti_rimossi_mese=prodotti_rimossi_mese,
        prodotti_inseriti=prodotti_inseriti,
        prodotti_rimossi=prodotti_rimossi,
        fatturato_mensile=fatturato_mensile
    )


# ============================
# ROUTE CLIENTI
# ============================

@app.route('/clienti')
@login_required
def clienti():
    zona_filtro = request.args.get('zona')
    order = request.args.get('order', 'zona')
    search = request.args.get('search', '').strip().lower()  # Nuovo parametro ricerca

    oggi = datetime.today()
    mese_corrente = oggi.month
    anno_corrente = oggi.year
    mese_prec = 12 if mese_corrente == 1 else mese_corrente - 1
    anno_prec = anno_corrente - 1 if mese_corrente == 1 else anno_corrente
    mese_due_fa = 12 if mese_corrente <= 2 else mese_corrente - 2
    anno_due_fa = anno_corrente - 1 if mese_corrente <= 2 else anno_corrente

    with get_db() as db:
        # Recupera i clienti filtrati per zona
        query = 'SELECT id, nome, zona FROM clienti'
        params = []
        condizioni = []

        if zona_filtro:
            condizioni.append('zona = ?')
            params.append(zona_filtro)
        if search:
            condizioni.append('LOWER(nome) LIKE ?')
            params.append(f'%{search}%')

        if condizioni:
            query += ' WHERE ' + ' AND '.join(condizioni)

        query += ' ORDER BY nome'
        clienti_rows = db.execute(query, params).fetchall()

        clienti_list = []
        stati_clienti = {}

        for cliente in clienti_rows:
            # Calcola il fatturato totale del cliente
            fatturato_totale = db.execute(
                'SELECT COALESCE(SUM(totale), 0) FROM fatturato WHERE cliente_id = ?',
                (cliente['id'],)
            ).fetchone()[0]

            # Calcola i fatturati degli ultimi mesi
            totale_mese_corrente = db.execute(
                'SELECT COALESCE(SUM(totale), 0) FROM fatturato WHERE cliente_id = ? AND mese = ? AND anno = ?',
                (cliente['id'], mese_corrente, anno_corrente)
            ).fetchone()[0]
            totale_mese_prec = db.execute(
                'SELECT COALESCE(SUM(totale), 0) FROM fatturato WHERE cliente_id = ? AND mese = ? AND anno = ?',
                (cliente['id'], mese_prec, anno_prec)
            ).fetchone()[0]
            totale_due_mesi_fa = db.execute(
                'SELECT COALESCE(SUM(totale), 0) FROM fatturato WHERE cliente_id = ? AND mese = ? AND anno = ?',
                (cliente['id'], mese_due_fa, anno_due_fa)
            ).fetchone()[0]

            # Stato cliente
            stato = (
                'attivo' if totale_mese_corrente > 0
                else 'inattivo' if totale_mese_prec == 0 and totale_due_mesi_fa == 0
                else 'bloccato'
            )
            stati_clienti[cliente['id']] = stato

            clienti_list.append({
                'id': cliente['id'],
                'nome': cliente['nome'],
                'zona': cliente['zona'],
                'fatturato_totale': fatturato_totale,
                'fatturato_corrente': totale_mese_corrente,
                'fatturato_precedente': totale_mese_prec,
                'fatturato_due_mesi_fa': totale_due_mesi_fa
            })

        # Riordina in base al parametro "order"
        if order == 'fatturato':
            clienti_list.sort(key=lambda c: c['fatturato_totale'], reverse=True)
        else:
            clienti_list.sort(key=lambda c: (c['zona'] or '', c['nome']))

        # Raggruppa per zona
        clienti_per_zona = defaultdict(list)
        for c in clienti_list:
            clienti_per_zona[c['zona']].append(c)

        # Lista zone
        zone = db.execute('SELECT DISTINCT zona FROM clienti').fetchall()
        zone_lista = sorted([z['zona'] for z in zone if z['zona']])

    return render_template(
        '01_clienti/01_clienti.html',
        clienti_per_zona=clienti_per_zona,
        zone=zone_lista,
        zona_filtro=zona_filtro,
        order=order,
        search=search,  # Passa il parametro search al template
        stati_clienti=stati_clienti
    )

@app.route('/clienti/aggiungi', methods=['GET', 'POST'])
@login_required
def nuovo_cliente():
    current_year = datetime.now().year
    with get_db() as db:
        zone = db.execute('SELECT nome FROM zone ORDER BY nome').fetchall()
        categorie = db.execute('SELECT * FROM categorie ORDER BY nome').fetchall()
        prodotti = db.execute('SELECT p.id, p.nome, p.categoria_id FROM prodotti p ORDER BY p.nome').fetchall()

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        zona = request.form.get('zona', '').strip()
        nuova_zona = request.form.get('nuova_zona', '').strip()

        if zona == 'nuova_zona' and nuova_zona:
            zona = nuova_zona
            with get_db() as db:
                existing = db.execute('SELECT 1 FROM zone WHERE nome = ?', (zona,)).fetchone()
                if not existing:
                    db.execute('INSERT INTO zone (nome) VALUES (?)', (zona,))
                    db.commit()

        if not nome:
            flash('Il nome del cliente è obbligatorio.', 'warning')
            return redirect(request.url)

        now = datetime.now()  # timestamp
        with get_db() as db:
            cursor = db.execute(
                'INSERT INTO clienti (nome, zona, data_registrazione) VALUES (?, ?, ?)',
                (nome, zona, now)
            )
            cliente_id = cursor.lastrowid

            # Prodotti associati
            prodotti_scelti = request.form.getlist('prodotti[]')
            for prodotto_id in prodotti_scelti:
                db.execute('''
                    INSERT INTO clienti_prodotti (cliente_id, prodotto_id, lavorato, data_operazione)
                    VALUES (?, ?, 1, ?)
                ''', (cliente_id, prodotto_id, datetime.now().isoformat()))
            
            # Fatturato
            mese = request.form.get('mese')
            anno = request.form.get('anno')
            fatturato_mensile = request.form.get('fatturato_mensile')
            if mese and anno and fatturato_mensile:
                try:
                    db.execute(
                        'INSERT INTO fatturato (cliente_id, mese, anno, totale) VALUES (?, ?, ?, ?)',
                        (cliente_id, int(mese), int(anno), float(fatturato_mensile))
                    )
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
        # 🔹 Recupera cliente
        cliente = db.execute('SELECT * FROM clienti WHERE id = ?', (id,)).fetchone()
        if not cliente:
            flash('Cliente non trovato.', 'danger')
            return redirect(url_for('clienti'))

        # 🔹 Zone e categorie
        zone = db.execute('SELECT * FROM zone ORDER BY nome').fetchall()
        categorie = db.execute('SELECT * FROM categorie ORDER BY nome').fetchall()

        # 🔹 Prodotti
        prodotti = db.execute('''
            SELECT p.id, p.nome, p.categoria_id, c.nome AS categoria_nome
            FROM prodotti p
            LEFT JOIN categorie c ON p.categoria_id = c.id
            ORDER BY c.nome, p.nome
        ''').fetchall()

        # 🔹 Prodotti associati al cliente
        prodotti_assoc = db.execute('''
            SELECT prodotto_id, lavorato, prezzo_attuale, prezzo_offerta
            FROM clienti_prodotti
            WHERE cliente_id = ?
        ''', (id,)).fetchall()

        prodotti_lavorati = [str(p['prodotto_id']) for p in prodotti_assoc if p['lavorato'] == 1]
        prodotti_non_lavorati = [str(p['prodotto_id']) for p in prodotti_assoc if p['lavorato'] == 0]
        prezzi_attuali = {str(p['prodotto_id']): p['prezzo_attuale'] for p in prodotti_assoc}
        prezzi_offerta = {str(p['prodotto_id']): p['prezzo_offerta'] for p in prodotti_assoc}

        # 🔹 Fatturati cliente
        fatturati_cliente = db.execute('''
            SELECT id, mese, anno, totale 
            FROM fatturato
            WHERE cliente_id = ?
            ORDER BY anno DESC, mese DESC
        ''', (id,)).fetchall()

        if request.method == 'POST':
            # 🔹 Gestione nome e zona
            nome = request.form.get('nome', '').strip()
            zona = request.form.get('zona', '').strip()
            nuova_zona = request.form.get('nuova_zona', '').strip()

            if zona == 'nuova_zona' and nuova_zona:
                zona = nuova_zona
                try:
                    db.execute('INSERT INTO zone (nome) VALUES (?)', (zona,))
                except sqlite3.IntegrityError:
                    pass

            if not nome:
                flash('Il nome del cliente è obbligatorio.', 'warning')
                return redirect(request.url)

            db.execute('UPDATE clienti SET nome = ?, zona = ? WHERE id = ?', (nome, zona, id))

            # 🔹 Aggiorna prodotti lavorati/non lavorati con prezzi
            prodotti_selezionati = request.form.getlist('prodotti_lavorati[]')

            for prodotto in prodotti:
                pid = str(prodotto['id'])
                lavorato = 1 if pid in prodotti_selezionati else 0
                prezzo_attuale = request.form.get(f'prezzo_attuale[{pid}]') or None
                prezzo_offerta = request.form.get(f'prezzo_offerta[{pid}]') or None

                esiste = db.execute('''
                    SELECT prodotto_id FROM clienti_prodotti
                    WHERE cliente_id = ? AND prodotto_id = ?
                ''', (id, pid)).fetchone()

                if esiste:
                    db.execute('''
                        UPDATE clienti_prodotti
                        SET lavorato = ?, prezzo_attuale = ?, prezzo_offerta = ?, data_operazione = ?
                        WHERE cliente_id = ? AND prodotto_id = ?
                    ''', (lavorato, prezzo_attuale, prezzo_offerta, datetime.now().isoformat(), id, pid))
                else:
                    db.execute('''
                        INSERT INTO clienti_prodotti
                        (cliente_id, prodotto_id, lavorato, prezzo_attuale, prezzo_offerta, data_operazione)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (id, pid, lavorato, prezzo_attuale, prezzo_offerta, datetime.now().isoformat()))

            # 🔹 Aggiorna fatturato
            mese = request.form.get('mese')
            anno = request.form.get('anno')
            importo = request.form.get('fatturato_mensile')
            if mese and anno and importo:
                try:
                    importo_float = float(importo)
                    mese_int = int(mese)
                    anno_int = int(anno)
                    esiste = db.execute('''
                        SELECT id FROM fatturato WHERE cliente_id = ? AND mese = ? AND anno = ?
                    ''', (id, mese_int, anno_int)).fetchone()
                    if esiste:
                        db.execute('UPDATE fatturato SET totale = ? WHERE id = ?', (importo_float, esiste['id']))
                    else:
                        db.execute('INSERT INTO fatturato (cliente_id, mese, anno, totale) VALUES (?, ?, ?, ?)',
                                   (id, mese_int, anno_int, importo_float))
                except ValueError:
                    flash('Importo fatturato non valido.', 'warning')

            db.commit()
            aggiorna_fatturato_totale(id)
            flash('Cliente modificato con successo.', 'success')
            return redirect(url_for('clienti'))

        # 🔹 Precompila ultimo fatturato
        ultimo_fatturato = db.execute('''
            SELECT mese, anno, totale FROM fatturato
            WHERE cliente_id = ?
            ORDER BY anno DESC, mese DESC
            LIMIT 1
        ''', (id,)).fetchone()
        mese = ultimo_fatturato['mese'] if ultimo_fatturato else None
        anno = ultimo_fatturato['anno'] if ultimo_fatturato else None
        importo = ultimo_fatturato['totale'] if ultimo_fatturato else None

        zone_nomi = [z['nome'] for z in zone]
        nuova_zona_selected = cliente['zona'] not in zone_nomi
        nuova_zona_value = cliente['zona'] if nuova_zona_selected else ''

    # 🔹 Render template aggiornato
    return render_template(
        '01_clienti/03_modifica_cliente.html',
        cliente=cliente,
        zone=zone,
        categorie=categorie,
        prodotti=prodotti,
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




@app.route('/clienti/<int:id>')
@login_required
def cliente_scheda(id):
    oggi = datetime.today()
    current_month = oggi.month
    current_year = oggi.year
    prev_month = 12 if current_month == 1 else current_month - 1
    prev_year = current_year - 1 if current_month == 1 else current_year

    with get_db() as db:
        # 🔹 Recupero cliente
        cliente = db.execute('SELECT * FROM clienti WHERE id = ?', (id,)).fetchone()
        if not cliente:
            flash('Cliente non trovato.', 'danger')
            return redirect(url_for('clienti'))

        # 🔹 Prodotti
        prodotti = db.execute('''
            SELECT p.id, p.nome, p.categoria_id, COALESCE(c.nome,'–') AS categoria_nome
            FROM prodotti p
            LEFT JOIN categorie c ON p.categoria_id = c.id
            ORDER BY c.nome, p.nome
        ''').fetchall()

        # 🔹 Prodotti associati al cliente
        prodotti_assoc = db.execute('''
            SELECT prodotto_id, lavorato, prezzo_attuale, prezzo_offerta, data_operazione
            FROM clienti_prodotti
            WHERE cliente_id = ?
        ''', (id,)).fetchall()
        assoc_dict = {p['prodotto_id']: p for p in prodotti_assoc}

        prodotti_lavorati = []
        prezzi_attuali = {}
        prezzi_offerta = {}
        prodotti_data = {}

        for p in prodotti:
            pid = p['id']
            if pid in assoc_dict:
                lavorato = assoc_dict[pid]['lavorato']
                prezzo_attuale = assoc_dict[pid]['prezzo_attuale']
                prezzo_offerta = assoc_dict[pid]['prezzo_offerta']
                data_op = assoc_dict[pid]['data_operazione']
            else:
                lavorato = 0
                prezzo_attuale = None
                prezzo_offerta = None
                data_op = None

            prezzi_attuali[str(pid)] = prezzo_attuale
            prezzi_offerta[str(pid)] = prezzo_offerta
            prodotti_data[str(pid)] = data_op

            if lavorato == 1:
                prodotti_lavorati.append(str(pid))

        # 🔹 Categorie
        categorie = db.execute('SELECT id, nome FROM categorie ORDER BY nome').fetchall()
        categorie = [dict(c) for c in categorie]

        # 🔹 Fatturato totale
        fatturato_totale = db.execute('''
            SELECT COALESCE(SUM(totale), 0) AS totale
            FROM fatturato
            WHERE cliente_id = ?
        ''', (id,)).fetchone()['totale']

        # 🔹 Fatturato corrente e precedente
        totale_corrente = db.execute('''
            SELECT COALESCE(SUM(totale), 0) 
            FROM fatturato 
            WHERE cliente_id = ? AND mese = ? AND anno = ?
        ''', (id, current_month, current_year)).fetchone()[0]

        totale_prec = db.execute('''
            SELECT COALESCE(SUM(totale), 0) 
            FROM fatturato 
            WHERE cliente_id = ? AND mese = ? AND anno = ?
        ''', (id, prev_month, prev_year)).fetchone()[0]

        variazione_fatturato_cliente = None
        if totale_prec != 0:
            variazione_fatturato_cliente = ((totale_corrente - totale_prec) / totale_prec) * 100

        # 🔹 Stato cliente
        if totale_corrente > 0:
            stato_cliente = 'attivo'
        elif totale_corrente == 0 and totale_prec == 0:
            stato_cliente = 'inattivo'
        else:
            stato_cliente = 'bloccato'

        # 🔹 Fatturato mensile ordinato
        fatturato_raw = db.execute('''
            SELECT anno, mese, SUM(totale) AS totale
            FROM fatturato
            WHERE cliente_id = ?
            GROUP BY anno, mese
            ORDER BY anno ASC, mese ASC
        ''', (id,)).fetchall()
        fatturato_mensile = {f"{r['anno']}-{r['mese']:02d}": r['totale'] for r in fatturato_raw}

        # 🔹 Log operazioni cliente ottimizzato (tutti i tipi di log)
        log_prodotti = db.execute('''
            SELECT descrizione, data
            FROM (
                SELECT 'Aggiunto prodotto: ' || p.nome AS descrizione, cp.data_operazione AS data
                FROM clienti_prodotti cp
                JOIN prodotti p ON cp.prodotto_id = p.id
                WHERE cp.cliente_id = ? AND cp.lavorato = 1

                UNION ALL

                SELECT 'Rimosso prodotto: ' || p.nome, pr.data_rimozione
                FROM prodotti_rimossi pr
                JOIN prodotti p ON pr.prodotto_id = p.id
                WHERE pr.cliente_id = ?

                UNION ALL

                SELECT 'Fatturato aggiornato: ' || totale || ' €', datetime(anno || '-' || mese || '-01')
                FROM fatturato
                WHERE cliente_id = ?

                UNION ALL

                SELECT 'Prezzo prodotto modificato: ' || p.nome, cp.data_operazione
                FROM clienti_prodotti cp
                JOIN prodotti p ON cp.prodotto_id = p.id
                WHERE cp.cliente_id = ? AND (cp.prezzo_attuale IS NOT NULL OR cp.prezzo_offerta IS NOT NULL)
            ) AS logs
            ORDER BY data DESC
        ''', (id, id, id, id)).fetchall()

        # 🔹 Conversione date log in datetime
        log_cliente = []
        for l in log_prodotti:
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
        cliente = db.execute('SELECT * FROM clienti WHERE id = ?', (id,)).fetchone()
        if not cliente:
            flash('Cliente non trovato.', 'danger')
            return redirect(url_for('clienti'))

        db.execute('DELETE FROM fatturato WHERE cliente_id = ?', (id,))
        db.execute('DELETE FROM cliente_prodotti WHERE cliente_id = ?', (id,))
        db.execute('DELETE FROM clienti WHERE id = ?', (id,))
        db.commit()
        flash('Cliente rimosso con successo.', 'success')
        return redirect(url_for('clienti'))


@app.route('/clienti/fatturato_totale')
@login_required
def fatturato_totale_clienti():
    with get_db() as db:
        clienti = db.execute('''
            SELECT c.id, c.nome, c.zona, COALESCE(SUM(f.totale), 0) AS fatturato_totale
            FROM clienti c
            LEFT JOIN fatturato f ON c.id = f.cliente_id
            GROUP BY c.id, c.nome, c.zona
            ORDER BY fatturato_totale DESC, c.nome ASC
        ''').fetchall()
    return render_template('01_clienti/05_fatturato_totale.html', clienti=clienti)

# ============================
# ROUTE PRODOTTI
# ============================

# ========================
# --- ROUTE PRODOTTI ---
# ========================

@app.route('/prodotti')
@login_required
def prodotti():
    q = request.args.get('q', '').strip()
    with get_db() as db:
        categorie_rows = db.execute('SELECT id, nome, immagine FROM categorie ORDER BY nome').fetchall()
        categorie = [c['nome'] for c in categorie_rows]

        sfondi = {}
        for c in categorie_rows:
            img_file = c['immagine'] if c['immagine'] else 'default_categoria.jpg'
            img_path = os.path.join(app.root_path, 'static', 'uploads', 'categorie', img_file)
            if not os.path.isfile(img_path):
                img_file = 'default_categoria.jpg'
            sfondi[c['nome']] = img_file

        prodotti_per_categoria = {}
        for c in categorie:
            query = 'SELECT p.id, p.nome FROM prodotti p LEFT JOIN categorie c ON p.categoria_id = c.id WHERE c.nome = ?'
            params = [c]
            if q:
                query += ' AND p.nome LIKE ?'
                params.append(f'%{q}%')
            prodotti_rows = db.execute(query, params).fetchall()
            prodotti_per_categoria[c] = [dict(p) for p in prodotti_rows]

    return render_template(
        '02_prodotti/01_prodotti.html',
        prodotti_per_categoria=prodotti_per_categoria,
        categorie=categorie,
        sfondi=sfondi
    )


@app.route('/prodotti/aggiungi', methods=['GET', 'POST'])
@login_required
def aggiungi_prodotto():
    with get_db() as db:
        categorie = db.execute('SELECT id, nome FROM categorie ORDER BY nome').fetchall()

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        categoria_id = request.form.get('categoria_id')
        nuova_categoria = request.form.get('nuova_categoria', '').strip()

        if not nome:
            flash('Il nome del prodotto è obbligatorio.', 'danger')
            return render_template('02_prodotti/02_aggiungi_prodotto.html', categorie=categorie)

        with get_db() as db:
            if nuova_categoria:
                categoria_row = db.execute('SELECT id FROM categorie WHERE nome = ?', (nuova_categoria,)).fetchone()
                if categoria_row:
                    categoria_id = categoria_row['id']
                else:
                    cursor = db.execute('INSERT INTO categorie (nome) VALUES (?)', (nuova_categoria,))
                    categoria_id = cursor.lastrowid
            else:
                categoria_id = int(categoria_id) if categoria_id else None

            db.execute('INSERT INTO prodotti (nome, categoria_id) VALUES (?, ?)', (nome, categoria_id))
            db.commit()

        flash(f'Prodotto "{nome}" aggiunto con successo.', 'success')
        return redirect(url_for('prodotti'))

    return render_template('02_prodotti/02_aggiungi_prodotto.html', categorie=categorie)


@app.route('/prodotti/modifica/<int:id>', methods=['GET', 'POST'])
@login_required
def modifica_prodotto(id):
    with get_db() as db:
        prodotto = db.execute('SELECT * FROM prodotti WHERE id = ?', (id,)).fetchone()
        if not prodotto:
            abort(404)
        categorie = db.execute('SELECT id, nome FROM categorie ORDER BY nome').fetchall()

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        categoria_id = request.form.get('categoria_id')
        nuova_categoria = request.form.get('nuova_categoria', '').strip()
        error = None

        if not nome:
            error = 'Il nome del prodotto è obbligatorio.'
            return render_template('02_prodotti/03_modifica_prodotto.html', prodotto=prodotto, categorie=categorie, error=error)

        with get_db() as db:
            if nuova_categoria:
                categoria_row = db.execute('SELECT id FROM categorie WHERE nome = ?', (nuova_categoria,)).fetchone()
                if categoria_row:
                    categoria_id = categoria_row['id']
                else:
                    cursor = db.execute('INSERT INTO categorie (nome) VALUES (?)', (nuova_categoria,))
                    categoria_id = cursor.lastrowid
            else:
                categoria_id = int(categoria_id) if categoria_id else None

            db.execute('UPDATE prodotti SET nome = ?, categoria_id = ? WHERE id = ?', (nome, categoria_id, id))
            db.commit()

        flash(f'Prodotto "{nome}" modificato con successo.', 'success')
        return redirect(url_for('prodotti'))

    return render_template('02_prodotti/03_modifica_prodotto.html', prodotto=prodotto, categorie=categorie, error=None)


@app.route('/prodotti/elimina/<int:id>', methods=['POST'])
@login_required
def elimina_prodotto(id):
    with get_db() as db:
        prodotto = db.execute('SELECT nome FROM prodotti WHERE id = ?', (id,)).fetchone()
        if not prodotto:
            flash('Prodotto non trovato.', 'danger')
            return redirect(url_for('prodotti'))

        db.execute('DELETE FROM prodotti WHERE id = ?', (id,))
        db.commit()
        flash(f'Prodotto "{prodotto["nome"]}" eliminato con successo.', 'success')
        return redirect(url_for('prodotti'))

@app.route('/prodotti/clienti/<int:id>')
def clienti_prodotto(id):
    db_path = os.path.join(BASE_DIR, 'gestionale.db')  # aggiorna con il tuo DB
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Prendi il prodotto
    cur.execute("SELECT * FROM prodotti WHERE id = ?", (id,))
    prodotto = cur.fetchone()
    if not prodotto:
        conn.close()
        return "Prodotto non trovato", 404

    # Prendi i clienti che lavorano quel prodotto usando la tabella di relazione
    cur.execute("""
        SELECT c.* 
        FROM clienti c
        JOIN clienti_prodotti cp ON c.id = cp.cliente_id
        WHERE cp.prodotto_id = ? AND cp.lavorato = 1
    """, (id,))
    clienti = cur.fetchall()

    conn.close()
    return render_template('/02_prodotti/04_prodotto_clienti.html', prodotto=prodotto, clienti=clienti)

@app.route('/categorie')
def gestisci_categorie():
    # Percorso al database
    db_path = os.path.join(BASE_DIR, 'gestionale.db')
    
    # Connessione al database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Prendi tutte le categorie
    cur.execute("SELECT * FROM categorie")
    categorie = [row["nome"] for row in cur.fetchall()]


    conn.close()

    # Passa le categorie al template
    return render_template('/02_prodotti/05_gestisci_categorie.html', categorie=categorie)

@app.route('/categorie/aggiungi', methods=['POST'])
def aggiungi_categoria():
    nome = request.form.get('nome_categoria')
    if nome:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO categorie (nome) VALUES (?)", (nome,))
        conn.commit()
        conn.close()
    return redirect(url_for('gestisci_categorie'))

@app.route('/categorie/elimina/<nome_categoria>', methods=['POST'])
def elimina_categoria(nome_categoria):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM categorie WHERE nome = ?", (nome_categoria,))
    conn.commit()
    conn.close()
    return redirect(url_for('gestisci_categorie'))

@app.route('/fatturato')
@login_required
def fatturato():
    zona_filtro = request.args.get('zona', 'tutte')

    with get_db() as db:
        # Recupera tutte le zone clienti distinte per il filtro
        zone = db.execute('SELECT DISTINCT zona FROM clienti ORDER BY zona').fetchall()

        # Recupero clienti (con eventuale filtro zona)
        params = []
        zona_cond = ''
        if zona_filtro != 'tutte':
            zona_cond = 'WHERE zona = ?'
            params.append(zona_filtro)

        clienti = db.execute(f'''
            SELECT id, nome, zona
            FROM clienti
            {zona_cond}
            ORDER BY nome
        ''', params).fetchall()

        clienti_list = []
        if clienti:
            # Calcolo fatturato totale storico per ciascun cliente
            clienti_ids = [c['id'] for c in clienti]
            placeholders = ','.join('?' for _ in clienti_ids)
            query = f'''
                SELECT cliente_id, SUM(totale) AS totale
                FROM fatturato
                WHERE cliente_id IN ({placeholders})
                GROUP BY cliente_id
            '''
            totali_rows = db.execute(query, clienti_ids).fetchall()
            totali_dict = {row['cliente_id']: float(row['totale'] or 0) for row in totali_rows}

            for cliente in clienti:
                clienti_list.append({
                    'id': cliente['id'],
                    'nome': cliente['nome'],
                    'zona': cliente['zona'],
                    'fatturato_totale': totali_dict.get(cliente['id'], 0.0)
                })

        # Grafico ultimi 3 mesi (facoltativo, rimane com’è)
        oggi = datetime.now()
        mesi_ultimi = []
        for i in range(2, -1, -1):
            dt = (oggi.replace(day=1) - relativedelta(months=i))
            mesi_ultimi.append((dt.year, dt.month))

        fatturato_mensile = {}
        for anno, mese in mesi_ultimi:
            query = '''
                SELECT SUM(f.totale) as totale_mese
                FROM fatturato f
                JOIN clienti c ON f.cliente_id = c.id
                WHERE f.anno = ? AND f.mese = ?
            '''
            params = [anno, mese]
            if zona_filtro != 'tutte':
                query += ' AND c.zona = ?'
                params.append(zona_filtro)

            totale_row = db.execute(query, params).fetchone()
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
        # Recupera tutti i clienti
        clienti = db.execute('SELECT id, nome, zona FROM clienti ORDER BY nome').fetchall()
        clienti_list = []

        if clienti:
            # Prepara lista ID clienti
            clienti_ids = [c['id'] for c in clienti]
            if clienti_ids:
                placeholders = ','.join('?' for _ in clienti_ids)
                # Calcola il fatturato totale per ogni cliente in un'unica query
                query = f'''
                    SELECT cliente_id, SUM(totale) AS totale
                    FROM fatturato
                    WHERE cliente_id IN ({placeholders})
                    GROUP BY cliente_id
                '''
                totali_rows = db.execute(query, clienti_ids).fetchall()
                totali_dict = {row['cliente_id']: float(row['totale'] or 0) for row in totali_rows}

            # Costruisci la lista finale da passare al template
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
        try:
            for f in fatturati:
                fid = f.get('id')
                importo = float(f.get('importo', 0))
                db.execute('UPDATE fatturato SET totale = ? WHERE id = ?', (importo, fid))
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
    conn = get_db_connection()

    # 🔹 Volantini
    volantini = conn.execute('''
        SELECT id, titolo, sfondo, data_creazione
        FROM volantini
        ORDER BY data_creazione DESC
    ''').fetchall()

    # 🔹 Promo lampo
    promo_lampo = conn.execute('''
        SELECT id, nome, prezzo, immagine, sfondo, data_creazione
        FROM promo_lampo
        ORDER BY data_creazione DESC
    ''').fetchall()

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
        os.makedirs(UPLOAD_FOLDER_VOLANTINI, exist_ok=True)
        sfondo_file.save(os.path.join(UPLOAD_FOLDER_VOLANTINI, filename))

        # 🔹 Inserisci volantino in DB
        conn = get_db_connection()
        cur = conn.execute(
            "INSERT INTO volantini (titolo, sfondo, data_creazione) VALUES (?, ?, datetime('now'))",
            (titolo, filename)
        )
        volantino_id = cur.lastrowid

        # 🔹 Inizializza griglia 3x3 con slot vuoti (9 prodotti)
        cols, rows = 3, 3
        max_slots = cols * rows
        layout_json = {"objects": []}

        for i in range(max_slots):
            col = i % cols
            row = i // cols
            x = 50 + col * 250
            y = 50 + row * 280

            # Oggetto vuoto per slot
            layout_json["objects"].append({
                "type": "group",
                "objects": [
                    {
                        "type": "rect",
                        "left": 0, "top": 0,
                        "width": 200,
                        "height": 240,
                        "fill": "#ffffff",
                        "stroke": "#cccccc",
                        "strokeWidth": 1
                    },
                    {
                        "type": "text",
                        "text": "",
                        "left": 100,
                        "top": 190,
                        "fontSize": 14,
                        "originX": "center",
                        "textAlign": "center"
                    },
                    {
                        "type": "text",
                        "text": "",
                        "left": 100,
                        "top": 215,
                        "fontSize": 18,
                        "fill": "red",
                        "originX": "center",
                        "textAlign": "center"
                    }
                ],
                "left": x,
                "top": y,
                "width": 200,
                "height": 240,
                "metadata": {}
            })

        # 🔹 Salva layout nel DB
        conn.execute(
            "UPDATE volantini SET layout_json=? WHERE id=?",
            (json.dumps(layout_json, ensure_ascii=False), volantino_id)
        )
        conn.commit()
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
    conn = get_db_connection()
    volantino = conn.execute(
        "SELECT sfondo FROM volantini WHERE id = ?", (volantino_id,)
    ).fetchone()

    if volantino:
        # Controllo se sfondo esiste
        sfondo_file = volantino["sfondo"]
        if sfondo_file:  # solo se non è None
            sfondo_path = os.path.join("static", "uploads", "volantini", sfondo_file)
            if os.path.exists(sfondo_path):
                os.remove(sfondo_path)

        # Elimina immagini prodotti collegati
        prodotti = conn.execute(
            "SELECT immagine FROM volantino_prodotti WHERE volantino_id = ?", 
            (volantino_id,)
        ).fetchall()
        for prod in prodotti:
            img_file = prod["immagine"]
            if img_file:
                img_path = os.path.join("static", "uploads", "volantini_prodotti", img_file)
                if os.path.exists(img_path):
                    os.remove(img_path)

        # Elimina volantino dal database
        conn.execute("DELETE FROM volantini WHERE id = ?", (volantino_id,))
        conn.commit()
        flash("✅ Volantino eliminato con successo!", "success")
    else:
        flash("❌ Volantino non trovato.", "danger")

    conn.close()
    return redirect(url_for("lista_volantini"))


# ============================
# MODIFICA VOLANTINO
# ============================
@app.route("/volantini/modifica/<int:volantino_id>", methods=["GET", "POST"])
@login_required
def modifica_volantino(volantino_id):
    conn = get_db_connection()
    volantino = conn.execute(
        "SELECT * FROM volantini WHERE id = ?", (volantino_id,)
    ).fetchone()

    if not volantino:
        conn.close()
        flash("❌ Volantino non trovato", "danger")
        return redirect(url_for("lista_volantini"))

    if request.method == "POST":
        titolo = request.form.get("titolo", "").strip()
        sfondo_file = request.files.get("sfondo")

        # 🔹 Gestione sfondo
        sfondo_nome = volantino["sfondo"]  # può essere None
        if sfondo_file and sfondo_file.filename:
            filename = secure_filename(sfondo_file.filename)
            sfondo_nome = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            os.makedirs(UPLOAD_FOLDER_VOLANTINI, exist_ok=True)
            sfondo_file.save(os.path.join(UPLOAD_FOLDER_VOLANTINI, sfondo_nome))

        # 🔹 Aggiorna dati DB
        conn.execute(
            """
            UPDATE volantini 
            SET titolo=?, sfondo=? 
            WHERE id=?
            """,
            (titolo, sfondo_nome, volantino_id),
        )
        conn.commit()
        flash("✅ Volantino aggiornato con successo", "success")
        conn.close()
        return redirect(url_for("modifica_volantino", volantino_id=volantino_id))

    # 🔹 Prodotti attivi collegati a questo volantino
    prodotti_raw = conn.execute(
        """
        SELECT * 
        FROM volantino_prodotti 
        WHERE volantino_id=? AND eliminato=0
        ORDER BY id ASC
        """,
        (volantino_id,),
    ).fetchall()
    prodotti = [dict(row) for row in prodotti_raw]

    # 🔹 Prodotti consigliati = ultimi 15 attivi con immagine
    prodotti_precedenti_raw = conn.execute(
        """
        SELECT id, nome, prezzo AS prezzo_default,
               COALESCE(immagine, 'no-image.png') AS immagine
        FROM volantino_prodotti
        WHERE eliminato=0 AND immagine IS NOT NULL
        ORDER BY id DESC
        LIMIT 15
        """
    ).fetchall()
    prodotti_precedenti = [dict(row) for row in prodotti_precedenti_raw]

    conn.close()

    return render_template(
        "04_volantino/03_modifica_volantino.html",
        volantino=dict(volantino),
        prodotti=prodotti,
        prodotti_precedenti=prodotti_precedenti
    )





# ============================
# AGGIUNGI PRODOTTO
# ============================
@app.route('/volantini/<int:volantino_id>/aggiungi_prodotto', methods=['GET', 'POST'])
@login_required
def aggiungi_prodotto_volantino(volantino_id):
    conn = get_db_connection()
    volantino = conn.execute(
        "SELECT * FROM volantini WHERE id = ?", (volantino_id,)
    ).fetchone()

    if not volantino:
        conn.close()
        flash("❌ Volantino non trovato.", "danger")
        return redirect(url_for("lista_volantini"))

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        prezzo_raw = request.form.get('prezzo', '').strip()
        immagine_file = request.files.get('immagine')

        # 🔹 Validazione base
        if not nome or not prezzo_raw:
            conn.close()
            flash("⚠️ Inserisci nome e prezzo.", "warning")
            return redirect(request.url)

        try:
            prezzo = float(prezzo_raw)
            if prezzo < 0:
                raise ValueError
        except ValueError:
            conn.close()
            flash("⚠️ Prezzo non valido.", "warning")
            return redirect(request.url)

        # 🔹 Gestione immagine
        immagine_filename = None
        if immagine_file and immagine_file.filename:
            filename = secure_filename(immagine_file.filename)
            immagine_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            upload_path = os.path.join("static", "uploads", "volantino_prodotti")
            os.makedirs(upload_path, exist_ok=True)
            immagine_file.save(os.path.join(upload_path, immagine_filename))

        # 🔹 Inserimento prodotto nel volantino (sempre attivo)
        conn.execute(
            """
            INSERT INTO volantino_prodotti (volantino_id, nome, prezzo, immagine, eliminato) 
            VALUES (?, ?, ?, ?, 0)
            """,
            (volantino_id, nome, prezzo, immagine_filename)
        )
        conn.commit()
        conn.close()

        flash("✅ Prodotto aggiunto al volantino con successo!", "success")
        return redirect(url_for("modifica_volantino", volantino_id=volantino_id))

    conn.close()
    return render_template("04_volantino/05_aggiungi_prodotto_volantino.html", volantino=volantino)

# ============================
# MODIFICA PRODOTTO
# ============================
import os
from werkzeug.utils import secure_filename

@app.route('/volantini/prodotto/modifica/<int:prodotto_id>', methods=['GET', 'POST'])
@login_required
def modifica_prodotto_volantino(prodotto_id):
    conn = get_db_connection()
    prodotto = conn.execute(
        "SELECT * FROM volantino_prodotti WHERE id = ?", 
        (prodotto_id,)
    ).fetchone()

    if not prodotto:
        conn.close()
        flash("❌ Prodotto non trovato.", "danger")
        return redirect(url_for("lista_volantini"))

    if request.method == "POST":
        # 🔹 Se l’utente ha cliccato "Lascia vuota"
        if "lascia_vuota" in request.form:
            conn.execute(
                """
                UPDATE volantino_prodotti 
                SET nome = '', prezzo = 0.00, immagine = NULL, lascia_vuota = 1, eliminato = 0
                WHERE id = ?
                """,
                (prodotto_id,)
            )
            conn.commit()
            conn.close()
            flash("✅ Box lasciata vuota.", "success")
            return redirect(url_for("modifica_volantino", volantino_id=prodotto["volantino_id"]))

        nome = request.form.get("nome", "").strip()
        prezzo_raw = request.form.get("prezzo", "").strip()

        # 🔹 Validazione base
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

        # 🔹 Gestione immagine
        file = request.files.get("immagine")
        filename = prodotto["immagine"]  # default: mantieni la vecchia

        if file and file.filename:
            original_name = secure_filename(file.filename)
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{original_name}"

            upload_dir = os.path.join("static", "uploads", "volantino_prodotti")
            os.makedirs(upload_dir, exist_ok=True)
            file.save(os.path.join(upload_dir, filename))

        # 🔹 Aggiorna DB con i dati reali
        conn.execute(
            """
            UPDATE volantino_prodotti 
            SET nome = ?, prezzo = ?, immagine = ?, lascia_vuota = 0, eliminato = 0
            WHERE id = ?
            """,
            (nome, prezzo, filename, prodotto_id)
        )
        conn.commit()
        conn.close()

        flash("✅ Prodotto aggiornato con successo!", "success")
        return redirect(url_for("modifica_volantino", volantino_id=prodotto["volantino_id"]))

    conn.close()
    return render_template(
        "04_volantino/06_modifica_prodotto_volantino.html", 
        prodotto=prodotto
    )


from flask import request, jsonify

@app.route("/volantini/<int:volantino_id>/aggiungi_consigliato", methods=["POST"])
@login_required
def aggiungi_consigliato(volantino_id):
    conn = get_db_connection()
    try:
        data = request.get_json()
        prodotto_id = data.get("id")
        prezzo = data.get("prezzo")

        # 🔹 Validazione prezzo
        try:
            prezzo = float(prezzo)
        except (ValueError, TypeError):
            return jsonify({"status": "error", "msg": "Prezzo non valido"}), 400

        # 🔹 Recupero dati prodotto di origine
        prodotto = conn.execute(
            "SELECT nome, immagine FROM volantino_prodotti WHERE id=?",
            (prodotto_id,)
        ).fetchone()

        if not prodotto:
            return jsonify({"status": "error", "msg": "Prodotto non trovato"}), 404

        # 🔹 Verifica se esiste già nel volantino ma segnato come eliminato
        esistente = conn.execute(
            """
            SELECT id FROM volantino_prodotti
            WHERE volantino_id=? AND nome=? AND eliminato=1
            """,
            (volantino_id, prodotto["nome"])
        ).fetchone()

        if esistente:
            # Riattivazione prodotto già presente
            conn.execute(
                """
                UPDATE volantino_prodotti
                SET prezzo=?, eliminato=0
                WHERE id=?
                """,
                (prezzo, esistente["id"])
            )
            conn.commit()
            return jsonify({"status": "ok", "id": esistente["id"], "riattivato": True})

        # 🔹 Inserimento nuovo prodotto
        cursor = conn.execute(
            """
            INSERT INTO volantino_prodotti (volantino_id, nome, prezzo, immagine, eliminato)
            VALUES (?, ?, ?, ?, 0)
            """,
            (volantino_id, prodotto["nome"], prezzo, prodotto["immagine"])
        )
        conn.commit()

        new_id = cursor.lastrowid
        return jsonify({"status": "ok", "id": new_id, "riattivato": False})

    finally:
        conn.close()




# ============================
# ELIMINA PRODOTTO
# ============================
@app.route("/volantini/prodotto/elimina/<int:prodotto_id>", methods=["POST"])
@login_required
def elimina_prodotto_volantino(prodotto_id):
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT volantino_id FROM volantino_prodotti WHERE id = ?", 
            (prodotto_id,)
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "msg": "Prodotto non trovato"}), 404

        # 🔹 Segna come eliminato invece di cancellare dal DB
        conn.execute(
            "UPDATE volantino_prodotti SET eliminato = 1 WHERE id = ?", 
            (prodotto_id,)
        )
        conn.commit()

        return jsonify({"status": "ok"})
    finally:
        conn.close()



# ============================
# VISUALIZZA VOLANTINO
# ============================
@app.route("/volantino/<int:volantino_id>")
def visualizza_volantino(volantino_id):
    conn = get_db_connection()
    volantino = conn.execute(
        "SELECT * FROM volantini WHERE id = ?", 
        (volantino_id,)
    ).fetchone()

    if not volantino:
        conn.close()
        flash("❌ Volantino non trovato.", "danger")
        return redirect(url_for("lista_volantini"))

    prodotti = conn.execute(
        "SELECT * FROM volantino_prodotti WHERE volantino_id = ? ORDER BY id ASC", 
        (volantino_id,)
    ).fetchall()
    conn.close()

    # 🔑 Normalizzo layout_json sempre in formato FabricJS corretto
    import json
    volantino_dict = dict(volantino)
    try:
        layout = json.loads(volantino_dict.get("layout_json") or "{}")
        if isinstance(layout, list):  
            # caso vecchio formato → avvolgo in dict
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


import json
# ============================
# EDITOR + SALVATAGGIO LAYOUT
# ============================
@app.route('/volantini/<int:volantino_id>/editor')
@login_required
def editor_volantino(volantino_id):
    import json

    conn = get_db_connection()

    # Recupero volantino
    volantino = conn.execute(
        "SELECT * FROM volantini WHERE id = ?", 
        (volantino_id,)
    ).fetchone()

    if not volantino:
        conn.close()
        flash("❌ Volantino non trovato.", "danger")
        return redirect(url_for("lista_volantini"))

    # ✅ Prodotti attivi dalla tabella volantino_prodotti
    prodotti_raw = conn.execute(
        """
        SELECT * 
        FROM volantino_prodotti 
        WHERE volantino_id = ? AND eliminato = 0
        ORDER BY id ASC
        """, 
        (volantino_id,)
    ).fetchall()

    conn.close()

    volantino_dict = dict(volantino)

    # Numero fisso di slot (3x3)
    cols, rows = 3, 3
    max_slots = cols * rows  # 9

    # ✅ Se non c’è layout_json → genera la griglia base coi prodotti
    if not volantino_dict.get("layout_json"):
        grid = []
        for i in range(max_slots):
            col = i % cols
            row = i // cols
            x = 50 + col * 250   # spaziatura coerente col template
            y = 50 + row * 280

            prodotto = dict(prodotti_raw[i]) if i < len(prodotti_raw) else {}
            nome = prodotto.get("nome", "")
            prezzo = prodotto.get("prezzo", "")
            immagine = prodotto.get("immagine", "")

            grid.append({
                "type": "group",
                "objects": [
                    {
                        "type": "rect",
                        "left": 0, "top": 0,
                        "width": 200, "height": 240,
                        "fill": "#ffffff",
                        "stroke": "#cccccc",
                        "strokeWidth": 1
                    },
                    # Nome prodotto
                    {
                        "type": "text",
                        "text": nome,
                        "left": 100, "top": 190,
                        "fontSize": 14,
                        "originX": "center",
                        "textAlign": "center"
                    },
                    # Prezzo prodotto
                    {
                        "type": "text",
                        "text": f"€ {prezzo}" if prezzo else "",
                        "left": 100, "top": 215,
                        "fontSize": 18,
                        "fill": "red",
                        "originX": "center",
                        "textAlign": "center"
                    }
                ],
                "left": x,
                "top": y,
                "width": 200,
                "height": 240,
                "metadata": {
                    "id": prodotto.get("id"),
                    "nome": nome,
                    "prezzo": prezzo,
                    "url": url_for("static", filename=f"uploads/volantino_prodotti/{immagine}") if immagine else "",
                    "lascia_vuota": prodotto.get("lascia_vuota", 0)
                }
            })

        volantino_dict["layout_json"] = json.dumps({"objects": grid}, ensure_ascii=False)

    else:
        # 👉 Se layout_json esiste, lo normalizzo
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
        num_prodotti=max_slots  # ora 9
    )



@app.route('/volantini/<int:volantino_id>/salva_layout', methods=['POST'])
@login_required
def salva_layout_volantino(volantino_id):
    """Salva il layout del volantino in formato JSON nel DB e riattiva prodotti eliminati presenti nel layout"""

    import json

    data = request.get_json(silent=True)
    if not data or "layout" not in data:
        return jsonify({"success": False, "message": "❌ Nessun layout ricevuto"}), 400

    layout = data.get("layout")

    # Normalizza layout
    try:
        if isinstance(layout, list):
            layout = {"objects": layout}
        elif not isinstance(layout, dict):
            return jsonify({"success": False, "message": "❌ Formato layout non valido"}), 400

        if "objects" not in layout:
            layout["objects"] = []

        layout_json = json.dumps(layout, ensure_ascii=False)

    except Exception as e:
        return jsonify({"success": False, "message": f"❌ Errore nella serializzazione JSON: {e}"}), 500

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 1️⃣ Salva layout nel volantino
        cursor.execute(
            "UPDATE volantini SET layout_json = ? WHERE id = ?",
            (layout_json, volantino_id)
        )

        # 2️⃣ Riattiva prodotti eliminati presenti nella griglia
        for obj in layout["objects"]:
            metadata = obj.get("metadata", {})
            prod_id = metadata.get("id")
            if prod_id:
                # Riattiva solo se era eliminato
                cursor.execute(
                    "UPDATE volantino_prodotti SET eliminato = 0 WHERE id = ? AND eliminato = 1",
                    (prod_id,)
                )

        conn.commit()
        updated = cursor.rowcount

    except Exception as e:
        return jsonify({"success": False, "message": f"❌ Errore DB: {e}"}), 500

    finally:
        conn.close()

    if updated == 0:
        return jsonify({"success": False, "message": "❌ Volantino non trovato"}), 404

    return jsonify({"success": True, "message": "✅ Layout salvato correttamente"})


from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
import os
from datetime import datetime

UPLOAD_FOLDER_PROMO = os.path.join("static", "uploads", "promolampo")
UPLOAD_FOLDER_VOLANTINI = os.path.join("static", "uploads", "volantini")
os.makedirs(UPLOAD_FOLDER_VOLANTINI, exist_ok=True)

# ----------------------------------------------------------------------
# LISTA VOLANTINI + PROMO LAMPO
# ----------------------------------------------------------------------
@app.route("/volantini")
@login_required
def lista_volantini_completa():
    conn = get_db_connection()
    
    # Volantini
    volantini = conn.execute(
        "SELECT id, titolo, sfondo, data_creazione FROM volantini ORDER BY data_creazione DESC"
    ).fetchall()

    # Promo lampo
    promo_lampo = conn.execute(
        "SELECT id, nome, prezzo, immagine, sfondo, data_creazione FROM promo_lampo ORDER BY data_creazione DESC"
    ).fetchall()

    conn.close()

    return render_template(
        "04_volantino/01_lista_volantini.html",
        volantini=volantini,
        promo_lampo=promo_lampo,
    )


# ----------------------------------------------------------------------
# NUOVA PROMO LAMPO
# ----------------------------------------------------------------------
@app.route("/promo-lampo/nuovo", methods=["GET", "POST"])
@login_required
def nuova_promo_lampo():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        prezzo = request.form.get("prezzo", "").strip()
        immagine_file = request.files.get("immagine")
        sfondo_file = request.files.get("sfondo")  # nuovo campo

        if not nome or not prezzo or not immagine_file or not sfondo_file:
            flash("❌ Tutti i campi sono obbligatori", "danger")
            return redirect(url_for("nuova_promo_lampo"))

        try:
            prezzo = float(prezzo)
        except ValueError:
            flash("❌ Prezzo non valido", "danger")
            return redirect(url_for("nuova_promo_lampo"))

        # 🔹 Salva immagine prodotto
        os.makedirs(UPLOAD_FOLDER_PROMO, exist_ok=True)

        filename_prod = secure_filename(immagine_file.filename)
        immagine_nome = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename_prod}"
        immagine_file.save(os.path.join(UPLOAD_FOLDER_PROMO, immagine_nome))

        # 🔹 Salva sfondo volantino
        filename_sfondo = secure_filename(sfondo_file.filename)
        sfondo_nome = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename_sfondo}"
        sfondo_file.save(os.path.join(UPLOAD_FOLDER_PROMO, sfondo_nome))

        # 🔹 Inserisci in DB
        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO promo_lampo (nome, prezzo, immagine, sfondo, data_creazione)
            VALUES (?, ?, ?, ?, ?)
            """,
            (nome, prezzo, immagine_nome, sfondo_nome, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        conn.close()

        flash("✅ Promo Lampo creata con successo!", "success")
        return redirect(url_for("lista_volantini_completa"))

    return render_template("04_volantino/08_nuova_promo_lampo.html")


# ----------------------------------------------------------------------
# MODIFICA PROMO LAMPO
# ----------------------------------------------------------------------
@app.route("/promo-lampo/modifica/<int:promo_id>", methods=["GET", "POST"])
@login_required
def modifica_promo_lampo(promo_id):
    conn = get_db_connection()
    promo = conn.execute(
        "SELECT * FROM promo_lampo WHERE id=?", (promo_id,)
    ).fetchone()

    if not promo:
        conn.close()
        flash("❌ Promo Lampo non trovata", "danger")
        return redirect(url_for("lista_volantini_completa"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        prezzo = request.form.get("prezzo", "").strip()
        immagine_file = request.files.get("immagine")

        try:
            prezzo = float(prezzo)
        except ValueError:
            flash("❌ Prezzo non valido", "danger")
            return redirect(url_for("modifica_promo_lampo", promo_id=promo_id))

        immagine_nome = promo["immagine"]
        if immagine_file and immagine_file.filename.strip():
            # elimina vecchia immagine
            old_path = os.path.join(UPLOAD_FOLDER_PROMO, immagine_nome)
            if os.path.exists(old_path):
                os.remove(old_path)

            # salva nuova immagine
            filename = secure_filename(immagine_file.filename)
            immagine_nome = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            immagine_file.save(os.path.join(UPLOAD_FOLDER_PROMO, immagine_nome))

        # aggiorna DB
        conn.execute(
            """
            UPDATE promo_lampo 
            SET nome=?, prezzo=?, immagine=? 
            WHERE id=?
            """,
            (nome, prezzo, immagine_nome, promo_id),
        )
        conn.commit()
        conn.close()

        flash("✅ Promo Lampo aggiornata con successo!", "success")
        return redirect(url_for("lista_volantini_completa"))

    conn.close()
    return render_template("04_volantino/09_modifica_promo_lampo.html", promo=promo)


# ----------------------------------------------------------------------
# ELIMINA PROMO LAMPO
# ----------------------------------------------------------------------
@app.route("/promo-lampo/elimina/<int:promo_id>", methods=["POST"])
@login_required
def elimina_promo_lampo(promo_id):
    conn = get_db_connection()
    promo = conn.execute(
        "SELECT immagine FROM promo_lampo WHERE id=?", (promo_id,)
    ).fetchone()

    if not promo:
        conn.close()
        flash("❌ Promo Lampo non trovata", "danger")
        return redirect(url_for("lista_volantini_completa"))

    # elimina immagine
    if promo["immagine"]:
        img_path = os.path.join(UPLOAD_FOLDER_PROMO, promo["immagine"])
        if os.path.exists(img_path):
            os.remove(img_path)

    # elimina record
    conn.execute("DELETE FROM promo_lampo WHERE id=?", (promo_id,))
    conn.commit()
    conn.close()

    flash("✅ Promo Lampo eliminata con successo!", "success")
    return redirect(url_for("lista_volantini_completa"))

@app.route("/promo-lampo/<int:promo_id>/editor", methods=["GET", "POST"])
@login_required
def editor_promo_lampo(promo_id):
    conn = get_db_connection()
    promo = conn.execute("SELECT * FROM promo_lampo WHERE id = ?", (promo_id,)).fetchone()
    conn.close()

    if not promo:
        flash("❌ Promo Lampo non trovata", "danger")
        return redirect(url_for("lista_volantini_completa"))

    # Se serve gestire POST per aggiornamenti
    if request.method == "POST":
        # Qui puoi salvare layout o modifiche via editor
        pass

    # Creiamo un array con un solo "prodotto", direttamente dai campi della promo
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

@app.route("/salva_layout/<int:promo_id>", methods=["POST"])
def salva_layout(promo_id):
    data = request.get_json()
    layout = data.get("layout")
    if not layout:
        return jsonify({"status": "error", "message": "Layout mancante"}), 400

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE promo_lampo SET layout = ? WHERE id = ?", (layout, promo_id))
        conn.commit()
        conn.close()
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

# ============================
# AVVIO APP
# ============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)



