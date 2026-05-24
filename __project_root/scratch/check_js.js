document.addEventListener("DOMContentLoaded", () => {
    
    const canvasContainer = document.getElementById("flyer-canvas");
    const volantinoId = "{{ volantino_id if volantino_id else '' }}";
    
    let currentDocPages = [];
    let currentPageIndex = 0;
    let layoutData = { header: {}, grid: [], background: null };
    
    // Lista sfondi
    let sfondiLibrary = [];
    
    // Parsiamo il JSON se valido (dal tag script sicuro)
    try {
        const layoutRaw = document.getElementById('layout-json-data').textContent;
        const parsed = JSON.parse(layoutRaw);
        if(parsed && !Array.isArray(parsed) && Object.keys(parsed).length > 0) {
            if (parsed.isMultiPage && Array.isArray(parsed.pages) && parsed.pages.length > 0) {
                currentDocPages = parsed.pages;
                layoutData = currentDocPages[0];
            } else {
                currentDocPages = [parsed];
                layoutData = currentDocPages[0];
            }
        } else {
            currentDocPages = [layoutData];
        }
    } catch(e) {
        console.error("Errore parsing layoutData:", e);
        currentDocPages = [layoutData];
    }
    
    if (!layoutData) layoutData = { header: {}, grid: [], background: null, global: {} };
    if (!layoutData.global) layoutData.global = {};
    if (!layoutData.header) layoutData.header = {};
    if (!layoutData.grid) layoutData.grid = [];

    console.log("LayoutData loaded:", layoutData);

    function saveCurrentPageToDoc() {
        if (currentDocPages.length > 0) {
            currentDocPages[currentPageIndex] = JSON.parse(JSON.stringify(layoutData));
        }
    }

    const btnSaveTemplate = document.getElementById("btn-save-template");
    if (btnSaveTemplate) {
        btnSaveTemplate.addEventListener("click", async () => {
            const btnOriginal = btnSaveTemplate.innerHTML;
            btnSaveTemplate.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Salvataggio...';
            btnSaveTemplate.disabled = true;
            try {
                saveCurrentPageToDoc();
                const currentData = layoutData;
                
                const resp = await fetch("{{ url_for('salva_template_promo') }}", {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        tipo: "{{ tipo_volantino }}",
                        global: currentData.global,
                        header: currentData.header,
                        background: currentData.background
                    })
                });
                const res = await resp.json();
                if(res.success) {
                    alert("Template visuale salvato con successo! Le prossime promozioni caricheranno queste impostazioni di base automaticamente.");
                } else {
                    alert("Errore salvataggio template: " + (res.message || ''));
                }
            } catch(e) {
                alert("Errore salvataggio template");
                console.error(e);
            }
            btnSaveTemplate.innerHTML = btnOriginal;
            btnSaveTemplate.disabled = false;
        });
    }

    function updatePaginationUI() {
        const pan = document.getElementById("multi-page-controls");
        if (!pan) return;
        if (currentDocPages.length > 1) {
            pan.style.setProperty("display", "flex", "important");
            document.getElementById("page-indicator").innerText = `Foglio ${currentPageIndex + 1} di ${currentDocPages.length}`;
            document.getElementById("btn-page-prev").disabled = (currentPageIndex === 0);
            document.getElementById("btn-page-next").disabled = (currentPageIndex === currentDocPages.length - 1);
        } else {
            pan.style.setProperty("display", "none", "important");
        }
    }
    
    const btnPrev = document.getElementById("btn-page-prev");
    if (btnPrev) {
        btnPrev.addEventListener("click", () => {
            if (currentPageIndex > 0) {
                saveCurrentPageToDoc();
                currentPageIndex--;
                layoutData = currentDocPages[currentPageIndex];
                renderLayout();
                updatePaginationUI();
            }
        });
    }

    const btnNext = document.getElementById("btn-page-next");
    if (btnNext) {
        btnNext.addEventListener("click", () => {
            if (currentPageIndex < currentDocPages.length - 1) {
                saveCurrentPageToDoc();
                currentPageIndex++;
                layoutData = currentDocPages[currentPageIndex];
                renderLayout();
                updatePaginationUI();
            }
        });
    }

    // --- ELIMINA FOGLIO CORRENTE ---
    const btnDeletePage = document.getElementById("btn-delete-page");
    if (btnDeletePage) {
        btnDeletePage.addEventListener("click", () => {
            if (currentDocPages.length <= 1) {
                alert("Non puoi eliminare l'unico foglio rimasto!");
                return;
            }
            if (!confirm(`Sei sicuro di voler eliminare il Foglio ${currentPageIndex + 1}? L'operazione è irreversibile.`)) return;
            
            currentDocPages.splice(currentPageIndex, 1);
            if (currentPageIndex >= currentDocPages.length) {
                currentPageIndex = currentDocPages.length - 1;
            }
            layoutData = currentDocPages[currentPageIndex];
            renderLayout();
            updatePaginationUI();
        });
    }

    // --- APPLICA PARAMETRI A TUTTI I FOGLI ---
    const btnApplyAll = document.getElementById("btn-apply-all-pages");
    if (btnApplyAll) {
        btnApplyAll.addEventListener("click", () => {
            if (currentDocPages.length <= 1) {
                alert("C'è un solo foglio, nessun altro foglio da aggiornare.");
                return;
            }
            saveCurrentPageToDoc();
            const currentGlobal = JSON.parse(JSON.stringify(layoutData.global));
            const currentHeader = JSON.parse(JSON.stringify(layoutData.header));
            const currentBg = layoutData.background ? JSON.parse(JSON.stringify(layoutData.background)) : null;
            
            for (let i = 0; i < currentDocPages.length; i++) {
                if (i === currentPageIndex) continue;
                currentDocPages[i].global = JSON.parse(JSON.stringify(currentGlobal));
                currentDocPages[i].header = JSON.parse(JSON.stringify(currentHeader));
                if (currentBg) {
                    currentDocPages[i].background = JSON.parse(JSON.stringify(currentBg));
                }
            }
            alert(`✅ Parametri applicati a tutti i ${currentDocPages.length} fogli!`);
        });
    }

    const btnAddPage = document.getElementById("btn-add-page");
    if (btnAddPage) {
        btnAddPage.addEventListener("click", () => {
            saveCurrentPageToDoc();
            // Copia layout corrente ma svuota i prodotti
            const newPage = JSON.parse(JSON.stringify(layoutData));
            if(newPage.grid && Array.isArray(newPage.grid)) {
                newPage.grid.forEach(cell => {
                    cell.productId = null;
                    cell.name = "";
                    cell.price = "";
                    cell.img = "";
                });
            }
            currentDocPages.push(newPage);
            currentPageIndex = currentDocPages.length - 1;
            layoutData = currentDocPages[currentPageIndex];
            renderFlyer();
            updatePaginationUI();
            alert("Nuovo foglio aggiunto!");
        });
    }

    // Inizializza layoutGrid di default se vuoto o non è un array
    if (!layoutData.grid || !Array.isArray(layoutData.grid) || layoutData.grid.length === 0) {
        console.log("Inizializzazione griglia di default (9 celle 3x3)...");
        layoutData.grid = [];
        for(let i=1; i<=9; i++) {
            layoutData.grid.push({
                id: 'cell_' + i,
                colSpan: 1,
                rowSpan: 1,
                isHidden: false,
                productId: null,
                name: "",
                price: "",
                img: "",
                bgTransparent: false,
                bgColor: "#f9f9f9",
                nameColor: "#000000",
                priceColor: "#e60000"
            });
        }
    }
    
    if(!layoutData.header) {
        layoutData.header = {
            title: "OFFERTE SPECIALI", titleColor: "#000000", titleSize: 48, logoUrl: "", logoSize: 180, logoPos: "center", titlePos: "right"
        };
    } else {
        if (layoutData.header.logoSize === undefined) layoutData.header.logoSize = 180;
        if (layoutData.header.logoPos === undefined) layoutData.header.logoPos = "center";
        if (layoutData.header.titlePos === undefined) layoutData.header.titlePos = "right";
    }

    if(!layoutData.global) {
        layoutData.global = {};
    }
    
    if(layoutData.global.width === undefined) layoutData.global.width = 4200;
    if(layoutData.global.height === undefined) layoutData.global.height = 1250;
    if(layoutData.global.border === undefined) layoutData.global.border = true;
    if(layoutData.global.bgColor === undefined) layoutData.global.bgColor = "#ffffff";
    if(layoutData.global.nameSize === undefined) layoutData.global.nameSize = 1.0;
    if(layoutData.global.priceSize === undefined) layoutData.global.priceSize = 1.8;
    if(layoutData.global.paddingTop === undefined) layoutData.global.paddingTop = 0;
    if(layoutData.global.paddingBottom === undefined) layoutData.global.paddingBottom = 0;
    if(layoutData.global.paddingSides === undefined) layoutData.global.paddingSides = 0;
    if(layoutData.global.gridGap === undefined) layoutData.global.gridGap = 0;
    if(layoutData.global.gridWidth === undefined) layoutData.global.gridWidth = 1800;
    if(layoutData.global.cols === undefined) layoutData.global.cols = 3;
    if(layoutData.global.rowHeight === undefined) layoutData.global.rowHeight = 0;
    
    if(layoutData.global.bgWidth === undefined) {
        layoutData.global.bgWidth = layoutData.global.bgSize !== undefined ? layoutData.global.bgSize : 100;
    }
    if(layoutData.global.bgHeight === undefined) {
        layoutData.global.bgHeight = layoutData.global.bgSize !== undefined ? layoutData.global.bgSize : 100;
    }
    if(layoutData.global.bgPosX === undefined) layoutData.global.bgPosX = 50;
    if(layoutData.global.bgPosY === undefined) layoutData.global.bgPosY = 50;
    if(layoutData.global.bgRepeat === undefined) layoutData.global.bgRepeat = "no-repeat";

    // --- DOM Elements ---
    const gridContainer = document.getElementById("flyer-grid");
    const headerContainer = document.getElementById("flyer-header");
    let selectedType = null; // 'header' o ID della cella

    // Proprietà UI
    const pnlEmpty = document.getElementById("no-selection-msg");
    const pnlHeader = document.getElementById("header-props");
    const pnlCell = document.getElementById("cell-props");
    const pnlFlyerBase = document.getElementById("flyer-base-props");
    
    // Base Flyer Inputs
    const inpFBorder = document.getElementById("prop-flyer-border");
    const inpFBgColor = document.getElementById("prop-flyer-bgcolor");
    const inpFPadTop = document.getElementById("prop-grid-pad-top");
    const inpFPadBot = document.getElementById("prop-grid-pad-bot");
    const inpFPadSides = document.getElementById("prop-grid-pad-sides");
    const inpFGridGap = document.getElementById("prop-grid-gap");
    
    // Background Image Props
    const inpFBgWidth = document.getElementById("prop-bg-width");
    const inpFBgHeight = document.getElementById("prop-bg-height");
    const inpFBgPosX = document.getElementById("prop-bg-pos-x");
    const inpFBgPosY = document.getElementById("prop-bg-pos-y");

    // Global Font Sizes
    const inpGNameSize = document.getElementById("prop-global-namesize");
    const lblGNameSize = document.getElementById("lbl-global-namesize");
    const inpGPriceSize = document.getElementById("prop-global-pricesize");
    const lblGPriceSize = document.getElementById("lbl-global-pricesize");

    const inpGWidth = document.getElementById("prop-global-width");
    const lblGWidth = document.getElementById("lbl-global-width");
    const inpGHeight = document.getElementById("prop-global-height");
    const lblGHeight = document.getElementById("lbl-global-height");
    const inpGGridWidth = document.getElementById("prop-global-grid-width");
    const lblGGridWidth = document.getElementById("lbl-global-grid-width");
    
    const inpGCols = document.getElementById("prop-global-cols");
    const lblGCols = document.getElementById("lbl-global-cols");
    const inpGRowHeight = document.getElementById("prop-global-row-height");
    const lblGRowHeight = document.getElementById("lbl-global-row-height");
    
    // Cell Padding Superiore/Inferiore (Custom Height management)
    const inpCPadTop = document.getElementById("prop-cell-pad-top");
    const lblCPadTop = document.getElementById("lbl-cell-pad-top");
    const inpCPadBot = document.getElementById("prop-cell-pad-bot");
    const lblCPadBot = document.getElementById("lbl-cell-pad-bot");

    const inpBgRepeat = document.getElementById("prop-bg-repeat");

    // Header Inputs
    const inpHTitle = document.getElementById("prop-header-title");
    const inpHColor = document.getElementById("prop-header-color");
    const inpHSize = document.getElementById("prop-header-size");
    const inpHLogo = document.getElementById("prop-header-logo");
    const inpHLogoSize = document.getElementById("prop-header-logo-size");
    const lblHLogoSize = document.getElementById("lbl-header-logo-size");

    // Cell Inputs
    const inpCName = document.getElementById("prop-cell-name");
    const inpCCode = document.getElementById("prop-cell-code");
    const inpCPrice = document.getElementById("prop-cell-price");
    const inpCImg = document.getElementById("prop-cell-img");
    const inpCBgColor = document.getElementById("prop-cell-bgcolor");
    const inpCNameColor = document.getElementById("prop-cell-namecolor");
    const inpCPriceColor = document.getElementById("prop-cell-pricecolor");
    const inpCBgTransparent = document.getElementById("prop-cell-bg-transparent");
    const inpCLayout = document.getElementById("prop-cell-layout");
    const inpCScadenza = document.getElementById("prop-cell-scadenza");
    const inpCPricePos = document.getElementById("prop-cell-pricepos");
    const inpCBadgePos = document.getElementById("prop-cell-badge-pos");
    const inpCBadgeStyle = document.getElementById("prop-cell-badge-style");
    const inpCImgZoom = document.getElementById("prop-cell-img-zoom");
    const inpCBadgeZoom = document.getElementById("prop-cell-badge-zoom");
    const inpCAlign = document.getElementById("prop-cell-align");
    const lblCellId = document.getElementById("lbl-cell-id");

    // --- CARICAMENTO PRODOTTI ---
    let prodottiData = [];
    fetch("{{ url_for('api_prodotti_volantino') }}")
        .then(r => r.json())
        .then(data => {
            prodottiData = data;
            renderProductsList(data);
        });

    function renderProductsList(list) {
        const container = document.getElementById("products-list");
        container.innerHTML = "";
        if (list.length === 0) {
            container.innerHTML = `<div class="text-muted small text-center mt-3">Nessun prodotto trovato.</div>`;
            return;
        }

        list.forEach(p => {
            const div = document.createElement('div');
            div.className = "product-item p-2 border-bottom";
            const prc = p.prezzo && p.prezzo !== "None" ? parseFloat(p.prezzo).toFixed(2) : "0.00";
            div.innerHTML = `
                <div class="fw-bold small">${p.nome}</div>
                <div class="d-flex justify-content-between align-items-center mt-1">
                    <span class="badge text-bg-light border">${p.codice||'-'}</span>
                    <span class="text-success fw-bold small">€ ${prc}</span>
                </div>
            `;
            
            // Assegnazione prodotto alla cella selezionata
            div.addEventListener('click', () => {
                if(selectedType && selectedType.startsWith('cell_')) {
                    const cellData = layoutData.grid.find(c => c.id === selectedType);
                    if(cellData) {
                        cellData.productId = p.id;
                        cellData.name = p.nome;
                        cellData.price = "€ " + prc;
                        
                        // Se il prodotto ha un'immagine nel DB la usa, altrimenti mette il placeholder
                        if(p.immagine && p.immagine.trim() !== "") {
                            cellData.img = p.immagine;
                        } else {
                            cellData.img = "https://via.placeholder.com/300?text=" + encodeURIComponent(p.nome.substring(0, 15));
                        }
                        
                        renderGrid();
                        selectElement(selectedType); // aggiorna pannello prop
                    }
                } else {
                    alert("Seleziona prima una casella vuota sul volantino!");
                }
            });
            container.appendChild(div);
        });
    }

    // Ricerca prodotti
    document.getElementById("search-products").addEventListener('input', (e) => {
        const q = e.target.value.toLowerCase().trim();
        const filtered = prodottiData.filter(p => p.nome.toLowerCase().includes(q) || (p.codice || "").toLowerCase().includes(q));
        renderProductsList(filtered);
    });

    // --- RENDERING CANVAS ---
    function getGridJson() {
        return JSON.stringify(layoutData);
    }

    function renderHeader() {
        const h = layoutData.header;
        
        const logoCont = document.getElementById("header-logo-container");
        const titleCont = document.getElementById("header-title-container");
        const img = document.getElementById("header-logo");
        const placeholder = document.getElementById("header-logo-placeholder");
        const titleText = document.getElementById("header-title");

        const lSize = h.logoSize !== undefined ? h.logoSize : 100;

        if(h.logoUrl) {
            img.src = h.logoUrl;
            img.style.display = "inline-block";
            
            // Calculate physical height to push grid down + zoom scale for sharpness
            const baseHeight = 120; // Default reference height in px
            const currentHeight = baseHeight * (lSize / 100);
            
            img.style.maxHeight = "none";
            img.style.height = currentHeight + "px";
            img.style.transform = `scale(${lSize / 100})`;
            img.style.transformOrigin = "center";
            
            placeholder.style.display = "none";
            
            // Remove artificial max-width constraints that caused zoom effect when moving slots
            img.style.maxWidth = "100%";
        } else {
            img.style.display = "none";
            placeholder.style.display = "block";
        }

        titleText.innerText = h.title || "";
        titleText.style.color = h.titleColor;
        titleText.style.fontSize = h.titleSize + "px";
        
        // Pulizia degli slot
        const slotL = document.getElementById("header-slot-left");
        const slotC = document.getElementById("header-slot-center");
        const slotR = document.getElementById("header-slot-right");
        
        // Mettiamoli temporaneamente nello storage per evitare errori se non mappati
        document.getElementById("header-elements-storage").appendChild(logoCont);
        document.getElementById("header-elements-storage").appendChild(titleCont);

        // Fix logic for inner styling of Logo Container to respect the Flex slots correctly
        logoCont.style.width = "100%";
        logoCont.style.display = "flex";
        
        // Add back standard margins while overriding the container
        img.style.margin = "0";
        logoCont.style.marginBottom = "0";

        // Mix-blend mode to drop white boundaries (makes "Sfondo" transparent!)
        img.style.mixBlendMode = "multiply";

        if(h.logoPos === 'center') {
            logoCont.style.justifyContent = "center";
            titleCont.style.textAlign = "center";
            img.style.margin = "0 auto";
        } else if(h.logoPos === 'right') {
            logoCont.style.justifyContent = "flex-end";
            titleCont.style.textAlign = "right";
            img.style.marginLeft = "auto";
            img.style.marginRight = "0";
        } else {
            logoCont.style.justifyContent = "flex-start";
            titleCont.style.textAlign = "left";
            img.style.marginRight = "auto";
            img.style.marginLeft = "0";
        }

        const slotMap = { "left": slotL, "center": slotC, "right": slotR };

        if(h.logoPos !== 'none' && slotMap[h.logoPos]) slotMap[h.logoPos].appendChild(logoCont);
        if(h.titlePos !== 'none' && slotMap[h.titlePos]) slotMap[h.titlePos].appendChild(titleCont);
        
        // Nascondi completamente il box header se entrambi sono disattivati
        // O se il tema è Pesce/Carne (richiesta utente: solo celle prodotti)
        const theme = layoutData.global.theme || 'standard';
        
        // Logica richiesta: Normale -> Logo + Celle, Carne/Pesce -> Solo Celle
        let headerVisible = false;
        if (theme === 'standard') {
            headerVisible = true;
            // Se in standard logoPos è 'none', lo forziamo a 'center' per assicurarci che si veda il logo
            if (h.logoPos === 'none' && h.logoUrl) {
                h.logoPos = 'center';
                syncHeaderButtons();
            }
        } else if (theme === 'carne' || theme === 'pesce') {
            headerVisible = false;
        }
        
        document.getElementById("flyer-header").style.display = headerVisible ? 'flex' : 'none';
    }

    function renderGrid() {
        gridContainer.innerHTML = "";
        
        layoutData.grid.forEach(cell => {
            const div = document.createElement("div");
            div.className = "grid-cell";
            div.id = cell.id;
            
            if(cell.isHidden) {
                div.classList.add("hidden");
            } else {
                div.style.gridColumn = "span " + cell.colSpan;
                div.style.gridRow = "span " + cell.rowSpan;
                
                // Forza visibilità se transparent ma senza BG (o se è richiesto esplicitamente)
                const isBgVisible = (cell.bgTransparent === false);
                div.style.backgroundColor = isBgVisible ? (cell.bgColor || "#ffffff") : "rgba(240, 240, 240, 0.95)";
                div.style.border = "2px solid #555"; // Forza bordo visibile
                
                // Applica Padding Cella (nuovi controlli)
                div.style.paddingTop = (cell.cellPadTop !== undefined ? cell.cellPadTop : 15) + "px";
                div.style.paddingBottom = (cell.cellPadBot !== undefined ? cell.cellPadBot : 15) + "px";
                
                const customLayout = cell.cellLayout || "vertical";
                const tAlign = cell.textAlign || "center";
                const pPos = cell.pricePos || "below";
                
                const globalNameSize = layoutData.global.nameSize || 1.0;
                const globalPriceSize = layoutData.global.priceSize || 1.8;
                const imgZoomScale = (cell.imgZoom !== undefined ? cell.imgZoom : 100) / 100;
                const badgeZoomScale = (cell.badgeZoom !== undefined ? cell.badgeZoom : 100) / 100;
                const imgRotate = (cell.imgRotate !== undefined) ? cell.imgRotate : 0;
                const imgX = (cell.imgX !== undefined) ? cell.imgX : 0;
                const imgY = (cell.imgY !== undefined) ? cell.imgY : 0;
                
                const htmlName = `<div style="color: ${cell.nameColor || '#333'}; font-size: ${globalNameSize}rem; line-height: 1.2; font-weight: bold; margin-bottom: 5px; min-height: ${globalNameSize * 3.8}rem; display: flex; align-items: flex-start; justify-content: ${tAlign === 'center' ? 'center' : (tAlign === 'right' ? 'flex-end' : 'flex-start')}; text-align: ${tAlign};">${(cell.name || '').replace(/\\n/g, '<br>')}</div>`;
                const htmlPrice = `<div style="color: ${cell.priceColor || '#e60000'}; font-size: ${globalPriceSize}rem; font-weight: 900; letter-spacing: -0.5px; margin-bottom: 0; min-height: ${globalPriceSize * 1.2}rem; display: flex; align-items: center; justify-content: ${tAlign === 'center' ? 'center' : (tAlign === 'right' ? 'flex-end' : 'flex-start')}; text-align: ${tAlign};">${cell.price || ''}</div>`;
                const htmlScad = cell.scadenza ? `<div style="font-size:0.9rem; color:#555; margin-top:2px;">SCAD: ${cell.scadenza}</div>` : '';

                const htmlTextGroup = pPos === 'above' 
                    ? htmlPrice + htmlName + htmlScad 
                    : htmlName + htmlPrice + htmlScad;
                
                const imgStyle = `max-width: 100%; max-height: 100%; object-fit: contain; mix-blend-mode: multiply; transform: translate(${imgX}px, ${imgY}px) scale(${imgZoomScale}) rotate(${imgRotate}deg); transition: transform 0.2s;`;
                
                // Crea nodi interni basati sul layout scelto
                let innerHtml = "";
                
                if (customLayout === "vertical") {
                    div.style.display = "grid";
                    div.style.gridTemplateRows = "1fr auto auto auto"; // Img, Name, Price, Scadenza
                    div.style.gap = "5px";
                    
                    innerHtml = `
                        <div class="cell-content-img" style="display: flex; align-items: center; justify-content: center; width: 100%; overflow: hidden; min-height: 0;">
                            ${cell.img ? `<img src="${cell.img}" alt="Prodotto" crossorigin="anonymous" style="${imgStyle}">` : `<div style="height:50px;"></div>`}
                        </div>
                        <div class="cell-content-name" style="text-align: ${tAlign};">
                            ${htmlName}
                        </div>
                        <div class="cell-content-price" style="text-align: ${tAlign}; position: relative;">
                            ${htmlPrice}
                            ${cell.code ? `<div style="font-size: 0.8rem; color: #666; margin-top: 2px; font-weight: bold; opacity: 0.8;">Cod. ${cell.code}</div>` : ''}
                        </div>
                        <div class="cell-content-scad" style="text-align: ${tAlign};">
                            ${htmlScad}
                        </div>
                    `;
                } else if (customLayout === "horizontal-left") {
                    div.style.display = "flex"; 
                    div.style.flexDirection = "row";
                    innerHtml = `
                        <div style="flex: 0 0 45%; max-width: 45%; display: flex; justify-content: center; align-items: center; padding-right: 15px; min-height: 0; overflow: hidden;">
                            ${cell.img ? `<img src="${cell.img}" alt="Prodotto" crossorigin="anonymous" style="${imgStyle}">` : `<div style="height:50px;"></div>`}
                        </div>
                        <div style="flex: 1; display: flex; flex-direction: column; justify-content: center; text-align: ${tAlign}; overflow: hidden;">
                            ${htmlTextGroup}
                        </div>
                    `;
                } else if (customLayout === "horizontal-right") {
                    div.style.display = "flex"; 
                    div.style.flexDirection = "row";
                    innerHtml = `
                        <div style="flex: 1; display: flex; flex-direction: column; justify-content: center; text-align: ${tAlign}; overflow: hidden;">
                            ${htmlTextGroup}
                        </div>
                        <div style="flex: 0 0 45%; max-width: 45%; display: flex; justify-content: center; align-items: center; padding-left: 15px; min-height: 0; overflow: hidden;">
                            ${cell.img ? `<img src="${cell.img}" alt="Prodotto" crossorigin="anonymous" style="${imgStyle}">` : `<div style="height:50px;"></div>`}
                        </div>
                    `;
                } else if (customLayout === "overlay") {
                    div.style.display = "block"; 
                    div.style.position = "relative"; 
                    div.style.overflow = "hidden";
                    
                    // Sfondo Immagine Estesa con Zoom Assoluto
                    const bgImgUrl = cell.img ? cell.img : "https://via.placeholder.com/400?text=" + encodeURIComponent(cell.name.substring(0, 15));
                    const overlayImgStyle = `position: absolute; top:0; left:0; width: 100%; height: 100%; object-fit: contain; padding: 20px; z-index: 1; transform: scale(${imgZoomScale}); transition: transform 0.2s;`;
                    
                    
                    // Box del Testo (Nome + Scadenza)
                    const htmlNameBox = `
                        <div style="position: absolute; top: 15px; left: 15px; right: 15px; background: rgba(255,255,255,0.9); padding: 10px; border-radius: 8px; text-align: ${tAlign}; box-shadow: 0 4px 10px rgba(0,0,0,0.15); z-index: 2;">
                            <div style="color: ${cell.nameColor || '#333'}; font-size: ${globalNameSize}rem; line-height: 1.2; font-weight: bold;">${(cell.name || '').replace(/\\n/g, '<br>')}</div>
                            ${cell.scadenza ? `<div style="font-size:0.9rem; color:#555; margin-top:2px;">SCAD: ${cell.scadenza}</div>` : ''}
                        </div>
                    `;

                    // Box del Prezzo (Badge)
                    const bStyle = cell.badgeStyle || 'none';
                    const bPos = cell.badgePos || 'bottom-right';

                    let badgeCss = `position: absolute; z-index: 3; display: flex; align-items: center; justify-content: center; font-weight: 900; line-height: 1; transition: transform 0.2s; `;
                    let priceHtmlInner = cell.price || '';

                    // Base transforms che dobbiamo preservare
                    let baseTransform = `scale(${badgeZoomScale})`;

                    // Stili Background
                    if (bStyle === 'circle-red') {
                        badgeCss += "background-color: #e60000; color: #ffffff !important; border-radius: 50%; width: 140px; height: 140px; font-size: 2.2rem; box-shadow: 0 8px 15px rgba(230,0,0,0.4); border: 4px solid white;";
                        baseTransform += " rotate(-5deg)";
                    } else if (bStyle === 'circle-yellow') {
                        badgeCss += "background-color: #ffcc00; color: #000000 !important; border-radius: 50%; width: 140px; height: 140px; font-size: 2.2rem; box-shadow: 0 8px 15px rgba(255,204,0,0.4); border: 4px solid #e60000;";
                        baseTransform += " rotate(-5deg)";
                    } else if (bStyle === 'rect-dark') {
                        badgeCss += "background-color: #222222; color: #ffffff !important; border-radius: 8px; padding: 15px 25px; font-size: 2rem; box-shadow: 0 8px 15px rgba(0,0,0,0.3); border: 2px solid white;";
                    } else { // none
                        badgeCss += `color: ${cell.priceColor || '#e60000'}; font-size: 2.5rem; text-shadow: 2px 2px 0px white, -2px -2px 0px white, 2px -2px 0px white, -2px 2px 0px white;`;
                    }
                    
                    badgeCss += ` transform: ${baseTransform}; transform-origin: center center;`;

                    // Posizionamento Assoluto
                    if (bPos === 'top-right') {
                        badgeCss += "top: 15px; right: 15px;";
                    } else if (bPos === 'bottom-left') {
                        badgeCss += "bottom: 15px; left: 15px;";
                    } else { // bottom-right (default)
                        badgeCss += "bottom: 15px; right: 15px;";
                    }

                    const htmlBadgeBox = `<div style="${badgeCss}">${priceHtmlInner}</div>`;

                    innerHtml = `
                        <img src="${bgImgUrl}" alt="Prodotto" crossorigin="anonymous" style="${overlayImgStyle}">
                        ${htmlNameBox}
                        ${htmlBadgeBox}
                    `;
                }
                
                div.innerHTML = innerHtml;
                
                if(selectedType === cell.id) {
                    div.classList.add("selected");
                }

                div.addEventListener("click", (e) => {
                    e.stopPropagation();
                    selectElement(cell.id);
                });

                // --- DRAG & DROP IMMAGINE ---
                div.addEventListener("dragover", (e) => {
                    e.preventDefault();
                    div.style.border = "3px dashed #007bff";
                    div.style.backgroundColor = "rgba(0,123,255,0.1)";
                });
                div.addEventListener("dragleave", (e) => {
                    e.preventDefault();
                    div.style.border = "2px solid #555";
                    div.style.backgroundColor = isBgVisible ? (cell.bgColor || "#ffffff") : "rgba(240, 240, 240, 0.95)";
                });
                div.addEventListener("drop", async (e) => {
                    e.preventDefault();
                    div.style.border = "2px solid #555";
                    div.style.backgroundColor = isBgVisible ? (cell.bgColor || "#ffffff") : "rgba(240, 240, 240, 0.95)";
                    
                    const files = e.dataTransfer.files;
                    if (files && files.length > 0) {
                        // Upload file locale
                        await handleFileUpload(files[0], cell.id);
                    } else {
                        // Prova a prendere URL (Drag from Google/External)
                        const html = e.dataTransfer.getData("text/html");
                        const match = html.match(/src="([^"]+)"/);
                        let url = match ? match[1] : e.dataTransfer.getData("text/plain");
                        if (url && url.startsWith("http")) {
                            await handleUrlDrop(url, cell.id);
                        }
                    }
                });
            }

            gridContainer.appendChild(div);
        });
    }

    function renderBackground() {
        const bg = layoutData.background;
        const mainCanvas = document.getElementById("flyer-canvas");
        const glob = layoutData.global;
        
        // Applica i margini e colori base
        if(glob) {
            mainCanvas.style.width = (glob.width || 2800) + "px";
            mainCanvas.style.height = (glob.height || 1250) + "px";
            mainCanvas.style.backgroundColor = glob.bgColor || "#ffffff";
            
            const theme = glob.theme || 'standard';
            let innerShadow = "inset 0 0 0 50px rgba(255,255,255,0)"; // standard
            
            if (theme === 'carne' || theme === 'pesce') {
                // Per i temi custom (Carne/Pesce) togliamo la vignetta di default
                innerShadow = "inset 0 0 0 50px rgba(255,255,255,0)"; 
            }
            
            // Applica CSS Griglia (Padding e Gap)
            const gridContainerDom = document.getElementById("flyer-grid");
            const headerAreaDom = document.getElementById("flyer-header");
            
            const gWidthPx = glob.gridWidth !== undefined ? glob.gridWidth : 1800;
            const gCols = glob.cols || 3;
            const gRowH = glob.rowHeight || 0;
            
            gridContainerDom.style.width = gWidthPx + "px";
            gridContainerDom.style.margin = "0 auto";
            gridContainerDom.style.gridTemplateColumns = `repeat(${gCols}, 1fr)`;
            gridContainerDom.style.flex = "1 1 auto"; 
            gridContainerDom.style.display = "grid"; 
            gridContainerDom.style.gap = (glob.gridGap || 0) + "px";
            
            if(gRowH > 0) {
                gridContainerDom.style.gridAutoRows = `${gRowH}px`;
            } else {
                gridContainerDom.style.gridAutoRows = `1fr`;
            }
            
            headerAreaDom.style.width = gWidthPx + "px";
            headerAreaDom.style.margin = "0 auto";
            headerAreaDom.style.flexShrink = "0"; 

            gridContainerDom.style.paddingTop = (glob.paddingTop || 0) + "px";
            gridContainerDom.style.paddingBottom = (glob.paddingBottom || 0) + "px";
            gridContainerDom.style.paddingLeft = (glob.paddingSides || 0) + "px";
            gridContainerDom.style.paddingRight = (glob.paddingSides || 0) + "px";
            gridContainerDom.style.gap = (glob.gridGap || 0) + "px";

            if(glob.border) {
                // To overlay the background, we use inset box-shadow
                mainCanvas.style.boxSizing = "border-box";
                mainCanvas.style.border = "none";
                document.getElementById('flyer-overlay-shadow').style.boxShadow = innerShadow;
                mainCanvas.style.boxShadow = "0 4px 6px rgba(0,0,0,0.1)"; // Default outer shadow
            } else {
                mainCanvas.style.border = "none";
                document.getElementById('flyer-overlay-shadow').style.boxShadow = "none";
                mainCanvas.style.boxShadow = "0 4px 6px rgba(0,0,0,0.1)"; // Default outer shadow
            }
        }

        if (bg && bg.url) {
            mainCanvas.style.backgroundImage = `url('${bg.url}')`;
            
            const bWidth = glob.bgWidth !== undefined ? glob.bgWidth : 100;
            const bHeight = glob.bgHeight !== undefined ? glob.bgHeight : 100;
            const bPosX = glob.bgPosX !== undefined ? glob.bgPosX : 50;
            const bPosY = glob.bgPosY !== undefined ? glob.bgPosY : 50;
            
            const bRepeat = glob.bgRepeat || "no-repeat";
            
            if (bRepeat === "cover" || bRepeat === "contain") {
                mainCanvas.style.backgroundSize = bRepeat;
                mainCanvas.style.backgroundRepeat = "no-repeat";
            } else {
                mainCanvas.style.backgroundSize = `${bWidth}% ${bHeight}%`;
                mainCanvas.style.backgroundRepeat = bRepeat;
            }
            mainCanvas.style.backgroundPosition = `${bPosX}% ${bPosY}%`;
            
            document.getElementById("current-bg-preview").src = bg.url;
            document.getElementById("current-bg-preview").style.display = "block";
            document.getElementById("current-bg-name").innerText = bg.nome || "Sfondo Libero";
        } else {
            mainCanvas.style.backgroundImage = "none";
            
            document.getElementById("current-bg-preview").style.display = "none";
            document.getElementById("current-bg-name").innerText = "Nessuno sfondo";
        }
    }

    async function loadLibraryBackgrounds() {
        const pnl = document.getElementById("bg-library-list");
        if(!pnl) return;
        
        try {
            const resp = await fetch("{{ url_for('get_sfondi_volantino') }}");
            const data = await resp.json();
            
            pnl.innerHTML = "";
            if (data.length === 0) {
                pnl.innerHTML = `<div class="text-muted small w-100 text-center py-2">Nessuno sfondo salvato.</div>`;
                return;
            }
            
            data.forEach(b => {
                const col = document.createElement("div");
                col.className = "col-4";
                
                const btn = document.createElement("div");
                btn.className = "p-1 border rounded text-center position-relative";
                btn.style.cursor = "pointer";
                btn.innerHTML = `
                    <img src="${b.url}" crossorigin="anonymous" style="width:100%; height:40px; object-fit:cover; border-radius:3px;">
                    <div class="small mt-1 text-truncate" style="font-size:0.75rem;" title="${b.nome}">${b.nome}</div>
                `;
                
                const delBtn = document.createElement("button");
                delBtn.className = "btn btn-sm btn-danger position-absolute top-0 end-0 p-0";
                delBtn.style.width = "18px";
                delBtn.style.height = "18px";
                delBtn.style.lineHeight = "1";
                delBtn.innerHTML = "&times;";
                delBtn.onclick = async (e) => {
                    e.stopPropagation();
                    if(confirm(`Eliminare lo sfondo "${b.nome}"?`)) {
                        try {
                            const dr = await fetch(`/api/sfondi_volantino/${b.id}`, { method: 'DELETE' });
                            const dd = await dr.json();
                            if(dd.success) loadLibraryBackgrounds();
                            else alert("Errore eliminazione: " + dd.message);
                        } catch(err) { alert("Errore di rete"); }
                    }
                };
                btn.appendChild(delBtn);
                
                btn.onclick = () => {
                    layoutData.background = { url: b.url, nome: b.nome };
                    renderBackground();
                    bootstrap.Modal.getOrCreateInstance(document.getElementById('bgModal')).hide();
                };
                
                col.appendChild(btn);
                pnl.appendChild(col);
            });
            
        } catch(err) {
            console.error(err);
            pnl.innerHTML = `<div class="text-danger small w-100 text-center py-2">Errore caricamento sfondi</div>`;
        }
    }

    // Modal Events
    document.getElementById("btn-apply-bg-url").addEventListener("click", () => {
        const url = document.getElementById("prop-bg-url").value.trim();
        if(url) {
            layoutData.background = { url: url, nome: "URL Link" };
            renderBackground();
            document.getElementById("prop-bg-url").value = "";
            bootstrap.Modal.getOrCreateInstance(document.getElementById('bgModal')).hide();
        }
    });

    document.getElementById("btn-remove-bg").addEventListener("click", () => {
        layoutData.background = null;
        renderBackground();
        bootstrap.Modal.getOrCreateInstance(document.getElementById('bgModal')).hide();
    });

    // Binding inputs Base Flyer

    inpFBorder.addEventListener("change", (e) => {
        layoutData.global.border = e.target.checked;
        renderBackground();
    });
    inpFBgColor.addEventListener("input", (e) => {
        layoutData.global.bgColor = e.target.value;
        renderBackground();
    });
    
    // Grid Padding Bindings
    inpFPadTop.addEventListener("input", (e) => {
        layoutData.global.paddingTop = parseInt(e.target.value);
        document.getElementById('lbl-grid-pad-top').innerText = e.target.value + "px";
        renderBackground();
    });
    inpFPadBot.addEventListener("input", (e) => {
        layoutData.global.paddingBottom = parseInt(e.target.value);
        document.getElementById('lbl-grid-pad-bot').innerText = e.target.value + "px";
        renderBackground();
    });
    inpFPadSides.addEventListener("input", (e) => {
        layoutData.global.paddingSides = parseInt(e.target.value);
        document.getElementById('lbl-grid-pad-sides').innerText = e.target.value + "px";
        renderBackground();
    });
    inpFGridGap.addEventListener("input", (e) => {
        layoutData.global.gridGap = parseInt(e.target.value);
        document.getElementById('lbl-grid-gap').innerText = e.target.value + "px";
        renderBackground();
    });
    
    // Background Image Bindings
    inpFBgWidth.addEventListener("input", (e) => {
        layoutData.global.bgWidth = parseInt(e.target.value);
        document.getElementById('lbl-bg-width').innerText = e.target.value + "%";
        renderBackground();
    });
    inpFBgHeight.addEventListener("input", (e) => {
        layoutData.global.bgHeight = parseInt(e.target.value);
        document.getElementById('lbl-bg-height').innerText = e.target.value + "%";
        renderBackground();
    });
    inpFBgPosX.addEventListener("input", (e) => {
        layoutData.global.bgPosX = parseInt(e.target.value);
        document.getElementById('lbl-bg-pos-x').innerText = e.target.value + "%";
        renderBackground();
    });
    inpFBgPosY.addEventListener("input", (e) => {
        layoutData.global.bgPosY = parseInt(e.target.value);
        document.getElementById('lbl-bg-pos-y').innerText = e.target.value + "%";
        renderBackground();
    });

    // Global Font Sizes
    inpGNameSize.addEventListener("input", (e) => {
        layoutData.global.nameSize = parseFloat(e.target.value);
        lblGNameSize.innerText = layoutData.global.nameSize;
        renderGrid();
    });

    inpGPriceSize.addEventListener("input", (e) => {
        layoutData.global.priceSize = parseFloat(e.target.value);
        lblGPriceSize.innerText = layoutData.global.priceSize;
        renderGrid();
    });

    // I vecchi listener per Dimensioni globali col, width, height, gridWidth, rowHeight 
    // sono ora gestiti in setupRangeSync() sotto.

    document.getElementById("btn-add-cell").addEventListener("click", () => {
        const newId = "cell_" + (layoutData.grid.length + 1);
        layoutData.grid.push({
            id: newId,
            colSpan: 1,
            rowSpan: 1,
            name: "Prodotto " + (layoutData.grid.length),
            price: "€ 0,00",
            img: "",
            nameColor: "#000000",
            priceColor: "#e60000",
            bgTransparent: true
        });
        renderGrid();
    });

    document.getElementById("btn-remove-cell").addEventListener("click", () => {
        if(layoutData.grid.length > 1) {
            layoutData.grid.pop();
            renderGrid();
        }
    });

    inpCPadTop.addEventListener("input", (e) => {
        if (selectedType && layoutData.grid.find(c => c.id === selectedType)) {
            const cell = layoutData.grid.find(c => c.id === selectedType);
            cell.cellPadTop = parseInt(e.target.value);
            lblCPadTop.innerText = cell.cellPadTop;
            renderGrid();
        }
    });

    inpCPadBot.addEventListener("input", (e) => {
        if (selectedType && layoutData.grid.find(c => c.id === selectedType)) {
            const cell = layoutData.grid.find(c => c.id === selectedType);
            cell.cellPadBot = parseInt(e.target.value);
            lblCPadBot.innerText = cell.cellPadBot;
            renderGrid();
        }
    });

    function setupRangeSync(rangeId, numberId, propName, isGlobal = false) {
        const rangeEl = document.getElementById(rangeId);
        const numberEl = document.getElementById(numberId);

        if (!rangeEl || !numberEl) return;

        function sync(value) {
            rangeEl.value = value;
            numberEl.value = value;
            if (isGlobal) {
                layoutData.global[propName] = parseFloat(value);
            } else {
                const cell = layoutData.grid.find(c => c.id === selectedType);
                if (cell) {
                    cell[propName] = parseFloat(value);
                }
            }
            if (isGlobal) renderBackground(); else renderGrid();
        }

        rangeEl.addEventListener("input", (e) => sync(e.target.value));
        numberEl.addEventListener("input", (e) => sync(e.target.value));
    }

    // Bind item specific:
    setupRangeSync("prop-cell-img-zoom", "inp-cell-img-zoom", "imgZoom");
    setupRangeSync("prop-cell-img-rotate", "inp-cell-img-rotate", "imgRotate");
    setupRangeSync("prop-cell-img-x", "inp-cell-img-x", "imgX");
    setupRangeSync("prop-cell-img-y", "inp-cell-img-y", "imgY");

    // Bind global items
    setupRangeSync("prop-global-cols", "inp-global-cols", "cols", true);
    setupRangeSync("prop-global-width", "inp-global-width", "width", true);
    setupRangeSync("prop-global-height", "inp-global-height", "height", true);
    setupRangeSync("prop-global-grid-width", "inp-global-grid-width", "gridWidth", true);
    setupRangeSync("prop-global-row-height", "inp-global-row-height", "rowHeight", true);

    inpBgRepeat.addEventListener("change", (e) => {
        layoutData.global.bgRepeat = e.target.value;
        renderBackground();
    });

    const fileUploadBg = document.getElementById('file-upload-bg');
    document.getElementById('btn-upload-bg-file').addEventListener('click', () => fileUploadBg.click());
    
    fileUploadBg.addEventListener('change', (e) => {
        if(e.target.files.length > 0) {
            document.getElementById('prop-bg-name').value = e.target.files[0].name.split('.')[0];
        }
    });

    document.getElementById('btn-save-bg').addEventListener('click', async () => {
        const nome = document.getElementById('prop-bg-name').value.trim();
        const file = fileUploadBg.files[0];
        
        if(!nome || !file) {
            alert("Inserisci un nome e seleziona un file.");
            return;
        }
        
        const btn = document.getElementById('btn-save-bg');
        const oldHtml = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
        btn.disabled = true;
        
        try {
            const fd = new FormData();
            fd.append('file', file);
            fd.append('nome', nome);
            
            const resp = await fetch("{{ url_for('upload_sfondo_volantino') }}", { method: 'POST', body: fd });
            const data = await resp.json();
            
            if(data.success) {
                document.getElementById('prop-bg-name').value = "";
                fileUploadBg.value = "";
                loadLibraryBackgrounds();
                layoutData.background = { url: data.sfondo.url, nome: data.sfondo.nome };
                renderBackground();
            } else {
                alert("Errore: " + data.message);
            }
        } catch(err) {
            alert("Errore di caricamento");
        } finally {
            btn.innerHTML = oldHtml;
            btn.disabled = false;
        }
    });

    // --- Nuovi Eventi UI (Estrazione PDF) ---
    const pdfInput = document.getElementById('pdf-inject-upload');
    const btnPdf = document.getElementById('btn-pdf-inject');
    
    btnPdf.addEventListener('click', () => {
        if(confirm("Vuoi estrarre automaticamente le offerte da un PDF e inserirle nelle celle vuote del volantino attuale?")) {
            pdfInput.click();
        }
    });

    pdfInput.addEventListener('change', async (e) => {
        if(!e.target.files.length) return;
        
        const file = e.target.files[0];
        const fd = new FormData();
        fd.append('file', file);
        
        const originalHtml = btnPdf.innerHTML;
        btnPdf.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Lettura PDF in corso...';
        btnPdf.disabled = true;

        try {
            const resp = await fetch("{{ url_for('api_estrai_prodotti_da_pdf') }}", { method: 'POST', body: fd });
            const data = await resp.json();
            
            if(data.success && data.prodotti) {
                let pIndex = 0;
                let injected = 0;
                
                // Itera sulla griglia e riempi le celle vuote (senza prodotto associato)
                for(let i = 0; i < layoutData.grid.length; i++) {
                    const c = layoutData.grid[i];
                    if(!c.productId && !c.isHidden && pIndex < data.prodotti.length) {
                        const prod = data.prodotti[pIndex];
                        c.productId = prod.id;
                        c.name = prod.nome;
                        c.price = prod.prezzo;
                        c.img = prod.immagine;
                        c.bgTransparent = false; // Forza visibilità cella con prodotto
                        pIndex++;
                        injected++;
                    }
                }
                
                renderGrid();
                
                if(injected > 0) {
                    alert(`✅ Super! Sono stati estratti ed inseriti ${injected} prodotti con successo nelle celle vuote.`);
                } else {
                    alert(`ℹ️ Prodotti estratti ma nessuna cella vuota trovata. Aggiungi celle o svuotane alcune prima di riversarli.`);
                }
                
            } else {
                alert("Errore estrazione PDF: " + data.message);
            }
        } catch(err) {
            console.error(err);
            alert("Errore di connessione durante l'analisi del PDF. Riprova.");
        } finally {
            btnPdf.innerHTML = originalHtml;
            btnPdf.disabled = false;
            pdfInput.value = ""; // Resetta l'input per poter ricaricare lo stesso file
        }
    });

    // --- TOOL DIMENSIONI VOLANTINO ---
    const modSizeModal = document.getElementById('sizeModal');
    modSizeModal.addEventListener('show.bs.modal', () => {
        document.getElementById('prop-flyer-width').value = layoutData.global.width || 4200;
        document.getElementById('prop-flyer-height').value = layoutData.global.height || 1250;
        document.getElementById('prop-flyer-namesize').value = layoutData.global.nameSize || 1.0;
        document.getElementById('prop-flyer-pricesize').value = layoutData.global.priceSize || 1.8;
    });

    document.getElementById('prop-flyer-preset').addEventListener('change', (e) => {
        const val = e.target.value;
        const wInp = document.getElementById('prop-flyer-width');
        const hInp = document.getElementById('prop-flyer-height');
        if(val === 'a4') { wInp.value = 2480; hInp.value = 3508; }
        else if(val === 'orizzontale') { wInp.value = 3508; hInp.value = 2480; }
        else if(val === 'striscia') { wInp.value = 4200; hInp.value = 1250; }
        else if(val === 'quadrato') { wInp.value = 2000; hInp.value = 2000; }
    });

    document.getElementById('btn-apply-size').addEventListener('click', () => {
        const w = parseInt(document.getElementById('prop-flyer-width').value) || 4200;
        const h = parseInt(document.getElementById('prop-flyer-height').value) || 1250;
        const ns = parseFloat(document.getElementById('prop-flyer-namesize').value) || 1.0;
        const ps = parseFloat(document.getElementById('prop-flyer-pricesize').value) || 1.8;
        
        layoutData.global.width = Math.max(800, Math.min(w, 8000));
        layoutData.global.height = Math.max(800, Math.min(h, 8000));
        layoutData.global.nameSize = Math.max(0.2, Math.min(ns, 8.0));
        layoutData.global.priceSize = Math.max(0.5, Math.min(ps, 10.0));
        
        renderBackground();
        renderGrid(); // Forza l'aggiornamento visivo di tutte le etichette di testo
        bootstrap.Modal.getOrCreateInstance(modSizeModal).hide();
    });

    // --- SELEZIONE UI ---
    // Rendi selezionabile lo sfondo del canvas intero (quando clicchi in un punto vuoto del canvas)
    document.getElementById("flyer-canvas").addEventListener("click", (e) => {
        const canvas = document.getElementById("flyer-canvas");
        const grid = document.getElementById("flyer-grid");
        const header = document.getElementById("flyer-header");
        
        if (e.target === canvas || e.target.id === 'flyer-overlay-shadow') {
            selectElement("flyer");
        } else if (e.target === grid || e.target.classList.contains('canvas-row')) {
            selectElement("background");
        }
    });

    function selectElement(type) {
        selectedType = type;
        document.querySelectorAll(".selected").forEach(el => el.classList.remove("selected", "flyer-bg-selected"));
        document.getElementById("no-selection-msg").classList.add("d-none");
        
        // Reset Accordion and selection classes
        document.querySelectorAll(".grid-cell").forEach(el => el.classList.remove("selected"));
        document.getElementById("flyer-header").classList.remove("selected");
        document.getElementById("flyer-canvas").classList.remove("flyer-bg-selected");
        
        if (type === "header") {
            document.getElementById("flyer-header").classList.add("selected");
            
            // Gestione Accordion: Espandi sezione Intestazione
            const coll = document.getElementById('collapseHeader');
            if(coll) bootstrap.Collapse.getOrCreateInstance(coll).show();
            document.getElementById('item-cell-props').classList.add('d-none');

            inpHTitle.value = layoutData.header.title;
            inpHColor.value = layoutData.header.titleColor;
            inpHSize.value = layoutData.header.titleSize;
            inpHLogo.value = layoutData.header.logoUrl || "";
            
            const lSize = layoutData.header.logoSize !== undefined ? layoutData.header.logoSize : 100;
            inpHLogoSize.value = lSize;
            lblHLogoSize.innerText = lSize + "%";
            
            syncHeaderButtons();
            
        } else if (type === "flyer" || type === "background") {
            selectedType = type;
            document.getElementById("flyer-canvas").classList.add("flyer-bg-selected");
            
            // Gestione Accordion: Espandi sezione Foglio o Sfondo
            const targetId = (type === "background") ? 'collapseBg' : 'collapseFlyer';
            const coll = document.getElementById(targetId);
            if(coll) bootstrap.Collapse.getOrCreateInstance(coll).show();

            document.getElementById('item-cell-props').classList.add('d-none');

            inpFBorder.checked = layoutData.global.border;
            inpFBgColor.value = layoutData.global.bgColor;
            
            inpFPadTop.value = layoutData.global.paddingTop || 0;
            document.getElementById('lbl-grid-pad-top').innerText = inpFPadTop.value + "px";
            inpFPadBot.value = layoutData.global.paddingBottom || 0;
            document.getElementById('lbl-grid-pad-bot').innerText = inpFPadBot.value + "px";
            inpFPadSides.value = layoutData.global.paddingSides || 0;
            document.getElementById('lbl-grid-pad-sides').innerText = inpFPadSides.value + "px";
            inpFGridGap.value = layoutData.global.gridGap || 0;
            document.getElementById('lbl-grid-gap').innerText = inpFGridGap.value + "px";
            
            inpFBgWidth.value = layoutData.global.bgWidth !== undefined ? layoutData.global.bgWidth : 100;
            document.getElementById('lbl-bg-width').innerText = inpFBgWidth.value + "%";
            inpFBgHeight.value = layoutData.global.bgHeight !== undefined ? layoutData.global.bgHeight : 100;
            document.getElementById('lbl-bg-height').innerText = inpFBgHeight.value + "%";
            inpFBgPosX.value = layoutData.global.bgPosX !== undefined ? layoutData.global.bgPosX : 50;
            document.getElementById('lbl-bg-pos-x').innerText = inpFBgPosX.value + "%";
            inpFBgPosY.value = layoutData.global.bgPosY !== undefined ? layoutData.global.bgPosY : 50;
            document.getElementById('lbl-bg-pos-y').innerText = inpFBgPosY.value + "%";

            inpGNameSize.value = layoutData.global.nameSize || 1.0;
            lblGNameSize.innerText = inpGNameSize.value;
            inpGPriceSize.value = layoutData.global.priceSize || 1.8;
            lblGPriceSize.innerText = inpGPriceSize.value;

            const gWidth = layoutData.global.width || 2800;
            const gHeight = layoutData.global.height || 1250;
            const gGridWidth = layoutData.global.gridWidth || 1800;
            const gRowH = layoutData.global.rowHeight || 0;
            const gCols = layoutData.global.cols || 3;

            document.getElementById("prop-global-cols").value = gCols;
            document.getElementById("inp-global-cols").value = gCols;
            document.getElementById("prop-global-width").value = gWidth;
            document.getElementById("inp-global-width").value = gWidth;
            document.getElementById("prop-global-height").value = gHeight;
            document.getElementById("inp-global-height").value = gHeight;
            document.getElementById("prop-global-grid-width").value = gGridWidth;
            document.getElementById("inp-global-grid-width").value = gGridWidth;
            document.getElementById("prop-global-row-height").value = gRowH;
            document.getElementById("inp-global-row-height").value = gRowH;
            
            inpBgRepeat.value = layoutData.global.bgRepeat || "no-repeat";

        } else if (type && type.startsWith("cell_")) {
            const cell = layoutData.grid.find(c => c.id === type);
            if (!cell) return;
            selectedType = type;

            const cellNode = document.getElementById(type);
            if(cellNode) cellNode.classList.add("selected");
            
            // Gestione Accordion: Espandi sezione Casella
            document.getElementById('item-cell-props').classList.remove('d-none');
            const coll = document.getElementById('collapseCell');
            if(coll) bootstrap.Collapse.getOrCreateInstance(coll).show();

            document.getElementById("lbl-cell-id").innerText = "#" + type.split("_")[1];
            
            inpCName.value = cell.name || "";
            inpCCode.value = cell.code || "";
            inpCPrice.value = cell.price || "";
            inpCImg.value = cell.img || "";
            inpCImgZoom.value = cell.imgZoom || 100;
            inpCBgColor.value = cell.bgColor || "#ffffff";
            inpCBgTransparent.checked = (cell.bgTransparent !== false);
            inpCNameColor.value = cell.nameColor || "#000000";
            inpCPriceColor.value = cell.priceColor || "#e60000";
            inpCLayout.value = cell.cellLayout || "vertical";
            inpCScadenza.value = cell.scadenza || "";
            inpCPricePos.value = cell.pricePos || "below";
            inpCBadgePos.value = cell.badgePos || "bottom-right";
            inpCBadgeStyle.value = cell.badgeStyle || "none";
            inpCBadgeZoom.value = cell.badgeZoom || 100;

            // Padding specifici cella
            inpCPadTop.value = cell.cellPadTop !== undefined ? cell.cellPadTop : 15;
            lblCPadTop.innerText = inpCPadTop.value;
            inpCPadBot.value = cell.cellPadBot !== undefined ? cell.cellPadBot : 15;
            lblCPadBot.innerText = inpCPadBot.value;

            // Nuovi controlli Immagine
            const imgZoom = cell.imgZoom || 100;
            const imgRotate = cell.imgRotate !== undefined ? cell.imgRotate : 0;
            const imgX = cell.imgX !== undefined ? cell.imgX : 0;
            const imgY = cell.imgY !== undefined ? cell.imgY : 0;

            document.getElementById("prop-cell-img-zoom").value = imgZoom;
            document.getElementById("inp-cell-img-zoom").value = imgZoom;

            document.getElementById("prop-cell-img-rotate").value = imgRotate;
            document.getElementById("inp-cell-img-rotate").value = imgRotate;

            document.getElementById("prop-cell-img-x").value = imgX;
            document.getElementById("inp-cell-img-x").value = imgX;

            document.getElementById("prop-cell-img-y").value = imgY;
            document.getElementById("inp-cell-img-y").value = imgY;

            document.getElementById("overlay-options").style.display = (inpCLayout.value === "overlay") ? "block" : "none";
            syncCellAlignButtons(cell.textAlign || "center");
        }
    }

    function syncHeaderButtons() {
        document.querySelectorAll(".btn-logo-pos").forEach(btn => {
            if(btn.dataset.pos === layoutData.header.logoPos) {
                btn.classList.replace("btn-outline-secondary", "btn-primary");
                btn.classList.add("text-white");
            } else {
                btn.classList.replace("btn-primary", "btn-outline-secondary");
                btn.classList.remove("text-white");
            }
        });
        document.querySelectorAll(".btn-title-pos").forEach(btn => {
            if(btn.dataset.pos === layoutData.header.titlePos) {
                btn.classList.replace("btn-outline-secondary", "btn-primary");
                btn.classList.add("text-white");
            } else {
                btn.classList.replace("btn-primary", "btn-outline-secondary");
                btn.classList.remove("text-white");
            }
        });
    }

    function syncCellAlignButtons(align) {
        document.querySelectorAll(".btn-cell-align").forEach(btn => {
            if(btn.dataset.align === align) {
                btn.classList.replace("btn-outline-secondary", "btn-primary");
                btn.classList.add("text-white");
            } else {
                btn.classList.replace("btn-primary", "btn-outline-secondary");
                btn.classList.remove("text-white");
            }
        });
    }


    headerContainer.addEventListener("click", () => selectElement("header"));

    // Binding inputs Header
    [inpHTitle, inpHColor, inpHSize, inpHLogo, inpHLogoSize].forEach(inp => {
        inp.addEventListener("input", () => {
            layoutData.header.title = inpHTitle.value;
            layoutData.header.titleColor = inpHColor.value;
            layoutData.header.titleSize = parseInt(inpHSize.value) || 32;
            layoutData.header.logoUrl = inpHLogo.value;
            layoutData.header.logoSize = parseInt(inpHLogoSize.value) || 100;
            if(inp === inpHLogoSize) {
                lblHLogoSize.innerText = inpHLogoSize.value + "%";
            }
            renderHeader();
        });
    });
    
    document.querySelectorAll(".btn-logo-pos").forEach(btn => {
        btn.addEventListener("click", () => {
            layoutData.header.logoPos = btn.dataset.pos;
            renderHeader();
            selectElement("header"); // Aggiorna UI bottoni
        });
    });

    document.querySelectorAll(".btn-title-pos").forEach(btn => {
        btn.addEventListener("click", () => {
            layoutData.header.titlePos = btn.dataset.pos;
            renderHeader();
            selectElement("header"); // Aggiorna UI bottoni
        });
    });

    // --- UPLOAD IMMAGINE HEADER (LOGO) ---
    const btnUploadLogo = document.getElementById('btn-upload-logo');
    const fileLogo = document.getElementById('file-upload-logo');
    
    btnUploadLogo.addEventListener('click', () => fileLogo.click());
    
    fileLogo.addEventListener('change', async (e) => {
        if(!e.target.files.length) return;
        const file = e.target.files[0];
        
        btnUploadLogo.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
        btnUploadLogo.disabled = true;
        
        const fd = new FormData();
        fd.append("image", file);
        
        try {
            const resp = await fetch("{{ url_for('api_upload_image') }}", { method: 'POST', body: fd });
            const data = await resp.json();
            if(data.status === 'ok') {
                inpHLogo.value = data.url;
                // Triggera l'evento input per aggiornare il JSON e il Canvas
                inpHLogo.dispatchEvent(new Event('input'));
            } else {
                alert("Errore caricamento: " + data.message);
            }
        } catch(err) {
            console.error(err);
            alert("Errore di rete durante l'upload");
        } finally {
            btnUploadLogo.innerHTML = '<i class="bi bi-upload"></i>';
            btnUploadLogo.disabled = false;
            fileLogo.value = '';
        }
    });

    // Binding inputs Cell Content
    [inpCName, inpCCode, inpCPrice, inpCImg, inpCImgZoom, inpCBgColor, inpCBgTransparent, inpCNameColor, inpCPriceColor, inpCLayout, inpCScadenza, inpCPricePos, inpCBadgePos, inpCBadgeStyle, inpCBadgeZoom].forEach(inp => {
        if(!inp) return;
        inp.addEventListener("input", () => {
            if(!selectedType || !selectedType.startsWith("cell_")) return;
            const cell = layoutData.grid.find(c => c.id === selectedType);
            if(cell) {
                cell.name = inpCName.value;
                cell.code = inpCCode.value;
                cell.price = inpCPrice.value;
                cell.img = inpCImg.value;
                cell.imgZoom = parseInt(inpCImgZoom.value) || 100;
                cell.bgColor = inpCBgColor.value;
                cell.bgTransparent = inpCBgTransparent.checked;
                cell.nameColor = inpCNameColor.value;
                cell.priceColor = inpCPriceColor.value;
                cell.cellLayout = inpCLayout.value;
                if(inpCScadenza) cell.scadenza = inpCScadenza.value;
                cell.pricePos = inpCPricePos.value;
                if(inpCBadgePos) cell.badgePos = inpCBadgePos.value;
                if(inpCBadgeStyle) cell.badgeStyle = inpCBadgeStyle.value;
                if(inpCBadgeZoom) cell.badgeZoom = parseInt(inpCBadgeZoom.value) || 100;
                
                const ovlOpt = document.getElementById('overlay-options');
                if(ovlOpt) {
                    ovlOpt.style.display = (inpCLayout.value === 'overlay') ? 'block' : 'none';
                }
                
                renderGrid();
            }
        });
    });
    document.querySelectorAll(".btn-cell-align").forEach(btn => {
        btn.addEventListener("click", () => {
            if(!selectedType || !selectedType.startsWith("cell_")) return;
            const cell = layoutData.grid.find(c => c.id === selectedType);
            if(cell) {
                cell.textAlign = btn.dataset.align;
                renderGrid();
                selectElement(selectedType); // per aggiornare bottoni
            }
        });
    });

    // --- UPLOAD IMMAGINE CELLA (PRODOTTO) ---
    const btnUploadCellImg = document.getElementById('btn-upload-cell-img');
    const fileCellImg = document.getElementById('file-upload-cell-img');
    
    btnUploadCellImg.addEventListener('click', () => fileCellImg.click());
    
    // --- FUNZIONI DI SUPPORTO PER UPLOAD / DROP ---
    async function handleFileUpload(file, targetCellId) {
        const cell = layoutData.grid.find(c => c.id === targetCellId);
        if(!cell) return;
        
        const fd = new FormData();
        fd.append("image", file);
        fd.append("remove_bg", "true");
        if(cell.productId) fd.append("prodotto_id", cell.productId);
        
        try {
            const resp = await fetch("{{ url_for('api_upload_image') }}", { method: 'POST', body: fd });
            const data = await resp.json();
            if(data.status === 'ok') {
                cell.img = data.url;
                renderGrid();
                if(selectedType === targetCellId) inpCImg.value = data.url;
                
                // Aggiorna database prodotti
                if(cell.productId) {
                    const p = prodottiData.find(x => x.id === cell.productId);
                    if(p) p.immagine = data.url;
                }
            }
        } catch(err) { console.error("Drop Upload Error:", err); }
    }

    async function handleUrlDrop(url, targetCellId) {
        const cell = layoutData.grid.find(c => c.id === targetCellId);
        if(!cell) return;
        
        try {
            const resp = await fetch("/api/salva_immagine_suggerita", {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ image_url: url, prodotto_id: cell.productId })
            });
            const data = await resp.json();
            if(data.status === 'ok') {
                cell.img = data.url;
                renderGrid();
                if(selectedType === targetCellId) inpCImg.value = data.url;
                
                // Aggiorna database prodotti
                if(cell.productId) {
                    const p = prodottiData.find(x => x.id === cell.productId);
                    if(p) p.immagine = data.url;
                }
            }
        } catch(err) { console.error("Drop URL Error:", err); }
    }

    fileCellImg.addEventListener('change', async (e) => {
        if(!e.target.files.length) return;
        const file = e.target.files[0];
        
        if(!selectedType || !selectedType.startsWith("cell_")) return;
        const targetCellId = selectedType; // Cattura ID cella corrente
        const cell = layoutData.grid.find(c => c.id === targetCellId);
        
        btnUploadCellImg.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
        btnUploadCellImg.disabled = true;
        
        const fd = new FormData();
        fd.append("image", file);
        fd.append("remove_bg", "true");
        if(cell && cell.productId) {
            fd.append("prodotto_id", cell.productId);
        }
        
        try {
            const resp = await fetch("{{ url_for('api_upload_image') }}", { method: 'POST', body: fd });
            const data = await resp.json();
            if(data.status === 'ok') {
                // Aggiorna direttamente la cella target invece di basarsi sulla selezione globale che può cambiare
                const targetCell = layoutData.grid.find(c => c.id === targetCellId);
                if (targetCell) {
                    targetCell.img = data.url;
                    renderGrid();
                    
                    // Se la cella è ancora quella selezionata, aggiorna anche l'input in sidebar
                    if (selectedType === targetCellId) {
                        inpCImg.value = data.url;
                    }
                }
                
                // Aggiorniamo anche la lista in ram prodottiData
                if(targetCell && targetCell.productId) {
                    const p = prodottiData.find(x => x.id === targetCell.productId);
                    if(p) p.immagine = data.url;
                }
            } else {
                alert("Errore caricamento: " + data.message);
            }
        } catch(err) {
            console.error(err);
            alert("Errore di rete durante l'upload");
        } finally {
            btnUploadCellImg.innerHTML = '<i class="bi bi-upload"></i>';
            btnUploadCellImg.disabled = false;
            fileCellImg.value = '';
        }
    });

    // --- SUGGERIMENTO IMMAGINE (WEB) - VERSIONE POPUP MODALE ---
    document.getElementById("btn-suggest-cell-img").addEventListener("click", async () => {
        if (!selectedType || !selectedType.startsWith("cell_")) return;
        const cell = layoutData.grid.find(c => c.id === selectedType);
        if(!cell || !cell.name) {
            alert("Inserisci un nome prodotto prima di cercare un'immagine!");
            return;
        }
        
        const modalEl = document.getElementById('modalSuggerimentiImg');
        const modal = new bootstrap.Modal(modalEl);
        modal.show();
        
        const grid = document.getElementById('gridSuggerimenti');
        const loader = document.getElementById('loaderSuggerimenti');
        
        grid.innerHTML = "";
        loader.classList.remove("d-none");
        
        try {
            const res = await fetch("/api/cerca_immagini_prodotto?q=" + encodeURIComponent(cell.name));
            const data = await res.json();
            loader.classList.add("d-none");
            
            if(data.status === "ok" && data.images && data.images.length > 0) {
                data.images.slice(0, 9).forEach(imgUrl => {
                    const div = document.createElement("div");
                    div.className = "col-4 col-md-4";
                    const pid = cell.productId ? cell.productId : 'null';
                    div.innerHTML = `
                        <div class="card h-100 border-0 shadow-sm overflow-hidden" style="cursor:pointer; border: 2px solid transparent;" 
                             onmouseover="this.style.borderColor='#0d6efd'; this.style.transform='translateY(-3px)'" 
                             onmouseout="this.style.borderColor='transparent'; this.style.transform='translateY(0)'"
                             style="transition: all 0.2s;"
                             onclick="selezionaImmagineSuggerita('${imgUrl}', ${pid})">
                            <div class="position-relative" style="height: 120px; background: white;">
                                <img src="${imgUrl}" class="w-100 h-100" style="object-fit: contain; padding: 10px;">
                            </div>
                            <div class="card-body p-1 text-center bg-white border-top">
                                <span class="small fw-bold text-primary"><i class="bi bi-check-circle-fill"></i> Scegli</span>
                            </div>
                        </div>
                    `;
                    grid.appendChild(div);
                });
            } else {
                grid.innerHTML = `
                    <div class='text-center py-4 w-100'>
                        <p class="mb-3">Nessuna immagine trovata nel sistema o su Google per "${cell.name}".</p>
                        <a href="https://www.google.com/search?q=${encodeURIComponent(cell.name)}+prodotto+pregis&tbm=isch" target="_blank" class="btn btn-outline-primary rounded-pill">
                            <i class="bi bi-google me-2"></i> Cerca manual su Google
                        </a>
                    </div>`;
            }
        } catch(e) {
            loader.classList.add("d-none");
            grid.innerHTML = "<div class='text-center py-4 w-100 text-danger'>Errore di connessione durante la ricerca web.</div>";
        }
    });

    window.selezionaImmagineSuggerita = async function(url, productId) {
        document.getElementById('loaderSuggerimenti').classList.remove("d-none");
        document.getElementById('gridSuggerimenti').innerHTML = "";
        
        try {
            const res = await fetch("/api/salva_immagine_suggerita", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prodotto_id: productId, image_url: url })
            });
            const data = await res.json();
            if(data.status === "ok") {
                const inpCImg = document.getElementById("prop-cell-img");
                inpCImg.value = data.url;
                inpCImg.dispatchEvent(new Event('input')); // Aggiorna cella
                
                if(productId) {
                    const p = prodottiData.find(x => x.id === productId);
                    if(p) p.immagine = data.url;
                }
                
                const modEl = document.getElementById('modalSuggerimentiImg');
                const modal = bootstrap.Modal.getInstance(modEl);
                if(modal) modal.hide();
            } else {
                alert("Errore download immagine: " + data.message);
                const modEl = document.getElementById('modalSuggerimentiImg');
                const modal = bootstrap.Modal.getInstance(modEl);
                if(modal) modal.hide();
            }
        } catch (e) {
            alert("Errore di rete durante il salvataggio.");
            const modEl = document.getElementById('modalSuggerimentiImg');
            const modal = bootstrap.Modal.getInstance(modEl);
            if(modal) modal.hide();
        }
        document.getElementById('loaderSuggerimenti').classList.add("d-none");
    };
    
    // --- MODIFICA RAPIDA PRODOTTI ---
    document.getElementById("btn-quick-edit").addEventListener("click", () => {
        const tbody = document.getElementById("quickEditTbody");
        if (!tbody) return;
        tbody.innerHTML = "";
        
        if (!layoutData || !layoutData.grid) {
            alert("Errore: Dati della griglia non caricati.");
            return;
        }

        layoutData.grid.forEach((cell, index) => {
            if (cell.isHidden) return; // Salta celle nascoste
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td class="fw-bold text-muted">${index + 1}</td>
                <td><input type="text" class="form-control fw-bold" id="qe-name-${cell.id}" value="${cell.name || ''}" placeholder="Nome vuoto"></td>
                <td><input type="text" class="form-control text-center fw-bold text-danger" id="qe-price-${cell.id}" value="${cell.price || ''}" placeholder="€"></td>
            `;
            tbody.appendChild(tr);
        });
        
        const modalEl = document.getElementById('modalQuickEdit');
        if (modalEl) {
            const modal = new bootstrap.Modal(modalEl);
            modal.show();
        }
    });

    document.getElementById("btn-save-quick-edit").addEventListener("click", () => {
        let changed = false;
        layoutData.grid.forEach(cell => {
            const newName = document.getElementById(`qe-name-${cell.id}`).value;
            const newPrice = document.getElementById(`qe-price-${cell.id}`).value;
            
            if (cell.name !== newName || cell.price !== newPrice) {
                cell.name = newName;
                cell.price = newPrice;
                changed = true;
            }
        });
        
        if (changed) {
            renderLayout();
            if(selectedType && selectedType.startsWith("cell_")) {
                loadProperties(selectedType); // Aggiorna sidebar se una cella è selezionata
            }
        }
        
        const modEl = document.getElementById('modalQuickEdit');
        const modal = bootstrap.Modal.getInstance(modEl);
        if(modal) modal.hide();
    });

    // Svuota cella
    document.getElementById("btn-empty-cell").addEventListener("click", () => {
        if(!selectedType || !selectedType.startsWith("cell_")) return;
        const cell = layoutData.grid.find(c => c.id === selectedType);
        if(cell) {
            cell.productId = null;
            cell.name = "";
            cell.price = "";
            cell.img = "";
            renderGrid();
            selectElement(selectedType); // per aggiornare input fields
        }
    });

    // Modifica Forma Casella (ColSpan / RowSpan)
    document.querySelectorAll(".btn-shape").forEach(btn => {
        btn.addEventListener("click", () => {
            if(!selectedType || !selectedType.startsWith("cell_")) return;
            const cellIdx = layoutData.grid.findIndex(c => c.id === selectedType);
            const cell = layoutData.grid[cellIdx];
            
            const reqCol = parseInt(btn.dataset.col);
            const reqRow = parseInt(btn.dataset.row);

            if(reqCol > 0) cell.colSpan = reqCol;
            if(reqRow > 0) cell.rowSpan = reqRow;

            // Logica semplificata per nascondere celle adiacenti e far spazio (InPublish style)
            // Se occupo 2 colonne, nascondo la cella successiva.
            // Reset hiding first
            layoutData.grid.forEach(c => c.isHidden = false);
            
            for(let i=0; i<layoutData.grid.length; i++) {
                const c = layoutData.grid[i];
                if(c.colSpan > 1) {
                    for(let step=1; step < c.colSpan; step++) {
                        if(i+step < layoutData.grid.length) layoutData.grid[i+step].isHidden = true;
                    }
                }
                // Row span nasconde celle della riga sotto (+3 in una griglia 3x3)
                if(c.rowSpan > 1) {
                     for(let step=1; step < c.rowSpan; step++) {
                         let targetIdx = i + (3 * step);
                         if(targetIdx < layoutData.grid.length) layoutData.grid[targetIdx].isHidden = true;
                     }
                }
            }

            renderGrid();
            selectElement(selectedType);
        });
    });


    // --- ZOOM ---
    let zoom = 0.8; // User requested 80% default zoom
    const canvas = document.getElementById("flyer-canvas");
    function setZoom(val) {
        zoom = val;
        canvas.style.transform = `scale(${zoom})`;
        document.getElementById('zoom-level').innerText = Math.round(zoom * 100) + '%';
    }
    document.getElementById("btn-zoom-in").addEventListener("click", () => setZoom(Math.min(zoom + 0.1, 2.0)));
    document.getElementById("btn-zoom-out").addEventListener("click", () => setZoom(Math.max(zoom - 0.1, 0.1)));
    
    // Fit to container on load
    setTimeout(() => {
        // Forza lo zoom iniziale all'80% ESATTO come richiesto dall'utente, ignorando la larghezza schermo
        setZoom(0.80);
    }, 100);

    function renderLayout() {
        renderHeader();
        renderGrid();
        renderBackground();
    }
    
    // INIT
    renderLayout();
    try { updatePaginationUI(); } catch(e){}
    loadLibraryBackgrounds();

    // --- SALVATAGGIO E EXPORT ---
    async function captureCanvas() {
        selectElement(null);
        const currentZoom = zoom;
        
        // Forza zoom a 1.0 e togli transform per html2canvas
        const oldTransform = canvas.style.transform;
        const oldTransition = canvas.style.transition;
        
        canvas.style.transition = 'none';
        canvas.style.transform = 'none';
        
        // Aggiungiamo classe per nascondere i bordi durante export
        canvas.classList.add('exporting');
        
        // Aspettiamo che il DOM ricarichi a pieno le dimensioni e l'immagine
        await new Promise(r => setTimeout(r, 400));
        
        const canvasHtml = document.getElementById("flyer-canvas");
        const w = canvasHtml.offsetWidth;
        const h = canvasHtml.offsetHeight;
        
        return new Promise((resolve, reject) => {
            html2canvas(canvasHtml, { 
                scale: 3, // Qualità Super (300dpi approx)
                useCORS: true, 
                allowTaint: false,
                width: w,
                height: h,
                logging: false,
                backgroundColor: '#ffffff'
            }).then(canvasRender => {
                canvas.classList.remove('exporting');
                canvas.style.transform = oldTransform;
                canvas.style.transition = oldTransition;
                resolve(canvasRender);
            }).catch(err => {
                canvas.classList.remove('exporting');
                canvas.style.transform = oldTransform;
                canvas.style.transition = oldTransition;
                console.error("html2canvas error:", err);
                reject(err);
            });
        });
    }

    document.getElementById("btn-export-png").addEventListener("click", async function() {
        const btn = this;
        const oldHtml = btn.innerHTML;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> Calcolo...`;
        btn.disabled = true;
        try {
            if (saveCurrentPageToDoc) { try { saveCurrentPageToDoc(); } catch(e){} }
            const currIdx = currentPageIndex;
            const renderedCanvases = [];
            
            for (let p = 0; p < currentDocPages.length; p++) {
                btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> Render Pag. ${p+1}...`;
                layoutData = currentDocPages[p];
                renderLayout();
                await new Promise(r => setTimeout(r, 300));
                const canvasRender = await captureCanvas();
                renderedCanvases.push(canvasRender);
            }
            
            // Restore original page
            currentPageIndex = currIdx;
            layoutData = currentDocPages[currentPageIndex];
            renderLayout();
            if (updatePaginationUI) { try { updatePaginationUI(); } catch(e){} }
            
            // Combine all canvases vertically
            const totalWidth = Math.max(...renderedCanvases.map(c => c.width));
            let totalHeight = renderedCanvases.reduce((sum, c) => sum + c.height, 0);
            
            // Limit per evitare crash in browser con limiti canvas (es. 16k o 32k)
            const MAX_CANVAS_HEIGHT = 20000;
            let finalScale = 1.0;
            if (totalHeight > MAX_CANVAS_HEIGHT) {
                finalScale = MAX_CANVAS_HEIGHT / totalHeight;
                totalHeight = MAX_CANVAS_HEIGHT;
            }

            const combined = document.createElement("canvas");
            combined.width = totalWidth * finalScale;
            combined.height = totalHeight;
            const ctx = combined.getContext("2d");
            ctx.fillStyle = "#ffffff";
            ctx.fillRect(0, 0, combined.width, combined.height);
            
            let yOffset = 0;
            for (const c of renderedCanvases) {
                const drawH = c.height * finalScale;
                ctx.drawImage(c, 0, 0, c.width, c.height, 0, yOffset, combined.width, drawH);
                yOffset += drawH;
            }
            
            const link = document.createElement('a');
            link.download = (document.getElementById("volantino-nome").value || 'volantino') + '.png';
            link.href = combined.toDataURL('image/png', 0.9);
            link.click();
        } catch(e) { 
            alert("Errore generazione PNG:\n" + (e.message || e)); 
            console.error("PNG error:", e);
        }
        btn.innerHTML = oldHtml;
        btn.disabled = false;
    });

    document.getElementById("btn-export-pdf").addEventListener("click", async function() {
        const btn = this;
        const oldHtml = btn.innerHTML;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> Render...`;
        btn.disabled = true;
        try {
            const { jsPDF } = window.jspdf;
            
            if (saveCurrentPageToDoc) { try { saveCurrentPageToDoc(); } catch(e){} }
            const currIdx = currentPageIndex;
            
            // Temporaneamente raccogliamo i dati delle pagine in alta qualità
            const pagesImgs = [];
            for (let p=0; p<currentDocPages.length; p++) {
                btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> Render Pag. ${p+1}...`;
                layoutData = currentDocPages[p];
                renderLayout();
                await new Promise(r => setTimeout(r, 300));
                const canvasRender = await captureCanvas();
                pagesImgs.push({
                   data: canvasRender.toDataURL('image/jpeg', 0.95),
                   w: canvasRender.width,
                   h: canvasRender.height
                });
            }

            // Inizializza PDF basandosi sulla prima pagina (auto-orientamento)
            const first = pagesImgs[0];
            const orientation = first.w > first.h ? 'l' : 'p';
            const pdf = new jsPDF(orientation, 'mm', 'a4');
            const pdfWidth = pdf.internal.pageSize.getWidth();
            const pdfHeight = pdf.internal.pageSize.getHeight();
            
            for (let p=0; p<pagesImgs.length; p++) {
                const img = pagesImgs[p];
                if (p > 0) pdf.addPage();
                
                // Calcola dimensioni per riempire la pagina A4 mantenendo l'aspetto
                const ratio = img.w / img.h;
                let drawW = pdfWidth;
                let drawH = pdfWidth / ratio;
                
                // Se l'immagine è troppo alta per una singola pagina A4, scaliamo per farla entrare 
                // (Oppure la dividiamo, ma per i volantini di solito si vuole una pagina intera)
                if (drawH > pdfHeight) {
                    drawH = pdfHeight;
                    drawW = pdfHeight * ratio;
                }
                
                // Centra l'immagine nella pagina
                const xOff = (pdfWidth - drawW) / 2;
                const yOff = (pdfHeight - drawH) / 2;
                
                pdf.addImage(img.data, 'JPEG', xOff, yOff, drawW, drawH);
            }
            
            currentPageIndex = currIdx;
            layoutData = currentDocPages[currentPageIndex];
            renderLayout();
            if (updatePaginationUI) { try { updatePaginationUI(); } catch(e){} }
            
            pdf.save((document.getElementById("volantino-nome").value || 'volantino') + '.pdf');
        } catch(e) { 
            alert("Errore generazione PDF:\n" + (e.message || e)); 
            console.error("PDF error:", e);
        }
        btn.innerHTML = oldHtml;
        btn.disabled = false;
    });

    document.getElementById("btn-save").addEventListener("click", async function() {
        const btn = this;
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> Salvataggio...`;
        
        try {
            const canvasRender = await captureCanvas();
            
            // Ridimensiona il thumbnail per evitare payload troppo grandi
            // (specialmente per volantini multi-pagina con promo mensile)
            const MAX_THUMB_WIDTH = 800;
            let thumbBase64;
            if (canvasRender.width > MAX_THUMB_WIDTH) {
                const scale = MAX_THUMB_WIDTH / canvasRender.width;
                const thumbCanvas = document.createElement("canvas");
                thumbCanvas.width = Math.round(canvasRender.width * scale);
                thumbCanvas.height = Math.round(canvasRender.height * scale);
                const thumbCtx = thumbCanvas.getContext("2d");
                thumbCtx.drawImage(canvasRender, 0, 0, thumbCanvas.width, thumbCanvas.height);
                thumbBase64 = thumbCanvas.toDataURL("image/jpeg", 0.5);
            } else {
                thumbBase64 = canvasRender.toDataURL("image/jpeg", 0.5);
            }

            try { saveCurrentPageToDoc(); } catch(e){}
            let payloadLayout = currentDocPages.length > 1 ? { isMultiPage: true, pages: currentDocPages } : currentDocPages[0];

            const payload = {
                id: volantinoId,
                nome: document.getElementById("volantino-nome").value || "Volantino Griglia",
                layout: payloadLayout,
                thumbnail: thumbBase64,
                tipo: "{{ tipo_volantino if tipo_volantino else 'standard' }}"
            };

            const payloadStr = JSON.stringify(payload);
            console.log("Payload size:", (payloadStr.length / 1024 / 1024).toFixed(2), "MB");

            const resp = await fetch("{{ url_for('salva_volantino_beta') }}", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: payloadStr
            });
            
            // Gestione robusta della risposta (potrebbe non essere JSON in caso di errore server)
            let data;
            const respText = await resp.text();
            try {
                data = JSON.parse(respText);
            } catch(parseErr) {
                console.error("Risposta non JSON dal server:", resp.status, respText.substring(0, 200));
                alert("Errore server (HTTP " + resp.status + "). Il volantino potrebbe essere troppo grande. Riprova.");
                return;
            }
            
            if (data.ok) {
                if (!volantinoId && data.id) {
                    window.location.href = "{{ url_for('beta_volantino_modifica', id=0) }}".replace("0", data.id);
                } else {
                    document.getElementById("save-status").classList.remove("d-none");
                    setTimeout(() => document.getElementById("save-status").classList.add("d-none"), 3000);
                }
            } else {
                alert("Errore salva: " + (data.message || 'sconosciuto'));
            }
        } catch(err) {
            console.error("Errore salvataggio volantino:", err);
            alert("Errore salvataggio: " + (err.message || "Errore sconosciuto. Controlla la console."));
        } finally {
            btn.disabled = false;
            btn.innerHTML = `<i class="bi bi-save"></i> Salva`;
        }
    });

});
