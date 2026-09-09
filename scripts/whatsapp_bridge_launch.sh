#!/bin/zsh
#
# Headless-Start der eigenen Jarvis-WhatsApp-Bridge (Baileys) auf dem
# Mac Mini. Siehe whatsapp-bridge/index.mjs fuer den Grund (Ersatz fuer den
# defekten ClawHub-Skill @0xs4m1337/openclaw-whatsapp).
#
# Aufruf: per LaunchAgent (siehe com.leon.jarvis.whatsappbridge.plist im
# selben Ordner) automatisch bei jedem Login starten lassen. Manuell
# testen: einfach direkt ausfuehren.

set -e

# Repo-Wurzel = Elternordner dieses Skripts (scripts/whatsapp_bridge_launch.sh -> Repo-Root)
SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
BRIDGE_DIR="$REPO_ROOT/whatsapp-bridge"

LOG_DIR="$HOME/Library/Logs/JarvisWhatsAppBridge"
mkdir -p "$LOG_DIR"
exec >"$LOG_DIR/launch.log" 2>&1

echo "[$(date)] Starte Jarvis-WhatsApp-Bridge..."

if [ ! -d "$BRIDGE_DIR/node_modules" ]; then
    echo "Installiere Node-Abhaengigkeiten unter $BRIDGE_DIR ..."
    (cd "$BRIDGE_DIR" && npm install --omit=dev)
fi

exec node "$BRIDGE_DIR/index.mjs"
