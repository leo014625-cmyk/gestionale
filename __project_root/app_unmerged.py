import os
import urllib.parse
import tempfile
from dotenv import load_dotenv
load_dotenv()
import os
import sqlite3
import json
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, jsonify
from datetime import datetime, timedelta
from jinja2 import FileSystemLoader
from collections import defaultdict
from werkzeug.utils import secure_filename
from dateutil.relativedelta import relativedelta
from PIL import Image, ImageDraw
import psycopg2
from psycopg2.extras import RealDictCursor
from dateutil.relativedelta import relativedelta
from collections import defaultdict
from flask_sqlalchemy import SQLAlchemy
import threading
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
# Carica variabili dal file .env
load_dotenv()
# ============================
# PATH STATIC E PLACEHOLDER
# ============================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "_templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")  # STATIC dentro il progetto
BASE_DIR = os.path.abspath(os.path.dirname(__file__))  # __project_root
TEMPLATES_DIR = os.path.join(BASE_DIR, "_templates")  # cartella _templates dentro __project_root
# Static si trova in ../gestionale/static
STATIC_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "gestionale", "static"))
NO_IMAGE_PATH = os.path.join(STATIC_DIR, "no-image.png")
# Cartelle upload
UPLOAD_FOLDER_VOLANTINI = os.path.join(STATIC_DIR, "uploads", "volantini")
UPLOAD_FOLDER_VOLANTINI_PRODOTTI = os.path.join(STATIC_DIR, "uploads", "volantino_prodotti")
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
    os.makedirs(STATIC_DIR, exist_ok=True)
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

# Forza loader Jinja sulla cartella corretta
app.jinja_loader = FileSystemLoader(TEMPLATES_DIR)
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
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # limite upload 50MB (serve per volantini multi-pagina con thumbnail base64)
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
    tipo = db.Column(db.String(50), default='volantino')
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
@app.context_processor
def inject_now():
    """Rende disponibile current_year e variabili per notifiche temporali in tutti i template"""
    oggi = datetime.now()
    return {
        'current_year': oggi.year,
        'is_saturday': (oggi.weekday() == 5),
        'is_first_of_month': (oggi.day == 1)
    }

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
        oggi = datetime.now()
        oggi_data = oggi.date()
        trenta_giorni_fa = oggi - timedelta(days=30)
        primo_giorno_mese_corrente = datetime(anno_corrente, mese_corrente, 1)
        primo_giorno_prossimo_mese = primo_giorno_mese_corrente + relativedelta(months=1)
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
        # Fatturato totale corrente
        cur.execute('SELECT COALESCE(SUM(totale),0) as totale FROM fatturato WHERE mese=%s AND anno=%s',
                    (mese_corrente, anno_corrente))
        fatturato_corrente = cur.fetchone()['totale']
        # === Fatturato mese precedente ===
        cur.execute(
            "SELECT COALESCE(SUM(totale),0) AS totale FROM fatturato WHERE mese=%s AND anno=%s",
            (mese_prec, anno_prec)
        )
        # Fatturato precedente
        mese_prec = 12 if mese_corrente == 1 else mese_corrente - 1
        anno_prec = anno_corrente - 1 if mese_corrente == 1 else anno_corrente
        cur.execute('SELECT COALESCE(SUM(totale),0) as totale FROM fatturato WHERE mese=%s AND anno=%s',
                    (mese_prec, anno_prec))
        fatturato_precedente = cur.fetchone()['totale']
        variazione_fatturato = None
        if fatturato_precedente != 0:
            variazione_fatturato = ((fatturato_corrente - fatturato_precedente) / fatturato_precedente) * 100
        # ======================================================================================
        # === CLIENTI NUOVI (ULTIMI 30 GIORNI)
        # ======================================================================================
        cur.execute("""
        # Clienti nuovi
        cur.execute('''
            SELECT id, nome, zona, data_registrazione
            FROM clienti
            WHERE data_registrazione >= %s
        """, (trenta_giorni_fa,))
            WHERE data_registrazione >= %s AND data_registrazione < %s
        ''', (primo_giorno_mese_corrente, primo_giorno_prossimo_mese))
        clienti_nuovi_rows = cur.fetchall()
        clienti_nuovi_dettaglio = [
            {
                "id": c["id"],
                "nome": c["nome"],
                "data_registrazione": c["data_registrazione"]
            }
            {'nome': c['nome'], 'data_registrazione': c['data_registrazione']}
            for c in clienti_nuovi_rows
        ]
        clienti_nuovi = len(clienti_nuovi_rows)
        # ======================================================================================
        # === CLIENTI ATTIVI / BLOCCATI / INATTIVI
        # ======================================================================================
        cur.execute("SELECT id, nome, stato FROM clienti ORDER BY nome")
        # Clienti bloccati / inattivi
        cur.execute('SELECT id, nome FROM clienti')
        clienti_rows = cur.fetchall()
        clienti_bloccati_dettaglio = []
        clienti_bloccati_inattivi_dettaglio = []
        for cliente in clienti_rows:
            cur.execute('SELECT COALESCE(SUM(totale),0) FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                        (cliente['id'], mese_corrente, anno_corrente))
            totale_corrente = cur.fetchone()['coalesce']
            cur.execute("""
                SELECT MAX(make_date(anno, mese, 1)) AS ultimo_fatturato
                FROM fatturato
                WHERE cliente_id = %s
            """, (cliente["id"],))
            cur.execute('SELECT COALESCE(SUM(totale),0) FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                        (cliente['id'], mese_prec, anno_prec))
            totale_prec = cur.fetchone()['coalesce']
            ultimo = cur.fetchone()["ultimo_fatturato"]
            mese_due_fa = 12 if mese_corrente <= 2 else mese_corrente - 2
            anno_due_fa = anno_corrente - 1 if mese_corrente <= 2 else anno_corrente
            cur.execute('SELECT COALESCE(SUM(totale),0) FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                        (cliente['id'], mese_due_fa, anno_due_fa))
            totale_due_mesi_fa = cur.fetchone()['coalesce']
            if ultimo:
                giorni = (oggi_data - ultimo).days
            if totale_corrente > 0:
                stato = 'attivo'
            elif totale_prec == 0 and totale_due_mesi_fa == 0:
                stato = 'inattivo'
            else:
                giorni = 9999   # se non ha fatturato: inattivo vecchissimo
                ultimo = None
                stato = 'bloccato'
            # Logica stato
            stato_db = cliente.get("stato", "automatico")
            if stato_db and stato_db != 'automatico':
                stato = stato_db
            else:
                if giorni <= 60:
                    stato = "attivo"
                elif 61 <= giorni <= 91:
                    stato = "bloccato"
                else:
                    stato = "inattivo"
            if stato == 'bloccato':
                clienti_bloccati_dettaglio.append({'nome': cliente['nome']})
            if stato in ('bloccato', 'inattivo'):
                clienti_bloccati_inattivi_dettaglio.append({'nome': cliente['nome'], 'stato': stato})
            info = {
                "id": cliente["id"],
                "nome": cliente["nome"],
                "ultimo_fatturato": ultimo,
                "giorni": giorni
            }
        clienti_bloccati = len(clienti_bloccati_dettaglio)
        clienti_bloccati_inattivi = len(clienti_bloccati_inattivi_dettaglio)
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
        # Prodotti inseriti
        cur.execute('''
            SELECT c.nome AS cliente, p.nome AS prodotto, cp.data_operazione
            FROM clienti_prodotti cp
            JOIN clienti c ON cp.cliente_id = c.id
            JOIN prodotti p ON cp.prodotto_id = p.id
            WHERE cp.lavorato = TRUE
              AND cp.data_operazione >= %s
        """, (trenta_giorni_fa,))
            WHERE cp.lavorato = 1
              AND cp.data_operazione >= %s AND cp.data_operazione < %s
        ''', (primo_giorno_mese_corrente, primo_giorno_prossimo_mese))
        prodotti_inseriti_rows = cur.fetchall()
        prodotti_inseriti = [
            {
                "cliente": r["cliente"],
                "prodotto": r["prodotto"],
                "data_operazione": r["data_operazione"]
            }
            {'cliente': r['cliente'], 'prodotto': r['prodotto'], 'data_operazione': r['data_operazione']}
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
        # Prodotti rimossi
        cur.execute('''
            SELECT c.nome AS cliente, p.nome AS prodotto, pr.data_rimozione
            FROM prodotti_rimossi pr
            JOIN prodotti p ON pr.prodotto_id = p.id
            JOIN clienti c ON pr.cliente_id = c.id
            WHERE pr.data_rimozione >= %s
        """, (trenta_giorni_fa,))
            JOIN clienti_prodotti cp ON cp.prodotto_id = p.id
            JOIN clienti c ON cp.cliente_id = c.id
            WHERE pr.data_rimozione >= %s AND pr.data_rimozione < %s
        ''', (primo_giorno_mese_corrente, primo_giorno_prossimo_mese))
        prodotti_rimossi_rows = cur.fetchall()
        prodotti_rimossi = [
            {
                "cliente": r["cliente"],
                "prodotto": r["prodotto"],
                "data_operazione": r["data_rimozione"]
            }
            {'cliente': r['cliente'], 'prodotto': r['prodotto'], 'data_operazione': r['data_rimozione']}
            for r in prodotti_rimossi_rows
        ]
        # ======================================================================================
        # === FATTURATO 12 MESI
        # ======================================================================================
        cur.execute("""
        prodotti_totali_mese = len(prodotti_inseriti)
        prodotti_rimossi_mese = len(prodotti_rimossi)
        # Fatturato ultimi 12 mesi
        cur.execute('''
            SELECT anno, mese, COALESCE(SUM(totale),0) as totale
            FROM fatturato
            GROUP BY anno, mese
            ORDER BY anno DESC, mese DESC
            LIMIT 12
        """)
        ''')
        fatturato_mensile_rows = cur.fetchall()
        fatturato_mensile = {f"{r['anno']}-{r['mese']:02}": r['totale'] for r in reversed(fatturato_mensile_rows)}
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
        # === VISITE DI OGGI
        # ======================================================================================
        cur.execute("""
            SELECT v.id, c.nome as cliente_nome, v.ora_visita, v.completata 
            FROM visite v 
            JOIN clienti c ON v.cliente_id = c.id 
            WHERE v.data_visita = %s
            ORDER BY v.ora_visita DESC
        """, (oggi_data,))
        visite_oggi = cur.fetchall()
        # ======================================================================================
        # === NOTIFICHE
        # ======================================================================================
        notifiche = []
        # Alert Fatturato Mese Precedente Mancante
        if fatturato_corrente == 0:
            mesi_nomi = ['Dicembre', 'Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio', 'Giugno', 'Luglio', 'Agosto', 'Settembre', 'Ottobre', 'Novembre']
            mese_str = mesi_nomi[mese_corrente] if mese_corrente < 12 else mesi_nomi[0]
            notifiche.append({
                "id": "fatturato_mancante",
                "titolo": "Fatturato Mancante",
                "descrizione": f"Fatturato di {mese_str} non inserito.",
                "data": datetime.now(),
                "tipo": "danger",
                "letto": False
            })
        if clienti_attivi_dettaglio:
            notifiche.append({
                "id": "aggiorna_fatturato",
                "titolo": "Aggiorna Fatturato",
                "descrizione": "Ricorda di aggiornare il fatturato dei clienti attivi.",
                "data": datetime.now(),
                "tipo": "warning",
                "clienti": clienti_attivi_dettaglio,
                "letto": False
            })
        if clienti_inattivi_dettaglio:
            notifiche.append({
                "id": "clienti_inattivi",
                "titolo": "Clienti Inattivi",
                "descrizione": "Verifica eventuali aggiornamenti.",
                "data": datetime.now(),
                "tipo": "secondary",
                "clienti": clienti_inattivi_dettaglio,
                "letto": False
            })
        # Filtro notifiche nascoste salva in session
        from flask import session
        dismissed = session.get('dismissed_notifiche', [])
        notifiche = [n for n in notifiche if n.get('id') not in dismissed and n['titolo'] not in dismissed]
    # ----------------------------------------------
    # RENDER TEMPLATE
    # ----------------------------------------------
    return render_template(
        "02_index.html",
        '02_index.html',
        variazione_fatturato=variazione_fatturato,
        clienti_nuovi=clienti_nuovi,
        clienti_nuovi_dettaglio=clienti_nuovi_dettaglio,
        clienti_bloccati=clienti_bloccati_dettaglio,
        clienti_bloccati=clienti_bloccati,
        clienti_bloccati_dettaglio=clienti_bloccati_dettaglio,
        clienti_attivi_dettaglio=clienti_attivi_dettaglio,
        clienti_inattivi=clienti_inattivi_dettaglio,
        clienti_bloccati_inattivi=clienti_bloccati_inattivi,
        clienti_bloccati_inattivi_dettaglio=clienti_bloccati_inattivi_dettaglio,
        prodotti_totali_mese=prodotti_totali_mese,
        prodotti_rimossi_mese=prodotti_rimossi_mese,
        prodotti_inseriti=prodotti_inseriti,
        prodotti_rimossi=prodotti_rimossi,
        fatturato_mensile=fatturato_mensile,
        fatturato_per_zona=fatturato_per_zona,
        notifiche=notifiche,
        visite_oggi=visite_oggi,
        is_saturday=(datetime.today().weekday() == 5)
        fatturato_mensile=fatturato_mensile
    )
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
    mese_corrente = oggi.month
    anno_corrente = oggi.year
    anno_due_fa = anno_corrente - 1 if mese_corrente <= 2 else anno_corrente
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
                c.telefono,
                c.giorno_visita_standard,
                c.frequenza_visita,
                c.stato,
                COALESCE(SUM(f.totale), 0) AS fatturato_totale,
                MAX(make_date(f.anno, f.mese, 1)) AS ultimo_fatturato,
                COALESCE(SUM(CASE WHEN f.mese = %s AND f.anno = %s THEN f.totale ELSE 0 END), 0) AS fatt_prev
            FROM clienti c
            LEFT JOIN fatturato f ON f.cliente_id = c.id
        '''
        cur = db.cursor()
        query = 'SELECT id, nome, zona FROM clienti'
        condizioni = []
        params = [mese_ref, anno_ref, mese_ref_prev, anno_ref_prev]
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
        query += '''
            GROUP BY c.id, c.nome, c.zona, c.telefono, c.giorno_visita_standard, c.frequenza_visita, c.stato
        '''
        # ordinamento base (poi rifiniamo in Python come prima)
        query += ' ORDER BY c.nome'
        cur.execute(query, params)
        rows = cur.fetchall()
        clienti_rows = cur.fetchall()
        clienti_list = []
        stati_clienti = {}
        andamento_clienti = {}
        for r in rows:
            ultimo = r['ultimo_fatturato']
            fatt_ref_val = float(r['fatt_ref'] or 0)
        for cliente in clienti_rows:
            cur.execute('SELECT COALESCE(SUM(totale),0) AS totale FROM fatturato WHERE cliente_id=%s', (cliente['id'],))
            fatturato_totale = cur.fetchone()['totale']
            # Stato cliente in base all'ultimo fatturato
            if ultimo:
                giorni_trascorsi = (oggi.date() - ultimo).days
                if giorni_trascorsi <= 60:
                    stato = 'attivo'
                elif 61 <= giorni_trascorsi <= 91:
                    stato = 'bloccato'
                stato = 'inattivo'
            cur.execute('SELECT COALESCE(SUM(totale),0) FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                        (cliente['id'], mese_corrente, anno_corrente))
            totale_mese_corrente = cur.fetchone()['coalesce']
            stati_clienti[r['id']] = stato
            cur.execute('SELECT COALESCE(SUM(totale),0) FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                        (cliente['id'], mese_prec, anno_prec))
            totale_mese_prec = cur.fetchone()['coalesce']
            # filtro stato cliente
            if stato_filtro and stato != stato_filtro:
                continue
            cur.execute('SELECT COALESCE(SUM(totale),0) FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                        (cliente['id'], mese_due_fa, anno_due_fa))
            totale_due_mesi_fa = cur.fetchone()['coalesce']
            # andamento
            fatt_prev = float(r['fatt_prev'] or 0)
            stato = ('attivo' if totale_mese_corrente > 0
                     else 'inattivo' if totale_mese_prec == 0 and totale_due_mesi_fa == 0
                     else 'bloccato')
            stati_clienti[cliente['id']] = stato
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
                'ultimo_fatturato': ultimo,
                '_fatt_ref_val': fatt_ref_val
                'id': cliente['id'],
                'nome': cliente['nome'],
                'zona': cliente['zona'],
                'fatturato_totale': fatturato_totale,
                'fatturato_corrente': totale_mese_corrente,
                'fatturato_precedente': totale_mese_prec,
                'fatturato_due_mesi_fa': totale_due_mesi_fa
            })
        # Ordinamento come prima
        if order == 'fatturato':
            clienti_list.sort(key=lambda c: c['fatturato_totale'], reverse=True)
        else:
            clienti_list.sort(key=lambda c: (c['zona'] or '', c['nome']))
        # Raggruppamento per zona e per STATO
        clienti_per_zona = defaultdict(list)
        clienti_attivi = []
        clienti_bloccati = []
        clienti_inattivi = []
        
        # KPI Globali
        kpi = {
            'totale_clienti': 0,
            'clienti_attivi': 0,
            'clienti_bloccati': 0,
            'clienti_inattivi': 0,
            'fatturato_mese_corrente': 0.0,
            'fatturato_mese_prec': 0.0
        }
        for c in clienti_list:
            clienti_per_zona[c['zona']].append(c)
            st = stati_clienti.get(c['id'])
            
            if st == 'attivo':
                clienti_attivi.append(c)
                kpi['clienti_attivi'] += 1
            elif st == 'bloccato':
                clienti_bloccati.append(c)
                kpi['clienti_bloccati'] += 1
            else:
                clienti_inattivi.append(c)
                kpi['clienti_inattivi'] += 1
                
            kpi['totale_clienti'] += 1
                kpi['fatturato_mese_corrente'] += float(c['_fatt_ref_val'])
                kpi['fatturato_mese_prec'] += float(c['_fatt_ref_prec_val'])
        # Previsione Fatturato Mese Successivo
        somma_corrente = kpi['fatturato_mese_corrente']
        somma_prec = kpi['fatturato_mese_prec']
        andamento_medio = (somma_corrente - somma_prec) / somma_prec if somma_prec > 0 else 0.0
        # Previsione = Somma Corrente aumentata del fatturato dell'andamento medio
        kpi['fatturato_previsto'] = somma_corrente * (1 + andamento_medio)
        is_saturday = datetime.today().weekday() == 0  # wait! Monday=0, Saturday=5. I'll use target 5
        is_saturday = datetime.today().weekday() == 5
        clienti_da_aggiornare = []
        if is_saturday:
            cur.execute("""
                SELECT c.id, c.nome, MAX(cp.data_operazione) as last_d
                FROM clienti c
                LEFT JOIN clienti_prodotti cp ON c.id = cp.cliente_id
                GROUP BY c.id, c.nome
                HAVING MAX(cp.data_operazione) IS NULL OR MAX(cp.data_operazione) < NOW() - INTERVAL '7 days'
                LIMIT 10
            """)
            clienti_da_aggiornare = cur.fetchall()
        # Recupero zone per select filtro
        cur.execute('SELECT DISTINCT zona FROM clienti')
        zone = cur.fetchall()
        zone_lista = sorted([z['zona'] for z in zone if z['zona']])
        # Check inserimento fatturato mese precedente
        cur.execute("SELECT COUNT(*) FROM fatturato WHERE mese = %s AND anno = %s", (mese_ref_prev, anno_ref_prev))
        prev_month_count = cur.fetchone()['count']
        avviso_mese_prec_mancante = prev_month_count == 0
        # ----------------------------------------------------
        # Query 2026 per la modale live
        # ----------------------------------------------------
        cur.execute("SELECT cliente_id, mese, totale FROM fatturato WHERE anno = 2026")
        f_rows = cur.fetchall()
        fatturato_2026 = {}
        for fr in f_rows:
            cid = fr['cliente_id']
            if cid not in fatturato_2026:
                fatturato_2026[cid] = {}
            fatturato_2026[cid][fr['mese']] = float(fr['totale'])
        # ----------------------------------------------------
        # Aggregati per Grafici Landing Page Clienti
        # ----------------------------------------------------
        fatturato_globale_mensile_2026 = [0.0] * 12
        for fr in f_rows:
            m = fr['mese'] - 1
            if 0 <= m < 12:
                fatturato_globale_mensile_2026[m] += float(fr['totale'])
        clienti_dist_zona = {}
        for z, c_list in clienti_per_zona.items():
            client_name = z if z else 'Senza Zona'
            clienti_dist_zona[client_name] = len(c_list)
    return render_template(
        '01_clienti/01_clienti.html',
        clienti_per_zona=clienti_per_zona,
        zone=zone_lista,
        zona_filtro=zona_filtro,
        order=order,
        search=search,
        stati_clienti=stati_clienti,
        andamento_clienti=andamento_clienti,
        stato_filtro=stato_filtro,
        kpi=kpi,
        fatturato_2026=fatturato_2026,
        clienti_attivi=clienti_attivi,
        clienti_bloccati=clienti_bloccati,
        clienti_inattivi=clienti_inattivi,
        fatturato_globale_2026=fatturato_globale_mensile_2026,
        clienti_dist_zona=clienti_dist_zona,
        avviso_mese_prec_mancante=avviso_mese_prec_mancante,
        mese_ref_prev=mese_ref_prev,
        anno_ref_prev=anno_ref_prev,
        is_saturday=is_saturday,
        clienti_da_aggiornare=clienti_da_aggiornare
        stati_clienti=stati_clienti
    )
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
            
            # Iteriamo per tutti i 12 mesi
            for m_num in range(1, 13):
                field_name = f'fatturato_{m_num}'
                valore = request.form.get(field_name)
                
                if valore and valore.strip() != "":
                    try:
                        totale_d = parse_decimal(valore)
                        if totale_d is not None:
                            # Elimina eventuale record esistente per lo stesso mese/anno
                            cur.execute('DELETE FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s', (id, m_num, anno_i))
                            # Inserisci il nuovo record
                            cur.execute('''
                                INSERT INTO fatturato (cliente_id, mese, anno, totale)
                                VALUES (%s,%s,%s,%s)
                            ''', (id, m_num, anno_i, totale_d))
                            saved_months.append(str(m_num))
                    except (ValueError, TypeError):
                        continue # Salta se il valore non è un numero valido
            
            db.commit()
        if saved_months:
            flash(f'Fatturato salvato per {len(saved_months)} mesi nell\'anno {anno_i}.', 'success')
        else:
            flash('Nessun dato inserito.', 'info')
            
    except Exception as e:
        flash(f'Errore salvataggio fatturato: {e}', 'danger')
    return redirect(url_for('clienti'))
@app.route('/clienti/aggiungi', methods=['GET', 'POST'])
@login_required
def nuovo_cliente():
        nuova_zona = request.form.get('nuova_zona', '').strip()
        with get_db() as db:
            from psycopg2.extras import RealDictCursor
            cur = db.cursor(cursor_factory=RealDictCursor)
            cur = db.cursor()
            if zona == 'nuova_zona' and nuova_zona:
                zona = nuova_zona
                cur.execute('SELECT 1 FROM zone WHERE nome=%s', (zona,))
                if not cur.fetchone():
                    cur.execute('INSERT INTO zone (nome) VALUES (%s)', (zona,))
            if not nome:
                flash('Il nome del cliente è obbligatorio.', 'warning')
                return redirect(request.url)
            # Nuovi campi scheduling
            ora_visita = request.form.get('ora_visita_standard')
            frequenza = request.form.get('frequenza_visita', 'settimanale')
            giorni_consegna = ",".join(request.form.getlist('giorni_consegna[]'))
            stato = request.form.get('stato', 'automatico')
            now = datetime.now()
            cur.execute('''
                INSERT INTO clienti (nome, zona, data_registrazione, giorno_visita_standard, giorni_consegna_standard, ora_visita_standard, frequenza_visita, stato) 
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            ''', (nome, zona, now, giorno_visita or None, giorni_consegna or None, ora_visita or None, frequenza, stato))
            cur.execute('INSERT INTO clienti (nome, zona, data_registrazione) VALUES (%s,%s,%s) RETURNING id',
                        (nome, zona, now))
            cliente_id = cur.fetchone()['id']
            # Inserimento Fatturato Multiplo
            mesi = request.form.getlist('mese[]')
            anni = request.form.getlist('anno[]')
            fatturati = request.form.getlist('fatturato_mensile[]')
            prodotti_scelti = request.form.getlist('prodotti[]')
            for prodotto_id in prodotti_scelti:
                cur.execute('''
                    INSERT INTO clienti_prodotti (cliente_id, prodotto_id, lavorato, data_operazione)
                    VALUES (%s,%s,1,%s)
                ''', (cliente_id, prodotto_id, datetime.now()))
            ha_errori_fatturato = False
            for m, a, f in zip(mesi, anni, fatturati):
                if m and a and f:
                    try:
                        cur.execute('INSERT INTO fatturato (cliente_id, mese, anno, totale) VALUES (%s,%s,%s,%s)',
                                    (cliente_id, int(m), int(a), float(f)))
                    except ValueError:
                        ha_errori_fatturato = True
            mese = request.form.get('mese')
            anno = request.form.get('anno')
            fatturato_mensile = request.form.get('fatturato_mensile')
            if mese and anno and fatturato_mensile:
                try:
                    cur.execute('INSERT INTO fatturato (cliente_id, mese, anno, totale) VALUES (%s,%s,%s,%s)',
                                (cliente_id, int(mese), int(anno), float(fatturato_mensile)))
                except ValueError:
                    flash('Dati di fatturato non validi.', 'warning')
            if ha_errori_fatturato:
                flash('Alcuni dati di fatturato non sono validi.', 'warning')
            db.commit()
        flash('Cliente aggiunto con successo.', 'success')
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
    Gestisce anche i separatori migliaia e.g. 1.250,00 -> 1250.00
    """
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    s = s.replace("€", "").replace(" ", "")
    
    # Se ha sia punto che virgola, presumiamo che il segno più a destra sia il separatore decimale
    if "." in s and "," in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # Se ha solo la virgola
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None
# --- FUNZIONE PRINCIPALE MODIFICA CLIENTE ---
@app.route('/clienti/modifica/<int:id>', methods=['GET', 'POST'])
@login_required
def modifica_cliente(id):
    current_datetime = datetime.now()
    oggi = current_datetime.date()  # ✅ Fix: Use .date() for safe subtraction
    def normalize_phone(s: str | None) -> str | None:
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
        cur = db.cursor()
        # 1. CLIENTE
        # Recupera cliente
        cur.execute('SELECT * FROM clienti WHERE id=%s', (id,))
        cliente = cur.fetchone()
        if not cliente:
            flash('Cliente non trovato.', 'danger')
            return redirect(url_for('clienti'))
        # 2. ZONE
        # Zone e categorie
        cur.execute('SELECT * FROM zone ORDER BY nome')
        zone = cur.fetchall()
        # 3. CATEGORIE
        cur.execute('SELECT * FROM categorie ORDER BY nome')
        categorie = cur.fetchall()
        # 4. PRODOTTI
        # Prodotti
        cur.execute('''
            SELECT p.id, p.nome, p.categoria_id, c.nome AS categoria_nome
            FROM prodotti p
            LEFT JOIN categorie c ON p.categoria_id = c.id
            WHERE COALESCE(p.eliminato, FALSE) = FALSE
            ORDER BY c.nome NULLS LAST, p.nome
            ORDER BY c.nome, p.nome
        ''')
        prodotti = cur.fetchall()
        # 5. ASSOCIAZIONI ESISTENTI
        # Prodotti associati al cliente
        cur.execute('''
            SELECT cp.prodotto_id, cp.lavorato, cp.prezzo_attuale, cp.prezzo_offerta,
                   cp.data_inizio_lavorazione, cp.data_fine_lavorazione,
                   fornitori.nome AS fornitore
            FROM clienti_prodotti cp
            JOIN prodotti p ON cp.prodotto_id = p.id
            LEFT JOIN fornitori ON cp.fornitore_id = fornitori.id
            WHERE cp.cliente_id=%s AND COALESCE(p.eliminato, FALSE) = FALSE
            SELECT prodotto_id, lavorato, prezzo_attuale, prezzo_offerta
            FROM clienti_prodotti
            WHERE cliente_id=%s
        ''', (id,))
        prodotti_assoc = cur.fetchall()
        prodotti_lavorati = []
        prezzi_attuali = {}
        prezzi_offerta = {}
        fornitori = {}
        prodotti_data_inizio = {}
        prodotti_data_fine = {}
        prodotti_non_lavorati = [str(p['prodotto_id']) for p in prodotti_assoc if p['lavorato'] == 0]
        prezzi_attuali = {str(p['prodotto_id']): p['prezzo_attuale'] for p in prodotti_assoc}
        prezzi_offerta = {str(p['prodotto_id']): p['prezzo_offerta'] for p in prodotti_assoc}
        for p in prodotti_assoc:
            pid = str(p["prodotto_id"])
            if p["lavorato"]:
                prodotti_lavorati.append(pid)
            prezzi_attuali[pid] = p["prezzo_attuale"]
            prezzi_offerta[pid] = p["prezzo_offerta"]
            fornitori[pid] = p["fornitore"] or ""
            prodotti_data_inizio[pid] = p["data_inizio_lavorazione"]
            prodotti_data_fine[pid] = p["data_fine_lavorazione"]
        # Fatturati cliente
        cur.execute('''
            SELECT id, mese, anno, totale
            FROM fatturato
            WHERE cliente_id=%s
            ORDER BY anno DESC, mese DESC
        ''', (id,))
        fatturati_cliente = cur.fetchall()
        # POST
        if request.method == 'POST':
            nome = (request.form.get('nome') or '').strip()
            zona = request.form.get('zona')
            nuova_zona = (request.form.get('nuova_zona') or '').strip()
            ora_visita = request.form.get('ora_visita_standard')
            frequenza = request.form.get('frequenza_visita', 'settimanale')
            giorni_consegna = ",".join(request.form.getlist('giorni_consegna[]'))
            telefono = normalize_phone(request.form.get('telefono'))
            stato = request.form.get('stato', 'automatico')
            if telefono and (len(telefono) < 8 or len(telefono) > 15):
                flash("⚠️ Telefono non valido.", "warning")
                telefono = None
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
            cur.execute('UPDATE clienti SET nome=%s, zona=%s WHERE id=%s', (nome, zona, id))
            # ✅ LOGICA WHATSAPP COLLEGATO:
            old_tel = normalize_phone(cliente.get("telefono"))
            old_linked = bool(cliente.get("whatsapp_linked") or False)
            new_linked = True if telefono else False
            # Aggiorna prodotti
            prodotti_selezionati = request.form.getlist('prodotti_lavorati[]')
            for prodotto in prodotti:
                pid = str(prodotto['id'])
                lavorato = 1 if pid in prodotti_selezionati else 0
                prezzo_attuale = request.form.get(f'prezzo_attuale[{pid}]') or None
                prezzo_offerta = request.form.get(f'prezzo_offerta[{pid}]') or None
            set_linked_at = None
            if new_linked and (not old_linked or old_tel != telefono):
                set_linked_at = current_datetime
            # Update Cliente
            if new_linked:
                if set_linked_at:
                cur.execute('SELECT prodotto_id FROM clienti_prodotti WHERE cliente_id=%s AND prodotto_id=%s', (id, pid))
                esiste = cur.fetchone()
                if esiste:
                    cur.execute('''
                        UPDATE clienti
                        SET nome=%s, zona=%s, telefono=%s,
                            whatsapp_linked=TRUE, whatsapp_linked_at=%s,
                            giorno_visita_standard=%s, ora_visita_standard=%s,
                            frequenza_visita=%s, giorni_consegna_standard=%s, stato=%s
                        WHERE id=%s
                    ''', (nome, zona, telefono, set_linked_at, giorno_visita or None, ora_visita or None, frequenza, giorni_consegna or None, stato, id))
                        UPDATE clienti_prodotti
                        SET lavorato=%s, prezzo_attuale=%s, prezzo_offerta=%s, data_operazione=%s
                        WHERE cliente_id=%s AND prodotto_id=%s
                    ''', (lavorato, prezzo_attuale, prezzo_offerta, datetime.now(), id, pid))
                else:
                    cur.execute('''
                        UPDATE clienti
                        SET nome=%s, zona=%s, telefono=%s,
                            whatsapp_linked=TRUE,
                            giorno_visita_standard=%s, ora_visita_standard=%s,
                            frequenza_visita=%s, giorni_consegna_standard=%s, stato=%s
                        WHERE id=%s
                    ''', (nome, zona, telefono, giorno_visita or None, ora_visita or None, frequenza, giorni_consegna or None, stato, id))
            else:
                cur.execute('''
                    UPDATE clienti
                    SET nome=%s, zona=%s, telefono=%s,
                        whatsapp_linked=FALSE, whatsapp_linked_at=NULL,
                        giorno_visita_standard=%s, ora_visita_standard=%s,
                        frequenza_visita=%s, giorni_consegna_standard=%s, stato=%s
                    WHERE id=%s
                ''', (nome, zona, None, giorno_visita or None, ora_visita or None, frequenza, giorni_consegna or None, stato, id))
                        INSERT INTO clienti_prodotti
                        (cliente_id, prodotto_id, lavorato, prezzo_attuale, prezzo_offerta, data_operazione)
                        VALUES (%s,%s,%s,%s,%s,%s)
                    ''', (id, pid, lavorato, prezzo_attuale, prezzo_offerta, datetime.now()))
            # Update Prodotti
            selezionati = set(request.form.getlist("prodotti_lavorati[]"))
            for p_info in prodotti:
                pid = str(p_info["id"])
                lavorato_now = pid in selezionati
                
                pz_att = parse_decimal(request.form.get(f"prezzo_attuale[{pid}]"))
                pz_off = parse_decimal(request.form.get(f"prezzo_offerta[{pid}]"))
                f_nome = (request.form.get(f"fornitore[{pid}]") or "").strip() or None
                
                f_id = None
                if f_nome:
                    cur.execute("SELECT id FROM fornitori WHERE nome=%s", (f_nome,))
                    f_row = cur.fetchone()
                    if f_row: f_id = f_row["id"]
            # Aggiorna fatturato
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
                        cur.execute("INSERT INTO fornitori (nome) VALUES (%s) RETURNING id", (f_nome,))
                        f_id = cur.fetchone()["id"]
                        cur.execute('INSERT INTO fatturato (cliente_id,mese,anno,totale) VALUES (%s,%s,%s,%s)',
                                    (id, mese_int, anno_int, importo_float))
                except ValueError:
                    flash('Importo fatturato non valido.', 'warning')
                cur.execute("SELECT id, lavorato FROM clienti_prodotti WHERE cliente_id=%s AND prodotto_id=%s", (id, int(pid)))
                esist = cur.fetchone()
                if esist:
                    v_lav = esist['lavorato']
                    d_fine = current_datetime if (not lavorato_now and v_lav) else None
                    
                    sql = "UPDATE clienti_prodotti SET lavorato=%s, prezzo_attuale=%s, prezzo_offerta=%s, fornitore_id=%s, data_operazione=%s"
                    params = [lavorato_now, pz_att, pz_off, f_id, current_datetime]
                    if d_ini:
                        sql += ", data_inizio_lavorazione=%s, data_fine_lavorazione=NULL"
                        params.append(d_ini)
                    elif d_fine:
                        sql += ", data_fine_lavorazione=%s"
                        params.append(d_fine)
                    
                    sql += " WHERE id=%s"
                    params.append(esist['id'])
                    cur.execute(sql, params)
                else:
                    d_fine = current_datetime if not lavorato_now else None
                    cur.execute('''
                        INSERT INTO clienti_prodotti (cliente_id, prodotto_id, lavorato, prezzo_attuale, prezzo_offerta, fornitore_id, data_operazione, data_inizio_lavorazione, data_fine_lavorazione)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ''', (id, int(pid), lavorato_now, pz_att, pz_off, f_id, current_datetime, d_ini, d_fine))
            # Batch Revenue 2026
            if request.form.get('batch_revenue_2026') == '1':
                for m in range(1, 13):
                    v_raw = request.form.get(f'fatt_gen_mese_{m}')
                    if v_raw:
                        vd = parse_decimal(v_raw)
                        if vd is not None:
                            cur.execute('DELETE FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=2026', (id, m))
                            cur.execute('INSERT INTO fatturato (cliente_id, mese, anno, totale) VALUES (%s,%s,%s,%s)', (id, m, 2026, vd))
            db.commit()
            flash("Cliente aggiornato con successo!", "success")
            aggiorna_fatturato_totale(id)
            flash('Cliente modificato con successo.', 'success')
            return redirect(url_for('clienti'))
        # GET Path
        import_preview_data = _PDF_IMPORT_CACHE.get(f'import_preview_{id}', None)
        show_import_popup = request.args.get('show_import_popup', '0') == '1'
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
        cur.execute('SELECT mese, anno, totale FROM fatturato WHERE cliente_id=%s ORDER BY anno DESC, mese DESC LIMIT 1', (id,))
        ultimo = cur.fetchone()
        mese = ultimo['mese'] if ultimo else None
        anno = ultimo['anno'] if ultimo else None
        importo = ultimo['totale'] if ultimo else None
        zone_nomi = [z['nome'] for z in zone]
        nuova_zona_selected = cliente['zona'] not in zone_nomi
        nuova_zona_value = cliente['zona'] if nuova_zona_selected else ''
        cur.execute('SELECT mese, anno, totale AS importo FROM fatturato WHERE cliente_id=%s ORDER BY anno DESC, mese DESC', (id,))
        fatturati_storico = cur.fetchall()
        telefono_cliente = (cliente.get("telefono") or "")
    return render_template(
        '01_clienti/03_modifica_cliente.html',
        cliente=cliente,
        telefono_cliente=telefono_cliente,
        zone=zone,
        categorie=categorie,
        prodotti=prodotti,
        prodotti_lavorati=prodotti_lavorati,
        prodotti_non_lavorati=prodotti_non_lavorati,
        prezzi_attuali=prezzi_attuali,
        prezzi_offerta=prezzi_offerta,
        prodotti_data_inizio=prodotti_data_inizio,
        prodotti_data_fine=prodotti_data_fine,
        fornitori=fornitori,
        nuova_zona_selected=nuova_zona_selected,
        nuova_zona_value=nuova_zona_value,
        import_preview_data=import_preview_data,
        import_result=import_preview_data,
        show_import_popup=show_import_popup,
        fatturato_mese=mese,
        fatturato_anno=anno,
        fatturato_importo=importo,
        fatturati_storico=fatturati_storico,
        fatturati_cliente=fatturati_cliente,
        current_month=current_datetime.month,
        current_year=current_datetime.year
    )
# ============================
# IMPORT PDF LAVORATI AUTO
# ============================
_PDF_IMPORT_CACHE = {}
@app.route('/clienti/modifica/<int:id>/importa_pdf', methods=['POST'])
@app.route('/clienti/<int:id>')
@login_required
def importa_pdf_lavorati_auto(id):
    if 'pdf' not in request.files:
        flash('Nessun file selezionato.', 'danger')
        return redirect(url_for('modifica_cliente', id=id))
        
    file = request.files['pdf']
    if file.filename == '':
        flash('Nessun file selezionato.', 'danger')
        return redirect(url_for('modifica_cliente', id=id))
        
    if not file.filename.lower().endswith('.pdf'):
        flash('Seleziona un file PDF.', 'danger')
        return redirect(url_for('modifica_cliente', id=id))
def cliente_scheda(id):
    oggi = datetime.today()
    current_month = oggi.month
    current_year = oggi.year
    prev_month = 12 if current_month == 1 else current_month - 1
    prev_year = current_year - 1 if current_month == 1 else current_year
    # Creazione file temporaneo
    import tempfile
    import os
    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        file.save(temp_path)
        
        # 1. ESTREZIONE PRODOTTI
        offerte = parse_offers_from_pdf(temp_path)
        
        prodotti_anteprima = []
        
        with get_db() as db:
            cur = db.cursor(cursor_factory=RealDictCursor)
            for off in offerte:
                codice = off['code']
                nome = off['name']
                prezzo = parse_decimal(off['price'])
                
                # Controlla se esiste già
                cur.execute("""
                    SELECT p.id, p.nome, p.categoria_id, c.nome AS categoria_nome 
                    FROM prodotti p
                    LEFT JOIN categorie c ON p.categoria_id = c.id
                    WHERE p.codice=%s AND COALESCE(p.eliminato, FALSE) = FALSE
                """, (codice,))
                esistente = cur.fetchone()
                
                prodotti_anteprima.append({
                    'codice': codice,
                    'nome_pdf': nome,
                    'nome_sistema': esistente['nome'] if esistente else None,
                    'prezzo_pdf': float(prezzo) if prezzo else 0.0,
                    'categoria_nome': esistente['categoria_nome'] if esistente else None,
                    'nuovo': esistente is None
                })
    with get_db() as db:
        cur = db.cursor()
        cur.execute('SELECT * FROM clienti WHERE id=%s', (id,))
        cliente = cur.fetchone()
        if not cliente:
            flash('Cliente non trovato.', 'danger')
            return redirect(url_for('clienti'))
        _PDF_IMPORT_CACHE[f'import_preview_{id}'] = prodotti_anteprima
        return redirect(url_for('modifica_cliente', id=id, show_import_popup='1'))
    finally:
        os.remove(temp_path)
        cur.execute('''
            SELECT p.id, p.nome, p.categoria_id, COALESCE(c.nome,'–') AS categoria_nome
            FROM prodotti p
            LEFT JOIN categorie c ON p.categoria_id=c.id
            ORDER BY c.nome, p.nome
        ''')
        prodotti = cur.fetchall()
# ============================
# CONFERMA E SALVA IMPORTAZIONE PDF
# ============================
@app.route('/clienti/modifica/<int:id>/conferma_import_pdf', methods=['POST'])
@login_required
def conferma_importazione_pdf(id):
    anteprima = _PDF_IMPORT_CACHE.pop(f'import_preview_{id}', None)
    if not anteprima:
        flash("Sessione scaduta o elaborazione fallita. Ricarica il file.", "danger")
        return redirect(url_for('modifica_cliente', id=id))
        cur.execute('''
            SELECT prodotto_id, lavorato, prezzo_attuale, prezzo_offerta, data_operazione
            FROM clienti_prodotti
            WHERE cliente_id=%s
        ''', (id,))
        prodotti_assoc = cur.fetchall()
        assoc_dict = {p['prodotto_id']: p for p in prodotti_assoc}
    current_datetime = datetime.now()
    count_agg = 0
    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)
        prodotti_nel_pdf = set()
        for item in anteprima:
            codice = item['codice']
            # Leggiamo i valori affinati dal form se presenti, altrimenti usiamo quelli del PDF
            nome_final = request.form.get(f'nome[{codice}]', item['nome_pdf']).strip()
            cat_id_final = parse_int(request.form.get(f'categoria[{codice}]', str(item['categoria_id'] or '')))
            
            prezzo_str = request.form.get(f'prezzo[{codice}]')
            prezzo_final = parse_decimal(prezzo_str) if prezzo_str else item['prezzo_pdf']
            
            f_nome = request.form.get(f'fornitore[{codice}]', '').strip()
            f_id = None
            if f_nome:
                cur.execute("SELECT id FROM fornitori WHERE nome=%s", (f_nome,))
                f_row = cur.fetchone()
                if f_row: f_id = f_row["id"]
                else:
                    cur.execute("INSERT INTO fornitori (nome) VALUES (%s) RETURNING id", (f_nome,))
                    f_id = cur.fetchone()["id"]
            # 1. CERCA O CREA PRODOTTO
            cur.execute("SELECT id, eliminato FROM prodotti WHERE codice=%s", (codice,))
            prod = cur.fetchone()
            
            if prod:
                pid = prod['id']
                # Aggiorna nome e categoria, e riattiva il prodotto in caso fosse stato eliminato
                cur.execute("UPDATE prodotti SET categoria_id=COALESCE(%s, categoria_id), eliminato=FALSE WHERE id=%s", (cat_id_final, pid))
        prodotti_lavorati, prezzi_attuali, prezzi_offerta, prodotti_data = [], {}, {}, {}
        for p in prodotti:
            pid = p['id']
            if pid in assoc_dict:
                lavorato = assoc_dict[pid]['lavorato']
                prezzo_attuale = assoc_dict[pid]['prezzo_attuale']
                prezzo_offerta = assoc_dict[pid]['prezzo_offerta']
                data_op = assoc_dict[pid]['data_operazione']
            else:
                cur.execute("INSERT INTO prodotti (codice, nome, categoria_id) VALUES (%s, %s, %s) RETURNING id", (codice, nome_final, cat_id_final))
                pid = cur.fetchone()['id']
                lavorato = 0
                prezzo_attuale = None
                prezzo_offerta = None
                data_op = None
            prodotti_nel_pdf.add(pid)
            prodotti_lavorati.append(str(pid)) if lavorato == 1 else None
            prezzi_attuali[str(pid)] = prezzo_attuale
            prezzi_offerta[str(pid)] = prezzo_offerta
            prodotti_data[str(pid)] = data_op
            # 2. ASSOCIA AL CLIENTE E AGGIORNA PREZZO ATTUALE e FORNITORE
            cur.execute("SELECT id, lavorato FROM clienti_prodotti WHERE cliente_id=%s AND prodotto_id=%s", (id, pid))
            link = cur.fetchone()
            
            if link:
                lavorato_id = link['id']
                is_lavorato = link['lavorato']
                if not is_lavorato:
                    cur.execute('''
                        UPDATE clienti_prodotti SET lavorato=TRUE, volte_mancante=0, prezzo_attuale=%s, fornitore_id=%s, data_operazione=%s, data_inizio_lavorazione=%s, data_fine_lavorazione=NULL
                        WHERE id=%s
                    ''', (prezzo_final, f_id, current_datetime, current_datetime, lavorato_id))
                else:
                    cur.execute('UPDATE clienti_prodotti SET volte_mancante=0, prezzo_attuale=%s, fornitore_id=%s, data_operazione=%s WHERE id=%s', (prezzo_final, f_id, current_datetime, lavorato_id))
            else:
                cur.execute('''
                    INSERT INTO clienti_prodotti (cliente_id, prodotto_id, lavorato, volte_mancante, prezzo_attuale, fornitore_id, data_operazione, data_inizio_lavorazione)
                    VALUES (%s, %s, TRUE, 0, %s, %s, %s, %s)
                ''', (id, pid, prezzo_final, f_id, current_datetime, current_datetime))
            
            count_agg += 1
        cur.execute('SELECT id, nome FROM categorie ORDER BY nome')
        categorie = [dict(c) for c in cur.fetchall()]
        # 3. INCREMENTA VOLTE MANCANTE PER PRODOTTI NON NEL PDF (MA PROPRIO LAVORATI)
        if prodotti_nel_pdf:
            cur.execute('''
                SELECT id, volte_mancante FROM clienti_prodotti 
                WHERE cliente_id=%s AND lavorato=TRUE AND prodotto_id NOT IN %s
            ''', (id, tuple(prodotti_nel_pdf)))
        else:
            cur.execute('''
                SELECT id, volte_mancante FROM clienti_prodotti 
                WHERE cliente_id=%s AND lavorato=TRUE
            ''', (id,))
        
        missing_links = cur.fetchall()
        for ml in missing_links:
            mid = ml['id']
            miss_count = (ml['volte_mancante'] or 0) + 1
            if miss_count >= 3:
                # Muove a non-lavorato
                cur.execute('''
                    UPDATE clienti_prodotti SET lavorato=FALSE, volte_mancante=%s, data_fine_lavorazione=%s 
                    WHERE id=%s
                ''', (miss_count, current_datetime, mid))
            else:
                cur.execute('UPDATE clienti_prodotti SET volte_mancante=%s WHERE id=%s', (miss_count, mid))
            
        db.commit()
        cur.execute('SELECT COALESCE(SUM(totale),0) AS totale FROM fatturato WHERE cliente_id=%s', (id,))
        fatturato_totale = cur.fetchone()['totale']
    flash(f"Importazione completata: {count_agg} prodotti elaborati.", "success")
    return redirect(url_for('modifica_cliente', id=id))
        cur.execute('SELECT COALESCE(SUM(totale),0) FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                    (id, current_month, current_year))
        totale_corrente = cur.fetchone()['coalesce']
import calendar
        cur.execute('SELECT COALESCE(SUM(totale),0) FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s',
                    (id, prev_month, prev_year))
        totale_prec = cur.fetchone()['coalesce']
@app.route('/clienti/<int:id>')
@login_required
def cliente_scheda(id):
    try:
        oggi = datetime.today().date()
    
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
            # PRODOTTI (✅ SOLO NON ELIMINATI + include CODICE)
            # ====================================
            cur.execute('''
                SELECT
                    p.id,
                    p.codice,
                    p.nome,
                    p.categoria_id,
                    COALESCE(c.nome,'–') AS categoria_nome
                FROM prodotti p
                LEFT JOIN categorie c ON p.categoria_id=c.id
                WHERE COALESCE(p.eliminato, FALSE) = FALSE
                ORDER BY c.nome NULLS LAST, p.nome
            ''')
            prodotti = cur.fetchall()
    
            # Prodotti già assegnati al cliente (✅ ESCLUDI ELIMINATI)
            cur.execute('''
                SELECT
                    cp.prodotto_id,
                    cp.lavorato,
                    cp.volte_mancante,
                    cp.prezzo_attuale,
                    cp.prezzo_offerta,
                    cp.data_operazione,
                    cp.data_inizio_lavorazione,
                    cp.data_fine_lavorazione
                FROM clienti_prodotti cp
                JOIN prodotti p ON cp.prodotto_id = p.id
                WHERE cp.cliente_id=%s
                  AND COALESCE(p.eliminato, FALSE) = FALSE
            ''', (id,))
            prodotti_assoc = cur.fetchall()
        variazione_fatturato_cliente = ((totale_corrente - totale_prec) / totale_prec * 100) if totale_prec else None
        stato_cliente = ('attivo' if totale_corrente > 0 else 'inattivo' if totale_corrente == 0 and totale_prec == 0 else 'bloccato')
            # Ultimo aggiornamento prodotti
            cur.execute("SELECT MAX(data_operazione) AS max_d FROM clienti_prodotti WHERE cliente_id = %s", (id,))
            res_d = cur.fetchone()
            last_product_update = res_d['max_d'] if res_d and res_d['max_d'] else None
        cur.execute('''
            SELECT anno, mese, SUM(totale) AS totale
            FROM fatturato
            WHERE cliente_id=%s
            GROUP BY anno, mese
            ORDER BY anno ASC, mese ASC
        ''', (id,))
        fatturato_mensile = {f"{r['anno']}-{r['mese']:02d}": r['totale'] for r in cur.fetchall()}
            from datetime import timedelta
            prossimo_aggiornamento = last_product_update + timedelta(days=7) if last_product_update else None
    
            assoc_dict = {p['prodotto_id']: p for p in prodotti_assoc}
    
            prodotti_ex_lavorati = []
            prodotti_recenti = []
            prezzi_attuali = {}
            prezzi_offerta = {}
            prodotti_data = {}
            prodotti_data_inizio = {}
            prodotti_data_fine = {}
            volte_mancante_dict = {}
    
            for p in prodotti:
                pid = p['id']
    
                if pid in assoc_dict:
                    lavorato = assoc_dict[pid]['lavorato']
                    prezzi_attuali[str(pid)] = assoc_dict[pid]['prezzo_attuale']
                    prezzi_offerta[str(pid)] = assoc_dict[pid]['prezzo_offerta']
                    prodotti_data[str(pid)] = assoc_dict[pid]['data_operazione']
                    prodotti_data_fine[str(pid)] = assoc_dict[pid]['data_fine_lavorazione']
                    volte_mancante_dict[str(pid)] = assoc_dict[pid].get('volte_mancante', 0)
                else:
                    lavorato = False
                    prezzi_attuali[str(pid)] = None
                    prezzi_offerta[str(pid)] = None
                    prodotti_data_fine[str(pid)] = None
                    volte_mancante_dict[str(pid)] = 0
    
                if lavorato:
                    prodotti_lavorati.append(str(pid))
                    d_in = prodotti_data_inizio[str(pid)]
                    if d_in:
                        d1 = oggi.date() if hasattr(oggi, 'date') else oggi
                        d2 = d_in.date() if hasattr(d_in, 'date') else d_in
                        if (d1 - d2).days <= 30:
                            prodotti_recenti.append(str(pid))
                elif prodotti_data_inizio[str(pid)] is not None and prodotti_data_fine[str(pid)] is not None:
                    prodotti_ex_lavorati.append(str(pid))
    
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
    
                    COALESCE(SUM(CASE WHEN mese=%s AND anno=%s THEN totale ELSE 0 END),0) AS fatt_prec
        cur.execute('''
            SELECT descrizione, data
            FROM (
                SELECT 'Aggiunto prodotto: ' || p.nome AS descrizione, cp.data_operazione AS data
                FROM clienti_prodotti cp JOIN prodotti p ON cp.prodotto_id=p.id
                WHERE cp.cliente_id=%s AND cp.lavorato=1
                UNION ALL
                SELECT 'Rimosso prodotto: ' || p.nome, pr.data_rimozione
                FROM prodotti_rimossi pr JOIN prodotti p ON pr.prodotto_id=p.id
                WHERE pr.cliente_id=%s
                UNION ALL
                SELECT 'Fatturato aggiornato: ' || totale || ' €', datetime(anno || '-' || mese || '-01')
                FROM fatturato
                WHERE cliente_id=%s
            ''', (mese_ref, anno_ref, mese_ref_prec, anno_ref_prec, id))
            fatt_row = cur.fetchone() or {}
    
            fatturato_totale = fatt_row.get("fatturato_totale", 0) or 0
            ultimo_fatturato_date = fatt_row.get("ultimo_fatturato")  # date o None
            fatt_prec = fatt_row.get("fatt_prec", 0) or 0
    
            # Crescita mensile
            if fatt_prec and fatt_prec > 0:
                crescita_mensile = round(((fatt_ref - fatt_prec) / fatt_prec) * 100, 2)
            else:
                crescita_mensile = None
    
            # Stato cliente (coerente con /clienti)
            if ultimo_fatturato_date:
                giorni_ult_fatt = (oggi - ultimo_fatturato_date).days
                if giorni_ult_fatt <= 60:
                    stato_cliente = "attivo"
                elif 61 <= giorni_ult_fatt <= 91:
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
                f"{r['anno']}-{r['mese']:02d}": float(r['totale']) if r['totale'] else 0.0
                for r in cur.fetchall()
            }
    
            # ====================================
            # PROMOZIONI PDF ATTIVE
            # ====================================
            cur.execute("SELECT tipo, prodotto_id FROM promozioni_pdf")
            promozioni = cur.fetchall()
            promo_mensile_ids = [str(p['prodotto_id']) for p in promozioni if p['tipo'] == 'mensile']
            promo_scadenza_ids = [str(p['prodotto_id']) for p in promozioni if p['tipo'] == 'scadenza']
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
            # ====================================
            # CHECKUP MENSILE PRODOTTI
            # ====================================
            checkups = []
            for p in prodotti:
                pid = str(p['id'])
                lavorato = pid in prodotti_lavorati
                d_in = prodotti_data_inizio.get(pid)
                d_out = prodotti_data_fine.get(pid)
                
                if lavorato and d_in:
                    # Ensure date subtraction
                    d1 = oggi.date() if hasattr(oggi, 'date') else oggi
                    d2 = d_in.date() if hasattr(d_in, 'date') else d_in
                    giorni_att = (d1 - d2).days
                    if giorni_att >= 150:  # ~5 mesi
                        checkups.append({
                            "tipo": "attivo",
                            "icona": "bi-info-circle",
                            "colore": "primary",
                            "prodotto": p['nome'],
                            "messaggio": f"Lavora questo prodotto da {giorni_att} giorni. Verifica se la fornitura e i volumi sono ancora ottimali."
                        })
                elif not lavorato and d_out:
                    # Ensure date subtraction
                    d1 = oggi.date() if hasattr(oggi, 'date') else oggi
                    d2 = d_out.date() if hasattr(d_out, 'date') else d_out
                    giorni_perso = (d1 - d2).days
                    if 30 <= giorni_perso <= 180:
                        checkups.append({
                            "tipo": "perso",
                            "icona": "bi-exclamation-triangle",
                            "colore": "warning",
                            "prodotto": p['nome'],
                            "messaggio": f"Non lavora più il prodotto da {giorni_perso} giorni! Assicurati che il prezzo di offerta sia ancora competitivo."
                        })
    
            # ====================================
            # VISITE E SCHEDULING
            # ====================================
            # Ultima visita completata
            cur.execute('''
                SELECT * FROM visite 
                WHERE cliente_id = %s AND completata = TRUE AND data_visita <= %s
                ORDER BY data_visita DESC, ora_visita DESC LIMIT 1
            ''', (id, oggi))
            last_visit = cur.fetchone()
            
            # Visite perse (non completate nel passato)
            cur.execute('''
                SELECT * FROM visite 
                WHERE cliente_id = %s AND completata = FALSE AND data_visita < %s
                ORDER BY data_visita DESC
            ''', (id, oggi))
            missed_visits = cur.fetchall()
            
            # Visite in programma
            cur.execute('''
                SELECT * FROM visite 
                WHERE cliente_id = %s AND completata = FALSE AND data_visita >= %s
                ORDER BY data_visita ASC
            ''', (id, oggi))
            upcoming_visits = cur.fetchall()
    
            # ====================================
            # LOG (✅ ESCLUDI ELIMINATI DAI JOIN)
            # ====================================
            cur.execute('''
                SELECT descrizione, data
                FROM (
                    SELECT 
                        'Aggiunto prodotto: ' || p.nome AS descrizione,
                        cp.data_operazione AS data
                    FROM clienti_prodotti cp 
                    JOIN prodotti p ON cp.prodotto_id=p.id
                    WHERE cp.cliente_id=%s
                      AND cp.lavorato=TRUE
                      AND COALESCE(p.eliminato, FALSE) = FALSE
    
                    UNION ALL
    
                    SELECT 
                        'Rimosso prodotto: ' || p.nome AS descrizione,
                        pr.data_rimozione AS data
                    FROM prodotti_rimossi pr 
                    JOIN prodotti p ON pr.prodotto_id=p.id
                    WHERE pr.cliente_id=%s
                      AND COALESCE(p.eliminato, FALSE) = FALSE
    
                    UNION ALL
    
                    SELECT 
                        'Fatturato aggiornato: ' || totale || ' €' AS descrizione,
                        CAST(make_date(anno, mese, 1) AS TIMESTAMP) AS data
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
                      AND COALESCE(p.eliminato, FALSE) = FALSE
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
            # --- STATS AGGIUNTIVE ---
            cat_count = {}
            for p in prodotti:
                if str(p['id']) in prodotti_lavorati:
                    c_name = p.get('categoria_nome') or 'Altro'
                    cat_count[c_name] = cat_count.get(c_name, 0) + 1
            media_mensile = 0.0
            if fatturato_mensile:
                media_mensile = sum(fatturato_mensile.values()) / len(fatturato_mensile)
        return render_template(
            "01_clienti/04_cliente_scheda.html",
            promo_mensile_ids=promo_mensile_ids,
            promo_scadenza_ids=promo_scadenza_ids,
            cat_count=cat_count,
            media_mensile=media_mensile,
            cliente=cliente,
            categorie=categorie,
            prodotti=prodotti,
            prodotti_ex_lavorati=prodotti_ex_lavorati,
            prodotti_recenti=prodotti_recenti,
            volte_mancante_dict=volte_mancante_dict,
            last_product_update=last_product_update,
            prossimo_aggiornamento=prossimo_aggiornamento,
            log_cliente=log_cliente,
            fatturato_totale=fatturato_totale,
            crescita_mensile=crescita_mensile,
            fatturato_mensile=fatturato_mensile,
            prezzi_attuali=prezzi_attuali,
            prezzi_offerta=prezzi_offerta,
            prodotti_data=prodotti_data,
            prodotti_data_inizio=prodotti_data_inizio,
            prodotti_data_fine=prodotti_data_fine,
            stato_cliente=stato_cliente,
            checkups=checkups,
            last_visit=last_visit,
            missed_visits=missed_visits,
            upcoming_visits=upcoming_visits
        )
    except Exception as e:
        import traceback
        log_path = os.path.join(BASE_DIR, "error_log.txt")
        with open(log_path, "a") as f:
            f.write(f"\n--- ERROR IN CLIENTE_SCHEDA ({datetime.now()}) ---\n")
            f.write(traceback.format_exc())
        flash(f"Errore interno nella scheda cliente: {e}", "danger")
        return redirect(url_for('clienti'))
@app.route('/clienti/rimuovi/<int:id>', methods=['POST'])
@login_required
def elimina_cliente(id):
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
        cur = db.cursor()
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
            WHERE p.eliminato = FALSE
        '''
        params = []
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
        if q:
            query += ' AND (p.nome ILIKE %s OR p.codice ILIKE %s)'
            like = f'%{q}%'
            params.extend([like, like])
    return render_template('02_prodotti/01_prodotti.html', prodotti_per_categoria=prodotti_per_categoria, categorie=categorie)
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
                prodotti_per_categoria[cat_nome] = []
            prodotti_per_categoria[cat_nome].append(item)
    return render_template(
        '02_prodotti/01_prodotti.html',
        prodotti_per_categoria=prodotti_per_categoria,
        categorie=categorie,
        prodotti_senza_categoria=prodotti_senza_categoria
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
            return render_template('02_prodotti/02_aggiungi_prodotto.html', categorie=categorie)
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
                    cur.execute('INSERT INTO categorie (nome) VALUES (%s) RETURNING id', (nuova_categoria,))
                    categoria_id = cur.fetchone()['id']
            else:
                categoria_id = int(categoria_id) if categoria_id else None
            # Inserimento prodotto
            cur.execute(
                'INSERT INTO prodotti (codice, nome, categoria_id) VALUES (%s, %s, %s)',
                (codice, nome, categoria_id)
            )
            cur.execute('INSERT INTO prodotti (nome, categoria_id) VALUES (%s, %s)', (nome, categoria_id))
            db.commit()
        flash(f'Prodotto "{nome}" aggiunto con successo.', 'success')
        return redirect(url_for('prodotti'))
    return render_template('02_prodotti/02_aggiungi_prodotto.html', categorie=categorie)
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
            return render_template('02_prodotti/03_modifica_prodotto.html', prodotto=prodotto, categorie=categorie, error=error)
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
            cur.execute('UPDATE prodotti SET nome=%s, categoria_id=%s WHERE id=%s', (nome, categoria_id, id))
            db.commit()
        flash(f'Prodotto "{nome}" modificato con successo.', 'success')
        return redirect(url_for('prodotti'))
    return render_template(
        '02_prodotti/03_modifica_prodotto.html',
        prodotto=prodotto,
        categorie=categorie,
        error=None,
        errore_codice=None
    )
    return render_template('02_prodotti/03_modifica_prodotto.html', prodotto=prodotto, categorie=categorie, error=None)
@app.route('/prodotti/elimina/<int:id>', methods=['POST'])
@login_required
def elimina_prodotto(id):
    conn = get_db_connection()
    cur = conn.cursor()
    with get_db() as db:
        cur = db.cursor()
        cur.execute('SELECT nome FROM prodotti WHERE id=%s', (id,))
        prodotto = cur.fetchone()
        if not prodotto:
            flash('Prodotto non trovato.', 'danger')
            return redirect(url_for('prodotti'))
    cur.execute(
        "UPDATE prodotti SET eliminato = TRUE WHERE id = %s",
        (id,)
    )
        cur.execute('DELETE FROM prodotti WHERE id=%s', (id,))
        db.commit()
        flash(f'Prodotto "{prodotto["nome"]}" eliminato con successo.', 'success')
        return redirect(url_for('prodotti'))
    conn.commit()
    cur.close()
    conn.close()
    flash("Prodotto eliminato", "success")
    return redirect(url_for("prodotti"))
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
@app.route('/prodotti/clienti/<int:id>')
@login_required
def clienti_prodotto(id):
    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)
        # Recupera il prodotto (include codice)
        cur.execute('SELECT id, codice, nome, categoria_id FROM prodotti WHERE id=%s', (id,))
        cur = db.cursor()
        cur.execute('SELECT * FROM prodotti WHERE id=%s', (id,))
        prodotto = cur.fetchone()
        if not prodotto:
            flash("❌ Prodotto non trovato", "danger")
            return redirect(url_for("prodotti"))
            return "Prodotto non trovato", 404
        # Recupera i clienti associati con lavorato=True
        cur.execute('''
            SELECT c.*
            FROM clienti c
            JOIN clienti_prodotti cp ON c.id = cp.cliente_id
            WHERE cp.prodotto_id=%s AND cp.lavorato IS TRUE
            ORDER BY c.nome
            JOIN clienti_prodotti cp ON c.id=cp.cliente_id
            WHERE cp.prodotto_id=%s AND cp.lavorato=1
        ''', (id,))
        clienti = cur.fetchall()
    return render_template(
        '02_prodotti/04_prodotto_clienti.html',
        prodotto=prodotto,
        clienti=clienti
    )
    return render_template('/02_prodotti/04_prodotto_clienti.html', prodotto=prodotto, clienti=clienti)
@app.route('/categorie')
# ROUTE FATTURATO
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
            cur.execute(f'''
                SELECT cliente_id, totale
                FROM fatturato
                WHERE mese = %s AND anno = %s AND cliente_id IN ({placeholders})
            ''', (mese, anno, *c_ids))
            fatt_dati = {row['cliente_id']: row['totale'] for row in cur.fetchall()}
            for c in clienti_attivi:
                c['importo'] = fatt_dati.get(c['id'], '')
    return render_template('03_fatturato/02_gestione_fatturato.html', mese=mese, anno=anno, clienti=clienti_attivi)
@app.route('/fatturato/gestione/salva', methods=['POST'])
@login_required
def salva_gestione_fatturato():
    mese = int(request.form.get('mese'))
    anno = int(request.form.get('anno'))
    
    with get_db() as db:
        cur = db.cursor()
        for key, value in request.form.items():
            if key.startswith('fatturato_') and value != '':
                c_id = int(key.split('_')[1])
                importo = float(value)
                
                # Check if exists
                cur.execute('SELECT id FROM fatturato WHERE cliente_id=%s AND mese=%s AND anno=%s', (c_id, mese, anno))
                row = cur.fetchone()
                if row:
                    cur.execute('UPDATE fatturato SET totale=%s WHERE id=%s', (importo, row['id']))
                else:
                    cur.execute('INSERT INTO fatturato (cliente_id, mese, anno, totale) VALUES (%s, %s, %s, %s)', (c_id, mese, anno, importo))
        db.commit()
    
    flash("Fatturati aggiornati con successo massivamente!", "success")
    return redirect(url_for('fatturato'))
@app.route('/fatturato')
@login_required
def fatturato():
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
        fatturato_mensile=fatturato_mensile
    )
@app.route('/volantini')
@login_required
def lista_volantini():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
    with get_db() as db:
        cur = db.cursor()
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
        # 🔹 Salva sfondo
        filename = secure_filename(sfondo_file.filename)
        os.makedirs(app.config["UPLOAD_FOLDER_VOLANTINI"], exist_ok=True)
        sfondo_path = os.path.join(app.config["UPLOAD_FOLDER_VOLANTINI"], filename)
        sfondo_file.save(sfondo_path)
        os.makedirs(UPLOAD_FOLDER_VOLANTINI, exist_ok=True)
        sfondo_file.save(os.path.join(UPLOAD_FOLDER_VOLANTINI, filename))
        # 🔹 Inserisci volantino in DB
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO volantini (titolo, sfondo, data_creazione) VALUES (%s, %s, NOW()) RETURNING id",
        with get_db() as db:
            cur = db.execute(
                "INSERT INTO volantini (titolo, sfondo, data_creazione) VALUES (?, ?, datetime('now'))",
                (titolo, filename)
            )
            volantino_id = cur.fetchone()["id"]
            volantino_id = cur.lastrowid
            # 🔹 Inizializza griglia 3x3 con slot vuoti
            layout_json = {"objects": []}
                        {"type": "text", "text":"", "left":100, "top":215, "fontSize":18, "fill":"red", "originX":"center", "textAlign":"center"}
                    ],
                    "left": x, "top": y, "width":200, "height":240,
                    "metadata": {}
                    "left": x, "top": y, "width":200, "height":240, "metadata": {}
                })
            # 🔹 Salva layout nel DB
            cur.execute(
                "UPDATE volantini SET layout_json=%s WHERE id=%s",
            db.execute(
                "UPDATE volantini SET layout_json=? WHERE id=?",
                (json.dumps(layout_json, ensure_ascii=False), volantino_id)
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()
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
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SELECT sfondo FROM volantini WHERE id = %s", (volantino_id,))
        volantino = cur.fetchone()
    with get_db() as db:
        volantino = db.execute(
            "SELECT sfondo FROM volantini WHERE id = ?", (volantino_id,)
        ).fetchone()
        if not volantino:
            flash("❌ Volantino non trovato.", "danger")
            return redirect(url_for("lista_volantini"))
        # 🔹 Elimina immagini prodotti collegati dal filesystem
        cur.execute("SELECT immagine FROM volantino_prodotti WHERE volantino_id = %s", (volantino_id,))
        prodotti = cur.fetchall()
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
        # 🔹 Elimina prodotti dal DB prima del volantino
        cur.execute("DELETE FROM volantino_prodotti WHERE volantino_id = %s", (volantino_id,))
        # 🔹 Elimina volantino e prodotti dal DB
        db.execute("DELETE FROM volantini WHERE id = ?", (volantino_id,))
        db.execute("DELETE FROM volantino_prodotti WHERE volantino_id = ?", (volantino_id,))
        db.commit()
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
    with get_db() as db:
        volantino = db.execute(
            "SELECT * FROM volantini WHERE id = ?", (volantino_id,)
        ).fetchone()
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
            sfondo_nome = volantino["sfondo"]
            if sfondo_file and sfondo_file.filename:
                filename = secure_filename(sfondo_file.filename)
                sfondo_nome = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                os.makedirs(UPLOAD_FOLDER_VOLANTINI, exist_ok=True)
                sfondo_path = os.path.join(UPLOAD_FOLDER_VOLANTINI, sfondo_nome)
                sfondo_file.save(sfondo_path)
                sfondo_file.save(os.path.join(UPLOAD_FOLDER_VOLANTINI, sfondo_nome))
            cur.execute(
                "UPDATE volantini SET titolo=%s, sfondo=%s WHERE id=%s",
            db.execute(
                "UPDATE volantini SET titolo=?, sfondo=? WHERE id=?",
                (titolo, sfondo_nome, volantino_id)
            )
            conn.commit()
            db.commit()
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
        # 🔹 Prodotti attivi del volantino
        prodotti_raw = db.execute(
            "SELECT * FROM volantino_prodotti WHERE volantino_id=? AND eliminato=0 ORDER BY id ASC",
            (volantino_id,)
        ).fetchall()
        prodotti = [dict(p) for p in prodotti_raw]
        # ============================
        # Ultimi 15 prodotti inseriti
        # ============================
        cur.execute("""
        # 🔹 Prodotti consigliati
        prodotti_precedenti_raw = db.execute(
            """
            SELECT id, nome, prezzo AS prezzo_default,
                   COALESCE(immagine, 'no-image.png') AS immagine
            FROM volantino_prodotti
            WHERE eliminato=FALSE
            ORDER BY id DESC
            LIMIT 15
        """)
        prodotti_precedenti_raw = cur.fetchall()
            WHERE eliminato=0 AND immagine IS NOT NULL
            ORDER BY id DESC LIMIT 15
            """
        ).fetchall()
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
    with get_db() as db:
        volantino = db.execute("SELECT * FROM volantini WHERE id = ?", (volantino_id,)).fetchone()
        if not volantino:
            flash("❌ Volantino non trovato.", "danger")
            return redirect(url_for("lista_volantini"))
                os.makedirs(UPLOAD_FOLDER_VOLANTINI_PRODOTTI, exist_ok=True)
                immagine_file.save(os.path.join(UPLOAD_FOLDER_VOLANTINI_PRODOTTI, immagine_filename))
            cur.execute(
                "INSERT INTO volantino_prodotti (volantino_id, nome, prezzo, immagine, eliminato) VALUES (%s, %s, %s, %s, FALSE) RETURNING id",
            db.execute(
                "INSERT INTO volantino_prodotti (volantino_id, nome, prezzo, immagine, eliminato) VALUES (?, ?, ?, ?, 0)",
                (volantino_id, nome, prezzo, immagine_filename)
            )
            new_id = cur.fetchone()["id"]
            conn.commit()
            db.commit()
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
    with get_db() as db:
        prodotto = db.execute("SELECT * FROM volantino_prodotti WHERE id = ?", (prodotto_id,)).fetchone()
        if not prodotto:
            flash("❌ Prodotto non trovato.", "danger")
            return redirect(url_for("lista_volantini"))
        if request.method == "POST":
            if "lascia_vuota" in request.form:
                cur.execute(
                    "UPDATE volantino_prodotti SET nome='', prezzo=0, immagine=NULL, lascia_vuota=TRUE, eliminato=FALSE WHERE id=%s",
                db.execute(
                    "UPDATE volantino_prodotti SET nome='', prezzo=0, immagine=NULL, lascia_vuota=1, eliminato=0 WHERE id=?",
                    (prodotto_id,)
                )
                conn.commit()
                db.commit()
                flash("✅ Box lasciata vuota.", "success")
                return redirect(url_for("modifica_volantino", volantino_id=prodotto["volantino_id"]))
                os.makedirs(UPLOAD_FOLDER_VOLANTINI_PRODOTTI, exist_ok=True)
                file.save(os.path.join(UPLOAD_FOLDER_VOLANTINI_PRODOTTI, filename))
            cur.execute(
                "UPDATE volantino_prodotti SET nome=%s, prezzo=%s, immagine=%s, lascia_vuota=FALSE, eliminato=FALSE WHERE id=%s",
            db.execute(
                "UPDATE volantino_prodotti SET nome=?, prezzo=?, immagine=?, lascia_vuota=0, eliminato=0 WHERE id=?",
                (nome, prezzo, filename, prodotto_id)
            )
            conn.commit()
            db.commit()
            flash("✅ Prodotto aggiornato con successo!", "success")
            return redirect(url_for("modifica_volantino", volantino_id=prodotto["volantino_id"]))
    finally:
        cur.close()
        conn.close()
    return render_template("04_volantino/06_modifica_prodotto_volantino.html", prodotto=dict(prodotto))
# ============================
# AGGIUNGI PRODOTTO CONSIGLIATO
# ============================
    except (ValueError, TypeError):
        return jsonify({"status": "error", "msg": "Prezzo non valido"}), 400
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SELECT nome, immagine FROM volantino_prodotti WHERE id=%s", (prodotto_id,))
        prodotto = cur.fetchone()
    with get_db() as db:
        prodotto = db.execute(
            "SELECT nome, immagine FROM volantino_prodotti WHERE id=?",
            (prodotto_id,)
        ).fetchone()
        if not prodotto:
            return jsonify({"status": "error", "msg": "Prodotto non trovato"}), 404
        # Riattiva prodotto già eliminato
        cur.execute(
            "SELECT id FROM volantino_prodotti WHERE volantino_id=%s AND nome=%s AND eliminato=TRUE",
        esistente = db.execute(
            "SELECT id FROM volantino_prodotti WHERE volantino_id=? AND nome=? AND eliminato=1",
            (volantino_id, prodotto["nome"])
        )
        esistente = cur.fetchone()
        ).fetchone()
        if esistente:
            cur.execute(
                "UPDATE volantino_prodotti SET prezzo=%s, eliminato=FALSE WHERE id=%s",
            db.execute(
                "UPDATE volantino_prodotti SET prezzo=?, eliminato=0 WHERE id=?",
                (prezzo, esistente["id"])
            )
            conn.commit()
            db.commit()
            return jsonify({"status": "ok", "id": esistente["id"], "riattivato": True})
        # Inserimento nuovo prodotto
        cur.execute(
            "INSERT INTO volantino_prodotti (volantino_id, nome, prezzo, immagine, eliminato) VALUES (%s, %s, %s, %s, FALSE) RETURNING id",
        cursor = db.execute(
            "INSERT INTO volantino_prodotti (volantino_id, nome, prezzo, immagine, eliminato) VALUES (?, ?, ?, ?, 0)",
            (volantino_id, prodotto["nome"], prezzo, prodotto["immagine"])
        )
        new_id = cur.fetchone()["id"]
        conn.commit()
        return jsonify({"status": "ok", "id": new_id, "riattivato": False})
    finally:
        cur.close()
        conn.close()
        db.commit()
        return jsonify({"status": "ok", "id": cursor.lastrowid, "riattivato": False})
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
    with get_db() as db:
        row = db.execute(
            "SELECT volantino_id FROM volantino_prodotti WHERE id=?", (prodotto_id,)
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "msg": "Prodotto non trovato"}), 404
        cur.execute("UPDATE volantino_prodotti SET eliminato=TRUE WHERE id=%s", (prodotto_id,))
        conn.commit()
        db.execute(
            "UPDATE volantino_prodotti SET eliminato=1 WHERE id=?", (prodotto_id,)
        )
        db.commit()
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
    with get_db() as db:
        volantino = db.execute("SELECT * FROM volantini WHERE id=?", (volantino_id,)).fetchone()
        if not volantino:
            flash("❌ Volantino non trovato.", "danger")
            return redirect(url_for("lista_volantini"))
        cur.execute(
            "SELECT * FROM volantino_prodotti WHERE volantino_id=%s ORDER BY id ASC",
            (volantino_id,)
        )
        prodotti_raw = cur.fetchall()
        prodotti = db.execute(
            "SELECT * FROM volantino_prodotti WHERE volantino_id=? ORDER BY id ASC", (volantino_id,)
        ).fetchall()
        volantino_dict = dict(volantino)
        # 🔹 Usa placeholder se sfondo non esiste
        sfondo_path_full = os.path.join(UPLOAD_FOLDER_VOLANTINI, volantino_dict.get("sfondo") or "")
        if not os.path.exists(sfondo_path_full):
            volantino_dict["sfondo"] = os.path.basename(NO_IMAGE_PATH)
        # 🔹 Layout JSON
        try:
            layout = json.loads(volantino_dict.get("layout_json") or "{}")
                layout = {"objects": layout}
                layout = {"objects": []}
        except Exception:
    volantino_dict = dict(volantino)
    try:
        layout = json.loads(volantino_dict.get("layout_json") or "{}")
            layout = {"objects": layout}
            layout = {"objects": []}
        volantino_dict["layout_json"] = json.dumps(layout, ensure_ascii=False)
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
        prodotti=[dict(p) for p in prodotti]
    )
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
    with get_db() as db:
        volantino = db.execute("SELECT * FROM volantini WHERE id=?", (volantino_id,)).fetchone()
        if not volantino:
            flash("❌ Volantino non trovato.", "danger")
            return redirect(url_for("lista_volantini"))
        cur.execute(
            "SELECT * FROM volantino_prodotti WHERE volantino_id=%s AND eliminato=FALSE ORDER BY id ASC",
        prodotti_raw = db.execute(
            "SELECT * FROM volantino_prodotti WHERE volantino_id=? AND eliminato=0 ORDER BY id ASC",
            (volantino_id,)
        )
        prodotti_raw = cur.fetchall()
        ).fetchall()
        volantino_dict = dict(volantino)
        cols, rows = 3, 3
        max_slots = cols * rows
    volantino_dict = dict(volantino)
    cols, rows = 3, 3
    max_slots = cols * rows
        # 🔹 Sfondo placeholder
        sfondo_path_full = os.path.join(UPLOAD_FOLDER_VOLANTINI, volantino_dict.get("sfondo") or "")
        if not os.path.exists(sfondo_path_full):
            volantino_dict["sfondo"] = os.path.basename(NO_IMAGE_PATH)
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
    except Exception as e:
        return jsonify({"success": False, "message": f"❌ Errore JSON: {e}"}), 500
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("UPDATE volantini SET layout_json=%s WHERE id=%s RETURNING id", (layout_json, volantino_id))
        updated_row = cur.fetchone()
        if not updated_row:
            return jsonify({"success": False, "message": "❌ Volantino non trovato"}), 404
    with get_db() as db:
        cursor = db.execute("UPDATE volantini SET layout_json=? WHERE id=?", (layout_json, volantino_id))
        for obj in layout["objects"]:
            metadata = obj.get("metadata", {})
            prod_id = metadata.get("id")
            if prod_id:
                db.execute("UPDATE volantino_prodotti SET eliminato=0 WHERE id=? AND eliminato=1", (prod_id,))
        db.commit()
        updated = cursor.rowcount
        conn.commit()
        return jsonify({"success": True, "message": "✅ Layout salvato correttamente"})
    finally:
        cur.close()
        conn.close()
    if updated == 0:
        return jsonify({"success": False, "message": "❌ Volantino non trovato"}), 404
# ============================
# GENERA VOLANTINO DA PRODOTTI GIÀ ESTRATTI (POST-REVIEW)
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
        promo_lampo=promo_lampo,
    )
            flash("❌ Prezzo non valido", "danger")
            return redirect(url_for("nuova_promo_lampo"))
        # 🔹 Assicurati che la cartella corretta esista
        os.makedirs(UPLOAD_FOLDER_PROMO, exist_ok=True)
        # 🔹 Salva immagine prodotto
        immagine_nome = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(immagine_file.filename)}"
        immagine_file.save(os.path.join(UPLOAD_FOLDER_PROMO, immagine_nome))
        # 🔹 Salva sfondo promo
        sfondo_nome = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(sfondo_file.filename)}"
        sfondo_file.save(os.path.join(UPLOAD_FOLDER_PROMO, sfondo_nome))
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
        with get_db() as db:
            db.execute(
                "INSERT INTO promo_lampo (nome, prezzo, immagine, sfondo, data_creazione) VALUES (?, ?, ?, ?, ?)",
                (nome, prezzo, immagine_nome, sfondo_nome, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()
        flash("✅ Promo Lampo creata con successo!", "success")
        return redirect(url_for("lista_volantini_completa"))
@app.route("/promo-lampo/modifica/<int:promo_id>", methods=["GET", "POST"])
@login_required
def modifica_promo_lampo(promo_id):
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM promo_lampo WHERE id=%s", (promo_id,))
        promo = cur.fetchone()
    with get_db() as db:
        promo = db.execute("SELECT * FROM promo_lampo WHERE id=?", (promo_id,)).fetchone()
        if not promo:
            flash("❌ Promo Lampo non trovata", "danger")
            return redirect(url_for("lista_volantini_completa"))
        if request.method == "POST":
            nome = request.form.get("nome", "").strip()
            prezzo_raw = request.form.get("prezzo", "").strip()
            immagine_file = request.files.get("immagine")
            sfondo_file = request.files.get("sfondo")
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        prezzo_raw = request.form.get("prezzo", "").strip()
        immagine_file = request.files.get("immagine")
            try:
                prezzo = float(prezzo_raw)
            except ValueError:
                flash("❌ Prezzo non valido", "danger")
                return redirect(url_for("modifica_promo_lampo", promo_id=promo_id))
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
        immagine_nome = promo["immagine"]
        if immagine_file and immagine_file.filename.strip():
            old_path = os.path.join(UPLOAD_FOLDER_PROMO, immagine_nome)
            if os.path.exists(old_path):
                os.remove(old_path)
            # Aggiorna sfondo se caricato
            sfondo_nome = promo.get("sfondo")
            if sfondo_file and sfondo_file.filename.strip():
                old_sfondo_path = os.path.join(UPLOAD_FOLDER_PROMO, sfondo_nome) if sfondo_nome else None
                if old_sfondo_path and os.path.exists(old_sfondo_path):
                    os.remove(old_sfondo_path)
                sfondo_file.save(os.path.join(UPLOAD_FOLDER_PROMO, sfondo_nome))
            immagine_file.save(os.path.join(UPLOAD_FOLDER_PROMO, immagine_nome))
            # Aggiorna DB
            cur.execute(
                "UPDATE promo_lampo SET nome=%s, prezzo=%s, immagine=%s, sfondo=%s WHERE id=%s",
                (nome, prezzo, immagine_nome, sfondo_nome, promo_id)
        with get_db() as db:
            db.execute(
                "UPDATE promo_lampo SET nome=?, prezzo=?, immagine=? WHERE id=?",
                (nome, prezzo, immagine_nome, promo_id)
            )
            conn.commit()
            flash("✅ Promo Lampo aggiornata con successo!", "success")
            return redirect(url_for("lista_volantini_completa"))
    finally:
        cur.close()
        conn.close()
        flash("✅ Promo Lampo aggiornata con successo!", "success")
        return redirect(url_for("lista_volantini_completa"))
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
    with get_db() as db:
        promo = db.execute("SELECT immagine, sfondo FROM promo_lampo WHERE id=?", (promo_id,)).fetchone()
        if not promo:
            flash("❌ Promo Lampo non trovata", "danger")
            return redirect(url_for("lista_volantini_completa"))
        # elimina immagini dalla cartella
        # elimina immagini
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
        db.execute("DELETE FROM promo_lampo WHERE id=?", (promo_id,))
    flash("✅ Promo Lampo eliminata con successo!", "success")
    return redirect(url_for("lista_volantini_completa"))
# ============================
# EDITOR PROMO LAMPO
# ============================
@app.route("/promo-lampo/<int:promo_id>/editor", methods=["GET", "POST"])
@login_required
def editor_promo_lampo(promo_id):
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM promo_lampo WHERE id=%s", (promo_id,))
        promo = cur.fetchone()
    with get_db() as db:
        promo = db.execute("SELECT * FROM promo_lampo WHERE id=?", (promo_id,)).fetchone()
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
    finally:
        cur.close()
        conn.close()
    return render_template(
        "04_volantino/10_editor_promo_lampo.html",
        promo=promo,
        promo_prodotti=promo_prodotti
    )
# ============================
# SALVA LAYOUT PROMO LAMPO
# ============================
@app.route("/promo-lampo/<int:promo_id>/salva_layout", methods=["POST"], endpoint="salva_layout")
@app.route("/promo-lampo/<int:promo_id>/salva_layout", methods=["POST"])
@login_required
def salva_layout_promo_lampo(promo_id):
    data = request.get_json(silent=True)
    layout = data.get("layout") if data else None
    if not layout:
        return jsonify({"status": "error", "message": "Layout mancante"}), 400
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
    
        with get_db() as db:
            db.execute("UPDATE promo_lampo SET layout=? WHERE id=?", (layout_json, promo_id))
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Errore interno: {str(e)}"}), 500
# ----------------------------------------------------------------------
#  CREA NUOVO VOLANTINO (pagina editor vuota)
# ----------------------------------------------------------------------
@app.route('/beta-volantino')
def beta_volantino():
    tema = request.args.get('tema', 'standard')
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
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT layout_json, titolo FROM volantini 
                WHERE layout_json::jsonb -> 'global' ->> 'theme' = %s 
                ORDER BY data_creazione DESC LIMIT 1
            """, (tema,))
            last_themed_vol = cur.fetchone()
            if last_themed_vol and last_themed_vol['layout_json']:
                prev_layout = json.loads(last_themed_vol['layout_json'])
                
                clona_griglia = last_themed_vol['titolo'].strip().lower() in ['volantino carne', 'volantino pesce']
                
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
        thumbnail=""
    )
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
            # We don't have prezzi natively in prodotti, typically they are in clienti_prodotti or base_prezzo.
            # I'll just return the fields available. Let's assume prezzo is just an example. 
            # I should be careful if 'prezzo' column doesn't exist in 'prodotti' table.
            res.append({
                "id": p["id"],
                "codice": p["codice"] or "",
                "nome": p["nome"],
                "prezzo": str(p["prezzo"]) if p["prezzo"] is not None else "",
                "immagine": p.get("immagine") or "",
                "categoria_nome": p["categoria_nome"] or "Senza Categoria"
            })
            
    return jsonify(res)
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
        
        uploads_dir = os.path.join(app.root_path, 'static', 'uploads', 'volantino_prodotti')
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
        uploads_dir = os.path.join(app.root_path, 'static', 'uploads', 'volantino_prodotti')
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
# ============================
# ROUTE DI TEST TEMPLATE
# ============================
@app.route('/test-template')
def test_template():
    return render_template('00_login.html')
        vol_id = data.get("id")
        nome = data.get("nome", "Volantino BETA")
        layout = data.get("layout")
        if not layout:
            return jsonify({"ok": False, "message": "Layout mancante nel payload."}), 400
        layout_json = json.dumps(layout)
        thumbnail = data.get("thumbnail")   # base64 da html2canvas
        if vol_id:
            # Aggiorna esistente
            vol = VolantinoBeta.query.get(int(vol_id))
            if not vol:
                return jsonify({"ok": False, "message": f"Volantino #{vol_id} non trovato."}), 404
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
    except Exception as e:
        db.session.rollback()
        print(f"Errore salvataggio volantino beta: {e}")
        return jsonify({"ok": False, "message": f"Errore server: {str(e)}"}), 500
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
        thumbnail=vol.thumbnail,
        tipo_volantino=vol.tipo
    )
# ----------------------------------------------------------------------
#  LISTA VOLANTINI
# ----------------------------------------------------------------------
@app.route('/beta-volantini')
def lista_volantini_beta():
    lista = VolantinoBeta.query.filter((VolantinoBeta.tipo == 'volantino') | (VolantinoBeta.tipo == None)).order_by(VolantinoBeta.creato_il.desc()).all()
    lista_promo = VolantinoBeta.query.filter(VolantinoBeta.tipo.like('promo_%')).order_by(VolantinoBeta.creato_il.desc()).all()
    return render_template(
        '05_beta_volantino/05_beta_volantino_lista.html',
        lista=lista,
        lista_promo=lista_promo
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
        thumbnail=vol.thumbnail,
        tipo=vol.tipo
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
# 2) PARSING PDF (codice, nome, prezzo)
# ------------------------------------------------------------
def parse_offers_from_pdf(pdf_path: str) -> list[dict]:
    offers = []
    
    current_code = None
    current_desc = ""
    current_price = None
    current_page_idx = 0
    
    # Accetta codici da 4 a 10 cifre
    code_re = re.compile(r"^\s*(\d{4,10})")
    # Regex per trovare prezzi numerici: 12,50 / 8.99 / 1.234,56 / 12,5
    price_re = re.compile(r'((?:\d{1,3}[.,])*\d{1,3}[.,]\d{1,3})')
    
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            lines = text.splitlines()
            
            for raw in lines:
                row_text = " ".join(raw.strip().split())
                if not row_text:
                    continue
                
                # Cerca codice a inizio riga
                m_code = code_re.match(row_text)
                
                if m_code:
                    # Salva il prodotto precedente prima di passare al nuovo
                    if current_code and current_desc:
                        offers.append({
                            "code": current_code,
                            "name": current_desc.strip(),
                            "price": current_price or "",
                            "raw": "[Compilato]",
                            "page": current_page_idx
                        })
                        
                    current_code = m_code.group(1)
                    current_desc = ""
                    current_price = None
                    current_page_idx = page_idx
                    
                    # Resto della stringa dopo il codice
                    rest = row_text[len(current_code):].strip()
                    
                    # Cerchiamo tutti i prezzi numerici nella riga
                    price_matches = price_re.findall(rest)
                    if price_matches:
                        # Prendi il penultimo prezzo trovato (molto spesso prezzo unitario, e l'ultimo è il totale)
                        current_price = price_matches[-2] if len(price_matches) >= 2 else price_matches[-1]
                    
                    # Rimuoviamo i numeri decimali e il simbolo euro dalla desc
                    desc_cleaned = re.sub(r'€?\s*\d{1,6}[.,]\d{1,3}', '', rest)
                    desc_cleaned = desc_cleaned.replace('€', '').strip()
                    
                    # Pulizia parti UM e numeri puri
                    parts = desc_cleaned.split()
                    desc_parts = []
                    for p in parts:
                        up = p.upper().rstrip('.,;')
                        if up in ("PZ", "KG", "BT", "CT", "LT"):
                            continue
                        if re.match(r'^\d+$', p):
                            continue
                        desc_parts.append(p)
                    current_desc = " ".join(desc_parts)
                        
                else:
                    # Riga senza codice a inizio riga
                    if current_code:
                        skip_words = ["Pag.", "Spett.le", "Codice Art", "Descrizione", "UM", "Qtà", "Prezzo", "Iva"]
                        if not any(sw in row_text for sw in skip_words):
                            # Cerchiamo prezzi anche nelle righe di continuazione
                            extra_prices = price_re.findall(row_text)
                            if extra_prices and not current_price:
                                current_price = extra_prices[-2] if len(extra_prices) >= 2 else extra_prices[-1]
                            
                            clean_line = re.sub(r'€?\s*\d{1,6}[.,]\d{1,3}', '', row_text).replace('€', '').strip()
                            if clean_line and (clean_line.isupper() or any(char.isdigit() for char in clean_line)):
                                current_desc += " " + clean_line
    # Flush the last product
    if current_code and current_desc:
        offers.append({
            "code": current_code,
            "name": current_desc.strip(),
            "price": current_price or "",
            "raw": "[Compilato]",
            "page": current_page_idx
        })
    # De-duplicate
    seen = set()
    uniq = []
    for o in offers:
        if o["code"] in seen:
            continue
        seen.add(o["code"])
        uniq.append(o)
        
    return uniq
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
# ------------------------------------------------------------
# 8) BROADCAST PREFERENZE (usa Twilio send_text)
# ------------------------------------------------------------
@app.route("/admin/whatsapp/broadcast-preferenze")
@login_required
def broadcast_preferenze():
    try:
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT telefono
                FROM clienti
                WHERE telefono IS NOT NULL
                  AND whatsapp_linked = TRUE
            """)
            rows = cur.fetchall()
            count = 0
            for r in rows:
                phone = _normalize_phone(r.get("telefono"))
                if not phone:
                    continue
                send_text(
                    phone,
                    "👋 Ciao!\n"
                    "Da oggi puoi ricevere offerte mirate su WhatsApp.\n\n"
                    "Scegli cosa vuoi ricevere:\n"
                    "• Scadenze\n"
                    "• Pesce\n"
                    "• Carne\n\n"
                    "Scrivi *MENU* per scegliere."
                )
                count += 1
                time.sleep(0.15)
        flash(f"Inviato messaggio preferenze a {count} clienti.", "success")
    except Exception as e:
        flash(f"Errore invio broadcast: {e}", "danger")
    return redirect(url_for("clienti"))
# ------------------------------------------------------------
# 9) BOT DASHBOARD (già aggiornato da te) -> NON TOCCO QUI
#    (tu hai già /bot e /bot/invia che usano send_text)
# ------------------------------------------------------------
@app.route("/bot", methods=["GET"])
@login_required
def bot_dashboard():
    pref = request.args.get("pref", "scadenza").strip().lower()
    
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Conteggi
        cur.execute("""
            SELECT 
                SUM(CASE WHEN wp.ricevi_carne = TRUE AND wp.opt_out = FALSE THEN 1 ELSE 0 END) as n_carne,
                SUM(CASE WHEN wp.opt_out = TRUE THEN 1 ELSE 0 END) as n_stop,
                SUM(CASE WHEN wp.cliente_id IS NULL THEN 1 ELSE 0 END) as n_nessuna
            FROM clienti c
            LEFT JOIN whatsapp_preferenze wp ON c.id = wp.cliente_id
        """)
        counts = cur.fetchone() or {}
        
        # Clienti del segmento
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
        flash("Inserisci un testo per il messaggio.", "warning")
        return redirect(url_for('bot_dashboard', pref=pref))
        
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        where_clause = _segment_where(pref)
        phone_col = _detect_phone_column(cur) or "telefono"
        
        q = f"""
            SELECT c.{phone_col} FROM clienti c
            LEFT JOIN whatsapp_preferenze wp ON c.id = wp.cliente_id
            WHERE {where_clause}
        """
        cur.execute(q)
        rows = cur.fetchall()
        
        count = 0
        for r in rows:
            phone = _normalize_phone(r.get(phone_col))
            if phone:
                try:
                    send_text(phone, testo)
                    count += 1
                except Exception as e:
                    print("Error sending dashboard broadcast:", e)
        
        conn.commit()
        flash(f"Messaggio inviato a {count} clienti nel segmento {pref.upper()}.", "success")
        
    return redirect(url_for('bot_dashboard', pref=pref))
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
            
        with get_db() as db:
            cur = db.cursor(cursor_factory=RealDictCursor)
            sent, total_mapped = send_offers_to_customers_pg(cur, offers)
            db.commit()
            
        flash(f"PDF elaborato! Trovate {len(offers)} offerte. Mandati {sent} messaggi a clienti con prodotti corrispondenti.", "success")
    else:
        flash("Formato non valido. Carica un PDF.", "danger")
        
    return redirect(url_for('bot_dashboard'))
@app.route("/promozioni/upload", methods=["POST"])
@login_required
def promozione_upload():
    tipo = request.form.get("tipo") # "mensile" o "scadenza"
    if "promo_file" not in request.files:
        flash("Seleziona un file PDF.", "warning")
        return redirect(url_for('clienti'))
        
    file = request.files["promo_file"]
    if file.filename == "":
        flash("Nessun file selezionato.", "warning")
        return redirect(url_for('clienti'))
        
    matched_items = []
    if file and file.filename.endswith(".pdf"):
        pdf_path = f"/tmp/promo_{tipo}_{int(time.time())}.pdf"
        file.save(pdf_path)
        
        if tipo == "scadenza":
            offers = parse_scadenze_from_pdf(pdf_path)
        else:
            offers = parse_offers_from_pdf(pdf_path)
        
        if not offers:
            flash("Nessun prodotto trovato nel PDF con i requisiti necessari.", "warning")
            return redirect(url_for('clienti'))
            
        with get_db() as db:
            cur = db.cursor(cursor_factory=RealDictCursor)
            
            # Svuota promozioni vecchie dello stesso tipo
            cur.execute("DELETE FROM promozioni_pdf WHERE tipo = %s", (tipo,))
            
            for o in offers:
                # Trova prodotto per codice o nome
                cur.execute('''
                    SELECT p.id, p.nome, p.codice
                    FROM prodotti p
                    WHERE p.codice = %s OR LOWER(p.nome) = LOWER(%s)
                    LIMIT 1
                ''', (o.get('code'), o.get('name')))
                p_match = cur.fetchone()
                
                if p_match:
                    pid = p_match['id']
                    # Salva in promozioni_pdf
                    cur.execute("INSERT INTO promozioni_pdf (tipo, prodotto_id) VALUES (%s, %s)", (tipo, pid))
                    
                    # Cerca clienti che lavorano questo prodotto
                    cur.execute('''
                        SELECT c.id, c.nome
                        FROM clienti_prodotti cp
                        JOIN clienti c ON c.id = cp.cliente_id
                        WHERE cp.prodotto_id = %s AND cp.lavorato = TRUE
                    ''', (pid,))
                    clienti_lavorano = cur.fetchall()
                    
                    matched_items.append({
                        "id": pid,
                        "nome": p_match['nome'],
                        "codice": p_match['codice'],
                        "prezzo": o.get('price'),
                        "scadenza": o.get('scadenza', ''),
                        "clienti": clienti_lavorano
                    })
                    
            # --- GENERAZIONE VOLANTINO AUTOMATICA ---
            import json
            from datetime import datetime
            
            # Raggruppa tutte le offerte e dividi a blocchi di 9 ignorando i limiti pagina del PDF
            doc_pages = []
            
            for i in range(0, len(offers), 9):
                chunk = offers[i:i+9]
                grid_cells = []
                cell_counter = 1
                
                for o in chunk:
                    cur.execute("SELECT id, immagine FROM prodotti WHERE codice = %s OR LOWER(nome) = LOWER(%s) LIMIT 1", (o.get('code'), o.get('name')))
                    p_match = cur.fetchone()
                    
                    img_path = ""
                    p_id = None
                    if p_match:
                        p_id = p_match['id']
                        img_path = f"/static/uploads/{p_match['immagine']}" if p_match['immagine'] else ""
                    
                    grid_cells.append({
                        "id": f"cell_{cell_counter}",
                        "colSpan": 1,
                        "rowSpan": 1,
                        "isHidden": False,
                        "productId": p_id,
                        "name": o.get("name"),
                        "price": f"€ {o['price']}" if o.get('price') and o['price'] != '0,00' else "",
                        "img": img_path,
                        "bgColor": "#ffffff",
                        "nameColor": "#000000",
                        "priceColor": "#e60000"
                    })
                    cell_counter += 1
                    
                # Pad the rest of the 9 cells
                remainder = len(chunk) % 9
                if remainder != 0:
                    for pad in range(9 - remainder):
                        grid_cells.append({
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
                template_path = os.path.join(app.config["UPLOAD_FOLDER_PROMO"], f"promo_template_{tipo}.json")
                custom_global = None
                custom_header = None
                custom_bg = None
                if os.path.exists(template_path):
                    try:
                        with open(template_path, "r", encoding="utf-8") as f:
                            tdata = json.load(f)
                            custom_global = tdata.get("global")
                            custom_header = tdata.get("header")
                            custom_bg = tdata.get("background")
                            
                            # Applica stili alle celle se definiti nel template (es. colori testo default)
                            for c in grid_cells:
                                if custom_global:
                                    if custom_global.get("cellBgColor"): c["bgColor"] = custom_global["cellBgColor"]
                                    if custom_global.get("nameColor"): c["nameColor"] = custom_global["nameColor"]
                                    if custom_global.get("priceColor"): c["priceColor"] = custom_global["priceColor"]
                    except Exception as e:
                        print(f"Errore lettura template promo: {e}")
                page_layout = {
                    "header": custom_header or {
                        "logoSize": 160, "logoPos": "center", "titlePos": "center",
                        "title": f"Promozione {'Mensile' if tipo == 'mensile' else 'Scadenza'}",
                        "titleColor": "#dc3545" if tipo == 'scadenza' else "#0d6efd",
                        "titleSize": 48, "logoUrl": ""
                    },
                    "global": custom_global or {
                        "theme": "standard",
                        "cols": 3,
                        "width": 3200,
                        "height": 4500,
                        "gridWidth": 1800,
                        "rowHeight": 0,
                        "gridGap": 15,
                        "paddingSides": 30,
                        "paddingTop": 30,
                        "paddingBottom": 30,
                        "border": True,
                        "bgColor": "#ffffff",
                        "nameSize": 1.0,
                        "priceSize": 1.8
                    },
                    "background": custom_bg,
                    "grid": grid_cells
                }
                doc_pages.append(page_layout)
            layout_json = {
                "isMultiPage": True,
                "pages": doc_pages
            }
            
            v_name = f"Promo {tipo.capitalize()} - {datetime.today().strftime('%d/%m/%Y %H:%M')}"
            cur.execute("INSERT INTO volantino_beta (nome, layout_json, tipo) VALUES (%s, %s, %s) RETURNING id", (v_name, json.dumps(layout_json), f"promo_{tipo}"))
            new_vol_id = cur.fetchone()['id']
            
            db.commit()
            
        return render_template("01_clienti/10_promo_risultati.html", tipo=tipo, items=matched_items, new_vol_id=new_vol_id)
    else:
        flash("Formato non valido. Carica un PDF.", "danger")
        return redirect(url_for('clienti'))
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
                  AND promo.tipo = 'mensile'
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
@app.route('/visite')
@login_required
def visite_clienti():
    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, nome, zona FROM clienti ORDER BY nome")
        tutti_clienti = cur.fetchall()
        
        # Clienti frequenti (quelli con più visite passate o standard visit day)
        cur.execute("SELECT id, nome, zona FROM clienti WHERE giorno_visita_standard IS NOT NULL LIMIT 10")
        clienti_frequenti = cur.fetchall()
        
    return render_template('06_visite/06_visite.html', tutti_clienti=tutti_clienti, clienti_frequenti=clienti_frequenti)
@app.route('/ordini')
@login_required
def ordini_settimanali():
    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, nome, zona, giorni_consegna_standard FROM clienti WHERE giorni_consegna_standard IS NOT NULL AND giorni_consegna_standard != ''")
        clienti = cur.fetchall()
        
        ordini_per_giorno = {}
        for c in clienti:
            days = c['giorni_consegna_standard'].split(',')
            for d in days:
                d = d.strip()
                if d not in ordini_per_giorno:
                    ordini_per_giorno[d] = []
                ordini_per_giorno[d].append(c)
                
    return render_template('01_clienti/07_ordini.html', ordini_per_giorno=ordini_per_giorno)
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
@app.route('/api/visite/save', methods=['POST'])
@login_required
def api_visite_save():
    cliente_id = request.form.get('cliente_id')
    data_visita = request.form.get('data_visita')
    ora_visita = request.form.get('ora_visita') or None
    note = request.form.get('note')
    
    with get_db() as db:
        cur = db.cursor()
        cur.execute('''
            INSERT INTO visite (cliente_id, data_visita, ora_visita, note)
            VALUES (%s, %s, %s, %s)
        ''', (cliente_id, data_visita, ora_visita, note))
        db.commit()
    
    flash("Appuntamento salvato.", "success")
    return redirect(url_for('visite_clienti'))
@app.route('/api/visite/detail/<int:id>')
@login_required
def api_visite_detail(id):
    with get_db() as db:
        cur = db.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT v.*, c.nome as cliente_nome, c.zona 
            FROM visite v 
            JOIN clienti c ON v.cliente_id = c.id 
            WHERE v.id = %s
        ''', (id,))
        v = cur.fetchone()
        
    if not v: return "Visita non trovata", 404
    
    # Return a small HTML snippet for the modal
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
                <p class="mb-1"><strong>Data:</strong> {v['data_visita']} {v['ora_visita'] or ''}</p>
                <p class="mb-0"><strong>Note:</strong> {v['note'] or 'Nessuna nota'}</p>
        </div>
        <div class="modal-footer border-0 p-4 pt-0">
            <form action="/api/visite/toggle_complete/{v['id']}" method="POST" class="w-100 d-flex gap-2">
                <button type="submit" class="btn {'btn-outline-danger' if v['completata'] else 'btn-success'} flex-grow-1 rounded-pill">
                    <i class="bi {'bi-x-circle' if v['completata'] else 'bi-check-circle'} me-2"></i>
                    {'Segna come Non Completata' if v['completata'] else 'Segna come Completata'}
                </button>
            </form>
        </div>
    '''
    return html
@app.route('/api/visite/move', methods=['POST'])
@login_required
def api_visite_move():
    data = request.json
    with get_db() as db:
        cur = db.cursor()
        cur.execute("UPDATE visite SET data_visita = %s, ora_visita = %s WHERE id = %s", (data['new_date'], data['new_time'], data['id']))
        db.commit()
    return jsonify(success=True)
@app.route('/api/visite/toggle_complete/<int:id>', methods=['POST'])
@login_required
def api_visite_toggle_complete(id):
    with get_db() as db:
        cur = db.cursor()
        cur.execute("UPDATE visite SET completata = NOT completata WHERE id = %s", (id,))
        db.commit()
    flash("Stato visita aggiornato.", "success")
    return redirect(url_for('visite_clienti'))
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