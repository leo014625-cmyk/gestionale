import os
import re
import csv
import io
import json
import zipfile
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
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

    # Aggiorna anche .env locale se presente e scrivibile
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
    """Suggerisce la categoria migliore (preferendo quelle già presenti a sistema)."""
    name_low = (product_name or "").lower()
    if not name_low:
        return existing_categories[0] if existing_categories else "OFFERTE"

    is_frozen = any(k in name_low for k in ["gelo", "surg", "iqf", "congelat"])

    # 1. Match diretto con il nome di una categoria esistente nel DB
    for cat in existing_categories:
        cat_clean = cat.strip().lower()
        if len(cat_clean) >= 3 and cat_clean in name_low:
            return cat

    # 2. Match su keyword HoReCa
    best_std_cat = None
    best_score = 0
    for std_cat, keywords in HORECA_CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if re.search(r'\b' + re.escape(kw), name_low))
        if score > best_score:
            best_score = score
            best_std_cat = std_cat

    if best_std_cat:
        # Cerca se nel DB dell'utente c'è già una categoria simile (gestendo Fresco vs Gelo)
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

        # Se è dispensa/alimentari/salumi e c'è "Alimentari" tra le categorie esistenti
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
    """Legge le righe di un file .xlsx anche senza librerie esterne (usando zipfile + xml)."""
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
    """Converte righe tabellari (CSV/XLSX) in dizionari prodotto."""
    if not rows:
        return []
    products = []
    header_map = {}

    for idx, row in enumerate(rows):
        cells = [str(c or "").strip() for c in row]
        if not any(cells):
            continue

        # Rileva eventuale riga di intestazione
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
            # Euristica su riga libera
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
    """Estrae prodotti da una lista testuale o messaggio in chat."""
    if not text:
        return []
    products = []
    lines = [l.strip() for l in re.split(r'[\n;]+', text) if l.strip()]

    um_list = ['KG', 'PZ', 'CT', 'BT', 'LT', 'CF', 'VAS', 'CONF', 'GR', 'SC', 'CART', 'L', 'ML', 'CL']
    um_regex = r'\b(' + '|'.join(um_list) + r')\b'

    for idx, raw_line in enumerate(lines):
        # Rimuovi solo veri bullet iniziali (-, *, •, oppure "1." / "2)" seguiti da spazio)
        line = re.sub(r'^(?:[\-\*\•]+|\d{1,2}[\.\)])\s*', '', raw_line).strip()
        if not line or len(line) < 3:
            continue

        # Ignora frasi puramente conversazionali se c'è una sola riga senza numeri/prodotti
        low = line.lower()
        for prefix in ["aggiungi questi prodotti:", "aggiungi prodotti:", "inserisci:", "carica:", "aggiungi ", "inserisci "]:
            if low.startswith(prefix):
                line = line[len(prefix):].strip()
                low = line.lower()

        # Cerca codice (es. "cod. 1045", "codice 1045", oppure codice iniziale 3-14 char con almeno una cifra)
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

        # Cerca prezzo (es. € 12,50 / 12.50€ / a 12,50 / 12,50)
        price = 0.0
        m_price = re.search(r'(?:€\s*(\d+[\.,]\d{1,2}|\d+))|(?:(\d+[\.,]\d{1,2}|\d+)\s*€)|(?:\ba\s+(\d+[\.,]\d{1,2})\b)|(?:\s(\d+[\.,]\d{2})(?:\s|$))', line, re.IGNORECASE)
        if m_price:
            p_str = next(g for g in m_price.groups() if g is not None)
            price = parse_price_value(p_str)
            line = (line[:m_price.start()] + " " + line[m_price.end():]).strip()

        # Cerca eventuale indicazione di categoria ("in categoria X" / "in Bevande")
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

        # Cerca UM
        um = "PZ"
        m_um = re.search(um_regex, line, re.IGNORECASE)
        if m_um:
            um = m_um.group(1).upper()

        # Pulisci il nome
        name = re.sub(r'\s+', ' ', line).strip(" -,:;/")
        if not name or len(name) < 2:
            continue

        # Se non sembra un prodotto (nessun codice, nessun prezzo e frase lunga conversazionale), salta
        if not code and price == 0.0 and len(lines) == 1 and any(w in name.lower() for w in ["vorrei", "puoi", "come", "aiutami", "crea un volantino", "categorizza"]):
            continue

        if not code:
            # Genera un codice univoco basato sulle iniziali + hash breve
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
    """Estrae prodotti da un file caricato (PDF, CSV, XLSX, TXT). Ritorna (prodotti, testo_grezzo)."""
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
# HELPER CONTESTO DATABASE
# ==============================================================================
def get_db_snapshot():
    """Carica categorie, clienti e statistiche rapide del catalogo per fornire contesto all'Agente."""
    with _GET_DB() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, nome FROM categorie ORDER BY nome")
        categorie = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT id, nome, zona FROM clienti ORDER BY nome")
        clienti = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT p.id, p.codice, p.nome, p.prezzo, p.immagine, p.categoria_id, c.nome AS categoria_nome
            FROM prodotti p
            LEFT JOIN categorie c ON p.categoria_id = c.id
            WHERE COALESCE(p.eliminato, FALSE) = FALSE
            ORDER BY p.nome
        """)
        prodotti = [dict(r) for r in cur.fetchall()]

    senza_cat = [p for p in prodotti if not p.get("categoria_id")]
    return {
        "categorie": categorie,
        "categorie_nomi": [c["nome"] for c in categorie],
        "clienti": clienti,
        "prodotti": prodotti,
        "prodotti_senza_categoria": senza_cat
    }


def enrich_products_with_db_status(items: list, snapshot: dict, cliente_id: int = None) -> list:
    """Arricchisce una lista di prodotti con lo stato nel DB (nuovo vs esistente, immagine, ecc.)."""
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
    """Trova il cliente migliore per ID di pagina o per nome."""
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
    """Pulisce una domanda in linguaggio naturale per isolare il nome/codice del prodotto cercato."""
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
    # Seconda passata se rimangono prefissi come "il prodotto "
    s = re.sub(r'^(?:il\s+prodotto|prodotto|quel\s+prodotto|il|lo|la|i|gli|le)\s+', '', s, flags=re.IGNORECASE).strip()
    return s.strip(' "\'')


def search_clients_by_product_or_similar(query_str: str, snapshot: dict) -> dict:
    """
    Cerca quali clienti lavorano un singolo prodotto (per nome o codice)
    e quali clienti lavorano prodotti simili (per parole chiave condivise o stessa categoria).
    """
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
            # Controlla se condivide almeno una keyword importante (radice >= 6 caratteri per singolare/plurale)
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

    # Includiamo anche prodotti affini della stessa famiglia/categoria (anche se non ancora categorizzati a DB)
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
        # Metti sempre in cima i prodotti che hanno clienti associati
        out.sort(key=lambda x: (-len(x["clienti"]), x["nome"]))
        return out

    exact_formatted = format_product_with_clients(exact_products)
    similar_formatted = format_product_with_clients(similar_products)
    similar_final = similar_formatted[:15]

    # Calcola statistiche rapide
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
# CHIAMATA OPENAI GPT-4o CON TOOL CALLING
# ==============================================================================
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "prepare_catalog_import",
            "description": "Prepara l'anteprima per caricare o aggiornare prodotti nel catalogo aziendale e assegnare loro una categoria.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spiegazione": {
                        "type": "string",
                        "description": "Messaggio amichevole in italiano che spiega cosa stai preparando in anteprima."
                    },
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
            "description": "Analizza i prodotti attualmente senza categoria nel database e prepara l'anteprima con la categoria consigliata per ciascuno.",
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
                "required": ["spiegazione", "assegnazioni"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_client_products_assignment",
            "description": "Prepara l'anteprima per inserire/assegnare prodotti al listino di uno specifico cliente (con prezzi ed eventuale creazione prodotto se non esiste).",
            "parameters": {
                "type": "object",
                "properties": {
                    "spiegazione": {"type": "string"},
                    "cliente_nome": {
                        "type": "string",
                        "description": "Nome del cliente a cui assegnare i prodotti (se menzionato dall'utente)."
                    },
                    "categoria_da_copiare": {
                        "type": "string",
                        "description": "Opzionale: se l'utente chiede di aggiungere tutti i prodotti di una categoria esistente al cliente."
                    },
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
            "description": "Prepara l'anteprima per creare rapidamente un nuovo volantino promozionale (Volantino Beta) con una lista di prodotti o da una categoria.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spiegazione": {"type": "string"},
                    "titolo_volantino": {"type": "string"},
                    "tema": {
                        "type": "string",
                        "enum": ["promo_mensile", "carne", "pesce", "volantino"],
                        "description": "Stile del volantino."
                    },
                    "cols": {"type": "integer", "description": "Numero colonne per pagina (default 3)."},
                    "rows": {"type": "integer", "description": "Numero righe per pagina (default 3)."},
                    "categoria_filtro": {
                        "type": "string",
                        "description": "Se l'utente vuole inserire tutti i prodotti di una specifica categoria del catalogo."
                    },
                    "cliente_filtro": {
                        "type": "string",
                        "description": "Se l'utente vuole creare un volantino con i prodotti lavorati/in offerta di un cliente specifico."
                    },
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
            "description": "Cerca quali clienti lavorano un singolo prodotto specifico (per nome o codice) e quali clienti lavorano prodotti simili o della stessa categoria.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spiegazione": {"type": "string"},
                    "prodotto_cercato": {
                        "type": "string",
                        "description": "Il nome o codice del prodotto da cercare (es. 'Salmone', 'Hamburger Black Angus', 'Polpo', '1045')."
                    }
                },
                "required": ["prodotto_cercato"]
            }
        }
    }
]


def call_openai_agent(user_message: str, page_context: dict, snapshot: dict, uploaded_products: list, uploaded_raw_text: str):
    api_key, model = get_openai_config()
    if not api_key:
        return None, "missing_key"

    cat_list_str = ", ".join(snapshot["categorie_nomi"]) or "Nessuna categoria (creane di nuove come CARNE, PESCE, BEVANDE, LATTICINI, DISPENSA)"
    clienti_str = ", ".join([f"{c['nome']} (ID:{c['id']})" for c in snapshot["clienti"][:80]]) or "Nessun cliente registrato"
    senza_cat_sample = [
        {"id": p["id"], "codice": p["codice"], "nome": p["nome"]}
        for p in snapshot["prodotti_senza_categoria"][:60]
    ]
    catalogo_sample = [
        {"id": p["id"], "codice": p["codice"], "nome": p["nome"], "prezzo": p.get("prezzo"), "categoria": p.get("categoria_nome")}
        for p in snapshot["prodotti"][:120]
    ]

    system_prompt = f"""Sei l'Agente Operativo AI integrato nel Gestionale HoReCa di Leonardo.
Il tuo compito è aiutare l'utente a:
1. Caricare prodotti aziendali a catalogo (da testo o da file PDF/Excel/CSV) e auto-categorizzarli.
2. Auto-categorizzare i prodotti già presenti che sono "Senza Categoria".
3. Inserire/assegnare prodotti cliente per cliente nel loro listino (`clienti_prodotti`).
4. Creare volantini promozionali rapidamente (`VolantinoBeta`).

REGOLE IMPORTANTI:
- Quando l'utente ti chiede di fare un'azione operativa (caricare prodotti, categorizzare, assegnare a un cliente, creare un volantino), USA SEMPRE uno dei tool a disposizione (`prepare_catalog_import`, `prepare_auto_categorize`, `prepare_client_products_assignment`, `prepare_flyer_creation`).
- Il sistema mostrerà automaticamente all'utente un'anteprima interattiva con il pulsante "Conferma e Salva" prima di scrivere nel database.
- Quando assegni una categoria, preferisci quelle già esistenti nel gestionale ({cat_list_str}) se pertinenti, altrimenti proponi una categoria HoReCa chiara in MAIUSCOLO (es. CARNE, PESCE E ITTICO, SALUMI E LATTICINI, ORTOFRUTTA, DISPENSA, DOLCI, BEVANDE).

CONTESTO ATTUALE DEL GESTIONALE:
- Pagina in cui si trova l'utente: {page_context.get('path', '/')} (Cliente attivo nella pagina: {page_context.get('cliente_id') or 'Nessuno'})
- Categorie esistenti: {cat_list_str}
- Clienti registrati: {clienti_str}
- Totale prodotti a catalogo: {len(snapshot['prodotti'])} (di cui senza categoria: {len(snapshot['prodotti_senza_categoria'])})
- Elenco prodotti senza categoria (primi 60): {json.dumps(senza_cat_sample, ensure_ascii=False)}
- Campione prodotti a catalogo (primi 120): {json.dumps(catalogo_sample, ensure_ascii=False)}
"""

    if uploaded_products or uploaded_raw_text:
        system_prompt += f"""
FILE ALLEGATO DALL'UTENTE NELLA CHAT:
- Prodotti già pre-estratti dal parser: {json.dumps(uploaded_products[:80], ensure_ascii=False)}
- Testo grezzo estratto dal file (primi 3000 caratteri):
{uploaded_raw_text[:3000]}
Usa questi dati per preparare l'azione richiesta dall'utente (caricamento catalogo, assegnazione a cliente o creazione volantino).
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
# COSTRUZIONE PIANI D'AZIONE (CON ANTEPRIMA INTERATTIVA)
# ==============================================================================
def build_action_from_intent(intent_name: str, args: dict, snapshot: dict, page_context: dict, uploaded_products: list):
    page_client_id = page_context.get("cliente_id")

    if intent_name == "prepare_catalog_import":
        raw_items = args.get("prodotti") or uploaded_products or []
        enriched = enrich_products_with_db_status(raw_items, snapshot)
        return {
            "reply": args.get("spiegazione") or f"Ho preparato l'anteprima di **{len(enriched)} prodotti** con auto-categorizzazione. Verifica i dati qui sotto e clicca **Conferma e Salva** per inserirli nel catalogo aziendale.",
            "pending_action": {
                "type": "catalog_import",
                "title": f"Caricamento Catalogo Aziendale ({len(enriched)} prodotti)",
                "categories": snapshot["categorie_nomi"],
                "items": enriched
            }
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
        return {
            "reply": args.get("spiegazione") or (
                f"Ho analizzato i **{len(raw_assign)} prodotti senza categoria** e ho assegnato a ciascuno la categoria più adatta. "
                "Puoi modificarle dal menu a tendina e cliccare **Conferma e Salva**."
                if raw_assign else "Ottima notizia: tutti i prodotti presenti nel catalogo hanno già una categoria assegnata!"
            ),
            "pending_action": {
                "type": "auto_categorize",
                "title": f"Auto-Categorizzazione ({len(raw_assign)} prodotti)",
                "categories": snapshot["categorie_nomi"],
                "items": raw_assign
            } if raw_assign else None
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
        return {
            "reply": args.get("spiegazione") or f"Ho preparato l'assegnazione di **{len(enriched)} prodotti** per il cliente **{client_name_label}**. Controlla i prezzi e clicca **Conferma e Salva**.",
            "pending_action": {
                "type": "client_assignment",
                "title": f"Inserimento Prodotti per Cliente: {client_name_label}",
                "cliente_id": target_client["id"] if target_client else None,
                "cliente_nome": client_name_label,
                "clienti": snapshot["clienti"],
                "categories": snapshot["categorie_nomi"],
                "items": enriched
            }
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

        # Se ancora vuoto, prendi i primi 9 prodotti con prezzo o del catalogo
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

        return {
            "reply": args.get("spiegazione") or f"Ho preparato il volantino **{titolo}** ({cols}x{rows}) con **{len(enriched)} prodotti**. Verifica i prezzi in anteprima e clicca **Conferma e Crea Volantino**!",
            "pending_action": {
                "type": "create_flyer",
                "title": f"Creazione Volantino: {titolo}",
                "titolo_volantino": titolo,
                "tema": tema,
                "cols": cols,
                "rows": rows,
                "items": enriched
            }
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


def local_smart_router(user_message: str, page_context: dict, snapshot: dict, uploaded_products: list):
    """Fallback locale intelligente (funziona anche senza chiave OpenAI o se l'utente usa i comandi rapidi)."""
    msg = (user_message or "").strip()
    msg_low = msg.lower()

    # 0. Ricerca quali clienti lavorano un singolo prodotto o prodotti simili
    if any(k in msg_low for k in [
        "chi lavora", "chi compra", "chi acquista", "chi ha", "quale cliente lavora",
        "quali clienti lavorano", "quale dei miei clienti", "quali dei miei clienti",
        "cerca chi", "clienti che lavorano", "prodotto simile", "prodotti simili"
    ]):
        return build_action_from_intent(
            "search_clients_for_product",
            {"prodotto_cercato": msg},
            snapshot,
            page_context,
            uploaded_products
        )

    # 1. Richiesta di auto-categorizzazione prodotti senza categoria
    if any(k in msg_low for k in ["senza categoria", "categorizza", "auto-categorizza", "autocategorizza", "assegna categorie"]):
        return build_action_from_intent("prepare_auto_categorize", {}, snapshot, page_context, uploaded_products)

    # 2. Richiesta di creazione volantino
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

        cli_filter = ""
        for cli in snapshot["clienti"]:
            if cli["nome"].lower() in msg_low:
                cli_filter = cli["nome"]
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
                "cliente_filtro": cli_filter,
                "prodotti": extracted
            },
            snapshot,
            page_context,
            uploaded_products
        )

    # 3. Richiesta di assegnazione prodotti a un cliente
    matched_client = None
    for cli in snapshot["clienti"]:
        if cli["nome"].lower() in msg_low:
            matched_client = cli["nome"]
            break

    if matched_client or any(k in msg_low for k in ["cliente", "listino cliente", "assegna a", "inserisci per"]):
        extracted = uploaded_products or extract_products_from_free_text(msg, snapshot["categorie_nomi"])
        cat_copy = ""
        for c in snapshot["categorie_nomi"]:
            if c.lower() in msg_low:
                cat_copy = c
                break
        if extracted or cat_copy:
            return build_action_from_intent(
                "prepare_client_products_assignment",
                {
                    "cliente_nome": matched_client or "",
                    "categoria_da_copiare": cat_copy,
                    "prodotti": extracted
                },
                snapshot,
                page_context,
                uploaded_products
            )

    # 4. Caricamento prodotti a catalogo (da file allegato o da lista testo)
    extracted = uploaded_products or extract_products_from_free_text(msg, snapshot["categorie_nomi"])
    if extracted:
        return build_action_from_intent(
            "prepare_catalog_import",
            {"prodotti": extracted},
            snapshot,
            page_context,
            uploaded_products
        )

    # 5. Risposta informativa / guida contestuale
    api_key, _ = get_openai_config()
    key_hint = "" if api_key else "\n\n💡 *Nota: Puoi cliccare sull'icona ⚙️ in alto nella chat per inserire la tua chiave API OpenAI (`GPT-4o`) e sbloccare il dialogo avanzato.*"
    return {
        "reply": (
            "Ecco cosa posso fare subito per te sul gestionale:\n"
            "- 📦 **Caricare prodotti aziendali**: incolla qui una lista di prodotti (es. `1020 Hamburger Scottona 200g €11.50`) o allega un file **PDF / Excel / CSV** col tasto 📎.\n"
            f"- 🏷️ **Auto-categorizzare**: al momento hai **{len(snapshot['prodotti_senza_categoria'])} prodotti senza categoria**. Scrivimi *\"Categorizza i prodotti senza categoria\"*.\n"
            "- 👤 **Inserire prodotti per cliente**: scrivimi *\"Assegna a [Nome Cliente] questi prodotti: ...\"*.\n"
            "- 🎨 **Creare volantini rapidi**: scrivimi *\"Crea un volantino 3x3 con i prodotti della categoria Carne\"*."
            + key_hint
        ),
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

    if request.content_type and "multipart/form-data" in request.content_type:
        user_message = (request.form.get("message") or "").strip()
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

    # Tenta con OpenAI GPT-4o se la chiave è configurata
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
                result = build_action_from_intent(fn_name, fn_args, snapshot, page_context, uploaded_products)
                if result:
                    return jsonify({"ok": True, **result})
            content = choice.get("content")
            if content:
                return jsonify({"ok": True, "reply": content, "pending_action": None})

    # Fallback intelligente locale (o se OpenAI non è ancora configurato)
    result = local_smart_router(user_message, page_context, snapshot, uploaded_products)
    return jsonify({"ok": True, **result})


@ai_agent_bp.route("/api/ai-agent/execute", methods=["POST"])
def api_ai_agent_execute():
    """Esegue effettivamente l'operazione sul DB dopo che l'utente ha cliccato 'Conferma e Salva'."""
    if not session.get("logged_in"):
        return jsonify({"ok": False, "error": "Non autorizzato"}), 401

    data = request.get_json(silent=True) or {}
    action_type = data.get("type")
    items = data.get("items") or []

    if not action_type:
        return jsonify({"ok": False, "error": "Tipo di azione mancante."}), 400

    try:
        # ------------------------------------------------------------------
        # 1. IMPORTAZIONE / AGGIORNAMENTO CATALOGO PRODOTTI AZIENDALI
        # ------------------------------------------------------------------
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

            return jsonify({
                "ok": True,
                "message": f"✅ Operazione completata! Creati **{created_count}** nuovi prodotti e aggiornati **{updated_count}** prodotti nel catalogo aziendale.",
                "redirect_url": url_for("prodotti"),
                "redirect_label": "📦 Vai al Catalogo Prodotti"
            })

        # ------------------------------------------------------------------
        # 2. AUTO-CATEGORIZZAZIONE PRODOTTI SENZA CATEGORIA
        # ------------------------------------------------------------------
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

            return jsonify({
                "ok": True,
                "message": f"✅ Categorizzati con successo **{updated_count}** prodotti!",
                "redirect_url": url_for("prodotti"),
                "redirect_label": "🏷️ Vedi Prodotti Categorizzati"
            })

        # ------------------------------------------------------------------
        # 3. ASSEGNAZIONE PRODOTTI AL LISTINO DI UN CLIENTE
        # ------------------------------------------------------------------
        elif action_type == "client_assignment":
            cliente_id = data.get("cliente_id")
            if not cliente_id:
                return jsonify({"ok": False, "error": "Seleziona un cliente valido prima di confermare."}), 400
            cliente_id = int(cliente_id)

            assigned_count = 0
            with _GET_DB() as conn:
                cur = conn.cursor()
                cur.execute("SELECT id, nome FROM clienti WHERE id = %s", (cliente_id,))
                cli_row = cur.fetchone()
                if not cli_row:
                    return jsonify({"ok": False, "error": "Cliente non trovato."}), 404
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

                    # Trova o crea il prodotto nel catalogo generale
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

                    # Associa al cliente in clienti_prodotti (compatibile PostgreSQL & SQLite)
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

            return jsonify({
                "ok": True,
                "message": f"✅ Assegnati **{assigned_count}** prodotti al listino del cliente **{cliente_nome}**!",
                "redirect_url": f"/clienti/{cliente_id}",
                "redirect_label": f"👤 Apri Scheda di {cliente_nome}"
            })

        # ------------------------------------------------------------------
        # 4. CREAZIONE RAPIDA VOLANTINO (VolantinoBeta)
        # ------------------------------------------------------------------
        elif action_type == "create_flyer":
            active_items = [it for it in items if not it.get("excluded")]
            if not active_items:
                return jsonify({"ok": False, "error": "Seleziona almeno un prodotto per il volantino."}), 400

            titolo = (data.get("titolo_volantino") or f"Volantino AI - {datetime.now().strftime('%d/%m/%Y %H:%M')}").strip()
            tipo = data.get("tema") or "promo_mensile"
            cols = max(1, min(6, int(data.get("cols") or 3)))
            rows = max(1, min(6, int(data.get("rows") or 3)))
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

            return jsonify({
                "ok": True,
                "message": f"🎨 Volantino **{titolo}** creato con successo ({len(doc_pages)} pagine, {len(active_items)} prodotti)!",
                "redirect_url": editor_url,
                "redirect_label": "🎨 Apri nell'Editor Volantino"
            })

        return jsonify({"ok": False, "error": f"Tipo azione non supportato: {action_type}"}), 400

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"Errore durante l'esecuzione: {str(e)}"}), 500

