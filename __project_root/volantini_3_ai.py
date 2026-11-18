import os
import re
import io
import csv
import json
import time
import html as html_mod
import base64
import tempfile
import requests
import urllib3
import werkzeug.utils
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from datetime import datetime, date
from flask import Blueprint, render_template, request, jsonify, session, url_for

volantini3_bp = Blueprint("volantini3_bp", __name__)

_GET_DB = None
_EXTRACT_PDF_FN = None
_GET_OPENAI_CFG_FN = None

PREGIS_LOGO_URL = "/static/img/logo-pregis-ufficiale.png"


def _ensure_volantini3_table(cur):
    """Assicura l'esistenza della tabella volantini_3_ai anche se il boot era in fallback SQLite."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS volantini_3_ai (
            id SERIAL PRIMARY KEY,
            titolo TEXT NOT NULL,
            sottotitolo TEXT,
            stile TEXT DEFAULT 'sfondo_crema_organico',
            layout_mode TEXT DEFAULT 'pregis_spontaneo',
            dati_json TEXT NOT NULL,
            creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            aggiornato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _fetch_saved_list(cur):
    """Restituisce i volantini salvati più recenti in formato serializzabile."""
    cur.execute("""
        SELECT id, titolo, sottotitolo, stile, layout_mode, aggiornato_il
        FROM volantini_3_ai
        ORDER BY aggiornato_il DESC, id DESC
        LIMIT 50
    """)
    out = []
    for r in cur.fetchall():
        d = dict(r)
        d["aggiornato_il"] = str(d.get("aggiornato_il") or "")[:16]
        out.append(d)
    return out


def _ensure_prodotti_catalog_columns(conn):
    """Assicura che la tabella prodotti abbia tutte le colonne del catalogo (PostgreSQL + SQLite)."""
    cols = [
        ("codice", "TEXT"),
        ("descrizione", "TEXT"),
        ("immagine", "TEXT"),
        ("marca", "TEXT"),
        ("confezionamento", "TEXT"),
        ("prezzo", "REAL"),
        ("eliminato", "BOOLEAN DEFAULT FALSE"),
    ]
    cur = conn.cursor()
    is_sqlite = hasattr(cur, "_cursor")
    if is_sqlite:
        cur.execute("PRAGMA table_info(prodotti)")
        existing = {row.get("name") for row in cur.fetchall()}
        for col_name, col_type in cols:
            if col_name not in existing:
                cur.execute(f"ALTER TABLE prodotti ADD COLUMN {col_name} {col_type}")
        conn.commit()
    else:
        for col_name, col_type in cols:
            cur.execute(f"ALTER TABLE prodotti ADD COLUMN IF NOT EXISTS {col_name} {col_type}")
        conn.commit()


def init_volantini_3(app, get_db_fn, extract_pdf_fn, get_openai_cfg_fn=None):
    global _GET_DB, _EXTRACT_PDF_FN, _GET_OPENAI_CFG_FN
    _GET_DB = get_db_fn
    _EXTRACT_PDF_FN = extract_pdf_fn
    _GET_OPENAI_CFG_FN = get_openai_cfg_fn

    try:
        with _GET_DB() as conn:
            cur = conn.cursor()
            _ensure_volantini3_table(cur)
            _ensure_prodotti_catalog_columns(conn)
            conn.commit()
    except Exception as e:
        print(f"⚠️ init_volantini_3 table warning: {e}")

    app.register_blueprint(volantini3_bp)


# ==============================================================================
# MOTORE AI PER PULIZIA NOMI, ESTRAZIONE MARCHIO/IMBALLO E ABBELLIMENTO PREGIS
# ==============================================================================
ABBREV_MAP = {
    r'\bFIL\.?\b': 'Filetto',
    r'\bHAMB\.?\b': 'Hamburger',
    r'\bSALM\.?\b': 'Salmone',
    r'\bNORV\.?\b': 'Norvegese',
    r'\bCONG\.?\b': 'Surgelato',
    r'\bSURG\.?\b': 'Surgelato',
    r'\bFRESC[OA]\.?\b': 'Fresco',
    r'\bNAZ\.?\b': 'Nazionale',
    r'\bSCOT\.?\b': 'Scottona',
    r'\bGAMB\.?\b': 'Gambero',
    r'\bMAZZ\.?\b': 'Mazzancolla',
    r'\bCALAM\.?\b': 'Calamaro',
    r'\bSEPPI[EA]\.?\b': 'Seppia',
    r'\bPROSC\.?\b': 'Prosciutto',
    r'\bMOZZ\.?\b': 'Mozzarella',
    r'\bFIOR\.?\b': 'Fiordilatte',
    r'\bPAT\.?\b': 'Patate',
    r'\bRIST\.?\b': 'Ristorazione',
    r'\bSTAG\.?\b': 'Stagionato',
    r'\bS/PELLE\b': 's/pelle',
    r'\bS/GLUT\b': 's/glutine',
}

KNOWN_BRANDS = [
    "Pregis", "S.Alessandro", "Sant'Alessandro", "Trinità", "Trinita", "San Francesco",
    "Sorrentino", "Simonini", "Salvatori", "Valpadana", "Sano",
    "Rovagnati", "Beretta", "Fiorucci", "Negroni", "Villani", "Levoni",
    "Casa Modena", "Citterio", "Galbani", "Granarolo", "Orogel", "Findus",
    "McCain", "LambWeston", "Mutti", "De Cecco", "Barilla", "Voila", "Surgital"
]


def beautify_product_name(raw_name: str) -> str:
    if not raw_name:
        return "Prodotto Selezione Pregis"
    s = str(raw_name).strip()
    for pat, repl in ABBREV_MAP.items():
        s = re.sub(pat, repl, s, flags=re.IGNORECASE)
    words = s.split()
    out_words = []
    small_words = {"di", "del", "della", "dei", "delle", "al", "alla", "con", "in", "da", "e", "per", "su", "sv", "s/pelle", "s/glutine", "s/glut", "metà", "mesi"}
    for idx, w in enumerate(words):
        w_low = w.lower()
        if re.match(r'^\d+[a-zA-Z/]+$', w_low) or "/" in w_low:
            out_words.append(w_low)
        elif idx > 0 and w_low in small_words:
            out_words.append(w_low)
        elif w.isupper() and len(w) <= 2:
            out_words.append(w)
        else:
            out_words.append(w.capitalize())
    return " ".join(out_words)


def extract_brand_imballo_and_copy(raw_name: str, categoria: str = "", idx: int = 0) -> dict:
    """Estrae marchio, imballo e genera una nota spontanea ed essenziale per il prodotto."""
    name_clean = raw_name or ""
    brand_found = ""

    for b in KNOWN_BRANDS:
        if re.search(r'\b' + re.escape(b) + r'\b', name_clean, re.IGNORECASE):
            brand_found = b
            name_clean = re.sub(r'\b' + re.escape(b) + r'\b', '', name_clean, flags=re.IGNORECASE).strip(" -–,")
            break

    imballo = ""
    m_imb = re.search(r'(?:imballo\s*)?(\d+[\.,]?\d*\s*(?:kg|gr|g|lt|ml|pz))', name_clean, re.IGNORECASE)
    if m_imb:
        imballo = f"Imballo {m_imb.group(1).lower()}"
    else:
        default_imballi = ["Imballo 5.50 kg", "Imballo 8.70 kg", "Imballo 2.20 kg", "Imballo 1.00 kg", "Imballo 3.88 kg", "Imballo 2.65 kg", "Imballo 7.20 kg", "Imballo 3.50 kg", "Imballo 3.00 kg", "Imballo 1.40 kg"]
        imballo = default_imballi[idx % len(default_imballi)]

    c_low = (categoria or "").lower()
    n_low = name_clean.lower()

    if not brand_found:
        if any(k in n_low or k in c_low for k in ["prosciutt", "salame", "lonza", "speck", "bresaola", "mortadella", "salum"]):
            fallback_brands = ["S.Alessandro", "Antica Norcineria", "Maestri Salumieri", "San Francesco", "Valpadana"]
        elif any(k in n_low or k in c_low for k in ["salmone", "polpo", "gamber", "pesce", "ittic", "calamar"]):
            fallback_brands = ["Pregis Mare", "Blue Ocean", "Nordic Superior", "Pescato Scelto"]
        elif any(k in n_low or k in c_low for k in ["angus", "scottona", "manzo", "hamburger", "carne"]):
            fallback_brands = ["Pregis Grill", "Prime Butchery", "Master Beef", "Selezione Carni"]
        else:
            fallback_brands = ["Pregis", "Linea Cucina", "Gastronomia", "Dispensa Chef"]
        brand_found = fallback_brands[idx % len(fallback_brands)]

    # Note spontanee ed essenziali per la ristorazione (nessun target/bollino)
    if any(k in n_low or k in c_low for k in ["prosciutt", "salame", "lonza", "speck", "bresaola", "mortadella", "salum"]):
        copies = [
            "Lavorazione tradizionale a stagionatura lenta, ideale per taglieri e banco.",
            "Fetta morbida e profumata, resa uniforme pensata per pizzerie e antipasti.",
            "Gusto equilibrato e consistenza compatta, perfetto al taglio sottile."
        ]
    elif any(k in n_low or k in c_low for k in ["salmone", "polpo", "gamber", "pesce", "ittic", "calamar", "mazzancoll"]):
        copies = [
            "Polpa soda e gusto naturale di mare, pratico per preparazioni espresse.",
            "Calibratura regolare e ottima tenuta in padella e alla griglia."
        ]
    elif any(k in n_low or k in c_low for k in ["angus", "scottona", "manzo", "hamburger", "carne", "pollo", "suin"]):
        copies = [
            "Taglio tenero dalla buona marezzatura, ideale su piastra e brace.",
            "Porzionatura regolare studiata per servizi rapidi in cucina."
        ]
    else:
        copies = [
            "Formato professionale pratico e versatile per le preparazioni quotidiane.",
            "Qualità costante e buona resa per menù stagionali e banchettistica."
        ]

    return {
        "titolo_pulito": beautify_product_name(name_clean),
        "brand": brand_found,
        "imballo": imballo,
        "descrizione_ai": copies[idx % len(copies)]
    }


def split_price_parts(prezzo_val) -> tuple:
    if isinstance(prezzo_val, (int, float)):
        num = float(prezzo_val)
    else:
        s = str(prezzo_val or "0").replace("€", "").strip()
        m = re.search(r'(\d+[\.,]\d{1,2}|\d+)', s)
        num = float(m.group(1).replace(",", ".")) if m else 0.0
    if num <= 0:
        return ("0", "00", "0,00")
    fmt = f"{num:.2f}"
    parts = fmt.split(".")
    return (parts[0], parts[1], fmt.replace(".", ","))


def get_mesi_stagione_default():
    mesi_it = ["GENNAIO", "FEBBRAIO", "MARZO", "APRILE", "MAGGIO", "GIUGNO",
               "LUGLIO", "AGOSTO", "SETTEMBRE", "OTTOBRE", "NOVEMBRE", "DICEMBRE"]
    m_idx = datetime.now().month
    mese_nome = mesi_it[m_idx - 1]
    return f"PROMO {mese_nome}", "sfondo_crema_organico"


def call_openai_vision_or_enrich(products: list, user_prompt: str = "", image_b64: str = None):
    if not _GET_OPENAI_CFG_FN:
        return None
    api_key, model = _GET_OPENAI_CFG_FN()
    if not api_key:
        return None

    try:
        if image_b64:
            vision_prompt = """Analizza questa immagine di un volantino prodotti e restituisci ESCLUSIVAMENTE un JSON valido senza badge o bollini promozionali:
{
  "titolo": "Titolo semplice e spontaneo (es. Offerte di Novembre)",
  "prodotti": [
    {
      "codice": "codice articolo es. 40616.002",
      "titolo": "Nome del prodotto pulito",
      "brand": "Marchio o produttore in corsivo",
      "imballo": "Testo imballo es. Imballo 5.50 kg",
      "descrizione_ai": "Nota breve e naturale per la cucina (max 70 caratteri, nessuno slogan o target tipo TOP QUALITY)",
      "prezzo": 8.80,
      "um": "al KG",
      "row_span": 2,
      "is_red_price": true
    }
  ]
}
Imposta row_span=2 per 1 o 2 prodotti principali e row_span=1 per gli altri."""
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": vision_prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
                            ]
                        }
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2
                },
                timeout=35
            )
            if resp.status_code == 200:
                return json.loads(resp.json()["choices"][0]["message"]["content"])

        if products:
            sample = [
                {"idx": i, "codice": p.get("codice", ""), "nome": p.get("nome") or p.get("titolo", ""), "prezzo": p.get("prezzo", ""), "um": p.get("um", "KG")}
                for i, p in enumerate(products[:35])
            ]
            sys_prompt = """Sei l'Art Director editoriale di PREGIS S.p.A. (distribuzione alimentare Ho.Re.Ca.).
Il tuo stile deve essere spontaneo, elegante, naturale e pulito: VIETATO inserire targhette, bollini o etichette tipo "TOP QUALITY", "TOP OFFERTA", "BEST SELLER", "SUPER PROMO" o simili.
Per ciascun prodotto genera:
- 'titolo_ai': nome prodotto leggibile ed elegante
- 'brand_ai': produttore o linea in corsivo (es. 'Trinità', 'Simonini', 'S.Alessandro')
- 'imballo_ai': formato confezione (es. 'Imballo 4.50 kg')
- 'descrizione_ai': breve nota gastronomica spontanea e autentica (max 70 caratteri)
Restituisci SOLO un oggetto JSON:
{
  "titolo": "es. Offerte del Mese",
  "prodotti_arricchiti": [
    {"idx": 0, "titolo_ai": "...", "brand_ai": "...", "imballo_ai": "...", "descrizione_ai": "..."}
  ]
}"""
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model or "gpt-4o",
                    "messages": [
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": f"Prodotti: {json.dumps(sample, ensure_ascii=False)}\nIstruzioni: {user_prompt}"}
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.35
                },
                timeout=25
            )
            if resp.status_code == 200:
                return json.loads(resp.json()["choices"][0]["message"]["content"])
    except Exception as e:
        print(f"⚠️ OpenAI Volantini 3.0 warning: {e}")
    return None


def build_rich_flyer_data(raw_products: list, filename: str = "", user_prompt: str = "", per_page: int = 10, ai_beautified: bool = True) -> dict:
    """Costruisce il Volantino PREGIS 3.0 con struttura spontanea, logo pulito, sfondo sotto i prodotti e nessun bollino."""
    db_by_code = {}
    db_by_name = {}
    try:
        with _GET_DB() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT p.id, p.codice, p.nome, p.prezzo, p.immagine, c.nome AS categoria_nome
                FROM prodotti p
                LEFT JOIN categorie c ON p.categoria_id = c.id
                WHERE COALESCE(p.eliminato, FALSE) = FALSE
            """)
            for r in cur.fetchall():
                d = dict(r)
                if d.get("codice"):
                    db_by_code[str(d["codice"]).strip().upper()] = d
                if d.get("nome"):
                    db_by_name[str(d["nome"]).strip().upper()] = d
    except Exception as e:
        print(f"⚠️ DB lookup warning: {e}")

    default_title, default_stile = get_mesi_stagione_default()
    ai_res = call_openai_vision_or_enrich(raw_products, user_prompt=user_prompt)
    ai_map = {}
    if ai_res:
        if ai_res.get("titolo"):
            default_title = ai_res["titolo"]
        for item in (ai_res.get("prodotti_arricchiti") or []):
            if "idx" in item:
                ai_map[int(item["idx"])] = item

    enriched_items = []
    for idx, p in enumerate(raw_products):
        code = str(p.get("codice") or "").strip()
        raw_name = str(p.get("titolo") or p.get("nome") or "Prodotto").strip()
        raw_um = str(p.get("um") or "KG").strip().upper()
        um_label = raw_um if raw_um.startswith("AL ") else f"al {raw_um}"
        cat = str(p.get("categoria") or "OFFERTE").strip()

        p_int, p_dec, p_full = split_price_parts(p.get("prezzo_str") or p.get("prezzo") or 0)

        db_match = db_by_code.get(code.upper()) or db_by_name.get(raw_name.upper())
        img_url = str(p.get("immagine") or "")
        if not img_url and db_match and db_match.get("immagine"):
            img_val = db_match["immagine"]
            img_url = img_val if (img_val.startswith("http") or img_val.startswith("/") or img_val.startswith("data:")) else f"/static/uploads/volantino_prodotti/{img_val}"

        info = extract_brand_imballo_and_copy(raw_name, cat, idx)
        ai_it = ai_map.get(idx, {})

        titolo_clean = ai_it.get("titolo_ai") or p.get("titolo") or info["titolo_pulito"]
        brand_clean = ai_it.get("brand_ai") or p.get("brand") or info["brand"]
        imballo_clean = ai_it.get("imballo_ai") or p.get("imballo") or info["imballo"]
        desc_clean = ai_it.get("descrizione_ai") or p.get("descrizione_ai") or info["descrizione_ai"]

        enriched_items.append({
            "id": db_match["id"] if db_match else p.get("id"),
            "codice": code or f"{40000 + idx}",
            "nome_originale": raw_name,
            "titolo": titolo_clean,
            "brand": brand_clean,
            "imballo": imballo_clean,
            "descrizione_ai": desc_clean,
            "prezzo": p_full,
            "prezzo_int": p_int,
            "prezzo_dec": p_dec,
            "um": um_label,
            "categoria": cat,
            "immagine": img_url,
            "imageZoom": float(p.get("imageZoom") or 1.0),
            "row_span": int(p.get("row_span") or 1),
            "col_span": int(p.get("col_span") or 1),
            "is_red_price": bool(p.get("is_red_price", False))
        })

    pages = []
    if not enriched_items:
        pages.append({"page_number": 1, "items": []})
    else:
        for p_idx in range(0, len(enriched_items), per_page):
            chunk = enriched_items[p_idx:p_idx + per_page]
            if all(it.get("row_span", 1) == 1 and it.get("col_span", 1) == 1 for it in chunk):
                # Ritmo spontaneo invece della solita cornice rigida a 2 torri simmetriche
                if len(chunk) >= 6:
                    chunk[0]["row_span"] = 2
                    chunk[0]["is_red_price"] = True
                    chunk[4]["col_span"] = 2
                    chunk[4]["is_red_price"] = True
                elif len(chunk) >= 3:
                    chunk[0]["row_span"] = 2
                    chunk[0]["is_red_price"] = True
                elif len(chunk) >= 1:
                    chunk[0]["is_red_price"] = True

            pages.append({
                "page_number": (p_idx // per_page) + 1,
                "items": chunk
            })

    nome_suggerito = os.path.splitext(filename)[0].replace("_", " ").strip() if filename else ""

    return {
        "brand_header": "PREGIS",
        "nome_volantino": nome_suggerito,
        "logo_url": PREGIS_LOGO_URL,
        "logo_mode": "logo_and_title",
        "titolo": default_title,
        "sottotitolo": "Selezione gastronomica per la ristorazione",
        "stile": default_stile,
        "card_style": "card_spontanea",
        "custom_bg_url": "",
        "layout_mode": "pregis_spontaneo",
        "ai_beautified": ai_beautified,
        "show_ai_descriptions": True,
        "per_page": per_page,
        "pages": pages
    }


def apply_smart_restyle(flyer_data: dict, prompt_text: str) -> dict:
    p_low = (prompt_text or "").lower()

    flyer_data["ai_beautified"] = True
    flyer_data.pop("show_ai_badges", None)

    if any(k in p_low for k in ["legno", "bistrot", "sabbia", "naturale", "tavola", "rustic"]):
        flyer_data["stile"] = "sfondo_legno_bistrot"
    elif any(k in p_low for k in ["orto", "acquerell", "verde", "botanic", "primaver", "fresc"]):
        flyer_data["stile"] = "sfondo_acquerello_orto"
    elif any(k in p_low for k in ["mare", "pesce", "azzurr", "blu", "mediterrane", "estate"]):
        flyer_data["stile"] = "sfondo_mediterraneo"
    elif any(k in p_low for k in ["terracotta", "autunn", "spezie", "caldo", "arancio", "ottobre", "novembre"]):
        flyer_data["stile"] = "sfondo_terracotta"
    elif any(k in p_low for k in ["ardesia", "nero", "oro", "scuro", "luxury", "sera", "elegante"]):
        flyer_data["stile"] = "sfondo_ardesia_gold"
    elif any(k in p_low for k in ["crema", "onde", "gourmet", "chiaro", "morbido"]):
        flyer_data["stile"] = "sfondo_crema_organico"

    if any(k in p_low for k in ["alone", "pedana", "cerchio", "isola"]):
        flyer_data["card_style"] = "alone_organico"
    elif any(k in p_low for k in ["libero", "fluttuante", "senza riquadr", "senza card"]):
        flyer_data["card_style"] = "libero_su_sfondo"
    elif any(k in p_low for k in ["card", "riquadr", "vetro"]):
        flyer_data["card_style"] = "card_spontanea"

    if "solo logo" in p_low:
        flyer_data["logo_mode"] = "logo_only"

    m_tit = re.search(r'titolo\s+["\']?([A-Za-zÀ-ÿ0-9\s]{3,30})["\']?', prompt_text, re.IGNORECASE)
    if m_tit:
        flyer_data["titolo"] = m_tit.group(1).strip().upper()

    if "base" in p_low and ("classico" in p_low or "semplice" in p_low):
        flyer_data["ai_beautified"] = False

    # Rigenera descrizioni e nomi con AI senza badge/target
    all_items = [it for pg in (flyer_data.get("pages") or []) for it in (pg.get("items") or [])]
    ai_res = call_openai_vision_or_enrich(all_items, user_prompt=prompt_text)
    ai_map = {}
    if ai_res:
        if ai_res.get("titolo"):
            flyer_data["titolo"] = ai_res["titolo"]
        for x in (ai_res.get("prodotti_arricchiti") or []):
            if "idx" in x:
                ai_map[int(x["idx"])] = x

    flat_idx = 0
    for pg in (flyer_data.get("pages") or []):
        for it in (pg.get("items") or []):
            it.pop("badge", None)
            info = extract_brand_imballo_and_copy(it.get("nome_originale") or it.get("titolo", ""), it.get("categoria", ""), flat_idx)
            upd = ai_map.get(flat_idx, {})
            it["titolo"] = upd.get("titolo_ai") or beautify_product_name(it.get("titolo", ""))
            it["brand"] = upd.get("brand_ai") or it.get("brand") or info["brand"]
            it["descrizione_ai"] = upd.get("descrizione_ai") or it.get("descrizione_ai") or info["descrizione_ai"]
            flat_idx += 1

    return flyer_data


# ==============================================================================
# ROUTES VOLANTINI 3.0 AI STUDIO (PREGIS)
# ==============================================================================
@volantini3_bp.route("/volantini-3")
def pagina_volantini_3():
    if not session.get("logged_in"):
        from flask import redirect
        return redirect(url_for("login"))

    vol_id = request.args.get("id", type=int)
    loaded_flyer = None
    saved_list = []
    categorie = []

    try:
        with _GET_DB() as conn:
            cur = conn.cursor()
            _ensure_volantini3_table(cur)
            conn.commit()
            saved_list = _fetch_saved_list(cur)

            if vol_id:
                cur.execute("SELECT * FROM volantini_3_ai WHERE id = %s", (vol_id,))
                row_v = cur.fetchone()
                if row_v:
                    loaded_flyer = dict(row_v)

            cur.execute("SELECT id, nome FROM categorie ORDER BY nome")
            categorie = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"⚠️ Errore caricamento pagina_volantini_3: {e}")

    return render_template(
        "08_volantini_3/volantini_3.html",
        loaded_flyer=loaded_flyer,
        saved_list=saved_list,
        categorie=categorie
    )


@volantini3_bp.route("/api/volantini-3/genera-da-pdf", methods=["POST"])
def api_volantini_3_genera_da_pdf():
    if not session.get("logged_in"):
        return jsonify({"ok": False, "error": "Non autorizzato"}), 401

    user_prompt = (request.form.get("prompt") or "").strip()
    per_page = int(request.form.get("per_page") or 10)
    categoria_id = request.form.get("categoria_id")
    raw_text = (request.form.get("raw_text") or "").strip()

    products = []
    filename = ""
    vision_title = None

    file = request.files.get("pdf") or request.files.get("file")
    if file and file.filename:
        filename = file.filename
        ext = os.path.splitext(filename)[1].lower()

        if ext in (".jpg", ".jpeg", ".png", ".webp"):
            img_bytes = file.read()
            b64_str = base64.b64encode(img_bytes).decode("utf-8")
            v_res = call_openai_vision_or_enrich([], user_prompt=user_prompt, image_b64=b64_str)
            if v_res and v_res.get("prodotti"):
                products = v_res["prodotti"]
                vision_title = v_res.get("titolo")
        else:
            temp_dir = tempfile.gettempdir()
            temp_path = os.path.join(temp_dir, f"v3_{int(time.time())}_{werkzeug.utils.secure_filename(filename)}")
            file.save(temp_path)
            try:
                if _EXTRACT_PDF_FN:
                    products = _EXTRACT_PDF_FN(temp_path)
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

    if not products and categoria_id:
        try:
            with _GET_DB() as conn:
                cur = conn.cursor()
                if categoria_id == "all":
                    cur.execute("""
                        SELECT p.id, p.codice, p.nome, p.prezzo, p.immagine, c.nome AS categoria
                        FROM prodotti p
                        LEFT JOIN categorie c ON p.categoria_id = c.id
                        WHERE COALESCE(p.eliminato, FALSE) = FALSE
                        ORDER BY p.id DESC LIMIT 20
                    """)
                else:
                    cur.execute("""
                        SELECT p.id, p.codice, p.nome, p.prezzo, p.immagine, c.nome AS categoria
                        FROM prodotti p
                        LEFT JOIN categorie c ON p.categoria_id = c.id
                        WHERE p.categoria_id = %s AND COALESCE(p.eliminato, FALSE) = FALSE
                        ORDER BY p.nome LIMIT 30
                    """, (int(categoria_id),))
                for r in cur.fetchall():
                    d = dict(r)
                    img_v = d.get("immagine") or ""
                    img_u = f"/static/uploads/volantino_prodotti/{img_v}" if (img_v and not img_v.startswith("http") and not img_v.startswith("/") and not img_v.startswith("data:")) else img_v
                    products.append({
                        "id": d["id"],
                        "codice": d.get("codice") or "",
                        "nome": d["nome"],
                        "prezzo": float(d.get("prezzo") or 0),
                        "um": "KG",
                        "categoria": d.get("categoria") or "OFFERTE",
                        "immagine": img_u
                    })
        except Exception as e:
            print(f"⚠️ Errore caricamento prodotti da categoria: {e}")

    if not products and raw_text:
        for line in raw_text.splitlines():
            line = line.strip()
            if len(line) < 3:
                continue
            m_price = re.search(r'(\d+[\.,]\d{2})', line)
            prz = float(m_price.group(1).replace(",", ".")) if m_price else 0.0
            clean_n = re.sub(r'€?\s*\d+[\.,]\d{2}', '', line).strip(" -–•\t")
            m_code = re.match(r'^([A-Za-z0-9\.]{3,14})\s+(.+)$', clean_n)
            cod = m_code.group(1) if m_code else ""
            nom = m_code.group(2) if m_code else clean_n
            if nom:
                products.append({"codice": cod, "nome": nom, "prezzo": prz, "um": "KG", "categoria": "OFFERTE"})

    if not products:
        return jsonify({
            "ok": False,
            "error": "Nessun prodotto trovato nel file caricato. Assicurati che il PDF contenga codici e prezzi oppure scegli una categoria dal catalogo."
        }), 400

    flyer_data = build_rich_flyer_data(products, filename=filename, user_prompt=user_prompt, per_page=per_page, ai_beautified=True)
    if vision_title:
        flyer_data["titolo"] = vision_title
    if user_prompt:
        flyer_data = apply_smart_restyle(flyer_data, user_prompt)

    return jsonify({
        "ok": True,
        "message": f"✨ Volantino PREGIS 3.0 generato e abbellito con AI ({len(products)} prodotti in {len(flyer_data['pages'])} pagine)!",
        "flyer": flyer_data
    })


@volantini3_bp.route("/api/volantini-3/ai-restyle", methods=["POST"])
def api_volantini_3_ai_restyle():
    if not session.get("logged_in"):
        return jsonify({"ok": False, "error": "Non autorizzato"}), 401

    data = request.get_json(silent=True) or {}
    flyer_data = data.get("flyer") or {}
    prompt_text = (data.get("prompt") or "").strip()

    if not flyer_data:
        return jsonify({"ok": False, "error": "Dati volantino mancanti"}), 400

    updated = apply_smart_restyle(flyer_data, prompt_text)
    return jsonify({
        "ok": True,
        "message": "✨ Volantino PREGIS abbellito con AI!",
        "flyer": updated
    })


@volantini3_bp.route("/api/volantini-3/salva", methods=["POST"])
def api_volantini_3_salva():
    if not session.get("logged_in"):
        return jsonify({"ok": False, "error": "Non autorizzato"}), 401

    data = request.get_json(silent=True) or {}
    vol_id = data.get("id")
    flyer = data.get("flyer") or {}
    nome_volantino = (data.get("nome") or flyer.get("nome_volantino") or flyer.get("titolo") or "Volantino PREGIS").strip()
    flyer["nome_volantino"] = nome_volantino
    sottotitolo = (flyer.get("titolo") or flyer.get("sottotitolo") or "").strip()
    stile = flyer.get("stile") or "sfondo_crema_organico"
    layout_mode = flyer.get("layout_mode") or "pregis_spontaneo"
    dati_json = json.dumps(flyer, ensure_ascii=False)

    try:
        with _GET_DB() as conn:
            cur = conn.cursor()
            _ensure_volantini3_table(cur)
            saved_id = None

            if vol_id:
                cur.execute("""
                    UPDATE volantini_3_ai
                    SET titolo = %s, sottotitolo = %s, stile = %s, layout_mode = %s,
                        dati_json = %s, aggiornato_il = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (nome_volantino, sottotitolo, stile, layout_mode, dati_json, int(vol_id)))
                if getattr(cur, "rowcount", 0) > 0:
                    saved_id = int(vol_id)

            if not saved_id:
                cur.execute("""
                    INSERT INTO volantini_3_ai (titolo, sottotitolo, stile, layout_mode, dati_json)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id
                """, (nome_volantino, sottotitolo, stile, layout_mode, dati_json))
                r = cur.fetchone()
                if r:
                    saved_id = r["id"] if isinstance(r, dict) else r[0]
                if not saved_id:
                    saved_id = getattr(cur, "lastrowid", None)

            conn.commit()
            saved_list = _fetch_saved_list(cur)
        return jsonify({
            "ok": True,
            "id": saved_id,
            "nome": nome_volantino,
            "saved_list": saved_list,
            "message": f"✅ Volantino '{nome_volantino}' salvato!"
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@volantini3_bp.route("/api/volantini-3/elimina/<int:vol_id>", methods=["POST", "DELETE"])
def api_volantini_3_elimina(vol_id):
    if not session.get("logged_in"):
        return jsonify({"ok": False, "error": "Non autorizzato"}), 401

    try:
        with _GET_DB() as conn:
            cur = conn.cursor()
            _ensure_volantini3_table(cur)
            cur.execute("DELETE FROM volantini_3_ai WHERE id = %s", (vol_id,))
            conn.commit()
            saved_list = _fetch_saved_list(cur)
        return jsonify({"ok": True, "saved_list": saved_list})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ==============================================================================
# SCANNER & IMPORTATORE CATALOGO PREGIS (SOLA LETTURA DA SAFARI / WEB)
# ==============================================================================
class _DOMNode:
    __slots__ = ("tag", "attrs", "children", "text_parts", "parent")

    def __init__(self, tag, attrs, parent=None):
        self.tag = (tag or "").lower()
        self.attrs = {k.lower(): (v or "") for k, v in (attrs or [])}
        self.children = []
        self.text_parts = []
        self.parent = parent

    def get_text(self, sep=" "):
        parts = []
        for c in self.children:
            if isinstance(c, str):
                s = c.strip()
                if s:
                    parts.append(s)
            else:
                t = c.get_text(sep=sep)
                if t:
                    parts.append(t)
        return re.sub(r'\s+', ' ', sep.join(parts)).strip()

    def iter_descendants(self):
        for c in self.children:
            if isinstance(c, _DOMNode):
                yield c
                yield from c.iter_descendants()


class _PregisDOMBuilder(HTMLParser):
    VOID_TAGS = {"img", "br", "hr", "input", "meta", "link", "source"}
    SKIP_TAGS = {"script", "style", "noscript", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _DOMNode("root", [])
        self.curr = self.root
        self.skip_depth = 0
        self.in_ld_json = False
        self.ld_json_blocks = []
        self._curr_ld = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        if t == "script" and "ld+json" in attr_dict.get("type", "").lower():
            self.in_ld_json = True
            self._curr_ld = []
            return
        if t in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth > 0:
            return
        node = _DOMNode(t, attrs, parent=self.curr)
        self.curr.children.append(node)
        if t not in self.VOID_TAGS:
            self.curr = node

    def handle_endtag(self, tag):
        t = tag.lower()
        if t == "script" and self.in_ld_json:
            self.in_ld_json = False
            raw = "".join(self._curr_ld).strip()
            if raw:
                self.ld_json_blocks.append(raw)
            self._curr_ld = []
            return
        if t in self.SKIP_TAGS:
            if self.skip_depth > 0:
                self.skip_depth -= 1
            return
        if self.skip_depth > 0 or t in self.VOID_TAGS:
            return
        p = self.curr
        while p and p.tag != t and p is not self.root:
            p = p.parent
        if p and p.parent:
            self.curr = p.parent

    def handle_data(self, data):
        if self.in_ld_json:
            self._curr_ld.append(data)
            return
        if self.skip_depth > 0:
            return
        if data and data.strip():
            self.curr.children.append(data)


def _is_valid_product_img_url(url: str) -> bool:
    if not url:
        return False
    u = url.strip()
    if u.startswith("data:image/svg") or len(u) < 5:
        return False
    low = u.lower()
    if any(bad in low for bad in ["missing_image_catalogue", "favicon", "sprite", "spinner", "loading", "placeholder", "no-image", "pixel", "blank.gif", "1x1"]):
        return False
    return True


def _pick_img_from_node(node: _DOMNode, base_url: str = "") -> str:
    best = ""
    candidates = [node] + list(node.iter_descendants())

    # 1. Tag <img> tradizionali
    for img in candidates:
        if img.tag != "img":
            continue
        cand = ""
        for attr in ("data-zoom-image", "data-large_image", "data-large", "data-original", "data-lazy-src", "data-src", "src"):
            v = img.attrs.get(attr, "").strip()
            if _is_valid_product_img_url(v):
                cand = v
                break
        if not cand and img.attrs.get("srcset"):
            parts = [p.strip().split(" ")[0] for p in img.attrs["srcset"].split(",") if p.strip()]
            if parts and _is_valid_product_img_url(parts[-1]):
                cand = parts[-1]
        if cand:
            if cand.startswith("//"):
                cand = "https:" + cand
            elif base_url and not cand.startswith(("http://", "https://", "data:")):
                cand = urljoin(base_url, cand)
            if "logo" not in cand.lower():
                return cand
            if not best:
                best = cand

    # 2. Tag <figure> / <div smartCssImage> con background-image inline (stile Angular .onSalesSmart)
    for n in candidates:
        style_val = n.attrs.get("style", "") or ""
        bg_attr = n.attrs.get("data-bg", "") or n.attrs.get("data-background-image", "") or ""
        raw_cands = []
        if style_val and "url(" in style_val.lower():
            for m_bg in re.finditer(r'url\((?:["\']?)(.*?)(?:["\']?)\)', style_val, re.IGNORECASE):
                raw_cands.append(m_bg.group(1).strip())
        if bg_attr:
            raw_cands.append(bg_attr.strip())
        if n.tag == "figure" or "smartcssimage" in n.attrs:
            for attr in ("src", "data-src"):
                v = n.attrs.get(attr, "").strip()
                if v:
                    raw_cands.append(v)

        for cand in raw_cands:
            if not _is_valid_product_img_url(cand):
                continue
            if cand.startswith("//"):
                cand = "https:" + cand
            elif not cand.startswith(("http://", "https://", "data:")):
                eff_base = base_url or ("https://tua.pregis.it/onSalesSmart/" if not cand.startswith("/") else "https://tua.pregis.it")
                cand = urljoin(eff_base, cand)
            if "logo" not in cand.lower():
                return cand
            if not best:
                best = cand

    return best


def _extract_product_from_dom_block(block: _DOMNode, base_url: str = "", default_cat: str = "") -> dict:
    attrs = block.attrs
    full_text = block.get_text("\n")
    if not full_text or len(full_text) < 3:
        return {}

    img_url = _pick_img_from_node(block, base_url=base_url)

    # Codice da data-attributes o sotto-elementi dedicati
    codice = ""
    for k in ("data-sku", "data-codice", "data-code", "data-product-code", "data-art", "data-id-prodotto"):
        if attrs.get(k):
            codice = attrs[k].strip()
            break

    title_cand = ""
    desc_cand = ""
    marca_cand = attrs.get("data-brand", "").strip() or attrs.get("data-marca", "").strip()
    cat_cand = attrs.get("data-category", "").strip() or attrs.get("data-categoria", "").strip() or default_cat
    conf_cand = attrs.get("data-pack", "").strip() or attrs.get("data-confezionamento", "").strip()
    price_cand = None

    for n in block.iter_descendants():
        cls = (n.attrs.get("class", "") + " " + n.attrs.get("id", "") + " " + n.attrs.get("itemprop", "")).lower()
        cls_tokens = set(cls.split())
        t = n.get_text(" ")
        if not t:
            continue
        if not codice and ("cod" in cls_tokens or "suggestion-item-info__id" in cls_tokens or any(k in cls for k in ("sku", "codice", "code", "cod-", "art-code", "ref"))):
            m_c = re.search(r'(?:cod\.?|codice|art\.?|sku)?\s*[:#]?\s*([A-Z0-9\.\-\/]{2,20})', t, re.IGNORECASE)
            if m_c and len(m_c.group(1)) <= 20 and m_c.group(1).strip(".").upper() not in ("COD", "SKU", "ART", "EAN", "BARCODE", "REF"):
                codice = m_c.group(1).strip()
        if not marca_cand and ("brand" in cls_tokens or "suggestion-item-info__brand" in cls_tokens or any(k in cls for k in ("brand", "marca", "produttore", "maker", "fornitore"))):
            cleaned_m = re.sub(r'^(?:marca|brand|produttore)\s*[:\-]\s*', '', t, flags=re.IGNORECASE).strip()
            if cleaned_m and cleaned_m != title_cand:
                marca_cand = cleaned_m
        if any(k in cls for k in ("categ", "reparto", "famiglia")) and len(t) < 60:
            cat_cand = re.sub(r'^(?:categoria|reparto)\s*[:\-]\s*', '', t, flags=re.IGNORECASE).strip()
        if not conf_cand and ("weight" in cls_tokens or ("text" in cls_tokens and n.parent and "product-card-picker-single" in (n.parent.attrs.get("class", "").lower())) or any(k in cls for k in ("conf", "pack", "imball", "pezz", "formato", "peso", "uom"))):
            conf_cand = re.sub(r'^(?:confezionamento|confezione|imballo|pezzatura)\s*[:\-]\s*', '', t, flags=re.IGNORECASE).strip().strip("()")
        if price_cand is None and ("real-price" in cls_tokens or "price" in cls_tokens or any(k in cls for k in ("price", "prezzo", "costo"))):
            m_p = re.search(r'(\d+[\.,]\d{2})', t)
            if m_p:
                price_cand = float(m_p.group(1).replace(",", "."))
        if not title_cand and ("name" in cls_tokens or "suggestion-item-info__title" in cls_tokens or n.tag in ("h1", "h2", "h3", "h4", "h5") or any(k in cls for k in ("title", "name", "nome", "product-name", "descrizione-breve"))):
            if len(t) >= 3 and not re.match(r'^[\d\.,\s€]+$', t):
                title_cand = t
        if not desc_cand and ("second-desc" in cls_tokens or any(k in cls for k in ("desc", "summary", "dettagli", "note"))):
            if len(t) > 3 and t != title_cand:
                desc_cand = t

    # Estrazione regex sul testo del blocco come fallback
    if not codice:
        m_c = re.search(r'(?:cod\.?|codice|art\.?|sku)\s*[:#\-]?\s*([A-Z0-9]{2,}[A-Z0-9\.\-\/]{1,16})', full_text, re.IGNORECASE)
        if m_c:
            codice = m_c.group(1).strip()
        else:
            m_num = re.search(r'\b(\d{4,8}(?:\.\d{1,4})?)\b', full_text)
            if m_num:
                codice = m_num.group(1).strip()

    if not marca_cand:
        m_m = re.search(r'(?:marca|brand|produttore)\s*[:\-]\s*([^\n|•]{2,40})', full_text, re.IGNORECASE)
        if m_m:
            marca_cand = m_m.group(1).strip()

    if not conf_cand:
        m_k = re.search(r'(?:confezionamento|confezione|conf\.?|imballo|pezzatura|formato)\s*[:\-]?\s*([^\n|•]{2,45})', full_text, re.IGNORECASE)
        if m_k:
            conf_cand = m_k.group(1).strip()
        else:
            m_u = re.search(r'\b(\d+(?:[\.,]\d+)?\s*(?:x\s*\d+(?:[\.,]\d+)?)?\s*(?:kg|gr|g|lt|l|ml|cl|pz|cf|crt)\b(?:\s*x\s*\d+)?)', full_text, re.IGNORECASE)
            if m_u:
                conf_cand = m_u.group(1).strip()

    if price_cand is None:
        m_p = re.search(r'€\s*(\d+[\.,]\d{2})|(\d+[\.,]\d{2})\s*€', full_text)
        if m_p:
            p_raw = m_p.group(1) or m_p.group(2)
            price_cand = float(p_raw.replace(",", "."))

    if not title_cand:
        for img in [n for n in block.iter_descendants() if n.tag == "img"]:
            alt = (img.attrs.get("alt") or img.attrs.get("title") or "").strip()
            if len(alt) >= 4 and "logo" not in alt.lower():
                title_cand = alt
                break

    if not title_cand:
        lines = [ln.strip() for ln in full_text.split("\n") if ln.strip()]
        for ln in lines:
            if len(ln) >= 4 and ln != codice and not re.match(r'^[\d\.,\s€]+$', ln):
                if not any(ln.lower().startswith(pfx) for pfx in ("cod", "prezzo", "€", "aggiungi", "carrello")):
                    title_cand = ln
                    break

    if not desc_cand:
        lines = [ln.strip() for ln in full_text.split("\n") if ln.strip()]
        desc_parts = [ln for ln in lines if ln != title_cand and ln != codice and not ln.lower().startswith("aggiungi")]
        if desc_parts:
            desc_cand = " — ".join(desc_parts[:4])[:320]

    # Pulizia finale titolo dal prefisso codice
    if codice and title_cand.startswith(codice):
        title_cand = title_cand[len(codice):].strip(" -–:·")

    return {
        "codice": codice[:40],
        "nome": title_cand[:180],
        "descrizione": (desc_cand or title_cand)[:400],
        "immagine": img_url,
        "marca": marca_cand[:80],
        "categoria": cat_cand[:80],
        "confezionamento": conf_cand[:80],
        "prezzo": price_cand
    }


def parse_pregis_catalog_payload(html_content: str = "", base_url: str = "", raw_text: str = "", items_list=None, default_category: str = "") -> list:
    """Estrae prodotti da HTML/JSON/CSV/Testo Pregis mantenendo associazione codice <-> immagine."""
    extracted = []

    if isinstance(items_list, list) and items_list:
        for obj in items_list:
            if not isinstance(obj, dict):
                continue
            img = str(obj.get("immagine") or obj.get("image") or obj.get("img") or obj.get("foto") or "").strip()
            if img and img.startswith("//"):
                img = "https:" + img
            elif img and base_url and not img.startswith(("http://", "https://", "data:", "/")):
                img = urljoin(base_url, img)
            raw_price = obj.get("prezzo") or obj.get("price")
            p_val = None
            if raw_price not in (None, "", "None"):
                try:
                    m_p = re.search(r'(\d+[\.,]?\d*)', str(raw_price).replace(",", "."))
                    if m_p:
                        p_val = float(m_p.group(1))
                except Exception:
                    pass
            extracted.append({
                "codice": str(obj.get("codice") or obj.get("sku") or obj.get("code") or "").strip(),
                "nome": str(obj.get("nome") or obj.get("titolo") or obj.get("name") or "").strip(),
                "descrizione": str(obj.get("descrizione") or obj.get("description") or obj.get("nome") or "").strip(),
                "immagine": img,
                "marca": str(obj.get("marca") or obj.get("brand") or "").strip(),
                "categoria": str(obj.get("categoria") or obj.get("category") or default_category or "").strip(),
                "confezionamento": str(obj.get("confezionamento") or obj.get("imballo") or obj.get("packaging") or "").strip(),
                "prezzo": p_val
            })
        return extracted

    if html_content and "<" in html_content:
        builder = _PregisDOMBuilder()
        builder.feed(html_content)
        builder.close()

        # 1. Controlla prima eventuali JSON-LD di Schema.org Product
        for raw_ld in builder.ld_json_blocks:
            try:
                ld = json.loads(raw_ld)
                objs = ld if isinstance(ld, list) else (ld.get("@graph") or [ld])
                for o in objs:
                    if isinstance(o, dict) and o.get("@type") in ("Product", "MenuItem"):
                        img_ld = o.get("image")
                        if isinstance(img_ld, list):
                            img_ld = img_ld[0]
                        elif isinstance(img_ld, dict):
                            img_ld = img_ld.get("url")
                        brand_ld = o.get("brand")
                        if isinstance(brand_ld, dict):
                            brand_ld = brand_ld.get("name", "")
                        offers = o.get("offers") or {}
                        if isinstance(offers, list):
                            offers = offers[0] if offers else {}
                        prz_ld = offers.get("price") if isinstance(offers, dict) else None
                        try:
                            prz_ld = float(str(prz_ld).replace(",", ".")) if prz_ld else None
                        except Exception:
                            prz_ld = None
                        extracted.append({
                            "codice": str(o.get("sku") or o.get("mpn") or o.get("gtin13") or "").strip(),
                            "nome": str(o.get("name") or "").strip(),
                            "descrizione": str(o.get("description") or o.get("name") or "").strip(),
                            "immagine": urljoin(base_url, str(img_ld or "")) if (base_url and img_ld) else str(img_ld or ""),
                            "marca": str(brand_ld or "").strip(),
                            "categoria": str(o.get("category") or default_category or "").strip(),
                            "confezionamento": "",
                            "prezzo": prz_ld
                        })
            except Exception:
                pass

        # 2. Scansiona card/righe DOM candidate (priorità alle card esatte .onSalesSmart .product-card / .suggestion-item)
        exact_cards = []
        candidate_nodes = []
        for node in builder.root.iter_descendants():
            if node.tag not in ("div", "article", "li", "tr", "section", "a"):
                continue
            cls_low = (node.attrs.get("class", "") + " " + node.attrs.get("itemtype", "")).lower()
            cls_tokens = set(cls_low.split())
            if "product-card" in cls_tokens or "product-card-tile" in cls_tokens or "product-card-row" in cls_tokens or "suggestion-item" in cls_tokens:
                exact_cards.append(node)
                continue
            if node.tag == "a":
                continue
            has_prod_hint = any(k in cls_low for k in ("prod", "item", "card", "art", "box", "sku", "offerta", "scheda")) or bool(node.attrs.get("data-sku") or node.attrs.get("data-codice"))
            if node.tag == "tr" or has_prod_hint:
                img_count = sum(1 for d in node.iter_descendants() if d.tag == "img" and _is_valid_product_img_url(d.attrs.get("src", "") or d.attrs.get("data-src", "")))
                bg_count = sum(1 for d in node.iter_descendants() if "url(" in (d.attrs.get("style", "")).lower())
                nested_cards = sum(1 for d in node.iter_descendants() if d is not node and any(k in d.attrs.get("class", "").lower() for k in ("product-card", "product-item", "card-product", "scheda-prodotto")))
                if nested_cards <= 1 and (img_count >= 1 or bg_count >= 1 or has_prod_hint or node.tag == "tr"):
                    candidate_nodes.append(node)

        for blk in (exact_cards if exact_cards else candidate_nodes):
            item = _extract_product_from_dom_block(blk, base_url=base_url, default_cat=default_category)
            if item.get("nome") or item.get("codice"):
                if item.get("immagine") or item.get("codice"):
                    extracted.append(item)

    # 3. Fallback da testo semplice / incollato (righe con codice + nome)
    if not extracted and raw_text:
        for raw_ln in raw_text.splitlines():
            ln = raw_ln.strip()
            if len(ln) < 4:
                continue
            m_p = re.search(r'(\d+[\.,]\d{2})', ln)
            prz = float(m_p.group(1).replace(",", ".")) if m_p else None
            ln_clean = re.sub(r'€?\s*\d+[\.,]\d{2}', '', ln).strip(" -–•\t")
            m_c = re.match(r'^([A-Z0-9\.\-\/]{3,16})\s+(.+)$', ln_clean, re.IGNORECASE)
            if m_c:
                extracted.append({
                    "codice": m_c.group(1).strip(),
                    "nome": m_c.group(2).strip(),
                    "descrizione": m_c.group(2).strip(),
                    "immagine": "",
                    "marca": "",
                    "categoria": default_category,
                    "confezionamento": "",
                    "prezzo": prz
                })

    return extracted


def _verify_and_clean_products(raw_items: list) -> dict:
    """Verifica duplicati, prodotti senza immagini e anomalie prima della conferma importazione."""
    dedup = {}
    ordered_keys = []
    duplicati_rimossi = 0
    errori_estrazione = 0
    warnings = []

    for idx, it in enumerate(raw_items or []):
        codice = str(it.get("codice") or "").strip()
        nome = re.sub(r'\s+', ' ', html_mod.unescape(str(it.get("nome") or ""))).strip()
        descrizione = re.sub(r'\s+', ' ', html_mod.unescape(str(it.get("descrizione") or nome))).strip()
        immagine = str(it.get("immagine") or "").strip()
        marca = str(it.get("marca") or "").strip()
        categoria = str(it.get("categoria") or "").strip()
        confezionamento = str(it.get("confezionamento") or "").strip()
        prezzo = it.get("prezzo")

        if not codice and (not nome or len(nome) < 2):
            errori_estrazione += 1
            if len(warnings) < 25:
                warnings.append(f"Riga #{idx + 1}: record incompleto (mancano sia codice sia nome).")
            continue

        if not nome and codice:
            nome = f"Articolo {codice}"
            if len(warnings) < 25:
                warnings.append(f"Codice {codice}: nome prodotto non rilevato nella pagina.")

        key = f"C:{codice.upper()}" if codice else f"N:{nome.upper()}"
        clean_rec = {
            "codice": codice,
            "nome": nome,
            "descrizione": descrizione or nome,
            "immagine": immagine,
            "marca": marca,
            "categoria": categoria or "Catalogo Pregis",
            "confezionamento": confezionamento,
            "prezzo": prezzo
        }

        if key in dedup:
            duplicati_rimossi += 1
            prev = dedup[key]
            # Merge: preserva sempre l'associazione con l'immagine o i metadati più completi
            if not prev["immagine"] and clean_rec["immagine"]:
                prev["immagine"] = clean_rec["immagine"]
            if len(clean_rec["descrizione"]) > len(prev["descrizione"]):
                prev["descrizione"] = clean_rec["descrizione"]
            if not prev["marca"] and clean_rec["marca"]:
                prev["marca"] = clean_rec["marca"]
            if not prev["confezionamento"] and clean_rec["confezionamento"]:
                prev["confezionamento"] = clean_rec["confezionamento"]
            if prev["prezzo"] is None and clean_rec["prezzo"] is not None:
                prev["prezzo"] = clean_rec["prezzo"]
            if (not prev["categoria"] or prev["categoria"] == "Catalogo Pregis") and clean_rec["categoria"]:
                prev["categoria"] = clean_rec["categoria"]
        else:
            dedup[key] = clean_rec
            ordered_keys.append(key)

    valid_list = [dedup[k] for k in ordered_keys]
    missing_img = [p for p in valid_list if not p.get("immagine")]
    categories = sorted({p["categoria"] for p in valid_list if p.get("categoria")})

    return {
        "stats": {
            "totale_estratti": len(raw_items or []),
            "totale_validi_unici": len(valid_list),
            "duplicati_rimossi": duplicati_rimossi,
            "con_immagine": len(valid_list) - len(missing_img),
            "senza_immagine": len(missing_img),
            "errori_estrazione": errori_estrazione,
            "categorie_rilevate": categories,
            "warnings": warnings,
            "codici_senza_immagine": [p.get("codice") or p.get("nome") for p in missing_img[:30]],
        },
        "preview_20": valid_list[:20],
        "all_products": valid_list
    }


PREGIS_QP_BASE = "https://tua.pregis.it/QueryPoint"
PREGIS_APP_BASE = "https://tua.pregis.it/onSalesSmart/"
PREGIS_QP_HEADERS = {
    "Accept": "application/json; charset=UTF-8",
    "Cache-Control": "no-cache",
    "Cache-control": "no-store",
    "Expires": "0",
    "Pragma": "no-cache",
    "Content-Type": "application/json; charset=UTF-8",
    "Require-Content-Type": "application/json",
    "timeout": "60000",
    "Origin": "https://tua.pregis.it",
    "Referer": "https://tua.pregis.it/onSalesSmart/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def _pregis_qp_post(sess: requests.Session, endpoint: str, payload: dict, timeout: int = 18) -> dict:
    """Invia una POST in sola lettura verso QueryPoint parsificando sempre il JSON di risposta Pregis."""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    r = sess.post(f"{PREGIS_QP_BASE}/{endpoint}", json=payload, headers=PREGIS_QP_HEADERS, verify=False, timeout=timeout)
    try:
        data = r.json()
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    if r.status_code >= 400:
        raise ValueError(f"Errore HTTP {r.status_code} da Pregis ({endpoint}): {r.text[:220]}")
    raise ValueError(f"Risposta non valida da Pregis ({endpoint}).")


def _pregis_resolve_img(images_list) -> str:
    if not isinstance(images_list, list):
        return ""
    for im in images_list:
        if not isinstance(im, dict):
            continue
        cand = (im.get("imagePath") or im.get("thumbnailPath") or im.get("imageId") or "").strip()
        if not cand or "missing_image_catalogue" in cand.lower():
            continue
        if cand.startswith("//"):
            return "https:" + cand
        if cand.startswith(("http://", "https://", "data:")):
            return cand
        if cand.startswith("/"):
            return "https://tua.pregis.it" + cand
        return urljoin(PREGIS_APP_BASE, cand)
    return ""


def _map_pregis_onsales_item(raw_it: dict, lookups: dict, cat_label: str = "") -> dict:
    codice = str(raw_it.get("itemCode") or raw_it.get("itemId") or "").strip()
    desc1 = str(raw_it.get("itemDesc") or "").strip()
    desc2 = str(raw_it.get("itemInfo") or "").strip()
    vdesc = str(raw_it.get("variantDesc") or "").strip()
    nome = desc1 or vdesc or desc2 or codice
    full_desc = " — ".join([p for p in dict.fromkeys([desc1, desc2, vdesc]) if p])

    brand_id = str(raw_it.get("brandId") or "").strip()
    marca = str(raw_it.get("brand") or (lookups.get("BRAND") or {}).get(brand_id) or brand_id).strip()

    g1_lbl = (lookups.get("G1") or {}).get(str(raw_it.get("group1Id") or "")) or ""
    g2_lbl = (lookups.get("G2") or {}).get(str(raw_it.get("group2Id") or "")) or ""
    g3_lbl = (lookups.get("G3") or {}).get(str(raw_it.get("group3Id") or "")) or ""
    it_cat = " / ".join([x for x in (g1_lbl, g2_lbl, g3_lbl) if x]) or cat_label or "Catalogo Pregis"

    uv_map = lookups.get("UV") or {}
    uv_code = str(raw_it.get("baseUnitDescId") or "").strip()
    uv_lbl = uv_map.get(uv_code) or uv_code
    units_desc = []
    for u in (raw_it.get("sellingItemUnits") or []):
        uid = str(u.get("unitId") or "")
        u_name = uv_map.get(uid) or uid
        cf = u.get("convFactor")
        try:
            cf_num = float(cf) if cf is not None else 0
        except Exception:
            cf_num = 0
        if u_name:
            units_desc.append(f"{u_name} ({cf})" if cf_num > 0 else u_name)
    wt = raw_it.get("weight") or raw_it.get("grossWeight")
    conf = " / ".join(dict.fromkeys([x for x in ([uv_lbl] + units_desc) if x]))
    if wt:
        conf = f"{conf} · Peso {wt}" if conf else f"Peso {wt}"

    prz_raw = raw_it.get("basePrice") or raw_it.get("baseNetPrice") or raw_it.get("pricePerUnitKgLt")
    prezzo = None
    if prz_raw not in (None, "", 0, "0"):
        try:
            prezzo = round(float(prz_raw), 2)
        except Exception:
            prezzo = None

    return {
        "codice": codice,
        "nome": nome,
        "descrizione": full_desc or nome,
        "immagine": _pregis_resolve_img(raw_it.get("images")),
        "marca": marca,
        "categoria": it_cat,
        "confezionamento": conf,
        "prezzo": prezzo,
    }


def _pregis_ensure_assortment(sess: requests.Session, sid: str, cart_obj=None) -> bool:
    """Inizializza l'assortimento catalogo (sola lettura) tramite Smart.DeliveryPlace + Smart.CreateAssortment."""
    dp_id = (cart_obj or {}).get("deliveryPlaceId") if isinstance(cart_obj, dict) else None
    pos_id = (cart_obj or {}).get("pointOfSaleId") if isinstance(cart_obj, dict) else None
    ds_id = (cart_obj or {}).get("deliveryServiceId") if isinstance(cart_obj, dict) else None

    try:
        dp_res = _pregis_qp_post(sess, "Smart.DeliveryPlace.door", {"sessionId": sid, "data": None})
        dp_data = dp_res.get("data") or {}
        if dp_res.get("status") in (None, "OK"):
            dp_list = dp_data.get("deliveryPlaceList") or []
            last_dp = (dp_data.get("lastDeliveryPlaceId") or "").strip() or None
            last_pos = (dp_data.get("lastPointOfSaleId") or "").strip() or None
            last_ds = (dp_data.get("lastDeliveryServiceId") or "").strip() or None
            first_dp = dp_list[0].get("contactId") if dp_list and isinstance(dp_list[0], dict) else None
            dp_id = last_dp or dp_id or first_dp
            pos_id = last_pos or pos_id
            ds_id = last_ds or ds_id
    except Exception as e:
        print(f"⚠️ Pregis DeliveryPlace warning: {e}")

    if not dp_id:
        return False

    try:
        ca_res = _pregis_qp_post(sess, "Smart.CreateAssortment.door", {
            "sessionId": sid,
            "data": {
                "deliveryPlaceId": dp_id,
                "pointOfSaleId": pos_id,
                "deliveryServiceId": ds_id,
                "deliveryDate": None,
            }
        })
        if ca_res.get("status") in (None, "OK"):
            return True
        if pos_id or ds_id:
            ca_res2 = _pregis_qp_post(sess, "Smart.CreateAssortment.door", {
                "sessionId": sid,
                "data": {
                    "deliveryPlaceId": dp_id,
                    "pointOfSaleId": None,
                    "deliveryServiceId": None,
                    "deliveryDate": None,
                }
            })
            return ca_res2.get("status") in (None, "OK")
    except Exception as e:
        print(f"⚠️ Pregis CreateAssortment warning: {e}")
    return False


def _pregis_init_session_and_assortment(session_id: str = "", username: str = "", password: str = "", cookies_dict=None):
    """Autentica (o riusa Session ID), inizializza AppSetup + Assortment, e carica lookup e categorie."""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    sess = requests.Session()
    if isinstance(cookies_dict, dict):
        for ck, cv in cookies_dict.items():
            if ck and cv is not None:
                sess.cookies.set(str(ck), str(cv), domain="tua.pregis.it")

    sid = (session_id or "").strip()
    if username and password and not sid:
        login_res = _pregis_qp_post(sess, "Smart.Login.door", {
            "sessionId": None,
            "data": {"username": username.strip(), "password": password, "languageId": "it"}
        })
        if login_res.get("status") != "OK":
            msg = login_res.get("message") or login_res.get("status") or "Credenziali Pregis non valide"
            raise ValueError(f"Login Pregis rifiutato: {msg}")
        sid = (login_res.get("data") or {}).get("sessionId") or ""

    if not sid:
        raise ValueError("Inserisci Username e Password Pregis oppure il Session ID della sessione Chrome.")

    # 1. AppSetup (inizializza profilo utente e verifica validità sessione)
    cart_obj = None
    try:
        setup_res = _pregis_qp_post(sess, "Smart.AppSetup.door", {"sessionId": sid, "data": {"languageId": "it"}})
        if setup_res.get("status") not in (None, "OK"):
            err_st = str(setup_res.get("status") or "")
            err_msg = str(setup_res.get("message") or err_st)
            if any(tok in (err_st + " " + err_msg).upper() for tok in ("UNAUTH", "INVALID_SESSION", "EXPIRED", "ERR_NO_AUTH")):
                raise ValueError(f"Session ID Pregis non valido o scaduto ({err_msg}). Usa Username e Password.")
        cart_obj = (setup_res.get("data") or {}).get("cart")
    except ValueError:
        raise
    except Exception as e:
        print(f"⚠️ Pregis AppSetup warning: {e}")

    # 2. Scarica lookup tabelle (G1, G2, G3, BRAND, UV)
    lookups = {"G1": {}, "G2": {}, "G3": {}, "BRAND": {}, "UV": {}}
    try:
        lk_res = _pregis_qp_post(sess, "Smart.GetDescriptionLookup.door", {"sessionId": sid, "data": {"languageId": "it"}})
        for row in ((lk_res.get("data") or {}).get("descriptionLookupList") or []):
            tname = row.get("tableName")
            if tname in lookups:
                lookups[tname][str(row.get("tableItemId"))] = str(row.get("tableItemDesc") or "").strip()
    except Exception as e:
        print(f"⚠️ Pregis GetDescriptionLookup warning: {e}")

    # 3. Scarica filtri catalogo (e se l'assortimento non è inizializzato, esegue DeliveryPlace + CreateAssortment)
    flt_payload = {
        "sessionId": sid,
        "data": {
            "itemFilter": {"textFilter": "", "groupIds": None, "attributes": None, "tagIds": [], "filterId": None, "communicationId": None},
            "scope": "allProducts"
        }
    }
    flt_res = _pregis_qp_post(sess, "Smart.GetCatalogFilters.door", flt_payload)
    if flt_res.get("status") not in (None, "OK"):
        st_str = str(flt_res.get("status") or "")
        if "ASSORTMENT" in st_str.upper() or "EMPTY" in st_str.upper() or _pregis_ensure_assortment(sess, sid, cart_obj=cart_obj):
            _pregis_ensure_assortment(sess, sid, cart_obj=cart_obj)
            flt_res = _pregis_qp_post(sess, "Smart.GetCatalogFilters.door", flt_payload)
    else:
        # Se già OK, verifica comunque se groups è vuoto (assortimento non ancora aperto sulla sessione)
        if not ((flt_res.get("data") or {}).get("groups")):
            if _pregis_ensure_assortment(sess, sid, cart_obj=cart_obj):
                flt_res = _pregis_qp_post(sess, "Smart.GetCatalogFilters.door", flt_payload)

    if flt_res.get("status") not in (None, "OK"):
        err_msg = flt_res.get("message") or flt_res.get("status")
        if "invalid session" in str(err_msg).lower() or "unauth" in str(err_msg).lower():
            raise ValueError("Session ID Pregis non valido o scaduto. Accedi con Username e Password.")
        print(f"⚠️ Pregis GetCatalogFilters status: {err_msg}")

    group_tasks = []

    def walk_groups(nodes, level=1, parent_ids=None, parent_labels=None):
        parent_ids = parent_ids or {}
        parent_labels = parent_labels or []
        for g in (nodes or []):
            fid = g.get("filterId")
            cnt = g.get("count")
            if not fid or (cnt is not None and cnt == 0):
                continue
            g_map = lookups.get(f"G{level}", {})
            g_label = g.get("description") or g_map.get(str(fid)) or f"Categoria {fid}"
            curr_ids = dict(parent_ids)
            curr_ids[f"group{level}id"] = str(fid)
            curr_labels = parent_labels + [g_label]
            subs = [s for s in (g.get("subfilters") or []) if (s.get("count") is None or s.get("count", 0) > 0)]
            if subs:
                walk_groups(subs, level + 1, curr_ids, curr_labels)
            else:
                group_tasks.append({"group_ids": curr_ids, "label": " / ".join(curr_labels), "count": cnt or 0})

    walk_groups(((flt_res.get("data") or {}).get("groups") or []))
    for b in ((flt_res.get("data") or {}).get("brands") or []):
        bid = b.get("filterId")
        blbl = b.get("description") or b.get("filterDesc")
        if bid and blbl and str(bid) not in lookups["BRAND"]:
            lookups["BRAND"][str(bid)] = str(blbl).strip()

    return sess, sid, lookups, group_tasks, sess.cookies.get_dict()


def _pregis_fetch_pages_chunk(
    sess: requests.Session,
    sid: str,
    lookups: dict,
    group_ids=None,
    cat_label: str = "Catalogo Pregis",
    start_page: int = 0,
    page_order: str = "",
    page_size: int = 50,
    max_pages: int = 5,
):
    """Scarica un piccolo lotto di pagine da Smart.GetItems.door (a prova di timeout su Render)."""
    items = []
    curr_page = max(0, int(start_page or 0))
    curr_order = page_order or ""
    last_page = False
    eff_size = max(10, min(100, int(page_size or 50)))

    for i in range(max_pages):
        res = _pregis_qp_post(sess, "Smart.GetItems.door", {
            "sessionId": sid,
            "data": {
                "itemFilter": {
                    "textFilter": None,
                    "groupIds": group_ids,
                    "attributes": None,
                    "tagIds": [],
                    "communicationId": None,
                },
                "pageNumber": curr_page,
                "pageSize": eff_size,
                "pageOrder": curr_order,
            }
        })
        st = res.get("status")
        if st not in (None, "OK"):
            msg = str(res.get("message") or st or "")
            if "invalid session" in msg.lower() or "unauth" in msg.lower():
                raise ValueError(f"Sessione Pregis scaduta: {msg}")
            if "assortment" in msg.lower() and i == 0:
                if _pregis_ensure_assortment(sess, sid):
                    continue
            if eff_size != 20 and curr_page == 0 and i == 0:
                eff_size = 20
                continue
            raise ValueError(f"Pregis Smart.GetItems.door ha risposto '{st}': {msg}")

        body_data = res.get("data") or {}
        item_list = body_data.get("itemList") or []
        if not item_list:
            last_page = True
            break

        for it in item_list:
            items.append(_map_pregis_onsales_item(it, lookups, cat_label))
            for var in (it.get("variants") or []):
                if isinstance(var, dict) and str(var.get("itemId") or "") != str(it.get("itemId") or ""):
                    items.append(_map_pregis_onsales_item(var, lookups, cat_label))

        curr_order = body_data.get("pageOrder") or ""
        curr_page += 1
        if body_data.get("lastPage"):
            last_page = True
            break

    return {
        "items": items,
        "next_page": curr_page,
        "page_order": curr_order,
        "last_page": last_page,
        "page_size_used": eff_size,
    }


def crawl_tua_pregis_onsales(session_id: str = "", username: str = "", password: str = "", max_pages_per_group: int = 40, time_budget_sec: float = 22.0) -> list:
    """Connettore in SOLA LETTURA per portale Pregis .onSales B2B (con budget anti-timeout)."""
    t0 = time.time()
    sess, sid, lookups, group_tasks, _ = _pregis_init_session_and_assortment(
        session_id=session_id,
        username=username,
        password=password,
    )

    collected = []
    # Prima esegue sempre la scansione globale (groupIds=None) molto più veloce e completa
    page_num = 0
    page_order = ""
    page_size = 50
    for _ in range(120):
        if time.time() - t0 > time_budget_sec:
            break
        chunk = _pregis_fetch_pages_chunk(
            sess=sess,
            sid=sid,
            lookups=lookups,
            group_ids=None,
            cat_label="Catalogo Pregis",
            start_page=page_num,
            page_order=page_order,
            page_size=page_size,
            max_pages=4,
        )
        collected.extend(chunk["items"])
        page_num = chunk["next_page"]
        page_order = chunk["page_order"]
        page_size = chunk["page_size_used"]
        if chunk["last_page"]:
            break

    # Se la scansione globale fosse rimasta vuota, ripiega sulle singole foglie categoria
    if not collected and group_tasks:
        for grp in group_tasks:
            if time.time() - t0 > time_budget_sec:
                break
            g_page = 0
            g_order = ""
            for _ in range(max_pages_per_group):
                if time.time() - t0 > time_budget_sec:
                    break
                chunk = _pregis_fetch_pages_chunk(
                    sess=sess,
                    sid=sid,
                    lookups=lookups,
                    group_ids=grp["group_ids"],
                    cat_label=grp["label"],
                    start_page=g_page,
                    page_order=g_order,
                    page_size=50,
                    max_pages=2,
                )
                collected.extend(chunk["items"])
                g_page = chunk["next_page"]
                g_order = chunk["page_order"]
                if chunk["last_page"]:
                    break

    return collected


@volantini3_bp.route("/api/catalogo/pregis-init", methods=["POST"])
def api_catalogo_pregis_init():
    """Inizializza la sessione sola lettura su tua.pregis.it (Login -> AppSetup -> Assortment -> Filtri)."""
    if not session.get("logged_in"):
        return jsonify({"ok": False, "error": "Non autorizzato"}), 401
    data = request.get_json(silent=True) or {}
    u = (data.get("pregis_username") or "").strip()
    p = data.get("pregis_password") or ""
    sid = (data.get("pregis_session_id") or "").strip()
    try:
        _, final_sid, lookups, groups, cookies_dict = _pregis_init_session_and_assortment(
            session_id=sid,
            username=u,
            password=p,
        )
        return jsonify({
            "ok": True,
            "session_id": final_sid,
            "lookups": lookups,
            "groups": groups,
            "cookies": cookies_dict,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@volantini3_bp.route("/api/catalogo/pregis-fetch-batch", methods=["POST"])
def api_catalogo_pregis_fetch_batch():
    """Scarica fino a 5 pagine di Smart.GetItems.door alla volta (nessun timeout su Render)."""
    if not session.get("logged_in"):
        return jsonify({"ok": False, "error": "Non autorizzato"}), 401
    data = request.get_json(silent=True) or {}
    sid = (data.get("session_id") or "").strip()
    if not sid:
        return jsonify({"ok": False, "error": "Session ID mancante"}), 400

    lookups = data.get("lookups") or {"G1": {}, "G2": {}, "G3": {}, "BRAND": {}, "UV": {}}
    group_ids = data.get("group_ids")
    cat_label = (data.get("category_label") or "Catalogo Pregis").strip()
    start_page = int(data.get("start_page") or 0)
    page_order = data.get("page_order") or ""
    page_size = int(data.get("page_size") or 50)
    max_pages = max(1, min(6, int(data.get("max_pages") or 5)))
    cookies_dict = data.get("cookies") if isinstance(data.get("cookies"), dict) else {}

    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        sess = requests.Session()
        for ck, cv in cookies_dict.items():
            if ck and cv is not None:
                sess.cookies.set(str(ck), str(cv), domain="tua.pregis.it")
        res = _pregis_fetch_pages_chunk(
            sess=sess,
            sid=sid,
            lookups=lookups,
            group_ids=group_ids,
            cat_label=cat_label,
            start_page=start_page,
            page_order=page_order,
            page_size=page_size,
            max_pages=max_pages,
        )
        return jsonify({"ok": True, "cookies": sess.cookies.get_dict(), **res})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


def _fetch_public_catalog_multi_page(start_url: str, max_pages: int = 18) -> list:
    """Esegue solo richieste GET in sola lettura su pagine/categorie pubbliche accessibili dall'URL."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15"
    }
    visited = set()
    queue = [start_url]
    parsed_start = urlparse(start_url)
    base_host = parsed_start.netloc
    collected = []

    while queue and len(visited) < max_pages:
        curr_url = queue.pop(0)
        if curr_url in visited:
            continue
        visited.add(curr_url)
        try:
            resp = requests.get(curr_url, headers=headers, timeout=12)
            if resp.status_code != 200 or "text/html" not in resp.headers.get("Content-Type", "").lower():
                continue
            page_html = resp.text
            items = parse_pregis_catalog_payload(html_content=page_html, base_url=curr_url)
            collected.extend(items)

            # Cerca link di paginazione o sottocategorie dello stesso catalogo (solo GET)
            builder = _PregisDOMBuilder()
            builder.feed(page_html)
            builder.close()
            for a in builder.root.iter_descendants():
                if a.tag != "a":
                    continue
                href = a.attrs.get("href", "").strip()
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                abs_u = urljoin(curr_url, href)
                pu = urlparse(abs_u)
                if pu.netloc != base_host:
                    continue
                low_u = abs_u.lower()
                if any(tok in low_u for tok in ("page=", "/page/", "categ", "catalog", "prodott", "p=")):
                    if abs_u not in visited and abs_u not in queue and len(queue) < 40:
                        queue.append(abs_u)
        except Exception as e:
            print(f"⚠️ Catalog GET warning ({curr_url}): {e}")

    return collected


@volantini3_bp.route("/api/salva_immagine_db", methods=["POST"])
def api_salva_immagine_db_alias():
    """Alias usato da Volantini 3.0 per associare la foto scelta direttamente al prodotto in DB."""
    if not session.get("logged_in"):
        return jsonify({"status": "error", "message": "Non autorizzato"}), 401
    from flask import current_app
    view_fn = current_app.view_functions.get("api_salva_immagine_volantino_prodotto")
    if view_fn:
        return view_fn()
    return jsonify({"status": "error", "message": "Endpoint immagini non disponibile"}), 500


@volantini3_bp.route("/api/catalogo/analizza-pregis", methods=["POST"])
def api_catalogo_analizza_pregis():
    """Analizza il catalogo (HTML/URL/JSON/CSV/PDF) in sola lettura, verifica duplicati/immagini e restituisce anteprima 20 prodotti."""
    if not session.get("logged_in"):
        return jsonify({"ok": False, "error": "Non autorizzato"}), 401

    raw_items = []
    source_url = ""
    html_text = ""
    raw_text = ""
    default_cat = ""
    pregis_user = ""
    pregis_pass = ""
    pregis_sid = ""

    if request.is_json:
        payload = request.get_json(silent=True) or {}
        source_url = (payload.get("url") or payload.get("base_url") or "").strip()
        html_text = (payload.get("html") or "").strip()
        raw_text = (payload.get("raw_text") or "").strip()
        default_cat = (payload.get("default_categoria") or "").strip()
        pregis_user = (payload.get("pregis_username") or "").strip()
        pregis_pass = payload.get("pregis_password") or ""
        pregis_sid = (payload.get("pregis_session_id") or "").strip()
        items_json = payload.get("items") or payload.get("prodotti")
        if isinstance(items_json, list):
            raw_items.extend(parse_pregis_catalog_payload(base_url=source_url, items_list=items_json, default_category=default_cat))
    else:
        source_url = (request.form.get("url") or request.form.get("base_url") or "").strip()
        html_text = (request.form.get("html") or "").strip()
        raw_text = (request.form.get("raw_text") or "").strip()
        default_cat = (request.form.get("default_categoria") or "").strip()
        pregis_user = (request.form.get("pregis_username") or "").strip()
        pregis_pass = request.form.get("pregis_password") or ""
        pregis_sid = (request.form.get("pregis_session_id") or "").strip()
        items_str = (request.form.get("items_json") or "").strip()
        if items_str:
            try:
                parsed_js = json.loads(items_str)
                if isinstance(parsed_js, list):
                    raw_items.extend(parse_pregis_catalog_payload(base_url=source_url, items_list=parsed_js, default_category=default_cat))
            except Exception:
                pass

        f = request.files.get("file")
        if f and f.filename:
            ext = os.path.splitext(f.filename)[1].lower()
            content_bytes = f.read()
            if ext in (".html", ".htm", ".txt"):
                html_text = content_bytes.decode("utf-8", errors="ignore")
            elif ext == ".json":
                try:
                    loaded = json.loads(content_bytes.decode("utf-8", errors="ignore"))
                    arr = loaded if isinstance(loaded, list) else (loaded.get("prodotti") or loaded.get("all_products") or loaded.get("items") or [])
                    raw_items.extend(parse_pregis_catalog_payload(base_url=source_url, items_list=arr, default_category=default_cat))
                except Exception as e:
                    return jsonify({"ok": False, "error": f"JSON non valido: {e}"}), 400
            elif ext == ".csv":
                try:
                    text_csv = content_bytes.decode("utf-8-sig", errors="ignore")
                    reader = csv.DictReader(io.StringIO(text_csv))
                    csv_rows = [dict(r) for r in reader]
                    raw_items.extend(parse_pregis_catalog_payload(base_url=source_url, items_list=csv_rows, default_category=default_cat))
                except Exception as e:
                    return jsonify({"ok": False, "error": f"CSV non valido: {e}"}), 400
            elif ext == ".pdf" and _EXTRACT_PDF_FN:
                tmp_path = os.path.join(tempfile.gettempdir(), f"cat_{int(time.time())}_{werkzeug.utils.secure_filename(f.filename)}")
                with open(tmp_path, "wb") as wf:
                    wf.write(content_bytes)
                try:
                    pdf_items = _EXTRACT_PDF_FN(tmp_path)
                    raw_items.extend(parse_pregis_catalog_payload(items_list=pdf_items, default_category=default_cat))
                finally:
                    if os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass

    if not raw_items and (pregis_sid or (pregis_user and pregis_pass)):
        try:
            raw_items.extend(crawl_tua_pregis_onsales(
                session_id=pregis_sid,
                username=pregis_user,
                password=pregis_pass,
            ))
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
    elif not raw_items and (html_text or raw_text):
        raw_items.extend(parse_pregis_catalog_payload(
            html_content=html_text,
            base_url=source_url,
            raw_text=raw_text,
            default_category=default_cat
        ))
    elif not raw_items and source_url:
        if "tua.pregis.it" in source_url.lower() and not (pregis_sid or (pregis_user and pregis_pass)):
            return jsonify({
                "ok": False,
                "error": "Il portale tua.pregis.it/onSalesSmart richiede autenticazione. Inserisci Username e Password (o il Session ID) nel riquadro Pregis, oppure esegui lo script auto-scanner direttamente nella Console della tua scheda aperta."
            }), 400
        raw_items.extend(_fetch_public_catalog_multi_page(source_url))

    verification = _verify_and_clean_products(raw_items)
    if verification["stats"]["totale_validi_unici"] == 0:
        return jsonify({
            "ok": False,
            "error": "Nessun prodotto rilevato dal contenuto fornito. Se il catalogo Pregis su Safari è protetto da login, usa lo Script Auto-Scanner Safari o copia la pagina da Safari e incollala nel riquadro."
        }), 400

    return jsonify({
        "ok": True,
        **verification
    })


@volantini3_bp.route("/api/catalogo/importa-pregis-confermato", methods=["POST"])
def api_catalogo_importa_pregis_confermato():
    """Importazione una tantum nel catalogo del sito dopo conferma utente."""
    if not session.get("logged_in"):
        return jsonify({"ok": False, "error": "Non autorizzato"}), 401

    data = request.get_json(silent=True) or {}
    products = data.get("prodotti") or []
    forced_cat_id = data.get("categoria_id")
    nuova_categoria = (data.get("nuova_categoria") or "").strip()

    if not products:
        return jsonify({"ok": False, "error": "Nessun prodotto da importare"}), 400

    inseriti = 0
    aggiornati = 0
    categorie_create = 0

    try:
        with _GET_DB() as conn:
            _ensure_prodotti_catalog_columns(conn)
            cur = conn.cursor()

            # Cache categorie esistenti
            cur.execute("SELECT id, nome FROM categorie")
            cat_cache = {str(r["nome"]).strip().lower(): r["id"] for r in cur.fetchall()}

            def get_or_create_cat_id(cat_name: str):
                nonlocal categorie_create
                cn = (cat_name or "").strip()
                if not cn:
                    return None
                k = cn.lower()
                if k in cat_cache:
                    return cat_cache[k]
                cur.execute("INSERT INTO categorie (nome) VALUES (%s) RETURNING id", (cn,))
                row_c = cur.fetchone()
                new_cid = (row_c["id"] if isinstance(row_c, dict) else row_c[0]) if row_c else getattr(cur, "lastrowid", None)
                cat_cache[k] = new_cid
                categorie_create += 1
                return new_cid

            if nuova_categoria:
                forced_cat_id = get_or_create_cat_id(nuova_categoria)
            elif forced_cat_id:
                try:
                    forced_cat_id = int(forced_cat_id)
                except Exception:
                    forced_cat_id = None

            # Carica indice prodotti esistenti
            cur.execute("SELECT id, codice, nome, immagine FROM prodotti WHERE COALESCE(eliminato, FALSE) = FALSE")
            by_code = {}
            by_name = {}
            for r in cur.fetchall():
                d = dict(r)
                if d.get("codice"):
                    by_code[str(d["codice"]).strip().upper()] = d
                if d.get("nome"):
                    by_name[str(d["nome"]).strip().upper()] = d

            for p in products:
                codice = str(p.get("codice") or "").strip()
                nome = str(p.get("nome") or "").strip()
                if not nome and not codice:
                    continue
                if not nome:
                    nome = f"Articolo {codice}"

                descrizione = str(p.get("descrizione") or nome).strip()
                immagine = str(p.get("immagine") or "").strip()
                marca = str(p.get("marca") or "").strip()
                confezionamento = str(p.get("confezionamento") or "").strip()
                prezzo = p.get("prezzo")
                try:
                    prezzo = float(str(prezzo).replace(",", ".")) if prezzo not in (None, "") else None
                except Exception:
                    prezzo = None

                cat_id = forced_cat_id if forced_cat_id else get_or_create_cat_id(p.get("categoria") or "Catalogo Pregis")

                existing = (by_code.get(codice.upper()) if codice else None) or by_name.get(nome.upper())
                if existing:
                    cur.execute("""
                        UPDATE prodotti
                        SET nome = %s,
                            codice = COALESCE(NULLIF(%s, ''), codice),
                            descrizione = COALESCE(NULLIF(%s, ''), descrizione),
                            immagine = COALESCE(NULLIF(%s, ''), immagine),
                            marca = COALESCE(NULLIF(%s, ''), marca),
                            confezionamento = COALESCE(NULLIF(%s, ''), confezionamento),
                            prezzo = COALESCE(%s, prezzo),
                            categoria_id = COALESCE(%s, categoria_id)
                        WHERE id = %s
                    """, (nome, codice, descrizione, immagine, marca, confezionamento, prezzo, cat_id, existing["id"]))
                    aggiornati += 1
                else:
                    cur.execute("""
                        INSERT INTO prodotti (codice, nome, descrizione, immagine, marca, confezionamento, prezzo, categoria_id, eliminato)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE)
                        RETURNING id
                    """, (codice or None, nome, descrizione, immagine or None, marca or None, confezionamento or None, prezzo, cat_id))
                    ins_row = cur.fetchone()
                    new_pid = (ins_row["id"] if isinstance(ins_row, dict) else ins_row[0]) if ins_row else getattr(cur, "lastrowid", None)
                    rec_cache = {"id": new_pid, "codice": codice, "nome": nome, "immagine": immagine}
                    if codice:
                        by_code[codice.upper()] = rec_cache
                    by_name[nome.upper()] = rec_cache
                    inseriti += 1

            conn.commit()

        return jsonify({
            "ok": True,
            "inseriti": inseriti,
            "aggiornati": aggiornati,
            "categorie_create": categorie_create,
            "totale": inseriti + aggiornati,
            "message": f"✅ Importazione completata: {inseriti} nuovi prodotti aggiunti, {aggiornati} aggiornati ({categorie_create} nuove categorie)."
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
