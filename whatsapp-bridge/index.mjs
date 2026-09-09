// Eigener WhatsApp-Bridge-Dienst fuer Jarvis (2026-09-09).
//
// Ersetzt den ClawHub-Skill @0xs4m1337/openclaw-whatsapp: dessen Go-Binary
// hat den QR-Code zwar angezeigt, aber nie eine echte WebSocket-Verbindung
// zu WhatsApps Servern aufgebaut ("QR code timed out" nach 2-4s statt der
// ueblichen 20-60s) - ein bekannter, als "stale" geschlossener Bug ohne
// Fix. Baileys (diese Bibliothek) ist dagegen die aktiv gepflegte
// Referenzimplementierung des WhatsApp-Multi-Device-Protokolls, auf der
// tausende Produktiv-Bots laufen.
//
// Architektur: dieser Prozess haelt selbst die WhatsApp-Verbindung. Jede
// eingehende Direktnachricht wird geloggt und an OpenClaws Gateway
// (dieselbe lokale Instanz, die auch JarvisMobile/JarvisApp fuer Chat
// nutzen - Port 18789) weitergereicht; die Agenten-Logik dort hat bereits
// Kalender-Werkzeugzugriff (siehe JarvisMobile-Migration), es braucht also
// keinen eigenen Kalender-Code hier. Die Antwort wird zurueck an WhatsApp
// gesendet.

import { makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } from '@whiskeysockets/baileys'
import qrcodeTerminal from 'qrcode-terminal'
import pino from 'pino'
import { appendFileSync, mkdirSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import path from 'node:path'

const DATA_DIR = path.join(homedir(), '.jarvis-whatsapp')
const AUTH_DIR = path.join(DATA_DIR, 'auth')
const LOG_FILE = path.join(DATA_DIR, 'messages.jsonl')
const GATEWAY_URL = 'http://127.0.0.1:18789/v1/chat/completions'

mkdirSync(AUTH_DIR, { recursive: true })

// EINMALIG beim Prozessstart gesetzt, nicht pro Reconnect - sonst geht eine
// Nachricht verloren, wenn sie genau waehrend eines Reconnects eintrifft
// (Baileys liefert sie danach mit ihrem urspruenglichen, "alten" Zeitstempel
// nach - ein pro-start() neu gesetztes startedAt haette sie faelschlich als
// Verlauf-vor-dem-Start verworfen; live beobachtet 2026-09-09).
const STARTED_AT = Date.now()

// Wortlaut 1:1 wie vom Nutzer vorgegeben (2026-09-09) - bewusst nicht
// umformuliert, damit die Standard-Antwort exakt dem entspricht, was
// zugesagt wurde.
const OPERATING_INSTRUCTIONS = `Du bist Jarvis, der persoenliche WhatsApp-Assistent von Herrn Gruenthaler.
Du gibst dich NIE als Herr Gruenthaler selbst aus - mach in JEDER Antwort
klar erkennbar, dass du sein Assistent Jarvis bist.

STANDARDFALL (kein konkreter Terminvorschlag mit Tag UND Uhrzeit erkennbar):
Antworte NUR mit exakt diesem Satz, sonst nichts:
"Guten Tag, hier ist Jarvis, der persoenliche Assistent von Herrn
Gruenthaler. Ich werde ihm ueber Ihre Nachricht Bescheid geben, und er
wird sich in Kuerze bei Ihnen melden."

TERMINFALL (die Nachricht nennt einen konkreten Tag UND eine konkrete
Uhrzeit als Terminvorschlag):
1. Pruefe im Kalender von Herrn Gruenthaler, ob dieser Tag und diese
   Uhrzeit frei sind.
2. Ist die Zeit frei: trage den Termin in den Kalender ein und bestaetige
   ihn dem Absender, klar als Jarvis, nicht als Herr Gruenthaler selbst.
3. Ist die Zeit NICHT frei: schlage stattdessen zwei andere Uhrzeiten am
   GLEICHEN Tag vor, die genau 1 Stunde auseinander liegen - trage
   nichts ein, bis der Absender einer davon zustimmt.
Schreib in diesem Fall Herrn Gruenthaler zusaetzlich selbst eine kurze
Nachricht, was du dem Absender geantwortet hast - er soll nie ueberrascht
werden von einer automatischen Zusage.

Antworte immer knapp, hoeflich, auf Deutsch.

WICHTIG - Antwortformat: gib GENAU diese zwei Zeilen zurueck, sonst nichts
(keine Anfuehrungszeichen, keine Erklaerungen, kein Markdown):

ANTWORT_AN_ABSENDER: <die Nachricht, die an den Absender geschickt wird>
NOTIZ_AN_LEON: <im Terminfall die kurze Info fuer Herrn Gruenthaler, sonst genau das Wort LEER>`

// Trennt die zwei vom Modell zurueckgegebenen Textteile (Antwort an den
// Absender vs. interne Notiz an Herrn Gruenthaler) - ohne diese Trennung
// landete die interne Notiz versehentlich direkt in der Nachricht an den
// Absender (live beobachtet 2026-09-09: Laura bekam "Termin eingetragen.
// Antwort an Laura folgt." mit in ihrer eigentlichen Antwort zu lesen).
function parseAgentResponse(raw) {
  // Das Modell haelt sich nicht immer exakt ans vorgegebene Format - z.B.
  // wurden die Label schon mit Markdown-Sternchen umschlossen
  // ("**NOTIZ_AN_LEON:**"), was eine striktere Regex zum Scheitern brachte
  // (live beobachtet 2026-09-09: der komplette Rohtext inkl. Notiz landete
  // bei der Absenderin). Deshalb erst Markdown-Betonung entfernen und die
  // Labels nur noch case-insensitiv per Position suchen statt strikt zu
  // parsen.
  const clean = raw.replace(/\*\*/g, '')
  const noteIdx = clean.search(/NOTIZ_AN_LEON:/i)
  const replyPart = noteIdx === -1 ? clean : clean.slice(0, noteIdx)
  const notePart = noteIdx === -1 ? '' : clean.slice(noteIdx).replace(/NOTIZ_AN_LEON:/i, '')
  const reply = replyPart.replace(/ANTWORT_AN_ABSENDER:/i, '').trim()
  const noteRaw = notePart.trim()
  const note = noteRaw && noteRaw.toUpperCase() !== 'LEER' ? noteRaw : null
  return { reply, note }
}

const OPENCLAW_CONFIG_FILE = path.join(homedir(), '.openclaw', 'openclaw.json')

function getGatewayToken() {
  // "openclaw config get gateway.auth.token" maskiert den Wert zu
  // "__OPENCLAW_REDACTED__", sobald es nicht in einem interaktiven Terminal
  // laeuft (live beobachtet 2026-09-09 - genau das hat den ersten
  // Testlauf mit 401 Unauthorized scheitern lassen). Also direkt aus der
  // Config-Datei lesen, wo der Wert im Klartext steht.
  const config = JSON.parse(readFileSync(OPENCLAW_CONFIG_FILE, 'utf8'))
  const token = config?.gateway?.auth?.token
  if (!token) throw new Error(`Kein gateway.auth.token in ${OPENCLAW_CONFIG_FILE} gefunden.`)
  return token
}

function logMessage(entry) {
  appendFileSync(LOG_FILE, JSON.stringify(entry) + '\n')
}

function extractText(message) {
  return (
    message.conversation ||
    message.extendedTextMessage?.text ||
    message.imageMessage?.caption ||
    message.videoMessage?.caption ||
    null
  )
}

async function askJarvis(name, jid, text) {
  const token = getGatewayToken()
  const prompt = `${OPERATING_INSTRUCTIONS}\n\nEingehende WhatsApp-Nachricht von "${name}" (${jid}):\n"${text}"\n\nAntworte jetzt gemaess der obigen Anweisung.`
  const res = await fetch(GATEWAY_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ model: 'openclaw', messages: [{ role: 'user', content: prompt }] }),
  })
  if (!res.ok) {
    throw new Error(`OpenClaw-Gateway antwortete mit ${res.status}: ${await res.text()}`)
  }
  const data = await res.json()
  return (data.choices?.[0]?.message?.content || '').trim()
}

async function handleMessage(sock, msg) {
  if (!msg.message || msg.key.fromMe) return
  const jid = msg.key.remoteJid
  // Direktnachrichten kommen nicht mehr nur als klassische Telefonnummer-JID
  // (@s.whatsapp.net) - WhatsApp adressiert viele Chats inzwischen ueber das
  // neuere, nummernverschleiernde @lid-Schema (live beobachtet 2026-09-09).
  // Gruppen (@g.us) und Broadcasts/Status bleiben weiterhin ausgeschlossen.
  if (!jid || (!jid.endsWith('@s.whatsapp.net') && !jid.endsWith('@lid'))) return

  const ts = (Number(msg.messageTimestamp) || 0) * 1000
  if (ts && ts < STARTED_AT) return // beim Start keinen alten Verlauf erneut beantworten

  const text = extractText(msg.message)
  if (!text) return // Nicht-Text-Nachrichten (Bilder/Sprachnotizen/...) vorerst ignorieren

  const name = msg.pushName || jid
  logMessage({ ts: new Date().toISOString(), direction: 'in', jid, name, text })

  const raw = await askJarvis(name, jid, text)
  if (!raw) return
  const { reply, note } = parseAgentResponse(raw)

  if (reply) {
    await sock.sendMessage(jid, { text: reply })
    logMessage({ ts: new Date().toISOString(), direction: 'out', jid, name, text: reply })
  }

  if (note) {
    // "Nachricht an mich selbst" - dieselbe eigene JID, an die WhatsApp auch
    // den "Nachricht an dich"-Chat adressiert.
    const selfJid = sock.user?.id
    if (selfJid) {
      await sock.sendMessage(selfJid, { text: `[Jarvis - WhatsApp von ${name}]\n${note}` })
      logMessage({ ts: new Date().toISOString(), direction: 'note', jid: selfJid, name, text: note })
    }
  }
}

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR)
  const { version } = await fetchLatestBaileysVersion()
  const sock = makeWASocket({
    version,
    auth: state,
    logger: pino({ level: 'warn' }),
    // Baileys' eigener "init queries"-Schritt (fetchProps: App-Konfiguration
    // von WhatsApp abrufen) lief bei diesem Account zuverlaessig nach genau
    // 60s in ein internes Timeout und riss danach die ganze Verbindung mit
    // ab (live beobachtet 2026-09-09, reproduzierbar bei jedem Verbindungs-
    // aufbau) - fuer reines Senden/Empfangen von Nachrichten wird dieser
    // Schritt nicht gebraucht, siehe WhiskeySockets/Baileys SocketConfig.
    fireInitQueries: false,
  })

  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update
    if (qr) {
      console.log('\nScanne diesen QR-Code mit WhatsApp -> Einstellungen -> Verknuepfte Geraete -> Geraet verknuepfen:\n')
      qrcodeTerminal.generate(qr, { small: true })
    }
    if (connection === 'open') {
      console.log('[jarvis-whatsapp] Verbunden mit WhatsApp.')
    }
    if (connection === 'close') {
      const statusCode = lastDisconnect?.error?.output?.statusCode
      const loggedOut = statusCode === DisconnectReason.loggedOut
      console.log(`[jarvis-whatsapp] Verbindung getrennt (Code ${statusCode}). ${loggedOut ? 'Ausgeloggt - kein Neuversuch, bitte auth-Ordner leeren und neu koppeln.' : 'Versuche erneut zu verbinden...'}`)
      if (!loggedOut) {
        start().catch((err) => console.error('[jarvis-whatsapp] Neuverbindung fehlgeschlagen:', err))
      }
    }
  })

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return
    for (const msg of messages) {
      try {
        await handleMessage(sock, msg)
      } catch (err) {
        console.error('[jarvis-whatsapp] Fehler bei Nachrichtenverarbeitung:', err)
      }
    }
  })
}

start().catch((err) => {
  console.error('[jarvis-whatsapp] Start fehlgeschlagen:', err)
  process.exit(1)
})
