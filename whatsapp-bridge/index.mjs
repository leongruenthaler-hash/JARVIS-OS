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
import { execSync } from 'node:child_process'
import { appendFileSync, mkdirSync } from 'node:fs'
import { homedir } from 'node:os'
import path from 'node:path'

const DATA_DIR = path.join(homedir(), '.jarvis-whatsapp')
const AUTH_DIR = path.join(DATA_DIR, 'auth')
const LOG_FILE = path.join(DATA_DIR, 'messages.jsonl')
const GATEWAY_URL = 'http://127.0.0.1:18789/v1/chat/completions'

mkdirSync(AUTH_DIR, { recursive: true })

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

Antworte immer knapp, hoeflich, auf Deutsch. Gib NUR den Text zurueck, der
als WhatsApp-Nachricht an den Absender verschickt werden soll - keine
Anfuehrungszeichen, keine Erklaerungen drumherum.`

function getGatewayToken() {
  return execSync('openclaw config get gateway.auth.token', { encoding: 'utf8' }).trim()
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

async function handleMessage(sock, msg, startedAt) {
  if (!msg.message || msg.key.fromMe) return
  const jid = msg.key.remoteJid
  if (!jid || !jid.endsWith('@s.whatsapp.net')) return // nur Direktnachrichten, keine Gruppen/Broadcasts

  const ts = (Number(msg.messageTimestamp) || 0) * 1000
  if (ts && ts < startedAt) return // beim Start keinen alten Verlauf erneut beantworten

  const text = extractText(msg.message)
  if (!text) return // Nicht-Text-Nachrichten (Bilder/Sprachnotizen/...) vorerst ignorieren

  const name = msg.pushName || jid
  logMessage({ ts: new Date().toISOString(), direction: 'in', jid, name, text })

  const reply = await askJarvis(name, jid, text)
  if (!reply) return

  await sock.sendMessage(jid, { text: reply })
  logMessage({ ts: new Date().toISOString(), direction: 'out', jid, name, text: reply })
}

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR)
  const { version } = await fetchLatestBaileysVersion()
  const sock = makeWASocket({ version, auth: state, logger: pino({ level: 'warn' }) })
  const startedAt = Date.now()

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
        await handleMessage(sock, msg, startedAt)
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
