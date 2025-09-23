#!/bin/bash

echo "Avvio Gestionale Horeca..."

# Ottieni la cartella dello script (__project_root)
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Percorso ai template (fuori da __project_root)
TEMPLATE_FOLDER="$(dirname "$PROJECT_ROOT")/_templates"

# Controllo che la cartella _templates esista
if [ ! -d "$TEMPLATE_FOLDER" ]; then
    echo "❌ Cartella _templates non trovata in $TEMPLATE_FOLDER"
    exit 1
fi

# Esporta le variabili ambiente Flask
export FLASK_APP="$PROJECT_ROOT/app.py"
export FLASK_ENV=development

# Forza Flask a usare il template folder corretto
export FLASK_RUN_EXTRA_FILES="$TEMPLATE_FOLDER"

# Avvia Flask con Python 3
python3 "$FLASK_APP"

echo "Sei uscito dall'app Flask. Premi INVIO per chiudere."
read
