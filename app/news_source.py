from __future__ import annotations

import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

"""Reines RSS-Abrufen/Parsen fuer Baustein "Wichtige Nachrichten" (siehe
plans/2026-08-09-jarvis-news-baustein.md) - bewusst analog zu web_search.py
getrennt vom eigentlichen Hintergrund-Worker (news_background_worker.py):
diese Datei kennt kein Caching, keine Threads, keine Klassifikation, nur den
reinen Netzwerk-Abruf + das Parsen in eine einfache Datenstruktur.

Standardquelle CORRECTIV (correctiv.org/feed/) - gemeinnuetzig,
spendenfinanziert, nicht regierungsfinanziert, investigativer Journalismus
(Leons ausdruecklicher Wunsch, siehe Plan). Nutzt die eingebaute
xml.etree.ElementTree statt einer neuen Abhaengigkeit - dieselbe
"keine externe Bibliothek noetig"-Philosophie wie web_search.py's
HTMLParser-basierter DuckDuckGo-Scraper.
"""

CORRECTIV_RSS_URL = "https://correctiv.org/feed/"

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class NewsHeadline:
    id: str
    title: str
    summary: str
    link: str
    published: str


def _clean_summary(raw: str, limit: int = 400) -> str:
    # RSS-Beschreibungen (auch bei CORRECTIV) enthalten haeufig HTML-Markup in
    # einer CDATA-Sektion - fuer eine gesprochene/geschriebene Kurzfassung
    # reicht reiner Text.
    text = _TAG_RE.sub(" ", raw or "")
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return text


def fetch_news_headlines(url: str = CORRECTIV_RSS_URL, max_items: int = 20) -> list[NewsHeadline]:
    """Laedt und parst einen RSS-2.0-Feed. Wirft bei Netzwerk-/Parse-Fehlern eine
    normale Exception weiter - der Aufrufer (NewsBackgroundWorker) faengt das
    ab, damit ein einzelner fehlgeschlagener Check nie den Hintergrund-Thread
    beendet."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
            )
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        raw = response.read()

    root = ET.fromstring(raw)
    items = root.findall("./channel/item")

    headlines: list[NewsHeadline] = []
    for item in items[:max_items]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        summary = _clean_summary(item.findtext("description") or "")
        published = (item.findtext("pubDate") or "").strip()
        if not title or not link:
            continue
        # `link` als ID: RSS-<guid> ist bei manchen Feeds instabil/fehlt, die
        # Artikel-URL ist in der Praxis der zuverlaessigste eindeutige Schluessel.
        headlines.append(NewsHeadline(id=link, title=title, summary=summary, link=link, published=published))
    return headlines
