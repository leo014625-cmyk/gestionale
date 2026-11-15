import os
import re
import json
import time
import tempfile
import requests
import werkzeug.utils
from datetime import datetime, date
from flask import Blueprint, render_template, request, jsonify, session, url_for

volantini3_bp = Blueprint("volantini3_bp", __name__)

_GET_DB = None
_EXTRACT_PDF_FN = None
_GET_OPENAI_CFG_FN = None


def init_volantini_3(app, get_db_fn, extract_pdf_fn, get_openai_cfg_fn=None):
    global _GET_DB, _EXTRACT_PDF_FN, _GET_OPENAI_CFG_FN
    _GET_DB = get_db_fn
    _EXTRACT_PDF_FN = extract_pdf_fn
    _GET_OPENAI_CFG_FN = get_openai_cfg_fn

    # Assicura tabella volantini_3_ai
    try:
        with _GET_DB() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS volantini_3_ai (
                    id SERIAL PRIMARY KEY,
                    titolo TEXT NOT NULL,
                    sottotitolo TEXT,
                    stile TEXT DEFAULT 'luxury_gold',
                    layout_mode TEXT DEFAULT 'bento_editorial',
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
# MOTORE AI CREATIVO PER ABBELLIMENTO PRODOTTI, COPY E DIREZIONE ARTISTICA
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
    r'\bscot\.?\b': 'Scottona',
    r'\bGAMB\.?\b': 'Gambero',
    r'\bMAZZ\.?\b': 'Mazzancolla',
    r'\bCALAM\.?\b': 'Calamaro',
    r'\bSEPPI[EA]\.?\b': 'Seppia',
    r'\bPROSC\.?\b': 'Prosciutto',
    r'\bMOZZ\.?\b': 'Mozzarella',
    r'\bFIOR\.?\b': 'Fiordilatte',
    r'\bPAT\.?\b': 'Patate',
    r'\b RIST\.?\b': ' Ristorazione',
    r'\bEXTRAV\.?\b': 'Extravergine',
}


def beautify_product_name(raw_name: str) -> str:
    """Trasforma codici/nomi grezzi da fattura o PDF in titoli commerciali eleganti."""
    if not raw_name:
        return "Prodotto Selezione Chef"
    s = str(raw_name).strip()
    for pat, repl in ABBREV_MAP.items():
        s = re.sub(pat, repl, s, flags=re.IGNORECASE)
    # Rimuove doppi spazi e formatta in Title Case intelligente preservando pesi (es. 200g, 1kg)
    words = s.split()
    out_words = []
    small_words = {"di", "del", "della", "dei", "delle", "al", "alla", "con", "in", "da", "e", "per", "su"}
    for idx, w in enumerate(words):
        w_low = w.lower()
        if re.match(r'^\d+[a-zA-Z]+$', w_low):
            out_words.append(w_low)
        elif idx > 0 and w_low in small_words:
            out_words.append(w_low)
        elif w.isupper() and len(w) <= 2:
            out_words.append(w)
        else:
            out_words.append(w.capitalize())
    return " ".join(out_words)


def generate_smart_copy_and_badge(nome: str, categoria: str, idx: int) -> dict:
    """Genera descrizione persuasiva HoReCa, badge accattivante e ruolo visivo."""
    n_low = (nome or "").lower()
    c_low = (categoria or "").lower()

    if any(k in n_low or k in c_low for k in ["angus", "scottona", "manzo", "bovin", "filetto", "costata", "entrecote", "hamburger", "burger", "pollo", "suin", "carne", "salsiccia", "wurstel"]):
        descriptions = [
            "Taglio selezionato ad alta resa in cottura, tenero e succoso al palato.",
            "Selezione garantita per bracerie e ristorazione: frollatura e calibro costanti.",
            "Gusto intenso e marezzatura equilibrata, ideale per piatti gourmet e griglia.",
            "Materia prima scelta con zero scarto in cucina e tenuta perfetta in piastra."
        ]
        badges = ["🔥 SCELTA GRILL", "🥩 TAGLIO NOBILE", "⭐ TOP STEAKHOUSE", "🔪 ALTA RESA"]
        theme_hint = "steakhouse_fire"
    elif any(k in n_low or k in c_low for k in ["salmone", "polpo", "gamber", "mazzancoll", "calamar", "seppi", "tonno", "pesce", "ittic", "merluzz", "baccala", "cozz", "vongol", "orata", "branzino", "spada"]):
        descriptions = [
            "Selezionato all'origine e lavorato per preservare intatta la texture del mare.",
            "Ideale per crudi, antipasti di mare e secondi piatti ad alto valore aggiunto.",
            "Calibro uniforme e polpa soda: resa eccellente in padella, forno o griglia.",
            "Qualità superiore per ristoranti di pesce e bistrot contemporanei."
        ]
        badges = ["🌊 SELEZIONE MARE", "💎 QUALITÀ EXTRA", "⭐ SCELTA CHEF", "❄️ FRESCHEZZA TOP"]
        theme_hint = "mare_bistrot"
    elif any(k in n_low or k in c_low for k in ["mozzarell", "fiordilatte", "burrata", "formagg", "grana", "parmigiano", "prosciutt", "salame", "speck", "bresaola", "mortadella", "salum", "latticin", "panna", "burro"]):
        descriptions = [
            "Filatura e stagionatura d'eccellenza per pizzerie gourmet e taglieri ricercati.",
            "Gusto autentico della tradizione casearia e norcina italiana.",
            "Perfetta scioglievolezza in forno e profumo ricco, pensato per i professionisti.",
            "Selezione artigianale ad alta rotazione per antipasti e farciture premium."
        ]
        badges = ["🇮🇹 ECCELLENZA DOP", "🍕 TOP PIZZERIA", "⭐ SELEZIONE ORO", "💎 GOURMET"]
        theme_hint = "tradizione_italiana"
    elif any(k in n_low or k in c_low for k in ["patat", "verd", "orto", "pomodor", "fungh", "carciof", "melanzan", "olio", "farina", "pasta", "riso"]):
        descriptions = [
            "Croccantezza superiore e doratura impeccabile, pensata per alti volumi Ho.Re.Ca.",
            "Ingrediente base indispensabile con standard qualitativo costante tutto l'anno.",
            "Massima resa in cucina e sapore ricco, selezionato dai migliori raccolti."
        ]
        badges = ["🌿 100% SCELTO", "⚡ SUPER RESA", "⭐ TOP CUCINA", "🔥 OFFERTA MESE"]
        theme_hint = "tradizione_italiana"
    elif any(k in n_low or k in c_low for k in ["torta", "dolc", "dessert", "tiramis", "gelat", "cornett", "brioche", "cioccolat"]):
        descriptions = [
            "Pasticceria fine pronta al servizio: presentazione impeccabile e gusto avvolgente.",
            "Il finale perfetto per conquistare il cliente e aumentare lo scontrino medio."
        ]
        badges = ["🍰 CHEF PASTRY", "✨ GOLOSITÀ TOP", "⭐ DESSERT GOURMET"]
        theme_hint = "luxury_gold"
    else:
        descriptions = [
            "Prodotto professionale ad alta rotazione selezionato per il canale Ho.Re.Ca.",
            "Qualità certificata e convenienza garantita per la tua cucina professionale.",
            "Scelto dai migliori professionisti della ristorazione per affidabilità e gusto."
        ]
        badges = ["🔥 SUPER PROMO", "⭐ SCELTA CHEF", "💎 PREMIUM", "⚡ BEST SELLER"]
        theme_hint = "luxury_gold"

    return {
        "descrizione_ai": descriptions[idx % len(descriptions)],
        "badge_ai": badges[idx % len(badges)],
        "theme_hint": theme_hint
    }


def detect_best_theme_and_header(products: list, filename: str = "") -> dict:
    """Determina il tema grafico migliore e genera titolo/sottotitolo d'impatto."""
    hints = {}
    for idx, p in enumerate(products):
        info = generate_smart_copy_and_badge(p.get("nome", ""), p.get("categoria", ""), idx)
        th = info["theme_hint"]
        hints[th] = hints.get(th, 0) + 1

    best_theme = "luxury_gold"
    if hints:
        best_theme = max(hints.items(), key=lambda x: x[1])[0]

    mesi_it = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
               "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]
    mese_corrente = mesi_it[datetime.now().month - 1]

    theme_headers = {
        "steakhouse_fire": {
            "titolo": "GRANDE SELEZIONE CARNI & GRILL",
            "sottotitolo": f"Tagli Nobili, Frollature Scelte & Specialità Braceria • {mese_corrente} {datetime.now().year}",
            "tagline": "QUALITÀ SUPERIORE PER LA RISTORAZIONE"
        },
        "mare_bistrot": {
            "titolo": "TESORI DEL MARE & BISTROT",
            "sottotitolo": f"Selezioni Ittiche Pregiate per Ristoranti d'Eccellenza • {mese_corrente} {datetime.now().year}",
            "tagline": "FRESCHEZZA E RESA IN CUCINA"
        },
        "tradizione_italiana": {
            "titolo": "SAPORI D'ITALIA & PIZZERIA GOURMET",
            "sottotitolo": f"Ingredienti Scelti, Latticini & Dispensa Professionale • {mese_corrente} {datetime.now().year}",
            "tagline": "LA TRADIZIONE CHE FA LA DIFFERENZA"
        },
        "pop_promo": {
            "titolo": "SUPER OFFERTE LAMPO HO.RE.CA.",
            "sottotitolo": f"Occasioni Imperdibili a Stock Limitato • {mese_corrente} {datetime.now().year}",
            "tagline": "MASSIMO RISPARMIO · ALTA ROTAZIONE"
        },
        "luxury_gold": {
            "titolo": f"COLLEZIONE GOURMET {mese_corrente.upper()}",
            "sottotitolo": "Selezione Esclusiva di Prodotti Premium per la Ristorazione Professionale",
            "tagline": "EXCELLENCE FOOD SERVICE"
        }
    }
    hdr = theme_headers.get(best_theme, theme_headers["luxury_gold"])
    return {
        "stile": best_theme,
        "layout_mode": "bento_editorial",
        "titolo": hdr["titolo"],
        "sottotitolo": hdr["sottotitolo"],
        "tagline": hdr["tagline"]
    }


def call_openai_for_flyer_3(products: list, user_prompt: str = "", current_flyer: dict = None):
    """Se la chiave OpenAI è attiva, usa GPT-4o per abbellire testi, scegliere hero, colori e layout."""
    if not _GET_OPENAI_CFG_FN:
        return None
    api_key, model = _GET_OPENAI_CFG_FN()
    if not api_key:
        return None

    sample_prods = [
        {"idx": i, "codice": p.get("codice", ""), "nome": p.get("nome", ""), "prezzo": p.get("prezzo", ""), "um": p.get("um", "PZ"), "categoria": p.get("categoria", "")}
        for i, p in enumerate(products[:36])
    ]

    sys_prompt = """Sei un Art Director e Copywriter Gourmet specializzato in cataloghi e volantini Ho.Re.Ca. di fascia alta.
Il tuo compito è trasformare una lista grezza di prodotti in un Volantino 3.0 editoriale, non in griglia standard, ma con gerarchia visiva dinamica (Hero + Spotlight + Card asimmetriche).
Restituisci ESCLUSIVAMENTE un oggetto JSON valido con questa struttura:
{
  "titolo": "Titolo principale accattivante",
  "sottotitolo": "Sottotitolo persuasivo",
  "tagline": "Breve motto in alto (es. SELEZIONE CHEF)",
  "stile": "uno tra: luxury_gold, mare_bistrot, steakhouse_fire, pop_promo, tradizione_italiana, minimal_chic",
  "layout_mode": "uno tra: bento_editorial, hero_spotlight, zigzag_gourmet, collage_pop, luxury_split",
  "prodotti_arricchiti": [
    {
      "idx": 0,
      "titolo_ai": "Nome prodotto pulito ed elegante",
      "descrizione_ai": "Breve descrizione gastronomica persuasiva (max 85 caratteri)",
      "badge_ai": "Badge breve es. 🔥 TOP OFFERTA o ⭐ SCELTA CHEF",
      "is_hero": true
    }
  ]
}"""

    user_msg = f"Prodotti da impaginare: {json.dumps(sample_prods, ensure_ascii=False)}\n"
    if current_flyer:
        user_msg += f"Stato attuale volantino: stile={current_flyer.get('stile')}, layout={current_flyer.get('layout_mode')}, titolo={current_flyer.get('titolo')}\n"
    if user_prompt:
        user_msg += f"ISTRUZIONE SPECIFICA DELL'UTENTE: {user_prompt}\n"

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model or "gpt-4o",
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_msg}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.4
            },
            timeout=25
        )
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)
    except Exception as e:
        print(f"⚠️ OpenAI Volantini 3.0 fallback a Smart Engine: {e}")
    return None


def build_rich_flyer_data(raw_products: list, filename: str = "", user_prompt: str = "", per_page: int = 6) -> dict:
    """Costruisce la struttura completa multi-pagina del Volantino 3.0 AI."""
    # 1. Sincronizza con DB per recuperare immagini esistenti e categorie
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
        print(f"⚠️ DB lookup warning in build_rich_flyer_data: {e}")

    meta = detect_best_theme_and_header(raw_products, filename)
    ai_res = call_openai_for_flyer_3(raw_products, user_prompt=user_prompt)
    ai_map = {}
    if ai_res:
        meta["titolo"] = ai_res.get("titolo") or meta["titolo"]
        meta["sottotitolo"] = ai_res.get("sottotitolo") or meta["sottotitolo"]
        meta["tagline"] = ai_res.get("tagline") or meta["tagline"]
        if ai_res.get("stile") in ("luxury_gold", "mare_bistrot", "steakhouse_fire", "pop_promo", "tradizione_italiana", "minimal_chic"):
            meta["stile"] = ai_res["stile"]
        if ai_res.get("layout_mode") in ("bento_editorial", "hero_spotlight", "zigzag_gourmet", "collage_pop", "luxury_split"):
            meta["layout_mode"] = ai_res["layout_mode"]
        for item in (ai_res.get("prodotti_arricchiti") or []):
            if "idx" in item:
                ai_map[int(item["idx"])] = item

    enriched_items = []
    for idx, p in enumerate(raw_products):
        code = str(p.get("codice") or "").strip()
        raw_name = str(p.get("nome") or p.get("titolo") or "Prodotto").strip()
        um = str(p.get("um") or "PZ").strip().upper()
        cat = str(p.get("categoria") or "SELEZIONE").strip()

        # Prezzo formattato
        prz_raw = p.get("prezzo_str") or p.get("prezzo") or ""
        if isinstance(prz_raw, (int, float)):
            prz_num = float(prz_raw)
        else:
            m_p = re.search(r'(\d+[\.,]\d{1,2}|\d+)', str(prz_raw))
            prz_num = float(m_p.group(1).replace(",", ".")) if m_p else 0.0
        prezzo_fmt = f"{prz_num:.2f}".replace(".", ",") if prz_num > 0 else "N/D"

        # Match immagine dal DB
        db_match = db_by_code.get(code.upper()) or db_by_name.get(raw_name.upper())
        img_url = str(p.get("immagine") or "")
        if not img_url and db_match and db_match.get("immagine"):
            img_val = db_match["immagine"]
            if img_val.startswith("http") or img_val.startswith("/"):
                img_url = img_val
            else:
                img_url = f"/static/uploads/volantino_prodotti/{img_val}"

        if db_match and db_match.get("categoria_nome") and cat in ("OFFERTE", "SELEZIONE", ""):
            cat = db_match["categoria_nome"]

        smart_info = generate_smart_copy_and_badge(raw_name, cat, idx)
        ai_item = ai_map.get(idx, {})

        titolo_clean = ai_item.get("titolo_ai") or beautify_product_name(raw_name)
        desc_clean = ai_item.get("descrizione_ai") or smart_info["descrizione_ai"]
        badge_clean = ai_item.get("badge_ai") or smart_info["badge_ai"]

        enriched_items.append({
            "id": db_match["id"] if db_match else p.get("id"),
            "codice": code,
            "nome_originale": raw_name,
            "titolo": titolo_clean,
            "descrizione": desc_clean,
            "badge": badge_clean,
            "prezzo": prezzo_fmt,
            "um": um,
            "categoria": cat,
            "immagine": img_url,
            "imageZoom": float(p.get("imageZoom") or 1.0),
            "is_hero": bool(ai_item.get("is_hero", False))
        })

    # Suddivisione in pagine editoriali (default 6 prodotti per pagina per dare respiro grafico)
    pages = []
    if not enriched_items:
        pages.append({"page_number": 1, "subtitle": "", "items": []})
    else:
        for p_idx in range(0, len(enriched_items), per_page):
            chunk = enriched_items[p_idx:p_idx + per_page]
            # Assicura che ogni pagina abbia esattamente 1 Hero (il primo se nessuno è marcato)
            has_hero = any(it.get("is_hero") for it in chunk)
            if not has_hero and chunk:
                chunk[0]["is_hero"] = True
            pages.append({
                "page_number": (p_idx // per_page) + 1,
                "subtitle": f"Selezione Speciale • Pagina {(p_idx // per_page) + 1}",
                "items": chunk
            })

    return {
        "titolo": meta["titolo"],
        "sottotitolo": meta["sottotitolo"],
        "tagline": meta["tagline"],
        "stile": meta["stile"],
        "layout_mode": meta["layout_mode"],
        "per_page": per_page,
        "footer_note": "Prezzi IVA esclusa riservati agli operatori professionali Ho.Re.Ca. • Offerta valida salvo esaurimento scorte.",
        "pages": pages
    }


def apply_smart_restyle(flyer_data: dict, prompt_text: str) -> dict:
    """Applica modifiche grafiche e di contenuto in base al comando naturale dell'utente."""
    p_low = (prompt_text or "").lower()

    # 1. Cambio Stile / Palette
    if any(k in p_low for k in ["nero", "oro", "lusso", "luxury", "elegante", "scuro", "gourmet", "michelin"]):
        flyer_data["stile"] = "luxury_gold"
    elif any(k in p_low for k in ["mare", "pesce", "blu", "azzurro", "ittic", "fresco", "mediterraneo"]):
        flyer_data["stile"] = "mare_bistrot"
    elif any(k in p_low for k in ["carne", "steak", "braceria", "fuoco", "griglia", "grill", "angus"]):
        flyer_data["stile"] = "steakhouse_fire"
    elif any(k in p_low for k in ["pop", "offerta", "aggressiv", "giallo", "rosso", "lampo", "scont"]):
        flyer_data["stile"] = "pop_promo"
    elif any(k in p_low for k in ["italia", "pizzeria", "tradizion", "rustic", "caldo", "terracotta"]):
        flyer_data["stile"] = "tradizione_italiana"
    elif any(k in p_low for k in ["minimal", "bianco", "pulito", "moderno", "chiaro"]):
        flyer_data["stile"] = "minimal_chic"

    # 2. Cambio Layout Non-Griglia
    if any(k in p_low for k in ["bento", "asimmetric"]):
        flyer_data["layout_mode"] = "bento_editorial"
    elif any(k in p_low for k in ["hero", "spotlight", "gigante", "grande in alto"]):
        flyer_data["layout_mode"] = "hero_spotlight"
    elif any(k in p_low for k in ["zig", "alternat", "rivista", "magazine"]):
        flyer_data["layout_mode"] = "zigzag_gourmet"
    elif any(k in p_low for k in ["collage", "inclinat", "dinamic", "movimento"]):
        flyer_data["layout_mode"] = "collage_pop"
    elif any(k in p_low for k in ["split", "catalogo", "cornic"]):
        flyer_data["layout_mode"] = "luxury_split"

    # 3. Se l'utente chiede di mettere un prodotto specifico come Hero / in evidenza
    for page in (flyer_data.get("pages") or []):
        items = page.get("items") or []
        matched_idx = None
        for idx, it in enumerate(items):
            t_low = (it.get("titolo") or "").lower()
            words = [w for w in re.findall(r'[a-zA-ZÀ-ÿ]{4,}', t_low)]
            if any(w in p_low for w in words):
                matched_idx = idx
                break
        if matched_idx is not None and any(k in p_low for k in ["hero", "evidenza", "primo", "principale", "gigante", "grande"]):
            for it in items:
                it["is_hero"] = False
            items[matched_idx]["is_hero"] = True
            hero_item = items.pop(matched_idx)
            items.insert(0, hero_item)

    # 4. Se c'è anche OpenAI configurato, arricchisce ulteriormente titoli/descrizioni secondo il prompt
    all_items = [it for pg in (flyer_data.get("pages") or []) for it in (pg.get("items") or [])]
    ai_res = call_openai_for_flyer_3(all_items, user_prompt=prompt_text, current_flyer=flyer_data)
    if ai_res:
        if ai_res.get("titolo"):
            flyer_data["titolo"] = ai_res["titolo"]
        if ai_res.get("sottotitolo"):
            flyer_data["sottotitolo"] = ai_res["sottotitolo"]
        if ai_res.get("stile"):
            flyer_data["stile"] = ai_res["stile"]
        if ai_res.get("layout_mode"):
            flyer_data["layout_mode"] = ai_res["layout_mode"]
        ai_map = {int(x["idx"]): x for x in (ai_res.get("prodotti_arricchiti") or []) if "idx" in x}
        flat_idx = 0
        for pg in (flyer_data.get("pages") or []):
            for it in (pg.get("items") or []):
                if flat_idx in ai_map:
                    upd = ai_map[flat_idx]
                    if upd.get("titolo_ai"):
                        it["titolo"] = upd["titolo_ai"]
                    if upd.get("descrizione_ai"):
                        it["descrizione"] = upd["descrizione_ai"]
                    if upd.get("badge_ai"):
                        it["badge"] = upd["badge_ai"]
                flat_idx += 1

    return flyer_data


# ==============================================================================
# ROUTES VOLANTINI 3.0 AI STUDIO
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
    per_page = int(request.form.get("per_page") or 6)
    categoria_id = request.form.get("categoria_id")
    raw_text = (request.form.get("raw_text") or "").strip()

    products = []
    filename = ""

    file = request.files.get("pdf") or request.files.get("file")
    if file and file.filename:
        filename = file.filename
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

    # Fallback: se l'utente ha scelto una categoria dal catalogo o incollato testo
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
                        ORDER BY p.id DESC LIMIT 18
                    """)
                else:
                    cur.execute("""
                        SELECT p.id, p.codice, p.nome, p.prezzo, p.immagine, c.nome AS categoria
                        FROM prodotti p
                        LEFT JOIN categorie c ON p.categoria_id = c.id
                        WHERE p.categoria_id = %s AND COALESCE(p.eliminato, FALSE) = FALSE
                        ORDER BY p.nome LIMIT 24
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
                        "um": "PZ",
                        "categoria": d.get("categoria") or "SELEZIONE",
                        "immagine": img_u
                    })
        except Exception as e:
            print(f"⚠️ Errore caricamento prodotti da categoria in Volantini 3.0: {e}")

    if not products and raw_text:
        for line in raw_text.splitlines():
            line = line.strip()
            if len(line) < 3:
                continue
            m_price = re.search(r'(\d+[\.,]\d{2})', line)
            prz = float(m_price.group(1).replace(",", ".")) if m_price else 0.0
            clean_n = re.sub(r'€?\s*\d+[\.,]\d{2}', '', line).strip(" -–•\t")
            m_code = re.match(r'^([A-Za-z0-9]{3,12})\s+(.+)$', clean_n)
            cod = m_code.group(1) if m_code else ""
            nom = m_code.group(2) if m_code else clean_n
            if nom:
                products.append({"codice": cod, "nome": nom, "prezzo": prz, "um": "PZ", "categoria": "OFFERTE"})

    if not products:
        return jsonify({
            "ok": False,
            "error": "Nessun prodotto rilevato nel PDF. Assicurati che il PDF contenga codici e prezzi oppure seleziona una categoria dal catalogo."
        }), 400

    flyer_data = build_rich_flyer_data(products, filename=filename, user_prompt=user_prompt, per_page=per_page)
    if user_prompt:
        flyer_data = apply_smart_restyle(flyer_data, user_prompt)

    return jsonify({
        "ok": True,
        "message": f"✨ Volantino 3.0 generato con AI: {len(products)} prodotti impaginati in {len(flyer_data['pages'])} pagine editoriali!",
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
        "message": "✨ Design e contenuti rigenerati con successo!",
        "flyer": updated
    })


@volantini3_bp.route("/api/volantini-3/salva", methods=["POST"])
def api_volantini_3_salva():
    if not session.get("logged_in"):
        return jsonify({"ok": False, "error": "Non autorizzato"}), 401

    data = request.get_json(silent=True) or {}
    vol_id = data.get("id")
    flyer = data.get("flyer") or {}
    titolo = (flyer.get("titolo") or "Volantino 3.0 AI").strip()
    sottotitolo = (flyer.get("sottotitolo") or "").strip()
    stile = flyer.get("stile") or "luxury_gold"
    layout_mode = flyer.get("layout_mode") or "bento_editorial"
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
        return jsonify({"ok": True, "id": saved_id, "message": f"✅ Volantino 3.0 '{titolo}' salvato!"})
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
