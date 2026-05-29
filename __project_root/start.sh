#!/bin/bash

echo "Avvio Gestionale Horeca..."

# Ottieni la cartella dello script (__project_root)
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Percorso ai template (dentro __project_root)
TEMPLATE_FOLDER="$PROJECT_ROOT/_templates"

# Controllo che la cartella _templates esista
if [ ! -d "$TEMPLATE_FOLDER" ]; then
    echo "❌ Cartella _templates non trovata in $TEMPLATE_FOLDER"
    exit 1
fi

# Attiva il virtual environment se esiste
VENV_PATH="$(dirname "$PROJECT_ROOT")/venv"
if [ -f "$VENV_PATH/bin/activate" ]; then
    echo "Attivazione virtual environment in $VENV_PATH..."
    source "$VENV_PATH/bin/activate"
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
