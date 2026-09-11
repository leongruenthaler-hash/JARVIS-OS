#!/bin/zsh
#
# Headless-Start des Jarvis-Gateway-Aktivitaets-Proxys auf dem Mac Mini. Siehe
# scripts/gateway_activity_proxy.mjs fuer den Grund.

set -e

# launchd startet Prozesse mit einem minimalen PATH ohne Homebrews bin-Verzeichnisse -
# node ist darin sonst "command not found" (gleiche Falle wie whatsapp_bridge_launch.sh).
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"

LOG_DIR="$HOME/Library/Logs/JarvisGatewayActivityProxy"
mkdir -p "$LOG_DIR"
exec >"$LOG_DIR/launch.log" 2>&1

echo "[$(date)] Starte Jarvis-Gateway-Aktivitaets-Proxy..."

exec node "$SCRIPT_DIR/gateway_activity_proxy.mjs"
