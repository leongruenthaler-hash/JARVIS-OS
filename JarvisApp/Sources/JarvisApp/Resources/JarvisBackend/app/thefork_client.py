from __future__ import annotations

"""Best-effort Abfrage echter TheFork-Verfuegbarkeit ueber eine per AppleScript
ferngesteuerte, echte Safari-Sitzung - siehe plans/... "Echte TheFork-
Verfuegbarkeit per Safari-Fernsteuerung (experimentell)".

Ein direkter Aufruf von TheForks interner GraphQL-API
(https://www.thefork.de/api/graphql) aus einem normalen Server/Skript wird
sofort mit 403 abgelehnt (live mit curl verifiziert, 2026-08-27) - derselbe
Bot-Schutz wie beim Lieferando-Feature. Eine echte, bereits "vertrauens-
wuerdige" Safari-Sitzung (Leons eigene) kommt dagegen durch, siehe Live-Test
vom selben Tag. Deshalb bewusst KEIN HTTP-Client hier, sondern Safari per
AppleScript fernsteuern - exakt das etablierte Muster aus
contacts_client.py::_run_applescript(), nur mit `do JavaScript` statt
nativer App-Steuerung.

Explizit experimentell und best-effort: jeder Fehlerfall (fehlende
Automation-/Safari-JavaScript-Berechtigung, TheFork blockt doch, Selektoren
haben sich geaendert, Timeout) gibt None zurueck statt zu werfen - der
Aufrufer (jarvis.py::handle_reservation_command) faellt dann still auf die
bisherige "Um wie viel Uhr...?"-Rueckfrage ohne Live-Daten zurueck. Kein
Aufrufer darf durch dieses Feature crashen oder haengen bleiben."""

import json
import subprocess
from typing import Any

_DEFAULT_TIMEOUT_SECONDS = 15.0
_CLEANUP_TIMEOUT_SECONDS = 5.0


def _escape_applescript_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _close_stray_tab(request_url: str) -> None:
    """Best-effort Aufraeumen eines liegen gebliebenen Tabs dieser Anfrage. Das
    Haupt-AppleScript schliesst seinen Tab erst ganz am Ende - bricht
    osascript vorher ab (Timeout, ein "do JavaScript"-Schritt scheitert an
    einem geaenderten Selektor, o.ae.), bleibt der Tab offen stehen (Codex-
    Adversarial-Review 2026-08-27).

    `request_url` ist die VOLLE URL dieser einen Anfrage (Restaurant + Datum +
    Personenzahl als Query-Parameter), nicht nur die Restaurant-Basis-URL -
    eine erste Fassung matchte auf die Basis-URL allein und haette so einen
    eigenen, unabhaengigen Tab treffen koennen, den Leon selbst fuer GENAU
    dieses Restaurant offen hatte (dritter Codex-Review-Fund, 2026-08-27).
    Datum+Personenzahl sind pro Anfrage dynamisch generiert, ein zufaelliger
    Treffer eines fremden Tabs ist damit extrem unwahrscheinlich. "startswith"
    statt exaktem Vergleich, weil TheForks SPA-Routing die URL per
    history.pushState veraendern kann (zweiter Codex-Review-Fund,
    2026-08-27) - vermutlich nur ANHAENGEND, nicht am Anfang, ein exakter
    Vergleich wuerde den Tab dann u.U. nicht mehr finden. Rein kosmetisches
    Aufraeumen - Fehler hier werden komplett verschluckt, kein Sicherheits-/
    Korrektheitsproblem."""
    script = f'''
tell application "Safari"
    repeat with w in windows
        repeat with t in tabs of w
            if URL of t starts with "{_escape_applescript_text(request_url)}" then
                close t
                return
            end if
        end repeat
    end repeat
end tell
'''
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=_CLEANUP_TIMEOUT_SECONDS)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _run_safari_script(script: str, *, timeout: float, request_url: str) -> str | None:
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        # Nur hier ist die URL-basierte Aufraeumung noch noetig: osascript
        # wurde von AUSSEN (Python) abgewuergt, das Skript selbst kam nicht
        # mehr dazu, seinen eigenen try/on-error-Block (siehe unten) mit der
        # ECHTEN Tab-Referenz laufen zu lassen. Jeder andere Fehlerfall wird
        # bereits innerhalb des Skripts mit der praezisen Referenz bereinigt -
        # dieser Pfad bleibt der einzige mit URL-Rate-Risiko (Codex-Review
        # 2026-08-27, P1).
        _close_stray_tab(request_url)
        return None
    except OSError:
        return None
    if result.returncode != 0:
        # Ungleich 0 heisst hier entweder "Safari/Automation liess sich gar
        # nicht erst ansprechen" (kein Tab wurde je erstellt, nichts
        # aufzuraeumen) oder "der interne try/on-error-Block hat bereits mit
        # der echten Tab-Referenz aufgeraeumt und den Fehler weitergereicht" -
        # in beiden Faellen KEIN zusaetzlicher URL-basierter Aufraeum-Versuch,
        # der faelschlich einen unabhaengigen, eigenen Tab von Leon treffen
        # koennte (Codex-Review 2026-08-27, P1).
        return None
    output = result.stdout.strip()
    return output or None


def fetch_available_time_slots(
    restaurant_base_url: str,
    date: str,
    party_size: int,
    *,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
) -> list[str] | None:
    """Liefert eine Liste verfuegbarer Uhrzeiten (z.B. ["18:00", "19:30"]) fuer
    das Restaurant an diesem Datum/dieser Personenzahl, oder None bei jedem
    Fehlschlag (siehe Moduldoc - niemals eine Exception, niemals haengen).
    Oeffnet dafuer kurz einen neuen Safari-Tab, klickt durch das Buchungs-
    Widget und schliesst den Tab wieder - live gegen die echte Seite
    verifiziertes Vorgehen (2026-08-27): "Reservieren"-Button oeffnen, den
    passenden Kalendertag anklicken, dann die gerenderten Uhrzeit-Buttons
    auslesen (Muster HH:MM, `disabled` = nicht mehr verfuegbar).

    Die komplette Funktion laeuft in einem breiten try/except - dieser
    experimentelle, externe UI-Automationspfad darf nie durch einen
    unerwarteten Fehler (z.B. eine kuenftige Aenderung an TheForks Markup,
    die hier noch nicht bedacht wurde) den aufrufenden Chat-Turn zum Absturz
    bringen (Codex-Adversarial-Review 2026-08-27)."""
    try:
        url = f"{restaurant_base_url}?date={date}&partySize={party_size}"
        day_testid = f"calendar-day-{date}"

        # Beide Klick-Skripte geben jetzt explizit 'true'/'false' zurueck, statt
        # unconditional 'true' - vorher lieferte ein NICHT gefundener Button
        # (Seite langsam geladen, Cookie-Overlay blockiert, TheFork hat den
        # Selektor geaendert) trotzdem "Erfolg", und die anschliessende leere
        # Uhrzeit-Liste wurde faelschlich als "echt abgefragt, Tag ausgebucht"
        # missverstanden statt als "Abfrage im Grunde fehlgeschlagen" (Codex-
        # Review 2026-08-27, P1).
        click_reserve_js = (
            "(function(){var b=Array.from(document.querySelectorAll('button'))"
            ".find(function(x){return x.textContent.trim()==='Reservieren';});"
            "if(b){b.click();return 'true';}return 'false';})();"
        )
        click_date_js = (
            "(function(){var el=document.querySelector('[data-testid=\"%s\"]');"
            "if(el){el.click();return 'true';}return 'false';})();" % day_testid
        )
        read_slots_js = (
            "(function(){var btns=Array.from(document.querySelectorAll('button'))"
            ".filter(function(b){return /^\\d{1,2}:\\d{2}$/.test(b.textContent.trim());});"
            "return JSON.stringify(btns.map(function(b){"
            "return {time:b.textContent.trim(), available:!b.disabled};}));})();"
        )

        # try/on error mit der ECHTEN theTab-Referenz statt eines spaeteren,
        # separaten URL-basierten Aufraeum-Versuchs - schliesst bei JEDEM
        # innerhalb des Skripts auftretenden Fehler (Button/Kalendertag nicht
        # gefunden, "do JavaScript" verweigert, ...) exakt den selbst
        # erstellten Tab, nie einen zufaellig aehnlichen, unabhaengigen Tab
        # von Leon (Codex-Review 2026-08-27, P1). Nur ein externer Timeout
        # (osascript wird von Python abgewuergt, bevor dieser Block ueberhaupt
        # fertig laufen kann) bleibt aussen vor - dafuer siehe
        # _close_stray_tab() in _run_safari_script().
        # Nach dem Kalendertag-Klick MEHRFACH (bis zu 2x) erneut lesen, wenn
        # der bisherige Versuch leer war, statt eine leere Liste sofort als
        # "definitiv ausgebucht" zu werten - bei einer langsam ladenden Seite
        # koennten die Uhrzeit-Buttons erst nach mehreren festen
        # 2-Sekunden-Delays erscheinen (eine einzelne feste Wiederholung
        # reichte laut Codex-Review u.U. immer noch nicht, 2026-08-27, dritte
        # Folgerunde) - bewusst weiterhin eine feste, kleine Obergrenze statt
        # unbegrenztem Polling, damit ein echt ausgebuchter Tag nicht
        # unnoetig lange auf sich warten laesst.
        #
        # read_slots_js oben faengt bewusst ALLE Uhrzeit-Buttons ein (auch
        # `disabled`, siehe `available:!b.disabled`), nicht nur die freien -
        # das "[]"-Retry hier ist damit bereits ein "hat das Widget UEBERHAUPT
        # etwas gerendert"-Signal, kein reiner "gibt es freie Zeiten"-Check.
        # Zeigt TheFork an einem ausgebuchten Tag deaktivierte Zeit-Buttons
        # (statt gar keine), unterscheidet dieser Mechanismus "noch am Laden"
        # (leeres Array) sauber von "echt ausgebucht" (nicht-leeres Array,
        # aber alle disabled).
        #
        # BEKANNTE EINSCHRAENKUNG: ein staerkeres, TheFork-markup-spezifisches
        # "fertig geladen"-Signal (z.B. ein expliziter Lade-Indikator) wurde
        # bewusst NICHT gebaut - ein Live-Check dafuer braucht Leons echte,
        # bereits vertrauenswuerdige Safari-Sitzung; ein Test in einer
        # anderen, cookie-losen Browser-Sitzung zeigte hier ein abweichendes,
        # nicht repraesentatives Widget-Verhalten (Kalendertage blieben ohne
        # Leons Session durchgehend disabled, selbst nach Klick auf
        # "Reservieren") und waere keine verlaessliche Grundlage fuer ein
        # spezifisches Markup-Signal gewesen (Codex-Review 2026-08-27, vierte
        # Folgerunde - Live-Verifikationsversuch am selben Tag). Die bewusst
        # gewaehlte, kleine Obergrenze oben ist der proportionale Kompromiss;
        # Leons eigener finaler Klick auf der echten Seite bleibt wie bei der
        # dokumentierten TOCTOU-Einschraenkung das eigentliche
        # Sicherheitsnetz.
        script = f'''
tell application "Safari"
    activate
    set theTab to make new tab at end of tabs of front window with properties {{URL:"{_escape_applescript_text(url)}"}}
    try
        delay 4
        set reserveClicked to (do JavaScript "{_escape_applescript_text(click_reserve_js)}" in theTab)
        if reserveClicked is not "true" then error "Reservieren-Button nicht gefunden"
        delay 2
        set dateClicked to (do JavaScript "{_escape_applescript_text(click_date_js)}" in theTab)
        if dateClicked is not "true" then error "Kalendertag nicht gefunden"
        delay 2
        set slotsJson to (do JavaScript "{_escape_applescript_text(read_slots_js)}" in theTab)
        repeat 2 times
            if slotsJson is not "[]" then exit repeat
            delay 2
            set slotsJson to (do JavaScript "{_escape_applescript_text(read_slots_js)}" in theTab)
        end repeat
        close theTab
        return slotsJson
    on error errMsg
        close theTab
        error errMsg
    end try
end tell
'''

        raw = _run_safari_script(script, timeout=timeout, request_url=url)
        if raw is None:
            return None
        try:
            data: Any = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, list):
            return None

        times: list[str] = []
        for entry in data:
            if isinstance(entry, dict) and entry.get("available") is True and isinstance(entry.get("time"), str):
                times.append(entry["time"])
        return times
    except Exception:
        return None
