#!/bin/zsh
#
# Headless-Start des Jarvis-TTS-Proxys (Edge-TTS via edge_tts-Bibliothek) auf
# dem Mac Mini. Siehe scripts/tts_proxy_server.py fuer den Grund.
#
# Aufruf: per LaunchAgent (siehe com.leon.jarvis.ttsproxy.plist im selben
# Ordner) automatisch bei jedem Login starten lassen. Manuell testen: einfach
# direkt ausfuehren.

set -e

# Repo-Wurzel = Elternordner dieses Skripts (scripts/tts_proxy_launch.sh -> Repo-Root)
SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
VENV_DIR="$REPO_ROOT/.venv"

LOG_DIR="$HOME/Library/Logs/JarvisTTSProxy"
mkdir -p "$LOG_DIR"
exec >"$LOG_DIR/launch.log" 2>&1

echo "[$(date)] Starte Jarvis TTS-Proxy..."

# Dieselbe venv wie der Remote-Worker/Server (app/requirements.txt enthaelt
# edge-tts bereits) - falls sie noch nicht existiert, hier anlegen statt eine
# zweite, separate venv zu pflegen.
if [ ! -x "$VENV_DIR/bin/python3" ]; then
    echo "Lege venv an unter $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install -r "$REPO_ROOT/requirements.txt"
fi

exec "$VENV_DIR/bin/python3" "$SCRIPT_DIR/tts_proxy_server.py"
