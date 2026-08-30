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
import time
from datetime import datetime, timedelta
from typing import Any

_DEFAULT_TIMEOUT_SECONDS = 15.0
_CLEANUP_TIMEOUT_SECONDS = 5.0
_DEFAULT_SCAN_DAYS = 7
_DEFAULT_SCAN_TIMEOUT_PER_DAY_SECONDS = 10.0
_DEFAULT_SCAN_MAX_TOTAL_SECONDS = 30.0


def _escape_applescript_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _close_stray_tab(request_url: str) -> None:
    """Best-effort Aufraeumen eines liegen gebliebenen Tabs dieser Anfrage. Das
    Haupt-AppleScript schliesst seinen Tab erst ganz am Ende - bricht
    osascript vorher ab (Timeout, ein "do JavaScript"-Schritt scheitert an
    einem geaenderten Selektor, o.ae.), bleibt der Tab offen stehen (Codex-
    Adversarial-Review 2026-08-27).

    `request_url` ist die VOLLE URL dieser einen Anfrage (Restaurant-Basis-URL
    plus Datum/Personenzahl als Hash-Fragment), nicht nur die Restaurant-
    Basis-URL allein -
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

    Oeffnet dafuer kurz einen neuen Safari-Tab direkt mit einer URL, die
    Datum und Personenzahl als Hash-Fragment traegt (z.B.
    "...#booking=&date=2026-09-14&partySize=2") - live verifiziert
    (2026-08-30): TheForks Buchungswidget liest diesen Hash beim initialen
    Laden der Seite und zeigt danach direkt die passenden Uhrzeit-Buttons,
    OHNE dass irgendein Klick simuliert werden muss. Query-Parameter
    (?date=...) haben dagegen live verifiziert KEINE Wirkung - eine fruehere
    Fassung dieser Funktion nutzte sie faelschlich zusammen mit einem
    Klick auf einen "calendar-day-{date}"-Testid, den es auf der echten
    Seite nicht (mehr) gibt; die Abfrage schlug dadurch seit einer
    TheFork-Aenderung nach dem 2026-08-27-Review still IMMER fehl (nie
    bemerkt, weil genau das der eingebaute Fallback ist). Die
    Uhrzeit-Buttons selbst tragen ein stabiles
    `data-testid="timeslot-HH:MM"` (bzw. "timeslot-service-lunch"/
    "timeslot-service-diner" fuer die beiden Abschnittsueberschriften, die
    hier explizit herausgefiltert werden).

    Die komplette Funktion laeuft in einem breiten try/except - dieser
    experimentelle, externe UI-Automationspfad darf nie durch einen
    unerwarteten Fehler (z.B. eine kuenftige Aenderung an TheForks Markup,
    die hier noch nicht bedacht wurde) den aufrufenden Chat-Turn zum Absturz
    bringen (Codex-Adversarial-Review 2026-08-27)."""
    try:
        url = f"{restaurant_base_url}#booking=&date={date}&partySize={party_size}"

        # Neuer Tab mit dieser URL ist ein ECHTER, frischer Seitenaufbau (kein
        # blosser Hash-Wechsel auf einer bereits offenen Seite) - genau das
        # ist entscheidend, damit TheForks Widget den Hash beim Mounten liest.
        # Ein blosser Hash-Wechsel auf einer schon geladenen Seite (z.B. per
        # "set URL of theTab" auf einen bereits offenen Tab) wuerde vom
        # Browser als reine In-Page-Navigation behandelt und vom Widget NICHT
        # neu ausgewertet (live verifiziert 2026-08-30) - deshalb hier bewusst
        # immer ein neuer Tab statt Wiederverwendung.
        # "ready" ist das vom Codex-Review geforderte Unterscheidungssignal
        # (2026-08-30, P2/P1 ueber zwei Runden verschaerft): eine erste
        # Fassung zaehlte dafuer JEDES "[data-testid^='timeslot-']"-Element,
        # auch die beiden Abschnittsueberschriften "timeslot-service-lunch"/
        # "timeslot-service-diner" - die rendern aber live verifiziert schon
        # SOFORT beim Mounten, BEVOR TheForks asynchrone
        # Verfuegbarkeitsabfrage fuer dieses Datum ueberhaupt fertig ist. Das
        # haette den gerade erst behobenen Fehler nur verschoben: ein noch
        # ladendes Widget haette sofort "ready:true" mit leerer Zeiten-Liste
        # gemeldet - exakt wie ein echt ausgebuchter Tag (Codex-Review
        # 2026-08-30, zweite Runde, P1). "ready" haengt deshalb jetzt
        # ausschliesslich an ECHTEN Uhrzeit-Buttons (Muster HH:MM) - die
        # koennen erst erscheinen, NACHDEM die Verfuegbarkeitsdaten geladen
        # sind.
        #
        # Live nachgetragen (2026-08-30, gegen ein echtes Restaurant ohne
        # Online-Verfuegbarkeit getestet, "Nobless"/Maxhuette-Haidhof): TheFork
        # hat doch ein explizites Signal, wenn fuer ein Restaurant/Datum gar
        # keine Online-Verfuegbarkeit hinterlegt ist - ein Element mit
        # `data-testid="booking-widget-no-availability-message"` und dem Text
        # "Leider ist für das Restaurant derzeit keine Verfügbarkeit
        # angegeben". "noAvailability" wird separat mitgegeben (statt es wie
        # eine erste Fassung direkt auf eine leere Zeiten-Liste abzubilden) -
        # Codex-Review 2026-08-30, P2: "keine Online-Verfuegbarkeitspruefung
        # moeglich" ist NICHT dasselbe wie "an diesem Tag alles ausgebucht"
        # (die Uhrzeit-Buttons wuerden dann trotzdem gerendert, nur alle
        # `available:false`) - eine telefonische Reservierung koennte trotzdem
        # moeglich sein. Der Aufrufer (siehe unten) behandelt "noAvailability"
        # deshalb wie einen Abfrage-Fehlschlag (None), nicht wie "definitiv
        # nichts frei" ([]) - der einzige Nutzen dieses Signals ist, die
        # sinnlosen Retries zu ueberspringen, wenn das Ergebnis schon feststeht
        # (kuerzere Latenz), NICHT eine positive "ausgebucht"-Aussage.
        read_slots_js = (
            "(function(){var btns=Array.from(document.querySelectorAll('[data-testid^=\"timeslot-\"]'));"
            "var real=btns.filter(function(b){return /^timeslot-\\d{1,2}:\\d{2}$/.test(b.getAttribute('data-testid'));});"
            "var noAvail=!!document.querySelector('[data-testid=\"booking-widget-no-availability-message\"]');"
            "return JSON.stringify({ready:real.length>0||noAvail, noAvailability:noAvail, slots:real.map(function(b){"
            "var t=b.getAttribute('data-testid').slice('timeslot-'.length);"
            "var avail=!b.disabled&&b.getAttribute('aria-disabled')!=='true';"
            "return {time:t, available:avail};})});})();"
        )

        # try/on error mit der ECHTEN theTab-Referenz statt eines spaeteren,
        # separaten URL-basierten Aufraeum-Versuchs - schliesst bei JEDEM
        # innerhalb des Skripts auftretenden Fehler (z.B. "do JavaScript"
        # verweigert) exakt den selbst erstellten Tab, nie einen zufaellig
        # aehnlichen, unabhaengigen Tab von Leon (Codex-Review 2026-08-27,
        # P1). Nur ein externer Timeout (osascript wird von Python
        # abgewuergt, bevor dieser Block ueberhaupt fertig laufen kann)
        # bleibt aussen vor - dafuer siehe _close_stray_tab() in
        # _run_safari_script().
        #
        # MEHRFACH (bis zu 2x) erneut lesen, wenn "ready" noch false ist,
        # statt sofort aufzugeben - bei einer langsam ladenden Seite/
        # Verfuegbarkeitsabfrage koennen die echten Uhrzeit-Buttons erst nach
        # mehreren festen 2-Sekunden-Delays erscheinen. Ein Tag mit
        # "ready:true" hat per Definition (siehe read_slots_js) IMMER
        # mindestens einen echten Uhrzeit-Button geliefert bekommen und
        # bricht dadurch sofort ab, statt unnoetig weiter zu warten; ein Tag,
        # der auch nach allen Retries "ready:false" bleibt, gilt als
        # Abfrage-Fehlschlag (siehe bekannte Einschraenkung oben), nicht als
        # "sicher ausgebucht".
        script = f'''
tell application "Safari"
    activate
    set theTab to make new tab at end of tabs of front window with properties {{URL:"{_escape_applescript_text(url)}"}}
    try
        delay 4
        set slotsJson to (do JavaScript "{_escape_applescript_text(read_slots_js)}" in theTab)
        repeat 2 times
            if slotsJson contains "\\"ready\\":true" then exit repeat
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
        if not isinstance(data, dict) or data.get("ready") is not True:
            # Kein einziger echter Uhrzeit-Button ist trotz der Retries
            # erschienen - entweder ist das Widget nie gemountet (Hash
            # ignoriert, Seite blockiert, Cookie-Overlay, geaendertes Markup)
            # oder die Verfuegbarkeitsdaten waren noch nicht fertig geladen.
            # Beides ist ein Abfrage-Fehlschlag, KEIN bestaetigtes "an diesem
            # Tag ist nichts frei" (siehe bekannte Einschraenkung in der
            # read_slots_js-Doku oben). None loest beim Aufrufer die
            # bisherige, datenlose Rueckfrage aus statt eine falsche
            # "ausgebucht"-Aussage zu treffen (Codex-Review 2026-08-30, zwei
            # Runden).
            return None
        if data.get("noAvailability") is True:
            # TheFork bietet fuer dieses Restaurant/Datum ueberhaupt KEINE
            # Online-Verfuegbarkeitspruefung an (z.B. nur telefonische
            # Reservierung) - live entdeckt bei "Nobless"/Maxhuette-Haidhof.
            # Das ist NICHT dasselbe wie "echt ausgebucht" (dort wuerden
            # Uhrzeit-Buttons gerendert, nur alle `available:false`) - eine
            # leere Liste wuerde der Aufrufer als bestaetigtes "nichts frei"
            # missverstehen und den Tag ablehnen, obwohl telefonisch u.U.
            # noch etwas moeglich ist. None behandelt diesen Fall deshalb wie
            # einen Abfrage-Fehlschlag (bisherige, datenlose Rueckfrage) -
            # der einzige Zweck des "noAvailability"-Signals ist, die
            # sinnlosen Retries in read_slots_js zu ueberspringen (kuerzere
            # Latenz), NICHT eine positive "ausgebucht"-Aussage zu treffen
            # (Codex-Review 2026-08-30, P2).
            return None
        slots = data.get("slots")
        if not isinstance(slots, list):
            return None

        times: list[str] = []
        for entry in slots:
            if isinstance(entry, dict) and entry.get("available") is True and isinstance(entry.get("time"), str):
                times.append(entry["time"])
        return times
    except Exception:
        return None


def find_available_dates(
    restaurant_base_url: str,
    start_date: str,
    party_size: int,
    *,
    num_days: int = _DEFAULT_SCAN_DAYS,
    timeout_per_day: float = _DEFAULT_SCAN_TIMEOUT_PER_DAY_SECONDS,
    max_total_seconds: float = _DEFAULT_SCAN_MAX_TOTAL_SECONDS,
) -> list[dict] | None:
    """Prueft bis zu `num_days` aufeinanderfolgende Tage AB EINSCHLIESSLICH
    `start_date` (Format "YYYY-MM-DD") und liefert eine Liste
    `[{"date": "YYYY-MM-DD", "times": [...]}, ...]` fuer jeden Tag mit
    mindestens einer freien Uhrzeit - oder None, wenn KEIN einziger Tag
    erfolgreich abgefragt werden konnte (z.B. fehlende Safari-Berechtigung,
    Timeout bei jedem Versuch). Ein Tag ohne freie Zeit taucht einfach nicht
    in der Liste auf; eine leere Liste heisst "alle Tage wurden erfolgreich
    geprueft, aber keiner hatte etwas frei" - ein ANDERER Fall als None
    (komplett fehlgeschlagene Abfrage), analog zur "is not None"-
    Unterscheidung von fetch_available_time_slots() selbst.

    Ruft dafuer fetch_available_time_slots() sequenziell fuer jeden Tag auf
    (kein paralleles Oeffnen mehrerer Safari-Tabs - das wuerde Leons eigene
    Safari-Sitzung mit mehreren gleichzeitigen Tabs ueberladen und das
    Tab-Aufraeumen in _run_safari_script() verkomplizieren).

    HARTES ZEITBUDGET (Codex-Review 2026-08-30, P1): der aufrufende Chat-
    Client (`JarvisAPIClient.sendChat`) hat ein 60-Sekunden-Request-Timeout.
    7 sequenzielle Tage mit dem Standard-15s-Timeout von
    fetch_available_time_slots() haetten im Worst Case (jede Abfrage laeuft
    komplett in den Timeout) ca. 64+ Sekunden gebraucht - genug, um dieses
    Client-Timeout zu reissen, WAEHREND genau der langsame Fall vorlag, den
    dieses Feature eigentlich abfedern sollte (der Nutzer haette dann gar
    keine Antwort bekommen, nicht mal den dokumentierten Fallback). Deshalb:
    ein knapperer Timeout pro Tag (Standard 10s statt 15s) UND ein
    Gesamt-Zeitbudget (Standard 30s). Vor jedem weiteren Tag (ab dem
    zweiten) wird das VERBLEIBENDE Budget berechnet und der fuer DIESEN Tag
    erlaubte Timeout darauf gedeckelt - abzueglich `_CLEANUP_TIMEOUT_SECONDS`
    (Codex-Review 2026-08-30, zweite Runde, P1): fetch_available_time_slots()
    kann bei einem echten externen Timeout zusaetzlich bis zu
    `_CLEANUP_TIMEOUT_SECONDS` in _close_stray_tab() verbringen - eine erste
    Fassung dieses Zeitbudgets uebersah das und haette im Worst Case (Aufruf
    startet knapp vor Budget-Ende, laeuft dann trotzdem in den vollen
    Timeout+Cleanup) das Gesamtbudget spuerbar reissen koennen. Reicht das
    verbleibende Budget nicht mal fuer die Cleanup-Zeit, bricht der Scan
    sofort ab, statt einen praktisch nutzlosen Mini-Timeout-Aufruf zu
    versuchen. Der ERSTE Tag (offset 0) laeuft immer mit dem vollen
    `timeout_per_day` (das Budget beginnt erst danach zu wirken) - der reale
    Worst Case fuer den GESAMTEN Scan liegt damit bei
    `max(timeout_per_day + _CLEANUP_TIMEOUT_SECONDS, max_total_seconds)`
    (Standard: 30s), zusammen mit dem vorherigen Einzel-Check (worst case
    `_DEFAULT_TIMEOUT_SECONDS + _CLEANUP_TIMEOUT_SECONDS` = 20s) komfortabel
    unter den 60s des Chat-Clients.

    Ein einzelner fehlgeschlagener Tag (fetch_available_time_slots()
    liefert None fuer diesen einen Tag, z.B. TheFork zeigt fuer DIESEN Tag
    kurzzeitig einen Ladefehler) bricht den gesamten Scan NICHT ab - der
    Tag wird einfach uebersprungen, die uebrigen Tage werden trotzdem
    geprueft (best-effort, siehe Moduldoc)."""
    try:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            return None
        results: list[dict] = []
        any_successful_check = False
        scan_started_at = time.monotonic()
        for offset in range(num_days):
            day_timeout = timeout_per_day
            if offset > 0:
                remaining = max_total_seconds - (time.monotonic() - scan_started_at)
                if remaining <= _CLEANUP_TIMEOUT_SECONDS:
                    break
                day_timeout = min(timeout_per_day, remaining - _CLEANUP_TIMEOUT_SECONDS)
            day = (start + timedelta(days=offset)).strftime("%Y-%m-%d")
            slots = fetch_available_time_slots(restaurant_base_url, day, party_size, timeout=day_timeout)
            if slots is None:
                continue
            any_successful_check = True
            if slots:
                results.append({"date": day, "times": slots})
        if not any_successful_check:
            return None
        return results
    except Exception:
        return None
