import os
import re
import json
import time
import base64
import tempfile
import requests
import werkzeug.utils
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


def init_volantini_3(app, get_db_fn, extract_pdf_fn, get_openai_cfg_fn=None):
    global _GET_DB, _EXTRACT_PDF_FN, _GET_OPENAI_CFG_FN
    _GET_DB = get_db_fn
    _EXTRACT_PDF_FN = extract_pdf_fn
    _GET_OPENAI_CFG_FN = get_openai_cfg_fn

    try:
        with _GET_DB() as conn:
            cur = conn.cursor()
            _ensure_volantini3_table(cur)
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
            img_url = img_val if (img_val.startswith("http") or img_val.startswith("/")) else f"/static/uploads/volantino_prodotti/{img_val}"

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
                    img_u = f"/static/uploads/volantino_prodotti/{img_v}" if (img_v and not img_v.startswith("http") and not img_v.startswith("/")) else img_v
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
