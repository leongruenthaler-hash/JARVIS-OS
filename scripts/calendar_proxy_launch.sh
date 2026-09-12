#!/bin/zsh
#
# Headless-Start des Jarvis-Kalender-Proxys auf dem Mac Mini. Siehe
# scripts/calendar_proxy_server.py fuer den Grund.
#
# Aufruf: per LaunchAgent (siehe com.leon.jarvis.calendarproxy.plist im
# selben Ordner) automatisch bei jedem Login starten lassen. Manuell testen:
# einfach direkt ausfuehren.

set -e

# Repo-Wurzel = Elternordner dieses Skripts (scripts/calendar_proxy_launch.sh -> Repo-Root)
SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
VENV_DIR="$REPO_ROOT/.venv"

LOG_DIR="$HOME/Library/Logs/JarvisCalendarProxy"
mkdir -p "$LOG_DIR"
exec >"$LOG_DIR/launch.log" 2>&1

echo "[$(date)] Starte Jarvis-Kalender-Proxy..."

if [ ! -x "$VENV_DIR/bin/python3" ]; then
    echo "Lege venv an unter $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install -r "$REPO_ROOT/requirements.txt"
fi

exec "$VENV_DIR/bin/python3" "$SCRIPT_DIR/calendar_proxy_server.py"
