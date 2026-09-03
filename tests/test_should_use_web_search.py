"""Live-Bug 2026-09-03 (50-Nachrichten-Test der Gemini/Claude-Code-Rollenaufteilung):
should_use_web_search()'s current_keywords loeste bei jedem Treffer UNBEDINGT eine
Websuche aus (kein UND mit einem sonstigen Signal noetig) - "gerade" und "modell"/
"modelle" sind aber so gebraeuchliche, kontextfreie Woerter, dass rein interne/
selbstbezogene Fragen wie "antwortest du mir gerade ueber Gemini oder Claude?" eine
sinnlose Websuche ausloesten, deren irrelevante "Suchergebnisse" die eigentliche
Antwort zusaetzlich verwirrten."""

import jarvis


def test_gerade_alone_does_not_trigger_web_search():
    assert jarvis.should_use_web_search("antwortest du mir gerade ueber Gemini oder Claude?") is False


def test_modell_alone_does_not_trigger_web_search():
    assert jarvis.should_use_web_search("welches Modell laeuft da eigentlich im Hintergrund?") is False


def test_genuinely_current_topics_still_trigger_web_search():
    assert jarvis.should_use_web_search("was kostet aktuell ein iPhone 17 Pro?") is True
    assert jarvis.should_use_web_search("wie ist das Wetter heute?") is True
