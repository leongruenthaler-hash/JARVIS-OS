#!/bin/zsh
#
# Headless-Start des VOLLEN Jarvis-Backends auf dem Mac Mini (Plan "Jarvis
# proaktiv machen", Phase 2, 2026-09-05) - loest scripts/remote_worker_launch.sh
# ab, das nur einen stark eingeschraenkten Hintergrund-Worker startete (siehe
# app/remote_worker_server.py). Der Mac Mini ist ab jetzt das einzige "Gehirn":
# Gedaechtnis, Gespraech, LLM-Routing, alle Faehigkeiten. MacBook/iPhone werden
# duenne Clients, die sich ueber Tailscale hierher verbinden.
#
# Aufruf: per LaunchAgent (siehe com.leon.jarvis.macmini.plist im selben
# Ordner) automatisch bei jedem Login starten lassen. Manuell testen: direkt
# ausfuehren.

set -e

# Repo-Wurzel = Elternordner dieses Skripts (scripts/mac_mini_launch.sh -> Repo-Root)
SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
BACKEND_DIR="$REPO_ROOT/app"
VENV_DIR="$REPO_ROOT/.venv"

LOG_DIR="$HOME/Library/Logs/JarvisMacMini"
mkdir -p "$LOG_DIR"
exec >"$LOG_DIR/launch.log" 2>&1

echo "[$(date)] Starte Jarvis (volles Backend, Mac-Mini-Gehirn)..."
cd "$BACKEND_DIR"

# venv einmalig anlegen, falls noch nicht vorhanden
if [ ! -x "$VENV_DIR/bin/python3" ]; then
    echo "Lege venv an unter $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install -r "$REPO_ROOT/requirements.txt"
fi

# System-Ollama muss laufen (auf dem Mac Mini normal installiert, kein
# gebuendelter Ollama-Fallback wie bei der GUI-App)
OLLAMA_URL="http://127.0.0.1:11434/api/tags"
if ! /usr/bin/curl -fsS --max-time 2 "$OLLAMA_URL" >/dev/null 2>&1; then
    echo "Starte Ollama..."
    if command -v ollama >/dev/null 2>&1; then
        nohup ollama serve >/tmp/jarvis_mac_mini_ollama.log 2>&1 &
    elif [ -d "/Applications/Ollama.app" ]; then
        /usr/bin/open -a Ollama >/tmp/jarvis_mac_mini_ollama.log 2>&1 &
    else
        echo "WARNUNG: Ollama nicht gefunden - lokaler Fallback wird fehlschlagen."
    fi
    for _ in $(seq 1 15); do
        if /usr/bin/curl -fsS --max-time 2 "$OLLAMA_URL" >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
fi

echo "Starte volles Backend (--local-server)..."
exec "$VENV_DIR/bin/python3" "$BACKEND_DIR/jarvis.py" --local-server
