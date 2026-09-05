from __future__ import annotations

"""Periodischer Hintergrund-Antrieb fuer die Proaktivitaet (Phase 4, Plan
"Jarvis proaktiv machen", 2026-09-05). Vorher wertete lediglich
GET /api/proactivity/events das aus, aufgerufen von AppState.
startProactivityPollingLoop() alle 5 Minuten - NUR solange die Mac-App offen war
(siehe docs/proactivity.md). Auf dem Mac Mini als 24/7-Server soll sich Jarvis
aber auch melden, wenn keine Mac-App laeuft. Gleiches Muster wie
background_tasks.py::MailBackgroundWorker: threading.Event-Stop-Flag +
_run_loop() mit stop_event.wait(N).

Ruft bewusst eine vom Aufrufer uebergebene Funktion auf (typischerweise
JarvisLocalServer.proactivity_events()), NICHT PROACTIVITY_ENGINE.evaluate()
direkt - proactivity_events() hat einen Nebeneffekt (Befuellen von
settings["pending_mail_calendar_confirmation"] fuer per Chat bestaetigbare
Kalender-Vorschlaege), den ein selbstgebauter Kontext hier verpassen wuerde."""

import threading
from typing import Any, Callable

DEFAULT_INTERVAL_SECONDS = 300


class ProactivityScheduler:
    def __init__(
        self,
        config: dict[str, Any],
        tick: Callable[[], Any],
        interval_seconds: int | None = None,
    ):
        self.config = config
        self.tick = tick
        self.enabled = bool(config.get("proactivity_enabled", True))
        self.interval_seconds = int(
            interval_seconds
            if interval_seconds is not None
            else config.get("proactivity_scheduler_interval_seconds", DEFAULT_INTERVAL_SECONDS)
        )
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled or self.interval_seconds <= 0:
            return
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _run_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:
                # Ein einzelner fehlgeschlagener Zyklus (z.B. ein kurzzeitig
                # nicht erreichbarer Datenzugriff) darf den Scheduler nie dauerhaft
                # beenden - gleiches Prinzip wie die Regel-Fehlerbehandlung in
                # ProactivityEngine.evaluate().
                print(f"Proaktivitaets-Scheduler Fehler: {type(exc).__name__}")
            self.stop_event.wait(self.interval_seconds)
