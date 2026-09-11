#!/usr/bin/env node
// Gateway-Aktivitaets-Proxy (2026-09-11) - loest das "operator.read wird fuer Remote-
// WebSocket-Clients verweigert"-Problem (live verifiziert: role "operator" +
// scopes ["operator.read"] funktioniert nur ueber Loopback (127.0.0.1); ueber
// Tailscale/remote antwortet das Gateway mit FORBIDDEN "missing scope: operator.read" -
// echte Remote-Scopes brauchten volles kryptographisches Geraete-Pairing (signierte
// Challenge, v3-Payload), ein eigenes, deutlich groesseres Feature).
//
// Stattdessen: DIESER Proxy laeuft direkt auf dem Mac Mini und haelt EINE dauerhafte
// Loopback-WebSocket-Verbindung zum Gateway (wo operator.read anstandslos funktioniert).
// JarvisApp/JarvisMobile fragen ihn per normalem HTTP (das laeuft ja schon laengst remote
// problemlos, siehe alle anderen scripts/*_proxy_server.py) nach dem aktuellen Live-
// Status einer Session, statt selbst eine WebSocket-Verbindung zum Gateway aufzumachen.
//
// Node statt Python (anders als die anderen Proxys), weil das noetige `ws`-Paket bereits
// fuer whatsapp-bridge installiert ist und Node ueber den Gateway-Handshake-Code schon
// live verifiziert wurde (siehe die Test-Skripte von heute Nacht).

import WebSocket from '../whatsapp-bridge/node_modules/ws/index.js'
import { createServer } from 'node:http'
import { readFileSync, writeFileSync, existsSync, chmodSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { randomBytes } from 'node:crypto'

const PORT = 18795
const TOKEN_FILE = join(homedir(), '.jarvis_gateway_activity_proxy_token')
const GATEWAY_URL = 'ws://127.0.0.1:18789'

function loadOrCreateToken() {
  if (existsSync(TOKEN_FILE)) {
    const existing = readFileSync(TOKEN_FILE, 'utf8').trim()
    if (existing) return existing
  }
  const token = randomBytes(24).toString('hex')
  writeFileSync(TOKEN_FILE, token)
  chmodSync(TOKEN_FILE, 0o600)
  return token
}

function loadGatewayToken() {
  const configPath = join(homedir(), '.openclaw', 'openclaw.json')
  const config = JSON.parse(readFileSync(configPath, 'utf8'))
  return config?.gateway?.auth?.token || ''
}

const TOKEN = loadOrCreateToken()
const GATEWAY_TOKEN = loadGatewayToken()

// sessionKey -> { currentActivity, activeTools: Map<toolCallId, {name,title}>, updatedAt }
const sessionState = new Map()
const subscribedKeys = new Set()

let ws = null
let reqCounter = 0
let connected = false
let connectRequestId = null

function nextId() {
  reqCounter += 1
  return `req-${reqCounter}`
}

function send(method, params) {
  const id = nextId()
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'req', id, method, params }))
  }
  return id
}

function ensureState(key) {
  if (!sessionState.has(key)) {
    sessionState.set(key, { currentActivity: null, activeTools: new Map(), updatedAt: Date.now() })
  }
  return sessionState.get(key)
}

function subscribeIfNeeded(key) {
  if (subscribedKeys.has(key)) return
  subscribedKeys.add(key)
  ensureState(key)
  if (connected) {
    send('sessions.messages.subscribe', { key })
  }
}

function connectGateway() {
  ws = new WebSocket(GATEWAY_URL)

  ws.on('open', () => {
    connectRequestId = send('connect', {
      minProtocol: 4,
      maxProtocol: 4,
      client: { id: 'gateway-client', version: '1.0.0', platform: 'macos', mode: 'backend' },
      role: 'operator',
      scopes: ['operator.read'],
      caps: [],
      auth: { token: GATEWAY_TOKEN },
      locale: 'de-DE',
      userAgent: 'GatewayActivityProxy/1.0',
    })
  })

  ws.on('message', (data) => {
    let json
    try { json = JSON.parse(data.toString()) } catch { return }

    if (json.type === 'res') {
      if (json.id === connectRequestId) {
        if (json.ok) {
          connected = true
          console.log('[gateway-activity-proxy] connected (loopback, operator.read)')
          // Bereits gewuenschte Sessions (waehrend eines Reconnects angefragt) jetzt
          // nachtraeglich abonnieren.
          for (const key of subscribedKeys) send('sessions.messages.subscribe', { key })
        } else {
          console.log('[gateway-activity-proxy] connect FEHLGESCHLAGEN:', JSON.stringify(json))
        }
      }
      return
    }

    if (json.type !== 'event' || !json.event || !json.payload) return
    const { event, payload } = json
    const key = payload.sessionKey
    if (!key || !subscribedKeys.has(key)) return
    const state = ensureState(key)

    if (event === 'session.observer') {
      state.currentActivity = payload.headline || null
      state.updatedAt = Date.now()
    } else if (event === 'agent' && payload.data?.kind === 'tool' && payload.data.toolCallId) {
      const { phase, toolCallId, name, title } = payload.data
      if (phase === 'start') {
        state.activeTools.set(toolCallId, { name: name || 'Werkzeug', title: title || name || 'Werkzeug' })
      } else if (phase === 'end') {
        state.activeTools.delete(toolCallId)
      }
      state.updatedAt = Date.now()
    } else if (event === 'chat' && payload.state === 'final') {
      state.currentActivity = null
      state.activeTools.clear()
      state.updatedAt = Date.now()
    }
  })

  ws.on('close', (code, reason) => {
    connected = false
    console.log(`[gateway-activity-proxy] connection lost (code=${code}, reason=${reason?.toString() || '-'}), retrying in 3s`)
    setTimeout(connectGateway, 3000)
  })

  ws.on('error', (err) => {
    console.log('[gateway-activity-proxy] error:', err.message, err.code || '')
  })
}

connectGateway()

const server = createServer((req, res) => {
  const auth = req.headers['authorization']
  if (auth !== `Bearer ${TOKEN}`) {
    res.writeHead(401, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ error: 'Ungueltiges oder fehlendes Token.' }))
    return
  }

  const url = new URL(req.url, `http://${req.headers.host}`)
  if (url.pathname === '/api/gateway/activity') {
    // .toLowerCase() defensiv, nicht nur auf Client-Seite (RemoteSettings.sessionUser /
    // OpenClawSettings.sessionUser) - OpenClaw legt die Session serverseitig klein
    // geschrieben an, ein Client-seitiger Normalisierungs-Fehler soll hier nicht erneut
    // zu einer nie existierenden Session-Subscription fuehren koennen (2026-09-11,
    // live als Ursache bestaetigt: UUID().uuidString liefert Grossbuchstaben).
    const sessionUser = (url.searchParams.get('sessionUser') || '').toLowerCase()
    if (!sessionUser) {
      res.writeHead(400, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ error: 'sessionUser fehlt.' }))
      return
    }
    const key = `agent:main:openai-user:${sessionUser}`
    subscribeIfNeeded(key)
    const state = ensureState(key)
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' })
    res.end(JSON.stringify({
      connected,
      currentActivity: state.currentActivity,
      activeTools: [...state.activeTools.entries()].map(([id, tool]) => ({ id, ...tool })),
    }))
  } else {
    res.writeHead(404, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ error: 'Unbekannter Pfad.' }))
  }
})

server.listen(PORT, '0.0.0.0', () => {
  console.log(`Jarvis Gateway-Aktivitaets-Proxy laeuft auf 0.0.0.0:${PORT}`)
  console.log(`Token (einmalig in JarvisApp -> Verbindung eintragen): ${TOKEN}`)
})
