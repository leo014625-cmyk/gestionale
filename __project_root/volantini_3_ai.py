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

PREGIS_LOGO_URL = "https://us-east-1.tixte.net/uploads/leonardogiorgini.tixte.co/logo-pregis-bordo.png"


def init_volantini_3(app, get_db_fn, extract_pdf_fn, get_openai_cfg_fn=None):
    global _GET_DB, _EXTRACT_PDF_FN, _GET_OPENAI_CFG_FN
    _GET_DB = get_db_fn
    _EXTRACT_PDF_FN = extract_pdf_fn
    _GET_OPENAI_CFG_FN = get_openai_cfg_fn

    try:
        with _GET_DB() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS volantini_3_ai (
                    id SERIAL PRIMARY KEY,
                    titolo TEXT NOT NULL,
                    sottotitolo TEXT,
                    stile TEXT DEFAULT 'pregis_autunno',
                    layout_mode TEXT DEFAULT 'pregis_10',
                    dati_json TEXT NOT NULL,
                    creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    aggiornato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
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
    """Estrae marchio, imballo, badge e genera una micro-descrizione gourmet per la versione abbellita AI."""
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
            fallback_brands = ["Selezione Pregis", "Antica Norcineria", "Maestri Salumieri", "Riserva Pregis", "Gran Tradizione"]
        elif any(k in n_low or k in c_low for k in ["salmone", "polpo", "gamber", "pesce", "ittic", "calamar"]):
            fallback_brands = ["Pregis Mare", "Blue Ocean", "Nordic Superior", "Pescato Scelto"]
        elif any(k in n_low or k in c_low for k in ["angus", "scottona", "manzo", "hamburger", "carne"]):
            fallback_brands = ["Pregis Grill", "Prime Butchery", "Black Label", "Master Beef"]
        else:
            fallback_brands = ["Selezione Pregis", "Alta Qualità Ho.Re.Ca.", "Linea Chef Pregis", "Specialità Gourmet"]
        brand_found = fallback_brands[idx % len(fallback_brands)]

    # Micro-copy gourmet e badge per la modalità AI Beautified
    if any(k in n_low or k in c_low for k in ["prosciutt", "salame", "lonza", "speck", "bresaola", "mortadella", "salum"]):
        copies = [
            "Stagionatura lenta e profumo intenso, resa perfetta al taglio con zero scarto.",
            "Fetta morbida e sapore equilibrato per taglieri, antipasti e pizzerie gourmet.",
            "Ricetta della tradizione norcina italiana selezionata per la ristorazione."
        ]
        badges = ["⭐ SELEZIONE PREGIS", "🔪 ZERO SCARTO", "🇮🇹 ALTA SALUMERIA", "🔥 TOP OFFERTA"]
    elif any(k in n_low or k in c_low for k in ["salmone", "polpo", "gamber", "pesce", "ittic", "calamar", "mazzancoll"]):
        copies = [
            "Surgelazione rapida all'origine per preservare polpa soda e sapore di mare.",
            "Calibro costante e altissima resa in cottura per secondi e antipasti di mare."
        ]
        badges = ["🌊 PREGIS MARE", "❄️ FRESCHEZZA TOP", "⭐ SCELTA CHEF", "💎 PREMIUM"]
    elif any(k in n_low or k in c_low for k in ["angus", "scottona", "manzo", "hamburger", "carne", "pollo", "suin"]):
        copies = [
            "Taglio scelto ad alta marezzatura: tenero, succoso e costante sulla griglia.",
            "Selezionato per steakhouse e ristoranti: tenuta in cottura superiore."
        ]
        badges = ["🔥 SPECIALE GRILL", "🥩 TAGLIO NOBILE", "⭐ TOP STEAKHOUSE", "🔪 ALTA RESA"]
    else:
        copies = [
            "Standard qualitativo superiore garantito da Pregis per i professionisti Ho.Re.Ca.",
            "Prodotto ad alta rotazione con resa ottimale in cucina e massima convenienza."
        ]
        badges = ["⭐ SELEZIONE PREGIS", "🔥 SUPER PROMO", "💎 QUALITÀ EXTRA", "⚡ BEST SELLER"]

    return {
        "titolo_pulito": beautify_product_name(name_clean),
        "brand": brand_found,
        "imballo": imballo,
        "descrizione_ai": copies[idx % len(copies)],
        "badge": badges[idx % len(badges)]
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
    if m_idx in (9, 10, 11):
        stile = "pregis_autunno"
    elif m_idx in (12, 1, 2):
        stile = "pregis_inverno"
    elif m_idx in (6, 7, 8):
        stile = "pregis_mare"
    else:
        stile = "pregis_primavera"
    return f"PROMO {mese_nome}", stile


def call_openai_vision_or_enrich(products: list, user_prompt: str = "", image_b64: str = None):
    if not _GET_OPENAI_CFG_FN:
        return None
    api_key, model = _GET_OPENAI_CFG_FN()
    if not api_key:
        return None

    try:
        if image_b64:
            vision_prompt = """Analizza questa immagine di un volantino prodotti e restituisci ESCLUSIVAMENTE un JSON valido con:
{
  "titolo": "Titolo banner in alto (es. PROMO NOVEMBRE)",
  "prodotti": [
    {
      "codice": "codice articolo es. 40616.002",
      "titolo": "Nome del prodotto pulito",
      "brand": "Marchio o linea in corsivo",
      "imballo": "Testo imballo es. Imballo 5.50 kg",
      "descrizione_ai": "Breve descrizione gastronomica accattivante (max 75 caratteri)",
      "badge": "Badge breve es. ⭐ SELEZIONE PREGIS",
      "prezzo": 8.80,
      "um": "al KG",
      "row_span": 2,
      "is_red_price": true
    }
  ]
}
Imposta row_span=2 per i prodotti con immagine grande sviluppata in verticale su 2 righe e row_span=1 per gli altri."""
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
            sys_prompt = """Sei l'Art Director ufficiale di PREGIS S.p.A. (leader nella distribuzione Ho.Re.Ca.).
Per ciascun prodotto genera:
- 'titolo_ai': nome prodotto elegante e ben formattato
- 'brand_ai': marchio o linea in corsivo (es. 'Selezione Pregis', 'Trinità', 'Simonini')
- 'imballo_ai': formato confezione (es. 'Imballo 4.50 kg')
- 'descrizione_ai': frase breve e persuasiva per chef/ristoratori (max 75 caratteri)
- 'badge_ai': bollino breve (es. '⭐ SELEZIONE PREGIS', '🔥 SUPER PROMO', '🔪 ZERO SCARTO')
Restituisci SOLO un oggetto JSON:
{
  "titolo": "es. PROMO MENSILE PREGIS",
  "prodotti_arricchiti": [
    {"idx": 0, "titolo_ai": "...", "brand_ai": "...", "imballo_ai": "...", "descrizione_ai": "...", "badge_ai": "..."}
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
    """Costruisce il Volantino PREGIS 3.0 con struttura di base a 10 prodotti + abbellimento grafico AI."""
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
        badge_clean = ai_it.get("badge_ai") or p.get("badge") or info["badge"]

        enriched_items.append({
            "id": db_match["id"] if db_match else p.get("id"),
            "codice": code or f"{40000 + idx}",
            "nome_originale": raw_name,
            "titolo": titolo_clean,
            "brand": brand_clean,
            "imballo": imballo_clean,
            "descrizione_ai": desc_clean,
            "badge": badge_clean,
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
                if len(chunk) >= 4:
                    # 1° prodotto: Torre Sinistra (2 righe, prezzo rosso)
                    chunk[0]["row_span"] = 2
                    chunk[0]["is_red_price"] = True
                    # 2° prodotto: Colonna Centrale Riga 1
                    chunk[1]["row_span"] = 1
                    # 3° prodotto: Torre Destra (2 righe, prezzo rosso)
                    chunk[2]["row_span"] = 2
                    chunk[2]["is_red_price"] = True
                    # 4° prodotto: Colonna Centrale Riga 2
                    chunk[3]["row_span"] = 1
                elif len(chunk) >= 1:
                    chunk[0]["is_red_price"] = True

            pages.append({
                "page_number": (p_idx // per_page) + 1,
                "items": chunk
            })

    return {
        "brand_header": "PREGIS",
        "brand_sub": "eccellenza nella ristorazione",
        "logo_url": PREGIS_LOGO_URL,
        "titolo": default_title,
        "sottotitolo": "Selezione Speciale Ho.Re.Ca. • Qualità Garantita Pregis",
        "stile": default_stile,
        "layout_mode": "pregis_10",
        "ai_beautified": ai_beautified,
        "show_ai_badges": True,
        "show_ai_descriptions": True,
        "per_page": per_page,
        "footer_brand": "PREGIS S.p.A. — Divisione Ho.Re.Ca.",
        "pages": pages
    }


def apply_smart_restyle(flyer_data: dict, prompt_text: str) -> dict:
    p_low = (prompt_text or "").lower()

    # Attiva sempre la modalità abbellita AI quando si chiede di migliorare/abbellire
    flyer_data["ai_beautified"] = True

    if any(k in p_low for k in ["autunn", "ottobre", "novembre", "foglie", "arancio", "caldo"]):
        flyer_data["stile"] = "pregis_autunno"
    elif any(k in p_low for k in ["natal", "invern", "dicembre", "feste", "rosso"]):
        flyer_data["stile"] = "pregis_inverno"
    elif any(k in p_low for k in ["mare", "pesce", "estate", "blu", "azzurr", "ittic"]):
        flyer_data["stile"] = "pregis_mare"
    elif any(k in p_low for k in ["nero", "oro", "luxury", "gourmet", "elegante", "scuro", "premium"]):
        flyer_data["stile"] = "pregis_luxury_dark"
    elif any(k in p_low for k in ["carne", "grill", "brace", "steak", "fuoco", "salum"]):
        flyer_data["stile"] = "pregis_grill"
    elif any(k in p_low for k in ["primaver", "verde", "fresc", "orto", "bio"]):
        flyer_data["stile"] = "pregis_primavera"

    m_tit = re.search(r'titolo\s+["\']?([A-Za-zÀ-ÿ0-9\s]{3,30})["\']?', prompt_text, re.IGNORECASE)
    if m_tit:
        flyer_data["titolo"] = m_tit.group(1).strip().upper()

    if "base" in p_low and ("classico" in p_low or "semplice" in p_low):
        flyer_data["ai_beautified"] = False

    # Rigenera descrizioni, nomi e badge con AI (OpenAI se presente + Smart Engine)
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
            info = extract_brand_imballo_and_copy(it.get("nome_originale") or it.get("titolo", ""), it.get("categoria", ""), flat_idx)
            upd = ai_map.get(flat_idx, {})
            it["titolo"] = upd.get("titolo_ai") or beautify_product_name(it.get("titolo", ""))
            it["brand"] = upd.get("brand_ai") or it.get("brand") or info["brand"]
            it["descrizione_ai"] = upd.get("descrizione_ai") or it.get("descrizione_ai") or info["descrizione_ai"]
            it["badge"] = upd.get("badge_ai") or it.get("badge") or info["badge"]
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
            cur.execute("""
                SELECT id, titolo, sottotitolo, stile, layout_mode, aggiornato_il
                FROM volantini_3_ai
                ORDER BY aggiornato_il DESC
                LIMIT 40
            """)
            for r in cur.fetchall():
                d = dict(r)
                d["aggiornato_il"] = str(d.get("aggiornato_il") or "")[:16]
                saved_list.append(d)

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
    titolo = (flyer.get("titolo") or "PROMO PREGIS 3.0").strip()
    sottotitolo = (flyer.get("sottotitolo") or "").strip()
    stile = flyer.get("stile") or "pregis_autunno"
    layout_mode = flyer.get("layout_mode") or "pregis_10"
    dati_json = json.dumps(flyer, ensure_ascii=False)

    try:
        with _GET_DB() as conn:
            cur = conn.cursor()
            if vol_id:
                cur.execute("""
                    UPDATE volantini_3_ai
                    SET titolo = %s, sottotitolo = %s, stile = %s, layout_mode = %s,
                        dati_json = %s, aggiornato_il = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (titolo, sottotitolo, stile, layout_mode, dati_json, int(vol_id)))
                saved_id = int(vol_id)
            else:
                cur.execute("""
                    INSERT INTO volantini_3_ai (titolo, sottotitolo, stile, layout_mode, dati_json)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id
                """, (titolo, sottotitolo, stile, layout_mode, dati_json))
                r = cur.fetchone()
                saved_id = r["id"] if r else None
            conn.commit()
        return jsonify({"ok": True, "id": saved_id, "message": f"✅ Volantino PREGIS '{titolo}' salvato!"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@volantini3_bp.route("/api/volantini-3/elimina/<int:vol_id>", methods=["POST", "DELETE"])
def api_volantini_3_elimina(vol_id):
    if not session.get("logged_in"):
        return jsonify({"ok": False, "error": "Non autorizzato"}), 401

    try:
        with _GET_DB() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM volantini_3_ai WHERE id = %s", (vol_id,))
            conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
