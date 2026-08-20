#!/bin/zsh
#
# Headless-Start des Mac-Mini-Workers (Fotoindex + Mail-Hintergrundscan).
# Siehe plans/... "Jarvis Mac-Mini-Worker".
#
# Anders als der Start ueber die JarvisApp-GUI (LocalServerController.swift)
# brauchen wir hier keinen Health-Check-Neustart-Loop und keinen gebuendelten
# Ollama-Fallback - das uebernimmt launchd (KeepAlive) bzw. eine normale
# System-Ollama-Installation auf dem Mac Mini (siehe Voraussetzungen im Plan).
#
# Aufruf: dieses Skript per LaunchAgent (siehe
# com.leon.jarvis.remoteworker.plist im selben Ordner) automatisch bei jedem
# Login starten lassen. Manuell testen: einfach direkt ausfuehren.

set -e

# Repo-Wurzel = Elternordner dieses Skripts (scripts/remote_worker_launch.sh -> Repo-Root)
SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
BACKEND_DIR="$REPO_ROOT/app"
VENV_DIR="$REPO_ROOT/.venv"

LOG_DIR="$HOME/Library/Logs/JarvisRemoteWorker"
mkdir -p "$LOG_DIR"
exec >"$LOG_DIR/launch.log" 2>&1

echo "[$(date)] Starte Jarvis Remote Worker..."
cd "$BACKEND_DIR"

# venv einmalig anlegen, falls noch nicht vorhanden
if [ ! -x "$VENV_DIR/bin/python3" ]; then
    echo "Lege venv an unter $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install -r "$REPO_ROOT/requirements.txt"
fi

# System-Ollama muss laufen (auf dem Mac Mini normal installiert, siehe
# Voraussetzungen im Plan - kein gebuendelter Ollama-Fallback wie bei der GUI-App)
OLLAMA_URL="http://127.0.0.1:11434/api/tags"
if ! /usr/bin/curl -fsS --max-time 2 "$OLLAMA_URL" >/dev/null 2>&1; then
    echo "Starte Ollama..."
    if command -v ollama >/dev/null 2>&1; then
        nohup ollama serve >/tmp/jarvis_remote_worker_ollama.log 2>&1 &
    elif [ -d "/Applications/Ollama.app" ]; then
        /usr/bin/open -a Ollama >/tmp/jarvis_remote_worker_ollama.log 2>&1 &
    else
        echo "WARNUNG: Ollama nicht gefunden - Fotos-Vision-Analyse wird fehlschlagen."
    fi
    for _ in $(seq 1 15); do
        if /usr/bin/curl -fsS --max-time 2 "$OLLAMA_URL" >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
fi

echo "Starte Backend im Worker-Modus..."
exec "$VENV_DIR/bin/python3" "$BACKEND_DIR/jarvis.py" --remote-worker
