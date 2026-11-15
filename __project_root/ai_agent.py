import os
import re
import csv
import io
import json
import zipfile
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, date
from flask import Blueprint, request, jsonify, session, url_for
import requests

ai_agent_bp = Blueprint('ai_agent', __name__)

# Riferimenti iniettati da app.py
_GET_DB = None
_SA_DB = None
_VOLANTINO_MODEL = None
_EXTRACT_PDF_FN = None
_GET_PRESET_FN = None
_GET_VOL_CFG_FN = None
_BASE_DIR = None


def init_ai_agent(app, get_db_fn, sa_db, volantino_model, extract_pdf_fn=None, get_preset_fn=None, get_vol_cfg_fn=None, base_dir=None):
    global _GET_DB, _SA_DB, _VOLANTINO_MODEL, _EXTRACT_PDF_FN, _GET_PRESET_FN, _GET_VOL_CFG_FN, _BASE_DIR
    _GET_DB = get_db_fn
    _SA_DB = sa_db
    _VOLANTINO_MODEL = volantino_model
    _EXTRACT_PDF_FN = extract_pdf_fn
    _GET_PRESET_FN = get_preset_fn
    _GET_VOL_CFG_FN = get_vol_cfg_fn
    _BASE_DIR = base_dir or os.path.abspath(os.path.dirname(__file__))
    app.register_blueprint(ai_agent_bp)


# ==============================================================================
# GESTIONE IMPOSTAZIONI & API KEY OPENAI
# ==============================================================================
def _ensure_settings_table():
    with _GET_DB() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_agent_settings (
                chiave TEXT PRIMARY KEY,
                valore TEXT
            )
        """)
        conn.commit()


def get_openai_config():
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    model = (os.environ.get("OPENAI_MODEL") or "gpt-4o").strip()
    try:
        _ensure_settings_table()
        with _GET_DB() as conn:
            cur = conn.cursor()
            cur.execute("SELECT chiave, valore FROM ai_agent_settings WHERE chiave IN ('openai_api_key', 'openai_model')")
            for row in cur.fetchall():
                k = row['chiave']
                v = (row['valore'] or '').strip()
                if k == 'openai_api_key' and v:
                    api_key = v
                elif k == 'openai_model' and v:
                    model = v
    except Exception as e:
        print(f"[AI Agent] Warning reading settings: {e}")
    return api_key, model


def save_openai_config(api_key: str, model: str = "gpt-4o"):
    _ensure_settings_table()
    api_key = (api_key or "").strip()
    model = (model or "gpt-4o").strip()
    with _GET_DB() as conn:
        cur = conn.cursor()
        for k, v in [('openai_api_key', api_key), ('openai_model', model)]:
            cur.execute("SELECT chiave FROM ai_agent_settings WHERE chiave = %s", (k,))
            if cur.fetchone():
                cur.execute("UPDATE ai_agent_settings SET valore = %s WHERE chiave = %s", (v, k))
            else:
                cur.execute("INSERT INTO ai_agent_settings (chiave, valore) VALUES (%s, %s)", (k, v))
        conn.commit()

    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key
    os.environ["OPENAI_MODEL"] = model

    if _BASE_DIR:
        env_path = os.path.join(_BASE_DIR, ".env")
        try:
            lines = []
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            found_key = False
            found_model = False
            new_lines = []
            for line in lines:
                if line.strip().startswith("OPENAI_API_KEY="):
                    if api_key:
                        new_lines.append(f"OPENAI_API_KEY={api_key}\n")
                    found_key = True
                elif line.strip().startswith("OPENAI_MODEL="):
                    new_lines.append(f"OPENAI_MODEL={model}\n")
                    found_model = True
                else:
                    new_lines.append(line)
            if not found_key and api_key:
                if new_lines and not new_lines[-1].endswith("\n"):
                    new_lines[-1] += "\n"
                new_lines.append(f"OPENAI_API_KEY={api_key}\n")
            if not found_model:
                if new_lines and not new_lines[-1].endswith("\n"):
                    new_lines[-1] += "\n"
                new_lines.append(f"OPENAI_MODEL={model}\n")
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception as e:
            print(f"[AI Agent] Non è stato possibile aggiornare .env: {e}")


# ==============================================================================
# AUTO-CATEGORIZZAZIONE SEMANTICA HORECA
# ==============================================================================
HORECA_CATEGORY_KEYWORDS = {
    "PESCE E ITTICO": [
        "salmone", "tonno", "merluzzo", "baccala", "baccalà", "spigola", "branzino",
        "orata", "gamberi", "gambero", "mazzancolle", "scampi", "calamari", "totani",
        "polpo", "seppia", "seppie", "cozze", "vongole", "pesce", "spada", "alici",
        "acciughe", "sarde", "sgombro", "halibut", "platessa", "frutti di mare", "surimi", "ittico"
    ],
    "CARNE": [
        "manzo", "bovino", "scottona", "angus", "vitello", "suino", "maiale", "pollo",
        "tacchino", "anatra", "agnello", "hamburger", "burger", "salsiccia", "costata",
        "fiorentina", "entrecote", "tagliata", "fesa", "lonza", "bresaola",
        "polpette", "cotoletta", "wurstel", "rosticceria", "spiedini", "carne"
    ],
    "SALUMI E LATTICINI": [
        "prosciutto", "crudo", "cotto", "salame", "speck", "mortadella", "pancetta",
        "guanciale", "coppa", "culatello", "nduja", "porchetta", "mozzarella", "fiordilatte",
        "bufala", "burrata", "stracciatella", "parmigiano", "grana", "pecorino", "gorgonzola",
        "scamorza", "provola", "ricotta", "mascarpone", "formaggio", "burro", "panna",
        "yogurt", "latte", "taleggio", "brie", "cheddar", "edamer", "emmental"
    ],
    "ORTOFRUTTA E VERDURE": [
        "patate", "patatine", "pomodori", "pomodoro", "insalata", "zucchine", "melanzane",
        "peperoni", "funghi", "porcini", "champignon", "carciofi", "asparagi", "spinaci",
        "piselli", "fagiolini", "cipolla", "cipolle", "aglio", "basilico", "olive",
        "friarielli", "broccoli", "cavolfiore", "carote", "verdure", "frutta", "limoni"
    ],
    "DISPENSA E ALIMENTARI": [
        "pasta", "spaghetti", "penne", "rigatoni", "fusilli", "tagliatelle", "gnocchi",
        "riso", "carnaroli", "farina", "olio", "extravergine", "semi", "frittura",
        "aceto", "balsamico", "sale", "pepe", "spezie", "salsa", "maionese", "ketchup",
        "senape", "pesto", "polpa", "pelati", "passata", "tonno in", "legumi", "fagioli",
        "ceci", "lenticchie", "pane", "pangrattato", "grissini", "focaccia", "pinsa", "base pizza"
    ],
    "DOLCI E DESSERT": [
        "tiramisu", "tiramisù", "torta", "cheesecake", "profiteroles", "tartufo", "gelato",
        "sorbetto", "croissant", "cornetto", "brioche", "biscotti", "cioccolato", "nutella",
        "crema", "pasticceria", "dessert", "dolce", "muffin", "pancake", "waffle", "zucchero"
    ],
    "BEVANDE E VINI": [
        "acqua", "coca", "cola", "fanta", "sprite", "chinotto", "aranciata", "the", "tè",
        "succo", "birra", "vino", "prosecco", "spumante", "champagne", "rosso", "bianco",
        "rosato", "amaro", "liquore", "gin", "vodka", "rum", "whisky", "caffe", "caffè", "red bull"
    ],
    "NO FOOD E DETERGENZA": [
        "carta", "tovaglioli", "tovaglia", "rotolo", "alluminio", "pellicola", "guanti",
        "detergente", "sgrassatore", "sapone", "igienizzante", "sacchi", "contenitori",
        "vaschette", "bicchieri", "piatti", "posate", "cannucce", "asporto", "scatole pizza"
    ]
}


def guess_category_for_product(product_name: str, existing_categories: list) -> str:
    name_low = (product_name or "").lower()
    if not name_low:
        return existing_categories[0] if existing_categories else "OFFERTE"

    is_frozen = any(k in name_low for k in ["gelo", "surg", "iqf", "congelat"])

    for cat in existing_categories:
        cat_clean = cat.strip().lower()
        if len(cat_clean) >= 3 and cat_clean in name_low:
            return cat

    best_std_cat = None
    best_score = 0
    for std_cat, keywords in HORECA_CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if re.search(r'\b' + re.escape(kw), name_low))
        if score > best_score:
            best_score = score
            best_std_cat = std_cat

    if best_std_cat:
        std_words = [w.lower() for w in best_std_cat.split() if len(w) > 3]
        matching_existing = []
        for cat in existing_categories:
            cat_low = cat.lower()
            if any(w[:4] in cat_low for w in std_words):
                matching_existing.append(cat)
        if matching_existing:
            if is_frozen:
                for mc in matching_existing:
                    if "gelo" in mc.lower() or "surg" in mc.lower():
                        return mc
            else:
                for mc in matching_existing:
                    if "fresc" in mc.lower():
                        return mc
            return matching_existing[0]

        for cat in existing_categories:
            if "alimentar" in cat.lower() and best_std_cat in ("DISPENSA E ALIMENTARI", "SALUMI E LATTICINI", "ORTOFRUTTA E VERDURE"):
                return cat
        return best_std_cat

    return existing_categories[0] if existing_categories else "GENERALE"


# ==============================================================================
# PARSER FILE MULTI-FORMATO (PDF, CSV, XLSX, TESTO)
# ==============================================================================
def parse_price_value(raw) -> float:
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return round(float(raw), 2)
    s = str(raw).replace("€", "").replace("EUR", "").strip()
    m = re.search(r'(\d+[\.,]\d{1,2}|\d+)', s)
    if not m:
        return 0.0
    val_str = m.group(1).replace(",", ".")
    try:
        return round(float(val_str), 2)
    except Exception:
        return 0.0


def parse_xlsx_rows(file_bytes: bytes) -> list:
    rows = []
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            shared_strings = []
            if "xl/sharedStrings.xml" in z.namelist():
                ss_xml = ET.fromstring(z.read("xl/sharedStrings.xml"))
                for si in ss_xml.iter():
                    if si.tag.endswith("}si") or si.tag == "si":
                        texts = [t.text or "" for t in si.iter() if t.tag.endswith("}t") or t.tag == "t"]
                        shared_strings.append("".join(texts))

            sheet_files = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
            for sf in sorted(sheet_files):
                sh_xml = ET.fromstring(z.read(sf))
                for row_el in sh_xml.iter():
                    if row_el.tag.endswith("}row") or row_el.tag == "row":
                        row_vals = []
                        for c_el in row_el:
                            if not (c_el.tag.endswith("}c") or c_el.tag == "c"):
                                continue
                            c_type = c_el.attrib.get("t", "")
                            v_text = ""
                            for child in c_el:
                                if child.tag.endswith("}v") or child.tag == "v":
                                    v_text = child.text or ""
                                elif child.tag.endswith("}is") or child.tag == "is":
                                    v_text = "".join(t.text or "" for t in child.iter() if t.tag.endswith("}t") or t.tag == "t")
                            if c_type == "s" and v_text.isdigit():
                                idx = int(v_text)
                                if 0 <= idx < len(shared_strings):
                                    v_text = shared_strings[idx]
                            row_vals.append(v_text.strip())
                        if any(row_vals):
                            rows.append(row_vals)
    except Exception as e:
        print(f"[AI Agent] Errore parsing XLSX: {e}")
    return rows


def extract_products_from_rows(rows: list, existing_categories: list) -> list:
    if not rows:
        return []
    products = []
    header_map = {}

    for idx, row in enumerate(rows):
        cells = [str(c or "").strip() for c in row]
        if not any(cells):
            continue

        low_cells = [c.lower() for c in cells]
        if idx == 0 and any(k in " ".join(low_cells) for k in ["codice", "code", "art", "nome", "descrizione", "prodotto", "prezzo"]):
            for c_i, col_name in enumerate(low_cells):
                if any(k in col_name for k in ["cod", "art", "sku", "id"]):
                    header_map["codice"] = c_i
                elif any(k in col_name for k in ["nom", "desc", "prod", "titolo"]):
                    header_map["nome"] = c_i
                elif any(k in col_name for k in ["prez", "listino", "eur", "costo", "offerta"]):
                    header_map["prezzo"] = c_i
                elif any(k in col_name for k in ["cat", "reparto", "famiglia"]):
                    header_map["categoria"] = c_i
                elif any(k in col_name for k in ["um", "u.m", "unita", "unità"]):
                    header_map["um"] = c_i
            continue

        if header_map and ("nome" in header_map or "codice" in header_map):
            cod = cells[header_map["codice"]] if "codice" in header_map and header_map["codice"] < len(cells) else ""
            nom = cells[header_map["nome"]] if "nome" in header_map and header_map["nome"] < len(cells) else ""
            prz = parse_price_value(cells[header_map["prezzo"]]) if "prezzo" in header_map and header_map["prezzo"] < len(cells) else 0.0
            cat = cells[header_map["categoria"]] if "categoria" in header_map and header_map["categoria"] < len(cells) else ""
            um = cells[header_map["um"]] if "um" in header_map and header_map["um"] < len(cells) else "PZ"
            if nom or cod:
                if not cod:
                    cod = f"AI{idx:04d}"
                if not cat:
                    cat = guess_category_for_product(nom, existing_categories)
                products.append({
                    "codice": cod.strip(),
                    "nome": nom.strip() or f"Prodotto {cod}",
                    "prezzo": prz,
                    "um": (um or "PZ").upper(),
                    "categoria": cat
                })
        else:
            line_joined = " ".join(c for c in cells if c)
            parsed = extract_products_from_free_text(line_joined, existing_categories)
            if parsed:
                products.extend(parsed)
            elif len(cells) >= 2:
                cod = cells[0] if re.match(r'^[A-Za-z0-9\-_]{2,14}$', cells[0]) else f"AI{idx:04d}"
                nom = cells[1] if cod == cells[0] else cells[0]
                prz = parse_price_value(cells[2]) if len(cells) > 2 else parse_price_value(cells[-1])
                cat = guess_category_for_product(nom, existing_categories)
                if nom:
                    products.append({
                        "codice": cod,
                        "nome": nom,
                        "prezzo": prz,
                        "um": "PZ",
                        "categoria": cat
                    })
    return products


def extract_products_from_free_text(text: str, existing_categories: list) -> list:
    if not text:
        return []
    products = []
    lines = [l.strip() for l in re.split(r'[\n;]+', text) if l.strip()]

    um_list = ['KG', 'PZ', 'CT', 'BT', 'LT', 'CF', 'VAS', 'CONF', 'GR', 'SC', 'CART', 'L', 'ML', 'CL']
    um_regex = r'\b(' + '|'.join(um_list) + r')\b'

    for idx, raw_line in enumerate(lines):
        line = re.sub(r'^(?:[\-\*\•]+|\d{1,2}[\.\)])\s*', '', raw_line).strip()
        if not line or len(line) < 3:
            continue

        low = line.lower()
        for prefix in ["aggiungi questi prodotti:", "aggiungi prodotti:", "inserisci:", "carica:", "aggiungi ", "inserisci "]:
            if low.startswith(prefix):
                line = line[len(prefix):].strip()
                low = line.lower()

        code = ""
        m_explicit_code = re.search(r'\b(?:cod\.?|codice)\s*[:#]?\s*([A-Za-z0-9\-_]{2,14})\b', line, re.IGNORECASE)
        if m_explicit_code:
            code = m_explicit_code.group(1)
            line = (line[:m_explicit_code.start()] + " " + line[m_explicit_code.end():]).strip()
        else:
            m_lead_code = re.match(r'^([A-Za-z0-9]{3,14})\s+(.+)', line)
            if m_lead_code and any(ch.isdigit() for ch in m_lead_code.group(1)):
                code = m_lead_code.group(1)
                line = m_lead_code.group(2).strip()

        price = 0.0
        m_price = re.search(r'(?:€\s*(\d+[\.,]\d{1,2}|\d+))|(?:(\d+[\.,]\d{1,2}|\d+)\s*€)|(?:\ba\s+(\d+[\.,]\d{1,2})\b)|(?:\s(\d+[\.,]\d{2})(?:\s|$))', line, re.IGNORECASE)
        if m_price:
            p_str = next(g for g in m_price.groups() if g is not None)
            price = parse_price_value(p_str)
            line = (line[:m_price.start()] + " " + line[m_price.end():]).strip()

        cat = ""
        m_cat = re.search(r'\b(?:nella\s+categoria|in\s+categoria|categoria|cat\.?)\s+([A-Za-zÀ-ÿ\s]{2,25})$', line, re.IGNORECASE)
        if m_cat:
            cat = m_cat.group(1).strip().upper()
            line = line[:m_cat.start()].strip()
        else:
            for existing_c in existing_categories:
                m_in_c = re.search(r'\bin\s+' + re.escape(existing_c) + r'\b', line, re.IGNORECASE)
                if m_in_c:
                    cat = existing_c
                    line = (line[:m_in_c.start()] + " " + line[m_in_c.end():]).strip()
                    break

        um = "PZ"
        m_um = re.search(um_regex, line, re.IGNORECASE)
        if m_um:
            um = m_um.group(1).upper()

        name = re.sub(r'\s+', ' ', line).strip(" -,:;/")
        if not name or len(name) < 2:
            continue

        if not code and price == 0.0 and len(lines) == 1 and any(w in name.lower() for w in [
            "vorrei", "puoi", "come", "aiutami", "crea", "categorizza", "quanto", "quali", "chi",
            "fatturato", "visita", "visite", "ordine", "ordini", "cliente", "clienti", "sposta", "modifica"
        ]):
            continue

        if not code:
            initials = "".join(w[0].upper() for w in re.findall(r'[A-Za-z]+', name)[:3]) or "PRD"
            code = f"{initials}{abs(hash(name)) % 9000 + 1000}"

        if not cat:
            cat = guess_category_for_product(name, existing_categories)

        products.append({
            "codice": code,
            "nome": name,
            "prezzo": price,
            "um": um,
            "categoria": cat
        })

    return products


def parse_uploaded_file(file_storage, existing_categories: list) -> tuple[list, str]:
    filename = (file_storage.filename or "").lower()
    raw_bytes = file_storage.read()
    file_storage.seek(0)

    if filename.endswith(".pdf"):
        fd, temp_path = tempfile.mkstemp(suffix=".pdf")
        raw_text_pages = []
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(raw_bytes)
            products = []
            if _EXTRACT_PDF_FN:
                extracted = _EXTRACT_PDF_FN(temp_path) or []
                for p in extracted:
                    cat = p.get("categoria") or ""
                    if not cat or cat.upper() == "OFFERTE":
                        cat = guess_category_for_product(p.get("nome", ""), existing_categories)
                    products.append({
                        "codice": str(p.get("codice", "")).strip(),
                        "nome": str(p.get("nome", "")).strip(),
                        "prezzo": parse_price_value(p.get("prezzo", 0)),
                        "um": str(p.get("um", "PZ")).upper(),
                        "categoria": cat
                    })
            try:
                import pdfplumber
                with pdfplumber.open(temp_path) as pdf:
                    for page in pdf.pages[:10]:
                        t = page.extract_text()
                        if t:
                            raw_text_pages.append(t)
            except Exception:
                pass
            raw_text = "\n".join(raw_text_pages)
            if not products and raw_text:
                products = extract_products_from_free_text(raw_text, existing_categories)
            return products, raw_text
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    elif filename.endswith(".xlsx"):
        rows = parse_xlsx_rows(raw_bytes)
        products = extract_products_from_rows(rows, existing_categories)
        raw_text = "\n".join(["\t".join(r) for r in rows[:100]])
        return products, raw_text

    elif filename.endswith(".csv") or filename.endswith(".tsv"):
        text = raw_bytes.decode("utf-8", errors="replace")
        delimiter = ";" if text.count(";") > text.count(",") else ("\t" if "\t" in text else ",")
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = list(reader)
        products = extract_products_from_rows(rows, existing_categories)
        return products, text[:8000]

    else:
        text = raw_bytes.decode("utf-8", errors="replace")
        products = extract_products_from_free_text(text, existing_categories)
        return products, text[:8000]


# ==============================================================================
# SNAPSHOT COMPLETO DEL SITO & DATABASE (CONOSCENZA UNIVERSALE)
# ==============================================================================
GIORNI_SETTIMANA = {
    1: "Lunedì", 2: "Martedì", 3: "Mercoledì",
    4: "Giovedì", 5: "Venerdì", 6: "Sabato", 0: "Domenica"
}
GIORNI_DA_NOME = {
    "lunedi": 1, "lunedì": 1, "lun": 1,
    "martedi": 2, "martedì": 2, "mar": 2,
    "mercoledi": 3, "mercoledì": 3, "mer": 3,
    "giovedi": 4, "giovedì": 4, "gio": 4,
    "venerdi": 5, "venerdì": 5, "ven": 5,
    "sabato": 6, "sab": 6,
    "domenica": 0, "dom": 0
}


def get_db_snapshot():
    """Carica l'intero stato del gestionale: categorie, clienti, prodotti, visite, ordini, fatturato, comparatore."""
    oggi = date.today()
    lunedi_corr = oggi - timedelta(days=oggi.weekday())
    domenica_corr = lunedi_corr + timedelta(days=6)
    settimana_corr = lunedi_corr.isocalendar()[1]
    anno_corr = oggi.year

    with _GET_DB() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, nome FROM categorie ORDER BY nome")
        categorie = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM clienti ORDER BY nome")
        clienti = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT p.id, p.codice, p.nome, p.prezzo, p.immagine, p.categoria_id, c.nome AS categoria_nome
            FROM prodotti p
            LEFT JOIN categorie c ON p.categoria_id = c.id
            WHERE COALESCE(p.eliminato, FALSE) = FALSE
            ORDER BY p.nome
        """)
        prodotti = [dict(r) for r in cur.fetchall()]

        # Visite recenti / future
        visite = []
        try:
            cur.execute("""
                SELECT v.id, v.cliente_id, c.nome AS cliente_nome, c.zona,
                       v.data_visita, v.ora_visita, v.completata, v.note
                FROM visite v
                JOIN clienti c ON c.id = v.cliente_id
                ORDER BY v.data_visita DESC, v.ora_visita ASC
                LIMIT 60
            """)
            for r in cur.fetchall():
                d = dict(r)
                d["data_visita"] = str(d.get("data_visita") or "")
                d["ora_visita"] = str(d.get("ora_visita") or "")[:5]
                visite.append(d)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

        # Ordini / Fatturato settimanale corrente
        ordini_settimana = []
        try:
            cur.execute("""
                SELECT fs.id, fs.cliente_id, c.nome AS cliente_nome, fs.totale, fs.note, fs.settimana, fs.anno
                FROM fatturato_settimanale fs
                JOIN clienti c ON c.id = fs.cliente_id
                WHERE (fs.settimana = %s AND fs.anno = %s)
                   OR (fs.data_inizio = %s AND fs.data_fine = %s)
            """, (settimana_corr, anno_corr, str(lunedi_corr), str(domenica_corr)))
            for r in cur.fetchall():
                ordini_settimana.append(dict(r))
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

        # Fatturato mensile anno corrente
        fatturato_mensile = []
        try:
            cur.execute("""
                SELECT f.cliente_id, c.nome AS cliente_nome, f.mese, f.anno, f.totale
                FROM fatturato f
                JOIN clienti c ON c.id = f.cliente_id
                WHERE f.anno >= %s
                ORDER BY f.anno DESC, f.mese DESC
                LIMIT 150
            """, (anno_corr - 1,))
            for r in cur.fetchall():
                fatturato_mensile.append(dict(r))
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

        # Comparazioni salvate
        comparazioni = []
        try:
            cur.execute("""
                SELECT id, cliente_id, cliente_nome, titolo, totale_volume_kg,
                       totale_attuale_mese, totale_nuovo_mese, risparmio_mese, risparmio_anno, percentuale_risparmio
                FROM comparazioni_listini
                ORDER BY aggiornato_il DESC
                LIMIT 30
            """)
            for r in cur.fetchall():
                comparazioni.append(dict(r))
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    senza_cat = [p for p in prodotti if not p.get("categoria_id")]
    return {
        "oggi": str(oggi),
        "settimana_corrente": settimana_corr,
        "anno_corrente": anno_corr,
        "lunedi_corrente": str(lunedi_corr),
        "domenica_corrente": str(domenica_corr),
        "categorie": categorie,
        "categorie_nomi": [c["nome"] for c in categorie],
        "clienti": clienti,
        "prodotti": prodotti,
        "prodotti_senza_categoria": senza_cat,
        "visite": visite,
        "ordini_settimana": ordini_settimana,
        "fatturato_mensile": fatturato_mensile,
        "comparazioni": comparazioni
    }


def enrich_products_with_db_status(items: list, snapshot: dict, cliente_id: int = None) -> list:
    by_code = {str(p["codice"]).strip().upper(): p for p in snapshot["prodotti"] if p.get("codice")}
    by_name = {str(p["nome"]).strip().upper(): p for p in snapshot["prodotti"] if p.get("nome")}
    cat_names = snapshot["categorie_nomi"]

    enriched = []
    for idx, item in enumerate(items):
        cod = str(item.get("codice") or "").strip()
        nom = str(item.get("nome") or "").strip()
        prz = parse_price_value(item.get("prezzo", 0))
        prz_off = parse_price_value(item.get("prezzo_offerta", 0)) if item.get("prezzo_offerta") else None
        um = str(item.get("um") or "PZ").strip().upper()
        cat = str(item.get("categoria") or "").strip()

        existing = None
        if cod and cod.upper() in by_code:
            existing = by_code[cod.upper()]
        elif nom and nom.upper() in by_name:
            existing = by_name[nom.upper()]

        if existing:
            if not cod:
                cod = existing.get("codice") or f"PRD{existing['id']}"
            if not nom:
                nom = existing.get("nome") or ""
            if prz == 0.0 and existing.get("prezzo"):
                prz = parse_price_value(existing.get("prezzo"))
            if not cat and existing.get("categoria_nome"):
                cat = existing.get("categoria_nome")

        if not cod:
            initials = "".join(w[0].upper() for w in re.findall(r'[A-Za-z]+', nom)[:3]) or "PRD"
            cod = f"{initials}{abs(hash(nom + str(idx))) % 9000 + 1000}"

        if not cat:
            cat = guess_category_for_product(nom, cat_names)

        img_url = item.get("immagine") or ""
        if not img_url and existing and existing.get("immagine"):
            img_val = existing["immagine"]
            if img_val.startswith("http") or img_val.startswith("/"):
                img_url = img_val
            else:
                img_url = f"/static/uploads/volantino_prodotti/{img_val}"

        enriched.append({
            "id": existing["id"] if existing else None,
            "codice": cod,
            "nome": nom,
            "prezzo": prz,
            "prezzo_offerta": prz_off,
            "um": um,
            "categoria": cat,
            "immagine": img_url,
            "stato": "esistente" if existing else "nuovo",
            "potenziale": bool(item.get("potenziale", False))
        })
    return enriched


def find_best_client(client_query: str, clienti_list: list, page_client_id: int = None):
    if client_query:
        q = client_query.strip().lower()
        for c in clienti_list:
            if c["nome"].lower() == q:
                return c
        for c in clienti_list:
            if q in c["nome"].lower() or c["nome"].lower() in q:
                return c
    if page_client_id:
        for c in clienti_list:
            if int(c["id"]) == int(page_client_id):
                return c
    return clienti_list[0] if clienti_list else None


def extract_product_search_term(raw_message: str) -> str:
    s = (raw_message or "").strip()
    patterns = [
        r'^(?:cerca|trova|dimmi|mostrami|verifica|controlla)\s+',
        r'^(?:quale|quali)\s+(?:dei\s+miei\s+)?client[ie]\s+(?:lavora(?:no)?|compra(?:no)?|ha(?:nno)?|acquista(?:no)?)\s+',
        r'^(?:chi)\s+(?:dei\s+miei\s+clienti\s+)?(?:lavora|compra|ha|acquista|usa)\s+',
        r'^(?:clienti\s+che\s+(?:lavorano|comprano|hanno))\s+',
        r'^(?:il\s+prodotto|prodotto|l\'articolo|articolo|codice|cod\.?)\s+',
        r'\s+(?:o\s+un\s+prodotto\s+simile|o\s+prodotti\s+simili|o\s+simil[ei]|e\s+simili)\b.*$',
        r'[\?\!\.]+$'
    ]
    for pat in patterns:
        s = re.sub(pat, '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'^(?:il\s+prodotto|prodotto|quel\s+prodotto|il|lo|la|i|gli|le)\s+', '', s, flags=re.IGNORECASE).strip()
    return s.strip(' "\'')


def search_clients_by_product_or_similar(query_str: str, snapshot: dict) -> dict:
    clean_term = extract_product_search_term(query_str)
    if not clean_term:
        clean_term = (query_str or "").strip()

    term_low = clean_term.lower()
    stop_words = {"di", "del", "della", "dei", "delle", "con", "per", "in", "da", "al", "alla", "il", "la", "le", "un", "una", "kg", "pz", "gr", "lt", "ml", "ct", "cf"}
    keywords = [w for w in re.findall(r'[a-zA-ZÀ-ÿ0-9]{3,}', term_low) if w not in stop_words]

    with _GET_DB() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT cp.cliente_id, c.nome AS cliente_nome, c.zona AS cliente_zona,
                   cp.prodotto_id, p.codice AS prodotto_codice, p.nome AS prodotto_nome,
                   p.categoria_id, cat.nome AS categoria_nome,
                   cp.lavorato, cp.potenziale, cp.prezzo_attuale, cp.prezzo_offerta
            FROM clienti_prodotti cp
            JOIN clienti c ON c.id = cp.cliente_id
            JOIN prodotti p ON p.id = cp.prodotto_id
            LEFT JOIN categorie cat ON cat.id = p.categoria_id
            WHERE COALESCE(p.eliminato, FALSE) = FALSE
            ORDER BY c.nome
        """)
        all_links = [dict(r) for r in cur.fetchall()]

    links_by_prod = {}
    for lk in all_links:
        pid = lk["prodotto_id"]
        links_by_prod.setdefault(pid, []).append(lk)

    exact_products = []
    keyword_similar_products = []
    matched_cat_ids = set()
    inferred_cat_name = guess_category_for_product(clean_term, snapshot["categorie_nomi"])

    for p in snapshot["prodotti"]:
        p_name_low = (p.get("nome") or "").lower()
        p_code_low = str(p.get("codice") or "").lower()

        is_exact = False
        if term_low and (term_low == p_code_low or term_low in p_name_low):
            is_exact = True
        elif keywords and all(kw in p_name_low or kw == p_code_low for kw in keywords):
            is_exact = True

        if is_exact:
            exact_products.append(p)
            if p.get("categoria_id"):
                matched_cat_ids.add(p["categoria_id"])
        else:
            shared_kw = False
            for kw in keywords:
                stem = kw[:-1] if len(kw) >= 6 else kw
                if re.search(r'\b' + re.escape(stem), p_name_low):
                    shared_kw = True
                    break
            if shared_kw:
                keyword_similar_products.append(p)
                if p.get("categoria_id"):
                    matched_cat_ids.add(p["categoria_id"])

    category_similar_products = []
    inferred_base = (inferred_cat_name or "").split()[0].lower() if inferred_cat_name else ""
    for p in snapshot["prodotti"]:
        if p in exact_products or p in keyword_similar_products:
            continue
        p_cat = p.get("categoria_nome") or guess_category_for_product(p.get("nome", ""), snapshot["categorie_nomi"])
        if (p.get("categoria_id") and p["categoria_id"] in matched_cat_ids) or (
            inferred_base and len(inferred_base) >= 4 and inferred_base in (p_cat or "").lower()
        ):
            category_similar_products.append(p)

    similar_products = keyword_similar_products + category_similar_products

    def format_product_with_clients(prod_list):
        out = []
        for p in prod_list:
            p_links = links_by_prod.get(p["id"], [])
            clienti_attivi = []
            for lk in p_links:
                stato_cli = "Lavorato" if lk.get("lavorato") else ("Potenziale" if lk.get("potenziale") else "Ex-Lavorato")
                clienti_attivi.append({
                    "cliente_id": lk["cliente_id"],
                    "cliente_nome": lk["cliente_nome"],
                    "zona": lk.get("cliente_zona") or "",
                    "prezzo_attuale": parse_price_value(lk.get("prezzo_attuale")),
                    "prezzo_offerta": parse_price_value(lk.get("prezzo_offerta")) if lk.get("prezzo_offerta") else None,
                    "stato": stato_cli,
                    "lavorato": bool(lk.get("lavorato"))
                })
            out.append({
                "id": p["id"],
                "codice": p.get("codice") or "",
                "nome": p["nome"],
                "prezzo_catalogo": parse_price_value(p.get("prezzo")),
                "categoria": p.get("categoria_nome") or "Senza Categoria",
                "clienti": clienti_attivi
            })
        out.sort(key=lambda x: (-len(x["clienti"]), x["nome"]))
        return out

    exact_formatted = format_product_with_clients(exact_products)
    similar_formatted = format_product_with_clients(similar_products)
    similar_final = similar_formatted[:15]

    exact_client_ids = {c["cliente_id"] for ep in exact_formatted for c in ep["clienti"] if c["lavorato"]}
    similar_only_clients = {}
    for sp in similar_final:
        for c in sp["clienti"]:
            if c["lavorato"] and c["cliente_id"] not in exact_client_ids:
                similar_only_clients[c["cliente_id"]] = {
                    "cliente_id": c["cliente_id"],
                    "cliente_nome": c["cliente_nome"],
                    "zona": c["zona"],
                    "prodotto_simile": sp["nome"],
                    "prezzo": c["prezzo_attuale"]
                }

    return {
        "query": clean_term,
        "exact_products": exact_formatted,
        "similar_products": similar_final,
        "cross_sell_clients": list(similar_only_clients.values()),
        "totale_clienti_diretti": len(exact_client_ids),
        "totale_clienti_simili": len(similar_only_clients)
    }


# ==============================================================================
# ESECUTORE UNIVERSALE DI OPERAZIONI SUL GESTIONALE (CLIENTI, VISITE, ORDINI, COMPARATORE, CATALOGO)
# ==============================================================================
def resolve_natural_date(date_str: str) -> str:
    """Converte espressioni come 'oggi', 'domani', 'lunedì', '15/11/2026' in YYYY-MM-DD."""
    oggi = date.today()
    if not date_str:
        return str(oggi)
    s = str(date_str).strip().lower()
    if "dopodomani" in s:
        return str(oggi + timedelta(days=2))
    if "domani" in s or "tomorrow" in s:
        return str(oggi + timedelta(days=1))
    if "ieri" in s:
        return str(oggi - timedelta(days=1))
    if s in ("oggi", "today", "adesso", "ora") or re.search(r'\boggi\b', s):
        return str(oggi)

    for day_name, day_idx in GIORNI_DA_NOME.items():
        if len(day_name) >= 4 and re.search(r'\b' + re.escape(day_name), s):
            target_wd = (day_idx - 1) if day_idx >= 1 else 6  # python weekday: Mon=0..Sun=6
            days_ahead = (target_wd - oggi.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return str(oggi + timedelta(days=days_ahead))

    m_iso = re.search(r'(\d{4})-(\d{2})-(\d{2})', s)
    if m_iso:
        return m_iso.group(0)
    m_it = re.search(r'(\d{1,2})[\/\-\.](\d{1,2})(?:[\/\-\.](\d{2,4}))?', s)
    if m_it:
        d_i = int(m_it.group(1))
        m_i = int(m_it.group(2))
        y_i = int(m_it.group(3)) if m_it.group(3) else oggi.year
        if y_i < 100:
            y_i += 2000
        try:
            return str(date(y_i, m_i, d_i))
        except Exception:
            pass
    return str(oggi)


def execute_universal_site_operation(op_type: str, params: dict, snapshot: dict) -> dict:
    """
    Esegue immediatamente un'operazione richiesta dall'utente su qualsiasi sezione del sito:
    - manage_client: crea/aggiorna cliente, giro visita, zona, telefono, consegna
    - manage_visita: pianifica/completa/modifica/elimina una visita
    - manage_ordine_fatturato: registra ordine settimanale o fatturato mensile
    - manage_comparatore: crea o aggiorna un preventivo nel comparatore offerte (con supporto kg/pz)
    - manage_catalog_and_prices: modifica prezzi (% o fissi), rinomina, cambia categoria, elimina prodotti/categorie
    """
    with _GET_DB() as conn:
        cur = conn.cursor()

        # ----------------------------------------------------------------------
        # A. GESTIONE CLIENTI, ZONE, GIRO VISITA E GIORNI CONSEGNA
        # ----------------------------------------------------------------------
        if op_type == "manage_client":
            azione = (params.get("azione") or "aggiorna").lower()
            nome_cli = (params.get("cliente_nome") or "").strip()
            nuovo_nome = (params.get("nuovo_nome") or "").strip()
            zona = params.get("zona")
            telefono = params.get("telefono")
            email = params.get("email")
            giorno_visita = params.get("giorno_visita")
            ora_visita = params.get("ora_visita")
            giorni_consegna = params.get("giorni_consegna")

            giorno_int = None
            if giorno_visita is not None and str(giorno_visita).strip() != "":
                gv_str = str(giorno_visita).strip().lower()
                if gv_str.isdigit():
                    giorno_int = int(gv_str)
                else:
                    for k, v in GIORNI_DA_NOME.items():
                        if k in gv_str:
                            giorno_int = v
                            break

            target = find_best_client(nome_cli, snapshot["clienti"]) if nome_cli else None
            avail_cols = set(snapshot["clienti"][0].keys()) if snapshot["clienti"] else {"id", "nome", "zona", "fatturato_totale"}

            if azione == "crea" or (not target and nome_cli):
                cur.execute("""
                    INSERT INTO clienti (nome, zona, fatturato_totale)
                    VALUES (%s, %s, 0) RETURNING id
                """, (nome_cli, zona or "Da assegnare"))
                row = cur.fetchone()
                new_id = row["id"] if row else None
                if new_id:
                    for col_n, col_v in [
                        ("telefono", telefono),
                        ("email", email),
                        ("giorno_visita_standard", giorno_int),
                        ("ora_visita_standard", ora_visita),
                        ("giorni_consegna_standard", giorni_consegna)
                    ]:
                        if col_v is not None and str(col_v).strip() != "" and col_n in avail_cols:
                            try:
                                cur.execute(f"UPDATE clienti SET {col_n} = %s WHERE id = %s", (col_v, new_id))
                            except Exception:
                                try:
                                    conn.rollback()
                                except Exception:
                                    pass
                conn.commit()
                return {
                    "ok": True,
                    "message": f"✅ Creato automaticamente il nuovo cliente **{nome_cli}**" + (f" (Zona: **{zona}**)" if zona else "") + "!",
                    "redirect_url": f"/clienti/{new_id}" if new_id else "/clienti",
                    "redirect_label": f"👤 Apri Scheda {nome_cli}"
                }

            if not target:
                return {"ok": False, "error": "Specifica il nome del cliente da modificare."}

            cid = target["id"]
            if azione == "elimina":
                cur.execute("DELETE FROM clienti_prodotti WHERE cliente_id = %s", (cid,))
                cur.execute("DELETE FROM clienti WHERE id = %s", (cid,))
                conn.commit()
                return {
                    "ok": True,
                    "message": f"🗑️ Cliente **{target['nome']}** eliminato dal gestionale.",
                    "redirect_url": "/clienti",
                    "redirect_label": "👥 Torna a Clienti"
                }

            updates = []
            vals = []
            changes_desc = []
            if nuovo_nome:
                updates.append("nome = %s")
                vals.append(nuovo_nome)
                changes_desc.append(f"nome → **{nuovo_nome}**")
            if zona is not None and str(zona).strip() != "":
                updates.append("zona = %s")
                vals.append(str(zona).strip())
                changes_desc.append(f"zona → **{zona}**")
            if telefono is not None and str(telefono).strip() != "" and "telefono" in avail_cols:
                updates.append("telefono = %s")
                vals.append(str(telefono).strip())
                changes_desc.append(f"telefono → **{telefono}**")
            if email is not None and str(email).strip() != "" and "email" in avail_cols:
                updates.append("email = %s")
                vals.append(str(email).strip())
                changes_desc.append(f"email → **{email}**")
            if giorno_int is not None and "giorno_visita_standard" in avail_cols:
                updates.append("giorno_visita_standard = %s")
                vals.append(giorno_int)
                changes_desc.append(f"giro visita → **{GIORNI_SETTIMANA.get(giorno_int, giorno_int)}**")
            if ora_visita and "ora_visita_standard" in avail_cols:
                updates.append("ora_visita_standard = %s")
                vals.append(str(ora_visita).strip())
                changes_desc.append(f"orario visita → **{ora_visita}**")
            if giorni_consegna and "giorni_consegna_standard" in avail_cols:
                updates.append("giorni_consegna_standard = %s")
                vals.append(str(giorni_consegna).strip())
                changes_desc.append(f"consegna → **{giorni_consegna}**")

            if updates:
                vals.append(cid)
                cur.execute(f"UPDATE clienti SET {', '.join(updates)} WHERE id = %s", tuple(vals))
                conn.commit()

            dettaglio = ", ".join(changes_desc) if changes_desc else "dati anagrafici aggiornati"
            return {
                "ok": True,
                "message": f"✅ Ho sistemato il cliente **{target['nome']}**: {dettaglio}.",
                "redirect_url": f"/clienti/{cid}",
                "redirect_label": f"👤 Vedi {target['nome']}"
            }

        # ----------------------------------------------------------------------
        # B. GESTIONE VISITE & CALENDARIO GIRI
        # ----------------------------------------------------------------------
        elif op_type == "manage_visita":
            azione = (params.get("azione") or "pianifica").lower()
            nome_cli = (params.get("cliente_nome") or "").strip()
            target = find_best_client(nome_cli, snapshot["clienti"])
            if not target:
                return {"ok": False, "error": f"Cliente '{nome_cli}' non trovato."}

            data_iso = resolve_natural_date(params.get("data") or "oggi")
            ora_str = (params.get("ora") or "10:00").strip()
            note_str = (params.get("note") or "").strip()
            completata = bool(params.get("completata", False)) or (azione == "completa")

            if azione == "elimina":
                cur.execute("DELETE FROM visite WHERE cliente_id = %s AND data_visita = %s", (target["id"], data_iso))
                conn.commit()
                return {
                    "ok": True,
                    "message": f"🗑️ Rimossa la visita per **{target['nome']}** del **{data_iso}**.",
                    "redirect_url": "/visite",
                    "redirect_label": "📅 Vai a Visite & Giri"
                }

            cur.execute("SELECT id FROM visite WHERE cliente_id = %s AND data_visita = %s", (target["id"], data_iso))
            existing_v = cur.fetchone()
            if existing_v:
                cur.execute("""
                    UPDATE visite
                    SET ora_visita = %s, note = COALESCE(NULLIF(%s, ''), note), completata = %s
                    WHERE id = %s
                """, (ora_str, note_str, completata, existing_v["id"]))
            else:
                cur.execute("""
                    INSERT INTO visite (cliente_id, data_visita, ora_visita, note, completata)
                    VALUES (%s, %s, %s, %s, %s)
                """, (target["id"], data_iso, ora_str, note_str, completata))
            conn.commit()

            stato_txt = "completata" if completata else "pianificata"
            return {
                "ok": True,
                "message": f"✅ Visita **{stato_txt}** per **{target['nome']}** in data **{data_iso}** alle **{ora_str}**" + (f" (Note: *{note_str}*)" if note_str else "") + "!",
                "redirect_url": "/visite",
                "redirect_label": "📅 Apri Calendario Visite"
            }

        # ----------------------------------------------------------------------
        # C. GESTIONE ORDINI SETTIMANALI & FATTURATO MENSILE
        # ----------------------------------------------------------------------
        elif op_type == "manage_ordine_fatturato":
            nome_cli = (params.get("cliente_nome") or "").strip()
            target = find_best_client(nome_cli, snapshot["clienti"])
            if not target:
                return {"ok": False, "error": f"Cliente '{nome_cli}' non trovato."}

            importo = parse_price_value(params.get("importo", 0))
            tipo_reg = (params.get("tipo") or "ordine_settimanale").lower()
            mese = int(params.get("mese") or date.today().month)
            anno = int(params.get("anno") or date.today().year)
            note = (params.get("note") or "").strip()

            if tipo_reg == "fatturato_mensile":
                cur.execute("SELECT id FROM fatturato WHERE cliente_id = %s AND mese = %s AND anno = %s", (target["id"], mese, anno))
                r_f = cur.fetchone()
                if r_f:
                    cur.execute("UPDATE fatturato SET totale = %s WHERE id = %s", (importo, r_f["id"]))
                else:
                    cur.execute("INSERT INTO fatturato (cliente_id, mese, anno, totale) VALUES (%s, %s, %s, %s)", (target["id"], mese, anno, importo))
            else:
                oggi = date.today()
                lun = oggi - timedelta(days=oggi.weekday())
                dom = lun + timedelta(days=6)
                sett = lun.isocalendar()[1]
                cur.execute("""
                    SELECT id FROM fatturato_settimanale
                    WHERE cliente_id = %s AND ((settimana = %s AND anno = %s) OR (data_inizio = %s AND data_fine = %s))
                """, (target["id"], sett, anno, str(lun), str(dom)))
                r_o = cur.fetchone()
                if r_o:
                    cur.execute("UPDATE fatturato_settimanale SET totale = %s, note = %s WHERE id = %s", (importo, note, r_o["id"]))
                else:
                    cur.execute("""
                        INSERT INTO fatturato_settimanale (cliente_id, data_inizio, data_fine, settimana, mese, anno, totale, note)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (target["id"], str(lun), str(dom), sett, oggi.month, anno, importo, note))

            # Ricalcola fatturato_totale del cliente
            cur.execute("SELECT COALESCE(SUM(totale), 0) AS s FROM fatturato WHERE cliente_id = %s", (target["id"],))
            sum_f = float((cur.fetchone() or {}).get("s") or 0)
            cur.execute("SELECT COALESCE(SUM(totale), 0) AS s FROM fatturato_settimanale WHERE cliente_id = %s", (target["id"],))
            sum_fs = float((cur.fetchone() or {}).get("s") or 0)
            nuovo_tot = max(sum_f, sum_fs, importo)
            cur.execute("UPDATE clienti SET fatturato_totale = %s WHERE id = %s", (nuovo_tot, target["id"]))
            conn.commit()

            return {
                "ok": True,
                "message": f"✅ Registrato **{tipo_reg.replace('_', ' ')}** di **€ {importo:.2f}** per il cliente **{target['nome']}**!",
                "redirect_url": "/ordini" if tipo_reg != "fatturato_mensile" else "/fatturato",
                "redirect_label": "🚚 Vai a Ordini & Fatturato"
            }

        # ----------------------------------------------------------------------
        # D. GESTIONE COMPARATORE OFFERTE (CON SUPPORTO KG / PZ)
        # ----------------------------------------------------------------------
        elif op_type == "manage_comparatore":
            nome_cli = (params.get("cliente_nome") or "").strip()
            target = find_best_client(nome_cli, snapshot["clienti"]) if nome_cli else None
            cliente_id = target["id"] if target else None
            cliente_label = target["nome"] if target else (nome_cli or "Cliente")
            titolo = (params.get("titolo") or f"Proposta Comparativa - {cliente_label}").strip()
            righe_input = params.get("prodotti") or []

            prodotti_comp = []
            tot_vol = 0.0
            tot_att_m = 0.0
            tot_nos_m = 0.0

            for r in righe_input:
                vol = float(r.get("volume") or r.get("volume_kg") or 20)
                um = "pz" if str(r.get("um") or "kg").lower().strip() == "pz" else "kg"
                pa = parse_price_value(r.get("prezzo_attuale") or r.get("prezzo_pagato") or 0)
                pn = parse_price_value(r.get("prezzo_nostro") or r.get("prezzo") or 0)
                if pa == 0 and pn > 0:
                    pa = round(pn * 1.15, 2)
                tot_vol += vol
                tot_att_m += vol * pa
                tot_nos_m += vol * pn
                prodotti_comp.append({
                    "nome": str(r.get("nome") or "Prodotto").strip(),
                    "codice": str(r.get("codice") or "").strip(),
                    "volume_kg": vol,
                    "um": um,
                    "prezzo_attuale": pa,
                    "prezzo_nostro": pn
                })

            risp_m = tot_att_m - tot_nos_m
            risp_a = risp_m * 12
            perc = ((risp_m / tot_att_m) * 100) if tot_att_m > 0 else 0.0
            dati_json = json.dumps({"prodotti": prodotti_comp, "impostazioni_pdf": {}}, ensure_ascii=False)

            cur.execute("""
                INSERT INTO comparazioni_listini (
                    cliente_id, cliente_nome, titolo, note,
                    totale_volume_kg, totale_attuale_mese, totale_nuovo_mese,
                    risparmio_mese, risparmio_anno, percentuale_risparmio, dati_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, (cliente_id, cliente_label, titolo, "", tot_vol, tot_att_m, tot_nos_m, risp_m, risp_a, perc, dati_json))
            row_c = cur.fetchone()
            comp_id = row_c["id"] if row_c else None
            conn.commit()

            return {
                "ok": True,
                "message": (
                    f"✅ Ho creato il prospetto nel **Comparatore Offerte** per **{cliente_label}** ({len(prodotti_comp)} prodotti)!\n"
                    f"💰 Risparmio calcolato: **€ {risp_m:.2f}/mese** (**€ {risp_a:.2f}/anno**, **-{perc:.1f}%**)."
                ),
                "redirect_url": f"/comparatore?id={comp_id}" if comp_id else "/comparatore",
                "redirect_label": "⚖️ Apri nel Comparatore Offerte"
            }

        # ----------------------------------------------------------------------
        # E. MODIFICA RAPIDA CATALOGO, PREZZI (% O FISSI), CATEGORIE
        # ----------------------------------------------------------------------
        elif op_type == "manage_catalog_and_prices":
            azione = (params.get("azione") or "aggiorna_prezzo").lower()
            filtro_nome = (params.get("prodotto_filtro") or "").strip()
            filtro_cat = (params.get("categoria_filtro") or "").strip()
            nuovo_prezzo = params.get("nuovo_prezzo")
            variazione_perc = params.get("variazione_percentuale")
            nuova_cat = (params.get("nuova_categoria") or "").strip()
            nuovo_nome = (params.get("nuovo_nome") or "").strip()

            cur.execute("SELECT id, nome FROM categorie")
            cat_map = {r["nome"].strip().upper(): r["id"] for r in cur.fetchall()}

            target_cat_id = None
            if nuova_cat:
                if nuova_cat.upper() in cat_map:
                    target_cat_id = cat_map[nuova_cat.upper()]
                else:
                    cur.execute("INSERT INTO categorie (nome) VALUES (%s) RETURNING id", (nuova_cat,))
                    rc = cur.fetchone()
                    target_cat_id = rc["id"] if rc else None

            matched_ids = []
            for p in snapshot["prodotti"]:
                if filtro_nome and filtro_nome.lower() not in (p.get("nome") or "").lower() and filtro_nome.lower() != str(p.get("codice") or "").lower():
                    continue
                if filtro_cat and filtro_cat.lower() not in (p.get("categoria_nome") or "").lower():
                    continue
                matched_ids.append(p)

            if not matched_ids:
                return {"ok": False, "error": "Nessun prodotto trovato con i criteri specificati."}

            count_mod = 0
            for p in matched_ids:
                pid = p["id"]
                if azione == "elimina":
                    cur.execute("UPDATE prodotti SET eliminato = TRUE WHERE id = %s", (pid,))
                    count_mod += 1
                else:
                    p_curr = parse_price_value(p.get("prezzo", 0))
                    p_new = p_curr
                    if nuovo_prezzo is not None and parse_price_value(nuovo_prezzo) > 0:
                        p_new = parse_price_value(nuovo_prezzo)
                    elif variazione_perc is not None:
                        perc_f = float(variazione_perc)
                        p_new = round(p_curr * (1.0 + perc_f / 100.0), 2)

                    name_final = nuovo_nome if (nuovo_nome and len(matched_ids) == 1) else p["nome"]
                    cat_final = target_cat_id if target_cat_id is not None else p.get("categoria_id")
                    cur.execute("""
                        UPDATE prodotti
                        SET nome = %s, categoria_id = %s, prezzo = %s
                        WHERE id = %s
                    """, (name_final, cat_final, p_new if p_new > 0 else p.get("prezzo"), pid))
                    count_mod += 1

            conn.commit()
            return {
                "ok": True,
                "message": f"✅ Ho aggiornato automaticamente **{count_mod} prodotti** nel catalogo!",
                "redirect_url": "/prodotti",
                "redirect_label": "📦 Vedi Catalogo Prodotti"
            }

    return {"ok": False, "error": f"Operazione '{op_type}' non riconosciuta."}


# ==============================================================================
# MOTORE DI RISPOSTA UNIVERSALE ALLE DOMANDE SUL SITO (Q&A + STATISTICHE)
# ==============================================================================
def answer_universal_site_question(question: str, snapshot: dict) -> str:
    """Risponde a qualsiasi domanda su fatturato, clienti, visite, giri, ordini, prodotti e comparatore."""
    q_low = (question or "").lower()

    # 1. Domande su FATTURATO / TOP CLIENTI / INCASSI
    if any(k in q_low for k in ["fatturato", "incasso", "guadagno", "migliori clienti", "top clienti", "quanto abbiamo fatto"]):
        tot_generale = sum(float(c.get("fatturato_totale") or 0) for c in snapshot["clienti"])
        top_clienti = sorted(snapshot["clienti"], key=lambda x: float(x.get("fatturato_totale") or 0), reverse=True)[:8]
        top_lines = "\n".join([
            f"- **{c['nome']}** ({c.get('zona') or 'N/D'}): **€ {float(c.get('fatturato_totale') or 0):,.2f}**"
            for c in top_clienti if float(c.get("fatturato_totale") or 0) > 0
        ]) or "- Nessun fatturato registrato finora."
        return (
            f"📊 **Riepilogo Fatturato Gestionale**:\n"
            f"- **Fatturato Totale Complessivo**: **€ {tot_generale:,.2f}** su **{len(snapshot['clienti'])} clienti**\n\n"
            f"🏆 **Top Clienti per Fatturato**:\n{top_lines}"
        )

    # 2. Domande su VISITE / GIRO VISITE / APPUNTAMENTI
    if any(k in q_low for k in ["visit", "giro", "appuntament", "chi devo vedere", "programma"]):
        for g_name, g_num in GIORNI_DA_NOME.items():
            if g_name in q_low and len(g_name) >= 3:
                cli_g = [c for c in snapshot["clienti"] if str(c.get("giorno_visita_standard") or "") == str(g_num)]
                lines = "\n".join([
                    f"- **{c['nome']}** ({c.get('zona') or 'Zona N/D'}) — Ore: `{c.get('ora_visita_standard') or 'N/D'}`"
                    for c in cli_g
                ]) or "- Nessun cliente assegnato a questo giorno."
                return f"🗓️ **Giro Visite del {GIORNI_SETTIMANA.get(g_num, g_name.title())}** ({len(cli_g)} clienti):\n{lines}"

        vis_oggi = [v for v in snapshot["visite"] if v.get("data_visita") == snapshot["oggi"]]
        vis_rec = snapshot["visite"][:8]
        lines = "\n".join([
            f"- **{v['data_visita']}** ore `{v.get('ora_visita') or '--:--'}` → **{v['cliente_nome']}** ({'✅ Completata' if v.get('completata') else '⏳ Da fare'})"
            for v in (vis_oggi or vis_rec)
        ]) or "- Nessuna visita registrata in calendario."
        return (
            f"📅 **Situazione Visite Commerciali** (Oggi `{snapshot['oggi']}`: **{len(vis_oggi)} visite**):\n{lines}\n\n"
            "💡 *Puoi dirmi ad esempio: \"Pianifica una visita per Blu Mare domani alle 15:00\" oppure \"Metti Leonardo nel giro del Martedì\".*"
        )

    # 3. Domande su ORDINI SETTIMANALI / CHI DEVE ORDINARE
    if any(k in q_low for k in ["ordin", "scarich", "consegn", "chi manca"]):
        ordinati_ids = {o["cliente_id"] for o in snapshot["ordini_settimana"] if float(o.get("totale") or 0) > 0}
        tot_sett = sum(float(o.get("totale") or 0) for o in snapshot["ordini_settimana"])
        mancanti = [c for c in snapshot["clienti"] if c["id"] not in ordinati_ids][:12]
        ord_lines = "\n".join([
            f"- **{o['cliente_nome']}**: **€ {float(o.get('totale') or 0):,.2f}**"
            for o in snapshot["ordini_settimana"] if float(o.get("totale") or 0) > 0
        ]) or "- Nessun ordine registrato per questa settimana."
        manc_lines = ", ".join([f"**{c['nome']}**" for c in mancanti]) or "Nessuno"
        return (
            f"🚚 **Ordini Settimana #{snapshot['settimana_corrente']}** ({snapshot['lunedi_corrente']} → {snapshot['domenica_corrente']}):\n"
            f"- **Totale Confermato**: **€ {tot_sett:,.2f}** ({len(ordinati_ids)} clienti hanno ordinato)\n"
            f"{ord_lines}\n\n"
            f"⏳ **Clienti che non hanno ancora ordinato**: {manc_lines}"
        )

    # 4. Domande su PREVENTIVI / COMPARATORE OFFERTE
    if any(k in q_low for k in ["preventiv", "comparat", "propost"]):
        comp_list = snapshot.get("comparazioni") or []
        c_lines = "\n".join([
            f"- **#{c['id']} {c.get('titolo') or 'Proposta'}** ({c.get('cliente_nome') or 'Cliente'}) → Risparmio: **€ {float(c.get('risparmio_anno') or 0):,.2f}/anno** (`-{float(c.get('percentuale_risparmio') or 0):.1f}%`) — [Apri](/comparatore?id={c['id']})"
            for c in comp_list[:10]
        ]) or "- Nessun preventivo salvato nel comparatore."
        return f"⚖️ **Preventivi nel Comparatore Offerte ({len(comp_list)})**:\n{c_lines}"

    # 5. Domande su uno specifico CLIENTE
    for c in snapshot["clienti"]:
        if c["nome"].lower() in q_low:
            with _GET_DB() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT p.codice, p.nome, cp.prezzo_attuale, cp.prezzo_offerta, cp.lavorato
                    FROM clienti_prodotti cp
                    JOIN prodotti p ON p.id = cp.prodotto_id
                    WHERE cp.cliente_id = %s AND COALESCE(p.eliminato, FALSE) = FALSE
                    ORDER BY cp.lavorato DESC, p.nome
                """, (c["id"],))
                prods = [dict(r) for r in cur.fetchall()]
            p_lines = "\n".join([
                f"- `{p.get('codice') or 'S/C'}` **{p['nome']}** → **€ {parse_price_value(p.get('prezzo_attuale')):.2f}**"
                for p in prods[:15]
            ]) or "- Nessun prodotto ancora associato."
            giro_lbl = GIORNI_SETTIMANA.get(int(c["giorno_visita_standard"]), "Non assegnato") if str(c.get("giorno_visita_standard") or "").isdigit() else "Non assegnato"
            return (
                f"👤 **Scheda Cliente: {c['nome']}**\n"
                f"- **Zona**: {c.get('zona') or 'N/D'} | **Tel**: {c.get('telefono') or 'N/D'}\n"
                f"- **Fatturato Totale**: **€ {float(c.get('fatturato_totale') or 0):,.2f}**\n"
                f"- **Giro Visita**: {giro_lbl} ({c.get('ora_visita_standard') or 'orario N/D'})\n"
                f"- **Prodotti lavorati ({len(prods)})**:\n{p_lines}"
            )

    # 6. Domande su PRODOTTI / PREZZO DI UN PRODOTTO / CATEGORIE
    for p in snapshot["prodotti"]:
        p_nom_l = (p.get("nome") or "").lower()
        if len(p_nom_l) >= 4 and p_nom_l in q_low:
            return (
                f"📦 **Prodotto a Catalogo: {p['nome']}**\n"
                f"- **Codice**: `{p.get('codice') or 'S/C'}`\n"
                f"- **Categoria**: **{p.get('categoria_nome') or 'Senza Categoria'}**\n"
                f"- **Prezzo di Listino**: **€ {parse_price_value(p.get('prezzo')):.2f}**"
            )

    for cat in snapshot["categorie_nomi"]:
        if cat.lower() in q_low:
            prods_c = [p for p in snapshot["prodotti"] if (p.get("categoria_nome") or "").lower() == cat.lower()]
            lines_c = "\n".join([
                f"- `{p.get('codice') or 'S/C'}` **{p['nome']}** — **€ {parse_price_value(p.get('prezzo')):.2f}**"
                for p in prods_c[:20]
            ]) or "- Nessun prodotto in questa categoria."
            return f"🏷️ **Categoria {cat}** (**{len(prods_c)} prodotti**):\n{lines_c}"

    if any(k in q_low for k in ["elenco clienti", "lista clienti", "quali clienti", "tutti i clienti"]):
        c_lines = "\n".join([
            f"- **{c['nome']}** ({c.get('zona') or 'Zona N/D'}) — Fatturato: **€ {float(c.get('fatturato_totale') or 0):,.2f}**"
            for c in snapshot["clienti"][:25]
        ])
        return f"👥 **Elenco Clienti in Anagrafica ({len(snapshot['clienti'])})**:\n{c_lines}"

    # 7. Panoramica generale del sito
    return (
        f"📋 **Stato Attuale del tuo Gestionale HoReCa**:\n"
        f"- 👥 **Clienti in anagrafica**: **{len(snapshot['clienti'])}**\n"
        f"- 📦 **Prodotti a catalogo**: **{len(snapshot['prodotti'])}** (di cui **{len(snapshot['prodotti_senza_categoria'])}** senza categoria)\n"
        f"- 🏷️ **Categorie**: **{len(snapshot['categorie'])}** ({', '.join(snapshot['categorie_nomi'])})\n"
        f"- ⚖️ **Preventivi Comparatore salvati**: **{len(snapshot['comparazioni'])}**\n\n"
        "Scrivimi pure qualsiasi cosa vuoi **sapere** (es. *\"Quanto abbiamo fatturato?\"*, *\"Chi lavora il Polpo?\"*, *\"Qual è il giro del Martedì?\"*) "
        "oppure qualsiasi cosa vuoi **farmi sistemare in automatico** (es. *\"Pianifica una visita per Blu Mare domani alle 15\"*, *\"Sposta Leonardo al giro di Giovedì\"*, *\"Aumenta del 5% i prezzi di Carne Fresca\"*, *\"Crea un preventivo nel comparatore per Blu Mare\"*)!"
    )


# ==============================================================================
# DEFINIZIONE TOOLS OPENAI GPT-4o (COPERTURA TOTALE DEL SITO)
# ==============================================================================
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "prepare_catalog_import",
            "description": "Carica o aggiorna prodotti nel catalogo aziendale e assegna loro una categoria.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spiegazione": {"type": "string"},
                    "prodotti": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "codice": {"type": "string"},
                                "nome": {"type": "string"},
                                "prezzo": {"type": "number"},
                                "um": {"type": "string"},
                                "categoria": {"type": "string"}
                            },
                            "required": ["nome", "categoria"]
                        }
                    }
                },
                "required": ["spiegazione", "prodotti"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_auto_categorize",
            "description": "Auto-categorizza i prodotti attualmente senza categoria nel database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spiegazione": {"type": "string"},
                    "assegnazioni": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer"},
                                "codice": {"type": "string"},
                                "nome": {"type": "string"},
                                "categoria": {"type": "string"}
                            },
                            "required": ["id", "nome", "categoria"]
                        }
                    }
                },
                "required": ["spiegazione"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_client_products_assignment",
            "description": "Inserisce o aggiorna prodotti nel listino di uno specifico cliente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spiegazione": {"type": "string"},
                    "cliente_nome": {"type": "string"},
                    "categoria_da_copiare": {"type": "string"},
                    "prodotti": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "codice": {"type": "string"},
                                "nome": {"type": "string"},
                                "prezzo": {"type": "number"},
                                "prezzo_offerta": {"type": "number"},
                                "um": {"type": "string"},
                                "categoria": {"type": "string"},
                                "potenziale": {"type": "boolean"}
                            },
                            "required": ["nome"]
                        }
                    }
                },
                "required": ["spiegazione"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_flyer_creation",
            "description": "Crea rapidamente un volantino promozionale (Volantino Beta) con una lista di prodotti o da una categoria/cliente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spiegazione": {"type": "string"},
                    "titolo_volantino": {"type": "string"},
                    "tema": {"type": "string", "enum": ["promo_mensile", "carne", "pesce", "volantino"]},
                    "cols": {"type": "integer"},
                    "rows": {"type": "integer"},
                    "categoria_filtro": {"type": "string"},
                    "cliente_filtro": {"type": "string"},
                    "prodotti": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "codice": {"type": "string"},
                                "nome": {"type": "string"},
                                "prezzo": {"type": "number"},
                                "um": {"type": "string"},
                                "categoria": {"type": "string"}
                            },
                            "required": ["nome"]
                        }
                    }
                },
                "required": ["spiegazione", "titolo_volantino"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_clients_for_product",
            "description": "Cerca quali clienti lavorano un singolo prodotto specifico e quali clienti lavorano prodotti simili.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spiegazione": {"type": "string"},
                    "prodotto_cercato": {"type": "string"}
                },
                "required": ["prodotto_cercato"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_client",
            "description": "Crea un nuovo cliente, oppure modifica/sistema i dati di un cliente esistente (nome, zona, telefono, email, giorno giro visita standard Lunedì-Sabato, ora visita, giorni consegna).",
            "parameters": {
                "type": "object",
                "properties": {
                    "azione": {"type": "string", "enum": ["crea", "aggiorna", "elimina"]},
                    "cliente_nome": {"type": "string"},
                    "nuovo_nome": {"type": "string"},
                    "zona": {"type": "string"},
                    "telefono": {"type": "string"},
                    "email": {"type": "string"},
                    "giorno_visita": {"type": "string", "description": "Es. Lunedì, Martedì, Mercoledì, Giovedì, Venerdì, Sabato o numero 1..6"},
                    "ora_visita": {"type": "string", "description": "Es. 10:30"},
                    "giorni_consegna": {"type": "string", "description": "Es. Martedì, Venerdì"}
                },
                "required": ["cliente_nome"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_visita",
            "description": "Pianifica, aggiorna, segna come completata o elimina una visita commerciale per un cliente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "azione": {"type": "string", "enum": ["pianifica", "completa", "elimina"]},
                    "cliente_nome": {"type": "string"},
                    "data": {"type": "string", "description": "Es. 'oggi', 'domani', 'martedì', o 'YYYY-MM-DD'"},
                    "ora": {"type": "string", "description": "Es. '15:00'"},
                    "note": {"type": "string"},
                    "completata": {"type": "boolean"}
                },
                "required": ["cliente_nome"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_ordine_fatturato",
            "description": "Registra o aggiorna un ordine settimanale o il fatturato mensile di un cliente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cliente_nome": {"type": "string"},
                    "importo": {"type": "number"},
                    "tipo": {"type": "string", "enum": ["ordine_settimanale", "fatturato_mensile"]},
                    "mese": {"type": "integer"},
                    "anno": {"type": "integer"},
                    "note": {"type": "string"}
                },
                "required": ["cliente_nome", "importo"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_comparatore",
            "description": "Crea un preventivo comparativo nel Comparatore Offerte per un cliente con righe prodotto (supportando volume in kg o pz, prezzo attuale e nostro prezzo).",
            "parameters": {
                "type": "object",
                "properties": {
                    "cliente_nome": {"type": "string"},
                    "titolo": {"type": "string"},
                    "prodotti": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "nome": {"type": "string"},
                                "codice": {"type": "string"},
                                "volume": {"type": "number"},
                                "um": {"type": "string", "enum": ["kg", "pz"]},
                                "prezzo_attuale": {"type": "number"},
                                "prezzo_nostro": {"type": "number"}
                            },
                            "required": ["nome", "prezzo_nostro"]
                        }
                    }
                },
                "required": ["cliente_nome", "prodotti"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_catalog_and_prices",
            "description": "Sistema automaticamente prodotti a catalogo: modifica prezzi (fissi o in percentuale es. +5%, -10%), sposta di categoria, rinomina o elimina prodotti.",
            "parameters": {
                "type": "object",
                "properties": {
                    "azione": {"type": "string", "enum": ["aggiorna_prezzo", "sposta_categoria", "rinomina", "elimina"]},
                    "prodotto_filtro": {"type": "string", "description": "Nome o codice del prodotto (vuoto se si applica a tutta una categoria)."},
                    "categoria_filtro": {"type": "string", "description": "Nome categoria su cui applicare la modifica in blocco."},
                    "nuovo_prezzo": {"type": "number"},
                    "variazione_percentuale": {"type": "number", "description": "Es. 5 per +5%, -10 per -10%"},
                    "nuova_categoria": {"type": "string"},
                    "nuovo_nome": {"type": "string"}
                }
            }
        }
    }
]


def call_openai_agent(user_message: str, page_context: dict, snapshot: dict, uploaded_products: list, uploaded_raw_text: str):
    api_key, model = get_openai_config()
    if not api_key:
        return None, "missing_key"

    cat_list_str = ", ".join(snapshot["categorie_nomi"]) or "Nessuna categoria"
    clienti_summary = [
        {
            "id": c["id"],
            "nome": c["nome"],
            "zona": c.get("zona"),
            "tel": c.get("telefono"),
            "fatturato": c.get("fatturato_totale"),
            "giro": GIORNI_SETTIMANA.get(int(c["giorno_visita_standard"]), "") if str(c.get("giorno_visita_standard") or "").isdigit() else "",
            "ora": c.get("ora_visita_standard")
        }
        for c in snapshot["clienti"][:80]
    ]
    catalogo_sample = [
        {"id": p["id"], "codice": p["codice"], "nome": p["nome"], "prezzo": p.get("prezzo"), "categoria": p.get("categoria_nome")}
        for p in snapshot["prodotti"][:140]
    ]

    system_prompt = f"""Sei il Super-Agente Operativo AI con pieno controllo sul Gestionale HoReCa di Leonardo.
Puoi rispondere a QUALSIASI domanda sui dati del gestionale e puoi eseguire/sistemare in automatico QUALSIASI operazione sul sito usando i tuoi tool:
- Caricare e auto-categorizzare prodotti (`prepare_catalog_import`, `prepare_auto_categorize`)
- Modificare prezzi (% o fissi), categorie o nomi nel catalogo (`manage_catalog_and_prices`)
- Inserire prodotti nel listino di un cliente (`prepare_client_products_assignment`)
- Cercare quali clienti lavorano un prodotto o prodotti simili (`search_clients_for_product`)
- Creare/modificare clienti, zone, telefoni, giri visita Lunedì-Sabato e consegne (`manage_client`)
- Pianificare, spostare o completare visite nel calendario (`manage_visita`)
- Registrare ordini settimanali o fatturati mensili (`manage_ordine_fatturato`)
- Creare preventivi nel Comparatore Offerte con volumi in kg o pz (`manage_comparatore`)
- Creare volantini promozionali (`prepare_flyer_creation`)

DATA ODIERNA: {snapshot['oggi']} (Settimana #{snapshot['settimana_corrente']})
PAGINA ATTUALE DELL'UTENTE: {page_context.get('path', '/')} (Cliente attivo: {page_context.get('cliente_id') or 'Nessuno'})
CATEGORIE: {cat_list_str}
CLIENTI ({len(snapshot['clienti'])}): {json.dumps(clienti_summary, ensure_ascii=False)}
VISITE RECENTI/PROGRAMMATE: {json.dumps(snapshot['visite'][:20], ensure_ascii=False)}
ORDINI SETTIMANA CORRENTE: {json.dumps(snapshot['ordini_settimana'], ensure_ascii=False)}
COMPARAZIONI SALVATE: {json.dumps(snapshot['comparazioni'][:10], ensure_ascii=False)}
PRODOTTI SENZA CATEGORIA ({len(snapshot['prodotti_senza_categoria'])}): {json.dumps([{'id': p['id'], 'codice': p['codice'], 'nome': p['nome']} for p in snapshot['prodotti_senza_categoria'][:50]], ensure_ascii=False)}
PRODOTTI CATALOGO ({len(snapshot['prodotti'])}): {json.dumps(catalogo_sample, ensure_ascii=False)}
"""

    if uploaded_products or uploaded_raw_text:
        system_prompt += f"""
FILE ALLEGATO DALL'UTENTE:
- Prodotti estratti: {json.dumps(uploaded_products[:80], ensure_ascii=False)}
- Testo grezzo:
{uploaded_raw_text[:3000]}
"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message or "Procedi con il file allegato."}
        ],
        "tools": OPENAI_TOOLS,
        "tool_choice": "auto",
        "temperature": 0.2
    }

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=35
        )
        if resp.status_code != 200:
            err_body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
            return None, f"Errore OpenAI ({resp.status_code}): {err_body}"
        data = resp.json()
        choice = data["choices"][0]["message"]
        return choice, None
    except Exception as e:
        return None, f"Errore di connessione a OpenAI: {str(e)}"


# ==============================================================================
# COSTRUZIONE ED ESECUZIONE AUTOMATICA AZIONI
# ==============================================================================
def execute_batch_action_internal(action_dict: dict) -> dict:
    """Esegue un'azione batch (catalog_import, auto_categorize, client_assignment, create_flyer) direttamente a DB."""
    action_type = action_dict.get("type")
    items = action_dict.get("items") or []

    if action_type == "catalog_import":
        created_count = 0
        updated_count = 0
        with _GET_DB() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, nome FROM categorie")
            cat_map = {r["nome"].strip().upper(): r["id"] for r in cur.fetchall()}

            for item in items:
                if item.get("excluded"):
                    continue
                cod = str(item.get("codice") or "").strip()
                nom = str(item.get("nome") or "").strip()
                prz = parse_price_value(item.get("prezzo", 0))
                cat_name = str(item.get("categoria") or "").strip()
                if not nom or not cod:
                    continue

                cat_id = None
                if cat_name:
                    cat_key = cat_name.upper()
                    if cat_key in cat_map:
                        cat_id = cat_map[cat_key]
                    else:
                        cur.execute("INSERT INTO categorie (nome) VALUES (%s) RETURNING id", (cat_name,))
                        row_c = cur.fetchone()
                        cat_id = row_c["id"] if row_c else None
                        if cat_id:
                            cat_map[cat_key] = cat_id

                cur.execute("SELECT id FROM prodotti WHERE codice = %s", (cod,))
                existing = cur.fetchone()
                if existing:
                    cur.execute("""
                        UPDATE prodotti
                        SET nome = %s,
                            categoria_id = COALESCE(%s, categoria_id),
                            prezzo = CASE WHEN %s > 0 THEN %s ELSE prezzo END,
                            eliminato = FALSE
                        WHERE id = %s
                    """, (nom, cat_id, prz, prz, existing["id"]))
                    updated_count += 1
                else:
                    cur.execute("""
                        INSERT INTO prodotti (codice, nome, categoria_id, prezzo, eliminato)
                        VALUES (%s, %s, %s, %s, FALSE)
                    """, (cod, nom, cat_id, prz if prz > 0 else None))
                    created_count += 1

            conn.commit()

        return {
            "ok": True,
            "message": f"✅ Fatto! Creati **{created_count}** nuovi prodotti e aggiornati **{updated_count}** prodotti nel catalogo aziendale.",
            "redirect_url": url_for("prodotti"),
            "redirect_label": "📦 Vai al Catalogo Prodotti"
        }

    elif action_type == "auto_categorize":
        updated_count = 0
        with _GET_DB() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, nome FROM categorie")
            cat_map = {r["nome"].strip().upper(): r["id"] for r in cur.fetchall()}

            for item in items:
                if item.get("excluded"):
                    continue
                pid = item.get("id")
                cat_name = str(item.get("categoria") or "").strip()
                if not pid or not cat_name:
                    continue

                cat_key = cat_name.upper()
                if cat_key in cat_map:
                    cat_id = cat_map[cat_key]
                else:
                    cur.execute("INSERT INTO categorie (nome) VALUES (%s) RETURNING id", (cat_name,))
                    row_c = cur.fetchone()
                    cat_id = row_c["id"] if row_c else None
                    if cat_id:
                        cat_map[cat_key] = cat_id

                if cat_id:
                    cur.execute("UPDATE prodotti SET categoria_id = %s WHERE id = %s", (cat_id, int(pid)))
                    updated_count += 1

            conn.commit()

        return {
            "ok": True,
            "message": f"✅ Ho categorizzato automaticamente **{updated_count}** prodotti!",
            "redirect_url": url_for("prodotti"),
            "redirect_label": "🏷️ Vedi Prodotti Categorizzati"
        }

    elif action_type == "client_assignment":
        cliente_id = action_dict.get("cliente_id")
        if not cliente_id:
            return {"ok": False, "error": "Seleziona un cliente valido."}
        cliente_id = int(cliente_id)

        assigned_count = 0
        with _GET_DB() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, nome FROM clienti WHERE id = %s", (cliente_id,))
            cli_row = cur.fetchone()
            if not cli_row:
                return {"ok": False, "error": "Cliente non trovato."}
            cliente_nome = cli_row["nome"]

            cur.execute("SELECT id, nome FROM categorie")
            cat_map = {r["nome"].strip().upper(): r["id"] for r in cur.fetchall()}

            for item in items:
                if item.get("excluded"):
                    continue
                cod = str(item.get("codice") or "").strip()
                nom = str(item.get("nome") or "").strip()
                prz = parse_price_value(item.get("prezzo", 0))
                prz_off = parse_price_value(item.get("prezzo_offerta", 0)) if item.get("prezzo_offerta") else None
                potenziale = bool(item.get("potenziale", False))
                cat_name = str(item.get("categoria") or "").strip()

                if not nom:
                    continue

                cat_id = None
                if cat_name:
                    cat_key = cat_name.upper()
                    if cat_key in cat_map:
                        cat_id = cat_map[cat_key]
                    else:
                        cur.execute("INSERT INTO categorie (nome) VALUES (%s) RETURNING id", (cat_name,))
                        row_c = cur.fetchone()
                        cat_id = row_c["id"] if row_c else None
                        if cat_id:
                            cat_map[cat_key] = cat_id

                pid = item.get("id")
                if not pid and cod:
                    cur.execute("SELECT id FROM prodotti WHERE codice = %s", (cod,))
                    r_p = cur.fetchone()
                    if r_p:
                        pid = r_p["id"]
                if not pid:
                    cur.execute("SELECT id FROM prodotti WHERE UPPER(nome) = UPPER(%s)", (nom,))
                    r_p = cur.fetchone()
                    if r_p:
                        pid = r_p["id"]

                if pid:
                    cur.execute("""
                        UPDATE prodotti
                        SET categoria_id = COALESCE(%s, categoria_id),
                            eliminato = FALSE
                        WHERE id = %s
                    """, (cat_id, int(pid)))
                else:
                    if not cod:
                        cod = f"PRD{abs(hash(nom)) % 9000 + 1000}"
                    cur.execute("""
                        INSERT INTO prodotti (codice, nome, categoria_id, prezzo, eliminato)
                        VALUES (%s, %s, %s, %s, FALSE) RETURNING id
                    """, (cod, nom, cat_id, prz if prz > 0 else None))
                    pid = cur.fetchone()["id"]

                cur.execute("""
                    SELECT cliente_id FROM clienti_prodotti
                    WHERE cliente_id = %s AND prodotto_id = %s
                """, (cliente_id, int(pid)))
                if cur.fetchone():
                    cur.execute("""
                        UPDATE clienti_prodotti
                        SET prezzo_attuale = %s,
                            prezzo_offerta = %s,
                            potenziale = %s,
                            lavorato = TRUE,
                            data_operazione = CURRENT_TIMESTAMP
                        WHERE cliente_id = %s AND prodotto_id = %s
                    """, (prz, prz_off, potenziale, cliente_id, int(pid)))
                else:
                    cur.execute("""
                        INSERT INTO clienti_prodotti (cliente_id, prodotto_id, prezzo_attuale, prezzo_offerta, potenziale, lavorato, data_operazione)
                        VALUES (%s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
                    """, (cliente_id, int(pid), prz, prz_off, potenziale))
                assigned_count += 1

            conn.commit()

        return {
            "ok": True,
            "message": f"✅ Assegnati **{assigned_count}** prodotti al listino del cliente **{cliente_nome}**!",
            "redirect_url": f"/clienti/{cliente_id}",
            "redirect_label": f"👤 Apri Scheda di {cliente_nome}"
        }

    elif action_type == "create_flyer":
        active_items = [it for it in items if not it.get("excluded")]
        if not active_items:
            return {"ok": False, "error": "Seleziona almeno un prodotto per il volantino."}

        titolo = (action_dict.get("titolo_volantino") or f"Volantino AI - {datetime.now().strftime('%d/%m/%Y %H:%M')}").strip()
        tipo = action_dict.get("tema") or "promo_mensile"
        cols = max(1, min(6, int(action_dict.get("cols") or 3)))
        rows = max(1, min(6, int(action_dict.get("rows") or 3)))
        per_page = cols * rows

        preset = _GET_PRESET_FN() if _GET_PRESET_FN else {}
        cfg = _GET_VOL_CFG_FN() if _GET_VOL_CFG_FN else {}
        default_logo = cfg.get("default_header_logo", "")
        cell_styles = preset.get("cellStyles", {}) if isinstance(preset.get("cellStyles"), dict) else {}

        doc_pages = []
        for i in range(0, len(active_items), per_page):
            chunk = active_items[i:i + per_page]
            bg_url = preset.get("bgImg", "") if tipo == "promo_mensile" else ""
            header_img = "" if tipo == "promo_mensile" else default_logo
            header_h = "0" if tipo == "promo_mensile" else ("90" if header_img else "70")

            page_dict = {
                "cols": cols,
                "rows": rows,
                "gap": int(preset.get("gap") or 12),
                "larghezza": str(preset.get("larghezza") or "800"),
                "altezza": str(preset.get("altezza") or "1100"),
                "cellWidth": str(preset.get("cellWidth") or "380"),
                "cellHeight": str(preset.get("cellHeight") or "500"),
                "padTop": str(preset.get("padTop") or "10"),
                "padBottom": str(preset.get("padBottom") or "10"),
                "padSides": str(preset.get("padSides") or "10"),
                "headerH": header_h,
                "headerImg": header_img,
                "footerH": "0",
                "headerFit": "contain",
                "headerZoom": "1",
                "bgImg": bg_url,
                "bgWidth": str(preset.get("bgWidth", "100")),
                "bgHeight": str(preset.get("bgHeight", "100")),
                "bgPosX": str(preset.get("bgPosX") or "0"),
                "bgPosY": str(preset.get("bgPosY") or "0"),
                "bgFit": str(preset.get("bgFit") or "originale"),
                "gridX": str(preset.get("gridX") or "40"),
                "gridY": str(preset.get("gridY") or "100"),
                "gridWidth": str(preset.get("gridWidth") or ""),
                "gridHeight": str(preset.get("gridHeight") or ""),
                "categoryTitle": "" if tipo == "promo_mensile" else tipo.upper(),
                "categoryBannerColor": "#0f172a",
                "cells": []
            }

            for c_idx in range(per_page):
                if c_idx < len(chunk):
                    p = chunk[c_idx]
                    prz_val = parse_price_value(p.get("prezzo", 0))
                    prz_str = f"{prz_val:.2f}".replace(".", ",") if prz_val > 0 else ""
                    um_val = str(p.get("um") or "PZ").strip().upper()
                    full_price = f"€ {prz_str} / {um_val}" if (prz_str and um_val) else (f"€ {prz_str}" if prz_str else "")
                    img_url = str(p.get("immagine") or "")

                    price_color = cell_styles.get("priceColor", "#e11d48")
                    if "pesce" in tipo:
                        price_color = "#0284c7"

                    cell_data = {
                        "codice": str(p.get("codice", "")),
                        "titolo": str(p.get("nome", "")),
                        "nome": str(p.get("nome", "")),
                        "descrizione": "",
                        "prezzo": full_price,
                        "oldPrice": "",
                        "priceStyle": str(cell_styles.get("priceStyle", "base")),
                        "priceSize": str(cell_styles.get("priceSize", "26")),
                        "priceColor": str(price_color),
                        "priceBg": str(cell_styles.get("priceBg", "#ffffff")),
                        "priceCurrency": "€",
                        "priceWeight": str(cell_styles.get("priceWeight", "800")),
                        "layout": str(cell_styles.get("layout", "modern-split")),
                        "textAlign": str(cell_styles.get("textAlign", "start")),
                        "fontFamily": str(cell_styles.get("fontFamily", "inherit")),
                        "fontColor": str(cell_styles.get("fontColor", "#0f172a")),
                        "titleSize": str(cell_styles.get("titleSize", "16")),
                        "titleWeight": str(cell_styles.get("titleWeight", "700")),
                        "titleSpacing": "0",
                        "titleHeight": "1.2",
                        "codeSize": str(cell_styles.get("codeSize", "9")),
                        "descSize": str(cell_styles.get("descSize", "10")),
                        "scadenza": "",
                        "scadenzaSize": "12",
                        "scadenzaY": "0",
                        "descItalic": "0",
                        "textUpper": "1",
                        "borderStyle": str(cell_styles.get("borderStyle", "solid")),
                        "borderColor": str(cell_styles.get("borderColor", "#cbd5e1")),
                        "radius": str(cell_styles.get("radius", "8")),
                        "bgColor": str(cell_styles.get("bgColor", "#ffffff")),
                        "bgTransparent": "0",
                        "shadow": "1",
                        "imageFilter": "none",
                        "imageZoom": "1.0",
                        "imagePosX": "50",
                        "imagePosY": "50",
                        "imageRadius": "6",
                        "imagePadding": "4",
                        "imageAspect": "contain",
                        "imgOriginal": img_url,
                        "imgNoBg": img_url,
                        "useNoBg": "1",
                        "showDesc": "0"
                    }
                else:
                    cell_data = {
                        "codice": "",
                        "nome": "",
                        "prezzo": "",
                        "imgOriginal": "",
                        "bgTransparent": "1"
                    }
                page_dict["cells"].append(cell_data)
            doc_pages.append(page_dict)

        nuovo_vol = _VOLANTINO_MODEL(
            nome=titolo,
            layout_json=json.dumps(doc_pages, ensure_ascii=False),
            tipo=tipo,
            aggiornato_il=datetime.utcnow()
        )
        _SA_DB.session.add(nuovo_vol)
        _SA_DB.session.commit()
        editor_url = url_for("beta_volantino_modifica", id=nuovo_vol.id)

        return {
            "ok": True,
            "message": f"🎨 Volantino **{titolo}** creato automaticamente ({len(doc_pages)} pagine, {len(active_items)} prodotti)!",
            "redirect_url": editor_url,
            "redirect_label": "🎨 Apri nell'Editor Volantino"
        }

    return {"ok": False, "error": f"Tipo azione non supportato: {action_type}"}


def build_action_from_intent(intent_name: str, args: dict, snapshot: dict, page_context: dict, uploaded_products: list, auto_execute: bool = False):
    page_client_id = page_context.get("cliente_id")

    # Nuove operazioni istantanee su Clienti, Visite, Ordini/Fatturato, Comparatore, Catalogo
    if intent_name in ("manage_client", "manage_visita", "manage_ordine_fatturato", "manage_comparatore", "manage_catalog_and_prices"):
        exec_res = execute_universal_site_operation(intent_name, args, snapshot)
        if exec_res.get("ok"):
            return {
                "reply": exec_res["message"],
                "auto_executed": exec_res,
                "pending_action": None
            }
        return {"reply": f"⚠️ {exec_res.get('error', 'Impossibile completare l\'operazione.')}", "pending_action": None}

    if intent_name == "prepare_catalog_import":
        raw_items = args.get("prodotti") or uploaded_products or []
        enriched = enrich_products_with_db_status(raw_items, snapshot)
        pending = {
            "type": "catalog_import",
            "title": f"Caricamento Catalogo Aziendale ({len(enriched)} prodotti)",
            "categories": snapshot["categorie_nomi"],
            "items": enriched
        }
        if auto_execute and enriched and len(enriched) <= 25:
            exec_res = execute_batch_action_internal(pending)
            if exec_res.get("ok"):
                return {"reply": exec_res["message"], "auto_executed": exec_res, "pending_action": None}
        return {
            "reply": args.get("spiegazione") or f"Ho preparato l'anteprima di **{len(enriched)} prodotti** con auto-categorizzazione. Verifica i dati qui sotto e clicca **Conferma e Salva**.",
            "pending_action": pending
        }

    elif intent_name == "prepare_auto_categorize":
        raw_assign = args.get("assegnazioni") or []
        if not raw_assign:
            for p in snapshot["prodotti_senza_categoria"]:
                raw_assign.append({
                    "id": p["id"],
                    "codice": p.get("codice") or "",
                    "nome": p["nome"],
                    "categoria": guess_category_for_product(p["nome"], snapshot["categorie_nomi"])
                })
        if not raw_assign:
            return {"reply": "Ottima notizia: tutti i prodotti nel catalogo hanno già una categoria assegnata!", "pending_action": None}
        pending = {
            "type": "auto_categorize",
            "title": f"Auto-Categorizzazione ({len(raw_assign)} prodotti)",
            "categories": snapshot["categorie_nomi"],
            "items": raw_assign
        }
        if auto_execute:
            exec_res = execute_batch_action_internal(pending)
            if exec_res.get("ok"):
                return {"reply": exec_res["message"], "auto_executed": exec_res, "pending_action": None}
        return {
            "reply": args.get("spiegazione") or f"Ho analizzato i **{len(raw_assign)} prodotti senza categoria** e ho assegnato a ciascuno la categoria più adatta.",
            "pending_action": pending
        }

    elif intent_name == "prepare_client_products_assignment":
        client_query = args.get("cliente_nome") or ""
        target_client = find_best_client(client_query, snapshot["clienti"], page_client_id)
        raw_items = args.get("prodotti") or uploaded_products or []

        cat_copy = (args.get("categoria_da_copiare") or "").strip().lower()
        if not raw_items and cat_copy:
            for p in snapshot["prodotti"]:
                if (p.get("categoria_nome") or "").lower() == cat_copy or cat_copy in (p.get("categoria_nome") or "").lower():
                    raw_items.append({
                        "id": p["id"],
                        "codice": p.get("codice") or "",
                        "nome": p["nome"],
                        "prezzo": parse_price_value(p.get("prezzo", 0)),
                        "categoria": p.get("categoria_nome") or "GENERALE"
                    })

        enriched = enrich_products_with_db_status(raw_items, snapshot, target_client["id"] if target_client else None)
        client_name_label = target_client["nome"] if target_client else "Seleziona un cliente"
        pending = {
            "type": "client_assignment",
            "title": f"Inserimento Prodotti per Cliente: {client_name_label}",
            "cliente_id": target_client["id"] if target_client else None,
            "cliente_nome": client_name_label,
            "clienti": snapshot["clienti"],
            "categories": snapshot["categorie_nomi"],
            "items": enriched
        }
        if auto_execute and target_client and enriched and len(enriched) <= 25:
            exec_res = execute_batch_action_internal(pending)
            if exec_res.get("ok"):
                return {"reply": exec_res["message"], "auto_executed": exec_res, "pending_action": None}
        return {
            "reply": args.get("spiegazione") or f"Ho preparato l'assegnazione di **{len(enriched)} prodotti** per il cliente **{client_name_label}**.",
            "pending_action": pending
        }

    elif intent_name == "prepare_flyer_creation":
        raw_items = args.get("prodotti") or uploaded_products or []
        cat_filter = (args.get("categoria_filtro") or "").strip().lower()
        cli_filter = (args.get("cliente_filtro") or "").strip()

        if not raw_items and cat_filter:
            for p in snapshot["prodotti"]:
                c_name = (p.get("categoria_nome") or "").lower()
                if cat_filter in c_name or c_name in cat_filter:
                    raw_items.append({
                        "id": p["id"],
                        "codice": p.get("codice") or "",
                        "nome": p["nome"],
                        "prezzo": parse_price_value(p.get("prezzo", 0)),
                        "immagine": p.get("immagine") or "",
                        "categoria": p.get("categoria_nome") or ""
                    })

        if not raw_items and cli_filter:
            target_c = find_best_client(cli_filter, snapshot["clienti"], page_client_id)
            if target_c:
                with _GET_DB() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT p.id, p.codice, p.nome, p.immagine, c.nome AS categoria_nome,
                               COALESCE(cp.prezzo_offerta, cp.prezzo_attuale, p.prezzo) AS prezzo_finale
                        FROM clienti_prodotti cp
                        JOIN prodotti p ON cp.prodotto_id = p.id
                        LEFT JOIN categorie c ON p.categoria_id = c.id
                        WHERE cp.cliente_id = %s AND cp.lavorato = TRUE AND COALESCE(p.eliminato, FALSE) = FALSE
                    """, (target_c["id"],))
                    for r in cur.fetchall():
                        raw_items.append({
                            "id": r["id"],
                            "codice": r.get("codice") or "",
                            "nome": r["nome"],
                            "prezzo": parse_price_value(r.get("prezzo_finale", 0)),
                            "immagine": r.get("immagine") or "",
                            "categoria": r.get("categoria_nome") or ""
                        })

        if not raw_items:
            for p in snapshot["prodotti"][:9]:
                raw_items.append({
                    "id": p["id"],
                    "codice": p.get("codice") or "",
                    "nome": p["nome"],
                    "prezzo": parse_price_value(p.get("prezzo", 0)),
                    "immagine": p.get("immagine") or "",
                    "categoria": p.get("categoria_nome") or ""
                })

        enriched = enrich_products_with_db_status(raw_items, snapshot)
        titolo = args.get("titolo_volantino") or f"Volantino AI - {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        tema = args.get("tema") or "promo_mensile"
        cols = int(args.get("cols") or 3)
        rows = int(args.get("rows") or 3)
        pending = {
            "type": "create_flyer",
            "title": f"Creazione Volantino: {titolo}",
            "titolo_volantino": titolo,
            "tema": tema,
            "cols": cols,
            "rows": rows,
            "items": enriched
        }
        if auto_execute and enriched:
            exec_res = execute_batch_action_internal(pending)
            if exec_res.get("ok"):
                return {"reply": exec_res["message"], "auto_executed": exec_res, "pending_action": None}
        return {
            "reply": args.get("spiegazione") or f"Ho preparato il volantino **{titolo}** ({cols}x{rows}) con **{len(enriched)} prodotti**.",
            "pending_action": pending
        }

    elif intent_name == "search_clients_for_product":
        q = args.get("prodotto_cercato") or ""
        search_res = search_clients_by_product_or_similar(q, snapshot)
        n_exact = len(search_res["exact_products"])
        n_cli_dir = search_res["totale_clienti_diretti"]
        n_cli_sim = search_res["totale_clienti_simili"]
        reply_msg = args.get("spiegazione") or (
            f"🔍 Risultati ricerca per **\"{search_res['query']}\"**:\n"
            f"- **{n_exact} prodotti corrispondenti** trovati (**{n_cli_dir} clienti** li lavorano direttamente)\n"
            f"- **{len(search_res['similar_products'])} prodotti simili/affini** (**{n_cli_sim} altri clienti** lavorano prodotti simili)"
        )
        return {
            "reply": reply_msg,
            "pending_action": None,
            "search_results": search_res
        }

    return None


def local_smart_router(user_message: str, page_context: dict, snapshot: dict, uploaded_products: list, auto_execute: bool = False):
    """Router locale intelligente: capisce qualsiasi richiesta operativa o informativa anche senza API key."""
    msg = (user_message or "").strip()
    msg_low = msg.lower()

    matched_client = None
    for cli in snapshot["clienti"]:
        if cli["nome"].lower() in msg_low:
            matched_client = cli["nome"]
            break

    # 0. Ricerca quali clienti lavorano un singolo prodotto o prodotti simili
    if any(k in msg_low for k in [
        "chi lavora", "chi compra", "chi acquista", "chi ha", "quale cliente lavora",
        "quali clienti lavorano", "quale dei miei clienti", "quali dei miei clienti",
        "cerca chi", "clienti che lavorano", "prodotto simile", "prodotti simili"
    ]):
        return build_action_from_intent("search_clients_for_product", {"prodotto_cercato": msg}, snapshot, page_context, uploaded_products, auto_execute)

    # 1. Pianificazione / gestione VISITA ("pianifica visita", "aggiungi visita", "visita per ... domani alle 15")
    if any(k in msg_low for k in ["pianifica visita", "aggiungi visita", "fissa visita", "programma visita", "nuova visita", "segna visita"]) or (
        "visita" in msg_low and matched_client and any(k in msg_low for k in ["oggi", "domani", "alle", "luned", "marted", "mercoled", "gioved", "venerd", "sabat"])
    ):
        m_ora = re.search(r'\b(\d{1,2}[:\.]\d{2})\b', msg_low)
        ora_val = m_ora.group(1).replace(".", ":") if m_ora else "10:00"
        return build_action_from_intent(
            "manage_visita",
            {"azione": "pianifica", "cliente_nome": matched_client or "", "data": msg_low, "ora": ora_val},
            snapshot, page_context, uploaded_products, auto_execute
        )

    # 2. Spostamento GIRO VISITA o modifica CLIENTE ("sposta ... al giro di martedì", "crea cliente ...", "cambia zona ...")
    if any(k in msg_low for k in ["giro visita", "giro del", "giro di", "nel giro", "sposta cliente", "crea cliente", "nuovo cliente", "cambia zona", "imposta zona"]):
        giorno_found = None
        for g_k in GIORNI_DA_NOME:
            if g_k in msg_low and len(g_k) >= 3:
                giorno_found = g_k
                break
        m_ora = re.search(r'\b(\d{1,2}[:\.]\d{2})\b', msg_low)
        ora_val = m_ora.group(1).replace(".", ":") if m_ora else None
        m_zona = re.search(r'\bzona\s+([A-Za-zÀ-ÿ\s]{2,20})', msg, re.IGNORECASE)
        zona_val = m_zona.group(1).strip() if m_zona else None
        azione_cli = "crea" if ("crea cliente" in msg_low or "nuovo cliente" in msg_low) else "aggiorna"
        nome_target = matched_client
        if not nome_target and azione_cli == "crea":
            m_nc = re.search(r'(?:crea\s+cliente|nuovo\s+cliente)\s+([A-Za-z0-9À-ÿ\s\'\.\-&]{2,35})', msg, re.IGNORECASE)
            if m_nc:
                nome_target = m_nc.group(1).strip()
        return build_action_from_intent(
            "manage_client",
            {"azione": azione_cli, "cliente_nome": nome_target or "", "giorno_visita": giorno_found, "ora_visita": ora_val, "zona": zona_val},
            snapshot, page_context, uploaded_products, auto_execute
        )

    # 3. Registrazione ORDINE SETTIMANALE o FATTURATO ("registra ordine di 450€ per ...", "segna fatturato ...")
    if any(k in msg_low for k in ["registra ordine", "segna ordine", "nuovo ordine", "registra fatturato", "segna fatturato", "imposta fatturato"]) and matched_client:
        imp = parse_price_value(msg)
        tipo_r = "fatturato_mensile" if "fatturato" in msg_low else "ordine_settimanale"
        return build_action_from_intent(
            "manage_ordine_fatturato",
            {"cliente_nome": matched_client, "importo": imp, "tipo": tipo_r},
            snapshot, page_context, uploaded_products, auto_execute
        )

    # 4. Creazione Preventivo nel COMPARATORE OFFERTE ("crea comparazione", "nel comparatore", "preventivo comparatore")
    if any(k in msg_low for k in ["comparatore", "comparazione", "preventivo comparativo"]):
        extracted = uploaded_products or extract_products_from_free_text(msg, snapshot["categorie_nomi"])
        comp_rows = [
            {
                "nome": p["nome"],
                "codice": p.get("codice") or "",
                "volume": 20,
                "um": "pz" if (p.get("um") or "").lower() == "pz" else "kg",
                "prezzo_attuale": round(p["prezzo"] * 1.15, 2) if p.get("prezzo") else 15.0,
                "prezzo_nostro": p.get("prezzo") or 13.0
            }
            for p in extracted
        ]
        if comp_rows:
            return build_action_from_intent(
                "manage_comparatore",
                {"cliente_nome": matched_client or "Cliente", "prodotti": comp_rows},
                snapshot, page_context, uploaded_products, auto_execute
            )

    # 5. Modifica prezzi in percentuale o spostamento categoria in blocco ("aumenta del 5%", "sconta del 10%")
    m_perc = re.search(r'(aumenta|incrementa|alza|sconta|riduci|abbassa).*?(\d+[\.,]?\d*)\s*%', msg_low)
    if m_perc:
        verb = m_perc.group(1)
        val_p = float(m_perc.group(2).replace(",", "."))
        if verb in ("sconta", "riduci", "abbassa"):
            val_p = -val_p
        cat_f = ""
        for c in snapshot["categorie_nomi"]:
            if c.lower() in msg_low:
                cat_f = c
                break
        return build_action_from_intent(
            "manage_catalog_and_prices",
            {"azione": "aggiorna_prezzo", "categoria_filtro": cat_f, "variazione_percentuale": val_p},
            snapshot, page_context, uploaded_products, auto_execute
        )

    # 5b. Modifica prezzo fisso di un singolo prodotto ("cambia prezzo di ... a 14,50", "imposta prezzo ... a ...")
    if any(k in msg_low for k in ["cambia prezzo", "imposta prezzo", "porta il prezzo", "modifica prezzo", "metti il prezzo"]):
        prz_new = parse_price_value(msg)
        prod_match = ""
        for p in snapshot["prodotti"]:
            if p["nome"].lower() in msg_low or (p.get("codice") and str(p["codice"]).lower() in msg_low):
                prod_match = p["nome"]
                break
        if prod_match and prz_new > 0:
            return build_action_from_intent(
                "manage_catalog_and_prices",
                {"azione": "aggiorna_prezzo", "prodotto_filtro": prod_match, "nuovo_prezzo": prz_new},
                snapshot, page_context, uploaded_products, auto_execute
            )

    # 6. Auto-categorizzazione prodotti senza categoria
    if any(k in msg_low for k in ["senza categoria", "categorizza", "auto-categorizza", "autocategorizza", "assegna categorie"]):
        return build_action_from_intent("prepare_auto_categorize", {}, snapshot, page_context, uploaded_products, auto_execute)

    # 7. Creazione volantino
    if any(k in msg_low for k in ["volantino", "flyer", "promo mensile", "locandina"]):
        tema = "promo_mensile"
        if "carne" in msg_low:
            tema = "carne"
        elif "pesce" in msg_low:
            tema = "pesce"

        cols, rows = 3, 3
        m_grid = re.search(r'(\d)\s*[xX]\s*(\d)', msg_low)
        if m_grid:
            cols, rows = int(m_grid.group(1)), int(m_grid.group(2))

        cat_filter = ""
        for c in snapshot["categorie_nomi"]:
            if c.lower() in msg_low:
                cat_filter = c
                break

        extracted = uploaded_products or extract_products_from_free_text(msg, snapshot["categorie_nomi"])
        titolo = f"Volantino {cat_filter.capitalize() if cat_filter else tema.replace('_', ' ').title()} - {datetime.now().strftime('%d/%m/%Y')}"
        return build_action_from_intent(
            "prepare_flyer_creation",
            {
                "titolo_volantino": titolo,
                "tema": tema,
                "cols": cols,
                "rows": rows,
                "categoria_filtro": cat_filter,
                "cliente_filtro": matched_client or "",
                "prodotti": extracted
            },
            snapshot, page_context, uploaded_products, auto_execute
        )

    # 8. Assegnazione prodotti a un cliente
    if matched_client and any(k in msg_low for k in ["assegna", "inserisci", "aggiungi", "listino", "prodott"]):
        extracted = uploaded_products or extract_products_from_free_text(msg, snapshot["categorie_nomi"])
        cat_copy = ""
        for c in snapshot["categorie_nomi"]:
            if c.lower() in msg_low:
                cat_copy = c
                break
        if extracted or cat_copy:
            return build_action_from_intent(
                "prepare_client_products_assignment",
                {"cliente_nome": matched_client, "categoria_da_copiare": cat_copy, "prodotti": extracted},
                snapshot, page_context, uploaded_products, auto_execute
            )

    # 9. Caricamento prodotti a catalogo (da file allegato o lista testo)
    extracted = uploaded_products or extract_products_from_free_text(msg, snapshot["categorie_nomi"])
    if extracted:
        return build_action_from_intent("prepare_catalog_import", {"prodotti": extracted}, snapshot, page_context, uploaded_products, auto_execute)

    # 10. Risposta universale a qualsiasi domanda sul sito / database
    return {
        "reply": answer_universal_site_question(msg, snapshot),
        "pending_action": None
    }


# ==============================================================================
# ROUTES API DELL'AGENTE AI
# ==============================================================================
@ai_agent_bp.route("/api/ai-agent/config", methods=["GET", "POST"])
def api_ai_agent_config():
    if not session.get("logged_in"):
        return jsonify({"ok": False, "error": "Non autorizzato"}), 401

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        api_key = data.get("api_key", "").strip()
        model = data.get("model", "gpt-4o").strip()
        save_openai_config(api_key, model)
        return jsonify({
            "ok": True,
            "has_key": bool(api_key),
            "masked_key": (api_key[:7] + "..." + api_key[-4:]) if len(api_key) > 12 else ("Configurata" if api_key else ""),
            "model": model
        })

    api_key, model = get_openai_config()
    snapshot = get_db_snapshot()
    return jsonify({
        "ok": True,
        "has_key": bool(api_key),
        "masked_key": (api_key[:7] + "..." + api_key[-4:]) if len(api_key) > 12 else ("Configurata" if api_key else ""),
        "model": model,
        "stats": {
            "totale_prodotti": len(snapshot["prodotti"]),
            "senza_categoria": len(snapshot["prodotti_senza_categoria"]),
            "totale_categorie": len(snapshot["categorie"]),
            "totale_clienti": len(snapshot["clienti"])
        }
    })


@ai_agent_bp.route("/api/ai-agent/chat", methods=["POST"])
def api_ai_agent_chat():
    if not session.get("logged_in"):
        return jsonify({"ok": False, "error": "Effettua il login per usare l'assistente AI."}), 401

    snapshot = get_db_snapshot()
    uploaded_products = []
    uploaded_raw_text = ""
    auto_execute = True

    if request.content_type and "multipart/form-data" in request.content_type:
        user_message = (request.form.get("message") or "").strip()
        auto_execute = str(request.form.get("auto_execute", "true")).lower() in ("true", "1", "yes")
        page_context_raw = request.form.get("page_context") or "{}"
        try:
            page_context = json.loads(page_context_raw)
        except Exception:
            page_context = {}

        file_obj = request.files.get("file")
        if file_obj and file_obj.filename:
            uploaded_products, uploaded_raw_text = parse_uploaded_file(file_obj, snapshot["categorie_nomi"])
    else:
        data = request.get_json(silent=True) or {}
        user_message = (data.get("message") or "").strip()
        page_context = data.get("page_context") or {}
        if "auto_execute" in data:
            auto_execute = bool(data.get("auto_execute"))

    api_key, _ = get_openai_config()
    if api_key:
        choice, err = call_openai_agent(user_message, page_context, snapshot, uploaded_products, uploaded_raw_text)
        if choice:
            tool_calls = choice.get("tool_calls") or []
            if tool_calls:
                tc = tool_calls[0]["function"]
                fn_name = tc.get("name")
                try:
                    fn_args = json.loads(tc.get("arguments") or "{}")
                except Exception:
                    fn_args = {}
                result = build_action_from_intent(fn_name, fn_args, snapshot, page_context, uploaded_products, auto_execute)
                if result:
                    return jsonify({"ok": True, **result})
            content = choice.get("content")
            if content:
                return jsonify({"ok": True, "reply": content, "pending_action": None})

    result = local_smart_router(user_message, page_context, snapshot, uploaded_products, auto_execute)
    return jsonify({"ok": True, **result})


@ai_agent_bp.route("/api/ai-agent/execute", methods=["POST"])
def api_ai_agent_execute():
    if not session.get("logged_in"):
        return jsonify({"ok": False, "error": "Non autorizzato"}), 401

    data = request.get_json(silent=True) or {}
    if not data.get("type"):
        return jsonify({"ok": False, "error": "Tipo di azione mancante."}), 400

    try:
        res = execute_batch_action_internal(data)
        return jsonify(res), (200 if res.get("ok") else 400)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"Errore durante l'esecuzione: {str(e)}"}), 500
